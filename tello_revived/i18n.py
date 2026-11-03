"""Translations, read from one text file per language in tello_revived/locales/.

Each file is JSON: {"_name": "Français", "English text": "translated text", ...}. Text is written in
English in the code, wrapped in t(); a language file only lists what it translates, and anything
missing stays in English. Placeholders like {reason} are filled in after translating, so a
translation can put them where its grammar needs them.

To add a language, copy locales/fr.json to locales/<code>.json and translate the values;
tools/check_translations.py lists what's missing.
"""

import json
import locale
import os
import sys
from pathlib import Path

LOCALES = Path(__file__).resolve().parent / "locales"

_strings = {}  # English -> translation, for the language in use


def languages():
    """[(code, name)] of the languages there are files for, English first."""
    found = [("en", "English")]
    for path in sorted(LOCALES.glob("*.json")):
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("_name", path.stem)
        except (OSError, ValueError):
            continue
        found.append((path.stem, name))
    return found


def system_language():
    """The computer's language as a two-letter code ("fr"), or "en"."""
    code = None
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
            code = buffer.value  # e.g. "fr-FR"
    if not code:
        code = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG")
    if not code:
        code = (locale.getlocale()[0] or "")
    return (code or "en").replace("-", "_").split("_")[0].lower() or "en"


def set_language(code):
    """Use a language ("auto" = the computer's). Unknown languages, and English, use the code's text."""
    global _strings
    if code == "auto":
        code = system_language()
    path = LOCALES / f"{code}.json"
    try:
        _strings = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    except (OSError, ValueError):
        _strings = {}  # English, or a language without a file


def t(text, **values):
    """The text in the language in use, with {placeholders} filled in."""
    text = _strings.get(text, text)
    return text.format(**values) if values else text


def N_(text):
    """Marks text defined once (lists, tables) for translation where it's shown with t(); returns it as is."""
    return text
