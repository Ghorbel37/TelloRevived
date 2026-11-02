"""Front / down camera (Tello EDU and RoboMaster TT)."""

import pygame
from conftest import connect, messages, wait_until


def press_v(app):
    app.on_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v, scancode=pygame.KSCAN_V, mod=0, unicode="v"))


def test_regular_tello_explains_it_has_no_down_camera(app):
    connect(app)
    press_v(app)
    assert "Only the Tello EDU and RoboMaster TT have a downward camera" in messages(app)[-1]
    assert not any(c.startswith("downvision") for c in app.fake.received)


def test_edu_switches_to_the_down_camera_and_back(app):
    app.settings["drone"]["model"] = "edu"
    connect(app)
    app.fake.state.update(h=100, tof=100)
    assert wait_until(app, lambda: app.tello.flying)
    assert ("V", "Down camera", None) in app.hint_items()[1]
    press_v(app)
    assert wait_until(app, lambda: app.camera_down)
    assert "downvision 1" in app.fake.received and messages(app)[-1] == "Camera: down"
    assert ("V", "Front camera", None) in app.hint_items()[1]
    press_v(app)
    assert wait_until(app, lambda: not app.camera_down)
    assert "downvision 0" in app.fake.received


def test_refusal_is_explained(app):
    app.settings["drone"]["model"] = "tt"
    app.fake.handlers["downvision"] = lambda fake, addr: "error"
    connect(app)
    app.switch_camera()
    assert wait_until(app, lambda: "didn't switch cameras (error)" in messages(app)[-1])
    assert not app.camera_down
