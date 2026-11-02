"""The update check and the remaining flight time."""

from conftest import connect, messages, screen_text, wait_until

from tello_revived import app as app_module, battery, updates


def test_versions_compare_as_numbers():
    assert updates.version_tuple("v0.8.2") == (0, 8, 2)
    assert updates.is_newer("v0.8.10", current="0.8.9")
    assert updates.is_newer("v0.9", current="0.8.2")
    assert not updates.is_newer("v0.8.2", current="0.8.2")
    assert not updates.is_newer("v0.8.1", current="0.8.2")
    assert not updates.is_newer("android-1", current="0.8.2")


def test_newer_release_is_offered_on_the_about_page(app, monkeypatch):
    monkeypatch.setattr(updates, "latest_release", lambda: ("v9.9", "https://example.invalid/release"))
    app._check_updates()
    assert app.new_release == ("v9.9", "https://example.invalid/release")
    assert "Tello Revived v9.9 is available - see Settings > About" in messages(app)
    rows = [r.label for r in app.menu.update_rows()]
    assert rows[0] == "Update available: v9.9 - open the download page"


def test_up_to_date_and_offline(app, monkeypatch):
    monkeypatch.setattr(updates, "latest_release", lambda: ("v0.0.1", "https://example.invalid"))
    app._check_updates()
    assert app.new_release is None and app.update_state == "Up to date"
    assert not any("is available" in m for m in messages(app))

    calls = []

    def offline():
        calls.append(1)
        if len(calls) == 2:
            app.tello.running = False  # end the retry loop after the second try
        return None

    monkeypatch.setattr(updates, "latest_release", offline)
    monkeypatch.setattr(app_module, "UPDATE_RETRY", 0.01)
    app._check_updates()
    assert len(calls) == 2  # it tried again
    assert app.update_state.startswith("Couldn't check for updates")


def test_flight_time_needs_a_real_drop_before_guessing():
    ft = battery.FlightTime()
    ft.update(True, 80, 0.0)
    ft.update(True, 79, 10.0)
    assert ft.minutes_left(10) is None  # only 1% and 10 s
    ft.update(True, 78, 30.0)  # 2% in 30 s: 4% a minute
    assert round(ft.minutes_left(10)) == 17  # (78 - 10) / 4
    assert round(ft.minutes_left(30)) == 12  # auto-land at 30%
    ft.update(False, 78, 31.0)  # landed: a new flight starts over
    assert ft.minutes_left(10) is None


def test_flight_time_uses_the_recent_rate():
    ft = battery.FlightTime()
    for minute, bat in enumerate([90, 89, 88, 87, 86, 80, 74, 68]):  # slow, then 6% a minute
        ft.update(True, bat, minute * 60.0)
    assert round(ft.minutes_left(10)) == 10  # (68 - 10) / 6, not the slow early rate
    assert battery.describe(0.4) == "<1 min" and battery.describe(4.2) == "~4 min"


def test_top_bar_shows_minutes_left_while_flying(app, monkeypatch):
    monkeypatch.setattr(battery, "MIN_SPAN", 1.0)
    connect(app)
    app.fake.state.update(h=100, tof=100, bat=80)
    assert wait_until(app, lambda: app.tello.flying)
    for level in (79, 78, 77):
        app.fake.state["bat"] = level
        assert wait_until(app, lambda: app.tello.state.get("bat") == level)
        wait_until(app, lambda: False, timeout=0.6)
    minutes = app.flight_minutes_left()
    assert minutes is not None
    assert f"BAT 77% {battery.describe(minutes)}" in screen_text(app)
