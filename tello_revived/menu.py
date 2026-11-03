"""In-app help and settings screen, driven by keyboard, gamepad or mouse."""

import platform
import time
import webbrowser

import av
import pygame

from tello_revived import REPO_URL, VERSION, desktop
from tello_revived import flights as flights_module
from tello_revived.i18n import N_, languages, t
from tello_revived.labels import key_label, pad_label
from tello_revived.paths import MEDIA_DIR
from tello_revived.settings import DRONE_MODELS, KEY_ACTIONS, PAD_ACTIONS, help_rows, stream_settings_supported

STREAM_KEYS = ("resolution", "stream_fps", "bitrate")  # SDK 3.0 only
TABS = [N_("Help"), N_("Keyboard"), N_("Gamepad"), N_("HUD"), N_("Flight"), N_("Video & Power"),
        N_("Flights"), N_("About")]

ACCENT = (120, 190, 255)
YELLOW = (240, 200, 60)
RED = (240, 70, 60)
GREEN = (90, 220, 120)
DIM = (150, 150, 150)
ROW_H = 28
HINT_H = 26  # line above the button bar for the highlighted setting's hint

# One short line per setting, shown above the button bar while it's highlighted.
_MOVE = {"forward": N_("Flies forward"), "back": N_("Flies backward"), "left": N_("Slides left without turning"),
         "right": N_("Slides right without turning"), "up": N_("Climbs"), "down": N_("Descends"),
         "turn_left": N_("Turns left on the spot"), "turn_right": N_("Turns right on the spot")}
_ACTIONS = {"precision": N_("Hold for slow, fine moves"), "takeoff": N_("Takes off and hovers"),
            "land": N_("Lands where it is"), "emergency": N_("Cuts the motors at once - the drone falls"),
            "photo": N_("Saves the current frame to the media folder"), "record": N_("Starts or stops a video"),
            "speed": N_("Cycles slow / normal / fast"), "speed_slow": N_("Switches to slow speed"),
            "speed_normal": N_("Switches to normal speed"), "speed_fast": N_("Switches to fast speed")}
