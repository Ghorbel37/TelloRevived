"""Build a standalone Tello Revived for this OS with PyInstaller.

    uv sync --group build
    uv run python tools/build.py

Windows: dist/TelloRevived-windows-x64.exe       (single exe)
Linux:   dist/TelloRevived-linux-x64.tar.gz      (single binary inside)
macOS:   dist/TelloRevived-macos-<arch>.zip      (Tello Revived.app inside)

Windows only, optional: --slim-ffmpeg DIR uses a minimal FFmpeg (built by tools/build_ffmpeg.sh, about
6 MB) instead of the full one PyAV ships (about 65 MB unpacked).
"""
import argparse
import os
import platform
import re
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


def stage_slim_av(ffmpeg_bin):
    """Copy PyAV into build/slim-av, pointed at the minimal FFmpeg DLLs in ffmpeg_bin.

    PyAV's modules load its FFmpeg DLLs by hashed names (avcodec-63-<hash>.dll). Each of those
    names is overwritten with the plain, shorter name (avcodec-63.dll) padded with zero bytes,
    so nothing else in the file moves, and the plain-named DLLs go next to it.
    """
    import av

    if av.ffmpeg_version_info not in ffmpeg_bin.joinpath("VERSION").read_text().split():
        sys.exit(f"{ffmpeg_bin} isn't FFmpeg {av.ffmpeg_version_info}, the version PyAV {av.__version__} uses")
    site = Path(av.__file__).parent.parent
    pattern = re.compile(r"^(avcodec|avformat|avutil|avdevice|avfilter|swscale|swresample)-(\d+)-[0-9a-f]{32}\.dll$")
    renames = {}
    for dll in (site / "av.libs").iterdir():
        if m := pattern.match(dll.name):
            short = f"{m[1]}-{m[2]}.dll"
            assert (ffmpeg_bin / short).exists(), f"{short} missing from {ffmpeg_bin}"
            renames[dll.name.encode()] = short.encode()

    stage = ROOT / "build" / "slim-av"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(site / "av", stage / "av", ignore=shutil.ignore_patterns("__pycache__"))
    for module in (stage / "av").rglob("*.pyd"):
        data = module.read_bytes()
        for old, short in renames.items():
            data = data.replace(old, short.ljust(len(old), bytes(1)))
        leftover = re.findall(rb"[\w.+-]+-[0-9a-f]{32}\.dll", data)
        assert not leftover, f"{module} still needs {leftover}"
        module.write_bytes(data)
    (stage / "av.libs").mkdir()
    for dll in ffmpeg_bin.glob("*.dll"):  # FFmpeg plus the compiler's thread library
        shutil.copy2(dll, stage / "av.libs")
    return stage


def pyinstaller(*args, slim=None):
    sep = ";" if os.name == "nt" else ":"
    # ready-made icons (assets/make_logo.py), so PyInstaller doesn't need Pillow to convert one;
    # Linux executables have no icon
    icon = ROOT / "assets" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", NAME, "--icon", str(icon),
           "--add-data", f"{ROOT / 'assets' / 'icon.png'}{sep}assets",
           "--add-data", f"{ROOT / 'assets' / 'selftest.h264'}{sep}assets",  # for --selftest
           "--distpath", str(DIST / "pyinstaller"), "--workpath", str(ROOT / "build"),
           "--specpath", str(ROOT / "build"), "--paths", str(ROOT),
           # not used by the app; leaving them out makes the build smaller
           "--exclude-module", "numpy", "--exclude-module", "ssl", "--exclude-module", "_ssl",
           "--exclude-module", "_hashlib",
           *args, str(ROOT / "tello_revived" / "__main__.py")]
    env = dict(os.environ)
    if slim:
        # the staged PyAV is found before the installed one, our hook replaces PyInstaller's,
        # and the minimal FFmpeg DLLs are found on PATH
        cmd[3:3] = ["--paths", str(slim), "--additional-hooks-dir", str(ROOT / "tools" / "pyinstaller_hooks")]
        env["PATH"] = str(slim / "av.libs") + os.pathsep + env["PATH"]
    subprocess.run(cmd, check=True, env=env)
    return DIST / "pyinstaller"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slim-ffmpeg", type=Path, metavar="DIR",
                        help="folder with a minimal FFmpeg's DLLs and VERSION file (Windows)")
    args = parser.parse_args()
    slim = stage_slim_av(args.slim_ffmpeg.resolve()) if args.slim_ffmpeg else None
    shutil.rmtree(DIST, ignore_errors=True)
    if sys.platform == "win32":
        out = pyinstaller("--onefile", slim=slim) / f"{NAME}.exe"
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
