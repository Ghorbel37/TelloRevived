"""In-app help and settings screen, driven by keyboard, gamepad or mouse."""

import platform
import time
import webbrowser

import av
import pygame

from tello_revived import REPO_URL, VERSION, desktop
from tello_revived import flights as flights_module
from tello_revived.labels import key_label, pad_label
from tello_revived.paths import MEDIA_DIR
from tello_revived.settings import DRONE_MODELS, KEY_ACTIONS, PAD_ACTIONS, help_rows, stream_settings_supported

STREAM_KEYS = ("resolution", "stream_fps", "bitrate")  # SDK 3.0 only
TABS = ["Help", "Keyboard", "Gamepad", "HUD", "Flight", "Video & Power", "Flights", "About"]

ACCENT = (120, 190, 255)
YELLOW = (240, 200, 60)
RED = (240, 70, 60)
GREEN = (90, 220, 120)
DIM = (150, 150, 150)
ROW_H = 28
HINT_H = 26  # line above the button bar for the highlighted setting's hint

# One short line per setting, shown above the button bar while it's highlighted.
_MOVE = {"forward": "Flies forward", "back": "Flies backward", "left": "Slides left without turning",
         "right": "Slides right without turning", "up": "Climbs", "down": "Descends",
         "turn_left": "Turns left on the spot", "turn_right": "Turns right on the spot"}
_ACTIONS = {"precision": "Hold for slow, fine moves", "takeoff": "Takes off and hovers",
            "land": "Lands where it is", "emergency": "Cuts the motors at once - the drone falls",
            "photo": "Saves the current frame to the media folder", "record": "Starts or stops a video",
            "speed": "Cycles slow / normal / fast", "speed_slow": "Switches to slow speed",
            "speed_normal": "Switches to normal speed", "speed_fast": "Switches to fast speed"}
HINTS = {
    "keys": {**_MOVE, **_ACTIONS, "flip": "Hold, then a move key to flip that way", "help": "Shows the controls",
             "settings": "Opens this screen", "fullscreen": "Fullscreen on / off",
             "quit": "Quits - lands first if flying",
             "camera": "Tello EDU / RoboMaster TT: switch to the downward camera and back"},
    "pad": {**_ACTIONS, "flip": "Hold, then the D-pad to flip that way", "menu": "Opens help and settings",
            "emergency_1": "Press both emergency buttons together", "emergency_2": "Press both emergency buttons together",
            "camera": "Tello EDU / RoboMaster TT: switch to the downward camera and back"},
    "hud": {"top_bar": "Battery, Wi-Fi, flight time, temperature", "flight_data": "Altitude, height, speed, climb rate",
            "heading": "Angle turned since power-on (no compass)", "attitude": "Shows the drone's tilt",
            "sticks": "Shows your stick positions", "messages": "Short status messages",
            "hint_bar": "The buttons you can use right now", "video_fps": "Video frames per second, and the app's own delay (receive to screen)",
            "sound_alerts": "Beeps for low battery, auto-land, failed landing, refusals, firewall",
            "vibration_alerts": "The same alerts, felt through the gamepad",
            "units": "For height and speed in the flight data panel"},
    "drone": {"model": "Hides settings your drone can't use"},
    "flight": {"move_stick": "This stick moves; the other climbs and turns",
               "speed_slow": "Top speed in slow mode", "speed_normal": "Top speed in normal mode",
               "speed_fast": "Top speed in fast mode", "precision": "Speed while precision is held",
               "deadzone": "Ignores small stick drift", "expo": "Gentler near the centre, full at the edge",
               "retry_landing": "Resends land until it touches down", "land_attempts": "Failed landings before the warning",
               "takeoff_pause": "Ignores the sticks right after takeoff", "land_on_quit": "Quitting while flying lands first",
               "rejoin_wifi": "Within 2 minutes of losing the drone, if the computer moved to another network"},
    "power": {"video": "Streaming heats the drone and uses battery", "resolution": "Lower uses less Wi-Fi and battery",
              "stream_fps": "Lower uses less battery", "bitrate": "Lower is smoother on weak Wi-Fi",
              "app_fps": "Lower saves PC battery", "auto_land_battery": "Lands by itself at this level",
              "low_battery_warning": "Warns at this battery level"},
}


