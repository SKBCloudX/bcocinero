import ipaddress

from typing import Optional
from textual import log
from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, SelectionList
from textual.widgets import RadioSet, RadioButton

from nm_helpers import (
    list_interfaces,
    get_interface_info,
    get_vlan_interfaces,
    delete_vlan_interface,
    get_bond_interfaces,
    delete_bond_interface,
    create_bond,
    create_vlan,
    save_state,
    apply_state,
)

class OpenBondConfig(Message):
    def __init__(self, d_iface: dict) -> None:
        self.d_iface = d_iface
        super().__init__()

class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(self.message, id="confirm"),
            Button("Yes", variant="error", id="yes"),
            Button("No", variant="primary", id="no"),
            id="confirm_dialog"
        )
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

class ListVlan(Widget):
    l_vlan_header = [
        "Name", "Base Interface", "VLAN ID", "IP Address", "State", "Delete"
    ]

    def compose(self) -> ComposeResult:
        yield DataTable(id="vlan_table")

    def on_mount(self) -> None:
        table = self.query_one("#vlan_table", DataTable)
        table.add_columns(*self.l_vlan_header)
        self.refresh_table()

    def refresh_table(self) -> None:
        table = self.query_one("#vlan_table", DataTable)
        table.clear()
        l_vlan_data = get_vlan_interfaces()
        for name, base, vid, ip, state in l_vlan_data:
            table.add_row(name, base, vid, ip, state, "[bold red]DELETE[/]")

    def check_confirm(result: bool) -> None:
        if result:
            delete_vlan_interface(vlan_name)
            self.notify(f"VLAN {vlan_name} deleted.")
            self.refresh_table()
            self.app.refresh_dashboard_interface_table()

    def on_data_table_cell_selected(self,
            event: DataTable.CellSelected) -> None:
        if event.coordinate.column == 5:
            table = self.query_one("#vlan_table", DataTable)
            row_data = table.get_row_at(event.coordinate.row)
            vlan_name = row_data[0]
            s_msg = f"Are you sure to delete VLAN '{vlan_name}'?"
            self.app.push_screen(ConfirmScreen(s_msg), self.check_confirm)

class ListBond(Widget):
    l_bond_header = ["Name", "Ports", "Mode", "State", "Edit", "Delete"]
    l_bond_data = get_bond_interfaces()

    def compose(self) -> ComposeResult:
        yield DataTable(id="bond_table")

    def on_mount(self) -> None:
        table = self.query_one("#bond_table", DataTable)
        table.add_columns(*self.l_bond_header)
        for name, ports, mode, state in self.l_bond_data:
            table.add_row(name, ports, mode, state, "EDIT", "DELETE")

    def on_data_table_cell_selected(self,
            event: DataTable.CellSelected) -> None:
        cell_key = event.cell_key
        value = event.value
        if event.coordinate.column in [4, 5]:
            row_index = event.coordinate.row
            table = self.query_one("#bond_table", DataTable)
            row_data = table.get_row_at(row_index)
            bond_name = row_data[0]
            if value == "DELETE":
                delete_bond_interface(bond_name)
                self.refresh_table()
                self.app.refresh_dashboard_interface_table()
                self.notify(f"Deleted {bond_name}")
            if value == "EDIT":
                d_iface = get_interface_info(bond_name)
                self.post_message(OpenBondConfig(d_iface))

    def refresh_table(self) -> None:
        table = self.query_one("#bond_table", DataTable)
        table.clear()
        self.l_bond_data = get_bond_interfaces()
        for name, ports, mode, state in self.l_bond_data:
            table.add_row(name, ports, mode, state, "EDIT", "DELETE")


