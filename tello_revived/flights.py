"""Past flights, read from the flight logs (flightlog.py): a summary of each, and battery history."""

import csv
import datetime
from dataclasses import dataclass, field
from pathlib import Path

RECENT = 5  # flights compared with the ones before them, for the battery trend


@dataclass
class Flight:
    path: Path
    started: datetime.datetime
    duration: float = 0.0  # seconds
    max_height: float = 0.0  # cm
    battery_start: int = 0
    battery_end: int = 0
    times: list = field(default_factory=list)  # seconds since takeoff, one per row
    heights: list = field(default_factory=list)  # cm
    batteries: list = field(default_factory=list)  # %
    speeds: list = field(default_factory=list)  # dm/s, horizontal

    @property
    def battery_used(self):
        return self.battery_start - self.battery_end

    @property
    def drain_per_minute(self):
        """Battery % used per minute of flight, or None for flights too short to tell."""
        if self.duration < 30 or self.battery_used < 1:
            return None
        return self.battery_used / (self.duration / 60)


def _number(text, default=0.0):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def read_flight(path):
    """A Flight from one log, or None if it isn't a readable flight log."""
    try:
        started = datetime.datetime.strptime(path.stem, "flight_%Y%m%d_%H%M%S")
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except (ValueError, OSError, csv.Error):
        return None
    flight = Flight(path, started)
    for row in rows:
        flight.times.append(_number(row.get("time_s")))
        flight.heights.append(_number(row.get("height_cm")))
        flight.batteries.append(_number(row.get("battery_pct")))
        flight.speeds.append((_number(row.get("speed_x_dm_s")) ** 2 + _number(row.get("speed_y_dm_s")) ** 2) ** 0.5)
    if not rows:
        return None
    flight.duration = flight.times[-1]
    flight.max_height = max(flight.heights)
    flight.battery_start, flight.battery_end = int(flight.batteries[0]), int(flight.batteries[-1])
    return flight


class Flights:
    """The logs in a folder, read once and kept until a file changes."""

    def __init__(self):
        self.cache = {}  # path -> (modified time, Flight)

    def list(self, folder):
        """Flights in the folder, newest first."""
        found = []
        for path in Path(folder).glob("flight_*.csv"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            cached = self.cache.get(path)
            if not cached or cached[0] != mtime:
                self.cache[path] = cached = (mtime, read_flight(path))
            if cached[1]:
                found.append(cached[1])
        return sorted(found, key=lambda f: f.started, reverse=True)


def battery_trend(flights):
    """(recent %/min, earlier %/min or None) from flights long enough to measure, newest first."""
    rates = [f.drain_per_minute for f in flights if f.drain_per_minute is not None]
    if not rates:
        return None
    recent = rates[:RECENT]
    earlier = rates[RECENT:]
    return sum(recent) / len(recent), (sum(earlier) / len(earlier) if earlier else None)
