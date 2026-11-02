"""A CSV of everything the drone reports during each flight, saved next to the photos and videos.

One row per telemetry packet (about ten a second): time since takeoff, what the drone measures,
the Wi-Fi signal, the stick inputs being sent, and any message the app showed (as an event).
"""

import csv
import datetime
import time

# (column, telemetry field) - the Tello's names are short, the columns say what they are
FIELDS = [
    ("height_cm", "h"), ("ground_distance_cm", "tof"), ("barometer_m", "baro"), ("battery_pct", "bat"),
    ("temp_low_c", "templ"), ("temp_high_c", "temph"), ("pitch_deg", "pitch"), ("roll_deg", "roll"),
    ("yaw_deg", "yaw"), ("speed_x_dm_s", "vgx"), ("speed_y_dm_s", "vgy"), ("speed_z_dm_s", "vgz"),
    ("accel_x", "agx"), ("accel_y", "agy"), ("accel_z", "agz"), ("drone_flight_time_s", "time"),
]
COLUMNS = (["time_s"] + [c for c, _ in FIELDS] + ["wifi", "stick_roll", "stick_pitch", "stick_throttle",
                                                  "stick_yaw", "event"])
LANDED_FOR = 3.0  # seconds on the ground before the log is closed


class FlightLog:
    def __init__(self):
        self.file = self.writer = self.path = None
        self.start = self.last_state = self.last_event = self.ground_since = 0.0

    def update(self, app):
        """Called every frame: opens a log at takeoff, adds a row per telemetry packet, closes it after landing."""
        tello = app.tello
        in_air = tello.flying or app.taking_off
        now = time.monotonic()
        if not self.file:
            if in_air and app.settings["files"]["flight_log"]:
                self._open(app, now)
            return
        if tello.state_time > self.last_state:
            self.last_state = tello.state_time
            self._row(app, now)
        if in_air:
            self.ground_since = 0.0
        else:
            self.ground_since = self.ground_since or now
            if now - self.ground_since > LANDED_FOR:
                self.close()
                tello.log(f"Saved {self.path.name}")

    def _open(self, app, now):
        folder = app.media_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self.path = folder / f"flight_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"
            self.file = open(self.path, "w", newline="", encoding="utf-8")
        except OSError as e:
            app.settings["files"]["flight_log"] = False  # don't retry every frame; the setting isn't saved
            return app.tello.log(f"Can't save the flight log: {e.strerror or e}")
        self.writer = csv.writer(self.file)
        self.writer.writerow(COLUMNS)
        self.start = self.last_event = now
        self.ground_since = 0.0

    def _row(self, app, now):
        st, t = app.tello.state, app.tello
        events = [m for ts, m in list(t.log_lines) if ts > self.last_event]
        if events:
            self.last_event = max(ts for ts, _ in list(t.log_lines))
        self.writer.writerow([f"{now - self.start:.2f}"] + [_number(st.get(field)) for _, field in FIELDS]
                             + [t.wifi if t.wifi is not None else ""] + [f"{v:.2f}" for v in app.sticks]
                             + [" / ".join(events)])
        self.file.flush()  # a crash or a pulled battery still leaves the log readable

    def close(self):
        if self.file:
            self.file.close()
            self.file = self.writer = None


def _number(value):
    if value is None:
        return ""
    return int(value) if float(value).is_integer() else value
