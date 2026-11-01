"""Draw the Tello Revived logo (assets/logo.png) and window icon (assets/icon.png).

    .venv\\Scripts\\python.exe assets\\make_logo.py
"""

import math
import os
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


def main():
    pygame.init()
    big = draw()
    pygame.image.save(pygame.transform.smoothscale(big, (512, 512)), str(HERE / "logo.png"))
    pygame.image.save(pygame.transform.smoothscale(big, (64, 64)), str(HERE / "icon.png"))
    print("wrote logo.png and icon.png")


if __name__ == "__main__":
    main()
