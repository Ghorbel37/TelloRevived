"""A fake Tello on localhost, and an App connected to it, for the tests.

    uv run pytest
"""

import os
import socket
import threading
import time
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"  # no window
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame  # noqa: E402
import pytest  # noqa: E402

from tello_revived import app as app_module, drone, i18n, settings, updates, video, wifi  # noqa: E402

CLIP = Path(__file__).resolve().parent.parent / "assets" / "selftest.h264"  # 5 frames, 160x120


def free_udp_ports(n):
    socks = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(n)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


class FakeDrone:
    """Answers commands like a Tello, sends telemetry to the app and, after streamon, video.

    Tests change its behaviour through its attributes:
      state      telemetry fields it sends ten times a second (h, tof, bat, temph, ...); while h or tof
                 say it's in the air, its motor-time counter ("time") runs, as on a real drone
      motors     False keeps the motors off whatever h and tof say (the drone held up by hand)
      telemetry  False stops sending it (like a firewall would)
      answer     False stops answering commands (switched off)
      handlers   command -> function(fake) returning the reply, or None for no reply
      padding    appended to every reply (the real drone sometimes adds NUL bytes)
      binary     packets of the official app's protocol it was sent (throw & go)
    """

    def __init__(self, app_state_port, app_video_port):
        self.state = {"bat": 80, "h": 0, "tof": 10, "temph": 60, "templ": 57, "time": 0}
        self.telemetry = True
        self.motors = None  # None: running while it's in the air; False: never (held up by hand)
        self.answer = True
        self.handlers = {}
        self.padding = ""
        self.received = []  # every command except rc
        self.binary = []
        self.rc = []  # (time, command)
        self.streaming = False
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.1)
        self.addr = self.sock.getsockname()
        self.app_state = ("127.0.0.1", app_state_port)
        self.app_video = ("127.0.0.1", app_video_port)
        for target in (self._commands, self._telemetry, self._video):
            threading.Thread(target=target, daemon=True).start()

    def reply_later(self, addr, reply, delay):
        threading.Timer(delay, self._send_reply, (addr, reply)).start()

    def _send_reply(self, addr, reply):
        try:
            self.sock.sendto((reply + self.padding).encode(), addr)
        except OSError:
            pass  # the test already finished

    def _commands(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
            except OSError:
                continue
            if data[:1] == bytes([0xCC]):  # the official app's protocol, not text
                self.binary.append(data)
                continue
            cmd = data.decode()
            if cmd.startswith("rc "):
                self.rc.append((time.monotonic(), cmd))
                continue
            self.received.append(cmd)
            if cmd in ("streamon", "streamoff"):
                self.streaming = cmd == "streamon"
            if not self.answer:
                continue
            handler = self.handlers.get(cmd.split()[0])
            reply = handler(self, addr) if handler else ("90" if cmd == "wifi?" else "ok")
            if reply is not None:
                self.sock.sendto((reply + self.padding).encode(), addr)

    def _telemetry(self):
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        motor_seconds = 0.0
        while self.running:
            airborne = self.state.get("h", 0) > 0 or 40 < self.state.get("tof", 0) < 1000
            if self.motors if self.motors is not None else airborne:
                motor_seconds += 0.1
                self.state["time"] = int(motor_seconds)
            if self.telemetry:
                out.sendto(";".join(f"{k}:{v}" for k, v in self.state.items()).encode() + b";\r\n", self.app_state)
            time.sleep(0.1)
        out.close()

    def _video(self):
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        clip = CLIP.read_bytes()
        while self.running:
            if self.streaming:
                for i in range(0, len(clip), 1400):
                    out.sendto(clip[i:i + 1400], self.app_video)
            time.sleep(5 / 30)  # the clip is 5 frames: about 30 fps
        out.close()

    def close(self):
        self.running = False
        self.sock.close()


@pytest.fixture(scope="session", autouse=True)
def pygame_started():
    pygame.init()
    pygame._sdl2.controller.init()
    yield
    pygame.quit()


@pytest.fixture
def app(tmp_path, monkeypatch):
    """An App talking to a FakeDrone (app.fake), with its own config.json and media folder."""
    monkeypatch.setattr(settings.Settings.__init__, "__defaults__", (tmp_path / "config.json",))
    monkeypatch.setattr(app_module, "MEDIA_DIR", tmp_path / "media")
    # never look at or change this computer's real Wi-Fi; tests that need networks replace these
    monkeypatch.setattr(wifi, "available", lambda: True)  # even where nmcli etc. aren't installed (CI)
    monkeypatch.setattr(wifi, "current_network", lambda: None)
    monkeypatch.setattr(wifi, "drone_networks", lambda: [])
    monkeypatch.setattr(wifi, "connect", lambda ssid: "tests don't connect")
    monkeypatch.setattr(app_module, "WIFI_SCAN_EVERY", 0.2)
    monkeypatch.setattr(updates, "latest_release", lambda: None)  # no calls to GitHub from the tests
    monkeypatch.setattr(i18n, "system_language", lambda: "en")  # the tests read the English text
    for attempt in range(5):  # a free port can be taken by something else before the app binds it
        cmd_port, state_port, video_port = free_udp_ports(3)
        fake = FakeDrone(state_port, video_port)
        monkeypatch.setattr(drone, "CMD_PORT", cmd_port)
        monkeypatch.setattr(drone, "STATE_PORT", state_port)
        monkeypatch.setattr(drone, "TELLO_ADDR", fake.addr)
        monkeypatch.setattr(video, "VIDEO_URL", f"udp://127.0.0.1:{video_port}?overrun_nonfatal=1&fifo_size=5000000")
        try:
            the_app = app_module.App()
            break
        except OSError:
            fake.close()
            if attempt == 4:
                raise
    the_app.ask_about_updates = False  # the first-run question has its own tests
    the_app.fake = fake
    yield the_app
    the_app.video.close()
    the_app.tello.close()
    fake.close()


def run(app, seconds):
    """Run the app's frames for a while."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.update()
        time.sleep(1 / 60)


def wait_until(app, condition, timeout=8.0):
    """Run frames until condition() is true; False if it never was."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.update()
        if condition():
            return True
        time.sleep(1 / 60)
    return False


def screen_text(app):
    """Every string the HUD draws in one frame."""
    drawn = []
    real = app.text
    app.text = lambda s, *a, **k: (drawn.append(s), real(s, *a, **k))[1]
    try:
        app.draw_hud(app.draw_video())
    finally:
        app.text = real
    return " | ".join(drawn)


def messages(app):
    return [m for _, m in app.tello.log_lines]


def connect(app):
    assert wait_until(app, lambda: app.tello.connected and app.tello.session), "never connected to the fake drone"
