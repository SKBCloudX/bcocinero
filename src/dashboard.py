from textual import log, on
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label

from nm_helpers import (
    get_host_info,
    list_interfaces,
    get_interface_state,
    build_static_ipv4_state,
    set_hostname,
    set_dns_servers,
    save_state,
    apply_state,
)

class HostInfo():
    def __init__(self):
        self.d_host = get_host_info()
        self.l_iface = list_interfaces()

    def update_host_info(self):
        self.d_host = get_host_info()

    def update_interfaces(self):
        self.l_iface = list_interfaces()

hostinfo = HostInfo()

class Hostname(Widget):
    hostname = reactive(hostinfo.d_host["name"])

    def render(self) -> str:
        return f"Hostname: {self.hostname}"

class Nameserver(Widget):
    nameserver = reactive(",".join(hostinfo.d_host["nameserver"]))

    def render(self) -> str:
        return f"Nameserver: {self.nameserver}"

class ListInterface(Widget):

    def __init__(self) -> None:
        super().__init__(id="dashboard_interface")
        self.l_iface_header = ["Name", "Type", "MAC Addr."]
        self.l_interface = list_interfaces()

    def compose(self) -> ComposeResult:
        yield DataTable()

    def _add_rows(self, table) -> None:
        for iface in self.l_interface:
            self.log(iface)
            table.add_row(
                iface.get("name", "N/A"), 
                iface.get("type", "N/A"),
                iface.get("mac-address", "N/A")
            )
        
    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(*self.l_iface_header)
        self._add_rows(table)

    def refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self.l_interface = list_interfaces()
        self.log(self.l_interface)
        self._add_rows(table)

class HostConfigScreen(ModalScreen[dict]):
    """Create Host config modal screen"""
    def __init__(self, s_hostname: str, s_nameserver: str):
        super().__init__()
        self.hostname = s_hostname
        self.nameserver = s_nameserver

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Host Configuration")
            with Horizontal():
                yield Label("Hostname: ")
                yield Input(value=self.hostname, id="hn")
            with Horizontal():
                yield Label("Nameserver: ")
                yield Input(value=self.nameserver, id="ns")
            yield Horizontal(Button("Save", id="save", variant="primary"),
                Button("Cancel", id="cancel", variant="error"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        d_result = {}
        input_hn = self.query_one("#hn")
        input_ns = self.query_one("#ns")
        if event.button.id == "save":
            d_result["hostname"] = input_hn.value
            d_result["nameserver"] = input_ns.value
        self.log(d_result)
        self.dismiss(result=d_result)


class Dashboard(VerticalScroll):
    """Widget to display dashboard."""
    def save_hostconfig(self, result: dict) -> None:
        d_state = {}
        if result:
            d_state = set_hostname(result["hostname"])
            save_state("host.yaml", d_state)
            apply_state(d_state)
            d_state = set_dns_servers([result["nameserver"]])
            save_state("nameserver.yaml", d_state)
            apply_state(d_state)
            hostinfo.update_host_info()
            d_host = get_host_info()
            self.query_one(Hostname).hostname = result["hostname"]
            self.query_one(Nameserver).nameserver = result["nameserver"]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Button event handler"""
        if event.button.id == "host-config":
            s_hostname = self.query_one(Hostname).hostname
            s_nameserver = self.query_one(Nameserver).nameserver
            self.app.push_screen(HostConfigScreen(s_hostname, s_nameserver),
                self.save_hostconfig)

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(classes="hostdns"):
                yield Label("Host", classes="title")
                yield Button(label="Config", id="host-config",
                    variant="primary")
                yield Hostname()
                yield Nameserver()
            with Vertical():
                yield Label("Interfaces", classes="title")
                yield ListInterface()
        with Vertical():
            yield Label("Network", classes="title")
            with Horizontal():
                with VerticalScroll():
                    yield Label("Service")
                    yield Horizontal(Label("Interface: "))
                    yield Horizontal(Label("IP: "))
                with VerticalScroll():
                    yield Label("Management")
                    yield Horizontal(Label("Interface: "))
                    yield Horizontal(Label("IP: "))
                with VerticalScroll():
                    yield Label("Provider")
                    yield Horizontal(Label("Interface: "))
                with VerticalScroll():
                    yield Label("Storage")
                    yield Horizontal(Label("Interface: "))
                    yield Horizontal(Label("IP: "))

        with Vertical():
            yield Label("Installer", classes="title")

