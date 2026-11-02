# How the code is laid out

| File | What it does |
|---|---|
| `tello_revived/app.py` | The app: input, camera actions and the main loop |
| `tello_revived/flight.py` | Take off, landing and the landing watch, flips, emergency stop, auto-land |
| `tello_revived/hud.py` | Everything drawn during flight: video, flight data, button guide, warnings |
| `tello_revived/menu.py` | Help and settings screen |
| `tello_revived/drone.py` | The link to the drone: commands, replies, telemetry and keep-alive |
| `tello_revived/video.py` | Receiving, decoding and recording the video |
| `tello_revived/gamepad.py` | Gamepad input |
| `tello_revived/settings.py` | Defaults, `config.json` loading and saving, the help table |
| `tello_revived/labels.py` | Key names (for the keyboard layout in use) and button names |
| `tello_revived/paths.py` | Where settings, media and assets are |
| `tello_revived/cli.py` | Command line: `--joytest`, `--selftest`, `--version` |
| `assets/make_logo.py` | Draws the logo, the window icon and the app icons (`.ico`, `.icns`) |
| `tools/make_screenshots.py` | Renders the README screenshots without a drone |
| `tools/build.py` | Builds the standalone app ([building.md](building.md)) |
| `tools/build_ffmpeg.sh` | Builds the minimal FFmpeg ([ffmpeg.md](ffmpeg.md)) |
| `.github/workflows/build.yml` | Builds, tests and releases all versions on GitHub |

`App` combines `FlightActions` (flight.py) and `HudDrawing` (hud.py), so those two files read the app's state directly.

## The drone link

The Tello takes text commands over UDP port 8889 and answers on the same port. The app:

- Sends `command` to start a session, then `rc <roll> <pitch> <throttle> <yaw>` 20 times a second while flying.
- Reads telemetry, which the drone sends to port 8890 about 10 times a second: battery, height, speed, attitude and temperature.
- Receives the H.264 video on port 11111 after `streamon`.

Replies can be padded with zero bytes, which the app strips.

The heading (HDG) comes from the `yaw` value in the telemetry. The Tello has no compass, so 0° is wherever the nose pointed when the drone was switched on.

## Video

One thread receives and decodes the stream, using a single decoder thread so frames aren't held back. FFmpeg converts each frame to RGB at the window's size, and the drawing loop just shows it. Photos are taken from the full-size frame. Recordings save the received H.264 as it is, then copy it into an mp4 without re-encoding.

## Gamepad

SDL's standard controller mapping is used when SDL recognises the pad; otherwise `RAW_MAP` in `gamepad.py` maps raw joystick numbers (`--joytest` shows them). L2 and R2 are analog, so a pull past 60% counts as pressed and below 30% as released.

## Keyboard

Keys are stored as scancodes, which mean physical positions, so the default WASD layout is ZQSD on an AZERTY keyboard. Names on screen come from SDL, which knows the keyboard layout in use.

## Screenshots

The screenshots in the README and these docs use a simulated camera image and telemetry, so no drone is needed. Regenerate them after changing anything on screen:

```
uv run python tools/make_screenshots.py
```

## Tests

```
uv run pytest
```

The tests in `tests/` run the real app against a fake drone (`FakeDrone` in `tests/conftest.py`) on localhost. The fake answers commands, sends telemetry and streams a short test clip as video, and each test changes what it does: a hot drone, a height that stays at 0 after takeoff, a firewall that blocks telemetry, a refused flip, a landing that never happens. They take about 40 seconds, and the release workflow runs them on every system before building.

When the real drone does something unexpected, add a test that makes the fake drone do the same.
