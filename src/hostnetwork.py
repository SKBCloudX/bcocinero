from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

class HostNetwork(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Host and Network")

