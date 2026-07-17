#!/usr/bin/env python3
"""
pet_library_dialog.py — right-click "Change Pet…" picker.

Shows every entry in core/pet_library.PET_LIBRARY as a color-swatch button;
picking one just changes body color + decorative pattern (see
BlobRenderer.apply_pattern) — the shape, rig, and every animation stay
exactly the same for every pet, per Ryan's spec.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.pet_library import PET_LIBRARY


class ChangePetDialog(QDialog):
    """Modal picker. Returns the chosen species id via `self.selected_id`
    once accepted (exec() == QDialog.Accepted)."""

    def __init__(self, current_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Pet")
        self.setMinimumWidth(340)
        self.selected_id = current_id
        self.setStyleSheet(
            "QDialog { background: #FFF8DC; }"
            "QPushButton { border: 2px solid #8A6BC0; border-radius: 8px; "
            "padding: 8px; text-align: left; color: #2D1B36; font-weight: bold; }"
            "QPushButton:hover { border-color: #5B3E8C; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Pick a pet — same squishy blob, different look")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #5B3E8C;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, entry in enumerate(PET_LIBRARY):
            btn = self._make_entry_button(entry, entry["id"] == current_id)
            grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(grid)

        close_btn = QPushButton("Cancel")
        close_btn.setStyleSheet(
            "QPushButton { background: #FFF8DC; text-align: center; "
            "border-color: #C9A5F0; font-weight: normal; }"
        )
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    def _make_entry_button(self, entry, is_current):
        color = QColor(entry["color"])
        text_color = "#FFFFFF" if color.lightness() < 150 else "#2D1B36"
        label = entry["name"] + (" ✓" if is_current else "")
        btn = QPushButton(f"{label}\n{entry['blurb']}")
        btn.setStyleSheet(
            f"background-color: {color.name()}; color: {text_color};"
        )
        btn.clicked.connect(lambda: self._choose(entry["id"]))
        return btn

    def _choose(self, pet_id):
        self.selected_id = pet_id
        self.accept()


# Manual demo: python3 -m ui.pet_library_dialog (from a graphical terminal)
if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dlg = ChangePetDialog("pip")
    if dlg.exec():
        print("Chosen:", dlg.selected_id)
