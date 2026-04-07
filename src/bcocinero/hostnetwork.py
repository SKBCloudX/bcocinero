import ipaddress
from typing import Optional, Dict, Any, List, Tuple
from textual import log
from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, SelectionList
from textual.widgets import RadioSet, RadioButton, Select

from bcocinero.nm_helpers import NetworkManager, ArtifactManager

nm = NetworkManager()
am = ArtifactManager()

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
        "Name", "Base Interface", "VLAN ID", "IP Address", "State",
        "Edit", "Delete"
    ]

    def compose(self) -> ComposeResult:
        yield DataTable(id="vlan_table",
                zebra_stripes=True,
                fixed_rows=1)

    def on_mount(self) -> None:
        table = self.query_one("#vlan_table", DataTable)
        table.add_columns(*self.l_vlan_header)
        self.refresh_table()

    def refresh_table(self) -> None:
        table = self.query_one("#vlan_table", DataTable)
        table.clear()
        l_vlan_data = nm.get_vlan_interfaces()
        for row in l_vlan_data:
            table.add_row(
                *row,
                "[#000000 on #00afaf]EDIT[/]",
                "[#ffffff on #af0000]DELETE[/]"
            )

    def on_data_table_cell_selected(self,
                                    event: DataTable.CellSelected) -> None:
        col = event.coordinate.column
        row_index = event.coordinate.row
        table = self.query_one("#vlan_table", DataTable)
        row_data = table.get_row_at(row_index)
        vlan_name = row_data[0]
        if col == 5: # EDIT
            iface_info =nm.get_interface_info(vlan_name)

            ipv4_data = iface_info.get("ipv4", {}).get("address", [])
            ip_str = ipv4_data[0].get("ip", "") if ipv4_data else ""
            prefix_val = ipv4_data[0].get("prefix-length", 24) if ipv4_data else 24
            
            gw_info = nm.get_default_gateway()
            gw_str = gw_info["gateway"] if gw_info and gw_info["interface"] == vlan_name else ""

            d_vlan = {
                "name": vlan_name,
                "base": row_data[1],
                "id": int(row_data[2]),
                "ip": ip_str,
                "prefix": prefix_val,
                "gw": gw_str
            }
            self.app.push_screen(VlanConfigScreen(d_vlan), self.parent.save_vlanconfig)
        elif col == 6:  # DELETE
            s_msg = f"Are you sure to delete VLAN '{vlan_name}'?"
            self.app.push_screen(ConfirmScreen(s_msg),
                lambda result: self.check_confirm(result, vlan_name))

    def check_confirm(self, result: bool, vlan_name: str) -> None:
        if result:
            try:
                state = nm.delete_interface_state(vlan_name)
                nm.apply_state(state)
                
                self.app.write_status(f"VLAN {vlan_name} is deleted.")
                self.refresh_table()
                self.app.refresh_dashboard_interface_table()
            except Exception as e:
                self.app.write_status(f"Failed to delete: {e}")

