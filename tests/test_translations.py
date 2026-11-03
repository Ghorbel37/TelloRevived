"""The language files match the code's text, and the Language setting switches the app's text."""

import importlib.util
from pathlib import Path

import pytest

from tello_revived import i18n
from conftest import connect, screen_text

spec = importlib.util.spec_from_file_location("check_translations",
                                              Path(__file__).resolve().parent.parent / "tools" / "check_translations.py")
check_translations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_translations)
TEXTS = check_translations.source_texts()


@pytest.mark.parametrize("code", [code for code, _ in i18n.languages() if code != "en"])
def test_language_file_matches_the_code(code):
    # missing text falls back to English, so only broken or stale entries fail
    problems = [p for p in check_translations.check(code, TEXTS) if not p.startswith("missing")]
    assert problems == []


def test_placeholders_are_filled_after_translating():
    i18n._strings = {"Saved {file}": "{file} enregistré"}
    try:
        assert i18n.t("Saved {file}", file="a.mp4") == "a.mp4 enregistré"
        assert i18n.t("Not in the file") == "Not in the file"
    finally:
        i18n.set_language("en")


def test_language_setting_changes_the_screen(app):
    connect(app)
    assert "to take off" in screen_text(app)
    app.settings["app"]["language"] = "fr"
    app.on_setting_changed("app", "language")
    try:
        assert "pour décoller" in screen_text(app)
    finally:
        i18n.set_language("en")


def test_auto_uses_the_computers_language(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "de")
    i18n.set_language("auto")
    try:
        assert i18n.t("Land") == "Landen"
    finally:
        i18n.set_language("en")
