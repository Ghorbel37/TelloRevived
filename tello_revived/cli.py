"""Command line entry point.

    uv run tello-revived              start the app (or: run.bat / ./run.sh)
    uv run tello-revived --joytest    show raw gamepad axis/button numbers (for RAW_MAP in gamepad.py)

Connect the computer's Wi-Fi to the TELLO-XXXXXX network first. In the app press H (or Start) for
the controls and O for settings; everything is saved in config.json.
"""

import argparse

import av
import pygame
from pygame._sdl2 import controller as sdl_controller

from tello_revived import VERSION, drone, labels
from tello_revived.app import App
from tello_revived.hud import MONO
from tello_revived.labels import key_label
from tello_revived.paths import ICON_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"Tello Revived v{VERSION}")
    parser.add_argument("--joytest", action="store_true", help="show raw gamepad input")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    pygame.init()
    sdl_controller.init()
    if args.joytest:
        joytest()
        pygame.quit()
        return
    if args.selftest:
        return selftest()
    try:
        app = App()
    except OSError as e:
        pygame.display.set_caption("Tello Revived")
        message_window([f"Can't open the Tello ports {drone.CMD_PORT}/{drone.STATE_PORT}:", str(e), "",
                        "Tello Revived (or another drone app) is probably already running.",
                        "Close it and start Tello Revived again."])
        pygame.quit()
        return 1
    app.run()


def message_window(lines):
    """Show some text until the window is closed or a key / button is pressed."""
    screen = pygame.display.set_mode((720, 60 + 28 * len(lines)))
    font = pygame.font.SysFont(MONO, 17)
    clock = pygame.time.Clock()
    while not any(ev.type in (pygame.QUIT, pygame.KEYDOWN, pygame.CONTROLLERBUTTONDOWN, pygame.JOYBUTTONDOWN)
                  for ev in pygame.event.get()):
        screen.fill((15, 15, 20))
        for n, line in enumerate(lines):
            screen.blit(font.render(line, True, (235, 235, 235)), (24, 30 + 28 * n))
        pygame.display.flip()
        clock.tick(20)


def selftest():
    """Start the app, draw a few frames and check the H.264 decoder, then exit (used by the builds)."""
    drone.CMD_PORT = drone.STATE_PORT = 0  # any free port, so it runs next to a real session
    try:
        av.CodecContext.create("h264", "r")
        assert ICON_PATH.exists(), f"missing {ICON_PATH}"
        key_label(pygame.KSCAN_UP)
        if not labels._sdl:
            print("warning: SDL2 library not found - key names use the US layout")
        app = App()
        for _ in range(5):
            app.read_sticks()
            app.draw_hud(app.draw_video())
            pygame.display.flip()
        app.shutdown()
    except Exception:  # a windowed build would show a dialog and hang CI instead
        import traceback
        traceback.print_exc()
        return 1
    print("selftest ok")
    return 0




def joytest():
    """Print raw joystick values so RAW_MAP can be adjusted."""
    screen = pygame.display.set_mode((640, 480))
    pygame.display.set_caption("Gamepad test - close window to exit")
    font = pygame.font.SysFont(MONO, 16)
    clock = pygame.time.Clock()
    joys = {}
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.JOYDEVICEADDED:
                j = pygame.joystick.Joystick(ev.device_index)
                joys[j.get_instance_id()] = j
            elif ev.type == pygame.JOYDEVICEREMOVED:
                joys.pop(ev.instance_id, None)
        screen.fill((15, 15, 20))
        lines = [] if joys else ["No gamepad detected"]
        for i, j in enumerate(joys.values()):
            std = "yes" if sdl_controller.is_controller(i) else "NO - uses RAW_MAP"
            lines += [f"{j.get_name()}", f"  GUID {j.get_guid()}", f"  standard mapping: {std}",
                      "  axes:    " + "  ".join(f"{a}:{j.get_axis(a):+.2f}" for a in range(j.get_numaxes())),
                      "  buttons: " + " ".join(str(b) for b in range(j.get_numbuttons()) if j.get_button(b)),
                      "  hats:    " + " ".join(str(j.get_hat(h)) for h in range(j.get_numhats())), ""]
        for n, line in enumerate(lines):
            screen.blit(font.render(line, True, (220, 220, 220)), (12, 12 + n * 22))
        pygame.display.flip()
        clock.tick(30)