class VlanConfigScreen(ModalScreen[dict]):
    def __init__(self, d_vlan: Optional[dict] = None):
        super().__init__()
        self.is_edit_mode = d_vlan is not None
        self.bond_data = nm.get_bond_interfaces()
        self.bond_options = [(bond[0], bond[0]) for bond in self.bond_data]

        if d_vlan:
            self.orig_base = d_vlan.get("base", "")
            self.orig_vid = str(d_vlan.get("id", ""))
            self.orig_ip = d_vlan.get("ip", "")
            self.orig_prefix = str(d_vlan.get("prefix", "24"))
            self.orig_gw = d_vlan.get("gw", "") or ""
        else:
            self.orig_base = ""
            self.orig_vid = ""
            self.orig_ip = ""
            self.orig_prefix = "24"
            self.orig_gw = ""


    def compose(self) -> ComposeResult:
        yield Label("VLAN Configuration", id="modal_title")
        with Horizontal():
            yield Label("Base Interface", classes="label-fixed")
            yield Select(self.bond_options, id="base_iface",
                         disabled=self.is_edit_mode,
                         prompt="Select Bond Interface")
        with Horizontal():
            yield Label("VLAN ID", classes="label-fixed")
            yield Input(id="vid",
                        value=self.orig_vid,
                        placeholder="1-4094", restrict=r"^[0-9]*$",
                        disabled=self.is_edit_mode)
        with Horizontal():
            yield Label("IP Addr / Prefix", classes="label-fixed")
            yield Input(id="vip", value=self.orig_ip,
                        placeholder="IP address (e.g. 192.168.21.100)")
            yield Label("/", id="slash")
            yield Input(id="vprefix", value=self.orig_prefix,
                        restrict=r"^[0-9]*$")
        with Horizontal():
            yield Label("Gateway", classes="label-fixed")
            yield Input(id="vgw", value=self.orig_gw,
                        placeholder="Gateway IP (e.g. 192.168.21.1)")
        with Horizontal(classes="modal_buttons"):
            yield Button("Save", id="save", variant="primary")
            yield Button("Cancel", id="cancel", variant="error")

    def on_mount(self) -> None:
        base_iface_widget = self.query_one("#base_iface", Select)
        if self.orig_base:
            base_iface_widget.value = self.orig_base

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            try:
                vip = self.query_one("#vip", Input).value.strip()
                prefix_text = self.query_one("#vprefix", Input).value.strip()
                vgw = self.query_one("#vgw", Input).value.strip()

                if self.is_edit_mode:
                    is_changed = (
                        vip != self.orig_ip or
                        prefix_text != self.orig_prefix or
                        vgw != self.orig_gw
                    )
                    if not is_changed:
                        s_vlan_name = f"{self.orig_base}.{self.orig_vid}"
                        self.notify(f"No changes for VLAN {s_vlan_name}")
                        self.dismiss(None)
                        return

                base_iface = self.query_one("#base_iface", Select).value
                if base_iface is Select.NULL:
                    raise ValueError("Please select the base interface.")

                vid_text = self.query_one("#vid", Input).value
                if not vid_text: raise ValueError("VLAN ID is required.")
                vid = int(vid_text)
                if not (1 <= vid <= 4094):
                    raise ValueError("VLAN ID should be between 1 and 4094.")

                if not vip: raise ValueError("IP address is required.")
                ipaddress.IPv4Address(vip)

                if not prefix_text: raise ValueError("Prefix is required.")
                prefix = int(prefix_text)
                if not (0 <= prefix <= 32):
                    raise ValueError("Prefix should be between 0 and 32.")

                if vgw: ipaddress.IPv4Address(vgw)

                self.dismiss({
                    "name": f"{base_iface}.{vid}",
                    "base": base_iface,
                    "id": vid,
                    "ip": vip,
                    "prefix": prefix,
                    "gw": vgw if vgw else None
                })
            except ValueError as e:
                self.notify(f"Input error: {e}", severity="error")
        else:
            self.dismiss(None)


class ListBond(Widget):
    l_bond_header = ["Name", "Ports", "Mode", "State", "Edit", "Delete"]

    def compose(self) -> ComposeResult:
        yield DataTable(id="bond_table",
                        zebra_stripes=True,
                        fixed_rows=1)

    def on_mount(self) -> None:
        table = self.query_one("#bond_table", DataTable)
        table.add_columns(*self.l_bond_header)
        self.refresh_table()

    def refresh_table(self) -> None:
        table = self.query_one("#bond_table", DataTable)
        table.clear()
        l_bond_data = nm.get_bond_interfaces()
        for row in l_bond_data:
            table.add_row(
                *row,
                "[#000000 on #00afaf] EDIT [/]",
                "[#ffffff on #af0000] DELETE [/]"
            )

    def on_data_table_cell_selected(self,
                                    event: DataTable.CellSelected) -> None:
        col = event.coordinate.column
        row_index = event.coordinate.row
        table = self.query_one("#bond_table", DataTable)
        row_data = table.get_row_at(row_index)
        bond_name = row_data[0]

        if col == 4:  # EDIT
            d_iface = nm.get_interface_info(bond_name)
            self.post_message(OpenBondConfig(d_iface))
        elif col == 5:  # DELETE
            s_msg = f"Are you sure to delete Bond '{bond_name}'?"
            self.app.push_screen(ConfirmScreen(s_msg),
                lambda result: self.handle_delete_result(result, bond_name))

    def handle_delete_result(self, result: bool, bond_name: str) -> None:
        if result:
            try:
                state = nm.delete_interface_state(bond_name)
                nm.apply_state(state)
                
                self.refresh_table()
                self.app.refresh_dashboard_interface_table()
                try:
                    list_vlan_widget = self.screen.query_one(ListVlan)
                    list_vlan_widget.refresh_table()
                except Exception:
                    pass
                self.app.write_status(f"{bond_name} is deleted.")
            except Exception as e:
                self.app.write_status(f"Failed to delete: {e}")

