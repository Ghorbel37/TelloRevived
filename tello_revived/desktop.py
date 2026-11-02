"""Linux: add Tello Revived to the applications menu (with its icon), or remove it again.

Desktops list programs from small .desktop files (freedesktop.org). The single-file Linux build
has none, so it doesn't show in the menu and gets a generic icon. This writes one for the current
user, pointing at wherever the program is now.
"""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from tello_revived.paths import resource_dir

APP_ID = "tello-revived"  # also the window's class name, so the dock matches it to this entry


def _data_home():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def entry_path():
    return _data_home() / "applications" / f"{APP_ID}.desktop"


def icon_path():
    return _data_home() / "icons" / "hicolor" / "512x512" / "apps" / f"{APP_ID}.png"


def supported():
    return sys.platform.startswith("linux")


def installed():
    return entry_path().exists()


def command():
    """How to start this copy: the built program itself, or this Python with the package."""
    if getattr(sys, "frozen", False):
        return shlex.quote(sys.executable)
    return f"{shlex.quote(sys.executable)} -m tello_revived"


def entry_text():
    return f"""[Desktop Entry]
Type=Application
Name=Tello Revived
Comment=Fly a DJI/Ryze Tello with a gamepad or the keyboard
Exec={command()}
Icon={APP_ID}
Terminal=false
Categories=Game;Utility;
StartupWMClass={APP_ID}
"""


def add():
    """Write the menu entry and copy the icon. Returns None, or what went wrong."""
    try:
        icon_path().parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resource_dir() / "assets" / "logo.png", icon_path())
        entry_path().parent.mkdir(parents=True, exist_ok=True)
        entry_path().write_text(entry_text(), encoding="utf-8")
        entry_path().chmod(0o755)
    except OSError as e:
        return e.strerror or str(e)
    _refresh()
    return None


def remove():
    for path in (entry_path(), icon_path()):
        path.unlink(missing_ok=True)
    _refresh()


def _refresh():
    """Ask the desktop to notice the change (optional: most notice anyway)."""
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(entry_path().parent)], capture_output=True)
