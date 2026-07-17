#!/usr/bin/env python3
"""
UI-only visual smoke test for the desktop pet (PySide6, procedural rendering).

Bypasses activity monitoring entirely so you can confirm fast:
  1. The alien blob renders (body, tentacle arms, antenna, eyes, mouth).
  2. It wanders, breathes, blinks, hops, waves, and bubbles appear.

Run from a graphical desktop terminal:
    cd ~/Projects/Personal/desktop-pet
    .venv/bin/python test_pet.py
"""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ui.pet_window import DesktopPetWindow


def main():
    app = QApplication(sys.argv)

    pet = DesktopPetWindow()
    pet.start()

    # Scripted proof-of-life sequence.
    QTimer.singleShot(500, lambda: pet.show_bubble(
        "Speech bubble test — you should see me!"))
    QTimer.singleShot(3000, pet.animator.trigger_wave)
    QTimer.singleShot(6000, pet.animator.trigger_hop)
    QTimer.singleShot(8000, lambda: pet.show_bubble(
        "Movement test — I should be wandering around."))

    print("Test pet running. You should see a lavender alien blob move and talk.")
    print("Click it to shoo it aside, drag it to reposition, Ctrl+C to stop.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
