# Running, building and releasing

## Running from source

With [uv](https://docs.astral.sh/uv/):

```
uv run tello-revived
```

uv installs Python and the dependencies the first time. Without uv, double-click `run.bat` on Windows or run `./run.sh` on Linux and macOS. Both use uv when it's installed, and otherwise create a `.venv` and install the app with pip (`pip install -e .`, which reads `pyproject.toml`).

Settings (`config.json`) and photos and videos (`media/`) are kept in the project folder.

| File | What it's for |
|---|---|
| `pyproject.toml` | The app's dependencies and the `tello-revived` command. pip reads it too. |
| `uv.lock` | The exact versions uv installs, so every machine gets the same ones |

The `build` dependency group (PyInstaller) is only installed for building: `uv sync --group build`.

## Building the standalone app

```
uv sync --group build
uv run python tools/build.py
```

This builds for the system you run it on, using PyAV's full FFmpeg. The releases use a minimal FFmpeg instead, which makes them much smaller. See [ffmpeg.md](ffmpeg.md) for how to build that and pass it with `--slim-ffmpeg`.

The result goes in `dist/`:

| System | File |
|---|---|
| Windows | `TelloRevived-v<version>-windows-x64-portable.exe` |
| Linux | `TelloRevived-v<version>-linux-x64-portable`, the program itself. Linux programs normally have no extension. |
| macOS | `TelloRevived-v<version>-macos-<arch>-portable.dmg`, a disk image containing `Tello Revived.app` (an `.app` is a folder, so it can't be a single file on its own) |

The icons the builds use (`assets/icon.ico`, `assets/icon.icns`) are made by `assets/make_logo.py`, so no image library is needed to build.

`TelloRevived --selftest` starts the app without a drone, decodes and saves a short test clip, draws a few frames and exits with an error code if anything fails.

## Releases

`.github/workflows/build.yml` runs when a tag starting with `v` is pushed, or when it's started by hand from the Actions page. For Windows, Linux, macOS on Apple silicon and macOS on Intel, it:

1. Installs the dependencies with uv.
2. Builds the minimal FFmpeg, or takes it from the cache.
3. Builds the app and runs `--selftest`.
4. Uploads the file. For a tag, it also attaches all four files to a GitHub release.

To publish a release:

```
git tag v1.0
git push origin v1.0
```

The version shown in the app and in the file names comes from `VERSION` in `tello_revived/__init__.py`, so update it before tagging.
