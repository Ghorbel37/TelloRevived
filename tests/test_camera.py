"""Video, photos, recordings and the photos and videos folder."""

import time

import av
import pygame
import pytest

from conftest import connect, messages, screen_text, wait_until


@pytest.fixture
def flying_with_video(app):
    connect(app)
    app.fake.state.update(h=100, tof=100)
    assert wait_until(app, app.camera_live, timeout=10), "no video from the fake drone"
    return app


def test_no_photo_or_recording_before_takeoff(app):
    connect(app)  # video is "only while flying" by default
    app.photo()
    app.toggle_record()
    assert messages(app)[-2:] == ["No photo: Camera starts at takeoff", "Not recording: Camera starts at takeoff"]
    assert not app.video.recording
    assert not app.fake.streaming


def test_photo_is_saved_at_full_size(flying_with_video, tmp_path):
    app = flying_with_video
    app.photo()
    app.photo()  # same second: must not overwrite the first
    photos = sorted((tmp_path / "media").glob("photo_*.png"))
    assert len(photos) == 2
    assert pygame.image.load(str(photos[0])).get_size() == (160, 120)


def test_recording_is_a_playable_mp4_and_stops_at_landing(flying_with_video, tmp_path):
    app = flying_with_video
    app.toggle_record()
    start = app.video.frame_id
    # CI machines sometimes stall the fake video for a while: ask for a dozen frames, with time to spare
    assert wait_until(app, lambda: app.video.frame_id - start >= 12, timeout=30)
    app.fake.state.update(h=0, tof=10)  # landed: video stops, so does the recording
    assert wait_until(app, lambda: not app.video.recording)
    assert wait_until(app, lambda: any(m.startswith("Saved video_") for m in messages(app)))
    mp4 = next((tmp_path / "media").glob("video_*.mp4"))
    with av.open(str(mp4)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.extradata  # the header players need
        assert sum(1 for _ in container.decode(stream)) >= 5


def test_media_folder_can_be_changed_and_reset(flying_with_video, tmp_path):
    app = flying_with_video
    chosen = tmp_path / "Drone media é"
    app.set_media_dir(str(chosen))
    app.photo()
    assert list(chosen.glob("photo_*.png"))
    assert app.settings["files"]["media_dir"] == str(chosen)

    not_a_folder = tmp_path / "file.txt"
    not_a_folder.write_text("x")
    app.set_media_dir(str(not_a_folder / "sub"))
    assert messages(app)[-1].startswith("Can't save to")
    assert app.media_dir() == chosen

    app.set_media_dir("")
    assert app.media_dir() == tmp_path / "media"
    assert app.settings["files"]["media_dir"] == ""


def test_app_delay_is_measured_and_shown(flying_with_video):
    app = flying_with_video
    assert wait_until(app, lambda: app.app_delay is not None)  # measured once a frame is on screen
    assert 0 <= app.app_delay < 1.0  # receive to screen, on this machine
    # shown while frames keep coming; a slow CI machine can pause the fake video for seconds, so say one just came
    app.video.frame_time = time.monotonic()
    assert "app delay" in screen_text(app)
    app.video.frame_time = time.monotonic() - 3  # and hidden once the video stops
    assert "app delay" not in screen_text(app)
