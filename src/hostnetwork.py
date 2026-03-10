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
    get_interface_info,
    get_bond_interfaces,
    delete_bond_interface,
    create_bond,
    save_state,
    apply_state,
)


class BondingList(Widget):
    l_bond_header = ["Name", "Ports", "Mode", "State", "Edit", "Delete"]
    l_bond_data = get_bond_interfaces()

    def compose(self) -> ComposeResult:
        yield DataTable()

    def on_mount(self) -> None:
        self.log(self.l_bond_data)
        table = self.query_one(DataTable)
        table.add_columns(*self.l_bond_header)
        for name, ports, mode, state in self.l_bond_data:
            table.add_row(name, ports, mode, state, "EDIT", "DELETE")

    def on_data_table_cell_selected(self,
            event: DataTable.CellSelected) -> None:
        cell_key = event.cell_key
        value = event.value
        self.log(f"{cell_key} : {value} :")
        if event.coordinate.column in [4, 5]:
            row_index = event.coordinate.row
            table = self.query_one(DataTable)
            row_data = table.get_row_at(row_index)
            if value == "DELETE":
                delete_bond_interface(row_data[0])
                self.refresh_table()
                self.notify(f"Deleted {row_data[0]}")
            if value == "Edit":


    def refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self.l_bond_data = get_bond_interfaces()
        for name, ports, mode, state in self.l_bond_data:
            table.add_row(name, ports, mode, state, "EDIT", "DELETE")


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
        self.mode = str(cur.label)
        for btn in radioset.query(RadioButton):
            if btn == cur:
                btn.value = True
            else:
                btn.value = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        d_result = {}
        bonding_name = self.query_one("#bn", Input).value
        bonding_ports = self.query_one("#port_list", SelectionList).selected
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
            self.notify(f"Configured {result['name']}}")
            self.query_one(BondingList).refresh_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bond-create":
            self.app.push_screen(BondConfigScreen(), self.save_bondconfig)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Bonding", classes="title")
            yield Button(label="Create", id="bond-create", variant="primary")
        yield BondingList()
        

