#!/usr/bin/env python3
"""Tello Revived - fly a Ryze/DJI Tello from a PC with a gamepad (PS3 via DsHidMini) or the keyboard.

    run.bat              start the app
    run.bat --joytest    show raw gamepad axis/button numbers (for RAW_MAP below)

Connect the PC's Wi-Fi to the TELLO-XXXXXX network first. In the app press H (or Start) for the
controls and O for settings; everything is saved in config.json next to this file.
"""

import argparse
import datetime
import math
import os
import queue
import socket
import sys
import threading
import time
from collections import deque
from fractions import Fraction
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import av
import pygame
from pygame._sdl2 import controller as sdl_controller

from menu import Menu
from settings import VERSION, Settings, data_dir, key_label, pad_label, resource_dir, stream_settings_supported

TELLO_ADDR = ("192.168.10.1", 8889)
CMD_PORT = 8889
STATE_PORT = 8890
VIDEO_URL = "udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=5000000"
MEDIA_DIR = data_dir() / "media"
ICON_PATH = resource_dir() / "assets" / "icon.png"
MONO = "consolas,dejavusansmono,menlo,couriernew"  # first one installed wins

RC_HZ = 20
BAR_H = 30  # height of the button guide at the bottom
LOW_BAT_TAKEOFF = 10  # the Tello refuses to take off at or below about this battery level
HOT_TEMP = 85  # degrees C; the HUD shows the temperature in red above this
STALE_VIDEO = 1.0  # seconds without frames before the last picture is dropped
LAND_STALL = 4.0  # seconds without descending before a landing attempt counts as failed
SPEED_NAMES = ["slow", "normal", "fast"]

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

FLIP_DIRS = {"up": "f", "down": "b", "left": "l", "right": "r"}
MOVE_FLIPS = {"forward": "f", "back": "b", "left": "l", "right": "r"}


