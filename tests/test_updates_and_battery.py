"""The update check and the remaining flight time."""

import pygame
from conftest import connect, messages, screen_text, wait_until

from tello_revived import battery, updates


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
    assert app.new_release is None and app.update_state.startswith("Up to date")
    assert not any("is available" in m for m in messages(app))

    calls = []
    monkeypatch.setattr(updates, "latest_release", lambda: calls.append(1))  # offline: None
    app._check_updates()
    assert calls == [1]  # one try, no retrying in the background
    assert app.update_state == "Couldn't check for updates (offline?)"


def test_no_update_message_while_flying(app, monkeypatch):
    connect(app)
    app.fake.state.update(h=100, tof=100)
    assert wait_until(app, lambda: app.tello.flying)
    monkeypatch.setattr(updates, "latest_release", lambda: ("v9.9", "https://example.invalid/release"))
    app._check_updates()
    assert app.new_release  # still on the About page
    assert not any("is available" in m for m in messages(app))


def test_first_run_asks_before_checking(app, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "latest_release", lambda: calls.append(1))
    app.ask_about_updates = True
    screen_text(app)
    assert set(app.update_buttons) == {"yes", "no"}
    app.on_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_y, scancode=pygame.KSCAN_Y, mod=0, unicode="y"))
    assert not app.ask_about_updates
    assert app.settings["app"]["check_updates"] is True
    assert wait_until(app, lambda: calls == [1])


def test_first_run_no_means_no(app, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "latest_release", lambda: calls.append(1))
    app.ask_about_updates = True
    app.on_pad_button("circle")
    assert app.settings["app"]["check_updates"] is False
    assert not app.ask_about_updates and calls == []


def test_question_never_shows_or_answers_while_flying(app):
    connect(app)
    app.fake.state.update(h=100, tof=100)
    assert wait_until(app, lambda: app.tello.flying)
    app.ask_about_updates = True
    screen_text(app)
    assert app.update_buttons == {}  # not drawn
    app.on_pad_button("cross")  # Cross is land while flying, not "yes"
    assert app.ask_about_updates and app.settings["app"]["check_updates"] is None
    assert "land" in app.fake.received or wait_until(app, lambda: "land" in app.fake.received)


def test_about_page_has_a_check_now_button(app, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "latest_release", lambda: calls.append(1))
    button = next(r for r in app.menu.update_rows() if r.label == "Check for updates now")
    button.fn()
    assert wait_until(app, lambda: calls == [1])


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


def key(app, scancode):
    return app.on_key(pygame.event.Event(pygame.KEYDOWN, key=0, scancode=scancode, mod=0, unicode=""))


def test_first_run_question_blocks_everything_until_answered(app, monkeypatch):
    monkeypatch.setattr(updates, "latest_release", lambda: None)
    connect(app)
    app.ask_about_updates = True
    key(app, pygame.KSCAN_T)  # take off
    app.on_pad_button("triangle")
    key(app, pygame.KSCAN_H)  # help
    app.on_pad_button("start")
    assert key(app, pygame.KSCAN_ESCAPE) is True  # quit is ignored too (the window's close button still works)
    wait_until(app, lambda: False, timeout=0.5)
    assert "takeoff" not in app.fake.received
    assert not app.menu.is_open
    assert app.ask_about_updates

    key(app, pygame.KSCAN_BACKSPACE)  # the emergency stop always gets through
    assert wait_until(app, lambda: "emergency" in app.fake.received)

    key(app, pygame.KSCAN_N)
    assert not app.ask_about_updates
    key(app, pygame.KSCAN_H)
    assert app.menu.is_open  # everything works again
