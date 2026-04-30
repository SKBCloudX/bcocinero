from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label

from bcocinero.nm_helpers import NetworkManager
from bcocinero.db import BcocineroDB

nm = NetworkManager()

class ListHost(Widget):
    l_host_header = ["Name", "IP", "Role", "State"]

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
        data = db.get_all_hosts()
        l_host_data = [tuple(d.values()) for d in data]
        for row in l_host_data:
            table.add_row(*row)

class Installer(VerticalScroll):
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hosts-refresh":
            self.query_one(ListHost).refresh_table()

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Hosts", classes="title")
            yield Button(label="Refresh", id="hosts-refresh",
                         variant="primary")
        yield ListHost(id="host_list_widget")

