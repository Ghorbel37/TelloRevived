"""The app: ties the drone, video, gamepad, HUD and settings screen together and runs the loop."""

import datetime
import threading
import time
from pathlib import Path

import pygame

from tello_revived.battery import FlightTime
from tello_revived.drone import Tello
from tello_revived.flightlog import FlightLog
from tello_revived.flight import FlightActions
from tello_revived.gamepad import Gamepad, shape
from tello_revived.hud import MONO, HudDrawing
from tello_revived.labels import key_label
from tello_revived.menu import Menu
from tello_revived import VERSION, firewall, folder_picker, updates, wifi
from tello_revived.paths import ICON_PATH, MEDIA_DIR
from tello_revived.settings import SPEED_NAMES, Settings
from tello_revived.video import Video

RC_HZ = 20
WIFI_SCAN_EVERY = 5.0  # seconds between looks for the drone's network, while it isn't connected

FLIP_DIRS = {"up": "f", "down": "b", "left": "l", "right": "r"}
MOVE_FLIPS = {"forward": "f", "back": "b", "left": "l", "right": "r"}


class App(FlightActions, HudDrawing):
    """The running app. Flying actions live in flight.py and drawing in hud.py; both are mixed in here."""

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
        self.taking_off = False  # takeoff sent, no answer yet
        self.flight_log = FlightLog()
        self.flight_time = FlightTime()
        self.firewall_button = None  # where the HUD drew "Allow it now", for mouse clicks
        self.firewall_status = None  # what happened after pressing it
        self.drone_networks = []  # TELLO-... networks in range, while the drone isn't connected
        self.current_wifi = None  # the network this computer is on
        self.wifi_button = None
        self.wifi_status = None
        if wifi.available():
            threading.Thread(target=self._watch_wifi, daemon=True).start()
        self.new_release = None  # (tag, url) of a newer release, once found
        self.update_state = "Not checked"
        self.ask_about_updates = self.settings["app"]["check_updates"] is None  # first run: ask
        self.update_buttons = {}  # "yes"/"no" -> where the question's buttons are drawn
        if self.settings["app"]["check_updates"]:
            self.check_for_updates()
        self.last_input = "pad"  # which device the button guide shows
        self.frame_surface = None  # the video frame on screen (already scaled to the window)
        self.shown_frame_id = -1
        self.font = pygame.font.SysFont(MONO, 18, bold=True)
        self.font_big = pygame.font.SysFont(MONO, 30, bold=True)
        self.font_small = pygame.font.SysFont(MONO, 15)
        self.media_dir().mkdir(parents=True, exist_ok=True)

    # ---- camera and display ------------------------------------------------

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
        folder = self.media_dir()
        path = folder / f"photo_{stamp()}.png"
        n = 2
        while path.exists():  # several photos in the same second
            path = folder / f"photo_{stamp()}_{n}.png"
            n += 1
        size, pitch, rgb = self.video.snapshot()  # full size, not the window-sized picture
        pygame.image.save(pygame.image.frombuffer(rgb, size, "RGB", pitch), str(path))
        self.tello.log(f"Saved {path.name}")

    def toggle_record(self):
        if self.video.recording:
            self.video.stop_recording()
            self.tello.log("Recording stopped - saving...")
        elif not self.camera_live():
            self.tello.log(f"Not recording: {self.camera_off_reason()}")
        else:
            self.video.start_recording(self.media_dir() / f"video_{stamp()}.h264")
            self.tello.log("Recording")

    def media_dir(self):
        """Where photos and recordings go: the folder chosen in settings, or the default one."""
        chosen = self.settings["files"]["media_dir"]
        return Path(chosen) if chosen else MEDIA_DIR

    def choose_media_dir(self):
        """Ask for a new photos and videos folder with the system's folder dialog."""
        if not folder_picker.available():
            return self.tello.log("No folder dialog on this system: set media_dir in config.json")
        if self.fullscreen:
            self.toggle_fullscreen()  # the dialog would open behind a fullscreen window
        # in a thread, so the drone keeps getting stick commands while the dialog is open
        threading.Thread(target=self._pick_media_dir, daemon=True).start()

    def _pick_media_dir(self):
        chosen = folder_picker.pick_folder("Folder for Tello Revived photos and videos", self.media_dir())
        if chosen:
            self.set_media_dir(chosen)

    def set_media_dir(self, folder):
        """Use folder for photos and recordings ("" = the default), if it can be written to."""
        path = Path(folder) if folder else MEDIA_DIR
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".tello_revived_write_test"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as e:
            return self.tello.log(f"Can't save to {path}: {e.strerror or e}")
        self.settings["files"]["media_dir"] = str(path) if folder else ""
        self.settings.save()
        self.tello.log(f"Photos and videos now go to {path}")

    def check_for_updates(self):
        """Ask GitHub for the latest release, in the background (at start, or from About)."""
        if self.update_state == "Checking for updates...":
            return
        self.update_state = "Checking for updates..."
        threading.Thread(target=self._check_updates, daemon=True).start()

    def _check_updates(self):
        latest = updates.latest_release()
        if not latest:
            self.update_state = "Couldn't check for updates (offline?)"
        elif updates.is_newer(latest[0]):
            self.new_release = latest
            self.update_state = f"{latest[0]} is available"
            if not self.tello.flying:  # never a message while flying; About shows it anyway
                self.tello.log(f"Tello Revived {latest[0]} is available - see Settings > About")
        else:
            self.update_state = f"Up to date (v{VERSION})"

    def update_question_open(self):
        """The first-run question is on screen. Never while flying, so it can't lock the controls in the air."""
        return self.ask_about_updates and not self.tello.flying

    def answer_update_question(self, yes):
        """The first-run question: check for updates when the app opens?"""
        self.ask_about_updates = False
        self.settings["app"]["check_updates"] = yes
        self.settings.save()
        if yes:
            self.check_for_updates()

    def _watch_wifi(self):
        """While the drone isn't connected, look for its network (TELLO-...) every few seconds."""
        while self.tello.running:
            if self.tello.connected or self.tello.blocked:
                self.drone_networks = []
            else:
                self.current_wifi = wifi.current_network()
                self.drone_networks = [n for n in wifi.drone_networks() if n != self.current_wifi]
            time.sleep(WIFI_SCAN_EVERY)

    def connect_wifi(self):
        """Join the first drone network found (the system's tools do it; takes a few seconds)."""
        if not self.drone_networks or (self.wifi_status or "").startswith("Connecting"):
            return
        ssid = self.drone_networks[0]
        self.wifi_status = f"Connecting to {ssid}..."
        threading.Thread(target=self._connect_wifi, args=(ssid,), daemon=True).start()

    def _connect_wifi(self, ssid):
        problem = wifi.connect(ssid)
        if problem:
            self.wifi_status = f"Couldn't connect to {ssid}: {problem}"
        else:
            self.wifi_status = None
            self.current_wifi = ssid
            self.drone_networks = []
            self.tello.log(f"Connected to {ssid}")

    def allow_firewall(self):
        """Ask the system (with its admin prompt) to let the drone's telemetry and video in."""
        if not firewall.can_allow():
            return self.tello.log("Can't change the firewall from here - see the steps on screen")
        if self.firewall_status == "Waiting for your answer to the admin prompt...":
            return
        if self.fullscreen:
            self.toggle_fullscreen()  # the prompt would open behind a fullscreen window
        self.firewall_status = "Waiting for your answer to the admin prompt..."
        threading.Thread(target=self._allow_firewall, daemon=True).start()

    def _allow_firewall(self):
        try:
            ok = firewall.allow()
        except OSError:
            ok = False
        self.firewall_status = ("Allowed - waiting for the drone's telemetry..." if ok
                                else "Not changed (cancelled or failed) - you can try again")

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.windowed_size = self.screen.get_size()
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)

    # ---- input -------------------------------------------------------------

    def on_pad_button(self, b):
        self.last_input = "pad"
        pad = self.settings["pad"]
        emergency = {pad["emergency_1"], pad["emergency_2"]} - {None}
        if b in emergency and emergency <= self.pad.held:
            return self.emergency()
        if self.update_question_open():  # it must be answered: everything else waits
            if b in ("cross", "circle"):
                self.answer_update_question(b == "cross")
            return
        if self.menu.is_open:
            return self.menu.handle_pad(b)
        if self.tello.blocked and b == "square":  # nothing to record while blocked anyway
            return self.allow_firewall()
        if self.drone_networks and not self.tello.connected and b == "square":
            return self.connect_wifi()
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
        if self.update_question_open():  # it must be answered: everything else waits
            if sc in (pygame.KSCAN_Y, pygame.KSCAN_N):
                self.answer_update_question(sc == pygame.KSCAN_Y)
            return True
        if self.menu.is_open:
            self.menu.handle_key(ev)
            return True
        if self.tello.blocked and sc == pygame.KSCAN_F:
            self.allow_firewall()
            return True
        if self.drone_networks and not self.tello.connected and sc == pygame.KSCAN_C:
            self.connect_wifi()
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
        typing = self.menu.is_open or self.update_question_open()  # keys drive the menu / the question
        down = lambda action: not typing and keys[action] is not None and keys[action] in held
        if not down("flip"):
            roll += down("right") - down("left")
            pitch += down("forward") - down("back")
        throttle += down("up") - down("down")
        yaw += down("turn_right") - down("turn_left")
        pad_precision = self.settings["pad"]["precision"]
        if pad_precision == "l2":
            pad_slow = l2  # analog: the further it's pulled, the slower
        else:
            pad_slow = 1.0 if pad_precision in self.pad.held else 0.0
        precision = max(pad_slow, 1.0 if down("precision") else 0.0)
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

    # ---- main loop ---------------------------------------------------------

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
                    elif ev.type == pygame.MOUSEBUTTONDOWN:
                        clicked = [a for a, r in self.update_buttons.items() if r.collidepoint(ev.pos)]
                        if self.update_question_open():
                            if clicked:
                                self.answer_update_question(clicked[0] == "yes")
                        elif self.tello.blocked and self.firewall_button and self.firewall_button.collidepoint(ev.pos):
                            self.allow_firewall()
                        elif self.wifi_button and self.wifi_button.collidepoint(ev.pos):
                            self.connect_wifi()
                elif ev.type == pygame.WINDOWMINIMIZED:
                    minimized = True
                elif ev.type in (pygame.WINDOWRESTORED, pygame.WINDOWMAXIMIZED, pygame.WINDOWSHOWN):
                    minimized = False
                else:
                    button = self.pad.handle(ev)
                    if button:
                        self.on_pad_button(button)
            if not self.update(draw=not minimized):  # nothing to see when minimised: save power
                running = False
            clock.tick(RC_HZ if minimized else self.settings["power"]["app_fps"])
        self.shutdown()

    def update(self, draw=True):
        """One frame after input: battery check, sticks, rc, drawing. False once it's time to quit."""
        if self.quit_after_land and not self.landing:
            self.quit_after_land = False
            if not self.tello.flying:
                return False
            self.tello.log("Quit cancelled - the drone is still flying")
        self.check_battery()
        self.flight_time.update(self.tello.flying, self.tello.state.get("bat"), time.monotonic())
        self.flight_log.update(self)
        if self.video.recording and not self.tello.want_video():
            self.toggle_record()  # e.g. landed with video set to "only while flying"
        self.read_sticks()
        self.send_rc()
        if draw:
            self.draw_hud(self.draw_video())
            pygame.display.flip()
        return True

    def shutdown(self):
        self.flight_log.close()
        if self.tello.flying:  # forced quit mid-flight: last-ditch land
            for _ in range(3):
                self.tello.send("land")
                time.sleep(0.1)
        self.video.close()
        self.tello.close()
        pygame.quit()


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
