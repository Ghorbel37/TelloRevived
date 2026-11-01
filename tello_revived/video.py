"""Receiving, decoding and recording the drone's H.264 video stream."""

import threading
import time
from collections import deque
from fractions import Fraction

import av

VIDEO_URL = "udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=5000000"


class Video:
    """Receives and decodes the H.264 stream; optionally records the raw stream to disk."""

    def __init__(self, log):
        self.log = log
        self.lock = threading.Lock()
        self.frame = None  # ((width, height), row pitch, rgb bytes), already scaled for the window
        self.raw_frame = None  # the last decoded frame at full size, for photos
        self.native_size = None  # the stream's own size
        self.display_size = None  # set by the HUD: the size the window shows the video at
        self.frame_id = 0
        self.frame_time = 0.0
        self.fps = 0.0
        self.rec_file = None
        self.rec_path = None
        self.rec_start = 0.0
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            try:
                container = av.open(VIDEO_URL, format="h264", timeout=(3.0, 3.0),
                                    options={"fflags": "nobuffer", "flags": "low_delay"})
            except Exception:
                time.sleep(0.2)
                continue  # nothing arriving yet
            try:
                stream = container.streams.video[0]
                # One decoder thread: this small stream decodes in a few ms, while FFmpeg's default
                # (a thread per CPU core) wastes CPU and holds frames back, adding delay.
                stream.codec_context.thread_count = 1
                frame_times = deque(maxlen=30)
                for packet in container.demux(stream):
                    if not self.running:
                        break
                    with self.lock:
                        if self.rec_file and packet.size:
                            self.rec_file.write(bytes(packet))
                    try:
                        frames = packet.decode()
                    except Exception:
                        continue  # corrupted packet (Wi-Fi loss) - next keyframe fixes it
                    for f in frames:
                        # convert to RGB and scale to the window in one FFmpeg step, here rather
                        # than in the drawing loop
                        size = self.display_size or (f.width, f.height)
                        plane = f.reformat(width=size[0], height=size[1], format="rgb24").planes[0]
                        rgb = bytes(plane)
                        now = time.monotonic()
                        frame_times.append(now)
                        if len(frame_times) > 1:
                            self.fps = (len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
                        with self.lock:
                            self.frame = (size, plane.line_size, rgb)
                            self.raw_frame = f
                            self.native_size = (f.width, f.height)
                            self.frame_id += 1
                            self.frame_time = now
            except Exception:
                pass  # stream timed out / dropped; reopen
            finally:
                container.close()

    def snapshot(self):
        """The latest frame at full size as ((width, height), pitch, rgb bytes), or None."""
        with self.lock:
            f = self.raw_frame
        if f is None:
            return None
        plane = f.reformat(format="rgb24").planes[0]
        return (f.width, f.height), plane.line_size, bytes(plane)

    @property
    def recording(self):
        return self.rec_file is not None

    def start_recording(self, path):
        with self.lock:
            self.rec_path = path
            self.rec_file = open(path, "wb")
            self.rec_start = time.monotonic()

    def stop_recording(self):
        with self.lock:
            f, path = self.rec_file, self.rec_path
            self.rec_file = None
        if f:
            f.close()
            threading.Thread(target=self._finish_recording, args=(path,), daemon=True).start()

    def _finish_recording(self, raw):
        mp4 = raw.with_suffix(".mp4")
        try:
            remux_to_mp4(raw, mp4)
            raw.unlink()
            self.log(f"Saved {mp4.name}")
        except Exception as e:
            self.log(f"Kept raw {raw.name} (mp4 failed: {e})")

    def close(self):
        self.stop_recording()
        self.running = False


def remux_to_mp4(src, dst, fps=30):
    """Wrap the raw Tello H.264 stream in an mp4 without re-encoding."""
    tb = Fraction(1, fps)
    with av.open(str(src), format="h264") as inp:
        in_stream = inp.streams.video[0]
        # FFmpeg finds the stream's SPS/PPS while opening it. Players need them in the mp4's header
        # and can't play the file without them, so keep the raw .h264 instead of saving that.
        if not in_stream.codec_context.extradata:
            raise ValueError("no SPS/PPS found in the stream")
        with av.open(str(dst), "w") as out:
            # opaque: copy the codec settings as they are, so no H.264 encoder is needed (the slim
            # FFmpeg in the Windows build only has the decoder)
            out_stream = out.add_stream_from_template(in_stream, opaque=True)
            n = 0
            for packet in inp.demux(in_stream):
                if not packet.size:
                    continue
                packet.stream = out_stream
                packet.time_base = tb
                packet.pts = packet.dts = n
                packet.duration = 1
                out.mux(packet)
                n += 1
    if not n:
        raise ValueError("no video in recording")
