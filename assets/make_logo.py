"""Draw the Tello Revived logo (assets/logo.png), window icon (icon.png) and app icons (icon.ico, icon.icns).

    uv run python assets/make_logo.py
"""

import math
import os
import struct
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

HERE = Path(__file__).resolve().parent
S = 2048  # drawn large, then scaled down for smooth edges

BG_TOP, BG_BOTTOM = (22, 34, 58), (10, 14, 24)
ACCENT = (120, 190, 255)
WHITE = (240, 244, 250)
GREEN = (120, 255, 160)


def draw():
    surf = pygame.Surface((S, S), pygame.SRCALPHA)
    # rounded square with a vertical gradient
    grad = pygame.Surface((S, S), pygame.SRCALPHA)
    for y in range(S):
        t = y / S
        grad.fill([int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)] + [255], (0, y, S, 1))
    mask = pygame.Surface((S, S), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, S, S), border_radius=S // 5)
    grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surf.blit(grad, (0, 0))

    c = S // 2
    # HUD horizon line behind the drone, tilted a little
    tilt = math.radians(-8)
    dx, dy = math.cos(tilt), math.sin(tilt)
    for side in (-1, 1):
        a = (c + side * dx * S * 0.30, c + 0.17 * S + side * dy * S * 0.30)
        b = (c + side * dx * S * 0.43, c + 0.17 * S + side * dy * S * 0.43)
        pygame.draw.line(surf, GREEN, a, b, S // 64)

    # quadcopter, top view
    arm = S * 0.25
    rotor_r = S * 0.13
    for ang in (45, 135, 225, 315):
        r = math.radians(ang)
        end = (c + math.cos(r) * arm, c + math.sin(r) * arm * 0.82)
        pygame.draw.line(surf, WHITE, (c, c), end, S // 26)
        pygame.draw.circle(surf, ACCENT, end, rotor_r, S // 48)
        pygame.draw.circle(surf, WHITE, end, S // 40)
        # motion blur blades
        for k in range(2):
            b = r + k * math.pi / 2 + 0.4
            p1 = (end[0] + math.cos(b) * rotor_r * 0.75, end[1] + math.sin(b) * rotor_r * 0.75)
            p2 = (end[0] - math.cos(b) * rotor_r * 0.75, end[1] - math.sin(b) * rotor_r * 0.75)
            pygame.draw.line(surf, (*ACCENT, 140), p1, p2, S // 90)
    body = pygame.Rect(0, 0, S * 0.24, S * 0.30)
    body.center = (c, c)
    pygame.draw.rect(surf, WHITE, body, border_radius=int(S * 0.06))
    cam = pygame.Rect(0, 0, S * 0.10, S * 0.05)
    cam.midtop = (c, body.top + S * 0.025)
    pygame.draw.rect(surf, BG_TOP, cam, border_radius=int(S * 0.02))
    pygame.draw.circle(surf, ACCENT, cam.center, S * 0.016)
    pygame.draw.circle(surf, GREEN, (c, body.bottom - S * 0.05), S * 0.018)
    return surf


def png_bytes(big, size):
    """The logo scaled to size x size, as PNG file bytes."""
    path = HERE / f".tmp_{size}.png"
    pygame.image.save(pygame.transform.smoothscale(big, (size, size)), str(path))
    data = path.read_bytes()
    path.unlink()
    return data


def write_ico(big, path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """Windows icon: an ICO directory whose entries are PNG images (supported since Vista)."""
    images = [png_bytes(big, s) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))  # reserved, type 1 = icon, image count
    offset = 6 + 16 * len(images)
    for s, data in zip(sizes, images):
        # width, height (0 means 256), colours, reserved, planes, bits per pixel, size, offset
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(out + b"".join(images))


def write_icns(big, path):
    """macOS icon: an ICNS container of PNG images, one per icon type."""
    types = {"icp4": 16, "icp5": 32, "icp6": 64, "ic07": 128, "ic08": 256, "ic09": 512, "ic10": 1024}
    body = b"".join(kind.encode() + struct.pack(">I", 8 + len(data)) + data
                    for kind, data in ((k, png_bytes(big, s)) for k, s in types.items()))
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def main():
    pygame.init()
    big = draw()
    pygame.image.save(pygame.transform.smoothscale(big, (512, 512)), str(HERE / "logo.png"))
    pygame.image.save(pygame.transform.smoothscale(big, (64, 64)), str(HERE / "icon.png"))
    write_ico(big, HERE / "icon.ico")  # used by the Windows build
    write_icns(big, HERE / "icon.icns")  # used by the macOS build
    print("wrote logo.png, icon.png, icon.ico and icon.icns")


if __name__ == "__main__":
    main()
