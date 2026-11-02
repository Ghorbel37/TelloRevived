"""Sound alerts, and the Linux applications-menu entry."""

import pytest
from conftest import connect, wait_until

from tello_revived import desktop, sounds


def test_tones_are_generated_without_sound_files():
    beeps = sounds.tone([(880, 0.1, 0.05)])
    assert len(beeps) == int(sounds.RATE * 0.1) + int(sounds.RATE * 0.05)
    assert max(beeps) > 10000 and beeps[0] == 0  # loud enough, and fades in (no click)


def test_sound_system_runs_only_while_alerts_are_on(app):
    assert app.settings["hud"]["sound_alerts"] is False and not app.sounds.on
    app.settings["hud"]["sound_alerts"] = True
    app.on_setting_changed("hud", "sound_alerts")
    assert app.sounds.on and set(app.sounds.sounds) == {"warning", "alarm", "error"}
    app.settings["hud"]["sound_alerts"] = False
    app.on_setting_changed("hud", "sound_alerts")
    assert not app.sounds.on


@pytest.fixture
def heard(app, monkeypatch):
    played = []
    monkeypatch.setattr(app.sounds, "play", played.append)
    return played


def test_low_battery_and_auto_land_alerts_once_per_flight(app, heard):
    app.settings["power"].update(low_battery_warning=20, auto_land_battery=15)
    connect(app)
    app.fake.state.update(h=100, tof=100, bat=25)
    assert wait_until(app, lambda: app.tello.flying)
    app.fake.state["bat"] = 19
    assert wait_until(app, lambda: heard == ["warning"])
    wait_until(app, lambda: False, timeout=0.5)
    assert heard == ["warning"]  # not again while it stays low
    app.fake.state["bat"] = 14
    assert wait_until(app, lambda: heard == ["warning", "alarm"])  # auto-land


def test_refused_takeoff_and_firewall_alerts(app, heard):
    app.fake.handlers["takeoff"] = lambda fake, addr: "error"
    connect(app)
    app.takeoff()
    assert wait_until(app, lambda: heard == ["error"])
    app.tello.blocked = True
    assert wait_until(app, lambda: heard == ["error", "error"])  # blocked by the firewall
    wait_until(app, lambda: False, timeout=0.3)
    assert heard == ["error", "error"]  # once, not every frame


@pytest.fixture
def linux_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(desktop, "supported", lambda: True)
    return tmp_path / "share"


def test_menu_entry_is_one_button_that_adds_or_removes(app, linux_home):
    def button():
        return next(r for r in app.menu.menu_entry_rows())

    assert button().label == "Add to the applications menu"
    button().fn()
    entry = linux_home / "applications" / "tello-revived.desktop"
    icon = linux_home / "icons" / "hicolor" / "512x512" / "apps" / "tello-revived.png"
    assert entry.exists() and icon.stat().st_size > 1000
    text = entry.read_text()
    assert "Name=Tello Revived" in text and "Icon=tello-revived" in text and "StartupWMClass=tello-revived" in text
    assert "Exec=" in text and "-m tello_revived" in text  # running from source

    assert button().label == "Remove from the applications menu"
    button().fn()
    assert not entry.exists() and not icon.exists()
    assert button().label == "Add to the applications menu"


def test_no_menu_entry_button_outside_linux(app, monkeypatch):
    monkeypatch.setattr(desktop, "supported", lambda: False)
    assert app.menu.menu_entry_rows() == []
