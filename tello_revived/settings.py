"""User settings: defaults, loading and saving config.json, and the help table."""

import copy
import json

import pygame

from tello_revived.i18n import N_, t
from tello_revived.labels import key_label, pad_label
from tello_revived.paths import CONFIG_PATH

SPEED_NAMES = [N_("slow"), N_("normal"), N_("fast")]

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
        "fullscreen": pygame.KSCAN_F11, "quit": pygame.KSCAN_ESCAPE, "camera": pygame.KSCAN_V,
        "throw": pygame.KSCAN_G,
    },
    "pad": {
        "takeoff": "triangle", "land": "cross", "speed": "circle", "photo": "r1", "record": "square",
        "flip": "l1", "precision": "l2", "menu": "start", "camera": None, "throw": None,
        "emergency_1": "select", "emergency_2": "start",
    },
    "hud": {
        "top_bar": True, "flight_data": True, "heading": True, "attitude": True,
        "sticks": True, "messages": True, "hint_bar": True, "video_fps": True,
        "sound_alerts": False,  # beeps for low battery, auto-land, failed landing, refusals, firewall
        "vibration_alerts": False,  # the same alerts as gamepad vibration
        "units": "metric",  # metric / metric_kmh / imperial (hud.UNITS)
        "button_names": "auto",  # gamepad buttons named as on a PlayStation or Xbox pad; auto = by the pad's name
    },
    "drone": {
        "model": "tello",           # tello / edu / tt - only the RoboMaster TT (SDK 3.0) can change stream quality
    },
    "flight": {
        "move_stick": "left",
        "speed_slow": 30, "speed_normal": 60, "speed_fast": 100,
        "deadzone": 0.08, "expo": 0.35, "precision": 0.3,
        "retry_landing": False, "land_attempts": 3, "takeoff_pause": 0, "land_on_quit": True,
        "rejoin_wifi": True,  # go back to the drone's Wi-Fi if the computer drops it mid-session
    },
    "power": {
        "video": "flying",          # flying (only while airborne) / on / off - the idle drone runs hot
        "resolution": "default",    # default / high / low     (SDK 3.0 firmware only)
        "stream_fps": "default",    # default / high / middle / low
        "bitrate": "default",       # default / auto / 1..5 Mbps
        "app_fps": 60, "auto_land_battery": 0, "low_battery_warning": 20,
    },
    "files": {
        "media_dir": "",  # where photos and recordings go; empty = the media folder next to the app
        "flight_log": False,  # a CSV of the telemetry for each flight, in the same folder (off unless chosen)
    },
    "app": {
        "check_updates": None,  # ask GitHub at start for a newer release; None = ask the user first
        "language": "auto",  # a file in tello_revived/locales, "en", or "auto" = the computer's language
    },
}

DRONE_MODELS = [("tello", N_("Tello")), ("edu", N_("Tello EDU")), ("tt", N_("RoboMaster TT"))]


def stream_settings_supported(settings):
    """Only SDK 3.0 (RoboMaster TT) has setresolution / setfps / setbitrate."""
    return settings["drone"]["model"] == "tt"


KEY_ACTIONS = [
    ("forward", N_("Move forward")), ("back", N_("Move back")), ("left", N_("Move left")), ("right", N_("Move right")),
    ("up", N_("Climb")), ("down", N_("Descend")), ("turn_left", N_("Turn left")), ("turn_right", N_("Turn right")),
    ("precision", N_("Precision (hold)")), ("flip", N_("Flip (hold + move key)")),
    ("takeoff", N_("Take off")), ("throw", N_("Throw & go")), ("land", N_("Land")),
    ("emergency", N_("EMERGENCY motor stop")),
    ("photo", N_("Photo")), ("record", N_("Start / stop recording")), ("speed", N_("Cycle speed mode")),
    ("speed_slow", N_("Speed: slow")), ("speed_normal", N_("Speed: normal")), ("speed_fast", N_("Speed: fast")),
    ("help", N_("Help")), ("settings", N_("Settings")), ("fullscreen", N_("Fullscreen")), ("quit", N_("Quit")),
    ("camera", N_("Front / down camera (EDU, TT)")),
]

PAD_ACTIONS = [
    ("takeoff", N_("Take off")), ("throw", N_("Throw & go")), ("land", N_("Land")), ("speed", N_("Cycle speed mode")),
    ("photo", N_("Photo")), ("record", N_("Start / stop recording")),
    ("flip", N_("Flip (hold + D-pad)")), ("precision", N_("Precision (hold)")),
    ("menu", N_("Help / settings")), ("camera", N_("Front / down camera (EDU, TT)")),
    ("emergency_1", N_("EMERGENCY button 1")), ("emergency_2", N_("EMERGENCY button 2 (press both)")),
]

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


def help_rows(settings):
    """(what, keyboard, gamepad) rows describing the current bindings."""
    k = {a: key_label(s) for a, s in settings["keys"].items()}
    p = {a: pad_label(b) for a, b in settings["pad"].items()}
    stick = {"left": t("Left stick"), "right": t("Right stick")}
    move = settings["flight"]["move_stick"]
    other = stick["right" if move == "left" else "left"]
    return [
        (N_("Forward / back / sideways"), f"{k['forward']} {k['left']} {k['back']} {k['right']}", stick[move]),
        (N_("Climb / descend"), f"{k['up']} / {k['down']}", t("{stick} up / down", stick=other)),
        (N_("Turn"), f"{k['turn_left']} / {k['turn_right']}", t("{stick} left / right", stick=other)),
        (N_("Precision (hold)"), k["precision"], p["precision"]),
        (N_("Take off"), k["takeoff"], p["takeoff"]),
        (N_("Throw & go"), k["throw"], p["throw"]),
        (N_("Land"), k["land"], p["land"]),
        (N_("Speed mode"), f"{k['speed_slow']} {k['speed_normal']} {k['speed_fast']}"
                           + (f" / {k['speed']}" if settings["keys"]["speed"] else ""), p["speed"]),
        (N_("Photo"), k["photo"], p["photo"]),
        (N_("Start / stop recording"), k["record"], p["record"]),
        (N_("Flip"), t("{key} + move key", key=k["flip"]), t("{button} + D-pad", button=p["flip"])),
        (N_("EMERGENCY motor stop"), k["emergency"], f"{p['emergency_1']} + {p['emergency_2']}"),
        (N_("Help / settings"), f"{k['help']} / {k['settings']}", p["menu"]),
        (N_("Front / down camera (EDU, TT)"), k["camera"], p["camera"]),
        (N_("Fullscreen"), k["fullscreen"], "-"),
        (N_("Quit (lands first)"), k["quit"], "-"),
    ]
