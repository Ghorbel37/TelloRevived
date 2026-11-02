"""Finding and joining the drone's Wi-Fi network."""

from conftest import messages, screen_text, wait_until

from tello_revived import wifi

WINDOWS_INTERFACES_FR = """
    Nom                   : Wi-Fi
    État                  : connecté
    SSID                   : globalmet
    BSSID                  : d4:53:2a:b0:42:a2
"""
WINDOWS_NETWORKS = """
Interface name : Wi-Fi
There are 3 networks currently visible.

SSID 1 : globalmet
    Network type            : Infrastructure
SSID 2 : TELLO-5A3C21
    Network type            : Infrastructure
SSID 3 : RMTT-0F11AA
"""
NMCLI = "no:globalmet\nyes:TELLO-5A3C21\nno:Cafe\\:Guest\n"  # nmcli escapes ":" in names
MACOS_PROFILER = """
        Current Network Information:
          globalmet:
            PHY Mode: 802.11ax
        Other Local Wi-Fi Networks:
          TELLO-5A3C21:
            PHY Mode: 802.11n
          Neighbours:
            PHY Mode: 802.11ac
"""


def test_parses_the_systems_output():
    assert wifi.parse_windows_current(WINDOWS_INTERFACES_FR) == "globalmet"
    assert wifi.parse_windows_networks(WINDOWS_NETWORKS) == ["globalmet", "TELLO-5A3C21", "RMTT-0F11AA"]
    assert wifi.parse_nmcli(NMCLI) == [(False, "globalmet"), (True, "TELLO-5A3C21"), (False, "Cafe:Guest")]
    assert wifi.parse_macos_networks(MACOS_PROFILER) == ["TELLO-5A3C21"]


def test_only_drone_networks_count():
    assert wifi.DRONE_NETWORK.match("TELLO-5A3C21")
    assert wifi.DRONE_NETWORK.match("RMTT-0F11AA")
    assert not wifi.DRONE_NETWORK.match("globalmet")
    assert not wifi.DRONE_NETWORK.match("TELLO-5A3C21; rm -rf")
    assert wifi.connect("globalmet") == "not a drone network"


def test_windows_profile_is_for_an_open_network():
    profile = wifi.windows_profile("TELLO-5A3C21")
    assert "<name>TELLO-5A3C21</name>" in profile
    assert "<authentication>open</authentication>" in profile


def test_connect_button_appears_and_joins_the_network(app, monkeypatch):
    app.fake.telemetry = app.fake.answer = False  # drone not reachable yet
    joined = []
    monkeypatch.setattr(wifi, "drone_networks", lambda: ["TELLO-5A3C21"])
    monkeypatch.setattr(wifi, "connect", lambda ssid: joined.append(ssid))
    assert wait_until(app, lambda: app.drone_networks == ["TELLO-5A3C21"])
    screen_text(app)
    assert app.wifi_button is not None  # drawn, and clickable
    assert app.hint_items()[1][0] == ("C", "Connect to TELLO-5A3C21", None)

    app.on_pad_button("square")
    assert wait_until(app, lambda: joined == ["TELLO-5A3C21"])
    assert wait_until(app, lambda: "Connected to TELLO-5A3C21" in messages(app))
    monkeypatch.setattr(wifi, "current_network", lambda: "TELLO-5A3C21")
    monkeypatch.setattr(wifi, "drone_networks", lambda: ["TELLO-5A3C21"])  # the one we're on isn't offered
    assert wait_until(app, lambda: app.current_wifi == "TELLO-5A3C21" and not app.drone_networks)
    assert "On TELLO-5A3C21 - waiting for the drone" in screen_text(app)

    app.fake.telemetry = app.fake.answer = True  # the drone answers: the app connects
    assert wait_until(app, lambda: app.tello.connected)


def test_failed_connection_is_explained(app, monkeypatch):
    app.fake.telemetry = app.fake.answer = False
    monkeypatch.setattr(wifi, "drone_networks", lambda: ["TELLO-5A3C21"])
    monkeypatch.setattr(wifi, "connect", lambda ssid: "The network is out of range")
    assert wait_until(app, lambda: app.drone_networks)
    app.connect_wifi()
    assert wait_until(app, lambda: "Couldn't connect to TELLO-5A3C21: The network is out of range"
                      in (app.wifi_status or ""))
    assert "Couldn't connect" in screen_text(app)


def drop_wifi(app, monkeypatch, joined, flying=True):
    """On TELLO-5A3C21 (flying or not), then the computer moves to another network and the drone goes quiet."""
    monkeypatch.setattr(wifi, "current_network", lambda: "TELLO-5A3C21")
    monkeypatch.setattr(wifi, "connect", lambda ssid: joined.append(ssid))
    assert wait_until(app, lambda: app.tello.connected and app.drone_wifi == "TELLO-5A3C21")
    if flying:
        app.fake.state.update(h=100, tof=100)
        assert wait_until(app, lambda: app.tello.flying)
    app.fake.telemetry = app.fake.answer = False
    monkeypatch.setattr(wifi, "current_network", lambda: "globalmet")
    monkeypatch.setattr(wifi, "drone_networks", lambda: ["TELLO-5A3C21"])


def test_rejoins_the_drones_wifi_after_a_drop(app, monkeypatch):
    joined = []
    drop_wifi(app, monkeypatch, joined)
    assert wait_until(app, lambda: joined == ["TELLO-5A3C21"], timeout=10)
    assert "Wi-Fi moved away from TELLO-5A3C21 - rejoining it" in messages(app)


def test_doesnt_rejoin_long_after_losing_the_drone(app, monkeypatch):
    from tello_revived import app as app_module

    monkeypatch.setattr(app_module, "REJOIN_WITHIN", 0.0)  # e.g. you moved to your own Wi-Fi after flying
    joined = []
    drop_wifi(app, monkeypatch, joined)
    wait_until(app, lambda: False, timeout=2)
    assert joined == []


def test_rejoining_can_be_switched_off(app, monkeypatch):
    app.settings["flight"]["rejoin_wifi"] = False
    joined = []
    drop_wifi(app, monkeypatch, joined)
    wait_until(app, lambda: False, timeout=2)
    assert joined == []


def test_switching_networks_on_the_ground_is_left_alone(app, monkeypatch):
    joined = []
    drop_wifi(app, monkeypatch, joined, flying=False)  # landed (or never took off), then you switch Wi-Fi
    wait_until(app, lambda: False, timeout=2)
    assert joined == []
