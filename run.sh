#!/bin/sh
# Start Tello Revived from source. Uses uv if installed, otherwise a plain venv.
cd "$(dirname "$0")" || exit 1
if command -v uv >/dev/null 2>&1; then
    exec uv run tello-revived "$@"
fi
if [ ! -x .venv/bin/python ]; then
    echo "Creating virtual environment... (installing uv makes this faster: https://docs.astral.sh/uv/)"
    python3 -m venv .venv || exit 1
    .venv/bin/python -m pip install -e . || exit 1
fi
exec .venv/bin/python -m tello_revived "$@"
