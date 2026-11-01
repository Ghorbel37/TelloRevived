#!/bin/sh
# Linux / macOS: run from source (creates .venv the first time)
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv || exit 1
    .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python -m tello_revived "$@"
