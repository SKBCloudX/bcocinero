import yaml
from typing import Optional
from textual import log
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, SelectionList

from nm_helpers import (
    list_interfaces,
)


class BondingList(Widget):
    l_iface = list_interfaces(["bonding"])
    l_bond = [("Name", "Ports", "Mode", "State"),]
    for iface in l_iface:
        bname = iface.get(Interface.NAME)
        bstate = iface.get(Interface.STATE)
        bmode = ""
        bports = []
        bconfig = iface.get(Bond.CONFIG_SUBTREE, {})
        if bconfig:
            bmode = bconfig.get(Bond.MODE)
            bports = bconfig.get(Bond.PORT_SUBTREE, [])
        l_bond.append([(bname, "/".join(bports), bmode, bstate)])

    def compose(self) -> ComposeResult:
        yield DataTable()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(*self.l_bond[0])
        for row in self.l_bond[1:]:
            table.add_row(row)

class BondConfigScreen(ModalScreen[dict]):
    MODES = [
        ("balance-rr", 0),
        ("active-backup", 1),
        ("balance-xor", 2),
        ("broadcast", 3),
        ("802.3ad", 4),
        ("balance-tlb", 5),
        ("blanace-alb", 6),
    ]
    def __init__(self, bond: Optional[dict] = None):
        super().__init__()
        self.bond = bond

    def compose(self) -> ComposeResult:
        yield Label("Bonding Configuration")
        with Horizontal():
            yield Label("Name")
            yield Input(placeholder="Enter bonding name", id="bn")
        with Horizontal():
            yield Label("Mode")
            yield SelectionList(id="mode_list")
        with Horizontal():
            yield Label("Ports")
            yield SelectionList(id="port_list")


    def on_mount(self) -> None:
        self.update_mode_list()
        self.update_port_list()

    def update_mode_list(self) -> None:
        selection_list = self.query_one("#mode_list", SelectionList)
        selection_list.add_options(self.MODES)

    def update_port_list(self) -> None:
        selection_list = self.query_one("#port_list", SelectionList)
        l_iface = list_interfaces(["ethernet"])
        options = [(iface["name"], iface["name"]) for iface in l_iface]
        selection_list.add_options(options)


class HostNetwork(VerticalScroll):

    def save_bondconfig(self, result: dict) -> None:
        pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bond-create":
            self.app.push_screen(BondConfigScreen(), self.save_bondconfig)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Bonding", classes="title")
            yield Button(label="Create", id="bond-create", variant="primary")
        yield BondingList()
        

