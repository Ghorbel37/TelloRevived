"""Build a standalone Tello Revived for this OS with PyInstaller.

    uv sync --group build
    uv run python tools/build.py

Windows: dist/TelloRevived-v<version>-windows-x64-portable.exe
Linux:   dist/TelloRevived-v<version>-linux-x64-portable            (the program itself)
macOS:   dist/TelloRevived-v<version>-macos-<arch>-portable.dmg     (Tello Revived.app inside)

Optional: --slim-ffmpeg DIR uses a minimal FFmpeg (built by tools/build_ffmpeg.sh, a few MB) instead
of the full one PyAV ships (40-65 MB unpacked).
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tello_revived import VERSION  # noqa: E402
DIST = ROOT / "dist"
NAME = "TelloRevived"


def arch():
    m = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(m, m)


FFMPEG_LIBS = "avcodec|avformat|avutil|avdevice|avfilter|swscale|swresample"


def stage_slim_av(ffmpeg_dir):
    """Copy PyAV into build/slim-av, using the minimal FFmpeg in ffmpeg_dir instead of its own.

    Windows and Linux: PyAV's modules load FFmpeg by hashed names (avcodec-63-<hash>.dll,
    libavcodec-<hash>.so.63.1.102). Each of those is overwritten with the plain, shorter name
    (avcodec-63.dll, libavcodec.so.63) padded with zero bytes, so nothing else in the file moves.
    macOS: the names are already plain (libavcodec.63.1.102.dylib), so the files are just swapped.
    """
    import av

    if av.ffmpeg_version_info not in ffmpeg_dir.joinpath("VERSION").read_text().split():
        sys.exit(f"{ffmpeg_dir} isn't FFmpeg {av.ffmpeg_version_info}, the version PyAV {av.__version__} uses")
    site = Path(av.__file__).parent.parent
    stage = ROOT / "build" / "slim-av"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(site / "av", stage / "av", ignore=shutil.ignore_patterns("__pycache__"))

    if sys.platform == "darwin":
        libs = stage / "av" / ".dylibs"
        for old in libs.iterdir():  # PyAV's FFmpeg and the codec libraries only it needed
            old.unlink()
        for lib in ffmpeg_dir.glob("*.dylib"):
            shutil.copy2(lib, libs)
        return stage

    if sys.platform == "win32":
        hashed = re.compile(rf"^({FFMPEG_LIBS})-(\d+)-[0-9a-f]{{32}}\.dll$")
        plain, modules = "{0}-{1}.dll", "*.pyd"
    else:
        hashed = re.compile(rf"^lib({FFMPEG_LIBS})-[0-9a-f]{{8}}\.so\.(\d+)[.\d]*$")
        plain, modules = "lib{0}.so.{1}", "*.so"
    renames = {}
    for lib in (site / "av.libs").iterdir():
        if m := hashed.match(lib.name):
            short = plain.format(m[1], m[2])
            assert (ffmpeg_dir / short).exists(), f"{short} missing from {ffmpeg_dir}"
            renames[lib.name.encode()] = short.encode()
    assert len(renames) == 7, f"expected PyAV's 7 FFmpeg libraries, found {sorted(renames)}"
    for module in (stage / "av").rglob(modules):
        data = module.read_bytes()
        for old, short in renames.items():
            data = data.replace(old, short.ljust(len(old), bytes(1)))
        leftover = [old for old in renames if old in data]
        assert not leftover, f"{module} still needs {leftover}"
        module.write_bytes(data)
    (stage / "av.libs").mkdir()
    for lib in ffmpeg_dir.iterdir():  # FFmpeg (plus, on Windows, the compiler's thread library)
        if lib.name != "VERSION":
            shutil.copy2(lib, stage / "av.libs")
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
        # and the minimal FFmpeg libraries are found as PyAV's dependencies
        cmd[3:3] = ["--paths", str(slim), "--additional-hooks-dir", str(ROOT / "tools" / "pyinstaller_hooks")]
        for var in ("PATH", "LD_LIBRARY_PATH"):
            env[var] = os.pathsep.join(filter(None, [str(slim / "av.libs"), env.get(var)]))
    subprocess.run(cmd, check=True, env=env)
    return DIST / "pyinstaller"


def make_dmg(app, dmg, tries=5):
    """Pack the .app into a disk image. hdiutil sometimes fails with "Resource busy" (often while
    macOS is still scanning the new files), so it's retried a few times."""
    cmd = ["hdiutil", "create", "-volname", "Tello Revived", "-srcfolder", str(app), "-format", "UDZO", "-ov", str(dmg)]
    for attempt in range(1, tries + 1):
        if subprocess.run(cmd).returncode == 0:
            return
        print(f"hdiutil failed (try {attempt} of {tries})")
        time.sleep(10 * attempt)
    sys.exit("couldn't create the disk image")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slim-ffmpeg", type=Path, metavar="DIR",
                        help="folder from tools/build_ffmpeg.sh with a minimal FFmpeg")
    args = parser.parse_args()
    slim = stage_slim_av(args.slim_ffmpeg.resolve()) if args.slim_ffmpeg else None
    shutil.rmtree(DIST, ignore_errors=True)
    base = f"{NAME}-v{VERSION}"
    if sys.platform == "win32":
        out = pyinstaller("--onefile", slim=slim) / f"{NAME}.exe"
        final = DIST / f"{base}-windows-{arch()}-portable.exe"
        out.replace(final)
    elif sys.platform == "darwin":
        app = pyinstaller("--osx-bundle-identifier", "io.github.tellorevived", slim=slim) / f"{NAME}.app"
        app = app.rename(app.with_name("Tello Revived.app"))
        final = DIST / f"{base}-macos-{arch()}-portable.dmg"
        # an .app is a folder; a disk image hands it out as one file (open it, drag the app anywhere)
        make_dmg(app, final)
    else:
        # strip the debug symbols Python and PyAV's Linux libraries carry (about half the file);
        # not on macOS, where it can get in the way of code signing
        out = pyinstaller("--onefile", "--strip", slim=slim) / NAME
        final = DIST / f"{base}-linux-{arch()}-portable"
        out.replace(final)
    print(f"built {final} ({final.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