class Row:
    def __init__(self, kind, label, section=None, key=None, options=None,
                 lo=0, hi=0, step=1, fmt="{}", fn=None, hint=None):
        self.kind, self.label, self.section, self.key = kind, label, section, key
        self.options, self.lo, self.hi, self.step, self.fmt, self.fn = options, lo, hi, step, fmt, fn
        self.hint = hint or HINTS.get(section, {}).get(key)

    @property
    def selectable(self):
        return self.kind not in ("info", "help", "text")


class Menu:
    def __init__(self, app):
        self.app = app
        self.settings = app.settings
        self.is_open = False
        self.tab = 0
        self.sel = 0
        self.scroll = 0
        self.capture = None  # ("key" | "pad", action) while waiting for a new binding
        self.graph = None  # the Flight shown as a graph on the Flights page
        self.device = "keyboard"
        self.tab_rects = []
        self.row_rects = []

    # ---- content -------------------------------------------------------------

    def rows(self):
        name = TABS[self.tab]
        reset = lambda section, what: Row("button", f"Reset {what} to defaults", fn=lambda: self.reset(section),
                                          hint="Puts this page back to its defaults")
        if name == "Help":
            return [Row("help", r) for r in help_rows(self.settings)]
        if name == "About":
            return self.about_rows()
        if name == "Flights":
            return self.flight_rows()
        if name == "Keyboard":
            return [Row("key", label, "keys", a) for a, label in KEY_ACTIONS] + [reset("keys", "keyboard")]
        if name == "Gamepad":
            return [Row("pad", label, "pad", a) for a, label in PAD_ACTIONS] + [reset("pad", "gamepad")]
        if name == "HUD":
            items = [("top_bar", "Top bar (battery, Wi-Fi, flight time)"), ("flight_data", "Altitude / speed panel"),
                     ("heading", "Heading"), ("attitude", "Horizon line"), ("sticks", "Stick boxes"),
                     ("messages", "Messages"), ("hint_bar", "Button guide (bottom bar)"),
                     ("sound_alerts", "Sound alerts"), ("vibration_alerts", "Vibration alerts (gamepad)"),
                     ("video_fps", "Video fps and app delay")]
            units = Row("choice", "Units", "hud", "units", [("metric", "Metric (m, m/s)"),
                        ("metric_kmh", "Metric (m, km/h)"), ("imperial", "Imperial (ft, mph)")])
            return [units] + [Row("toggle", label, "hud", k) for k, label in items] + [reset("hud", "HUD")]
        if name == "Flight":
            return [
                Row("choice", "Drone model", "drone", "model", DRONE_MODELS),
                Row("choice", "Move with", "flight", "move_stick",
                    [("left", "Left stick"), ("right", "Right stick")]),
                Row("number", "Slow speed", "flight", "speed_slow", lo=5, hi=100, step=5, fmt="{}%"),
                Row("number", "Normal speed", "flight", "speed_normal", lo=5, hi=100, step=5, fmt="{}%"),
                Row("number", "Fast speed", "flight", "speed_fast", lo=5, hi=100, step=5, fmt="{}%"),
                Row("number", "Precision speed", "flight", "precision",
                    lo=0.1, hi=1.0, step=0.05, fmt="{:.0%}"),
                Row("number", "Stick deadzone", "flight", "deadzone", lo=0.0, hi=0.3, step=0.01, fmt="{:.2f}"),
                Row("number", "Stick expo (softer centre)", "flight", "expo", lo=0.0, hi=1.0, step=0.05,
                    fmt="{:.2f}"),
                Row("toggle", "Retry landing automatically", "flight", "retry_landing"),
                Row("number", "Failed landings before warning", "flight", "land_attempts", lo=1, hi=6),
                Row("number", "Pause sticks after takeoff", "flight", "takeoff_pause", lo=0, hi=10,
                    fmt="{} s"),
                Row("toggle", "Land before quitting", "flight", "land_on_quit"),
                Row("toggle", "Rejoin the drone's Wi-Fi if it drops", "flight", "rejoin_wifi"),
                reset("flight", "flight settings"),
            ]
        stream = [
            Row("choice", "Stream resolution", "power", "resolution",
                [("default", "Drone default"), ("high", "High (720p)"), ("low", "Low (480p)")]),
            Row("choice", "Stream frame rate", "power", "stream_fps",
                [("default", "Drone default"), ("high", "High (30)"), ("middle", "Middle (15)"), ("low", "Low (5)")]),
            Row("choice", "Stream bitrate", "power", "bitrate",
                [("default", "Drone default"), ("auto", "Auto")] + [(str(n), f"{n} Mbps") for n in range(1, 6)]),
        ] if stream_settings_supported(self.settings) else []
        return [
            Row("choice", "Video stream", "power", "video",
                [("flying", "Only while flying"), ("on", "On"), ("off", "Off")]),
            *stream,
            Row("choice", "App frame rate", "power", "app_fps", [(20, "20 fps"), (30, "30 fps"), (60, "60 fps")]),
            Row("choice", "Auto-land at battery", "power", "auto_land_battery",
                [(0, "Off")] + [(n, f"{n}%") for n in (10, 15, 20, 25, 30)]),
            Row("number", "Low battery warning", "power", "low_battery_warning", lo=5, hi=50, step=5, fmt="{}%"),
            *self.media_rows(),
            reset("power", "video & power"),
        ]

    def flight_rows(self):
        """Past flights from the flight logs, newest first, and the battery trend across them."""
        folder = self.app.media_dir()
        flights = self.app.flights.list(folder)
        if not flights:
            return [Row("info", "No flight logs yet."),
                    Row("info", "Turn on Video & Power > Save flight logs, and each flight appears here."),
                    Row("info", f"(looking in {folder})")]
        rows = [Row("text", f"{len(flights)} flight{'s' * (len(flights) > 1)}")]
        trend = flights_module.battery_trend(flights)
        if trend:
            recent, earlier = trend
            line = f"Battery use: {recent:.1f}% a minute lately"
            if earlier:
                line += f", {earlier:.1f}% in earlier flights"
            rows.append(Row("info", line))
            if earlier and recent > earlier * 1.15:
                rows.append(Row("info", "Recent flights drain the battery faster: it may be ageing"))
        dist, dist_unit = self.app.distance_units()
        for f in flights[:40]:
            minutes, seconds = divmod(int(f.duration), 60)
            label = (f"{f.started:%Y-%m-%d %H:%M}   {minutes}:{seconds:02d}   "
                     f"max {f.max_height / 100 * dist:.1f} {dist_unit}   battery {f.battery_start}% > {f.battery_end}%")
            rows.append(Row("button", label, fn=lambda f=f: self.show_graph(f),
                            hint="Shows height, battery and speed over this flight"))
        return rows

    def show_graph(self, flight):
        self.graph = flight

    def menu_entry_rows(self):
        """Linux only: one button that adds the app to the applications menu, or removes it."""
        if not desktop.supported():
            return []
        if desktop.installed():
            return [Row("button", "Remove from the applications menu", fn=self.app.toggle_menu_entry,
                        hint="Deletes the menu entry and icon this app added")]
        return [Row("button", "Add to the applications menu", fn=self.app.toggle_menu_entry,
                    hint="So it appears in your app menu, with its icon, pointing at this copy")]

    def update_rows(self):
        app = self.app
        if app.new_release:
            tag, url = app.new_release
            first = Row("button", f"Update available: {tag} - open the download page",
                        fn=lambda: webbrowser.open(url), hint="Opens the release page in your browser")
        else:
            first = Row("info", app.update_state)
        return [first,
                Row("button", "Check for updates now", fn=app.check_for_updates,
                    hint="Asks GitHub for the latest version"),
                Row("toggle", "Check for updates when the app opens", "app", "check_updates",
                    hint="Asks GitHub once at start; never shows anything while flying")]

    def media_rows(self):
        folder = str(self.app.media_dir())
        if len(folder) > 48:
            folder = "..." + folder[-45:]
        rows = [Row("button", f"Photos and videos: {folder}", fn=self.app.choose_media_dir,
                    hint="Choose where photos and recordings are saved"),
                Row("toggle", "Save flight logs", "files", "flight_log",
                    hint="A CSV of the drone's telemetry for each flight, in that folder")]
        if self.settings["files"]["media_dir"]:
            rows.append(Row("button", "Use the default folder", fn=lambda: self.app.set_media_dir(""),
                            hint=f"Back to {MEDIA_DIR}"))
        return rows

    # ---- open / close --------------------------------------------------------

    def open(self, tab="Help"):
        self.is_open = True
        self.tab = TABS.index(tab)
        self.sel = self.scroll = 0
        self.capture = None
        self._fix_selection(1)

    def close(self):
        self.is_open = False
        self.capture = None
        self.graph = None

    def toggle(self, tab):
        if self.is_open:
            self.close()
        else:
            self.open(tab)

    # ---- editing -------------------------------------------------------------

    def changed(self, section, key):
        self.settings.save()
        self.app.on_setting_changed(section, key)

    def about_rows(self):
        media = self.app.media_dir()
        return [
            Row("text", f"Tello Revived v{VERSION}"),
            Row("info", "Fly a DJI/Ryze Tello from your computer with a gamepad or keyboard."),
            Row("info", ""),
            Row("button", REPO_URL.removeprefix("https://"), fn=lambda: webbrowser.open(REPO_URL),
                hint="Opens in your browser"),
            Row("button", "Open the photos and videos folder", fn=lambda: webbrowser.open(media.as_uri()),
                hint="Opens in your file manager"),
            *self.update_rows(),
            *self.menu_entry_rows(),
            Row("info", ""),
            Row("info", f"Settings file:  {self.settings.path}"),
            Row("info", f"Photos/videos:  {media}"),
            Row("info", f"Python {platform.python_version()}, pygame-ce {pygame.version.ver}, "
                        f"PyAV {av.__version__}, {platform.system()} {platform.release()}"),
        ]

    def reset(self, section):
        self.settings.reset(section)
        self.app.on_setting_changed(section, None)
        self.app.tello.log(f"{TABS[self.tab]} reset to defaults")

    def activate(self, row, direction=1):
        s = self.settings
        if row.kind == "toggle":
            s[row.section][row.key] = not s[row.section][row.key]
        elif row.kind == "choice":
            values = [v for v, _ in row.options]
            cur = s[row.section][row.key]
            i = values.index(cur) if cur in values else 0
            s[row.section][row.key] = values[(i + direction) % len(values)]
        elif row.kind == "number":
            v = s[row.section][row.key] + direction * row.step
            v = min(row.hi, max(row.lo, v))
            s[row.section][row.key] = round(v, 4) if isinstance(row.step, float) else int(v)
        elif row.kind in ("key", "pad"):
            self.capture = (row.kind, row.key)
            return
        elif row.kind == "button":
            row.fn()
            return
        else:
            return
        self.changed(row.section, row.key)

    def clear_binding(self, row):
        if row.kind in ("key", "pad"):
            self.settings[row.section][row.key] = None
            self.changed(row.section, row.key)

    def bind(self, value):
        kind, action = self.capture
        section = "keys" if kind == "key" else "pad"
        self.settings[section][action] = value
        self.capture = None
        self.changed(section, action)

    # ---- input ---------------------------------------------------------------

    def handle_key(self, ev):
        self.device = "keyboard"
        if self.capture:
            if ev.key == pygame.K_ESCAPE:
                self.capture = None
            elif self.capture[0] == "key":
                self.bind(ev.scancode)
            return
        keys = self.settings["keys"]
        if self.graph:  # back to the list (Tab still changes page)
            if ev.key == pygame.K_TAB:
                self.switch_tab(-1 if ev.mod & pygame.KMOD_SHIFT else 1)
            elif ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_SPACE):
                self.graph = None
            return
        rows = self.rows()
        row = rows[self.sel] if self.sel < len(rows) else None
        k = ev.key
        if k == pygame.K_ESCAPE or ev.scancode in (keys["help"], keys["settings"]):
            self.close()
        elif k == pygame.K_TAB:
            self.switch_tab(-1 if ev.mod & pygame.KMOD_SHIFT else 1)
        elif k in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            self.switch_tab(-1 if k == pygame.K_PAGEUP else 1)
        elif k in (pygame.K_UP, pygame.K_DOWN):
            self.move(-1 if k == pygame.K_UP else 1)
        elif row and k in (pygame.K_LEFT, pygame.K_RIGHT):
            if row.kind in ("toggle", "choice", "number"):
                self.activate(row, -1 if k == pygame.K_LEFT else 1)
        elif row and k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.activate(row)
        elif row and k == pygame.K_DELETE:
            self.clear_binding(row)

    def handle_pad(self, b):
        self.device = "gamepad"
        if self.capture:
            if self.capture[0] == "pad":
                self.bind(b)
            return
        if self.graph:
            if b in ("l1", "r1"):
                self.switch_tab(-1 if b == "l1" else 1)
            elif b in ("circle", "cross"):
                self.graph = None
            return
        rows = self.rows()
        row = rows[self.sel] if self.sel < len(rows) else None
        if b in ("circle",) or b == self.settings["pad"]["menu"]:
            self.close()
        elif b in ("l1", "r1"):
            self.switch_tab(-1 if b == "l1" else 1)
        elif b in ("up", "down"):
            self.move(-1 if b == "up" else 1)
        elif row and b in ("left", "right") and row.kind in ("toggle", "choice", "number"):
            self.activate(row, -1 if b == "left" else 1)
        elif row and b == "cross":
            self.activate(row)
        elif row and b == "square":
            self.clear_binding(row)

    def handle_mouse(self, ev):
        self.device = "mouse"
        if ev.type == pygame.MOUSEWHEEL:
            self.move(-ev.y)
            return
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button not in (1, 3):
            return
        self.capture = None
        if self.graph and not any(r.collidepoint(ev.pos) for r in self.tab_rects):
            self.graph = None  # a click goes back to the list
            return
        for i, rect in enumerate(self.tab_rects):
            if rect.collidepoint(ev.pos):
                self.switch_tab(i - self.tab)
                return
        rows = self.rows()
        for rect, i, value_rect in self.row_rects:
            if rect.collidepoint(ev.pos) and rows[i].selectable:
                self.sel = i
                back = ev.button == 3 or (value_rect and ev.pos[0] < value_rect.centerx
                                          and rows[i].kind in ("choice", "number"))
                self.activate(rows[i], -1 if back else 1)
                return

    def switch_tab(self, delta):
        self.graph = None
        self.tab = (self.tab + delta) % len(TABS)
        self.sel = self.scroll = 0
        self._fix_selection(1)

    def move(self, delta):
        rows = self.rows()
        if not any(r.selectable for r in rows):
            self.scroll = max(0, self.scroll + delta)
            return
        self.sel = (self.sel + delta) % len(rows)
        self._fix_selection(delta)

    def _fix_selection(self, delta):
        rows = self.rows()
        if not any(r.selectable for r in rows):
            return
        while not rows[self.sel].selectable:
            self.sel = (self.sel + (1 if delta >= 0 else -1)) % len(rows)

    # ---- drawing -------------------------------------------------------------

    def value_text(self, row):
        s = self.settings
        if row.kind == "key":
            sc = s["keys"][row.key]
            dup = sc is not None and list(s["keys"].values()).count(sc) > 1
            return key_label(sc), RED if dup else YELLOW
        if row.kind == "pad":
            b = s["pad"][row.key]
            singles = [v for a, v in s["pad"].items() if not a.startswith("emergency")]
            dup = b is not None and not row.key.startswith("emergency") and singles.count(b) > 1
            return pad_label(b), RED if dup else YELLOW
        if row.kind == "toggle":
            on = s[row.section][row.key]
            return ("ON" if on else "OFF"), GREEN if on else DIM
        if row.kind == "choice":
            cur = s[row.section][row.key]
            label = next((t for v, t in row.options if v == cur), str(cur))
            if row.key in STREAM_KEYS and self.app.tello.stream_settings_ok is False:
                return f"<  {label}  >  not supported", DIM
            return f"<  {label}  >", YELLOW
        if row.kind == "number":
            v = s[row.section][row.key]
            text = "off" if row.key == "takeoff_pause" and v == 0 else row.fmt.format(v)
            return f"<  {text}  >", YELLOW
        return "", YELLOW

    def draw(self):
        app, screen = self.app, self.app.screen
        sw, sh = screen.get_size()
        box = pygame.Rect(0, 0, min(880, sw - 24), sh - 24)
        box.center = (sw // 2, sh // 2)
        app.panel(box, 228)
        pygame.draw.rect(screen, (70, 80, 100), box, 1)

        # tabs
        self.tab_rects = []
        x = box.left + 16
        for i, name in enumerate(TABS):
            img = app.font_small.render(name, True, (255, 255, 255))
            rect = pygame.Rect(x, box.top + 12, img.get_width() + 20, 28)
            if i == self.tab:
                pygame.draw.rect(screen, (50, 75, 120), rect, border_radius=6)
            app.text(name, rect.center, (255, 255, 255) if i == self.tab else DIM, app.font_small, "center")
            self.tab_rects.append(rect)
            x = rect.right + 6
        version = app.font_small.render(f"Tello Revived v{VERSION}", True, DIM)
        if x + version.get_width() + 16 < box.right:  # skip on narrow windows
            app.text(f"Tello Revived v{VERSION}", (box.right - 16, box.top + 26), DIM, app.font_small, "midright")
        pygame.draw.line(screen, (70, 80, 100), (box.left, box.top + 50), (box.right, box.top + 50))

        if self.graph:
            self.draw_graph(pygame.Rect(box.left + 20, box.top + 62, box.width - 40, box.height - 62 - 48))
            pygame.draw.line(screen, (70, 80, 100), (box.left, box.bottom - 36), (box.right, box.bottom - 36))
            app.text(self.footer(), (box.centerx, box.bottom - 27), DIM, app.font_small, "midtop")
            return

        top, bottom = box.top + 62, box.bottom - 44 - HINT_H
        rows = self.rows()
        visible = max(1, (bottom - top) // ROW_H)
        if len(rows) + (TABS[self.tab] == "Help") > visible:
            visible -= 1  # leave room for the "more" line
        if any(r.selectable for r in rows):
            self.scroll = min(max(self.scroll, self.sel - visible + 1), self.sel)
        self.scroll = max(0, min(self.scroll, max(0, len(rows) - visible + (1 if TABS[self.tab] == "Help" else 0))))
        self.row_rects = []
        y = top
        if TABS[self.tab] == "Help":
            for x_off, head in ((20, "CONTROL"), (330, "KEYBOARD"), (560, "GAMEPAD")):
                app.text(head, (box.left + x_off, y), ACCENT, app.font_small)
            y += ROW_H
            visible -= 1
        for i in range(self.scroll, min(len(rows), self.scroll + visible)):
            row = rows[i]
            rect = pygame.Rect(box.left + 8, y, box.width - 16, ROW_H - 2)
            value_rect = None
            if row.kind == "help":
                what, kb, pad = row.label
                app.text(what, (box.left + 20, y + 5), font=app.font_small)
                app.text(kb, (box.left + 330, y + 5), YELLOW, app.font_small)
                app.text(pad, (box.left + 560, y + 5), YELLOW, app.font_small)
            elif row.kind == "info":
                app.text(row.label, (box.left + 20, y + 5), DIM, app.font_small)
            elif row.kind == "text":
                app.text(row.label, (box.left + 20, y + 3), font=app.font)
            else:
                if i == self.sel:
                    pygame.draw.rect(screen, (45, 65, 105), rect, border_radius=5)
                color = ACCENT if row.kind == "button" else (235, 235, 235)
                app.text(row.label, (box.left + 20, y + 5), color, app.font_small)
                value, vcolor = self.value_text(row)
                if self.capture and i == self.sel:
                    blink = int(time.monotonic() * 3) % 2 == 0
                    value = ("Press a key..." if self.capture[0] == "key" else "Press a pad button...") if blink else ""
                    vcolor = (255, 255, 255)
                if value:
                    value_rect = app.text(value, (box.right - 24, y + 5), vcolor, app.font_small, "topright")
            self.row_rects.append((rect, i, value_rect))
            y += ROW_H
        if self.scroll + visible < len(rows):
            app.text("v  more below  v", (box.centerx, y + 5), DIM, app.font_small, "midtop")
        elif self.scroll > 0:
            app.text("^  more above  ^", (box.centerx, y + 5), DIM, app.font_small, "midtop")

        row = rows[self.sel] if self.sel < len(rows) and rows[self.sel].selectable else None
        if row and row.hint and not self.capture:
            app.text(row.hint, (box.left + 20, box.bottom - 36 - HINT_H + 4), ACCENT, app.font_small)
        pygame.draw.line(screen, (70, 80, 100), (box.left, box.bottom - 36), (box.right, box.bottom - 36))
        app.text(self.footer(), (box.centerx, box.bottom - 27), DIM, app.font_small, "midtop")

    def draw_graph(self, area):
        """Height, battery and speed over one flight, as three stacked line charts."""
        app, f = self.app, self.graph
        app.screen.fill((16, 18, 24), area.inflate(12, 8))  # solid: nothing behind shows through the charts
        minutes, seconds = divmod(int(f.duration), 60)
        app.text(f"Flight of {f.started:%Y-%m-%d %H:%M}   {minutes}:{seconds:02d}   "
                 f"battery {f.battery_start}% > {f.battery_end}%", (area.left, area.top), font=app.font)
        dist, dist_unit = app.distance_units()
        speed, speed_unit = app.speed_units()
        charts = [(f"Height ({dist_unit})", [h / 100 * dist for h in f.heights], ACCENT),
                  ("Battery (%)", f.batteries, GREEN),
                  (f"Speed ({speed_unit})", [v / 10 * speed for v in f.speeds], YELLOW)]
        top, gap = area.top + 34, 14
        height = (area.bottom - top - gap * (len(charts) - 1)) // len(charts)
        for i, (title, values, colour) in enumerate(charts):
            chart = pygame.Rect(area.left + 60, top + i * (height + gap), area.width - 60, height)
            self.draw_chart(chart, title, f.times, values, colour, last=i == len(charts) - 1)

    def draw_chart(self, rect, title, times, values, colour, last):
        app, screen = self.app, self.app.screen
        pygame.draw.rect(screen, (40, 46, 60), rect, 1)
        app.text(title, (rect.left + 6, rect.top + 4), DIM, app.font_small)
        if len(values) < 2 or times[-1] <= times[0]:
            return
        low, high = min(values), max(values)
        if high - low < 1e-6:
            low, high = low - 1, high + 1
        span = times[-1] - times[0]
        inner = rect.inflate(-8, -24).move(0, 8)
        points = [(inner.left + (t - times[0]) / span * inner.width,
                   inner.bottom - (v - low) / (high - low) * inner.height) for t, v in zip(times, values)]
        pygame.draw.lines(screen, colour, False, points, 2)
        app.text(f"{high:.1f}", (rect.left - 6, inner.top), DIM, app.font_small, "topright")
        app.text(f"{low:.1f}", (rect.left - 6, inner.bottom), DIM, app.font_small, "bottomright")
        if last:  # time axis under the bottom chart
            app.text("0:00", (rect.left, rect.bottom + 2), DIM, app.font_small, "topleft")
            m, s = divmod(int(span), 60)
            app.text(f"{m}:{s:02d}", (rect.right, rect.bottom + 2), DIM, app.font_small, "topright")

    def footer(self):
        if self.graph:
            return {"gamepad": "Circle: back to the list   L1 / R1: page",
                    "mouse": "Click: back to the list"}.get(self.device, "Esc: back to the list   Tab: page")
        if self.capture:
            return "Esc: cancel" if self.capture[0] == "pad" else "Press the new key   Esc: cancel"
        if self.device == "gamepad":
            return "D-pad: move / change   Cross: edit   Square: clear   L1 / R1: page   Circle: close"
        if self.device == "mouse":
            return "Click: change (left half / right-click goes back)   Wheel: scroll   Esc: close"
        return "Up/Down: move   Left/Right: change   Enter: edit   Del: clear   Tab: page   Esc: close"
