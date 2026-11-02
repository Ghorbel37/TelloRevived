"""Gamepad input: SDL's standard controller mapping, or a raw joystick fallback."""

import math
import threading

import pygame
from pygame._sdl2 import controller as sdl_controller

# Vibration for alerts, matching the sound alerts: (low motor, high motor, ms on, ms off) per pulse
RUMBLE = {
    "warning": [(0.5, 0.5, 200, 150), (0.5, 0.5, 200, 0)],                   # two pulses: low battery
    "alarm": [(1.0, 1.0, 150, 100), (1.0, 1.0, 150, 100), (1.0, 1.0, 150, 0)],  # three strong ones
    "error": [(0.8, 0.2, 450, 0)],                                           # one long rumble
}

# Only used when SDL doesn't recognise the pad as a standard controller.
# Run with --joytest to find the right numbers for your pad.
RAW_MAP = {
    "axes": {"lx": 0, "ly": 1, "rx": 2, "ry": 3, "l2": 4, "r2": 5},
    "buttons": {"cross": 0, "circle": 1, "square": 2, "triangle": 3, "select": 4, "ps": 5,
                "start": 6, "l3": 7, "r3": 8, "l1": 9, "r1": 10,
                "up": 11, "down": 12, "left": 13, "right": 14},
}

CTRL_BUTTONS = {
    pygame.CONTROLLER_BUTTON_A: "cross",
    pygame.CONTROLLER_BUTTON_B: "circle",
    pygame.CONTROLLER_BUTTON_X: "square",
    pygame.CONTROLLER_BUTTON_Y: "triangle",
    pygame.CONTROLLER_BUTTON_BACK: "select",
    pygame.CONTROLLER_BUTTON_GUIDE: "ps",
    pygame.CONTROLLER_BUTTON_START: "start",
    pygame.CONTROLLER_BUTTON_LEFTSTICK: "l3",
    pygame.CONTROLLER_BUTTON_RIGHTSTICK: "r3",
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: "l1",
    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: "r1",
    pygame.CONTROLLER_BUTTON_DPAD_UP: "up",
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: "down",
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: "left",
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: "right",
}

TRIGGERS = {pygame.CONTROLLER_AXIS_TRIGGERLEFT: "l2", pygame.CONTROLLER_AXIS_TRIGGERRIGHT: "r2"}
TRIGGER_ON, TRIGGER_OFF = 0.6, 0.3  # how far a trigger is pulled to count as pressed / released


class Gamepad:
    """First connected pad, via SDL's controller mapping when available, else raw joystick."""

    def __init__(self):
        self.ctl = None
        self.joy = None
        self.name = None
        self.held = set()

    def rescan(self):
        self.close()
        for i in range(pygame.joystick.get_count()):
            if sdl_controller.is_controller(i):
                self.ctl = sdl_controller.Controller(i)
                self.name = pygame.joystick.Joystick(i).get_name() or "Gamepad"
                return
        if pygame.joystick.get_count():
            self.joy = pygame.joystick.Joystick(0)
            self.name = f"{self.joy.get_name()} (raw)"

    def close(self):
        for dev in (self.ctl, self.joy):
            if dev:
                try:
                    dev.quit()
                except pygame.error:
                    pass
        self.ctl = self.joy = self.name = None
        self.held.clear()

    def handle(self, ev):
        """Track held buttons; return the button name on a press, else None."""
        name, down = None, False
        if self.ctl and ev.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
            name, down = CTRL_BUTTONS.get(ev.button), ev.type == pygame.CONTROLLERBUTTONDOWN
        elif self.joy and ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
            name = next((k for k, v in RAW_MAP["buttons"].items() if v == ev.button), None)
            down = ev.type == pygame.JOYBUTTONDOWN
        elif self.ctl and ev.type == pygame.CONTROLLERAXISMOTION and ev.axis in TRIGGERS:
            return self._trigger(TRIGGERS[ev.axis], ev.value / 32767)
        elif self.joy and ev.type == pygame.JOYAXISMOTION and ev.axis in (RAW_MAP["axes"]["l2"], RAW_MAP["axes"]["r2"]):
            name = "l2" if ev.axis == RAW_MAP["axes"]["l2"] else "r2"
            return self._trigger(name, (ev.value + 1) / 2)  # raw triggers rest at -1
        elif self.joy and ev.type == pygame.JOYHATMOTION:
            x, y = ev.value
            now = {d for d, on in (("left", x < 0), ("right", x > 0), ("down", y < 0), ("up", y > 0)) if on}
            pressed = now - self.held
            self.held -= {"up", "down", "left", "right"} - now
            self.held |= now
            return next(iter(pressed), None)
        if not name:
            return None
        if down:
            self.held.add(name)
            return name
        self.held.discard(name)
        return None

    def _trigger(self, name, value):
        """Treat an analog trigger as a button, so L2 / R2 can be bound like the others."""
        if value > TRIGGER_ON and name not in self.held:
            self.held.add(name)
            return name
        if value < TRIGGER_OFF:
            self.held.discard(name)
        return None

    def rumble(self, name):
        """Play a vibration pattern from RUMBLE, if the pad can vibrate."""
        delay = 0.0
        for low, high, on_ms, off_ms in RUMBLE.get(name, []):
            threading.Timer(delay, self._pulse, (low, high, on_ms)).start()
            delay += (on_ms + off_ms) / 1000

    def _pulse(self, low, high, ms):
        device = self.ctl or self.joy
        if device:
            try:
                device.rumble(low, high, ms)
            except pygame.error:
                pass  # this pad (or driver mode) can't vibrate

    def axes(self):
        """lx, ly, rx, ry in -1..1 (y down = +), l2, r2 in 0..1."""
        if self.ctl:
            g = self.ctl.get_axis
            return (g(pygame.CONTROLLER_AXIS_LEFTX) / 32767, g(pygame.CONTROLLER_AXIS_LEFTY) / 32767,
                    g(pygame.CONTROLLER_AXIS_RIGHTX) / 32767, g(pygame.CONTROLLER_AXIS_RIGHTY) / 32767,
                    g(pygame.CONTROLLER_AXIS_TRIGGERLEFT) / 32767, g(pygame.CONTROLLER_AXIS_TRIGGERRIGHT) / 32767)
        if self.joy:
            n = self.joy.get_numaxes()
            a = {k: (self.joy.get_axis(i) if i < n else 0.0) for k, i in RAW_MAP["axes"].items()}
            # raw triggers usually rest at -1
            return a["lx"], a["ly"], a["rx"], a["ry"], (a["l2"] + 1) / 2 if n > 4 else 0.0, (a["r2"] + 1) / 2 if n > 5 else 0.0
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0


def shape(v, deadzone, expo):
    """Deadzone + expo for one stick axis (expo 0 = linear, 1 = fully cubic)."""
    if abs(v) < deadzone:
        return 0.0
    v = math.copysign((abs(v) - deadzone) / (1 - deadzone), v)
    v = (1 - expo) * v + expo * v ** 3
    return max(-1.0, min(1.0, v))
