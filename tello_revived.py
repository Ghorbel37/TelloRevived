#!/usr/bin/env python3
"""Tello Revived - fly a Ryze/DJI Tello from a PC with a gamepad (PS3 via DsHidMini) or the keyboard.

    run.bat              start the app
    run.bat --joytest    show raw gamepad axis/button numbers (for RAW_MAP below)

Connect the PC's Wi-Fi to the TELLO-XXXXXX network first. Press H in the app for the controls.
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

TELLO_ADDR = ("192.168.10.1", 8889)
CMD_PORT = 8889
STATE_PORT = 8890
VIDEO_URL = "udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=5000000"
MEDIA_DIR = Path(__file__).resolve().parent / "media"

RC_HZ = 20
SPEED_MODES = [("SLOW", 30), ("NORMAL", 60), ("FAST", 100)]  # max rc value per mode
DEADZONE = 0.08
EXPO = 0.35            # 0 = linear sticks, 1 = fully cubic (softer around centre)
PRECISION_SCALE = 0.3  # speed multiplier with L2 fully pressed / Shift held

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
# Movement keys go by physical position (scancode), so WASD is ZQSD on AZERTY
MOVE_SCANS = {pygame.KSCAN_W: "f", pygame.KSCAN_S: "b", pygame.KSCAN_A: "l", pygame.KSCAN_D: "r"}
TAKEOFF_GRACE = 6.0  # seconds of no rc after takeoff, unless the sticks move

HELP_LINES = [
    ("GAMEPAD", ""),
    ("Left stick", "forward / back, sideways"),
    ("Right stick", "climb / descend, turn"),
    ("Triangle / Cross", "take off / land"),
    ("Circle", "cycle speed mode"),
    ("L2 (analog)", "precision - slows everything down"),
    ("R1 / Square", "photo / start-stop recording"),
    ("L1 + D-pad", "flip"),
    ("Select + Start", "EMERGENCY motor stop"),
    ("Start or PS", "this help"),
    ("", ""),
    ("KEYBOARD", ""),
    ("W A S D", "forward / left / back / right (Z Q S D on AZERTY)"),
    ("Arrow up / down", "climb / descend"),
    ("Arrow left / right", "turn"),
    ("Shift (hold)", "precision"),
    ("T / L", "take off / land"),
    ("1 2 3", "speed mode"),
    ("P / R", "photo / start-stop recording"),
    ("Ctrl + W A S D", "flip"),
    ("Backspace", "EMERGENCY motor stop"),
    ("H / F11 / Esc", "help / fullscreen / quit (lands first)"),
]


class Tello:
    """Command, state and keep-alive link to the drone (SDK over UDP)."""

    def __init__(self):
        self.sock = self._udp(CMD_PORT)
        self.state_sock = self._udp(STATE_PORT)
        self.replies = queue.Queue()
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
            reply = data.decode(errors="replace").strip()
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

    def _link_loop(self):
        last_wifi = 0.0
        while self.running:
            now = time.monotonic()
            if self.session and not self.connected and now - self.session_time > 3:
                self.session = False
                self.log("Link lost - reconnecting")
            if not self.session:
                if self.query("command", 1.0, lambda r: r == "ok"):
                    if not self.query("streamon", 2.0, lambda r: r == "ok"):
                        self.log("streamon got no reply - video may not start")
                    self.session = True
                    self.session_time = time.monotonic()
                    self.log("Tello connected")
                else:
                    time.sleep(0.5)
                continue
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


def shape(v):
    """Deadzone + expo for one stick axis."""
    if abs(v) < DEADZONE:
        return 0.0
    v = math.copysign((abs(v) - DEADZONE) / (1 - DEADZONE), v)
    v = (1 - EXPO) * v + EXPO * v ** 3
    return max(-1.0, min(1.0, v))


class App:
    def __init__(self):
        pygame.display.set_caption("Tello Revived")
        self.windowed_size = (960, 720)
        self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.fullscreen = False
        self.tello = Tello()
        self.video = Video(self.tello.log)
        self.pad = Gamepad()
        self.speed_idx = 1
        self.show_help = False
        self.sticks = (0.0, 0.0, 0.0, 0.0)  # roll, pitch, throttle, yaw (-1..1, after scaling)
        self.last_rc = 0.0
        self.landing = False
        self.takeoff_until = 0.0
        self.quit_after_land = False
        self.held_scans = set()
        self.frame_surface = None
        self.scaled = None
        self.shown_frame_id = -1
        self.font = pygame.font.SysFont("consolas", 18, bold=True)
        self.font_big = pygame.font.SysFont("consolas", 30, bold=True)
        self.font_small = pygame.font.SysFont("consolas", 15)
        MEDIA_DIR.mkdir(exist_ok=True)

    # ---- actions -------------------------------------------------------------

    def takeoff(self):
        if not self.tello.connected:
            return self.tello.log("Not connected")
        self.tello.log("Taking off")
        self.landing = False
        self.takeoff_until = time.monotonic() + TAKEOFF_GRACE
        self.tello.send("takeoff")

    def land(self):
        if self.landing:
            return
        self.landing = True
        self.tello.log("Landing")
        threading.Thread(target=self._land_loop, daemon=True).start()

    def _land_loop(self):
        # rc packets can cancel a landing and single UDP packets get lost, so stop rc
        # and resend "land" until the drone reports it's down
        deadline = time.monotonic() + 20
        down_since = None
        last_send = 0.0
        while self.landing and time.monotonic() < deadline:
            now = time.monotonic()
            if not self.tello.flying:
                down_since = down_since or now
                if now - down_since > 1.0:
                    break
            else:
                down_since = None
                if now - last_send > 3:
                    last_send = now
                    self.tello.send("land")
            time.sleep(0.1)
        else:
            if self.landing:
                self.tello.log("Landing timed out - still flying?")
        if self.landing:
            self.landing = False
            if not self.tello.flying:
                self.tello.log("Landed")

    def emergency(self):
        for _ in range(3):
            self.tello.send("emergency")
        self.tello.log("EMERGENCY - motors stopped")

    def flip(self, d):
        self.tello.log(f"Flip {d}")
        self.tello.send(f"flip {d}")

    def cycle_speed(self, idx=None):
        self.speed_idx = (self.speed_idx + 1) % len(SPEED_MODES) if idx is None else idx
        self.tello.log(f"Speed: {SPEED_MODES[self.speed_idx][0]}")

    def photo(self):
        if not self.frame_surface:
            return self.tello.log("No video frame to save")
        path = MEDIA_DIR / f"photo_{stamp()}.png"
        pygame.image.save(self.frame_surface, str(path))
        self.tello.log(f"Saved {path.name}")

    def toggle_record(self):
        if self.video.recording:
            self.video.stop_recording()
            self.tello.log("Recording stopped - saving...")
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
        held = self.pad.held
        if b in ("start", "select") and {"start", "select"} <= held:
            self.emergency()
        elif b in FLIP_DIRS and "l1" in held:
            self.flip(FLIP_DIRS[b])
        elif b == "triangle":
            self.takeoff()
        elif b == "cross":
            self.land()
        elif b == "circle":
            self.cycle_speed()
        elif b == "r1":
            self.photo()
        elif b == "square":
            self.toggle_record()
        elif b in ("ps", "start"):
            self.show_help = not self.show_help

    def on_key(self, ev):
        k, ctrl = ev.key, ev.mod & pygame.KMOD_CTRL
        if ctrl and ev.scancode in MOVE_SCANS:
            self.flip(MOVE_SCANS[ev.scancode])
        elif k == pygame.K_BACKSPACE:
            self.emergency()
        elif k == pygame.K_t:
            self.takeoff()
        elif k == pygame.K_l:
            self.land()
        elif k in (pygame.K_1, pygame.K_2, pygame.K_3):
            self.cycle_speed(k - pygame.K_1)
        elif k == pygame.K_p:
            self.photo()
        elif k == pygame.K_r:
            self.toggle_record()
        elif k == pygame.K_h:
            self.show_help = not self.show_help
        elif k == pygame.K_F11:
            self.toggle_fullscreen()
        elif k == pygame.K_ESCAPE:
            return self.request_quit()
        return True

    def request_quit(self):
        """Land before quitting; a second request quits right away."""
        if self.quit_after_land or not self.tello.flying:
            return False
        self.quit_after_land = True
        self.tello.log("Landing before quit (Esc again to quit now)")
        self.land()
        return True

    def read_sticks(self):
        lx, ly, rx, ry, l2, _ = self.pad.axes()
        roll, pitch, throttle, yaw = shape(lx), -shape(ly), -shape(ry), shape(rx)
        keys = pygame.key.get_pressed()
        mods = pygame.key.get_mods()
        if not mods & pygame.KMOD_CTRL:
            held = {MOVE_SCANS[s] for s in self.held_scans if s in MOVE_SCANS}
            roll += ("r" in held) - ("l" in held)
            pitch += ("f" in held) - ("b" in held)
        throttle += keys[pygame.K_UP] - keys[pygame.K_DOWN]
        yaw += keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
        precision = max(l2, 1.0 if mods & pygame.KMOD_SHIFT else 0.0)
        scale = 1 - (1 - PRECISION_SCALE) * precision
        clamp = lambda v: max(-1.0, min(1.0, v)) * scale
        self.sticks = (clamp(roll), clamp(pitch), clamp(throttle), clamp(yaw))

    def send_rc(self):
        now = time.monotonic()
        if now - self.last_rc < 1 / RC_HZ:
            return
        self.last_rc = now
        idle = not any(self.sticks)
        if self.landing and not idle:
            self.landing = False
            self.tello.log("Landing cancelled by stick input")
        if idle and (self.landing or now < self.takeoff_until):
            return  # don't let rc interrupt takeoff / landing
        if self.tello.connected:
            top = SPEED_MODES[self.speed_idx][1]
            self.tello.send("rc " + " ".join(str(int(round(v * top))) for v in self.sticks))

    # ---- drawing -------------------------------------------------------------

    def text(self, s, pos, color=(235, 235, 235), font=None, anchor="topleft"):
        font = font or self.font
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

        # top bar
        bar = pygame.Rect(0, 0, sw, 34)
        self.panel(bar)
        x = 10
        if t.connected:
            x = self.text("● LINK", (x, 7), (90, 220, 120)).right + 18
            bat = int(st.get("bat", 0))
            col = (90, 220, 120) if bat > 40 else (240, 200, 60) if bat > 20 else (240, 70, 60)
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
        name, top = SPEED_MODES[self.speed_idx]
        right = self.text(f"{name}", (right, 7), (120, 190, 255), anchor="topright").left - 18
        right = self.text(self.pad.name or "keyboard", (right, 7), (180, 180, 180), self.font_small, "topright").left - 18
        if self.video.recording:
            secs = int(now - self.video.rec_start)
            self.text(f"{'●' if blink else ' '} REC {secs // 60}:{secs % 60:02d}", (right, 7), (240, 70, 60), anchor="topright")

        if not t.connected:
            self.text("Connect this PC's Wi-Fi to TELLO-XXXXXX and power on the drone",
                      (sw // 2, sh // 2), (220, 220, 220), anchor="center")
            self.text(f"Press {self.help_keys()} for controls", (sw // 2, sh // 2 + 30), (160, 160, 160),
                      self.font_small, "center")
        else:
            if now - self.video.frame_time > 2:
                self.text("NO VIDEO", (sw // 2, sh // 2 - 80), (240, 200, 60), self.font_big, "center")
            self.draw_attitude(area.center, st)
            # flight data, left side
            y = 50
            h = st.get("h", 0) / 100
            spd = math.hypot(st.get("vgx", 0), st.get("vgy", 0)) / 10
            for label, value in (("ALT", f"{h:4.1f} m"), ("TOF", f"{st.get('tof', 0) / 100:4.2f} m"),
                                 ("SPD", f"{spd:4.1f} m/s"), ("VS", f"{-st.get('vgz', 0) / 10:+4.1f} m/s")):
                self.panel(pygame.Rect(8, y - 2, 160, 30), 110)
                self.text(label, (14, y + 3), (160, 160, 160), self.font_small)
                self.text(value, (160, y + 1), anchor="topright")
                y += 34
            hdg = int(st.get("yaw", 0)) % 360
            self.text(f"HDG {hdg:03d}°", (sw // 2, 42), anchor="midtop")
            if st.get("bat", 100) <= 20 and blink:
                self.text("LOW BATTERY - LAND", (sw // 2, 80), (240, 70, 60), self.font_big, "midtop")
            if self.video.fps:
                self.text(f"{self.video.fps:.0f} fps", (sw - 10, 42), (160, 160, 160), self.font_small, "topright")

        self.draw_stick((70, sh - 70), self.sticks[0], self.sticks[1])
        self.draw_stick((sw - 70, sh - 70), self.sticks[3], self.sticks[2])

        # messages
        y = sh - 30
        for ts, msg in reversed(list(t.log_lines)):
            age = now - ts
            if age > 5:
                continue
            self.text(msg, (sw // 2, y), (235, 235, 235) if age < 4 else (130, 130, 130), self.font_small, "midbottom")
            y -= 20

        if self.show_help:
            self.draw_help()
        else:
            self.text(f"Press {self.help_keys()} for help", (sw // 2, sh - 6), (150, 150, 150),
                      self.font_small, "midbottom")

    def help_keys(self):
        return "H or Start" if self.pad.name else "H"

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

    def draw_help(self):
        sw, sh = self.screen.get_size()
        box = pygame.Rect(0, 0, 620, 30 + 22 * len(HELP_LINES))
        box.center = (sw // 2, sh // 2)
        self.panel(box, 215)
        y = box.top + 15
        for key, desc in HELP_LINES:
            if key and not desc:
                self.text(key, (box.left + 20, y), (120, 190, 255))
            elif key:
                self.text(key, (box.left + 30, y), (240, 200, 60), self.font_small)
                self.text(desc, (box.left + 250, y), font=self.font_small)
            y += 22

    # ---- main loop -----------------------------------------------------------

    def run(self):
        clock = pygame.time.Clock()
        running = True
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
                else:
                    button = self.pad.handle(ev)
                    if button:
                        self.on_pad_button(button)
            if self.quit_after_land and not self.landing:
                running = False
            self.read_sticks()
            self.send_rc()
            area = self.draw_video()
            self.draw_hud(area)
            pygame.display.flip()
            clock.tick(60)
        self.shutdown()

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
    font = pygame.font.SysFont("consolas", 16)
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
    parser.add_argument("--joytest", action="store_true", help="show raw gamepad input")
    args = parser.parse_args()
    pygame.init()
    sdl_controller.init()
    if args.joytest:
        joytest()
        pygame.quit()
        return
    App().run()


if __name__ == "__main__":
    sys.exit(main())
