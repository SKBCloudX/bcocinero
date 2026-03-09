from typing import Optional
from textual import log
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, SelectionList
from textual.widgets import RadioSet, RadioButton

from nm_helpers import (
    list_interfaces,
    create_bond,
    save_state,
    apply_state,
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
        ("balance-rr", False),
        ("active-backup", True),
        ("balance-xor", False),
        ("broadcast", False),
        ("802.3ad", False),
        ("balance-tlb", False),
        ("blanace-alb", False),
    ]
    mode = "active-backup"
    def __init__(self, bond: Optional[dict] = None):
        super().__init__()
        self.bond = bond

    def compose(self) -> ComposeResult:
        yield Label("Bonding Configuration")
        with Horizontal():
            yield Label("Name")
            yield Input(placeholder="Enter bonding name", id="bn")
        with Horizontal():
            yield Label("Ports")
            yield SelectionList(id="port_list")
        with Horizontal():
            yield Label("Mode")
            yield RadioSet(id="mode_list")
        with Horizontal():
            yield Button("Save", id="save", variant="primary")
            yield Button("Cancel", id="cancel", variant="error")

    def on_mount(self) -> None:
        self.update_port_list()
        self.update_mode_list(self.MODES)

    def update_port_list(self) -> None:
        selection_list = self.query_one("#port_list", SelectionList)
        l_iface = list_interfaces(["ethernet"])
        options = [(iface["name"], iface["name"]) for iface in l_iface]
        selection_list.add_options(options)

    def update_mode_list(self, options: list[tuple]) -> None:
        radioset = self.query_one("#mode_list", RadioSet)
        radioset.remove_children()
        radioset.mount(
            *(RadioButton(t[0], value=t[1]) for t in options)
        )

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        radioset = self.query_one("#mode_list", RadioSet)
        cur = event.pressed
        self.mode = cur.id
        self.log(self.mode)
        for btn in radioset.query(RadioButton):
            if btn == cur:
                btn.value = True
            else:
                btn.value = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        d_result = {}
        bonding_name = self.query_one("#bn", Input).value
        bonding_ports = self.query_one("#port_list", SelectionList).selected
        self.log(self.mode)
        if event.button.id == "save":
            d_result["name"] = bonding_name
            d_result["ports"] = bonding_ports
            d_result["mode"] = self.mode
        self.log(d_result)
        self.dismiss(result=d_result)


class HostNetwork(VerticalScroll):

    def save_bondconfig(self, result: dict) -> None:
        d_state = {}
        if result:
            d_state = create_bond(result["name"], result["ports"],
                result["mode"])
            save_state(f"{result['name']}.yaml", d_state)
            apply_state(d_state)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bond-create":
            self.app.push_screen(BondConfigScreen(), self.save_bondconfig)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Bonding", classes="title")
            yield Button(label="Create", id="bond-create", variant="primary")
        yield BondingList()
        

