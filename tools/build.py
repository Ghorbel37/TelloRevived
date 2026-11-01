"""Build a standalone Tello Revived for this OS with PyInstaller.

    uv sync --group build
    uv run python tools/build.py

Windows: dist/TelloRevived-windows-x64.exe       (single exe)
Linux:   dist/TelloRevived-linux-x64.tar.gz      (single binary inside)
macOS:   dist/TelloRevived-macos-<arch>.zip      (Tello Revived.app inside)
"""
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
NAME = "TelloRevived"


def arch():
    m = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(m, m)


def pyinstaller(*args):
    sep = ";" if os.name == "nt" else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", NAME, "--icon", str(ROOT / "assets" / "logo.png"),
           "--add-data", f"{ROOT / 'assets' / 'icon.png'}{sep}assets",
           "--distpath", str(DIST / "pyinstaller"), "--workpath", str(ROOT / "build"),
           "--specpath", str(ROOT / "build"), "--paths", str(ROOT),
           *args, str(ROOT / "tello_revived" / "__main__.py")]
    subprocess.run(cmd, check=True)
    return DIST / "pyinstaller"


def main():
    shutil.rmtree(DIST, ignore_errors=True)
    if sys.platform == "win32":
        out = pyinstaller("--onefile") / f"{NAME}.exe"
        final = DIST / f"{NAME}-windows-{arch()}.exe"
        out.replace(final)
    elif sys.platform == "darwin":
        app = pyinstaller("--osx-bundle-identifier", "io.github.tellorevived") / f"{NAME}.app"
        app = app.rename(app.with_name("Tello Revived.app"))
        final = DIST / f"{NAME}-macos-{arch()}.zip"
        # ditto keeps the bundle's symlinks and permissions, unlike zipfile
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(final)], check=True)
    else:
        out = pyinstaller("--onefile") / NAME
        final = DIST / f"{NAME}-linux-{arch()}.tar.gz"
        with tarfile.open(final, "w:gz") as tar:
            tar.add(out, arcname=f"{NAME}/{NAME}")
            tar.add(ROOT / "README.md", arcname=f"{NAME}/README.md")
    print(f"built {final} ({final.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
