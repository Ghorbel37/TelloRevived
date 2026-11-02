"""Short alert tones, generated here (no sound files), played only while sound alerts are on.

The sound system is started only when alerts are switched on, so the app doesn't keep the audio
device busy otherwise.
"""

import array
import math

import pygame

RATE = 44100

# name -> (frequency in Hz, length in s, pause after it in s) for each beep
TONES = {
    "warning": [(880, 0.12, 0.08), (880, 0.12, 0.0)],                       # two beeps: low battery
    "alarm": [(1320, 0.09, 0.05), (1320, 0.09, 0.05), (1320, 0.09, 0.0)],   # three fast high beeps
    "error": [(523, 0.15, 0.02), (392, 0.25, 0.0)],                          # falling: refused, blocked
}


def tone(beeps, volume=0.35):
    """16-bit mono samples for a list of (frequency, length, pause), with short fades (no clicks)."""
    samples = array.array("h")
    for freq, length, pause in beeps:
        n, fade = int(RATE * length), int(RATE * 0.01)
        for i in range(n):
            envelope = min(1.0, i / fade, (n - i) / fade)
            samples.append(int(32767 * volume * envelope * math.sin(2 * math.pi * freq * i / RATE)))
        samples.extend([0] * int(RATE * pause))
    return samples


class Sounds:
    def __init__(self):
        self.sounds = {}

    @property
    def on(self):
        return bool(self.sounds)

    def enable(self, on):
        if on and not self.sounds:
            try:
                pygame.mixer.init(RATE, -16, 1, 512)
                self.sounds = {name: pygame.mixer.Sound(buffer=tone(beeps).tobytes()) for name, beeps in TONES.items()}
            except pygame.error:
                self.sounds = {}  # no audio device: alerts stay silent
        elif not on and self.sounds:
            self.sounds = {}
            pygame.mixer.quit()

    def play(self, name):
        if name in self.sounds:
            self.sounds[name].play()
