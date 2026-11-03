"""Tello Revived: fly a Ryze/DJI Tello from a computer with a gamepad or the keyboard."""

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # before any module imports pygame
# the window's class on Linux, so the dock matches it to the applications-menu entry (desktop.py)
os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "tello-revived")
os.environ.setdefault("SDL_VIDEO_WAYLAND_WMCLASS", "tello-revived")

VERSION = "0.10"
REPO_URL = "https://github.com/Ghorbel37/TelloRevived"