HINTS = {
    "keys": {**_MOVE, **_ACTIONS, "flip": N_("Hold, then a move key to flip that way"), "help": N_("Shows the controls"),
             "settings": N_("Opens this screen"), "fullscreen": N_("Fullscreen on / off"),
             "quit": N_("Quits - lands first if flying"),
             "camera": N_("Tello EDU / RoboMaster TT: switch to the downward camera and back")},
    "pad": {**_ACTIONS, "flip": N_("Hold, then the D-pad to flip that way"), "menu": N_("Opens help and settings"),
            "emergency_1": N_("Press both emergency buttons together"), "emergency_2": N_("Press both emergency buttons together"),
            "camera": N_("Tello EDU / RoboMaster TT: switch to the downward camera and back")},
    "hud": {"top_bar": N_("Battery, Wi-Fi, flight time, temperature"), "flight_data": N_("Altitude, height, speed, climb rate"),
            "heading": N_("Angle turned since power-on (no compass)"), "attitude": N_("Shows the drone's tilt"),
            "sticks": N_("Shows your stick positions"), "messages": N_("Short status messages"),
            "hint_bar": N_("The buttons you can use right now"), "video_fps": N_("Video frames per second, and the app's own delay (receive to screen)"),
            "sound_alerts": N_("Beeps for low battery, auto-land, failed landing, refusals, firewall"),
            "vibration_alerts": N_("The same alerts, felt through the gamepad"),
            "units": N_("For height and speed in the flight data panel")},
    "drone": {"model": N_("Hides settings your drone can't use")},
    "app": {"language": N_("The app's language; Auto follows your computer")},
    "flight": {"move_stick": N_("This stick moves; the other climbs and turns"),
               "speed_slow": N_("Top speed in slow mode"), "speed_normal": N_("Top speed in normal mode"),
               "speed_fast": N_("Top speed in fast mode"), "precision": N_("Speed while precision is held"),
               "deadzone": N_("Ignores small stick drift"), "expo": N_("Gentler near the centre, full at the edge"),
               "retry_landing": N_("Resends land until it touches down"), "land_attempts": N_("Failed landings before the warning"),
               "takeoff_pause": N_("Ignores the sticks right after takeoff"), "land_on_quit": N_("Quitting while flying lands first"),
               "rejoin_wifi": N_("Only if it drops mid-flight; switching networks on the ground is left alone")},
    "power": {"video": N_("Streaming heats the drone and uses battery"), "resolution": N_("Lower uses less Wi-Fi and battery"),
              "stream_fps": N_("Lower uses less battery"), "bitrate": N_("Lower is smoother on weak Wi-Fi"),
              "app_fps": N_("Lower saves PC battery"), "auto_land_battery": N_("Lands by itself at this level"),
              "low_battery_warning": N_("Warns at this battery level")},
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
        self.pending_delete = None  # a flight log waiting for the second Del / Square
        self.device = "keyboard"
        self.tab_rects = []
        self.row_rects = []

    # ---- content -------------------------------------------------------------

    def rows(self):
        name = TABS[self.tab]
        reset = lambda section, label: Row("button", label, fn=lambda: self.reset(section),
                                          hint=N_("Puts this page back to its defaults"))
        if name == "Help":
            return [Row("help", r) for r in help_rows(self.settings)]
        if name == "About":
            return self.about_rows()
        if name == "Flights":
            return self.flight_rows()
        if name == "Keyboard":
            return [Row("key", label, "keys", a) for a, label in KEY_ACTIONS] + [reset("keys", N_("Reset keyboard to defaults"))]
        if name == "Gamepad":
            return [Row("pad", label, "pad", a) for a, label in PAD_ACTIONS] + [reset("pad", N_("Reset gamepad to defaults"))]
        if name == "HUD":
            items = [("top_bar", N_("Top bar (battery, Wi-Fi, flight time)")), ("flight_data", N_("Altitude / speed panel")),
                     ("heading", N_("Heading")), ("attitude", N_("Horizon line")), ("sticks", N_("Stick boxes")),
                     ("messages", N_("Messages")), ("hint_bar", N_("Button guide (bottom bar)")),
                     ("sound_alerts", N_("Sound alerts")), ("vibration_alerts", N_("Vibration alerts (gamepad)")),
                     ("video_fps", N_("Video fps and app delay"))]
            units = Row("choice", N_("Units"), "hud", "units", [("metric", N_("Metric (m, m/s)")),
                        ("metric_kmh", N_("Metric (m, km/h)")), ("imperial", N_("Imperial (ft, mph)"))])
            language = Row("choice", N_("Language"), "app", "language",
                           [("auto", N_("Auto (computer's language)"))] + languages())
            return [language, units] + [Row("toggle", label, "hud", k) for k, label in items] \
                + [reset("hud", N_("Reset HUD to defaults"))]
        if name == "Flight":
            return [
                Row("choice", N_("Drone model"), "drone", "model", DRONE_MODELS),
                Row("choice", N_("Move with"), "flight", "move_stick",
                    [("left", N_("Left stick")), ("right", N_("Right stick"))]),
                Row("number", N_("Slow speed"), "flight", "speed_slow", lo=5, hi=100, step=5, fmt="{}%"),
                Row("number", N_("Normal speed"), "flight", "speed_normal", lo=5, hi=100, step=5, fmt="{}%"),
                Row("number", N_("Fast speed"), "flight", "speed_fast", lo=5, hi=100, step=5, fmt="{}%"),
                Row("number", N_("Precision speed"), "flight", "precision",
                    lo=0.1, hi=1.0, step=0.05, fmt="{:.0%}"),
                Row("number", N_("Stick deadzone"), "flight", "deadzone", lo=0.0, hi=0.3, step=0.01, fmt="{:.2f}"),
                Row("number", N_("Stick expo (softer centre)"), "flight", "expo", lo=0.0, hi=1.0, step=0.05,
                    fmt="{:.2f}"),
                Row("toggle", N_("Retry landing automatically"), "flight", "retry_landing"),
                Row("number", N_("Failed landings before warning"), "flight", "land_attempts", lo=1, hi=6),
                Row("number", N_("Pause sticks after takeoff"), "flight", "takeoff_pause", lo=0, hi=10,
                    fmt="{} s"),
                Row("toggle", N_("Land before quitting"), "flight", "land_on_quit"),
                Row("toggle", N_("Rejoin the drone's Wi-Fi if it drops"), "flight", "rejoin_wifi"),
                reset("flight", N_("Reset flight settings to defaults")),
            ]
        stream = [
            Row("choice", N_("Stream resolution"), "power", "resolution",
                [("default", N_("Drone default")), ("high", N_("High (720p)")), ("low", N_("Low (480p)"))]),
            Row("choice", N_("Stream frame rate"), "power", "stream_fps",
                [("default", N_("Drone default")), ("high", N_("High (30)")), ("middle", N_("Middle (15)")), ("low", N_("Low (5)"))]),
            Row("choice", N_("Stream bitrate"), "power", "bitrate",
                [("default", N_("Drone default")), ("auto", N_("Auto"))] + [(str(n), f"{n} Mbps") for n in range(1, 6)]),
        ] if stream_settings_supported(self.settings) else []
        return [
            Row("choice", N_("Video stream"), "power", "video",
                [("flying", N_("Only while flying")), ("on", N_("On")), ("off", N_("Off"))]),
            *stream,
            Row("choice", N_("App frame rate"), "power", "app_fps", [(20, N_("20 fps")), (30, N_("30 fps")), (60, N_("60 fps"))]),
            Row("choice", N_("Auto-land at battery"), "power", "auto_land_battery",
                [(0, N_("Off"))] + [(n, f"{n}%") for n in (10, 15, 20, 25, 30)]),
            Row("number", N_("Low battery warning"), "power", "low_battery_warning", lo=5, hi=50, step=5, fmt="{}%"),
            *self.media_rows(),
            reset("power", N_("Reset video & power to defaults")),
        ]

    def flight_rows(self):
        """Past flights from the flight logs, newest first, and the battery trend across them."""
        folder = self.app.media_dir()
        flights = self.app.flights.list(folder)
        if not flights:
            return [Row("info", N_("No flight logs yet.")),
                    Row("info", N_("Turn on Video & Power > Save flight logs, and each flight appears here.")),
                    Row("info", t("(looking in {folder})", folder=folder))]
        rows = [Row("text", t("{count} flights", count=len(flights)) if len(flights) > 1 else t("1 flight"))]
        trend = flights_module.battery_trend(flights)
        if trend:
            recent, earlier = trend
            line = t("Battery use: {recent}% a minute lately", recent=f"{recent:.1f}")
            if earlier:
                line = t("Battery use: {recent}% a minute lately, {earlier}% in earlier flights",
                         recent=f"{recent:.1f}", earlier=f"{earlier:.1f}")
            rows.append(Row("info", line))
            if earlier and recent > earlier * 1.15:
                rows.append(Row("info", N_("Recent flights drain the battery faster: it may be ageing")))
        dist, dist_unit = self.app.distance_units()
        for f in flights[:40]:
            minutes, seconds = divmod(int(f.duration), 60)
            label = t("{date}   {time}   max {height}   battery {start}% > {end}%", date=f"{f.started:%Y-%m-%d %H:%M}",
                      time=f"{minutes}:{seconds:02d}", height=f"{f.max_height / 100 * dist:.1f} {dist_unit}",
                      start=f.battery_start, end=f.battery_end)
            row = Row("button", label, fn=lambda f=f: self.show_graph(f),
                      hint=self.delete_hint(f) or N_("Shows height, battery and speed over this flight"))
            row.flight = f
            rows.append(row)
        return rows

    def show_graph(self, flight):
        self.graph = flight

    def delete_hint(self, flight):
        if self.pending_delete == flight.path:
            return t("Press {key} again to delete this flight log", key="Square" if self.device == "gamepad" else "Del")
        return None

    def selected_flight(self):
        """The flight Del / Square applies to: the one shown, or the one highlighted in the list."""
        if self.graph:
            return self.graph
        rows = self.rows()
        return getattr(rows[self.sel], "flight", None) if self.sel < len(rows) else None

    def delete_flight(self, flight):
        """First press asks, the second deletes the log (it can't be undone)."""
        if self.pending_delete != flight.path:
            self.pending_delete = flight.path
            return
        self.pending_delete = None
        try:
            flight.path.unlink()
        except OSError as e:
            return self.app.tello.log(t("Couldn't delete {file}: {error}", file=flight.path.name, error=e.strerror or e))
        self.app.flights.cache.pop(flight.path, None)
        self.graph = None
        self.app.tello.log(t("Deleted {file}", file=flight.path.name))
        self._fix_selection(-1)

    def menu_entry_rows(self):
        """Linux only: one button that adds the app to the applications menu, or removes it."""
        if not desktop.supported():
            return []
        if desktop.installed():
            return [Row("button", N_("Remove from the applications menu"), fn=self.app.toggle_menu_entry,
                        hint=N_("Deletes the menu entry and icon this app added"))]
        return [Row("button", N_("Add to the applications menu"), fn=self.app.toggle_menu_entry,
                    hint=N_("So it appears in your app menu, with its icon, pointing at this copy"))]

    def update_rows(self):
        app = self.app
        if app.new_release:
            tag, url = app.new_release
            first = Row("button", t("Update available: {version} - open the download page", version=tag),
                        fn=lambda: webbrowser.open(url), hint=N_("Opens the release page in your browser"))
        else:
            first = Row("info", app.update_state)
        return [first,
                Row("button", N_("Check for updates now"), fn=app.check_for_updates,
                    hint=N_("Asks GitHub for the latest version")),
                Row("toggle", N_("Check for updates when the app opens"), "app", "check_updates",
                    hint=N_("Asks GitHub once at start; never shows anything while flying"))]

    def media_rows(self):
        folder = str(self.app.media_dir())
        if len(folder) > 48:
            folder = "..." + folder[-45:]
        rows = [Row("button", t("Photos and videos: {folder}", folder=folder), fn=self.app.choose_media_dir,
                    hint=N_("Choose where photos and recordings are saved")),
                Row("toggle", N_("Save flight logs"), "files", "flight_log",
                    hint=N_("A CSV of the drone's telemetry for each flight, in that folder"))]
        if self.settings["files"]["media_dir"]:
            rows.append(Row("button", N_("Use the default folder"), fn=lambda: self.app.set_media_dir(""),
                            hint=t("Back to {folder}", folder=MEDIA_DIR)))
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
            Row("info", N_("Fly a DJI/Ryze Tello from your computer with a gamepad or keyboard.")),
            Row("info", ""),
            Row("button", REPO_URL.removeprefix("https://"), fn=lambda: webbrowser.open(REPO_URL),
                hint=N_("Opens in your browser")),
            Row("button", N_("Open the photos and videos folder"), fn=lambda: webbrowser.open(media.as_uri()),
                hint=N_("Opens in your file manager")),
            *self.update_rows(),
            *self.menu_entry_rows(),
            Row("info", ""),
            Row("info", t("Settings file:  {path}", path=self.settings.path)),
            Row("info", t("Photos/videos:  {folder}", folder=media)),
            Row("info", f"Python {platform.python_version()}, pygame-ce {pygame.version.ver}, "
                        f"PyAV {av.__version__}, {platform.system()} {platform.release()}"),
        ]

    def reset(self, section):
        self.settings.reset(section)
        self.app.on_setting_changed(section, None)
        self.app.tello.log(t("{page} reset to defaults", page=t(TABS[self.tab])))

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
        if TABS[self.tab] == "Flights" and ev.key == pygame.K_DELETE:
            if flight := self.selected_flight():
                self.delete_flight(flight)
            return
        self.pending_delete = None  # any other key cancels a delete
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
        if TABS[self.tab] == "Flights" and b == "square":
            if flight := self.selected_flight():
                self.delete_flight(flight)
            return
        self.pending_delete = None  # any other button cancels a delete
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
            return (t("ON") if on else t("OFF")), GREEN if on else DIM
        if row.kind == "choice":
            cur = s[row.section][row.key]
            label = t(next((name for v, name in row.options if v == cur), str(cur)))
            if row.key in STREAM_KEYS and self.app.tello.stream_settings_ok is False:
                return f"<  {label}  >  {t('not supported')}", DIM
            return f"<  {label}  >", YELLOW
        if row.kind == "number":
            v = s[row.section][row.key]
            text = t("off") if row.key == "takeoff_pause" and v == 0 else row.fmt.format(v)
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
            name = t(name)
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
            for x_off, head in ((20, N_("CONTROL")), (330, N_("KEYBOARD")), (560, N_("GAMEPAD"))):
                app.text(t(head), (box.left + x_off, y), ACCENT, app.font_small)
            y += ROW_H
            visible -= 1
        for i in range(self.scroll, min(len(rows), self.scroll + visible)):
            row = rows[i]
            rect = pygame.Rect(box.left + 8, y, box.width - 16, ROW_H - 2)
            value_rect = None
            if row.kind == "help":
                what, kb, pad = row.label
                app.text(t(what), (box.left + 20, y + 5), font=app.font_small)
                app.text(kb, (box.left + 330, y + 5), YELLOW, app.font_small)
                app.text(pad, (box.left + 560, y + 5), YELLOW, app.font_small)
            elif row.kind == "info":
                app.text(t(row.label), (box.left + 20, y + 5), DIM, app.font_small)
            elif row.kind == "text":
                app.text(t(row.label), (box.left + 20, y + 3), font=app.font)
            else:
                if i == self.sel:
                    pygame.draw.rect(screen, (45, 65, 105), rect, border_radius=5)
                color = ACCENT if row.kind == "button" else (235, 235, 235)
                app.text(t(row.label), (box.left + 20, y + 5), color, app.font_small)
                value, vcolor = self.value_text(row)
                if self.capture and i == self.sel:
                    blink = int(time.monotonic() * 3) % 2 == 0
                    value = (t("Press a key...") if self.capture[0] == "key" else t("Press a pad button...")) if blink else ""
                    vcolor = (255, 255, 255)
                if value:
                    value_rect = app.text(value, (box.right - 24, y + 5), vcolor, app.font_small, "topright")
            self.row_rects.append((rect, i, value_rect))
            y += ROW_H
        if self.scroll + visible < len(rows):
            app.text(f"v  {t('more below')}  v", (box.centerx, y + 5), DIM, app.font_small, "midtop")
        elif self.scroll > 0:
            app.text(f"^  {t('more above')}  ^", (box.centerx, y + 5), DIM, app.font_small, "midtop")

        row = rows[self.sel] if self.sel < len(rows) and rows[self.sel].selectable else None
        if row and row.hint and not self.capture:
            app.text(t(row.hint), (box.left + 20, box.bottom - 36 - HINT_H + 4), ACCENT, app.font_small)
        pygame.draw.line(screen, (70, 80, 100), (box.left, box.bottom - 36), (box.right, box.bottom - 36))
        app.text(self.footer(), (box.centerx, box.bottom - 27), DIM, app.font_small, "midtop")

    def draw_graph(self, area):
        """Height, battery and speed over one flight, as three stacked line charts."""
        app, f = self.app, self.graph
        app.screen.fill((16, 18, 24), area.inflate(12, 8))  # solid: nothing behind shows through the charts
        minutes, seconds = divmod(int(f.duration), 60)
        app.text(t("Flight of {date}   {time}   battery {start}% > {end}%", date=f"{f.started:%Y-%m-%d %H:%M}",
                   time=f"{minutes}:{seconds:02d}", start=f.battery_start, end=f.battery_end),
                 (area.left, area.top), font=app.font)
        dist, dist_unit = app.distance_units()
        speed, speed_unit = app.speed_units()
        charts = [(t("Height ({unit})", unit=dist_unit), [h / 100 * dist for h in f.heights], ACCENT),
                  (t("Battery (%)"), f.batteries, GREEN),
                  (t("Speed ({unit})", unit=speed_unit), [v / 10 * speed for v in f.speeds], YELLOW)]
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
            if self.pending_delete == self.graph.path:
                key = "Square" if self.device == "gamepad" else "Del"
                return t("Press {key} again to delete this flight log", key=key)
            return {"gamepad": t("Circle: back to the list   Square: delete   L1 / R1: page"),
                    "mouse": t("Click: back to the list")}.get(self.device,
                                                               t("Esc: back to the list   Del: delete   Tab: page"))
        if self.capture:
            return t("Esc: cancel") if self.capture[0] == "pad" else t("Press the new key   Esc: cancel")
        if self.device == "gamepad":
            return t("D-pad: move / change   Cross: edit   Square: clear   L1 / R1: page   Circle: close")
        if self.device == "mouse":
            return t("Click: change (left half / right-click goes back)   Wheel: scroll   Esc: close")
        return t("Up/Down: move   Left/Right: change   Enter: edit   Del: clear   Tab: page   Esc: close")
