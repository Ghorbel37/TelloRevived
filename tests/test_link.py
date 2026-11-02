"""Connecting to the drone, telemetry and the firewall check."""

from conftest import connect, messages, screen_text, wait_until


def test_connects_and_reads_telemetry(app):
    connect(app)
    assert app.fake.received[0] == "command"
    assert wait_until(app, lambda: app.tello.wifi == 90)
    assert app.tello.state["bat"] == 80


def test_replies_padded_with_nul_bytes_still_work(app):
    app.fake.padding = chr(0) * 3
    connect(app)
    assert wait_until(app, lambda: app.tello.wifi == 90)
    app.tello.log("padded" + chr(0) + "message")
    screen_text(app)  # pygame refuses NUL characters: this used to crash


def test_blocked_telemetry_is_reported_once_then_clears(app):
    app.fake.telemetry = False  # like a firewall: replies get through, telemetry doesn't
    assert wait_until(app, lambda: app.tello.blocked, timeout=10)
    assert "BLOCKED BY FIREWALL" in screen_text(app)
    assert app.hint_items()[0][0] == "BLOCKED"
    wait_until(app, lambda: False, timeout=4)  # no reconnect loop meanwhile
    assert messages(app).count("Tello connected") == 1
    assert sum("telemetry is blocked" in m for m in messages(app)) == 1

    app.fake.telemetry = True
    assert wait_until(app, lambda: app.tello.connected and not app.tello.blocked)
    assert "BLOCKED" not in screen_text(app)


def test_lost_drone_is_noticed(app):
    connect(app)
    app.fake.telemetry = app.fake.answer = False  # switched off
    assert wait_until(app, lambda: not app.tello.session, timeout=10)
    assert "Link lost - reconnecting" in messages(app)
    assert not app.tello.blocked


def test_flight_data_in_each_unit(app):
    app.fake.state.update(h=150, tof=182, vgx=30, vgy=40, vgz=-10)  # 1.5 m up, 5 m/s, climbing 1 m/s
    connect(app)
    assert wait_until(app, lambda: app.tello.state.get("vgx") == 30)
    expected = {
        "metric": ["1.5 m", "1.82 m", "5.0 m/s", "+1.0 m/s"],
        "metric_kmh": ["1.5 m", "18.0 km/h", "+1.0 m/s"],
        "imperial": ["4.9 ft", "5.97 ft", "11.2 mph", "+3.3 ft/s"],
    }
    for units, values in expected.items():
        app.settings["hud"]["units"] = units
        text = screen_text(app)
        for value in values:
            assert value in text, (units, value)
