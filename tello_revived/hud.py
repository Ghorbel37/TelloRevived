"""Everything drawn on screen during flight: video, flight data, button guide, warnings."""

import math
import sys
import time
from pathlib import Path

import pygame

from tello_revived import battery, firewall, wifi
from tello_revived.flight import HOT_TEMP
from tello_revived.labels import key_label, pad_label
from tello_revived.settings import SPEED_NAMES

MONO = "consolas,dejavusansmono,menlo,couriernew"  # first one installed wins
BAR_H = 30  # height of the button guide at the bottom
STALE_VIDEO = 1.0  # seconds without frames before the last picture is dropped


class HudDrawing:
    """Part of App: drawing. Reads the app's state directly; the settings screen is in menu.py."""

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
            frame, fid, native = self.video.frame, self.video.frame_id, self.video.native_size
        sw, sh = self.screen.get_size()
        if native:  # the video thread scales the next frames to fit the window
            k = min(sw / native[0], sh / native[1])
            self.video.display_size = (max(2, int(native[0] * k)), max(2, int(native[1] * k)))
        if frame and fid != self.shown_frame_id:
            size, pitch, data = frame
            self.frame_surface = pygame.image.frombuffer(data, size, "RGB", pitch)
            self.shown_frame_id = fid
        self.screen.fill((12, 14, 18))
        if self.frame_surface and (not self.tello.want_video()
                                   or time.monotonic() - self.video.frame_time > STALE_VIDEO):
            # stream stopped or link dropped: forget the old picture, so it doesn't flash up at the
            # next takeoff (a new frame replaces it as soon as one arrives)
            self.frame_surface = None
        if not self.frame_surface:
            return pygame.Rect(0, 0, sw, sh)
        picture = self.frame_surface
        if self.video.display_size and picture.get_size() != self.video.display_size:
            # the window was just resized: stretch this frame until a correctly sized one arrives
            picture = pygame.transform.scale(picture, self.video.display_size)
        rect = picture.get_rect(center=(sw // 2, sh // 2))
        self.screen.blit(picture, rect)
        return rect

    def draw_hud(self, area):
        t, st, now = self.tello, self.tello.state, time.monotonic()
        sw, sh = self.screen.get_size()
        blink = int(now * 2) % 2 == 0

        hud = self.settings["hud"]
        if hud["top_bar"]:
            self.draw_top_bar(blink, now)

        if t.blocked and not t.connected:
            self.draw_firewall_help()
        elif not t.connected:
            self.draw_connect_help()
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
        elif t.flying or self.taking_off:
            items = []
            if self.landing or self.land_failed:
                items.append((emergency, "EMERGENCY stop", red))
            items += [(b("land"), "Land", None),
                      (speed, f"Speed: {SPEED_NAMES[self.speed_idx]}", None),
                      *self.camera_items(b),
                      (b("flip"), "Hold: flips", None)] + help_items
            mode = (("LANDING", amber) if self.landing else ("TAKING OFF", amber) if not t.flying
                    else ("FLYING", (90, 220, 120)))
        elif t.connected:
            items = [(b("takeoff"), "Take off", None), *self.camera_items(b)] + help_items
            mode = ("READY", (120, 190, 255))
        elif t.blocked:
            allow = ("Square" if on_pad else "F") if firewall.can_allow() else None
            items = [(allow, "Allow through firewall", None)] + help_items + [(k("quit"), "Quit", None)]
            mode = ("BLOCKED", red)
        else:
            items = help_items + [(k("quit"), "Quit", None)]
            if self.drone_networks:
                items.insert(0, ("Square" if on_pad else "C", f"Connect to {self.drone_networks[0]}", None))
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
        if self.taking_off:
            self.text("Taking off...", (sw // 2, sh // 2 + 110), (120, 255, 160), self.font_big, "center")
            return
        if problem := self.takeoff_problem():
            rect = self.text("Can't take off", (sw // 2, sh // 2 + 110), (240, 70, 60), self.font_big, "center")
            self.text(problem[0].upper() + problem[1:], (sw // 2, rect.bottom + 6), (235, 235, 235),
                      self.font_small, "midtop")
            return
        rect = self.text(f"Press {btn} to take off", (sw // 2, sh // 2 + 110), (120, 255, 160),
                         self.font_big, "center")
        if warning := self.heat_warning():
            self.text(warning[0].upper() + warning[1:], (sw // 2, rect.bottom + 6), (240, 200, 60),
                      self.font_small, "midtop")
        else:
            self.text("Check there is space around and above the drone", (sw // 2, rect.bottom + 6),
                      (170, 170, 170), self.font_small, "midtop")

    def draw_connect_help(self):
        """Not connected: what to do, with a button when a drone network is in range."""
        sw, sh = self.screen.get_size()
        self.wifi_button = None
        if self.current_wifi and wifi.DRONE_NETWORK.match(self.current_wifi):
            title = f"On {self.current_wifi} - waiting for the drone to answer..."
        else:
            title = "Connect this computer's Wi-Fi to TELLO-XXXXXX and power on the drone"
        self.text(title, (sw // 2, sh // 2), (220, 220, 220), anchor="center")
        y = sh // 2 + 30
        if self.drone_networks:
            keys = "C or Square" if self.pad.name else "C"
            label = self.font.render(f"Connect to {self.drone_networks[0]} ({keys})", True, (15, 18, 24))
            rect = label.get_rect(midtop=(sw // 2, y)).inflate(28, 12)
            pygame.draw.rect(self.screen, (120, 190, 255), rect, border_radius=6)
            self.screen.blit(label, label.get_rect(center=rect.center))
            self.wifi_button = rect
            y = rect.bottom + 10
        if self.wifi_status:
            self.text(self.wifi_status, (sw // 2, y), (240, 200, 60), self.font_small, "midtop")
            y += 24
        self.text(f"Press {self.help_keys()} for controls", (sw // 2, y), (160, 160, 160), self.font_small, "midtop")

    def draw_firewall_help(self):
        """The drone answers commands but its telemetry and video don't get through."""
        sw, sh = self.screen.get_size()
        if sys.platform == "win32":
            if getattr(sys, "frozen", False):
                app = Path(sys.executable).name
            else:  # a venv's python.exe hands over to the installed Python, which is what the firewall sees
                app = getattr(sys, "_base_executable", sys.executable)
                if len(app) > 70:
                    app = "..." + app[-67:]
            how = ["Open Windows Security > Firewall & network protection >",
                   "Allow an app through firewall, and tick Private and Public for:", app]
        elif sys.platform == "darwin":
            how = ["Open System Settings > Network > Firewall > Options,", "and allow incoming connections for Tello Revived."]
        else:
            how = ["Allow incoming UDP on ports 8890 and 11111, for example:", "sudo ufw allow 8890,11111/udp"]
        lines = ["The drone answers, but your firewall blocks its telemetry and video.", "", *how, "",
                 "This message goes away by itself once it's allowed."]
        button = firewall.can_allow()
        box = pygame.Rect(0, 0, min(sw - 20, 680), 70 + 24 * len(lines) + (80 if button else 0))
        box.center = (sw // 2, sh // 2)
        self.panel(box, 210)
        pygame.draw.rect(self.screen, (240, 70, 60), box, 3)
        self.text("BLOCKED BY FIREWALL", (box.centerx, box.top + 12), (240, 70, 60), self.font_big, "midtop")
        for i, line in enumerate(lines):
            self.text(line, (box.centerx, box.top + 56 + 24 * i), font=self.font_small, anchor="midtop")
        self.firewall_button = None
        if button:
            keys = "F or Square" if self.pad.name else "F"
            label = self.font.render(f"Allow it now ({keys})", True, (15, 18, 24))
            rect = label.get_rect(midtop=(box.centerx, box.bottom - 76)).inflate(28, 12)
            pygame.draw.rect(self.screen, (120, 190, 255), rect, border_radius=6)
            self.screen.blit(label, label.get_rect(center=rect.center))
            self.firewall_button = rect
            note = self.firewall_status or "Asks for administrator permission, then allows only the drone's ports"
            self.text(note, (box.centerx, rect.bottom + 8), (170, 170, 170), self.font_small, "midtop")

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
            label = f"BAT {bat}%"
            if (minutes := self.flight_minutes_left()) is not None:
                label += f" {battery.describe(minutes)}"
            x = self.text(label, (x, 7), col).right + 18
            if t.wifi is not None:
                col = (90, 220, 120) if t.wifi > 60 else (240, 200, 60) if t.wifi > 30 else (240, 70, 60)
                x = self.text(f"WIFI {t.wifi}", (x, 7), col).right + 18
            tm = int(st.get("time", 0))
            x = self.text(f"FLT {tm // 60}:{tm % 60:02d}", (x, 7)).right + 18
            temp = (st.get("templ", 0) + st.get("temph", 0)) / 2
            self.text(f"{temp:.0f}°C", (x, 7), (240, 70, 60) if temp > HOT_TEMP else (235, 235, 235))
        elif t.blocked:
            self.text("● BLOCKED BY FIREWALL" if blink else "○ BLOCKED BY FIREWALL", (x, 7), (240, 70, 60))
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
