#!/usr/bin/env python3
"""
Quick launcher for the desktop pet.

Runs the app IN-PROCESS so you see logs live and the GUI stays attached to
your desktop session. Must be run from a graphical (logged-in) terminal —
not over plain SSH or from cron, where there is no DISPLAY.
"""

import os
import sys


def run_desktop_pet():
    pet_dir = os.path.expanduser("~/Projects/Personal/desktop-pet")
    os.chdir(pet_dir)
    sys.path.insert(0, pet_dir)

    # Re-exec under the project venv if PySide6 isn't importable here.
    venv_python = os.path.join(pet_dir, ".venv", "bin", "python")
    if os.path.exists(venv_python) and sys.executable != venv_python:
        try:
            import PySide6  # noqa: F401
        except ImportError:
            os.execv(venv_python, [venv_python, os.path.abspath(__file__)])

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("WARNING: No DISPLAY/WAYLAND_DISPLAY detected.")
        print("Run this from your logged-in desktop terminal, not SSH/cron.")

    print("Starting desktop pet... (Ctrl+C to quit)")
    from desktop_pet import main
    main()


if __name__ == "__main__":
    run_desktop_pet()
