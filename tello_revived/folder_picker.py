"""Ask for a folder with the system's own dialog (no GUI toolkit is bundled for this)."""

import os
import shutil
import subprocess
import sys


def pick_folder(title, start):
    """The folder the user chose, or None if they cancelled or no dialog is available.

    Blocks until the dialog closes, so call it from a thread.
    """
    env = dict(os.environ, PICK_TITLE=title, PICK_START=str(start))
    flags = 0
    if sys.platform == "win32":
        script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
                  "Add-Type -AssemblyName System.Windows.Forms;"
                  "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                  "$d.Description = $env:PICK_TITLE; $d.SelectedPath = $env:PICK_START;"
                  "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }")
        cmd = ["powershell", "-NoProfile", "-STA", "-Command", script]
        flags = subprocess.CREATE_NO_WINDOW  # the dialog only, no console window
    elif sys.platform == "darwin":
        cmd = ["osascript", "-e", 'POSIX path of (choose folder with prompt (system attribute "PICK_TITLE") '
                                  'default location (POSIX file (system attribute "PICK_START")))']
    elif shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", "--title", title, "--filename", f"{start}/"]
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--getexistingdirectory", str(start), "--title", title]
    else:
        return None
    try:
        result = subprocess.run(cmd, capture_output=True, env=env, creationflags=flags)
    except OSError:
        return None
    path = result.stdout.decode("utf-8", "replace").strip()
    return path or None


def available():
    """Whether pick_folder can show a dialog on this system."""
    return sys.platform in ("win32", "darwin") or bool(shutil.which("zenity") or shutil.which("kdialog"))
