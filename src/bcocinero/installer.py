import logging
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, ProgressBar, Static

from bcocinero.nm_helpers import NetworkManager, InventoryGenerator
from bcocinero.db import BcocineroDB
from bcocinero.prep import Prep

nm = NetworkManager()

class ListHost(Widget):
    l_host_header = ["Name", "IP", "Role", "State"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db_hostdata = []
        self.logger = logging.getLogger("bcocinero")

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
        self.db_hostdata = db.get_all_hosts()
        l_host_data = [tuple(d.values()) for d in self.db_hostdata]
        for row in l_host_data:
            table.add_row(*row)

    def create_inventory(self) -> None:
        if not self.db_hostdata:
            self.logger.error("No host data available to create inventory.")
            return

        gen = InventoryGenerator(self.db_hostdata)
        gen.generate("/tmp/hosts")
        self.logger.info(f"Created an inventory file: hosts")


class Installer(VerticalScroll):

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hosts-refresh":
            self.query_one(ListHost).refresh_table()
        if event.button.id == "create-inventory":
            self.query_one(ListHost).create_inventory()
        if event.button.id == "installer-prepare":
            self.run_prep_task()

    @work(exclusive=True, thread=True)
    async def run_prep_task(self) -> None:
        btn = self.query_one("#installer-prepare", Button)
        bar = self.query_one("#prep-progress", ProgressBar)
        status = self.query_one("#prep-status", Static)

        btn.disbled = True
        bar.progress = 0

        try:
            prep_engine = Prep()
            for progress, message in prep_engine.run_prep_gen():
                bar.progress = progress
                status.update(f"[cyan]{message}[/]")
            logging.info("Prep process is completed successfully.")
        except Exception as e:
            status.update(f"[bold red]{str(e)}[/]")
        finally:
            btn.disabled = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Hosts", classes="title")
            yield Button(label="Refresh", id="hosts-refresh",
                         variant="primary")
            yield Button(label="Inventory", id="create-inventory",
                         variant="primary")
        yield ListHost(id="host_list_widget")
        with Horizontal(id="installer_block"):
            yield Label("Installer", classes="title")
            yield Button(label="Prep", id="installer-prepare",
                         variant="primary")
            yield Button(label="Recipe", id="installer-recipe",
                         variant="primary")
        yield Static("", id="prep-status")
        yield ProgressBar(id="prep-progress", total=1.0, show_bar=True)

