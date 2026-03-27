from datetime import datetime
from textual.app import App, ComposeResult
from textual.containers import HorizontalScroll, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, TabbedContent, TabPane
from bcocinero.dashboard import Dashboard
from bcocinero.hostnetwork import HostNetwork
from bcocinero.installer import Installer

class StatusBar(Widget):
    message = reactive("Ready")
    display_msg = reactive("")

    def watch_message(self, msg: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.display_msg = f"[{timestamp}] {msg}"

    def render(self) -> str:
        return f"{self.display_msg}"

class BcocineroScreen(Screen):
    CSS_PATH = ["app.tcss"]
    BINDINGS = [
        ("d", "switch_tab('dashboard')", "Dashboard"),
        ("n", "switch_tab('network')", "Network"),
        ("i", "switch_tab('installer')", "Installer"),
    ]
    def compose(self) -> ComposeResult:
        self.header = Header(show_clock=True, icon="B")
        self.footer = Footer(show_command_palette=False)
        yield self.header
        with TabbedContent(initial="dashboard", id="main"):
            with TabPane("[red][b]D[/b][/red]ashboard", id="dashboard"):
                yield Dashboard()
            with TabPane("[red][b]N[/b][/red]etwork", id="network"):
                yield HostNetwork()
            with TabPane("[red][b]I[/b][/red]nstaller", id="installer"):
                yield Installer()
        yield StatusBar(id="main_status_bar")
        #yield self.footer

    def action_switch_tab(self, tab: str) -> None:
        self.query_one("#main", TabbedContent).active = tab

class Bcocinero(App):
    """Burrito Chef"""

    def write_status(self, msg: str) -> None:
        try:
            self.screen.query_one("#main_status_bar").message = msg
        except NoMatches:
            self.log("Cannot find #main_status_bar widget")

    def refresh_dashboard_interface_table(self):
        try:
            self.screen.query_one("#dashboard_interface").refresh_table()
        except NoMatches:
            self.log("Cannot find #dashboard_interface widget")

    def on_mount(self) -> None:
        self.title = "BCocinero"
        self.sub_title = "Installer for Burrito"

    def on_ready(self) -> None:
        self.push_screen(BcocineroScreen())


def entrypoint() -> None:
    app = Bcocinero()
    app.run()

if __name__ == "__main__":
    entrypoint()
