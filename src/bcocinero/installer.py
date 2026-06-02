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
from bcocinero.vault import VaultManager

nm = NetworkManager()
am = ArtifactManager()

_RECIPE = "recipe.yml"
_RECIPE_VARS = "recipe_vars.yml"
_RECIPE_SAVED = ".recipe.yml"
_VAULT_PASS_FILE = ".vaultpass"
_UD_VAULT_FILE = "group_vars/all/ud_vault.yml"
_VAULT_FILE = "group_vars/all/vault.yml"
_NOVA_SSH_KEY = "/tmp/nova_sshkey"

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
                        "svm": raw.get("netapp_svm", ""),
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
                        "svm": raw.get("netapp_svm", ""),
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
                        yield Label(field["label"], classed="label-fixed")
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
        if event.button.id == "installer-vault":
            if not self.install_root_dir:
                s_msg = "Cannot find install root directory. Did you run Prep?"
                logging.error(s_msg)
                return
            self.modal_screen = VaultModal()
            self.app.push_screen(self.modal_screen, self.handle_save_vault)

    @work(exclusive=True, thread=True)
    async def run_prep_task(self) -> None:
        btn = self.query_one("#installer-prepare", Button)
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
            self.app.call_from_thread(self._update_button, btn, "success")
        except Exception as e:
            logging.error(f"Error during prep: {e}")
            self.app.call_from_thread(status.update, f"[bold red]{str(e)}[/]")
            self.app.call_from_thread(self._update_button, btn)

    def _init_ui(self, btn: Button, bar: Optional[ProgressBar] = None) -> None:
        btn.disabled = True

        if bar is not None:
            bar.progress = 0

    def _update_progress(self,
                         bar: ProgressBar, status: Static,
                         progress: float, message: str) -> None:
        bar.progress = progress
        status.update(f"[cyan]{message}[/]")

    def _update_button(self, btn: Button, variant: str = "error") -> None:
        cur_label = str(btn.label)
        if not cur_label.endswith("(Done!)"):
            btn.label = f"{cur_label}(Done!)"

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

        variant = "success" if b_ret_vars and b_ret_saved else "error"
        self._update_button(btn, variant)

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
            processed_data = iface_data | processed_data

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
            variant = "success"
        except Exception as e:
            logging.error(f"Failed to execute vault tasks: {e}")
            btn.label = "Vault(Failed!)"
            variant = "error"

        self._update_button(btn, variant)

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
            yield Button(label="Vault", id="installer-vault",
                         variant="primary")
        yield Static("", id="prep-status")
        yield ProgressBar(id="prep-progress", total=1.0, show_bar=True)

