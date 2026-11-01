"""User settings: defaults, load/save to config.json, and display names for keys and pad buttons."""

import copy
import ctypes
import json
import sys
from pathlib import Path

import pygame


def data_dir():
    """Where config.json and media/ go: next to the script, or next to the built app."""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":  # don't write inside the .app bundle
            return Path.home() / "Tello Revived"
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir():
    """Where bundled files (assets/) are: the source folder, or PyInstaller's unpack folder."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


VERSION = "0.7"
CONFIG_PATH = data_dir() / "config.json"

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
        "sticks": True, "messages": True, "hint_bar": True, "video_fps": True,
    },
    "drone": {
        "model": "tello",           # tello / edu / tt - only the RoboMaster TT (SDK 3.0) can change stream quality
    },
    "flight": {
        "move_stick": "left",
        "speed_slow": 30, "speed_normal": 60, "speed_fast": 100,
        "deadzone": 0.08, "expo": 0.35, "precision": 0.3,
        "retry_landing": False, "land_attempts": 3, "takeoff_pause": 0, "land_on_quit": True,
    },
    "power": {
        "video": "flying",          # flying (only while airborne) / on / off - the idle drone runs hot
        "resolution": "default",    # default / high / low     (SDK 3.0 firmware only)
        "stream_fps": "default",    # default / high / middle / low
        "bitrate": "default",       # default / auto / 1..5 Mbps
        "app_fps": 60, "auto_land_battery": 0, "low_battery_warning": 20,
    },
}

DRONE_MODELS = [("tello", "Tello"), ("edu", "Tello EDU"), ("tt", "RoboMaster TT")]


def stream_settings_supported(settings):
    """Only SDK 3.0 (RoboMaster TT) has setresolution / setfps / setbitrate."""
    return settings["drone"]["model"] == "tt"


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
            self.path.parent.mkdir(parents=True, exist_ok=True)
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


def _load_sdl():
    """The SDL2 library pygame uses (already loaded, so this just gets a handle to it)."""
    base = Path(pygame.__file__).resolve().parent
    # Windows: pygame/SDL2.dll, macOS: pygame/.dylibs, Linux: pygame_ce.libs next to pygame
    for folder in (base, base / ".dylibs", base.parent / "pygame_ce.libs", base.parent):
        for lib in sorted(folder.glob("*SDL2*")):
            if "sdl2_" in lib.name.lower():  # SDL2_image, SDL2_ttf, ...
                continue
            try:
                sdl = ctypes.CDLL(str(lib))
                sdl.SDL_GetKeyFromScancode.restype = ctypes.c_int32
                sdl.SDL_GetKeyFromScancode.argtypes = [ctypes.c_int]
                return sdl
            except (OSError, AttributeError):
                continue
    return False


def _us_key(scancode):
    """US-layout key code for a scancode, if SDL can't be asked."""
    if 4 <= scancode <= 29:
        return ord("a") + scancode - 4
    if 30 <= scancode <= 39:
        return ord("1234567890"[scancode - 30])
    return {40: 13, 41: 27, 42: 8, 43: 9, 44: 32}.get(scancode, scancode | 1 << 30)


def key_label(scancode):
    """Name of the key at this physical position on the current keyboard layout."""
    global _sdl
    if scancode is None:
        return "-"
    if _sdl is None:
        _sdl = _load_sdl()
    try:
        name = pygame.key.name(_sdl.SDL_GetKeyFromScancode(scancode) if _sdl else _us_key(scancode))
    except (OSError, ValueError):
        name = ""
    if not name:
        return f"key {scancode}"
    return name.upper() if len(name) == 1 else name.title()


def pad_label(button):
    return PAD_LABELS.get(button, "-") if button else "-"


def help_rows(settings):
    """(what, keyboard, gamepad) rows describing the current bindings."""
    k = {a: key_label(s) for a, s in settings["keys"].items()}
    p = {a: pad_label(b) for a, b in settings["pad"].items()}
    move = settings["flight"]["move_stick"].title()
    other = "Right" if move == "Left" else "Left"
    precision = "L2" + (f" / {p['precision']}" if settings["pad"]["precision"] else "")
    return [
        ("Forward / back / sideways", f"{k['forward']} {k['left']} {k['back']} {k['right']}", f"{move} stick"),
        ("Climb / descend", f"{k['up']} / {k['down']}", f"{other} stick up / down"),
        ("Turn", f"{k['turn_left']} / {k['turn_right']}", f"{other} stick left / right"),
        ("Precision (hold)", k["precision"], precision),
        ("Take off", k["takeoff"], p["takeoff"]),
        ("Land", k["land"], p["land"]),
        ("Speed mode", f"{k['speed_slow']} {k['speed_normal']} {k['speed_fast']}"
                       + (f" / {k['speed']}" if settings["keys"]["speed"] else ""), p["speed"]),
        ("Photo", k["photo"], p["photo"]),
        ("Start / stop recording", k["record"], p["record"]),
        ("Flip", f"{k['flip']} + move key", f"{p['flip']} + D-pad"),
        ("EMERGENCY motor stop", k["emergency"], f"{p['emergency_1']} + {p['emergency_2']}"),
        ("Help / settings", f"{k['help']} / {k['settings']}", p["menu"]),
        ("Fullscreen", k["fullscreen"], "-"),
        ("Quit (lands first)", k["quit"], "-"),
    ]
