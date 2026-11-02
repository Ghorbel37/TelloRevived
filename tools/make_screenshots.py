"""Render the README screenshots with a simulated camera image and telemetry (no drone needed).

    uv run python tools/make_screenshots.py

Uses default settings (your config.json is not read or changed) and writes docs/screenshots/*.png.
"""
import tempfile
import time
from pathlib import Path

import numpy as np
import pygame
from pygame._sdl2 import controller as sdl_controller

from tello_revived import drone, settings
from tello_revived.app import App

ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "docs" / "screenshots"
out.mkdir(parents=True, exist_ok=True)
settings.Settings.__init__.__defaults__ = (Path(tempfile.mkdtemp()) / "config.json",)  # leave yours alone
drone.CMD_PORT, drone.STATE_PORT = 18889, 18890  # don't clash with a running app


def landscape(w=960, h=720):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 3), np.float32)
    horizon = 300 + 12 * np.sin(x / 140) + 6 * np.sin(x / 37)
    t = np.clip(y / 300, 0, 1)[..., None]
    sky = (1 - t) * np.array([70, 130, 200]) + t * np.array([190, 215, 235])
    hills = 300 - 55 * np.exp(-((x - 260) / 180) ** 2) - 35 * np.exp(-((x - 720) / 220) ** 2) + 8 * np.sin(x / 23)
    hill_col = np.array([95, 120, 120])
    g = np.clip((y - horizon) / (h - horizon), 0, 1)[..., None]
    ground = (1 - g) * np.array([110, 150, 80]) + g * np.array([60, 105, 45])
    with np.errstate(divide="ignore", invalid="ignore"):
        stripes = (np.sin((x - w / 2) / (y - horizon + 40) * 18) > 0.6)[..., None] * (y > horizon)[..., None]
    ground = ground * (1 - 0.12 * stripes)
    img[:] = sky
    img = np.where((y > hills)[..., None], hill_col, img)
    img = np.where((y > horizon)[..., None], ground, img)
    # a few trees
    for cx, cy, r in ((150, 395, 26), (190, 400, 20), (820, 380, 30), (600, 345, 14), (640, 348, 11)):
        m = (x - cx) ** 2 + ((y - cy) * 1.2) ** 2 < r * r
        img[m] = [45, 80, 40]
    return np.clip(img, 0, 255).astype(np.uint8)


pygame.init(); sdl_controller.init()
app = App()
app.media_dir = lambda: Path("media")  # don't show this computer's folders
frame = landscape()
app.video.frame = ((960, 720), 960 * 3, frame.tobytes()); app.video.frame_id = 1
app.video.native_size = (960, 720)
app.video.fps = 30.0
app.tello.wifi = 82
app.pad.name = "PLAYSTATION(R)3 Controller"
state = {"pitch": -4, "roll": 6, "yaw": 37, "vgx": 9, "vgy": 2, "vgz": -3, "templ": 58, "temph": 61,
         "tof": 182, "h": 170, "bat": 76, "time": 94}


def shot(name, setup=lambda: None):
    app.tello.state = dict(state)
    app.tello.state_time = time.monotonic() + 1000
    app.video.frame_time = time.monotonic() + 1000
    setup()
    app.sticks = (0.0, 0.55, 0.0, 0.2)
    app.draw_hud(app.draw_video())
    pygame.image.save(app.screen, str(out / f"{name}.png"))


app.tello.log_lines.clear()
app.tello.log("Speed: NORMAL")
shot("flight")
app.tello.log_lines.clear()


def ready():
    app.tello.state.update(h=0, tof=10, time=0, vgx=0, vgy=0, vgz=0)
shot("ready", ready)


def flip():
    app.pad.held.add("l1")
shot("flip", flip)
app.pad.held.discard("l1")


def keyboard():
    app.last_input = "keys"
shot("flight_keyboard", keyboard)
app.last_input = "pad"
for tab in ("Help", "Keyboard", "Gamepad", "Flight", "Video & Power"):
    app.menu.open(tab)
    if tab == "Keyboard":
        app.menu.sel = 10
    if tab == "Flight":
        app.menu.sel = 8
    shot("menu_" + tab.split()[0].lower())
app.menu.close()


def failed():
    app.land_failed, app.land_fails = True, 3
    app.tello.state["h"] = 120
shot("landing_failed", failed)
app.land_failed = False
print(sorted(p.name for p in out.iterdir()))
app.video.close(); app.tello.close()
