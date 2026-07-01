import asyncio
import os
import re
import subprocess
import yaml
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button, DataTable, Input, Select, Label, ProgressBar,
    RichLog, Static, TextArea
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

class InventoryViewModal(ModalScreen[None]):
    def __init__(self, list_host_obj: ListHost):
        super().__init__()
        self.logger = logging.getLogger("bcocinero")
        self.list_host_obj = list_host_obj

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Label("Inventory view", classes="modal-title")
            yield TextArea(
                id="inventory_textarea",
                read_only=True,
                show_line_numbers=True,
            )
            yield Button("Close", variant="error", 
                         id="close_modal_btn", classes="workflow-btn")

    def on_mount(self) -> None:
        s_inventory = ""
        textarea = self.query_one("#inventory_textarea", TextArea)
        textarea.language = "toml"
        try:
            self.list_host_obj.create_inventory("/tmp")
            with open("/tmp/hosts", "r", encoding="utf-8") as f:
                s_inventory = f.read()
            os.unlink("/tmp/hosts")
        except Exception as e:
            s_inventory = f"Failed to create inventory: {e}"
            self.logger.error(s_inventory)

        textarea.text = s_inventory

    @on(Button.Pressed, "#close_modal_btn")
    def close_modal(self) -> None:
        self.dismiss()

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

class LogViewModal(ModalScreen):
    def __init__(self, title: str, log_path: Path):
        super().__init__()
        self.log_title = title
        self.log_path = log_path

    def compose(self):
        with VerticalScroll(id="modal-container"):
            yield Label(f"Cooking: {self.log_title}", classes="modal-title")
            yield RichLog(id="modal_log_window", highlight=True, markup=True)
            yield Static("", id="modal_playbook_status")
            yield Label("Progress:", id="modal_progress_label")
            yield ProgressBar(id="modal_playbook_progress",
                    total=1.0, show_bar=True)
            yield Button("Close", id="close-modal-btn", variant="error")

    def on_mount(self):
        self.query_one("#close-modal-btn").disabled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-modal-btn":
            self.dismiss()

    def append_log(self, text: str):
        try:
            self.query_one("#modal_log_window", RichLog).write(text)
        except Exception:
            pass

    def enable_close(self):
        try:
            self.query_one("#close-modal-btn").disabled = False
        except Exception:
            pass

