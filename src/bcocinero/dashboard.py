# src/bcocinero/dashboard.py
import asyncio
import inspect
import os
import re
import ipaddress
import logging
from pathlib import Path
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.containers import (
    Container, Horizontal, HorizontalScroll, Vertical, VerticalScroll
)
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button, DataTable, Header, Input, Label,
    OptionList, RichLog, Select, Static, Switch
)
from typing import Optional, Dict, Any, List

from bcocinero.nm_helpers import (
    NetworkManager,
    ArtifactManager,
    ProfileType,
    NodeRole
)
from bcocinero.install_tracker import InstallTracker
from bcocinero import TITLE

_HOSTNAME_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)
nm = NetworkManager()
am = ArtifactManager()

class Hostname(Widget):
    hostname: reactive[str] = reactive("")
    nameserver: reactive[str] = reactive("")
    role: reactive[str] = reactive("")

    def on_mount(self) -> None:
        host_data = nm.get_host_info()
        self.hostname = host_data["hostname"]
        self.nameserver = ",".join(host_data["nameservers"])
        self.role = host_data["role"]
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

class PlaybookLogScreen(ModalScreen):
    def __init__(self, playbook_name: str) -> None:
        super().__init__()
        self.playbook_name = playbook_name
        self.log_path = am.base_dir / f"{playbook_name}.log"

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-container"):
            yield Label(f"Cooked: {self.playbook_name}", classes="title")
            yield RichLog(id="log_viewer", classes="modal-log-window",
                          highlight=True, markup=True)
            yield Button("Close", id="close_log_modal", variant="error")

    def on_mount(self) -> None:
        log_viewer = self.query_one("#log_viewer", RichLog)
        if not self.log_path.exists():
            log_viewer.write(f"Error: Log file not found: {self.log_path}.")
            return

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    log_viewer.write(escape(line.rstrip()))
        except Exception as e:
            log_viewer.write(f"Failed to read log file: {str(e)}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_log_modal":
            self.dismiss()

class HostConfigScreen(ModalScreen[dict]):
    def __init__(self,
                 s_hostname: str,
                 s_nameserver: str,
                 s_role: str,
                 s_hc_ip: str):
        super().__init__()
        self.init_hostname = s_hostname
        self.init_nameserver = s_nameserver
        self.init_role = s_role if s_role else NodeRole.HEAD.value
        self.init_hc_ip = s_hc_ip
        self.role_options = [
            (item.value, item.value)
            for item in NodeRole if item != NodeRole.NONE
        ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal_container"):
            yield Label("Host Configuration", classes="title")
            with Horizontal():
                yield Label("Hostname: ", classes="label-fixed")
                yield Input(value=self.init_hostname, id="hn")
            with Horizontal():
                yield Label("Role: ", classes="label-fixed")
                yield Select(
                    self.role_options, value=self.init_role,
                    id="role", type_to_search=True, allow_blank=False
                )
            with Horizontal(id="hc_ip_container", classes="hidden"):
                yield Label("Head Control IP", classes="label-fixed")
                yield Input(placeholder="Enter Head Control IP address", 
                        id="hc_ip", value=self.init_hc_ip)
            with Horizontal():
                yield Label("Nameserver: ", classes="label-fixed")
                yield Input(value=self.init_nameserver, id="ns")
            with Horizontal(classes="modal_buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel", variant="error")

    def on_mount(self) -> None:
        self._toggle_ip_input(self.init_role)

    def on_select_changed(self, event: Select.Changed) -> None:
        self._toggle_ip_input(event.value)

    def _toggle_ip_input(self, role_value: str) -> None:
        container = self.query_one("#hc_ip_container")
        if role_value == NodeRole.HEAD.value:
            container.display = False
        else:
            container.display = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            hn_val = self.query_one("#hn", Input).value.strip()
            ns_val = self.query_one("#ns", Input).value.strip()
            role_val = self.query_one("#role", Select).value
            hc_ip_val = self.query_one("#hc_ip", Input).value.strip()

            if not hn_val or not ns_val or role_val == Select.NULL:
                self.app.notify("Enter hostname, nameservers and select role",
                                severity="error")
                return
            if not _HOSTNAME_RE.match(hn_val):
                self.app.notify("Invalid hostname format.", severity="error")
                return
            if role_val != NodeRole.HEAD.value:
                try:
                    ipaddress.ip_address(hc_ip_val)
                except ValueError:
                    self.app.notify("Head Control IP is not valid.",
                                    severity="error")
                    return
                except AttributeError:
                    self.app.notify(f"Enter Head Control IP: {hc_ip_val}",
                                    severity="error")
                    return

            self.dismiss({
                "hostname": hn_val,
                "nameserver": ns_val,
                "role": role_val,
                "hc_ip": hc_ip_val,
            })
        else:
            self.dismiss(None)

class Dashboard(VerticalScroll):
    def __init__(self) -> None:
        super().__init__()
        self.tracker = None

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
            if not b_ret:
                logging.error(s_msg)
                return

            if result["hc_ip"]:
                b_ret, s_msg = nm.set_head_control_ip(result["hc_ip"])
                if not b_ret:
                    logging.error(s_msg)
                    return

            hostname_widget = self.query_one(Hostname)
            hostname_widget.hostname = result["hostname"]
            hostname_widget.nameserver = result["nameserver"]
            hostname_widget.role = result["role"]

            # update app title appending hostname
            self.app.title = f"{TITLE}@{result['hostname']}"

            self._toggle_installer_visibility(result["role"])
            if hasattr(self.app.screen, "update_tabs_visibility"):
                self.app.screen.update_tabs_visibility()

            logging.info("Configured host information")
        except Exception as e:
            logging.error(f"Failed to configure: {str(e)}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "host-config":
            h_widget = self.query_one(Hostname)
            hdata = nm.get_host_info()
            self.app.push_screen(
                HostConfigScreen(
                    h_widget.hostname,
                    h_widget.nameserver,
                    h_widget.role,
                    hdata["hc_ip"]
                ),
                self.save_hostconfig
            )
        elif event.button.id and event.button.id.startswith("log_btn_"):
            playbook_name = getattr(event.button, "playbook_name", "")
            if playbook_name:
                self.app.push_screen(PlaybookLogScreen(playbook_name))

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
        with Vertical(id="dashboard_installer_container",
                      classes="dashboard_installer"):
            yield Label("Installer", classes="title")
            with Container(id="dashboard_installer_status_block"):
                with Horizontal():
                    yield Static("", id="prep_progress_view", markup=True)
                with Horizontal(id="installer_buttons_container"):
                    pass

    async def on_mount(self) -> None:
        interval = 10.0

        host_data = nm.get_host_info()
        self._toggle_installer_visibility(host_data.get("role",""))
        await asyncio.sleep(0)

        if inspect.iscoroutinefunction(self._update_installation_progress):
            await self._update_installation_progress()
        else:
            self._update_installation_progress()

        self.set_interval(interval, self._update_installation_progress)

    def _toggle_installer_visibility(self, role: str) -> None:
        try:
            container = self.query_one("#dashboard_installer_container")
            is_head = (role == NodeRole.HEAD.value)
            container.display = is_head
            
            if is_head and self.tracker is None:
                self.tracker = InstallTracker()
            elif not is_head and self.tracker is not None:
                self.tracker = None
        except Exception:
            logging.error("Failed to set installer block visibility")
            pass

    async def _update_installation_progress(self) -> None:
        try:
            container = self.query_one("#dashboard_installer_container")
            if not container.display or self.tracker is None:
                return
        except Exception:
            return

        prep_markup = self.tracker.get_prep_status()
        cook_status = self.tracker.get_playbooks_status()

        try:
            self.query_one("#prep_progress_view", Static).update(prep_markup)
        except Exception:
            pass

        try:
            btn_container = self.query_one("#installer_buttons_container")

            focused_id = None
            c_focus = self.app.focused
            if c_focus is not None and str(c_focus.id).startswith("log_btn_"):
                focused_id = c_focus.id

            btn_container.remove_children()
            await asyncio.sleep(0)

            if not cook_status:
                btn_container.mount(
                    Label("[yellow]Cook: It has not been cooked.[/]")
                )
                return

            btn_container.mount(Label("[bold]Cook:[/]"))
            for name, state in cook_status:
                button_id = f"log_btn_{name}"
                label = name
                if state == "pass":
                    variant = "success"
                    disabled = False
                elif state == "fail":
                    variant = "error"
                    disabled = False
                else:
                    variant = "default"
                    disabled = True
                btn = Button(label, id=button_id, variant=variant)
                btn.disabled = disabled
                btn.playbook_name = name
                btn_container.mount(btn)

            if focused_id:
                try:
                    new_btn = btn_container.query_one(f"#{focused_id}")
                    if not new_btn.disabled:
                        new_btn.focus()
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"Fail to update installer block: {e}")
