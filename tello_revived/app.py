"""The app: ties the drone, video, gamepad, HUD and settings screen together and runs the loop."""

import datetime
import threading
import time

import pygame

from tello_revived.drone import Tello
from tello_revived.flight import FlightActions
from tello_revived.gamepad import Gamepad, shape
from tello_revived.hud import MONO, HudDrawing
from tello_revived.labels import key_label
from tello_revived.menu import Menu
from tello_revived.paths import ICON_PATH, MEDIA_DIR
from tello_revived.settings import SPEED_NAMES, Settings
from tello_revived.video import Video

RC_HZ = 20

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
        self.last_input = "pad"  # which device the button guide shows
        self.frame_surface = None  # the video frame on screen (already scaled to the window)
        self.shown_frame_id = -1
        self.font = pygame.font.SysFont(MONO, 18, bold=True)
        self.font_big = pygame.font.SysFont(MONO, 30, bold=True)
        self.font_small = pygame.font.SysFont(MONO, 15)
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

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
        path = MEDIA_DIR / f"photo_{stamp()}.png"
        n = 2
        while path.exists():  # several photos in the same second
            path = MEDIA_DIR / f"photo_{stamp()}_{n}.png"
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
            self.video.start_recording(MEDIA_DIR / f"video_{stamp()}.h264")
            self.tello.log("Recording")

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
