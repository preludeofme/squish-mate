#!/usr/bin/env bash
# Launcher for the desktop pet. Always uses the project venv's Python so you
# never hit "No module named 'PySide6'" from running the wrong interpreter.
set -euo pipefail
cd "$(dirname "$0")"

VENV_PY=".venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
    echo "Project venv not found at $VENV_PY"
    echo "Create it and install deps:"
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/pip install PySide6 psutil requests pillow"
    exit 1
fi

exec "$VENV_PY" desktop_pet.py "$@"
