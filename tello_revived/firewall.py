"""Let the drone's telemetry and video through the firewall, after the system's own admin prompt.

The drone sends telemetry to UDP port 8890 and video to 11111 on its own, which a firewall blocks
unless the app is allowed. Replies to our commands get through either way.
"""

import base64
import ctypes
import shutil
import subprocess
import sys
from pathlib import Path

PORTS = "8890,11111"
RULE_NAME = "Tello Revived: drone telemetry and video"


def program():
    """The program the firewall sees: the app itself, or the installed Python behind a venv."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return getattr(sys, "_base_executable", sys.executable)


def can_allow():
    """Whether allow() can do it on this system (otherwise only instructions are shown)."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(shutil.which("pkexec") and shutil.which("ufw"))


def allow():
    """Ask for admin rights and allow the app's UDP ports 8890 and 11111.

    Returns True if the request went ahead, False if it was cancelled or failed. Blocks until the
    admin prompt is answered on macOS and Linux, so call it from a thread.
    """
    if sys.platform == "win32":
        return _allow_windows()
    if sys.platform == "darwin":
        return _allow_macos()
    return subprocess.run(["pkexec", "ufw", "allow", f"{PORTS}/udp"]).returncode == 0


def windows_script(path):
    """PowerShell that replaces this program's inbound block rules with an allow rule for our ports.

    Block rules (which Windows adds when its firewall question is dismissed) win over allow rules,
    so they have to go. Only inbound rules for this one program are touched.
    """
    p = path.replace("'", "''")
    return (
        f"$p = '{p}'\n"
        # Windows may store the path in another case (c:\users\...), so compare it ourselves
        "Get-NetFirewallApplicationFilter | Where-Object { $_.Program -ieq $p } | Get-NetFirewallRule |\n"
        "    Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' } | Remove-NetFirewallRule\n"
        f"Remove-NetFirewallRule -DisplayName '{RULE_NAME}' -ErrorAction SilentlyContinue\n"
        f"New-NetFirewallRule -DisplayName '{RULE_NAME}' -Direction Inbound -Program $p -Protocol UDP"
        f" -LocalPort {PORTS} -Action Allow -Profile Any | Out-Null\n"
    )


def _allow_windows():
    encoded = base64.b64encode(windows_script(program()).encode("utf-16-le")).decode()
    # "runas" shows the UAC prompt; the result is above 32 if it went ahead, 5 if it was declined
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "powershell.exe", f"-NoProfile -WindowStyle Hidden -EncodedCommand {encoded}", None, 0)
    return result > 32


def macos_command(path):
    """The shell command that adds the program to macOS's application firewall and unblocks it."""
    fw = "/usr/libexec/ApplicationFirewall/socketfilterfw"
    quoted = "'" + path.replace("'", "'\\''") + "'"
    return f"{fw} --add {quoted} && {fw} --unblockapp {quoted}"


def _allow_macos():
    command = macos_command(program()).replace("\\", "\\\\").replace('"', '\\"')
    script = f'do shell script "{command}" with administrator privileges'
    return subprocess.run(["osascript", "-e", script]).returncode == 0


def describe():
    """Short text for the button: what will be allowed."""
    return Path(program()).name
