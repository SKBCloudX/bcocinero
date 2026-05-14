import os
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button, DataTable, Input, Select, Label, ProgressBar, Static
)
from bcocinero.nm_helpers import (
    NetworkManager,
    ArtifactManager,
    InventoryGenerator
)
from bcocinero.db import BcocineroDB
from bcocinero.prep import Prep

nm = NetworkManager()
am = ArtifactManager()

_RECIPE = "recipe.yml"
_RECIPE_VARS = "recipe_vars.yml"
_RECIPE_SAVED = ".recipe.yml"

class ListHost(Widget):
    l_host_header = ["Name", "IP", "Role", "State"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db_hostdata = []
        self.logger = logging.getLogger("bcocinero")

    def compose(self) -> ComposeResult:
        yield DataTable(id="host_table", zebra_stripes=True, fixed_rows=1)

    def on_mount(self) -> None:
        table = self.query_one("#host_table", DataTable)
        table.add_columns(*self.l_host_header)
        self.refresh_table()

    def refresh_table(self) -> None:
        table = self.query_one("#host_table", DataTable)
        table.clear()
        hostinfo = nm.get_host_info()
        ip = hostinfo.get("mgmt_ip")
        if not ip:
            return
        db = BcocineroDB(urls=[f"{ip}:4001"])
        self.db_hostdata = db.get_all_hosts()
        l_host_data = [tuple(d.values()) for d in self.db_hostdata]
        for row in l_host_data:
            table.add_row(*row)

    def create_inventory(self, install_root_dir) -> None:
        if not self.db_hostdata:
            self.logger.error("No host data available to create inventory.")
            return

        gen = InventoryGenerator(self.db_hostdata)
        gen.generate(f"{install_root_dir}/hosts")
        self.logger.info(
            f"Created an inventory file: {install_root_dir}/hosts"
        )

class RecipeModal(ModalScreen[dict]):
    def __init__(self, recipe_path: str, recipe_saved_path: str):
        super().__init__()
        self.recipe_path = recipe_path
        self.recipe_saved_path = recipe_saved_path
        self.recipe_data = {}
        self.widgets = {}
        self.load_error = None

        self._load_recipe()

    def _load_recipe(self) -> None:
        target_path = self.recipe_path
        if os.path.exists(self.recipe_saved_path):
            target_path = self.recipe_saved_path
        elif not os.path.exists(self.recipe_path):
            self.load_error = f"Error: '{self.recipe_path}' not found."
            return

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data or "variable" not in data:
                    s_msg = "Error: Invalid format. 'variable' key is missing"
                    self.load_error = s_msg
                    return
                self.recipe_data = data["variable"]
        except yaml.YAMLError as e:
            self.load_error = f"Error parsing YAML: {e}"
        except Exception as e:
            self.load_error = f"Error: {e}"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="modal-dialog"):
            if self.load_error:
                yield Label(self.load_error, id="error-message")
                with Horizontal(id="error-buttons"):
                    yield Button("Close", variant="error", id="cancel-btn")
                return

            yield Label(self.recipe_data.get("title"), id="recipe-title")
            with VerticalScroll(id="form-body"):
                for field in self.recipe_data.get("fields", []):
                    yield Label(field["label"], classes="label-fixed")

                    if field["type"] == "input":
                        input_widget = Input(
                            placeholder=field.get("placeholder", ""),
                            value=str(field.get("default", "")),
                            id=field["name"]
                        )
                        self.widgets[field["name"]] = input_widget
                        yield input_widget
                    elif field["type"] == "select":
                        select_options = [
                            (opt[0], opt[1]) for opt in field.get("options", [])
                        ]
                        select_widget = Select(
                            options=select_options,
                            value=field.get("default", Select.NULL),
                            id=field["name"],
                            allow_blank=False,
                            type_to_search=True
                        )
                        self.widgets[field["name"]] = select_widget
                        yield select_widget
            with Horizontal(id="modal-buttons"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            result_data = {
                name: widget.value for name, widget in self.widgets.items()
            }
            self.dismiss(result_data)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)
            