class BondConfigScreen(ModalScreen[dict]):
    MODES = [
        "balance-rr", "active-backup", "balance-xor",
        "broadcast", "802.3ad", "balance-tlb", "balance-alb",
    ]

    def __init__(self, d_iface: Optional[dict] = None):
        super().__init__()
        self.is_edit_mode = d_iface is not None

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

    def compose(self) -> ComposeResult:
        yield Label("Bond Configuration", id="modal_title")
        with Horizontal():
            yield Label("Name", classes="label-fixed")
            yield Input(
                placeholder="Enter bonding name",
                id="bn",
                value=self.bond_name,
                disabled=self.is_edit_mode
            )
            if self.is_edit_mode:
                yield Label("Not editable", id="edit_lock_label")
        with Horizontal():
            yield Label("Ports", classes="label-fixed")
            yield SelectionList(id="port_list")
        with Horizontal():
            yield Label("Mode", classes="label-fixed")
            yield RadioSet(id="mode_list")
        with Horizontal(classes="modal_buttons"):
            yield Button("Save", id="save", variant="primary")
            yield Button("Cancel", id="cancel", variant="error")

    def on_mount(self) -> None:
        self.update_port_list()
        self.update_mode_list()

    def update_port_list(self) -> None:
        selection_list = self.query_one("#port_list", SelectionList)
        l_iface = nm.list_interfaces(["ethernet"])
        options = [
            (iface["name"], iface["name"], iface["name"] in self.bond_ports)
            for iface in l_iface
        ]
        selection_list.add_options(options)

    def update_mode_list(self) -> None:
        radioset = self.query_one("#mode_list", RadioSet)
        radioset.remove_children()
        for mode in self.MODES:
            radioset.mount(RadioButton(mode, value=(mode == self.bond_mode)))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed:
            # self.bond_mode = str(event.pressed.label)
            radioset = self.query_one("#mode_list", RadioSet)
            for btn in radioset.query(RadioButton):
                btn.value = True if btn == event.pressed else False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            name = self.query_one("#bn", Input).value.strip()
            ports = sorted(
                self.query_one("#port_list", SelectionList).selected
            )
            rs = self.query_one("#mode_list", RadioSet)
            mode = str(rs.pressed_button.label) if rs.pressed_button else self.bond_mode

            if self.is_edit_mode:
                is_changed = (
                    name != self.bond_name or
                    ports != self.bond_ports or
                    mode != self.bond_mode
                )
                if not is_changed:
                    self.notify(f"No changes for {name}.", severity="info")
                    self.dismiss(None)
                    return

            missing = []
            if not name: missing.append("bond name")
            if not ports: missing.append("bond ports")

            if not missing:
                self.dismiss(
                    {"name": name, "ports": ports, "mode": mode}
                )
            else:
                self.notify(f"Missing: {', '.join(missing)}", severity="error")
        else:
            self.dismiss(None)

class HostNetwork(VerticalScroll):
    """Network Configuration (Bond/VLAN) Manager."""

    def on_open_bond_config(self, message: OpenBondConfig) -> None:
        """Edit existing bond interface message handler."""
        d_iface = message.d_iface
        self.app.push_screen(BondConfigScreen(d_iface), self.save_bondconfig)

    def save_bondconfig(self, result: Optional[dict] = None) -> None:
        """Save bond configuration: Generate state -> Save YAML -> Apply."""
        if result:
            try:
                d_state = nm.create_bond_state(
                    result["name"],
                    result["ports"],
                    result["mode"]
                )
                am.save_state(f"{result['name']}.yml", d_state)
                nm.apply_state(d_state)

                self.app.write_status(f"Configured Bond: {result['name']}")
                self.query_one(ListBond).refresh_table()
                self.app.refresh_dashboard_interface_table()
            except Exception as e:
                self.app.write_status(f"Bond configuration failed: {e}")

    def save_vlanconfig(self, result: Optional[dict] = None) -> None:
        """Save VLAN configuration: Generate state -> Save YAML -> Apply."""
        if result:
            try:
                d_state = nm.create_vlan_state(
                    result["name"],
                    result["base"],
                    result["id"],
                    result["ip"],
                    result["prefix"],
                    result["gw"]
                )
                am.save_state(f"{result['name']}.yml", d_state)
                nm.apply_state(d_state)

                s_msg = f"VLAN {result['name']} created on {result['base']}"
                self.app.write_status(s_msg)
                self.query_one(ListVlan).refresh_table()
                self.app.refresh_dashboard_interface_table()
            except Exception as e:
                self.app.write_status(f"VLAN configuration failed: {e}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Create button event handler."""
        if event.button.id == "bond-create":
            self.app.push_screen(BondConfigScreen(), self.save_bondconfig)
        elif event.button.id == "vlan-create":
            self.app.push_screen(VlanConfigScreen(), self.save_vlanconfig)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Bond", classes="title")
            yield Button(label="Create", id="bond-create", variant="primary")
        yield ListBond(id="bond_list_widget")

        with Horizontal():
            yield Label("VLAN", classes="title")
            yield Button(label="Create", id="vlan-create", variant="primary")
        yield ListVlan(id="vlan_list_widget")

