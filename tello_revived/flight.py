"""Flying actions: take off, land (and watch the landing), flips, emergency stop, auto-land."""

import threading
import time

LOW_BAT_TAKEOFF = 10  # the Tello refuses to take off at or below about this battery level
HOT_TEMP = 85  # degrees C; the HUD shows the temperature in red above this
LAND_STALL = 4.0  # seconds without descending before a landing attempt counts as failed


class FlightActions:
    """Part of App: the commands that make the drone take off, land and flip."""

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
