"""The Flights page: past flights from the flight logs, graphs, and battery history."""

import csv
import math

import pygame

from tello_revived import flights
from tello_revived.flightlog import COLUMNS


def write_log(folder, name, minutes, bat_start, bat_end, top_cm=200):
    """A flight log like FlightLog writes: climb, hover with a little wobble, descend."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"flight_{name}.csv"
    rows = int(minutes * 60 * 10)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        for i in range(rows):
            t = i / 10
            phase = i / rows
            h = top_cm * min(1, phase * 6, (1 - phase) * 6) + 10 * math.sin(t)
            w.writerow({"time_s": f"{t:.2f}", "height_cm": int(max(0, h)), "battery_pct": round(
                bat_start - (bat_start - bat_end) * phase), "speed_x_dm_s": int(5 + 3 * math.sin(t / 3)),
                "speed_y_dm_s": 2, "ground_distance_cm": int(max(10, h)), "event": ""})
    return path


def test_reads_a_flight_log(tmp_path):
    f = flights.read_flight(write_log(tmp_path, "20261102_101500", 3, 90, 70))
    assert f.started.hour == 10 and round(f.duration) == 180
    assert f.battery_start == 90 and f.battery_end == 70 and f.battery_used == 20
    assert 190 < f.max_height <= 210
    assert round(f.drain_per_minute, 1) == 6.7


def test_battery_trend_compares_recent_flights_with_earlier_ones(tmp_path):
    for day in range(1, 6):  # five older flights: 5% a minute
        write_log(tmp_path, f"202610{day:02d}_120000", 4, 95, 75)
    for day in range(6, 11):  # five recent ones: 7% a minute
        write_log(tmp_path, f"202610{day:02d}_120000", 4, 95, 67)
    found = flights.Flights().list(tmp_path)
    assert found[0].started.day == 10  # newest first
    recent, earlier = flights.battery_trend(found)
    assert round(recent) == 7 and round(earlier) == 5


def test_flights_page_warns_when_the_battery_drains_faster(app, tmp_path):
    media = tmp_path / "media"
    for day in range(1, 6):
        write_log(media, f"202610{day:02d}_120000", 4, 95, 75)  # 5% a minute
    for day in range(6, 11):
        write_log(media, f"202610{day:02d}_120000", 4, 95, 67)  # 7% a minute
    app.menu.open("Flights")
    labels = [r.label for r in app.menu.rows()]
    assert "Battery use: 7.0% a minute lately, 5.0% in earlier flights" in labels
    assert "Recent flights drain the battery faster: it may be ageing" in labels


def test_flights_page_lists_flights_and_opens_a_graph(app, tmp_path):
    media = tmp_path / "media"
    write_log(media, "20261101_090000", 2, 80, 66)
    write_log(media, "20261102_101500", 3, 90, 70)
    app.menu.open("Flights")
    rows = app.menu.rows()
    labels = [r.label for r in rows]
    assert labels[0] == "2 flights"
    assert any(label.startswith("2026-11-02 10:15   2:59   max 2.") for label in labels)  # newest first
    first = next(r for r in rows if r.kind == "button")
    first.fn()
    assert app.menu.graph.started.day == 2
    app.draw_hud(app.draw_video())  # draws the three charts without errors
    app.menu.handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, scancode=0, mod=0, unicode=""))
    assert app.menu.graph is None and app.menu.is_open  # Esc goes back to the list first
    first.fn()
    app.menu.handle_pad("circle")
    assert app.menu.graph is None


def test_empty_flights_page_says_how_to_get_logs(app):
    app.menu.open("Flights")
    labels = [r.label for r in app.menu.rows()]
    assert labels[0] == "No flight logs yet."
    assert "Save flight logs" in labels[1]
