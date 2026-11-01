"""User settings: defaults, load/save to config.json, and display names for keys and pad buttons."""

import copy
import ctypes
import json
import os
from pathlib import Path

import pygame

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

# Keyboard bindings are scancodes (physical key positions), so they work on any layout.
DEFAULTS = {
    "keys": {
        "forward": pygame.KSCAN_W, "back": pygame.KSCAN_S, "left": pygame.KSCAN_A, "right": pygame.KSCAN_D,
        "up": pygame.KSCAN_UP, "down": pygame.KSCAN_DOWN,
        "turn_left": pygame.KSCAN_LEFT, "turn_right": pygame.KSCAN_RIGHT,
        "precision": pygame.KSCAN_LSHIFT, "flip": pygame.KSCAN_LCTRL,
        "takeoff": pygame.KSCAN_T, "land": pygame.KSCAN_L, "emergency": pygame.KSCAN_BACKSPACE,
        "photo": pygame.KSCAN_P, "record": pygame.KSCAN_R, "speed": None,
        "speed_slow": pygame.KSCAN_1, "speed_normal": pygame.KSCAN_2, "speed_fast": pygame.KSCAN_3,
        "help": pygame.KSCAN_H, "settings": pygame.KSCAN_O,
        "fullscreen": pygame.KSCAN_F11, "quit": pygame.KSCAN_ESCAPE,
    },
    "pad": {
        "takeoff": "triangle", "land": "cross", "speed": "circle", "photo": "r1", "record": "square",
        "flip": "l1", "precision": None, "menu": "start",
        "emergency_1": "select", "emergency_2": "start",
    },
    "hud": {
        "top_bar": True, "flight_data": True, "heading": True, "attitude": True,
        "sticks": True, "messages": True, "help_hint": True, "video_fps": True,
    },
    "flight": {
        "move_stick": "left",
        "speed_slow": 30, "speed_normal": 60, "speed_fast": 100,
        "deadzone": 0.08, "expo": 0.35, "precision": 0.3,
        "takeoff_pause": 6, "land_on_quit": True,
    },
}

KEY_ACTIONS = [
    ("forward", "Move forward"), ("back", "Move back"), ("left", "Move left"), ("right", "Move right"),
    ("up", "Climb"), ("down", "Descend"), ("turn_left", "Turn left"), ("turn_right", "Turn right"),
    ("precision", "Precision (hold)"), ("flip", "Flip (hold + move key)"),
    ("takeoff", "Take off"), ("land", "Land"), ("emergency", "EMERGENCY motor stop"),
    ("photo", "Photo"), ("record", "Start / stop recording"), ("speed", "Cycle speed mode"),
    ("speed_slow", "Speed: slow"), ("speed_normal", "Speed: normal"), ("speed_fast", "Speed: fast"),
    ("help", "Help"), ("settings", "Settings"), ("fullscreen", "Fullscreen"), ("quit", "Quit"),
]

PAD_ACTIONS = [
    ("takeoff", "Take off"), ("land", "Land"), ("speed", "Cycle speed mode"),
    ("photo", "Photo"), ("record", "Start / stop recording"),
    ("flip", "Flip (hold + D-pad)"), ("precision", "Precision (hold, L2 always works)"),
    ("menu", "Help / settings"),
    ("emergency_1", "EMERGENCY button 1"), ("emergency_2", "EMERGENCY button 2 (press both)"),
]

PAD_LABELS = {
    "cross": "Cross", "circle": "Circle", "square": "Square", "triangle": "Triangle",
    "select": "Select", "start": "Start", "ps": "PS", "l1": "L1", "r1": "R1", "l3": "L3", "r3": "R3",
    "up": "D-pad up", "down": "D-pad down", "left": "D-pad left", "right": "D-pad right",
}


class Settings:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def __getitem__(self, section):
        return self.data[section]

    def load(self):
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for section, values in saved.items():
            if section not in self.data or not isinstance(values, dict):
                continue
            for key, value in values.items():
                if key in self.data[section] and _compatible(DEFAULTS[section][key], value):
                    self.data[section][key] = value

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def reset(self, section):
        self.data[section] = copy.deepcopy(DEFAULTS[section])
        self.save()


def _compatible(default, value):
    if default is None or value is None:
        return True  # bindings may be unset
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(default))


_sdl = None


def key_label(scancode):
    """Name of the key at this physical position on the current keyboard layout."""
    global _sdl
    if scancode is None:
        return "-"
    try:
        if _sdl is None:
            _sdl = ctypes.CDLL(os.path.join(os.path.dirname(pygame.__file__), "SDL2.dll"))
            _sdl.SDL_GetKeyFromScancode.restype = ctypes.c_int32
            _sdl.SDL_GetKeyFromScancode.argtypes = [ctypes.c_int]
        name = pygame.key.name(_sdl.SDL_GetKeyFromScancode(scancode))
    except (OSError, AttributeError):
        name = ""
    if not name:
        return f"key {scancode}"
    return name.upper() if len(name) == 1 else name.title()


def pad_label(button):
    return PAD_LABELS.get(button, "-") if button else "-"
