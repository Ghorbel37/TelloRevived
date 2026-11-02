# User guide

- [Button guide](#button-guide)
- [Controls in detail](#controls-in-detail)
- [Settings screen](#settings-screen)
- [Landing](#landing)
- [Battery and heat](#battery-and-heat)
- [Gamepads](#gamepads)
- [Firewall](#firewall)

## Button guide

The bar at the bottom shows the buttons for what the drone is doing right now: take off on the ground; land, speed, photo, record and flips in the air; the four flip directions while the flip button is held.

It shows the gamepad's buttons after you touch the gamepad, and the keyboard's keys after you press a key:

![Button guide for the keyboard](screenshots/flight_keyboard.png)

- Photo and Record only appear while the camera is streaming.
- While landing, or after a landing fails, the emergency stop is added to the front.
- You can turn the bar off in **Settings → HUD**.

## Controls in detail

| | Keyboard | Gamepad |
|---|---|---|
| Forward / back / sideways | `W A S D` (`Z Q S D` on AZERTY) | Left stick |
| Climb / descend | `Up` / `Down` | Right stick up / down |
| Turn | `Left` / `Right` | Right stick left / right |
| Slow, precise moves (hold) | `Left Shift` | `L2` (the further you pull, the slower) |
| Take off / land | `T` / `L` | Triangle / Cross |
| Speed mode | `1` `2` `3` | Circle (cycles) |
| Photo / record | `P` / `R` | R1 / Square |
| Flip | `Left Ctrl` + move key | L1 + D-pad |
| **Emergency motor stop** | `Backspace` | **Select + Start** |
| Help / settings | `H` / `O` | Start |
| Fullscreen / quit | `F11` / `Esc` | |

- Flips need more than 50% battery. If the drone refuses one, the app says why.
- If a takeoff is refused, the app gives the likely reason (battery too low, drone too hot).
- Quitting while flying lands first. Press the quit key again to quit right away.

## Settings screen

| Help | Video & Power |
|---|---|
| ![Help](screenshots/menu_help.png) | ![Video and power settings](screenshots/menu_video.png) |

Moving around:

- **Keyboard:** `Up`/`Down` to move, `Left`/`Right` to change a value, `Enter` to edit, `Del` to clear a binding, `Tab` to switch page, `Esc` to close.
- **Gamepad:** D-pad, Cross to edit, Square to clear, L1/R1 to switch page, Circle to close.
- **Mouse:** click a value. Click its left half, or right-click, to go back.

Changing things:

- **Rebinding:** select an action and press the new key or button. A red value means two actions share it.
- **Short hints:** the highlighted setting's hint appears just above the bottom bar.
- **Swapping the sticks:** **Flight → Move with** changes which stick moves and which one climbs and turns.
- **Drone model:** **Flight → Drone model** sets Tello, Tello EDU or RoboMaster TT. Settings your drone can't use are hidden.
- **Photos and videos folder:** at the bottom of **Video & Power**. It opens your system's folder dialog. **Use the default folder** switches back. On Linux this needs `zenity` or `kdialog`; without them, set `media_dir` in `config.json`.
- **About:** shows the version, a link to this project, the photos and videos folder, and where your settings are saved.

Settings are saved in `config.json`. While the settings screen is open, only the gamepad flies the drone, and the emergency stop still works.

## Landing

By default, landing sends one `land` command, like the original Tello app. The app then watches the descent. If the drone stops descending, that try counts as failed. After **Flight → Failed landings before warning** tries (3 by default), this warning appears:

![Landing failed warning](screenshots/landing_failed.png)

When that happens, fly the drone down slowly yourself, and use the emergency stop when it's just above the ground.

With **Flight → Retry landing automatically** on, the app keeps resending `land` for you. It also holds back stick commands while landing, because they can cancel a landing. Moving a stick cancels the automatic landing.

## Battery and heat

All of these are on the **Video & Power** page:

- **Video stream** is **Only while flying** by default, because the Tello gets very hot when it streams sitting on the ground. Choose **On** to see the camera before takeoff, or **Off** for no video.
- **Auto-land at battery** lands once per flight when the battery reaches that level.
- **Low battery warning** sets when the HUD warns you.
- **App frame rate** lowers how often the window is redrawn, which saves laptop battery. Nothing is drawn while the window is minimised.
- **Stream resolution, frame rate and bitrate** only exist on the RoboMaster TT (SDK 3.0). They appear when the drone model is set to RoboMaster TT. A regular Tello (SDK 1.3) or a Tello EDU (SDK 2.0) can't get them through a firmware update.

## Gamepads

- Gamepads that SDL knows (PlayStation, Xbox and most others) work out of the box. A PS3 controller on Windows works through DsHidMini in SDF or XInput mode.
- If the top bar shows your gamepad as `(raw)`, SDL doesn't know its layout. Run `uv run tello-revived --joytest`, then put the axis and button numbers it shows into `RAW_MAP` in `tello_revived/gamepad.py`.
- L2 and R2 can be bound like buttons. A firm pull counts as a press.

## Firewall

The drone sends its telemetry (port 8890) and video (port 11111) on its own, and a firewall blocks that unless the app is allowed. Replies to commands still get through, so the drone seems to connect but never shows data. When this happens, the app shows **BLOCKED BY FIREWALL**, with steps for your system and the exact program to allow. The message clears by itself once it's allowed.

On Windows, the Tello's Wi-Fi usually counts as a Public network, so allow the app on **Public**, or on both Private and Public. When running from source, the program to allow is the installed Python, not the `.venv` one. The message shows its path.
