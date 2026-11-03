# Translations

Tello Revived's text comes from one file per language in [`tello_revived/locales/`](../tello_revived/locales). The app is written in English, and each language file says how to show each English text in that language.

## Choosing the language

Settings > HUD > Language. **Auto** (the default) uses your computer's language when there's a file for it, and English otherwise. The change applies right away.

## The language files

Each file is JSON, named after the language's two-letter code (`fr.json`, `de.json`, ...):

```json
{
  "_name": "Français",
  "Taking off": "Décollage",
  "Battery {battery}% - auto landing": "Batterie {battery} % - atterrissage auto",
  "Saved {file}": "{file} enregistré"
}
```

- `_name` is the language's name, written in that language, as shown in the Language setting.
- Each other key is the exact English text from the app, and its value is the translation.
- Words in braces, like `{battery}` or `{file}`, are filled in by the app. Keep them as they are, with the same names; you can move them wherever the sentence needs them.
- Text missing from a file is shown in English, so a partial translation still works.
- Keep translations about as short as the English: most text is on the HUD or in a menu row with limited room.

Button and key names (Triangle, L1, Space...) and the drone's own replies aren't translated.

## Adding a language

1. Copy `tello_revived/locales/fr.json` to `tello_revived/locales/<code>.json` (for example `nl.json`).
2. Change `_name`, then translate every value. Leave the keys in English.
3. Check it:

   ```bash
   uv run python tools/check_translations.py nl
   ```

   It lists text that's missing from the file, text the app no longer uses, and translations whose `{placeholders}` don't match the English.
4. Look through the screens, either in the app (Settings > HUD > Language) or as pictures:

   ```bash
   uv run python tools/make_screenshots.py nl shots-nl
   ```

   This draws the flight screen and every settings page in that language into the `shots-nl` folder, so you can spot text that's too long to fit.
5. Open a pull request with the new file.

## Fixing a translation

Edit the value in the language's file. If the English text changes in the code, the old entry stops matching and the checker reports it as unused, with the new text as missing.

## For developers

User-facing text in the code goes through `t()` from `tello_revived/i18n.py`:

```python
from tello_revived.i18n import N_, t

self.tello.log(t("Taking off"))
self.tello.log(t("Battery {battery}% - auto landing", battery=f"{bat:.0f}"))
```

- Pass changing values as named placeholders, never by building the sentence with an f-string, so translators get one whole sentence.
- Text defined once at module level (tables, lists of names) is marked with `N_("...")`, which leaves it in English, and translated with `t()` where it's drawn. The menu does this for every row label, hint and option.
- Don't compare shown text in the code (`if status == "Connecting..."`): it changes with the language. Keep a flag instead.

`tools/check_translations.py` finds every `t("...")` and `N_("...")` in the code. `tests/test_translations.py` fails if a language file has a placeholder mismatch, an empty or unused entry, or no `_name`; missing text only shows in the checker, since it falls back to English. The other tests run in English.
