"""Flying actions: take off, land (and watch the landing), flips, emergency stop, auto-land."""

import threading
import time
from tello_revived.i18n import N_, t

LOW_BAT_TAKEOFF = 10  # the Tello refuses to take off at or below about this battery level
HOT_TEMP = 85  # degrees C: shown in red, and a warning before takeoff (Tellos often fly hotter, so no block)
LAND_STALL = 4.0  # seconds without descending before a landing attempt counts as failed


class FlightActions:
    """Part of App: the commands that make the drone take off, land and flip."""

    def takeoff(self):
        if not self.tello.connected:
            return self.tello.log(t("Not connected"))
        self.tello.log(t("Taking off"))
        self.landing = self.land_failed = False
        self.land_fails = 0
        self.takeoff_until = time.monotonic() + self.settings["flight"]["takeoff_pause"]
        self.taking_off = True  # until the drone answers: its height can read 0 for a few seconds
        threading.Thread(target=self._do_takeoff, daemon=True).start()

    def _do_takeoff(self):
        # "ok" comes once it hovers; a refusal comes straight away and is just "error"
        try:
            reply = self.tello.query("takeoff", 12.0)
        finally:
            self.taking_off = False
        if reply == "ok" or self.tello.flying:
            return
        reason = self.takeoff_problem() or self.heat_warning()
        if not reason:
            reason = (t("no reply from the drone") if not reply else
                      t("the drone said '{reply}' with no reason - put it on a flat surface, or restart it", reply=reply))
        self.tello.log(t("Take off refused: {reason}", reason=reason))
        self.alert("error")

    def takeoff_problem(self):
        """Why the drone will refuse to take off, if we can tell: only a low battery is certain."""
        bat = self.tello.state.get("bat", 100)
        if bat <= LOW_BAT_TAKEOFF:
            return t("battery {battery}% is too low - charge it", battery=f"{bat:.0f}")
        return None

    def heat_warning(self):
        """A hot drone may refuse to take off, but often flies fine, so this only warns."""
        temp = self.tello.state.get("temph", 0)
        if temp >= HOT_TEMP:
            return t("drone is hot ({temp}°C) - it may refuse; let it cool if it does", temp=f"{temp:.0f}")
        return None

    def land(self):
        self.tello.log(t("Landing"))
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
                self.tello.log(t("Landed"))
                break
            if result == "lost":
                self.tello.log(t("Link lost while landing"))
                break
            if result == "cancelled":
                break
            self.land_fails += 1
            if self.land_fails >= fl["land_attempts"]:
                self.land_failed = True
                self.tello.log(t("Landing failed {count} times", count=self.land_fails))
                self.alert("alarm")
                break
            if fl["retry_landing"]:
                self.tello.log(t("Landing stalled - retrying ({attempt}/{attempts})", attempt=self.land_fails + 1,
                                  attempts=fl["land_attempts"]))
                self.tello.send("land")
                self.land_kick = time.monotonic()
            else:
                self.tello.log(t("Landing didn't work ({attempt}/{attempts}) - press land again", attempt=self.land_fails,
                                  attempts=fl["land_attempts"]))
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
        self.tello.log(t("EMERGENCY - motors stopped"))

    def flip(self, d):
        name = {"f": N_("forward"), "b": N_("back"), "l": N_("left"), "r": N_("right")}[d]
        bat = self.tello.state.get("bat", 0)
        if not self.tello.flying:
            return self.tello.log(t("Flips only work in the air"))
        if bat <= 50:
            return self.tello.log(t("No flip: battery {battery}% - the Tello only flips above 50%", battery=f"{bat:.0f}"))
        if time.monotonic() < self.flip_until:
            return  # one at a time
        self.tello.log(t("Flip {direction}", direction=t(name)))
        self.flip_until = time.monotonic() + 4.0  # no hover rc while it flips
        threading.Thread(target=self._do_flip, args=(d, name), daemon=True).start()

    def _do_flip(self, d, name):
        reply = self.tello.query(f"flip {d}", 4.0)
        self.flip_until = time.monotonic() + 0.3  # the drone answers once the flip is done
        if reply != "ok":
            self.tello.log(t("Drone refused the flip {direction}: {reply} (battery {battery}%)", direction=t(name),
                             reply=reply or t("no reply"), battery=f"{self.tello.state.get('bat', 0):.0f}"))
            self.alert("error")

    def flight_minutes_left(self):
        """Estimated minutes until auto-land (or the drone's own landing at about 10%), or None."""
        reserve = self.settings["power"]["auto_land_battery"] or LOW_BAT_TAKEOFF
        return self.flight_time.minutes_left(reserve)

    def check_battery(self):
        """Once per flight: a low-battery alert, and auto-land at the configured level."""
        limit = self.settings["power"]["auto_land_battery"]
        if not self.tello.flying:
            self.auto_landed = self.low_battery_warned = False
            return
        bat = self.tello.state.get("bat", 100)
        if not self.low_battery_warned and bat <= self.settings["power"]["low_battery_warning"]:
            self.low_battery_warned = True
            self.alert("warning")
        if limit and not self.auto_landed and bat <= limit:
            self.auto_landed = True
            self.tello.log(t("Battery {battery}% - auto landing", battery=f"{bat:.0f}"))
            self.alert("alarm")
            self.land()
