<p align="center"><img src="assets/logo.png" width="128" alt="Tello Revived logo"></p>

# TelloRevived

A Tello app for PC: fly a Ryze/DJI Tello drone from Windows, macOS or Linux with a gamepad or the keyboard. You get a big live video feed, a flight HUD, photos and recordings, and a settings screen where everything can be changed.

![Flying with the HUD](docs/screenshots/flight.png)

## Contents

- [Quick start](#quick-start)
- [Features](#features)
- [Controls](#controls)
- [Settings](#settings)
- [Safety](#safety)
- [Running from source](#running-from-source)
- [Contributing](#contributing)

## Quick start

1. **[Download the latest release](https://github.com/Ghorbel37/TelloRevived/releases/latest)**, the file for your platform:
   - **Windows:** `…-windows-x64-portable.exe`
   - **macOS:** `…-macos-arm64-portable.dmg` (Apple silicon) or `…-macos-x64-portable.dmg` (Intel)
   - **Linux:** `…-linux-x64-portable`
2. Turn on the Tello and connect your computer's Wi-Fi to `TELLO-XXXXXX`, or press **Connect** in the app once it finds the network.
3. Start the app. It shows which button takes off.

Nothing needs installing. A few notes the first time:
- **Windows:** when the firewall asks, allow the app on **Public** networks. If it's blocked, the app shows what to allow.
- **macOS:** open the disk image and drag **Tello Revived.app** anywhere. It isn't signed, so right-click it and choose **Open** the first time.
- **Linux:** make the file executable first (`chmod +x TelloRevived-*-portable`).

## Features

- **Live video**, windowed or fullscreen, with photos and mp4 recordings.
- **Flight HUD:** battery, Wi-Fi, altitude, speed, heading, horizon line and stick positions. Each element can be turned off.
- **Button guide** at the bottom showing only the buttons that matter right now.
- **Gamepad and keyboard** at the same time. Keys follow their position, so WASD becomes ZQSD on AZERTY keyboards.
- **Everything rebindable**, including the sticks, with speeds, stick feel and landing behaviour adjustable.
- **Minutes of flight left** in the top bar, measured from how fast your battery is dropping.
- **Flight logs and graphs:** see each flight's height, battery and speed, and how your battery is ageing.
- **Landing help** and **battery saving**: video only while flying, and auto-land at a battery level you choose.

## Controls

| | Keyboard | Gamepad |
|---|---|---|
| Move | `W A S D` | Left stick |
| Climb / descend, turn | Arrow keys | Right stick |
| Slow, precise moves (hold) | `Left Shift` | `L2` |
| Take off / land | `T` / `L` | Triangle / Cross |
| Speed | `1` `2` `3` | Circle |
| Photo / record | `P` / `R` | R1 / Square |
| Flip | `Left Ctrl` + move key | L1 + D-pad |
| **Emergency motor stop** | `Backspace` | **Select + Start** |
| Help / settings | `H` / `O` | Start |

The bar at the bottom shows the buttons for what the drone is doing right now:

| On the ground | Flying | Holding L1 |
|---|---|---|
| ![Ready to take off](docs/screenshots/ready.png) | ![Flying](docs/screenshots/flight.png) | ![Flip directions](docs/screenshots/flip.png) |

## Settings

Press **O**, or **Start** on the gamepad, to change controls, the HUD, flight behaviour, video and battery options. Changes are saved straight away.

| Keyboard | Flight |
|---|---|
| ![Keyboard bindings](docs/screenshots/menu_keyboard.png) | ![Flight settings](docs/screenshots/menu_flight.png) |

The [user guide](docs/usage.md) explains the settings, landing and battery options in detail.

## Safety

- The **emergency stop cuts the motors immediately, and the drone falls.** Use it only when the drone is very low, or when something goes wrong.
- If the gamepad disconnects or you let go of everything, the drone hovers.
- Quitting while flying lands first.

## Running from source

With [uv](https://docs.astral.sh/uv/) installed, run `uv run tello-revived` in the project folder. Without uv, double-click `run.bat` (Windows) or run `./run.sh` (Linux, macOS).

More documentation:
- [User guide](docs/usage.md)
- [Running, building and releasing](docs/building.md)
- [The minimal FFmpeg](docs/ffmpeg.md): how the releases are made smaller
- [How the code is laid out](docs/development.md)

## Contributing

Bug reports, ideas and pull requests are welcome.

- **Bugs:** [open an issue](https://github.com/Ghorbel37/TelloRevived/issues) with your system, your drone model, what you did and what happened. A screenshot of the app helps.
- **Code:** read [how the code is laid out](docs/development.md), then make your change on a branch:
  - Keep each pull request to one topic.
  - Run `uv run tello-revived --selftest` before opening it.
  - If you change what's on screen, regenerate the screenshots with `uv run python tools/make_screenshots.py`.
- **Testing on real hardware** is especially useful, in particular on Tello EDU, RoboMaster TT, macOS and Linux.
