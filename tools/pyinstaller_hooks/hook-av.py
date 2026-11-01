"""PyAV hook for slim builds (tools/build.py --slim-ffmpeg), used instead of PyInstaller's own.

PyInstaller's hook packs every DLL in the installed av.libs folder. Here the minimal FFmpeg DLLs are
on PATH instead (build.py puts them there), so they are packed as ordinary dependencies of PyAV's
modules and the full FFmpeg is left out.
"""
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ["fractions", "dataclasses", "uuid"] + collect_submodules("av")
