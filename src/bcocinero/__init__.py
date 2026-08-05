from importlib.metadata import PackageNotFoundError, version

TITLE="CloudX"
SUB_TITLE="TUI Installer"

try:
    __version__ = version("bcocinero")
except PackageNotFoundError:
    __version__ = "dev"
