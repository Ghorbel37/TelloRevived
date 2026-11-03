"""Find the drone's Wi-Fi network and connect to it, with the system's own tools.

Windows: netsh. Linux: NetworkManager's nmcli. macOS: networksetup and system_profiler.
A Tello's network is called TELLO-XXXXXX (RMTT-XXXXXX for a RoboMaster TT) and has no password.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tello_revived.i18n import t

DRONE_NETWORK = re.compile(r"^(TELLO|RMTT)-\w+$")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flashing up on Windows


def _call(*cmd, timeout=15):
    """(exit code, output as text) of a command; (-1, "") if it can't run."""
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""
    # netsh prints in the console code page ("oem"), which isn't UTF-8 on most Windows setups
    encoding = "oem" if sys.platform == "win32" else "utf-8"
    return result.returncode, (result.stdout + result.stderr).decode(encoding, "replace")


def _run(*cmd, timeout=15):
    return _call(*cmd, timeout=timeout)[1]


def available():
    """Whether this system has the tools to look for and join networks."""
    if sys.platform == "win32":
        return bool(shutil.which("netsh"))
    if sys.platform == "darwin":
        return bool(shutil.which("networksetup"))
    return bool(shutil.which("nmcli"))


# ---- parsing (kept separate so it can be tested with sample output) ---------------------------

def parse_windows_current(text):
    """The SSID from `netsh wlan show interfaces` (its "SSID" label isn't translated)."""
    m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", text, re.M)
    return m[1] if m else None


def parse_windows_networks(text):
    """SSIDs from `netsh wlan show networks` ("SSID 1 : name", in any language)."""
    return [m.strip() for m in re.findall(r"^SSID \d+\s*:\s*(.*)$", text, re.M) if m.strip()]


def parse_nmcli(text):
    """(in use, SSID) pairs from `nmcli -t -f active,ssid dev wifi`."""
    pairs = []
    for line in text.splitlines():
        active, _, ssid = line.partition(":")
        if ssid:
            pairs.append((active == "yes", ssid.replace("\\:", ":")))
    return pairs


def parse_macos_networks(text):
    """Network names from `system_profiler SPAirPortDataType` (each is a line "   NAME:")."""
    return re.findall(r"^\s+((?:TELLO|RMTT)-\w+):\s*$", text, re.M)


# ---- the system --------------------------------------------------------------------------------

def _mac_interface():
    m = re.search(r"Hardware Port: Wi-Fi\s*\nDevice: (\w+)", _run("networksetup", "-listallhardwareports"))
    return m[1] if m else "en0"


def current_network():
    """The Wi-Fi network this computer is on, or None."""
    if sys.platform == "win32":
        return parse_windows_current(_run("netsh", "wlan", "show", "interfaces"))
    if sys.platform == "darwin":
        m = re.search(r"Network: (.+)", _run("networksetup", "-getairportnetwork", _mac_interface()))
        return m[1].strip() if m else None
    return next((ssid for active, ssid in parse_nmcli(_run("nmcli", "-t", "-f", "active,ssid", "dev", "wifi"))
                 if active), None)


def drone_networks():
    """Drone networks in range, best first as the system lists them."""
    if sys.platform == "win32":
        names = parse_windows_networks(_run("netsh", "wlan", "show", "networks"))
    elif sys.platform == "darwin":
        names = parse_macos_networks(_run("system_profiler", "SPAirPortDataType", timeout=30))
    else:
        names = [ssid for _, ssid in parse_nmcli(_run("nmcli", "-t", "-f", "active,ssid", "dev", "wifi"))]
    return list(dict.fromkeys(n for n in names if DRONE_NETWORK.match(n)))


def windows_profile(ssid):
    """A Wi-Fi profile for an open network, which netsh needs before it can connect."""
    name = ssid.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{name}</name>
    <SSIDConfig><SSID><name>{name}</name></SSID></SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>manual</connectionMode>
    <MSM><security><authEncryption>
        <authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX>
    </authEncryption></security></MSM>
</WLANProfile>
"""


def connect(ssid):
    """Join a drone's network. Returns None if it went ahead, else a short reason. Takes a few seconds."""
    if not DRONE_NETWORK.match(ssid):
        return t("not a drone network")
    if sys.platform == "win32":
        if f": {ssid}" not in _run("netsh", "wlan", "show", "profiles"):
            # a profile for this open network, for the current user only (no admin needed)
            profile = Path(tempfile.mkdtemp()) / f"{ssid}.xml"
            profile.write_text(windows_profile(ssid), encoding="utf-8")
            _run("netsh", "wlan", "add", "profile", f"filename={profile}", "user=current")
            profile.unlink()
        code, out = _call("netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}")
    elif sys.platform == "darwin":
        code, out = _call("networksetup", "-setairportnetwork", _mac_interface(), ssid, timeout=30)
        code = code or bool(out.strip())  # networksetup exits 0 even when it fails, but says why
    else:
        code, out = _call("nmcli", "dev", "wifi", "connect", ssid, timeout=30)
    return None if code == 0 else (out.strip().splitlines() or [t("couldn't connect")])[-1]