class Tello:
    """Command, state and keep-alive link to the drone (SDK over UDP)."""

    def __init__(self, settings):
        self.settings = settings
        self.sock = self._udp(CMD_PORT)
        self.state_sock = self._udp(STATE_PORT)
        self.replies = queue.Queue()
        self.stream_on = None  # what we last told the drone (None = unknown)
        self.stream_settings_ok = None  # False once the drone rejects setresolution etc. (pre SDK 3.0)
        self.query_lock = threading.Lock()
        self.awaiting = False
        self.state = {}
        self.state_time = 0.0
        self.session_time = 0.0
        self.session = False
        self.wifi = None
        self.log_lines = deque(maxlen=6)
        self.running = True
        for target in (self._reply_loop, self._state_loop, self._link_loop):
            threading.Thread(target=target, daemon=True).start()

    @staticmethod
    def _udp(port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            s.ioctl(socket.SIO_UDP_CONNRESET, False)  # Windows: ignore ICMP "port unreachable"
        s.bind(("", port))
        s.settimeout(0.5)
        return s

    @property
    def connected(self):
        return time.monotonic() - self.state_time < 1.5

    @property
    def flying(self):
        return self.connected and self.state.get("h", 0) > 0

    def log(self, text):
        self.log_lines.append((time.monotonic(), text))

    def send(self, cmd):
        try:
            self.sock.sendto(cmd.encode(), TELLO_ADDR)
        except OSError:
            pass  # not on the Tello network (yet)

    def query(self, cmd, timeout, accept=lambda r: True):
        with self.query_lock:
            while not self.replies.empty():
                self.replies.get_nowait()
            self.awaiting = True
            try:
                self.send(cmd)
                deadline = time.monotonic() + timeout
                while (left := deadline - time.monotonic()) > 0:
                    try:
                        reply = self.replies.get(timeout=left)
                    except queue.Empty:
                        break
                    if accept(reply):
                        return reply
                    self.log(f"Tello: {reply}")  # a reply to some other command
                return None
            finally:
                self.awaiting = False

    def _reply_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(1024)
            except OSError:
                continue
            # the Tello sometimes pads replies with NUL bytes
            reply = data.decode(errors="replace").replace(chr(0), "").strip()
            if self.awaiting:
                self.replies.put(reply)
            else:
                self.log(f"Tello: {reply}")

    def _state_loop(self):
        while self.running:
            try:
                data, _ = self.state_sock.recvfrom(1024)
            except OSError:
                continue
            state = {}
            for field in data.decode(errors="ignore").strip().split(";"):
                key, _, value = field.partition(":")
                try:
                    state[key] = float(value)
                except ValueError:
                    pass
            if state:
                self.state = state
                self.state_time = time.monotonic()

    def want_video(self):
        mode = self.settings["power"]["video"]
        return mode == "on" or (mode == "flying" and self.flying)

    def apply_stream_settings(self):
        """Send the stream quality settings that aren't left at the drone's default."""
        p = self.settings["power"]
        if not stream_settings_supported(self.settings):
            return  # the user's model can't, so don't even ask
        cmds = []
        if p["resolution"] != "default":
            cmds.append(f"setresolution {p['resolution']}")
        if p["stream_fps"] != "default":
            cmds.append(f"setfps {p['stream_fps']}")
        if p["bitrate"] != "default":
            cmds.append(f"setbitrate {0 if p['bitrate'] == 'auto' else p['bitrate']}")
        if not cmds or self.stream_settings_ok is False:
            return  # nothing to set, or this drone already said it can't
        for cmd in cmds:
            reply = self.query(cmd, 2.0)
            if reply != "ok":
                self.stream_settings_ok = False
                self.log(f"This Tello can't change stream quality ('{cmd}': {reply or 'no reply'}) - "
                         "needs SDK 3.0 firmware, using its defaults")
                return
        self.stream_settings_ok = True

    def _link_loop(self):
        last_wifi = last_stream = 0.0
        while self.running:
            now = time.monotonic()
            if self.session and not self.connected and now - self.session_time > 3:
                self.session = False
                self.log("Link lost - reconnecting")
            if not self.session:
                if self.query("command", 1.0, lambda r: r == "ok"):
                    self.session = True
                    self.session_time = time.monotonic()
                    self.stream_on = None
                    self.log("Tello connected")
                    self.apply_stream_settings()
                else:
                    time.sleep(0.5)
                continue
            want = self.want_video()
            if want != self.stream_on and now - last_stream > 3:
                last_stream = now
                cmd = "streamon" if want else "streamoff"
                if self.query(cmd, 2.0, lambda r: r == "ok"):
                    self.stream_on = want
                else:
                    self.log(f"{cmd} got no reply - retrying")
            if self.connected and now - last_wifi > 3:
                last_wifi = now
                reply = self.query("wifi?", 1.0, lambda r: r.isdigit())
                if reply:
                    self.wifi = int(reply)
            time.sleep(0.25)

    def close(self):
        self.running = False


class Video:
    """Receives and decodes the H.264 stream; optionally records the raw stream to disk."""

    def __init__(self, log):
        self.log = log
        self.lock = threading.Lock()
        self.frame = None  # (width, height, rgb bytes)
        self.frame_id = 0
        self.frame_time = 0.0
        self.fps = 0.0
        self.rec_file = None
        self.rec_path = None
        self.rec_start = 0.0
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            try:
                container = av.open(VIDEO_URL, format="h264", timeout=(3.0, 3.0),
                                    options={"fflags": "nobuffer", "flags": "low_delay"})
            except Exception:
                time.sleep(0.2)
                continue  # nothing arriving yet
            try:
                stream = container.streams.video[0]
                frame_times = deque(maxlen=30)
                for packet in container.demux(stream):
                    if not self.running:
                        break
                    with self.lock:
                        if self.rec_file and packet.size:
                            self.rec_file.write(bytes(packet))
                    try:
                        frames = packet.decode()
                    except Exception:
                        continue  # corrupted packet (Wi-Fi loss) - next keyframe fixes it
                    for f in frames:
                        rgb = f.to_ndarray(format="rgb24")
                        now = time.monotonic()
                        frame_times.append(now)
                        if len(frame_times) > 1:
                            self.fps = (len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
                        with self.lock:
                            self.frame = (rgb.shape[1], rgb.shape[0], rgb.tobytes())
                            self.frame_id += 1
                            self.frame_time = now
            except Exception:
                pass  # stream timed out / dropped; reopen
            finally:
                container.close()

    @property
    def recording(self):
        return self.rec_file is not None

    def start_recording(self, path):
        with self.lock:
            self.rec_path = path
            self.rec_file = open(path, "wb")
            self.rec_start = time.monotonic()

    def stop_recording(self):
        with self.lock:
            f, path = self.rec_file, self.rec_path
            self.rec_file = None
        if f:
            f.close()
            threading.Thread(target=self._finish_recording, args=(path,), daemon=True).start()

    def _finish_recording(self, raw):
        mp4 = raw.with_suffix(".mp4")
        try:
            remux_to_mp4(raw, mp4)
            raw.unlink()
            self.log(f"Saved {mp4.name}")
        except Exception as e:
            self.log(f"Kept raw {raw.name} (mp4 failed: {e})")

    def close(self):
        self.stop_recording()
        self.running = False


def remux_to_mp4(src, dst, fps=30):
    """Wrap the raw Tello H.264 stream in an mp4 without re-encoding."""
    tb = Fraction(1, fps)
    with av.open(str(src), format="h264") as inp, av.open(str(dst), "w") as out:
        in_stream = inp.streams.video[0]
        out_stream = out.add_stream_from_template(in_stream)
        n = 0
        for packet in inp.demux(in_stream):
            if not packet.size:
                continue
            packet.stream = out_stream
            packet.time_base = tb
            packet.pts = packet.dts = n
            packet.duration = 1
            out.mux(packet)
            n += 1
        if not n:
            raise ValueError("no video in recording")


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


class App:
    def __init__(self):
        pygame.display.set_caption("Tello Revived")
        try:
            pygame.display.set_icon(pygame.image.load(str(ICON_PATH)))
        except (pygame.error, FileNotFoundError):
            pass
        self.windowed_size = (960, 720)
        self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.fullscreen = False
        self.settings = Settings()
        self.tello = Tello(self.settings)
        self.video = Video(self.tello.log)
        self.pad = Gamepad()
        self.speed_idx = 1
        self.menu = Menu(self)
        self.sticks = (0.0, 0.0, 0.0, 0.0)  # roll, pitch, throttle, yaw (-1..1, after scaling)
        self.last_rc = 0.0
        self.landing = False
        self.land_kick = 0.0
        self.land_fails = 0
        self.land_failed = False
        self.auto_landed = False
        self.takeoff_until = 0.0
        self.flip_until = 0.0
        self.quit_after_land = False
        self.held_scans = set()
        self.last_input = "pad"  # which device the button guide shows
        self.frame_surface = None
        self.scaled = None
        self.shown_frame_id = -1
        self.font = pygame.font.SysFont(MONO, 18, bold=True)
        self.font_big = pygame.font.SysFont(MONO, 30, bold=True)
        self.font_small = pygame.font.SysFont(MONO, 15)
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- actions -------------------------------------------------------------

    def takeoff(self):
        if not self.tello.connected:
            return self.tello.log("Not connected")
        self.tello.log("Taking off")
        self.landing = self.land_failed = False
        self.land_fails = 0
        self.takeoff_until = time.monotonic() + self.settings["flight"]["takeoff_pause"]
        threading.Thread(target=self._do_takeoff, daemon=True).start()

    def _do_takeoff(self):
        # "ok" comes once it hovers; a refusal comes straight away and is just "error"
        reply = self.tello.query("takeoff", 12.0)
        if reply == "ok" or self.tello.flying:
            return
        reason = self.takeoff_problem()
        if not reason:
            reason = ("no reply from the drone" if not reply else
                      f"the drone said '{reply}' with no reason - put it on a flat surface, or restart it")
        self.tello.log(f"Take off refused: {reason}")

    def takeoff_problem(self):
        """The likely reason the drone won't take off, from its battery and temperature."""
        st = self.tello.state
        bat, temp = st.get("bat", 100), st.get("temph", 0)
        if bat <= LOW_BAT_TAKEOFF:
            return f"battery {bat:.0f}% is too low - charge it"
        if temp >= HOT_TEMP:
            return f"drone too hot ({temp:.0f}°C) - let it cool down"
        return None

    def land(self):
        self.tello.log("Landing")
        self.tello.send("land")
        if not self.tello.flying:
            return
        self.land_kick = time.monotonic()
        if not self.landing:
            self.landing = True
            threading.Thread(target=self._watch_landing, daemon=True).start()

    def _watch_landing(self):
        """Count landings that don't happen; with retry_landing on, resend "land" automatically."""
        fl = self.settings["flight"]
        while True:
            result = self._wait_touchdown()
            if result == "down":
                self.land_fails, self.land_failed = 0, False
                self.tello.log("Landed")
                break
            if result == "lost":
                self.tello.log("Link lost while landing")
                break
            if result == "cancelled":
                break
            self.land_fails += 1
            if self.land_fails >= fl["land_attempts"]:
                self.land_failed = True
                self.tello.log(f"Landing failed {self.land_fails} times")
                break
            if fl["retry_landing"]:
                self.tello.log(f"Landing stalled - retrying ({self.land_fails + 1}/{fl['land_attempts']})")
                self.tello.send("land")
                self.land_kick = time.monotonic()
            else:
                self.tello.log(f"Landing didn't work ({self.land_fails}/{fl['land_attempts']}) - press land again")
                break
        self.landing = False

    def _wait_touchdown(self):
        """'down', 'stalled' (stopped descending), 'lost' (no telemetry) or 'cancelled'."""
        best = self.tello.state.get("h", 0)
        progress = time.monotonic()
        down_since = None
        while self.landing:
            now = time.monotonic()
            if not self.tello.connected:
                return "lost"
            if not self.tello.flying:
                down_since = down_since or now
                if now - down_since > 1.0:
                    return "down"
            else:
                down_since = None
                h = self.tello.state.get("h", 0)
                if h < best - 5:
                    best, progress = h, now
                elif now - max(progress, self.land_kick) > LAND_STALL:
                    return "stalled"
            time.sleep(0.1)
        return "cancelled"

    def emergency(self):
        for _ in range(3):
            self.tello.send("emergency")
        self.landing = self.land_failed = False
        self.tello.log("EMERGENCY - motors stopped")

    def flip(self, d):
        name = {"f": "forward", "b": "back", "l": "left", "r": "right"}[d]
        bat = self.tello.state.get("bat", 0)
        if not self.tello.flying:
            return self.tello.log("Flips only work in the air")
        if bat <= 50:
            return self.tello.log(f"No flip: battery {bat:.0f}% - the Tello only flips above 50%")
        if time.monotonic() < self.flip_until:
            return  # one at a time
        self.tello.log(f"Flip {name}")
        self.flip_until = time.monotonic() + 4.0  # no hover rc while it flips
        threading.Thread(target=self._do_flip, args=(d, name), daemon=True).start()

    def _do_flip(self, d, name):
        reply = self.tello.query(f"flip {d}", 4.0)
        self.flip_until = time.monotonic() + 0.3  # the drone answers once the flip is done
        if reply != "ok":
            self.tello.log(f"Drone refused the flip {name}: {reply or 'no reply'}"
                           f" (battery {self.tello.state.get('bat', 0):.0f}%)")

    def cycle_speed(self, idx=None):
        self.speed_idx = (self.speed_idx + 1) % len(SPEED_NAMES) if idx is None else idx
        self.tello.log(f"Speed: {SPEED_NAMES[self.speed_idx].upper()}")

    def toggle_help(self):
        self.menu.toggle("Help")

    def toggle_settings(self):
        self.menu.toggle("Keyboard")

    def on_setting_changed(self, section, key):
        stream_keys = (None, "resolution", "stream_fps", "bitrate")
        if (section == "drone" or section == "power" and key in stream_keys) and self.tello.session:
            threading.Thread(target=self.tello.apply_stream_settings, daemon=True).start()

    def camera_live(self):
        """True while the stream is wanted and frames are actually arriving."""
        return self.tello.want_video() and time.monotonic() - self.video.frame_time < 1.5

    def camera_off_reason(self):
        mode = self.settings["power"]["video"]
        if mode == "off":
            return "Camera is off (Settings > Video & Power)"
        if not self.tello.want_video():
            return "Camera starts at takeoff"
        return "No video from the drone"

    def photo(self):
        if not self.camera_live():
            return self.tello.log(f"No photo: {self.camera_off_reason()}")
        path = MEDIA_DIR / f"photo_{stamp()}.png"
        n = 2
        while path.exists():  # several photos in the same second
            path = MEDIA_DIR / f"photo_{stamp()}_{n}.png"
            n += 1
        pygame.image.save(self.frame_surface, str(path))
        self.tello.log(f"Saved {path.name}")

    def toggle_record(self):
        if self.video.recording:
            self.video.stop_recording()
            self.tello.log("Recording stopped - saving...")
        elif not self.camera_live():
            self.tello.log(f"Not recording: {self.camera_off_reason()}")
        else:
            self.video.start_recording(MEDIA_DIR / f"video_{stamp()}.h264")
            self.tello.log("Recording")

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.windowed_size = self.screen.get_size()
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.scaled = None

    # ---- input ---------------------------------------------------------------

    def on_pad_button(self, b):
        self.last_input = "pad"
        pad = self.settings["pad"]
        emergency = {pad["emergency_1"], pad["emergency_2"]} - {None}
        if b in emergency and emergency <= self.pad.held:
            return self.emergency()
        if self.menu.is_open:
            return self.menu.handle_pad(b)
        if b in FLIP_DIRS and pad["flip"] in self.pad.held:
            return self.flip(FLIP_DIRS[b])
        actions = {"takeoff": self.takeoff, "land": self.land, "speed": self.cycle_speed,
                   "photo": self.photo, "record": self.toggle_record, "menu": self.toggle_help}
        for action, fn in actions.items():
            if pad[action] == b:
                fn()

    def on_key(self, ev):
        keys = self.settings["keys"]
        sc = ev.scancode
        self.last_input = "keys"
        if sc == keys["emergency"] and not self.menu.capture:
            self.emergency()
            return True
        if self.menu.is_open:
            self.menu.handle_key(ev)
            return True
        if keys["flip"] in self.held_scans:
            for action, d in MOVE_FLIPS.items():
                if keys[action] == sc:
                    self.flip(d)
                    return True
        if sc == keys["quit"]:
            return self.request_quit()
        actions = {"takeoff": self.takeoff, "land": self.land, "speed": self.cycle_speed,
                   "speed_slow": lambda: self.cycle_speed(0), "speed_normal": lambda: self.cycle_speed(1),
                   "speed_fast": lambda: self.cycle_speed(2), "photo": self.photo,
                   "record": self.toggle_record, "help": self.toggle_help, "settings": self.toggle_settings,
                   "fullscreen": self.toggle_fullscreen}
        for action, fn in actions.items():
            if keys[action] == sc:
                fn()
        return True

    def request_quit(self):
        """Land before quitting; a second request quits right away."""
        if self.quit_after_land or not self.tello.flying or not self.settings["flight"]["land_on_quit"]:
            return False
        self.quit_after_land = True
        self.tello.log(f"Landing before quit ({key_label(self.settings['keys']['quit'])} again to quit now)")
        self.land()
        return True

    def read_sticks(self):
        fl, keys, held = self.settings["flight"], self.settings["keys"], self.held_scans
        lx, ly, rx, ry, l2, _ = (self.pad.axes() if fl["move_stick"] == "left"
                                 else self._swapped(self.pad.axes()))
        if max(abs(lx), abs(ly), abs(rx), abs(ry)) > 0.5:
            self.last_input = "pad"
        s = lambda v: shape(v, fl["deadzone"], fl["expo"])
        roll, pitch, throttle, yaw = s(lx), -s(ly), -s(ry), s(rx)
        # the arrow keys etc. drive the menu while it's open, so only the pad flies then
        down = lambda action: not self.menu.is_open and keys[action] is not None and keys[action] in held
        if not down("flip"):
            roll += down("right") - down("left")
            pitch += down("forward") - down("back")
        throttle += down("up") - down("down")
        yaw += down("turn_right") - down("turn_left")
        precision = max(l2, 1.0 if down("precision") or self.settings["pad"]["precision"] in self.pad.held else 0.0)
        scale = 1 - (1 - fl["precision"]) * precision
        clamp = lambda v: max(-1.0, min(1.0, v)) * scale
        self.sticks = (clamp(roll), clamp(pitch), clamp(throttle), clamp(yaw))

    @staticmethod
    def _swapped(axes):
        lx, ly, rx, ry, l2, r2 = axes
        return rx, ry, lx, ly, l2, r2

    def speed_limit(self):
        return self.settings["flight"][f"speed_{SPEED_NAMES[self.speed_idx]}"]

    def send_rc(self):
        now = time.monotonic()
        if now - self.last_rc < 1 / RC_HZ - 0.005:
            return
        self.last_rc = now
        idle = not any(self.sticks)
        pause_for_landing = self.landing and self.settings["flight"]["retry_landing"]
        if pause_for_landing and not idle:
            self.landing = False
            self.tello.log("Landing cancelled by stick input")
        if idle and (pause_for_landing or now < self.takeoff_until or now < self.flip_until):
            return  # don't let rc interrupt takeoff / landing / a flip
        if self.tello.connected:
            top = self.speed_limit()
            self.tello.send("rc " + " ".join(str(int(round(v * top))) for v in self.sticks))

    # ---- drawing -------------------------------------------------------------

    def text(self, s, pos, color=(235, 235, 235), font=None, anchor="topleft"):
        font = font or self.font
        s = s.replace(chr(0), "")  # pygame can't render NUL
        img = font.render(s, True, color)
        rect = img.get_rect(**{anchor: pos})
        self.screen.blit(font.render(s, True, (0, 0, 0)), rect.move(2, 2))
        self.screen.blit(img, rect)
        return rect

    def panel(self, rect, alpha=140):
        s = pygame.Surface(rect.size, pygame.SRCALPHA)
        s.fill((0, 0, 0, alpha))
        self.screen.blit(s, rect.topleft)

    def draw_video(self):
        with self.video.lock:
            frame, fid = self.video.frame, self.video.frame_id
        sw, sh = self.screen.get_size()
        if frame and fid != self.shown_frame_id:
            w, h, data = frame
            self.frame_surface = pygame.image.frombuffer(data, (w, h), "RGB")
            self.shown_frame_id = fid
            self.scaled = None
        self.screen.fill((12, 14, 18))
        if self.frame_surface and (not self.tello.want_video()
                                   or time.monotonic() - self.video.frame_time > STALE_VIDEO):
            # stream stopped or link dropped: forget the old picture, so it doesn't flash up at the
            # next takeoff (a new frame replaces it as soon as one arrives)
            self.frame_surface = self.scaled = None
        if not self.frame_surface:
            return pygame.Rect(0, 0, sw, sh)
        fw, fh = self.frame_surface.get_size()
        k = min(sw / fw, sh / fh)
        size = (int(fw * k), int(fh * k))
        if not self.scaled or self.scaled.get_size() != size:
            self.scaled = pygame.transform.smoothscale(self.frame_surface, size)
        rect = self.scaled.get_rect(center=(sw // 2, sh // 2))
        self.screen.blit(self.scaled, rect)
        return rect

    def draw_hud(self, area):
        t, st, now = self.tello, self.tello.state, time.monotonic()
        sw, sh = self.screen.get_size()
        blink = int(now * 2) % 2 == 0

        hud = self.settings["hud"]
        if hud["top_bar"]:
            self.draw_top_bar(blink, now)

        if not t.connected:
            self.text("Connect this PC's Wi-Fi to TELLO-XXXXXX and power on the drone",
                      (sw // 2, sh // 2), (220, 220, 220), anchor="center")
            self.text(f"Press {self.help_keys()} for controls", (sw // 2, sh // 2 + 30), (160, 160, 160),
                      self.font_small, "center")
        else:
            video_mode = self.settings["power"]["video"]
            if video_mode == "off":
                self.text("VIDEO OFF (battery saver)", (sw // 2, sh // 2 - 80), (160, 160, 160), self.font, "center")
            elif not t.want_video():
                self.text("Video starts at takeoff", (sw // 2, sh // 2 - 80), (160, 160, 160),
                          self.font, "center")
            elif now - self.video.frame_time > 2:
                self.text("NO VIDEO", (sw // 2, sh // 2 - 80), (240, 200, 60), self.font_big, "center")
            if hud["attitude"]:
                self.draw_attitude(area.center, st)
            if hud["flight_data"]:
                y = 50
                h = st.get("h", 0) / 100
                spd = math.hypot(st.get("vgx", 0), st.get("vgy", 0)) / 10
                for label, value in (("ALT", f"{h:4.1f} m"), ("TOF", f"{st.get('tof', 0) / 100:4.2f} m"),
                                     ("SPD", f"{spd:4.1f} m/s"), ("VS", f"{-st.get('vgz', 0) / 10:+4.1f} m/s")):
                    self.panel(pygame.Rect(8, y - 2, 160, 30), 110)
                    self.text(label, (14, y + 3), (160, 160, 160), self.font_small)
                    self.text(value, (160, y + 1), anchor="topright")
                    y += 34
            if hud["heading"]:
                hdg = int(st.get("yaw", 0)) % 360
                self.text(f"HDG {hdg:03d}°", (sw // 2, 42), anchor="midtop")
            if st.get("bat", 100) <= self.settings["power"]["low_battery_warning"] and blink:
                self.text("LOW BATTERY - LAND", (sw // 2, 80), (240, 70, 60), self.font_big, "midtop")
            if hud["video_fps"] and self.video.fps:
                self.text(f"{self.video.fps:.0f} fps", (sw - 10, 42), (160, 160, 160), self.font_small, "topright")

        bar = BAR_H if hud["hint_bar"] and not self.menu.is_open else 0
        if hud["sticks"]:
            self.draw_stick((70, sh - 70 - bar), *self.stick_pair("left"))
            self.draw_stick((sw - 70, sh - 70 - bar), *self.stick_pair("right"))

        if bar and t.connected and not t.flying and not self.landing:
            self.draw_takeoff_hint()

        if hud["messages"]:
            y = sh - 30 - bar
            for ts, msg in reversed(list(t.log_lines)):
                age = now - ts
                if age > 5:
                    continue
                self.text(msg, (sw // 2, y), (235, 235, 235) if age < 4 else (130, 130, 130),
                          self.font_small, "midbottom")
                y -= 20

        if self.land_failed and t.flying:
            self.draw_land_failed()

        if self.menu.is_open:
            self.menu.draw()
        elif bar:
            self.draw_hint_bar()

    # ---- button guide --------------------------------------------------------

    def input_device(self):
        """'pad' or 'keys': whichever was used last (the guide shows its buttons)."""
        return "pad" if self.pad.name and self.last_input == "pad" else "keys"

    def flip_held(self):
        """'pad' / 'keys' while the flip modifier is held, else None."""
        if self.settings["pad"]["flip"] and self.settings["pad"]["flip"] in self.pad.held:
            return "pad"
        if self.settings["keys"]["flip"] is not None and self.settings["keys"]["flip"] in self.held_scans:
            return "keys"
        return None

    def hint_items(self):
        """(mode, [(button, what, colour)]) for the bottom bar, most important first."""
        t, keys, pad = self.tello, self.settings["keys"], self.settings["pad"]
        k = lambda a: key_label(keys[a]) if keys[a] is not None else None
        p = lambda a: pad_label(pad[a]) if pad[a] else None
        on_pad = self.input_device() == "pad"
        b = p if on_pad else k
        red, amber = (240, 90, 80), (240, 200, 60)
        if on_pad:
            emergency = f"{p('emergency_1')} + {p('emergency_2')}" if pad["emergency_1"] and pad["emergency_2"] else None
            speed = p("speed")
            help_items = [(p("menu"), "Help & settings", None)]
        else:
            emergency = k("emergency")
            speed = " ".join(filter(None, (k("speed_slow"), k("speed_normal"), k("speed_fast")))) or k("speed")
            help_items = [(k("help"), "Help", None), (k("settings"), "Settings", None)]

        if t.flying and (flip := self.flip_held()):
            if flip == "pad":
                dirs = [("↑", "forward"), ("↓", "back"), ("←", "left"), ("→", "right")]
                items = [(f"D-pad {arrow}", f"Flip {what}", amber) for arrow, what in dirs]
            else:
                items = [(k(a), f"Flip {a}", amber) for a in ("forward", "back", "left", "right")]
            bat = t.state.get("bat", 0)
            items.append(("!", "needs > 50% battery" if bat > 50 else f"battery {bat:.0f}% - too low to flip", red))
            mode = ("FLIP", amber)
        elif t.flying:
            items = []
            if self.landing or self.land_failed:
                items.append((emergency, "EMERGENCY stop", red))
            items += [(b("land"), "Land", None),
                      (speed, f"Speed: {SPEED_NAMES[self.speed_idx]}", None),
                      *self.camera_items(b),
                      (b("flip"), "Hold: flips", None)] + help_items
            mode = ("LANDING", amber) if self.landing else ("FLYING", (90, 220, 120))
        elif t.connected:
            items = [(b("takeoff"), "Take off", None), *self.camera_items(b)] + help_items
            mode = ("READY", (120, 190, 255))
        else:
            items = help_items + [(k("quit"), "Quit", None)]
            mode = ("OFFLINE", (150, 150, 150))
        return mode, [(btn, what, col) for btn, what, col in items if btn and btn != "-"]

    def camera_items(self, b):
        """Photo / record buttons, only while there is a picture (stop is always offered)."""
        live = self.camera_live()
        items = [(b("photo"), "Photo", None)] if live else []
        if self.video.recording:
            items.append((b("record"), "Stop recording", None))
        elif live:
            items.append((b("record"), "Record", None))
        return items

    def draw_hint_bar(self):
        """Zellij-style strip of the buttons that matter right now."""
        sw, sh = self.screen.get_size()
        bar = pygame.Rect(0, sh - BAR_H, sw, BAR_H)
        self.panel(bar, 190)
        (mode, mode_col), items = self.hint_items()
        f = self.font_small
        img = f.render(f" {mode} ", True, (15, 18, 24))
        chip = img.get_rect(midleft=(6, bar.centery)).inflate(0, 8)
        pygame.draw.rect(self.screen, mode_col, chip)
        self.screen.blit(img, img.get_rect(center=chip.center))
        x = chip.right + 14
        for btn, what, col in items:
            kimg = f.render(f" {btn} ", True, (15, 18, 24))
            wimg = f.render(what, True, (225, 225, 225))
            if x + kimg.get_width() + 5 + wimg.get_width() > sw - 6:
                break  # narrow window: drop the less important ones
            chip = kimg.get_rect(midleft=(x, bar.centery)).inflate(0, 6)
            pygame.draw.rect(self.screen, col or (200, 205, 215), chip, border_radius=4)
            self.screen.blit(kimg, kimg.get_rect(center=chip.center))
            x = self.screen.blit(wimg, wimg.get_rect(midleft=(chip.right + 5, bar.centery))).right + 16

    def draw_takeoff_hint(self):
        sw, sh = self.screen.get_size()
        on_pad = self.input_device() == "pad"
        btn = pad_label(self.settings["pad"]["takeoff"]) if on_pad else key_label(self.settings["keys"]["takeoff"])
        if btn == "-":
            return
        if problem := self.takeoff_problem():
            rect = self.text("Can't take off", (sw // 2, sh // 2 + 110), (240, 70, 60), self.font_big, "center")
            self.text(problem[0].upper() + problem[1:], (sw // 2, rect.bottom + 6), (235, 235, 235),
                      self.font_small, "midtop")
            return
        rect = self.text(f"Press {btn} to take off", (sw // 2, sh // 2 + 110), (120, 255, 160),
                         self.font_big, "center")
        self.text("Check there is space around and above the drone", (sw // 2, rect.bottom + 6),
                  (170, 170, 170), self.font_small, "midtop")

    def draw_land_failed(self):
        sw, sh = self.screen.get_size()
        keys, pad = self.settings["keys"], self.settings["pad"]
        stick = "right" if self.settings["flight"]["move_stick"] == "left" else "left"
        emergency = key_label(keys["emergency"])
        if self.pad.name:
            emergency += f" or {pad_label(pad['emergency_1'])} + {pad_label(pad['emergency_2'])}"
        lines = [f"Landing didn't work {self.land_fails} times.",
                 f"Fly it down slowly yourself ({key_label(keys['down'])} / {stick} stick down),",
                 "then when it's just above the ground (under ~20 cm)",
                 f"stop the motors with EMERGENCY: {emergency}"]
        box = pygame.Rect(0, 0, min(sw - 20, 640), 70 + 24 * len(lines))
        box.midtop = (sw // 2, 200)  # below the flight data panel
        self.panel(box, 200)
        pygame.draw.rect(self.screen, (240, 70, 60), box, 3)
        self.text("LANDING FAILED", (box.centerx, box.top + 12), (240, 70, 60), self.font_big, "midtop")
        for i, line in enumerate(lines):
            self.text(line, (box.centerx, box.top + 56 + 24 * i), font=self.font_small, anchor="midtop")

    def stick_pair(self, side):
        """(x, y) the HUD shows for a physical stick."""
        roll, pitch, throttle, yaw = self.sticks
        return (roll, pitch) if self.settings["flight"]["move_stick"] == side else (yaw, throttle)

    def help_keys(self):
        k = key_label(self.settings["keys"]["help"])
        menu = self.settings["pad"]["menu"]
        return f"{k} or {pad_label(menu)}" if self.pad.name and menu else k

    def draw_top_bar(self, blink, now):
        t, st = self.tello, self.tello.state
        sw = self.screen.get_width()
        self.panel(pygame.Rect(0, 0, sw, 34))
        x = 10
        if t.connected:
            x = self.text("● LINK", (x, 7), (90, 220, 120)).right + 18
            bat = int(st.get("bat", 0))
            low = self.settings["power"]["low_battery_warning"]
            col = (90, 220, 120) if bat > 2 * low else (240, 200, 60) if bat > low else (240, 70, 60)
            x = self.text(f"BAT {bat}%", (x, 7), col).right + 18
            if t.wifi is not None:
                col = (90, 220, 120) if t.wifi > 60 else (240, 200, 60) if t.wifi > 30 else (240, 70, 60)
                x = self.text(f"WIFI {t.wifi}", (x, 7), col).right + 18
            tm = int(st.get("time", 0))
            x = self.text(f"FLT {tm // 60}:{tm % 60:02d}", (x, 7)).right + 18
            temp = (st.get("templ", 0) + st.get("temph", 0)) / 2
            self.text(f"{temp:.0f}°C", (x, 7), (240, 70, 60) if temp > 85 else (235, 235, 235))
        else:
            self.text("● SEARCHING FOR TELLO" if blink else "○ SEARCHING FOR TELLO", (x, 7), (240, 200, 60))
        right = sw - 10
        right = self.text(SPEED_NAMES[self.speed_idx].upper(), (right, 7), (120, 190, 255),
                          anchor="topright").left - 18
        right = self.text(self.pad.name or "keyboard", (right, 7), (180, 180, 180), self.font_small,
                          "topright").left - 18
        if self.video.recording:
            secs = int(now - self.video.rec_start)
            self.text(f"{'●' if blink else ' '} REC {secs // 60}:{secs % 60:02d}", (right, 7), (240, 70, 60),
                      anchor="topright")

    def draw_attitude(self, center, st):
        cx, cy = center
        roll = math.radians(st.get("roll", 0))
        dy = -st.get("pitch", 0) * 4
        dx, ddy = math.cos(roll) * 110, -math.sin(roll) * 110
        col = (120, 255, 160)
        for gap in (-1, 1):  # horizon in two halves around the centre
            pygame.draw.line(self.screen, col, (cx + gap * dx * 0.35, cy + dy + gap * ddy * 0.35),
                             (cx + gap * dx, cy + dy + gap * ddy), 2)
        pygame.draw.lines(self.screen, (255, 255, 255), False,
                          [(cx - 34, cy), (cx - 12, cy), (cx, cy + 8), (cx + 12, cy), (cx + 34, cy)], 2)

    def draw_stick(self, center, x, y):
        r = pygame.Rect(0, 0, 90, 90)
        r.center = center
        self.panel(r, 110)
        pygame.draw.rect(self.screen, (120, 120, 120), r, 1)
        pygame.draw.line(self.screen, (80, 80, 80), r.midleft, r.midright)
        pygame.draw.line(self.screen, (80, 80, 80), r.midtop, r.midbottom)
        pygame.draw.circle(self.screen, (120, 190, 255), (center[0] + x * 40, center[1] - y * 40), 7)

    # ---- main loop -----------------------------------------------------------

    def run(self):
        clock = pygame.time.Clock()
        running = True
        minimized = False
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = self.request_quit()
                elif ev.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                    self.pad.rescan()
                    self.tello.log(f"Gamepad: {self.pad.name}" if self.pad.name else "Gamepad disconnected")
                elif ev.type == pygame.KEYDOWN:
                    self.held_scans.add(ev.scancode)
                    running = self.on_key(ev)
                elif ev.type == pygame.KEYUP:
                    self.held_scans.discard(ev.scancode)
                elif ev.type == pygame.WINDOWFOCUSLOST:
                    self.held_scans.clear()
                elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL):
                    if self.menu.is_open:
                        self.menu.handle_mouse(ev)
                elif ev.type == pygame.WINDOWMINIMIZED:
                    minimized = True
                elif ev.type in (pygame.WINDOWRESTORED, pygame.WINDOWMAXIMIZED, pygame.WINDOWSHOWN):
                    minimized = False
                else:
                    button = self.pad.handle(ev)
                    if button:
                        self.on_pad_button(button)
            if self.quit_after_land and not self.landing:
                self.quit_after_land = False
                if self.tello.flying:
                    self.tello.log("Quit cancelled - the drone is still flying")
                else:
                    running = False
            self.check_battery()
            if self.video.recording and not self.tello.want_video():
                self.toggle_record()  # e.g. landed with video set to "only while flying"
            self.read_sticks()
            self.send_rc()
            if not minimized:  # nothing to see: skip drawing to save power
                area = self.draw_video()
                self.draw_hud(area)
                pygame.display.flip()
            clock.tick(RC_HZ if minimized else self.settings["power"]["app_fps"])
        self.shutdown()

    def check_battery(self):
        """Auto-land once per flight when the battery reaches the configured level."""
        limit = self.settings["power"]["auto_land_battery"]
        if not self.tello.flying:
            self.auto_landed = False
            return
        bat = self.tello.state.get("bat", 100)
        if limit and not self.auto_landed and bat <= limit:
            self.auto_landed = True
            self.tello.log(f"Battery {bat:.0f}% - auto landing")
            self.land()

    def shutdown(self):
        if self.tello.flying:  # forced quit mid-flight: last-ditch land
            for _ in range(3):
                self.tello.send("land")
                time.sleep(0.1)
        self.video.close()
        self.tello.close()
        pygame.quit()


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def joytest():
    """Print raw joystick values so RAW_MAP can be adjusted."""
    screen = pygame.display.set_mode((640, 480))
    pygame.display.set_caption("Gamepad test - close window to exit")
    font = pygame.font.SysFont(MONO, 16)
    clock = pygame.time.Clock()
    joys = {}
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.JOYDEVICEADDED:
                j = pygame.joystick.Joystick(ev.device_index)
                joys[j.get_instance_id()] = j
            elif ev.type == pygame.JOYDEVICEREMOVED:
                joys.pop(ev.instance_id, None)
        screen.fill((15, 15, 20))
        lines = [] if joys else ["No gamepad detected"]
        for i, j in enumerate(joys.values()):
            std = "yes" if sdl_controller.is_controller(i) else "NO - uses RAW_MAP"
            lines += [f"{j.get_name()}", f"  GUID {j.get_guid()}", f"  standard mapping: {std}",
                      "  axes:    " + "  ".join(f"{a}:{j.get_axis(a):+.2f}" for a in range(j.get_numaxes())),
                      "  buttons: " + " ".join(str(b) for b in range(j.get_numbuttons()) if j.get_button(b)),
                      "  hats:    " + " ".join(str(j.get_hat(h)) for h in range(j.get_numhats())), ""]
        for n, line in enumerate(lines):
            screen.blit(font.render(line, True, (220, 220, 220)), (12, 12 + n * 22))
        pygame.display.flip()
        clock.tick(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"Tello Revived v{VERSION}")
    parser.add_argument("--joytest", action="store_true", help="show raw gamepad input")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    pygame.init()
    sdl_controller.init()
    if args.joytest:
        joytest()
        pygame.quit()
        return
    if args.selftest:
        return selftest()
    try:
        app = App()
    except OSError as e:
        pygame.display.set_caption("Tello Revived")
        message_window([f"Can't open the Tello ports {CMD_PORT}/{STATE_PORT}:", str(e), "",
                        "Tello Revived (or another drone app) is probably already running.",
                        "Close it and start Tello Revived again."])
        pygame.quit()
        return 1
    app.run()


def message_window(lines):
    """Show some text until the window is closed or a key / button is pressed."""
    screen = pygame.display.set_mode((720, 60 + 28 * len(lines)))
    font = pygame.font.SysFont(MONO, 17)
    clock = pygame.time.Clock()
    while not any(ev.type in (pygame.QUIT, pygame.KEYDOWN, pygame.CONTROLLERBUTTONDOWN, pygame.JOYBUTTONDOWN)
                  for ev in pygame.event.get()):
        screen.fill((15, 15, 20))
        for n, line in enumerate(lines):
            screen.blit(font.render(line, True, (235, 235, 235)), (24, 30 + 28 * n))
        pygame.display.flip()
        clock.tick(20)


def selftest():
    """Start the app, draw a few frames and check the H.264 decoder, then exit (used by the builds)."""
    global CMD_PORT, STATE_PORT
    CMD_PORT = STATE_PORT = 0  # any free port, so it runs next to a real session
    try:
        av.CodecContext.create("h264", "r")
        assert ICON_PATH.exists(), f"missing {ICON_PATH}"
        key_label(pygame.KSCAN_UP)
        import settings
        if not settings._sdl:
            print("warning: SDL2 library not found - key names use the US layout")
        app = App()
        for _ in range(5):
            app.read_sticks()
            app.draw_hud(app.draw_video())
            pygame.display.flip()
        app.shutdown()
    except Exception:  # a windowed build would show a dialog and hang CI instead
        import traceback
        traceback.print_exc()
        return 1
    print("selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
