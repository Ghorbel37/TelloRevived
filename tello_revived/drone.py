"""The link to the drone: commands, replies, telemetry and keep-alive (Tello SDK over UDP)."""

import queue
import socket
import threading
import time
from collections import deque

from tello_revived.settings import stream_settings_supported

TELLO_ADDR = ("192.168.10.1", 8889)
CMD_PORT = 8889
STATE_PORT = 8890


class Tello:
    """Command, state and keep-alive link to the drone (SDK over UDP)."""

    def __init__(self, settings):
        self.settings = settings
        self.sock = self._udp(CMD_PORT)
        self.state_sock = self._udp(STATE_PORT)
        self.replies = queue.Queue()
        self.stream_on = None  # what we last told the drone (None = unknown)
        self.stream_settings_ok = None  # False once the drone rejects setresolution etc. (pre SDK 3.0)
        self.query_lock = threading.Lock()
        self.awaiting = False
        self.state = {}
        self.state_time = 0.0
        self.session_time = 0.0
        self.session = False
        # the drone answers commands but its telemetry never arrives: almost always a firewall,
        # which lets replies to our commands through but blocks what the drone sends on its own
        self.blocked = False
        self.wifi = None
        self.log_lines = deque(maxlen=6)
        self.running = True
        for target in (self._reply_loop, self._state_loop, self._link_loop):
            threading.Thread(target=target, daemon=True).start()

    @staticmethod
    def _udp(port):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            s.ioctl(socket.SIO_UDP_CONNRESET, False)  # Windows: ignore ICMP "port unreachable"
        s.bind(("", port))
        s.settimeout(0.5)
        return s

    @property
    def connected(self):
        return time.monotonic() - self.state_time < 1.5

    @property
    def flying(self):
        return self.connected and self.state.get("h", 0) > 0

    def log(self, text):
        self.log_lines.append((time.monotonic(), text))

    def send(self, cmd):
        try:
            self.sock.sendto(cmd.encode(), TELLO_ADDR)
        except OSError:
            pass  # not on the Tello network (yet)

    def query(self, cmd, timeout, accept=lambda r: True):
        with self.query_lock:
            while not self.replies.empty():
                self.replies.get_nowait()
            self.awaiting = True
            try:
                self.send(cmd)
                deadline = time.monotonic() + timeout
                while (left := deadline - time.monotonic()) > 0:
                    try:
                        reply = self.replies.get(timeout=left)
                    except queue.Empty:
                        break
                    if accept(reply):
                        return reply
                    self.log(f"Tello: {reply}")  # a reply to some other command
                return None
            finally:
                self.awaiting = False

    def _reply_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(1024)
            except OSError:
                continue
            # the Tello sometimes pads replies with NUL bytes
            reply = data.decode(errors="replace").replace(chr(0), "").strip()
            if self.awaiting:
                self.replies.put(reply)
            else:
                self.log(f"Tello: {reply}")

    def _state_loop(self):
        while self.running:
            try:
                data, _ = self.state_sock.recvfrom(1024)
            except OSError:
                continue
            state = {}
            for field in data.decode(errors="ignore").strip().split(";"):
                key, _, value = field.partition(":")
                try:
                    state[key] = float(value)
                except ValueError:
                    pass
            if state:
                self.state = state
                self.state_time = time.monotonic()
                if self.blocked:
                    self.blocked = False
                    self.log("Telemetry is getting through now")

    def want_video(self):
        mode = self.settings["power"]["video"]
        return mode == "on" or (mode == "flying" and self.flying)

    def apply_stream_settings(self):
        """Send the stream quality settings that aren't left at the drone's default."""
        p = self.settings["power"]
        if not stream_settings_supported(self.settings):
            return  # the user's model can't, so don't even ask
        cmds = []
        if p["resolution"] != "default":
            cmds.append(f"setresolution {p['resolution']}")
        if p["stream_fps"] != "default":
            cmds.append(f"setfps {p['stream_fps']}")
        if p["bitrate"] != "default":
            cmds.append(f"setbitrate {0 if p['bitrate'] == 'auto' else p['bitrate']}")
        if not cmds or self.stream_settings_ok is False:
            return  # nothing to set, or this drone already said it can't
        for cmd in cmds:
            reply = self.query(cmd, 2.0)
            if reply != "ok":
                self.stream_settings_ok = False
                self.log(f"This Tello can't change stream quality ('{cmd}': {reply or 'no reply'}) - "
                         "needs SDK 3.0 firmware, using its defaults")
                return
        self.stream_settings_ok = True

    def _link_loop(self):
        last_wifi = last_stream = 0.0
        while self.running:
            now = time.monotonic()
            if self.session and not self.connected and now - self.session_time > 3:
                if self.state_time < self.session_time:  # nothing at all since we connected
                    self._check_blocked()
                    continue
                self.session = False
                self.log("Link lost - reconnecting")
            if not self.session:
                if self.query("command", 1.0, lambda r: r == "ok"):
                    self.session = True
                    self.session_time = time.monotonic()
                    self.stream_on = None
                    self.log("Tello connected")
                    self.apply_stream_settings()
                else:
                    time.sleep(0.5)
                continue
            want = self.want_video()
            if want != self.stream_on and now - last_stream > 3:
                last_stream = now
                cmd = "streamon" if want else "streamoff"
                if self.query(cmd, 2.0, lambda r: r == "ok"):
                    self.stream_on = want
                else:
                    self.log(f"{cmd} got no reply - retrying")
            if self.connected and now - last_wifi > 3:
                last_wifi = now
                reply = self.query("wifi?", 1.0, lambda r: r.isdigit())
                if reply:
                    self.wifi = int(reply)
            time.sleep(0.25)

    def _check_blocked(self):
        """The drone answers but sends no telemetry: say so once, and keep checking it's there."""
        if self.query("command", 1.0, lambda r: r == "ok"):
            if not self.blocked:
                self.blocked = True
                self.log("The drone answers, but its telemetry is blocked - check the firewall")
            self.session_time = time.monotonic()  # check again in 3 s, without reconnecting
            time.sleep(0.5)
        else:  # it stopped answering too: switched off or out of range
            self.session = self.blocked = False
            self.log("Link lost - reconnecting")

    def close(self):
        self.running = False
