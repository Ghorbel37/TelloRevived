"""Take off, flips and landing, against the fake drone."""

import threading

from conftest import connect, messages, run, screen_text, wait_until

from tello_revived import flight


def climbs(height_after=3.0, reply_after=4.0):
    """A takeoff handler: the drone climbs at once, but its height reads 0 for a while (like a real one)."""
    def handler(fake, addr):
        fake.state["tof"] = 80
        threading.Timer(height_after, lambda: fake.state.update(h=80)).start()
        fake.reply_later(addr, "ok", reply_after)
    return handler


def lands(after=1.0):
    def handler(fake, addr):
        threading.Timer(after, lambda: fake.state.update(h=0, tof=10)).start()
        fake.reply_later(addr, "ok", after + 0.5)
    return handler


def fly(app):
    """Connect and put the fake drone in the air."""
    connect(app)
    app.fake.state.update(h=100, tof=100)
    assert wait_until(app, lambda: app.tello.flying)


def test_hot_drone_only_gets_a_warning(app):
    app.fake.state["temph"] = 90
    connect(app)
    text = screen_text(app)
    assert "to take off" in text and "Drone is hot (90" in text
    assert "Can't take off" not in text


def test_takeoff_shows_taking_off_then_flying_even_while_height_reads_0(app):
    app.fake.handlers["takeoff"] = climbs(height_after=3.0)
    connect(app)
    app.on_pad_button("triangle")
    assert "Taking off..." in screen_text(app)
    assert app.hint_items()[0][0] == "TAKING OFF"
    assert wait_until(app, lambda: app.tello.flying, timeout=3)  # from the distance sensor, before h moves
    assert app.tello.state["h"] == 0
    run(app, 2)
    assert "to take off" not in screen_text(app)
    assert app.hint_items()[0][0] == "FLYING"


def test_low_battery_blocks_the_takeoff_hint_and_explains_a_refusal(app):
    app.fake.state["bat"] = 7
    app.fake.handlers["takeoff"] = lambda fake, addr: "error"
    connect(app)
    assert "Can't take off" in screen_text(app)
    app.takeoff()
    assert wait_until(app, lambda: any("Take off refused: battery 7%" in m for m in messages(app)))


def test_flip_pauses_stick_commands_until_the_drone_answers(app):
    app.fake.handlers["flip"] = lambda fake, addr: fake.reply_later(addr, "ok", 1.5)
    fly(app)
    app.flip("f")
    app.flip("b")  # ignored: one at a time
    run(app, 1.0)
    flips = [c for c in app.fake.received if c.startswith("flip")]
    assert flips == ["flip f"]
    rc_before = len(app.fake.rc)
    run(app, 0.4)
    assert len(app.fake.rc) == rc_before  # no rc while flipping
    run(app, 1.5)
    assert len(app.fake.rc) > rc_before  # back after the answer


def test_refused_flip_and_low_battery_flip_are_explained(app):
    app.fake.handlers["flip"] = lambda fake, addr: "error"
    fly(app)
    app.flip("l")
    assert wait_until(app, lambda: any("refused the flip left: error" in m for m in messages(app)))
    app.fake.state["bat"] = 45
    run(app, 0.5)
    app.flip("r")
    assert "No flip: battery 45%" in messages(app)[-1]
    assert "flip r" not in app.fake.received


def test_landing_is_watched_until_touchdown(app):
    app.fake.handlers["land"] = lands(after=1.0)
    fly(app)
    app.land()
    assert wait_until(app, lambda: "Landed" in messages(app))
    assert not app.land_failed


def test_landing_that_never_happens_shows_the_warning(app, monkeypatch):
    monkeypatch.setattr(flight, "LAND_STALL", 1.0)
    app.settings["flight"]["land_attempts"] = 1
    fly(app)  # the fake answers "ok" to land but stays in the air
    app.land()
    assert wait_until(app, lambda: app.land_failed)
    assert "LANDING FAILED" in screen_text(app)


def test_each_flight_is_logged_to_a_csv(app, tmp_path):
    import csv

    app.fake.handlers["takeoff"] = climbs(height_after=1.0, reply_after=1.5)
    app.fake.handlers["land"] = lands(after=1.0)
    connect(app)
    app.takeoff()
    run(app, 3)
    app.land()
    assert wait_until(app, lambda: any(m.startswith("Saved flight_") for m in messages(app)), timeout=10)
    log = next((tmp_path / "media").glob("flight_*.csv"))
    rows = list(csv.DictReader(log.open(encoding="utf-8")))
    assert len(rows) > 20  # about ten a second
    assert rows[0]["height_cm"] == "0" and rows[0]["battery_pct"] == "80"
    assert "80" in {r["ground_distance_cm"] for r in rows}  # climbing while the height still read 0
    assert "80" in {r["height_cm"] for r in rows}
    events = " / ".join(r["event"] for r in rows)
    assert "Landing" in events and "Landed" in events
    assert float(rows[-1]["time_s"]) > float(rows[0]["time_s"])


def test_flight_log_can_be_switched_off(app, tmp_path):
    app.settings["files"]["flight_log"] = False
    connect(app)
    app.fake.state.update(h=100, tof=100)
    run(app, 1.5)
    assert not list((tmp_path / "media").glob("flight_*.csv"))