class Installer(VerticalScroll):
    def __init__(self):
        super().__init__()
        self.install_root_dir = am.get_install_root()
        self.home_dir = Path.home()
        self.log_dir = self.home_dir / ".local" / "bcocinero"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.modal_screen = None

    def _init_workflow(self) -> None:
        if self.install_root_dir:
            self.config_path = Path(self.install_root_dir) / "recipe.yml"
            self.status_path = (
                self.config_path.parent / f".{self.config_path.name}"
            )
            target_path = (
                self.status_path if self.status_path.exists() else self.config_path
            )
        else:
            self.config_path = None
            self.status_path = None
            target_path = None
        self.workflow_data = {}
        self.btn_map = {}
        
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                self.workflow_data = yaml.safe_load(f) or {}
        except Exception as e:
            logging.warning(f"Failed to load the original recipe: {e}")
            self.workflow_data = {
                "install": {"preparations": [], "playbooks": []}
            }

    def _init_ui(self, btn: Button, bar: Optional[ProgressBar] = None) -> None:
        btn.disabled = True

        if bar is not None:
            bar.progress = 0

    def _update_progress(self,
                         bar: ProgressBar, status: Static,
                         progress: float, message: str) -> None:
        bar.progress = progress
        status.update(f"[cyan]{message}[/]")

    def _update_button(self,
            btn: Button, variant: str = "default", cooked_at: str = "") -> None:
        cook_msg = ""
        if variant == "success":
            cook_msg = "Cooked right at"
        elif variant == "error":
            cook_msg = "Cooked wrong at"
        btn.variant = variant
        btn.disabled = False

        btn.tooltip = (
            f"{cook_msg}: {cooked_at}"
            if variant in ["success", "error"] and cooked_at
            else None
        )

        btn.refresh(layout=True)

    def _update_cooking_status(self,
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

        self._update_button(button_widget, variant, current_time)

        if is_success:
            self._unlock_next_step(btn_id)
            data = self.workflow_data.get("install", {})
            all_preps_passed = all(
                i.get("state") == "pass" for i in data.get("preparations", [])
            )
            if all_preps_passed:
                try:
                    self.query_one("#cook-all", Button).disabled = False
                except Exception:
                    logging.error("Cannot find 'cook-all' button")

    def _unlock_next_step(self, current_btn_id: str) -> None:
        data = self.workflow_data.get("install", {})
        ordered_ids = []
        if "preparations" in data:
            ordered_ids.extend([
                f"installer-{i['name']}" for i in data["preparations"]
            ])
        if "playbooks" in data:
            ordered_ids.extend([
                f"playbook-{i['name']}" for i in data["playbooks"]
            ])
        try:
            cur_index = ordered_ids.index(current_btn_id)
            if cur_index + 1 < len(ordered_ids):
                next_btn_id = ordered_ids[cur_index+1]
                next_button = self.query_one(f"#{next_btn_id}", Button)
                if next_button:
                    next_button.disabled = False
                    next_button.refresh()
        except ValueError:
            logging.error(f"Button ID {current_btn_id} not found.")
        except Exception as e:
            logging.error(f"Failed to unlock next step: {e}")

    def _save_recipe_vars(self,
            filepath: str, data_to_save: dict) -> Tuple[bool, str]:
        try:
            processed_data = data_to_save.copy()
            # process ntp servers
            ntp_val = processed_data.get("ntp_servers", None)
            processed_data["ntp_servers"] = [ntp_val] if ntp_val else []
            # process upstream_dns_servers
            dns_val = processed_data.get("upstream_dns_servers", None)
            processed_data["upstream_dns_servers"] = (
                [dns_val] if dns_val else ["8.8.8.8"]
            )
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

    def _cache_recipe(self, filepath: str, data_to_save: dict) -> Tuple:
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
                self.workflow_data.get("install", {}).get("playbooks", [])
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

    def _get_playbook_task_count(self, task_name: str) -> int:
        TASK_REGEX = re.compile(r'^[ ]{6}\S')
        default_count = 45
        cmd = f"./run.sh {task_name} --list-tasks"

        try:
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.install_root_dir
            )
            stdout, _ = process.communicate()
            count = sum(1 for l in stdout.splitlines() if TASK_REGEX.match(l))

            return count if count > 0 else default_count
        except Exception as e:
            logging.error(f"Failed to count tasks for {task_name}: {e}")
            return default_count

    async def _execute_run_script(self, task_name: str,
            playbook_button: Button, bar: ProgressBar, status_lbl: Static,
            prefix_msg: str = "",
            modal: Optional[LogViewModal] = None) -> bool:
        log_file_path = self.log_dir / f"{task_name}.log"

        total = self._get_playbook_task_count(task_name)

        is_success = False
        index = 0

        self._update_progress(
            bar, status_lbl, 0.0, f"{prefix_msg}Initializing {task_name}..."
        )

        try:
            with open(log_file_path, "w", encoding="utf-8") as log_f:
                process = await asyncio.create_subprocess_exec(
                    "./run.sh", task_name,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=self.install_root_dir
                )
                while True:
                    line_bytes = await process.stdout.readline()
                    if not line_bytes:
                        break

                    line = line_bytes.decode("utf-8")
                    log_f.write(line)
                    log_f.flush()
                    escaped = escape(line.strip("\n"))
                    modal.append_log(escaped)
                    
                    if "TASK [" in line:
                        index += 1
                        pratio = min(index / total, 0.99)
                        self._update_progress(
                            bar, status_lbl, pratio, 
                            f"{prefix_msg}{task_name}: {index}/{total} Tasks"
                        )
                await process.wait()
                is_success = (process.returncode == 0)
        except Exception as e:
            logging.error(f"Subprocess run crashed at {task_name}: {e}")
            if 'modal' in locals():
                modal.append_log(f"\n[bold red]Fatal Error:[/] {e}")

        modal.enable_close()
        if is_success:
            s_msg = f"{prefix_msg}Done: {task_name}"
            self._update_progress(bar, status_lbl, 1.0, s_msg)
            logging.info(s_msg)
        else:
            s_msg = f"{prefix_msg}Failed: {task_name}"
            self._update_progress(bar, status_lbl, bar.progress,s_msg)
            logging.error(s_msg)

        self._update_cooking_status(playbook_button, is_success)
        return is_success


    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "hosts-refresh":
            self.query_one(ListHost).refresh_table()
        elif btn_id == "inventory-view":
            o_list_host = self.query_one(ListHost)
            self.modal_screen = InventoryViewModal(o_list_host)
            self.app.push_screen(self.modal_screen)
        elif btn_id == "installer-prep":
            self.run_prep_task()
        elif btn_id == "installer-recipe":
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
        elif btn_id == "installer-vault":
            if not self.install_root_dir:
                s_msg = "Cannot find install root directory. Did you run Prep?"
                logging.error(s_msg)
                return
            self.modal_screen = VaultModal()
            self.app.push_screen(self.modal_screen, self.handle_save_vault)
        elif btn_id == "cook-all":
            event.button.disabled = True
            self.run_cook_all(event.button)
        elif btn_id.startswith("playbook-"):
            self.run_playbook(event.button)

    @work
    async def run_cook_all(self, btn: Button) -> None:
        install_data = self.workflow_data.get("install", {})
        playbooks = install_data.get("playbooks", [])

        if not playbooks:
            logging.warning("No playbooks found.")
            return

        logging.info("Starting [Cook All] workflow...")

        for item in playbooks:
            name = item.get("name")
            state = item.get("state", "")
            btn_id = f"playbook-{name}"

            if state == "pass":
                logging.info(f"[Cook All] Skipping playbook '{name}'")
                continue

            logging.info(f"[Cook All] Next playbook: {name}")

            try:
                playbook_btn = self.query_one(f"#{btn_id}", Button)
                worker = self.run_playbook(playbook_btn)
                await worker.wait()

                if isinstance(self.app.screen, LogViewModal):
                    await self.app.pop_screen()

                current_state = item.get("state", "")

                if current_state == "fail":
                    logging.error(f"[Cook All] playbook '{name}' failed.")
                    break
                elif current_state != "pass":
                    logging.warning(
                        f"[Cook All] playbook '{name}' interrupted."
                    )
                    break
            except Exception as e:
                logging.error(f"[Cook All] playbook '{name}' exception: {e}")
                break
        logging.info("[Cook All] finished.")
        btn.disabled = False

    @work
    async def run_playbook(self, button_widget: Button) -> None:
        task_name = button_widget.id.split("-", 1)[-1]
        log_file_path = self.log_dir / f"{task_name}.log"

        modal = LogViewModal(
            title=f"{task_name}", log_path=log_file_path
        )
        await self.app.push_screen(modal)
        bar = modal.query_one("#modal_playbook_progress", ProgressBar)
        status_lbl = modal.query_one("#modal_playbook_status", Static)
        self._init_ui(button_widget, bar)
    
        is_success = await self._execute_run_script(
            task_name, button_widget, bar, status_lbl,
            "", modal=modal
        )

        self._update_cooking_status(button_widget, is_success=is_success)

    @work(exclusive=True, thread=True)
    async def run_prep_task(self) -> None:
        btn = self.query_one("#installer-prep", Button)
        bar = self.query_one("#prep-progress", ProgressBar)
        status = self.query_one("#prep-status", Static)

        is_success = False
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
            is_success = True
        except Exception as e:
            logging.error(f"Error during prep: {e}")
            self.app.call_from_thread(status.update, f"[bold red]{str(e)}[/]")

        self.app.call_from_thread(self._update_cooking_status, btn, is_success)

    def handle_save_recipe(self, data: Optional[Dict]) -> None:
        if not data:
            logging.info("Recipe configuration is cancelled.")
            return

        s_recipe_vars = f"{self.install_root_dir}/{_RECIPE_VARS}"
        s_recipe_saved = f"{self.install_root_dir}/{_RECIPE_SAVED}"

        btn = self.query_one("#installer-recipe", Button)
        b_ret_vars, msg_vars = self._save_recipe_vars(s_recipe_vars, data)
        if b_ret_vars:
            logging.info(f"{_RECIPE_VARS} is saved.")
        else:
            logging.error(f"Fail to save {_RECIPE_VARS}: {msg_vars}")

        b_ret_cached, msg_saved = self._cache_recipe(s_recipe_saved, data)
        if b_ret_cached:
            logging.info(f"{_RECIPE_SAVED} is saved.")
        else:
            logging.error(f"Fail to save {_RECIPE_SAVED}: {msg_saved}")

        is_success = True if b_ret_vars and b_ret_cached else False
        self._update_cooking_status(btn, is_success=is_success)


    def handle_save_vault(self, data: Optional[dict]) -> None:
        if not data:
            logging.info("Vault configuration is cancelled.")
            return

        is_success = False
        btn = self.query_one("#installer-vault", Button)

        try:
            vault_engine = VaultManager(self.install_root_dir)
            is_success = vault_engine.create_vault(data)
        except Exception as e:
            logging.error(f"Failed to create vault: {e}")

        self._update_cooking_status(btn, is_success)

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

        next_button_allowed = True

        if "preparations" in install_data:
            with Horizontal(classes="workflow-row"):
                yield Label("Prep:", classes="row-header")
                for item in install_data["preparations"]:
                    name = item["name"]
                    state = item.get("state", "")
                    cooked_at = item.get("cooked_at", "")
                    btn_id = f"installer-{name}"
                    if state == "pass":
                        cook_msg = "Cooked right at"
                        variant = "success"
                    elif state == "fail":
                        cook_msg = "Cooked wrong at"
                        variant = "error"
                    else:
                        variant = "default"
                    btn = Button(label=name, id=btn_id, variant=variant,
                            classes="workflow-btn")
                    btn.disabled = not next_button_allowed
                    btn.tooltip = (
                        f"{cook_msg}: {cooked_at}" if state and cooked_at
                        else None
                    )
                    yield btn
                    self.btn_map[btn_id] = item
                    next_button_allowed = (state == "pass")

        yield Static("", id="prep-status")
        yield ProgressBar(id="prep-progress", total=1.0, show_bar=True)

        if "playbooks" in install_data:
            with VerticalScroll(classes="workflow-row"):
                with Horizontal(classes="workflow-row"):
                    yield Label("Cook:", classes="row-header")
                    # check all preps are passed
                    all_preps_passed = all(
                        item.get("state") == "pass"
                        for item in install_data.get("preparations", [])
                    )
                    cooking_btn = Button(
                        label="Cook All",
                        id="cook-all",
                        variant="primary",
                        classes="workflow-btn"
                    )
                    cooking_btn.disabled = not all_preps_passed
                    yield cooking_btn
                with Container(id="playbooks_block"):
                    for item in install_data["playbooks"]:
                        name = item["name"]
                        state = item.get("state", "")
                        cooked_at = item.get("cooked_at", "")
                        btn_id = f"playbook-{name}"
                        if state == "pass":
                            cook_msg = "Cooked right at"
                            variant = "success"
                        elif state == "fail":
                            cook_msg = "Cooked wrong at"
                            variant = "error"
                        else:
                            variant = "default"
                        btn = Button(label=name, id=btn_id, variant=variant,
                                classes="workflow-btn")
                        btn.disabled = not next_button_allowed
                        btn.tooltip = (
                            f"{cook_msg}: {cooked_at}" if state and cooked_at
                            else None
                        )
                        yield btn
                        self.btn_map[btn_id] = item
                        next_button_allowed = (state == "pass")