class BondConfigScreen(ModalScreen[dict]):
    MODES = [
        "balance-rr",
        "active-backup",
        "balance-xor",
        "broadcast",
        "802.3ad",
        "balance-tlb",
        "blanace-alb",
    ]
    def __init__(self, d_iface: Optional[dict] = None):
        super().__init__()
        if d_iface:
            self.bond_name = d_iface.get("name", "")
            link_aggr = d_iface.get("link-aggregation", {})
            self.bond_ports = link_aggr.get("port", [])
            self.bond_mode = link_aggr.get("mode", "active-backup")
        else:
            self.bond_name = ""
            self.bond_ports = []
            self.bond_mode = "active-backup"
        self.bond_mode_list = []

    def _update_bond_mode_list(self) -> None:
        self.bond_mode_list = [
            (mode_name, True if mode_name == self.bond_mode else False)
            for mode_name in self.MODES
        ]

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
        self.update_name()
        self.update_port_list()
        self.update_mode_list()

    def update_name(self) -> None:
        self.query_one("#bn").value = self.bond_name

    def update_port_list(self) -> None:
        selection_list = self.query_one("#port_list", SelectionList)
        l_iface = list_interfaces(["ethernet"])
        options = [(iface["name"], iface["name"], True if iface["name"] in
            self.bond_ports else False) for iface in l_iface]
        selection_list.add_options(options)

    def update_mode_list(self) -> None:
        radioset = self.query_one("#mode_list", RadioSet)
        radioset.remove_children()
        self._update_bond_mode_list()
        radioset.mount(
            *(RadioButton(bname, value=bsel) for bname, bsel in
                self.bond_mode_list)
        )

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed:
            self.bond_mode = str(event.pressed.label)
            radioset = self.query_one("#mode_list", RadioSet)
            for btn in radioset.query(RadioButton):
                if btn == event.pressed:
                    btn.value = True
                else:
                    btn.value = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.bond_name = self.query_one("#bn", Input).value
            port_list_select = self.query_one("#port_list", SelectionList)
            self.bond_ports = port_list_select.selected
            d_result = {
                "name": self.bond_name,
                "ports": self.bond_ports,
                "mode": self.bond_mode
            }
            self.dismiss(d_result)
        else:
            self.dismiss(None)

class VlanConfigScreen(ModalScreen[dict]):
    def __init__(self, base_iface: str = "bond0"):
        super().__init__()
        self.base_iface = base_iface

    def compose(self) -> ComposeResult:
        yield Label(f"VLAN Configuration (Base: {self.base_iface})")
        with Horizontal():
            yield Label("VLAN Name")
            yield Input(id="vn", placeholder="e.g. bond0.100")
        with Horizontal():
            yield Label("VLAN ID")
            yield Input(id="vid", placeholder="1-4094")
        with Horizontal():
            yield Label("IP Addr")
            yield Input(id="vip", placeholder="192.168.21.100")
            yield Input(id="vprefix", value="24")
        with Horizontal():
            yield Label("Gateway")
            yield Input(id="vgw")
        with Horizontal():
            yield Button("Save", id="save", variant="primary")
            yield Button("Cancel", id="cancel", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            try:
                vname = self.query_one("#vn", Input).value.strip()
                vid = int(self.query_one("#vid", Input).value)
                vip = self.query_one("#vip", Input).value.strip()
                vprefix = int(self.query_one("#vprefix", Input).value)
                vgw = self.query_one("#vgw", Input).value.strip()

                if not (1 <= vid <= 4094):
                    raise ValueError("VLAN ID should be between 1 and 4094.")
                if vip:
                    ipaddress.IPv4Address(vip)
                if not (0 <= vprefix <= 32):
                    raise ValueError("Prefix should be between 0 and 32.")
                if vgw:
                    ipaddress.IPv4Address(vgw)

                d_result = {
                    "name": vname,
                    "base": self.base_iface,
                    "id": vid,
                    "ip": vip,
                    "prefix": vprefix,
                    "gw": vgw
                }
                self.dismiss(d_result)
            except ValueError as e:
                self.notify("Input error: {str(e)}", severity="error")
        else:
            self.dismiss(None)

class HostNetwork(VerticalScroll):

    def on_open_bond_config(self, message: OpenBondConfig) -> None:
        d_iface = message.d_iface
        self.app.push_screen(BondConfigScreen(d_iface), self.save_bondconfig)

    def save_bondconfig(self, result: Optional[dict] = None) -> None:
        if result:
            d_state = create_bond(result["name"], result["ports"],
                result["mode"])
            save_state(f"{result['name']}.yml", d_state)
            apply_state(d_state)
            self.notify(f"Configured {result['name']}")
            self.query_one(ListBond).refresh_table()
            self.app.refresh_dashboard_interface_table()
    
    def save_vlanconfig(self, result: dict) -> None:
        if result:
            d_state = create_vlan(
                result["name"],
                result["base"],
                result["id"],
                result["ip"],
                result["prefix"],
                result["gw"]
            )
            save_state(f"{result['name']}.yml", d_state)
            apply_state(d_state)

            self.notify(f"VLAN {result['name']} created on {result['base']}")
            self.query_one(ListVlan).refresh_table()
            self.app.refresh_dashboard_interface_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bond-create":
            self.app.push_screen(BondConfigScreen(), self.save_bondconfig)
        if event.button.id == "vlan-create":
            self.app.push_screen(VlanConfigScreen(), self.save_vlanconfig)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("VLAN", classes="title")
            yield Button(label="Create", id="vlan-create", variant="primary")
        yield ListVlan(id="vlan_list_widget")
        with Horizontal():
            yield Label("Bonding", classes="title")
            yield Button(label="Create", id="bond-create", variant="primary")
        yield ListBond()
        
