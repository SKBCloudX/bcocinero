from textual import log
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Select
from typing import Optional, Dict, Any, List

from bcocinero.nm_helpers import (
    NetworkManager,
    ArtifactManager,
    ProfileType,
    NodeRole
)

nm = NetworkManager()
am = ArtifactManager()

class Hostname(Widget):
    host_data = nm.get_host_info()
    hostname = reactive(host_data["name"])
    nameserver = reactive(",".join(host_data["nameserver"]))
    role = reactive(host_data["role"])

    def render(self) -> str:
        return f"Hostname: {self.hostname} ({self.role}) / DNS: {self.nameserver}"

class ListInterface(Widget):
    def __init__(self) -> None:
        super().__init__(id="dashboard_interface")
        self.l_iface_header = [
            "Name", "Profile", "Type", "MAC Addr.", "IP Addr./Netmask"
        ]
        self.l_interface = nm.list_interfaces()

    def compose(self) -> ComposeResult:
        yield DataTable(
            id="list_interface_table",
            cursor_type="row",
            fixed_rows=1,
            zebra_stripes=True
        )

    def on_mount(self) -> None:
        table = self.query_one("#list_interface_table", DataTable)
        table.add_columns(*self.l_iface_header)
        self._add_rows(table)

    def _add_rows(self, table: DataTable) -> None:
        for iface in self.l_interface:
            ip_info = iface.get("ipv4", {})
            addresses = ip_info.get("address", [])
            
            s_ip = ""
            if addresses:
                addr = addresses[0]
                s_ip = f"{addr.get('ip')}/{addr.get('prefix-length')}"

            pval = iface.get("profile-name", "")
            profile = pval if pval in ProfileType.list_values() else "-"

            table.add_row(
                iface.get("name", "N/A"),
                profile,
                iface.get("type", "N/A"),
                iface.get("mac-address", "N/A"),
                s_ip
            )
        
    def refresh_table(self) -> None:
        table = self.query_one("#list_interface_table", DataTable)
        table.clear()
        self.l_interface = nm.list_interfaces()
        self._add_rows(table)

class HostConfigScreen(ModalScreen[dict]):
    def __init__(self, s_hostname: str, s_nameserver: str, s_role: str):
        super().__init__()
        self.init_hostname = s_hostname
        self.init_nameserver = s_nameserver
        self.init_role = s_role if s_role else NodeRole.HEAD.value

        self.role_options = [
            (item.value, item.value)
            for item in NodeRole if item != NodeRole.NONE
        ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_container"):
            yield Label("Host Configuration", classes="modal_title")
            with Horizontal():
                yield Label("Hostname: ", classes="input_label")
                yield Input(value=self.init_hostname, id="hn")
            with Horizontal():
                yield Label("Role: ", classes="input_label")
                yield Select(self.role_options, value=self.init_role,
                        id="role", prompt="Select Role")
            with Horizontal():
                yield Label("Nameserver: ", classes="input_label")
                yield Input(value=self.init_nameserver, id="ns")
            with Horizontal(classes="modal_buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            hn_val = self.query_one("#hn", Input).value.strip()
            ns_val = self.query_one("#ns", Input).value.strip()
            role_val = self.query_one("#role", Select).value

            if not hn_val or not ns_val or role_val == Select.NULL:
                self.app.notify("Enter hostname, nameservers and select role",
                                severity="error")
                return

            self.dismiss({
                "hostname": hn_val,
                "nameserver": ns_val,
                "role": role_val
            })
        else:
            self.dismiss(None)

class Dashboard(VerticalScroll):
    def save_hostconfig(self, result: Optional[Dict[str, str]]) -> None:
        if not result:
            return

        try:
            hn_state = nm.set_hostname(result["hostname"])
            am.save_state("host.yaml", hn_state)
            nm.apply_state(hn_state)

            ns_list = [
                addr.strip() for addr in result["nameserver"].split(",") 
                    if addr.strip()
            ]
            dns_state = nm.set_dns_servers(ns_list)
            am.save_state("nameserver.yaml", dns_state)
            nm.apply_state(dns_state)

            b_ret, s_msg = nm.set_role(result["role"])
            hostname_widget = self.query_one(Hostname)
            hostname_widget.hostname = result["hostname"]
            hostname_widget.nameserver = result["nameserver"]
            hostname_widget.role = result["role"]

            self.app.write_status("Configured host information.")
        except Exception as e:
            self.app.write_status(f"Failed to configure: {str(e)}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "host-config":
            h_widget = self.query_one(Hostname)
            self.app.push_screen(
                HostConfigScreen(
                    h_widget.hostname,
                    h_widget.nameserver,
                    h_widget.role
                ),
                self.save_hostconfig
            )

    def compose(self) -> ComposeResult:
        with Vertical(classes="dashboard_hostname"):
            with Horizontal():
                yield Label("Host", classes="title")
                yield Button(label="Config", id="host-config",
                             variant="primary")
            with Horizontal():
                yield Hostname()
        with Vertical(classes="dashboard_interface"):
            yield Label("Interfaces", classes="title")
            yield ListInterface()
        with Vertical(classes="dashboard_installer"):
            yield Label("Installer", classes="title")

