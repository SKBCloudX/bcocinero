import yaml
from textual import log
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static

from nm_helpers import (
    get_host_info,
    list_interfaces,
    get_interface_state,
    build_static_ipv4_state,
    build_dhcp_ipv4_state,
    set_hostname,
    set_dns_servers,
    apply_state,
)

d_host = get_host_info()
l_iface = list_interfaces()

class LabelInput(Widget):
    def __init__(self, label: str, id: str, value: str, placeholder: str):
        super().__init__()
        self.label = label
        self.id = id
        self.value = value
        self.placeholder = placeholder

    def compose(self):
        with Horizontal():
            yield Label(f"{self.label}: ")
            yield Input(value=self.value, placeholder=self.placeholder,
                    id=self.id)

class HostConfigScreen(ModalScreen[dict]):
    """Create Host config modal screen"""
    
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Host Configuration")
            with Horizontal():
                yield Label("Hostname: ")
                yield Input(value=d_host["name"], placeholder="hostname", 
                    id="hn")
            with Horizontal():
                yield Label("Nameserver: ")
                yield Input(value=d_host["nameserver"][0], 
                    placeholder="nameserver", id="ns")
            yield Horizontal(Button("Save", id="save", variant="primary"),
                Button("Cancel", id="cancel", variant="error"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        d_result = {}
        if event.button.id == "save":
            input_hn = self.query_one("#hn")
            input_ns = self.query_one("#ns")
            d_result["hostname"] = input_hn.value
            d_result["nameserver"] = input_ns.value
        self.log(d_result)
        self.dismiss(result=d_result)

class Dashboard(VerticalScroll):
    """Widget to display dashboard."""

    def save_hostconfig(self, result: dict) -> None:
        d_state = {}
        d_state = set_hostname(result["hostname"])
        with open('host.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(d_state, f, allow_unicode=True)
        apply_state(d_state)
        d_state = set_dns_servers([result["nameserver"]])
        with open('nameserver.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(d_state, f, allow_unicode=True)
        apply_state(d_state)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Button event handler"""
        if event.button.id == "host-config":
            self.app.push_screen(HostConfigScreen(), self.save_hostconfig)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="dashhost"):
            with Vertical():
                yield Horizontal(Label("Host "), Button("Config",
                    id="host-config", variant="primary"))
                yield Horizontal(Label("Hostname: "), Label(d_host["name"]))
                yield Horizontal(Label("Name Server: "),
                        Label(','.join(d_host["nameserver"])))
            with VerticalScroll():
                yield Label("Interfaces")
                for iface in l_iface:
                    yield Label(iface)

        with Vertical(classes="dashnetwork"):
            yield Static("Network")
            with Horizontal():
                with VerticalScroll(classes="nbox"):
                    yield Label("Service")
                    yield Horizontal(Label("Interface: "))
                    yield Horizontal(Label("IP: "))
                with VerticalScroll(classes="nbox"):
                    yield Label("Management")
                    yield Horizontal(Label("Interface: "))
                    yield Horizontal(Label("IP: "))
                with VerticalScroll(classes="nbox"):
                    yield Label("Provider")
                    yield Horizontal(Label("Interface: "))
                with VerticalScroll(classes="nbox"):
                    yield Label("Storage")
                    yield Horizontal(Label("Interface: "))
                    yield Horizontal(Label("IP: "))

        with Vertical(classes="dashinstaller"):
            yield Static("Installer")


