import logging
import os
import shutil
import socket
import sys
import subprocess
from contextlib import contextmanager
from datetime import datetime
from textual.app import App, ComposeResult
from textual.containers import Grid, HorizontalScroll, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button, Footer, Header, Label,
    TabbedContent, TabPane, RichLog
)
from bcocinero import TITLE, SUB_TITLE, __version__
from bcocinero.common_logger import BcocineroLogger
from bcocinero.dashboard import Dashboard
from bcocinero.hostnetwork import HostNetwork
from bcocinero.installer import Installer

from bcocinero.nm_helpers import (
    NetworkManager,
    NodeRole
)

class QuitScreen(ModalScreen[bool]):
    def compose(self) -> ComposeResult:
        yield Grid(
            Label("Are you sure you want to quit the program?", id="confirm"),
            Button("Quit", variant="error", id="quit-btn"),
            Button("Cancel", variant="primary", id="cancel-btn"),
            id="confirm_dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

class BcocineroScreen(Screen):
    CSS_PATH = ["app.tcss"]
    BINDINGS = [
        ("d", "switch_tab('dashboard')", "Dashboard"),
        ("n", "switch_tab('network')", "Network"),
        ("i", "switch_tab('installer')", "Installer"),
        ("ctrl+l", "clear_logs", "Clear Logs"),
    ]
    
    def action_clear_logs(self) -> None:
        try:
            self.query_one("#main_log", RichLog).clear()
            logging.info("Cleared logs.")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        self.header = Header(show_clock=True, icon="B")
        yield self.header
        with TabbedContent(initial="dashboard", id="main"):
            with TabPane("[red][b]D[/b][/red]ashboard", id="dashboard"):
                yield Dashboard()
            with TabPane("[red][b]N[/b][/red]etwork", id="network"):
                yield HostNetwork()
        yield RichLog(id="main_log", auto_scroll=True, markup=True,
                      highlight=True)
        yield Footer(show_command_palette=False)

    def action_switch_tab(self, tab: str) -> None:
        try:
            tabbed_content = self.query_one("#main", TabbedContent)
            if tab == "installer" and not tabbed_content.get_pane("installer"):
                return
            tabbed_content.active = tab
        except Exception:
            pass

    def on_mount(self) -> None:
        if hasattr(self.app, "bc_logger"):
            self.set_timer(0.5, lambda: self.app.bc_logger.load_prev_logs(3))
        self.update_tabs_visibility()

    def update_tabs_visibility(self) -> None:
        try:
            nm = NetworkManager()
            host_data = nm.get_host_info()
            tabbed_content = self.query_one("#main", TabbedContent)

            is_head_control = (host_data.get("role") == NodeRole.HEAD.value)
            try:
                tabbed_content.get_pane("installer")
                has_installer_pane = True
            except Exception:
                has_installer_pane = False

            if is_head_control and not has_installer_pane:
                new_pane = TabPane(
                    "[red][b]I[/b][/red]nstaller", Installer(), id="installer"
                )
                tabbed_content.add_pane(new_pane)
            elif not is_head_control and has_installer_pane:
                if tabbed_content.active == "installer":
                    tabbed_content.active = "dashboard"
                tabbed_content.remove_pane("installer")
        except Exception as e:
            logging.error(f"Failed to update tab visibility layout: {str(e)}")

class Bcocinero(App):
    """Burrito Chef"""
    APP_VERSION = f"v{__version__}"
    LEVEL_COLORS = {
        "INFO": "green",
        "WARN": "yellow",
        "ERROR": "red",
    }
    BINDINGS = [("ctrl+q", "request_quit", f"Quit ({APP_VERSION})")]

    def action_request_quit(self) -> None:
        def check_quit(b_quit: bool) -> None:
            if b_quit:
                self.exit()
        self.push_screen(QuitScreen(), check_quit)

    def post_log(self, msg: str, level: str = "INFO") -> None:
        try:
            log_widget = self.screen.query_one("#main_log", RichLog)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            color = self.LEVEL_COLORS.get(level, "green")
            log_widget.write(f"{timestamp} [[bold {color}]{level}[/]] {msg}")
        except Exception:
            pass

    def refresh_dashboard_interface_table(self):
        try:
            self.screen.query_one("#dashboard_interface").refresh_table()
        except NoMatches:
            self.log("Cannot find #dashboard_interface widget")

    def on_mount(self) -> None:
        self.title = f"{TITLE}@{socket.gethostname()}"
        self.sub_title = SUB_TITLE
        self.version = self.APP_VERSION

    def on_ready(self) -> None:
        self.bc_logger = BcocineroLogger(self)
        self.push_screen(BcocineroScreen())

def _is_console() -> bool:
    try:
        ttyname = os.ttyname(sys.stdout.fileno())
        return ttyname.startswith("/dev/tty")
    except Exception:
        return False

@contextmanager
def mute_console_messages():
    is_mute = _is_console()
    original_printk = None

    if is_mute:
        try:
            result = subprocess.run(
                ["sysctl", "-n", "kernel.printk"],
                capture_output=True, text=True, check=True
            )
            original_printk = result.stdout.strip()

            subprocess.run(
                ["sudo", "sysctl", "-w", "kernel.printk=1 4 1 7"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=True
            )
        except FileNotFoundError:
            original_printk = None

    try:
        yield
    finally:
        if is_mute and original_printk:
            try:
                subprocess.run(
                    ["sudo", "sysctl", "-w",
                     f"kernel.printk={original_printk}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    check=True
                )
            except Exception:
                pass

def entrypoint() -> None:
    # check terminal size
    MIN_COLS = 80
    MIN_ROWS = 24
    DEFAULT_TERM = "xterm-256color"

    cols, rows = shutil.get_terminal_size(fallback=(0, 0))
    if cols == 0 and rows == 0:
        os.environ["COLUMNS"] = "80"
        os.environ["LINES"] = "24"
        try:
            os.system("stty cols 80 rows 24 2>/dev/null")
        except Exception:
            pass
        else:
            cols, rows = shutil.get_terminal_size(fallback=(0, 0))

    if cols < MIN_COLS or rows < MIN_ROWS:
        print(f"Error: terminal size ({cols}x{rows}) is smaller than the required size ({MIN_COLS}x{MIN_ROWS}).")
        sys.exit(1)
    os.environ["TERM"] = DEFAULT_TERM

    app = Bcocinero()
    with mute_console_messages():
        app.run()

if __name__ == "__main__":
    entrypoint()
