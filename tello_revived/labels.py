"""Display names for keyboard keys (layout aware) and gamepad buttons."""

import ctypes
from pathlib import Path

import pygame

PAD_LABELS = {
    "cross": "Cross", "circle": "Circle", "square": "Square", "triangle": "Triangle",
    "select": "Select", "start": "Start", "ps": "PS", "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2", "l3": "L3", "r3": "R3",
    "up": "D-pad up", "down": "D-pad down", "left": "D-pad left", "right": "D-pad right",
}


_sdl = None


def _load_sdl():
    """The SDL2 library pygame uses (already loaded, so this just gets a handle to it)."""
    base = Path(pygame.__file__).resolve().parent
    # Windows: pygame/SDL2.dll, macOS: pygame/.dylibs, Linux: pygame_ce.libs next to pygame
    for folder in (base, base / ".dylibs", base.parent / "pygame_ce.libs", base.parent):
        for lib in sorted(folder.glob("*SDL2*")):
            if "sdl2_" in lib.name.lower():  # SDL2_image, SDL2_ttf, ...
                continue
            try:
                sdl = ctypes.CDLL(str(lib))
                sdl.SDL_GetKeyFromScancode.restype = ctypes.c_int32
                sdl.SDL_GetKeyFromScancode.argtypes = [ctypes.c_int]
                return sdl
            except (OSError, AttributeError):
                continue
    return False


def _us_key(scancode):
    """US-layout key code for a scancode, if SDL can't be asked."""
    if 4 <= scancode <= 29:
        return ord("a") + scancode - 4
    if 30 <= scancode <= 39:
        return ord("1234567890"[scancode - 30])
    return {40: 13, 41: 27, 42: 8, 43: 9, 44: 32}.get(scancode, scancode | 1 << 30)


def key_label(scancode):
    """Name of the key at this physical position on the current keyboard layout."""
    global _sdl
    if scancode is None:
        return "-"
    if _sdl is None:
        _sdl = _load_sdl()
    try:
        name = pygame.key.name(_sdl.SDL_GetKeyFromScancode(scancode) if _sdl else _us_key(scancode))
    except (OSError, ValueError):
        name = ""
    if not name:
        return f"key {scancode}"
    return name.upper() if len(name) == 1 else name.title()


def pad_label(button):
    return PAD_LABELS.get(button, "-") if button else "-"
