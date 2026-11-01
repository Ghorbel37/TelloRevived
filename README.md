# TelloRevived

Fly a Tello from the PC with a PS3 controller (DsHidMini) or the keyboard. You get a live video feed and a HUD.

## Run

1. Turn on the Tello and connect the PC's Wi-Fi to `TELLO-XXXXXX`.
2. Double-click `run.bat`. It creates `.venv` the first time if it's missing.
3. On the first run, Windows Firewall will ask about Python. Allow it on **Public** networks, because Windows treats the Tello's Wi-Fi as public. If you don't, there will be no video and no telemetry.

Press **H** (or **Start** / **PS** on the pad) to see the controls. Photos and recordings are saved to `media\`. Recordings are saved as `.mp4` without re-encoding, so they keep the drone's original quality.

## Controller

- DsHidMini in **SDF** or **XInput** mode works with SDL's standard mapping, and the app uses it automatically.
- If the top bar shows your pad as `(raw)`, run `run.bat --joytest`. Move each stick and press each button, then put the numbers it shows into `RAW_MAP` at the top of `tello_revived.py`.
- Stick feel is set by `DEADZONE`, `EXPO`, `SPEED_MODES` and `PRECISION_SCALE` in the same file.

## Safety

- **Select + Start** or **Backspace** stops the motors immediately. The drone will fall.
- If the pad disconnects, or you release everything, the drone hovers.
- If you quit while flying, the app sends `land` first.
- Flips need more than 50% battery.
