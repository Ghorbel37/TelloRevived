"""Closing the settings window with the mouse."""

import pygame


def test_a_click_outside_the_settings_window_or_on_its_x_closes_it(app):
    click = lambda pos: app.menu.handle_mouse(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    app.menu.open("HUD")
    app.draw_hud(app.draw_video())  # where the window is drawn
    click(app.menu.box.center)
    assert app.menu.is_open  # inside: stays open
    click((app.menu.box.right + 5, app.menu.box.centery))
    assert not app.menu.is_open
    app.menu.open("HUD")
    app.draw_hud(app.draw_video())
    click(app.menu.close_rect.center)  # the X in the corner
    assert not app.menu.is_open
