"""Compare the language files with the text in the code (docs/translations.md).

    uv run python tools/check_translations.py          all languages
    uv run python tools/check_translations.py fr de    some of them
    uv run python tools/check_translations.py --list   just the English text, one per line

Lists, for each language, the text it doesn't translate yet, entries the app no longer uses, and
translations whose {placeholders} don't match the English. Exits with 1 if anything is wrong.
"""

import ast
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "tello_revived"
LOCALES = PACKAGE / "locales"


def source_texts():
    """{English text: "file:line" where it's first used}, from every t("...") and N_("...") in the app."""
    found = {}
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("t", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                    and node.args[0].value):
                found.setdefault(node.args[0].value, f"{path.name}:{node.lineno}")
    return found


def placeholders(text):
    """The {names} in a text, as a set."""
    try:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
    except ValueError:
        return None  # a stray { or }


def check(code, texts):
    """Problems with one language file, as printable lines."""
    try:
        data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"can't read {code}.json: {e}"]
    problems = []
    if not data.get("_name"):
        problems.append('no "_name" (the language\'s name, in that language)')
    entries = {k: v for k, v in data.items() if not k.startswith("_")}
    for english, where in texts.items():
        if english not in entries:
            problems.append(f"missing ({where}): {english}")
    for english, translated in entries.items():
        if english not in texts:
            problems.append(f"unused: {english}")
        elif not isinstance(translated, str) or not translated.strip():
            problems.append(f"empty: {english}")
        elif placeholders(translated) != placeholders(english):
            problems.append(f"placeholders differ: {english}  ->  {translated}")
    return problems


def main(args):
    texts = source_texts()
    if args == ["--list"]:
        print("\n".join(texts))
        return 0
    codes = args or sorted(p.stem for p in LOCALES.glob("*.json"))
    failed = False
    for code in codes:
        problems = check(code, texts)
        failed |= bool(problems)
        print(f"{code}: {'OK' if not problems else f'{len(problems)} to fix'} ({len(texts)} texts)")
        for line in problems:
            print("  " + line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