class Installer(VerticalScroll):
    def __init__(self):
        super().__init__()
        self.install_root_dir = am.get_install_root()
        self.modal_screen = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hosts-refresh":
            self.query_one(ListHost).refresh_table()
        if event.button.id == "installer-prepare":
            self.run_prep_task()
        if event.button.id == "installer-recipe":
            if not self.install_root_dir:
                s_msg = "Cannot find install root directory. Did you run Prep?"
                logging.error(s_msg)
                return
            recipe_file_path = f"{self.install_root_dir}/{_RECIPE}"
            recipe_saved_path = f"{self.install_root_dir}/{_RECIPE_SAVED}"
            self.modal_screen = RecipeModal(
                recipe_file_path,
                recipe_saved_path
            )
            self.app.push_screen(self.modal_screen, self.handle_save_recipe)

    def handle_save_recipe(self, data: Optional[Dict]) -> None:
        if not data:
            logging.info("Recipe configuration is cancelled.")
            return

        s_recipe_vars = f"{self.install_root_dir}/{_RECIPE_VARS}"
        s_recipe_saved = f"{self.install_root_dir}/{_RECIPE_SAVED}"

        b_ret_vars, msg_vars = self.save_recipe_vars(s_recipe_vars, data)
        if b_ret_vars:
            logging.info(f"{_RECIPE_VARS} is saved.")
        else:
            logging.error(f"Fail to save {_RECIPE_VARS}: {msg_vars}")

        b_ret_saved, msg_saved = self.save_recipe_saved(s_recipe_saved, data)
        if b_ret_vars:
            logging.info(f"{_RECIPE_SAVED} is saved.")
        else:
            logging.error(f"Fail to save {_RECIPE_SAVED}: {msg_saved}")

    def save_recipe_vars(self,
            filepath: str, data_to_save: dict) -> Tuple[bool, str]:
        processed_data = data_to_save.copy()
        cur_val = processed_data["storage_backends"]
        processed_data["storage_backends"] = [cur_val]
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    processed_data, f, allow_unicode=True, sort_keys=False
                )
            return (True, "Succeed")
        except OSError as e:
            return (False, e.strerror)
        except Exception as e:
            return (False, str(e))

    def save_recipe_saved(self, filepath: str, data_to_save: dict) -> Tuple:
        if not self.modal_screen or not self.modal_screen.recipe_data:
            return (False, "No recipe data")
        try:
            output_data = {
                "variable": {
                    "title": self.modal_screen.recipe_data.get(
                                "title", "Global Configuration"
                    ),
                    "fields": []
                }
            }

            for field in self.modal_screen.recipe_data.get("fields", []):
                field_copy = field.copy()
                name = field["name"]
                if name in data_to_save:
                    field_copy["default"] = data_to_save[name]
                output_data["variable"]["fields"].append(field_copy)

            with open(filepath, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    output_data, f, allow_unicode=True, sort_keys=False
                )
            return (True, "Succeed")
        except OSError as e:
            return (False, e.strerror)
        except Exception as e:
            return (False, str(e))

    @work(exclusive=True, thread=True)
    async def run_prep_task(self) -> None:
        btn = self.query_one("#installer-prepare", Button)
        bar = self.query_one("#prep-progress", ProgressBar)
        status = self.query_one("#prep-status", Static)

        btn.disabled = True
        bar.progress = 0

        try:
            prep_engine = Prep()
            for progress, message in prep_engine.run_prep_gen():
                bar.progress = progress
                status.update(f"[cyan]{message}[/]")
            self.query_one(ListHost).create_inventory(
                prep_engine.install_root_dir
            )
            am.save_install_root_file(f"{prep_engine.install_root_dir}")
            logging.info("Prep process is completed successfully.")
        except Exception as e:
            status.update(f"[bold red]{str(e)}[/]")
        finally:
            btn.disabled = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Hosts", classes="title")
            yield Button(label="Refresh", id="hosts-refresh",
                         variant="primary")
            yield Button(label="Inventory", id="inventory-view",
                         variant="primary")
        yield ListHost(id="host_list_widget")
        yield Label("Installer", classes="title")
        with Horizontal(id="installer_block"):
            yield Button(label="Prep", id="installer-prepare",
                         variant="primary")
            yield Button(label="Recipe", id="installer-recipe",
                         variant="primary")
        yield Static("", id="prep-status")
        yield ProgressBar(id="prep-progress", total=1.0, show_bar=True)

