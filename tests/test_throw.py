"""Throw & go."""

from conftest import connect, messages, wait_until

from tello_revived.drone import THROW_AND_GO


def test_throw_and_go_sends_the_app_packet_and_notices_the_flight(app):
    connect(app)
    app.throw_and_go()
    assert wait_until(app, lambda: THROW_AND_GO in app.fake.binary)
    assert wait_until(app, lambda: any(m.startswith("Throw the drone within 5 s") for m in messages(app)))
    app.fake.state.update(h=100, tof=100)  # thrown: it flies
    assert wait_until(app, lambda: messages(app)[-1] == "Flying")


def test_robomaster_tt_uses_throwfly(app):
    app.settings["drone"]["model"] = "tt"
    connect(app)
    app.throw_and_go()
    assert wait_until(app, lambda: "throwfly" in app.fake.received)
    assert not app.fake.binary
