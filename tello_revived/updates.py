"""Is there a newer release on GitHub?

Uses curl (part of Windows 10+, macOS and most Linux systems), so the app doesn't need to bundle
Python's SSL library just for this one request.
"""

import json
import re
import shutil
import subprocess

from tello_revived import REPO_URL, VERSION

LATEST = REPO_URL.replace("https://github.com/", "https://api.github.com/repos/") + "/releases/latest"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def version_tuple(text):
    """'v0.8.2' or '0.8.2' -> (0, 8, 2); None if it isn't a version."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(n) for n in m[1].split(".")) if m else None


def is_newer(tag, current=VERSION):
    new, old = version_tuple(tag), version_tuple(current)
    return bool(new and old and new > old)


def latest_release():
    """(tag, page url) of the latest release, or None if it can't be checked (offline, no curl)."""
    curl = shutil.which("curl")
    if not curl:
        return None
    try:
        out = subprocess.run([curl, "-sSfL", "--max-time", "10", "-H", "Accept: application/vnd.github+json", LATEST],
                             capture_output=True, timeout=20, creationflags=NO_WINDOW).stdout
        release = json.loads(out)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    tag, url = release.get("tag_name"), release.get("html_url")
    return (tag, url) if tag and url else None
