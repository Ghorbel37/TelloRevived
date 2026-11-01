"""Where Tello Revived keeps its files."""

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent.parent  # the repository, when running from source


def data_dir():
    """Where config.json and media/ go.

    From source: the repository folder. Built app: next to the exe (macOS: ~/Tello Revived, since
    the .app bundle shouldn't be written to). Installed as a package: ~/Tello Revived.
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Tello Revived"
        return Path(sys.executable).resolve().parent
    if (SOURCE_DIR / "pyproject.toml").exists():
        return SOURCE_DIR
    return Path.home() / "Tello Revived"


def resource_dir():
    """Where bundled files (assets/) are: the repository, or PyInstaller's unpack folder."""
    return Path(getattr(sys, "_MEIPASS", SOURCE_DIR))


CONFIG_PATH = data_dir() / "config.json"
MEDIA_DIR = data_dir() / "media"
ICON_PATH = resource_dir() / "assets" / "icon.png"
