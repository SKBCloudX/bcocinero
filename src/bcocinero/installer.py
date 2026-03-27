from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

class Installer(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Installer")

