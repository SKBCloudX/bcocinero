import os
import yaml
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
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
from bcocinero.vault import VaultManager

nm = NetworkManager()
am = ArtifactManager()

_RECIPE = "recipe.yml"
_RECIPE_VARS = "recipe_vars.yml"
_RECIPE_SAVED = ".recipe.yml"

class QuotedStr(str):
    pass

def quoted_str_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='"')

yaml.SafeDumper.add_representer(QuotedStr, quoted_str_representer)
yaml.Dumper.add_representer(QuotedStr, quoted_str_representer)

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
                    is_netapp = field["name"].startswith("netapp_")
                    row_classes = (
                        "form-row netapp-field" if is_netapp else "form-row"
                    )
                    with Horizontal(classes=row_classes):
                        yield Label(field["label"], classes="label-fixed")
                        if field["type"] in ("input", "password"):
                            input_widget = Input(
                                placeholder=field.get("placeholder", ""),
                                password=(field["type"] == "password"),
                                value=str(field.get("default", "")),
                                id=field["name"]
                            )
                            self.widgets[field["name"]] = input_widget
                            yield input_widget
                        elif field["type"] == "select":
                            select_options = [
                                (opt[0], opt[1]) for opt in field["options"]
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

    def on_mount(self) -> None:
        select_widget = self.widgets.get("storage_backends")
        if select_widget:
            self._toggle_netapp_fields(select_widget.value)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "storage_backends":
            self._toggle_netapp_fields(event.value)

    def _toggle_netapp_fields(self, backend_value: str) -> None:
        show_netapp = (backend_value == "netapp")
        for row in self.query(".netapp-field"):
            row.styles.display = "block" if show_netapp else "none"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            raw = {
                name: widget.value for name, widget in self.widgets.items()
            }
            result = {
                k: v for k, v in raw.items() if not k.startswith("netapp_")
            }
            if raw.get("storage_backends") == "netapp":
                q_transport = QuotedStr("{{ netapp_transport_type }}")
                q_password = QuotedStr(raw.get("netapp_pass", ""))
                q_nfsopts = QuotedStr("{{ netapp_nfs_mount_options }}")
                result["netapp_tmpl"] = [
                    {
                        "name": "netapp",
                        "managementLIF": raw.get("netapp_mgmt_lif", ""),
                        "dataLIF": raw.get("netapp_data_lif1", ""),
                        "transportType": q_transport,
                        "svm1": raw.get("netapp_svm1", ""),
                        "username": raw.get("netapp_user", ""),
                        "password": q_password,
                        "nfsMountOptions": q_nfsopts,
                        "shares": [raw.get("netapp_shares1", "")]
                    },
                    {
                        "name": "netapp2",
                        "managementLIF": raw.get("netapp_mgmt_lif", ""),
                        "dataLIF": raw.get("netapp_data_lif2", ""),
                        "transportType": q_transport,
                        "svm2": raw.get("netapp_svm2", ""),
                        "username": raw.get("netapp_user", ""),
                        "password": q_password,
                        "nfsMountOptions": q_nfsopts,
                        "shares": [raw.get("netapp_shares2", "")]
                    }
                ]
            self.dismiss(result)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

class VaultModal(ModalScreen[dict]):
    def __init__(self):
        super().__init__()
        self.widgets = {}

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="vault-modal-dialog"):
            yield Label("Vault (Secret Cabinet) Config", id="vault-title")
            with VerticalScroll():
                fields = [
                    {"label": "User Password",
                     "name": "user_pass",
                     "placeholder": "Enter clex user password."},
                    {"label": "OpenStack Admin Password",
                     "name": "os_admin_pass",
                     "placeholder": "Enter OpenStack admin password."}
                ]
                for field in fields:
                    with Horizontal():
                        yield Label(field["label"], classes="label-fixed")
                        input_widget = Input(
                            placeholder=field["placeholder"],
                            password=True,
                            id=field["name"]
                        )
                        self.widgets[field["name"]] = input_widget
                        yield input_widget
            with Horizontal(id="vault-modal-buttons"):
                yield Button("Save", variant="primary", id="vault-save-btn")
                yield Button("Cancel", variant="error", id="vault-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "vault-save-btn":
            result = {
                name: widget.value for name, widget in self.widgets.items()
            }
            if not result["user_pass"] or not result["os_admin_pass"]:
                return
            self.dismiss(result)
        elif event.button.id == "vault-cancel-btn":
            self.dismiss(None)


class Installer(VerticalScroll):
    def __init__(self):
        super().__init__()
        self.install_root_dir = am.get_install_root()
        self.home_dir = Path(self.install_root_dir).parent
        self.modal_screen = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hosts-refresh":
            self.query_one(ListHost).refresh_table()
        if event.button.id == "installer-prep":
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
        if event.button.id == "installer-vault":
            if not self.install_root_dir:
                s_msg = "Cannot find install root directory. Did you run Prep?"
                logging.error(s_msg)
                return
            self.modal_screen = VaultModal()
            self.app.push_screen(self.modal_screen, self.handle_save_vault)

    @work(exclusive=True, thread=True)
    async def run_prep_task(self) -> None:
        btn = self.query_one("#installer-prep", Button)
        bar = self.query_one("#prep-progress", ProgressBar)
        status = self.query_one("#prep-status", Static)

        self.app.call_from_thread(self._init_ui, btn, bar)

        try:
            prep_engine = Prep()
            for progress, message in prep_engine.run_prep_gen():
                self.app.call_from_thread(self._update_progress,
                    bar, status, progress, message)
            self.query_one(ListHost).create_inventory(
                prep_engine.install_root_dir
            )
            am.save_install_root_file(f"{prep_engine.install_root_dir}")
            logging.info("Prep process is completed successfully.")
            self.app.call_from_thread(
                self._complete_progress_tracker, btn, is_success=True)
        except Exception as e:
            logging.error(f"Error during prep: {e}")
            self.app.call_from_thread(status.update, f"[bold red]{str(e)}[/]")
            self.app.call_from_thread(
                self._update_button, btn, variant="error")

    def _init_ui(self, btn: Button, bar: Optional[ProgressBar] = None) -> None:
        btn.disabled = True

        if bar is not None:
            bar.progress = 0

    def _update_progress(self,
                         bar: ProgressBar, status: Static,
                         progress: float, message: str) -> None:
        bar.progress = progress
        status.update(f"[cyan]{message}[/]")

    def _update_button(self, btn: Button, variant: str = "default") -> None:
        orig_name = btn.id.split("-", 1)[-1]
        if variant == "success":
            btn.label = f"{orig_name}[bold green](P)[/]"
        elif variant == "error":
            btn.label = f"{orig_name}[bold red](F)[/]"
        else:
            btn.label = orig_name
        btn.variant = variant
        btn.disabled = False
        btn.refresh(layout=True)

    def handle_save_recipe(self, data: Optional[Dict]) -> None:
        if not data:
            logging.info("Recipe configuration is cancelled.")
            return

        s_recipe_vars = f"{self.install_root_dir}/{_RECIPE_VARS}"
        s_recipe_saved = f"{self.install_root_dir}/{_RECIPE_SAVED}"

        btn = self.query_one("#installer-recipe", Button)
        b_ret_vars, msg_vars = self.save_recipe_vars(s_recipe_vars, data)
        if b_ret_vars:
            logging.info(f"{_RECIPE_VARS} is saved.")
        else:
            logging.error(f"Fail to save {_RECIPE_VARS}: {msg_vars}")

        b_ret_saved, msg_saved = self.save_recipe_saved(s_recipe_saved, data)
        if b_ret_saved:
            logging.info(f"{_RECIPE_SAVED} is saved.")
        else:
            logging.error(f"Fail to save {_RECIPE_SAVED}: {msg_saved}")

        if b_ret_vars and b_ret_saved:
            self._complete_progress_tracker(btn, is_success=True)
        else:
            self._update_button(btn, "error")

    def save_recipe_vars(self,
            filepath: str, data_to_save: dict) -> Tuple[bool, str]:
        try:
            processed_data = data_to_save.copy()
            # process ntp servers
            ntp_val = processed_data.get("ntp_servers", None)
            processed_data["ntp_servers"] = [ntp_val] if ntp_val else []
            # process storage_backends 
            sb_val = processed_data.get("storage_backends", None)
            processed_data["storage_backends"] = [sb_val] if sb_val else []
            if sb_val == "ceph":
                processed_data["ceph_osd_use_all"] = True
            # process network interface names
            mgmt = nm.get_interface_by_profile("management")
            svc = nm.get_interface_by_profile("service")
            provider = nm.get_interface_by_profile("provider")
            storage = nm.get_interface_by_profile("storage")
            if not mgmt:
                raise ValueError("Management profile must exist.")
            if not provider:
                raise ValueError("Provider profile must exist.")
            mgmt_name = mgmt.get("name")
            provider_name = provider.get("name")
            svc_name = svc.get("name") if svc else mgmt_name
            storage_name = storage.get("name") if storage else svc_name
            iface_data = {
                "svc_iface_name": svc_name,
                "mgmt_iface_name": mgmt_name,
                "provider_iface_name": provider_name,
                "storage_iface_name": storage_name
            }
            processed_data |= iface_data

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

            if (
                hasattr(self, "workflow_data")
                and "install" in self.workflow_data
            ):
                output_data["install"] = self.workflow_data["install"]

            netapp_lookup = {}
            if "netapp_tmpl" in data_to_save:
                tmpl_list = data_to_save["netapp_tmpl"]
                tmpl1 = tmpl_list[0] if len(tmpl_list) > 0 else {}
                tmpl2 = tmpl_list[1] if len(tmpl_list) > 1 else {}
                
                netapp_lookup = {
                    "netapp_mgmt_lif": tmpl1.get("managementLIF"),
                    "netapp_svm": tmpl1.get("svm"),
                    "netapp_user": tmpl1.get("username"),
                    "netapp_pass": tmpl1.get("password"),
                    "netapp_data_lif1": tmpl1.get("dataLIF"),
                    "netapp_shares1": tmpl1.get("shares")[0] if tmpl1.get("shares") else "",
                    "netapp_data_lif2": tmpl2.get("dataLIF"),
                    "netapp_shares2": tmpl2.get("shares")[0] if tmpl2.get("shares") else "",
                }

            for field in self.modal_screen.recipe_data.get("fields", []):
                field_copy = field.copy()
                name = field["name"]

                if name.startswith("netapp_") and name in netapp_lookup:
                    val = netapp_lookup[name]
                    field_copy["default"] = str(val) if val is not None else ""
                elif name in data_to_save:
                    field_copy["default"] = data_to_save[name]
                output_data["variable"]["fields"].append(field_copy)

            self.workflow_data = output_data

            # update preparations recipes
            new_preps = (
                self.workflow_data.get("install", {}).get("preparations", [])
            )
            for item in new_preps:
                item_name = item.get("name")
                if item_name in self.btn_map:
                    self.btn_map[item_name] = item
            new_plays = (
                self.workflow_data.get("install", {}).get("playboks", [])
            )
            for item in new_plays:
                item_name = item.get("name")
                if item_name in self.btn_map:
                    self.btn_map[item_name] = item

            with open(filepath, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    output_data, f, allow_unicode=True, sort_keys=False
                )
            return (True, "Succeed")
        except OSError as e:
            return (False, e.strerror)
        except Exception as e:
            return (False, str(e))

    def handle_save_vault(self, data: Optional[dict]) -> None:
        if not data:
            logging.info("Vault configuration is cancelled.")
            return

        btn = self.query_one("#installer-vault", Button)

        try:
            vault_engine = VaultManager(self.install_root_dir)
            vault_engine.generate_vault_files(data)

            logging.info("Vault process is completed successfully.")
            self._complete_progress_tracker(btn, is_success=True)
        except Exception as e:
            logging.error(f"Failed to execute vault tasks: {e}")
            variant = "error"
            self._update_button(btn, "error")

    def _init_workflow(self) -> None:
        self.config_path = Path(self.install_root_dir) / "recipe.yml"
        self.status_path = (
            self.config_path.parent / f".{self.config_path.name}"
        )
        self.workflow_data = {}
        self.btn_map = {}
        
        target_path = (
            self.status_path if self.status_path.exists() else self.config_path
        )
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                self.workflow_data = yaml.safe_load(f) or {}
        except Exception:
            logging.error(f"Failed to load the original recipe: {e}")
            self.workflow_data = {
                "install": {"preparations": [], "playbooks": []}
            }

    def compose(self) -> ComposeResult:
        if not hasattr(self, "workflow_data") or not self.workflow_data:
            self._init_workflow()
        install_data = self.workflow_data.get("install", {})

        if not install_data.get("preparations") and not install_data.get("playbooks"):
            yield Label("Warning: No workflow data found in recipe.yml!")
        with Horizontal():
            yield Label("Hosts", classes="title")
            yield Button(label="Refresh", id="hosts-refresh",
                         variant="primary")
            yield Button(label="Inventory", id="inventory-view",
                         variant="primary")
        yield ListHost(id="host_list_widget")

        yield Label("Installer", classes="title")
        if "preparations" in install_data:
            with Horizontal(classes="workflow-row", id="prep_block"):
                yield Label("Prep:", classes="row-header")
                for item in install_data["preparations"]:
                    name = item["name"]
                    state = item.get("state", "")
                    btn_id = f"installer-{name}"
                    if state == "pass":
                        variant = "success"
                        lbl = f"{name} [bold green](P)[/]"
                    elif state == "fail":
                        variant = "error"
                        lbl = f"{name} [bold red](F)[/]"
                    else:
                        variant = "default"
                        lbl = name
                    btn = Button(label=lbl, id=btn_id, variant=variant,
                            classes="workflow-btn")
                    self.btn_map[btn_id] = item
                    yield btn
        if "playbooks" in install_data:
            with Horizontal(classes="workflow-row"):
                yield Label("Cook:", classes="row-header")
                with Container(id="playbooks_block"):
                    for item in install_data["playbooks"]:
                        name = item["name"]
                        state = item.get("state", "")
                        btn_id = f"playbook-{name}"
                        if state == "pass":
                            variant = "success"
                            lbl = f"{name} [bold green](P)[/]"
                        elif state == "fail":
                            variant = "error"
                            lbl = f"{name} [bold red](F)[/]"
                        else:
                            variant = "default"
                            lbl = name
                        btn = Button(label=lbl, id=btn_id, variant=variant,
                                classes="workflow-btn")
                        self.btn_map[btn_id] = item
                        yield btn
        yield Static("", id="prep-status")
        yield ProgressBar(id="prep-progress", total=1.0, show_bar=True)


    def run_playbook_task(self, button_widget: Button) -> None:
        # run playbook code here
        pass
        #self._complete_progress_tracker(button_widget)

    def _complete_progress_tracker(self,
            button_widget: Button, is_success: bool = False) -> None:
        btn_id = button_widget.id
        if btn_id in self.btn_map:
            target_item = self.btn_map[btn_id]
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            target_item["cooked_at"] = current_time
            target_item["state"] = "pass" if is_success else "fail"

            try:
                with open(self.status_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(
                        self.workflow_data,
                        f,
                        allow_unicode=True,
                        sort_keys=False
                    )
            except Exception as e:
                logging.error(f"Failed to update cooking status: {e}")

        variant = "success" if is_success else "error"
        self._update_button(button_widget, variant)
