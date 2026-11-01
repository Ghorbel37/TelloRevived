# The minimal FFmpeg

The standalone builds don't use the FFmpeg that comes with PyAV. They use a minimal FFmpeg built with only what Tello Revived needs, which makes them much smaller:

| Build | Full FFmpeg (from PyAV) | Minimal FFmpeg |
|---|---|---|
| Windows exe | 42 MB | 18 MB |
| FFmpeg libraries alone (Windows) | about 65 MB unpacked | about 6 MB |

Running from source (`uv run tello-revived`) still uses PyAV's normal FFmpeg. Nothing here changes how the app behaves.

## What FFmpeg and PyAV are

[FFmpeg](https://ffmpeg.org) is the C library that does the video work: it decodes the drone's H.264 stream into pictures, converts and resizes them, and writes recordings as mp4. [PyAV](https://pyav.basswood-io.com) (the `av` package) lets Python use FFmpeg. Its packages come with a complete FFmpeg already compiled in.

That complete FFmpeg is the problem. It includes encoders for H.264, H.265, AV1 and VP9, a video quality analyser, hundreds of filters and formats, and the libraries they need. The app uses none of these, and they can't simply be deleted, because the main FFmpeg library won't load without them. No lighter PyAV package exists either: every version from 12 to 19 ships 24 to 30 MB of FFmpeg on Windows alone.

## What the minimal FFmpeg contains

`tools/build_ffmpeg.sh` builds FFmpeg from the official source with `--disable-everything`, then turns back on only these parts:

| Part | Used for |
|---|---|
| `h264` decoder and parser | Decoding the drone's video |
| `h264` demuxer | Reading the raw stream (live and from a saved recording) |
| `udp` and `file` protocols | Receiving the stream; reading and writing files |
| `mp4` muxer | Saving recordings as mp4 |
| `extract_extradata` bitstream filter | Finding the stream's SPS/PPS, which the mp4 header needs |
| `h264_mp4toannexb` bitstream filter | Converting between mp4 and raw H.264 |
| swscale | Converting frames to RGB and resizing them to the window |

`--disable-autodetect` stops the build from picking up any other libraries installed on the machine, so the result depends only on the operating system (and, on Windows, the compiler's small `libwinpthread-1.dll`).

## Building it

The FFmpeg version must be exactly the one PyAV was built with, because PyAV is compiled against that version's data layouts:

```
uv run python -c "import av; print(av.ffmpeg_version_info)"
```

Then build it and build the app with it:

```
tools/build_ffmpeg.sh 9.0.2 build/ffmpeg-slim
uv run python tools/build.py --slim-ffmpeg build/ffmpeg-slim
```

`build.py` checks the version and stops if it doesn't match. The FFmpeg build takes about 3 minutes on a fast PC.

What you need on each system:

| System | Tools |
|---|---|
| Windows | An MSYS2 UCRT64 shell with `mingw-w64-ucrt-x86_64-gcc`, `mingw-w64-ucrt-x86_64-nasm`, `make`, `diffutils`, `tar`, `xz` and `curl`. Git Bash also works if a MinGW gcc, nasm and make are on `PATH`. |
| Linux | gcc, make and nasm (`sudo apt install build-essential nasm`) |
| macOS | The Xcode command line tools, plus nasm on Intel Macs (`brew install nasm`) |

The release workflow does the same on GitHub for each system, and caches the result until the FFmpeg version or the build script changes.

## How it replaces PyAV's FFmpeg

PyAV isn't recompiled. `tools/build.py` copies the installed PyAV into `build/slim-av`, points the copy at the minimal libraries, and packs that copy into the app instead of the installed one. This works because FFmpeg always includes all of its public functions, whichever parts are switched on. Only the codecs and formats behind them are left out, so PyAV finds every function it was compiled to call.

How the copy is pointed at the new libraries depends on the system:

- **Windows and Linux.** PyAV's packages give the FFmpeg libraries hashed names, like `avcodec-63-2756d4ff….dll` or `libavcodec-d61378e8.so.63.1.102`, and PyAV's compiled modules load them by those names. FFmpeg's own build uses plain names: `avcodec-63.dll`, `libavcodec.so.63`. Inside each PyAV module, every hashed name is overwritten with the plain name. The plain name is shorter, so it's padded with zero bytes to the same length. A zero byte ends a name, and nothing else in the file moves. The script checks that no hashed name is left.
- **macOS.** PyAV's Mac packages already use plain names (`libavcodec.63.1.102.dylib`), so the files are swapped without patching anything. FFmpeg's libraries refer to each other by a shorter name (`libavcodec.63.dylib`), so after building, the script renames those references with `install_name_tool` and signs the libraries again (macOS won't load a changed library that isn't signed). One more difference: macOS ties every function a module imports to the library it came from when the module was built, and PyAV's own libraries also offer the functions of the FFmpeg libraries they use (PyAV expects `av_malloc` in `libavdevice`, for example). So on macOS the FFmpeg libraries are linked to each other as *re-exports*, which makes each one offer its dependencies' functions too.

During the PyInstaller run, `tools/pyinstaller_hooks/hook-av.py` replaces PyInstaller's own PyAV hook. That hook packs every file in PyAV's library folder, which would bring the full FFmpeg back. Ours packs only PyAV's Python modules, and the minimal libraries are picked up as their dependencies.

## Problems found along the way

- **Saving recordings needed an encoder.** Copying the video into an mp4 used to look up an H.264 *encoder*, which the minimal FFmpeg doesn't have. Recordings are now copied with `add_stream_from_template(..., opaque=True)`, which takes the stream settings as they are.
- **Unplayable recordings.** The first minimal build didn't include `extract_extradata`, so FFmpeg never found the stream's SPS/PPS and wrote mp4 files with an empty header. Players and FFmpeg itself refused them. The filter is now included. Saving also refuses to write an mp4 without SPS/PPS: the raw `.h264` file is kept instead, so a recording is never lost.
- **macOS: "Symbol not found: _av_malloc".** The first macOS builds failed because PyAV looks for FFmpeg's utility functions in `libavdevice` (see above). Fixed with re-exports.
- **Windows temp path.** FFmpeg's configure script can't use a Windows-style `TMPDIR` (`C:\...`), so the build script sets a Unix-style one.

## How it's tested

`TelloRevived --selftest`, which the release workflow runs on every build, decodes a 5-frame H.264 clip (`assets/selftest.h264`), resizes a frame, and saves the clip as an mp4 that must contain SPS/PPS. That covers every part of FFmpeg the app uses, so a broken minimal FFmpeg fails the build instead of reaching a release.

## Updating

When PyAV is updated (in `uv.lock`), its FFmpeg version may change. The release workflow reads the version from the installed PyAV, so it builds the right one automatically. Locally, run `tools/build_ffmpeg.sh` again with the new version. If a new PyAV ever loads FFmpeg differently, `build.py` stops with an error instead of producing a broken build.
