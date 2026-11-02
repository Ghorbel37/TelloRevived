"""How many minutes of flight are left, from how fast the battery has been dropping in this flight."""

from collections import deque

WINDOW = 120.0  # seconds of recent flight the rate is measured over
MIN_DROP = 2  # percent the battery must have dropped before there's an estimate
MIN_SPAN = 20.0  # seconds, likewise


class FlightTime:
    def __init__(self):
        self.samples = deque()  # (time, battery %) each time the percentage changed

    def update(self, flying, battery, now):
        if not flying or battery is None:
            self.samples.clear()  # a new flight starts a new measurement
            return
        if not self.samples or battery != self.samples[-1][1]:
            self.samples.append((now, battery))
        while len(self.samples) > 2 and now - self.samples[1][0] > WINDOW:
            self.samples.popleft()

    def minutes_left(self, reserve):
        """Minutes until the battery reaches reserve %, or None while there's too little to go on."""
        if len(self.samples) < 2:
            return None
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        if b0 - b1 < MIN_DROP or t1 - t0 < MIN_SPAN:
            return None
        per_second = (b0 - b1) / (t1 - t0)
        return max(0.0, (b1 - reserve) / per_second / 60)


def describe(minutes):
    """Short text for the top bar: '~4 min', '<1 min'."""
    return "<1 min" if minutes < 1 else f"~{minutes:.0f} min"
