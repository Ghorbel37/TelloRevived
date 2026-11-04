"""Small pieces that don't need a drone."""

import json
from pathlib import Path

import av
import pygame

from tello_revived import firewall, labels
from tello_revived.gamepad import Gamepad, shape
from tello_revived.settings import DEFAULTS, Settings
from tello_revived.video import remux_to_mp4

CLIP = Path(__file__).resolve().parent.parent / "assets" / "selftest.h264"


def test_recording_is_wrapped_in_an_mp4_with_its_header(tmp_path):
    mp4 = tmp_path / "clip.mp4"
    remux_to_mp4(CLIP, mp4)
    with av.open(str(mp4)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.extradata
        assert sum(1 for _ in container.decode(stream)) == 5


def test_settings_keep_defaults_for_bad_or_unknown_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "flight": {"speed_fast": "very", "land_attempts": 5, "nonsense": 1},
        "keys": {"takeoff": None},
        "unknown_section": {"x": 1},
    }))
    s = Settings(path)
    assert s["flight"]["speed_fast"] == DEFAULTS["flight"]["speed_fast"]  # wrong type: ignored
    assert s["flight"]["land_attempts"] == 5
    assert s["keys"]["takeoff"] is None  # bindings may be cleared
    assert "nonsense" not in s["flight"]


def test_settings_survive_a_save_and_load(tmp_path):
    path = tmp_path / "config.json"
    s = Settings(path)
    s["files"]["media_dir"] = "D:/Drone"
    s["pad"]["precision"] = "r2"
    s.save()
    again = Settings(path)
    assert again["files"]["media_dir"] == "D:/Drone"
    assert again["pad"]["precision"] == "r2"


def test_triggers_press_once_and_release_with_hysteresis():
    pad = Gamepad()
    presses = [pad._trigger("r2", v) for v in (0.2, 0.5, 0.7, 0.9, 1.0, 0.8, 0.5)]
    assert [p for p in presses if p] == ["r2"]
    assert "r2" in pad.held
    pad._trigger("r2", 0.1)
    assert "r2" not in pad.held


def test_stick_deadzone_and_expo():
    assert shape(0.05, 0.08, 0.35) == 0.0
    assert shape(1.0, 0.08, 0.35) == 1.0
    assert 0 < shape(0.5, 0.08, 0.35) < 0.5  # expo: gentler near the centre
    assert shape(-1.0, 0.08, 0.35) == -1.0


def test_key_names_fall_back_to_the_us_layout(monkeypatch):
    monkeypatch.setattr(labels, "_sdl", False)
    assert labels.key_label(pygame.KSCAN_W) == "W"
    assert labels.key_label(pygame.KSCAN_UP) == "Up"
    assert labels.key_label(None) == "-"


def test_windows_firewall_script_only_opens_the_drone_ports():
    script = firewall.windows_script(r"C:\Users\O'Brien\Tello Revived.exe")
    assert "'C:\\Users\\O''Brien\\Tello Revived.exe'" in script  # quote escaped for PowerShell
    assert "-Protocol UDP -LocalPort 8890,11111 -Action Allow" in script
    assert "-Direction Inbound" in script


def test_button_names_follow_the_gamepad_or_the_setting():
    try:
        labels.set_pad_style("auto", "Xbox Wireless Controller")
        assert (labels.pad_label("cross"), labels.pad_label("l1"), labels.pad_label("start")) == ("A", "LB", "Menu")
        labels.set_pad_style("auto", "PLAYSTATION(R)3 Controller")
        assert (labels.pad_label("cross"), labels.pad_label("l1")) == ("Cross", "L1")
        labels.set_pad_style("auto", "8BitDo Pro 2")  # unknown pads mostly use the Xbox layout
        assert labels.pad_label("triangle") == "Y"
        labels.set_pad_style("playstation", "Xbox Wireless Controller")  # the setting wins
        assert labels.pad_label("square") == "Square"
        assert labels.pad_label("up") == "D-pad up" and labels.pad_label(None) == "-"
    finally:
        labels.set_pad_style("playstation", None)


def test_video_skips_frames_only_when_it_cant_keep_up():
    from tello_revived.video import CatchUp

    fast = CatchUp()
    for _ in range(20):
        fast.took(0.02)  # 20 ms a frame: keeps up with 30 fps
    assert not fast.behind(1.0, 1.0)  # a packet that was already waiting (a Wi-Fi burst)...
    assert not fast.behind(1.02, 1.02)  # ...or two: they're done in time anyway
    assert [fast.behind(t, t) for t in (1.04, 1.06)] == [False, True]  # four waiting in a row: a backlog
    assert not fast.behind(2.0, 1.9)  # it arrived after the last was done: on time again

    slow = CatchUp()
    for _ in range(20):
        slow.took(0.04)  # 40 ms a frame: can't keep up
    assert slow.behind(1.0, 1.0)
    assert not slow.behind(2.0, 1.9)
