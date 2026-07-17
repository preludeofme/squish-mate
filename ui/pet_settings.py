#!/usr/bin/env python3
"""
pet_settings.py — right-click "Settings…" dialog, plus the frequency/color
presets shared by pet_window.py (live rendering/animation) and
desktop_pet.py (idle chatter cadence, brain persona).
"""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from ui.blob_renderer import DEFAULT_BODY_COLOR as DEFAULT_COLOR

# (hop, wave, wander) re-scheduling ranges in seconds — how often each
# behavior is re-rolled while idle. Lower = more frequent.
MOVE_FREQUENCY_PRESETS = {
    "calm":   {"hop": (14, 26), "wave": (35, 70), "wander": (40, 90)},
    "normal": {"hop": (8, 16),  "wave": (25, 50), "wander": (25, 60)},
    "hyper":  {"hop": (3, 8),   "wave": (12, 25), "wander": (10, 25)},
}

# Idle chatter cadence (no LLM call) + LLM comment cooldown, per preset.
MESSAGE_FREQUENCY_PRESETS = {
    "quiet":  {"idle_range_s": (60, 150), "idle_prob": 0.15, "brain_cooldown": 60.0},
    "normal": {"idle_range_s": (25, 70),  "idle_prob": 0.30, "brain_cooldown": 30.0},
    "chatty": {"idle_range_s": (10, 30),  "idle_prob": 0.55, "brain_cooldown": 12.0},
}

MOVE_FREQUENCY_LABELS = [("calm", "Calm"), ("normal", "Normal"), ("hyper", "Hyper")]
MESSAGE_FREQUENCY_LABELS = [("quiet", "Quiet"), ("normal", "Normal"), ("chatty", "Chatty")]


class PetSettingsDialog(QDialog):
    """Right-click → Settings… dialog. Read new values with get_values()
    after exec() returns QDialog.Accepted."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pet Settings")
        self.setMinimumWidth(360)
        self._color = QColor(config.get("color") or DEFAULT_COLOR)

        self._name = QLineEdit(config.get("name", "Pip"))

        self._color_btn = QPushButton()
        self._color_btn.clicked.connect(self._pick_color)
        self._update_color_btn()

        self._traits = QLineEdit(", ".join(config.get("personality_traits", [])))
        self._traits.setPlaceholderText("curious, goofy, mischievous")

        self._prompt = QTextEdit(config.get("initial_prompt", ""))
        self._prompt.setPlaceholderText(
            "Extra guidance for the pet's personality/behavior (optional)...")
        self._prompt.setFixedHeight(80)

        self._move_freq = QComboBox()
        for key, label in MOVE_FREQUENCY_LABELS:
            self._move_freq.addItem(label, key)
        self._select_combo(self._move_freq, config.get("move_frequency", "normal"))

        self._msg_freq = QComboBox()
        for key, label in MESSAGE_FREQUENCY_LABELS:
            self._msg_freq.addItem(label, key)
        self._select_combo(self._msg_freq, config.get("message_frequency", "normal"))

        self._sleep_after = QSpinBox()
        self._sleep_after.setRange(30, 3600)
        self._sleep_after.setSuffix(" s")
        self._sleep_after.setValue(int(config.get("sleep_after", 120)))

        self._keystroke_commentary = QCheckBox("Occasionally comment on what I'm typing")
        self._keystroke_commentary.setChecked(
            bool(config.get("keystroke_commentary", False)))

        keystroke_note = QLabel(
            "Off by default — nothing is captured unless this is checked. "
            "When ON, the pet occasionally glances at a few recent "
            "keystrokes to react to the vibe of what you're typing (e.g. "
            "venting in an email). We are NOT recording, storing, or "
            "logging keystrokes anywhere — they live in a tiny in-memory "
            "buffer that's wiped the instant it's used (or if you turn "
            "this back off). Nothing is ever written to disk. Uncheck "
            "anytime to stop listening completely."
        )
        keystroke_note.setWordWrap(True)
        keystroke_note.setStyleSheet("color: #666; font-size: 11px;")

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Color", self._color_btn)
        form.addRow("Personality traits", self._traits)
        form.addRow("Initial prompt", self._prompt)
        form.addRow("Movement frequency", self._move_freq)
        form.addRow("Message frequency", self._msg_freq)
        form.addRow("Nap after (idle seconds)", self._sleep_after)
        form.addRow(self._keystroke_commentary)
        form.addRow(keystroke_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _select_combo(combo, key):
        idx = combo.findData(key)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _pick_color(self):
        color = QColorDialog.getColor(self._color, self, "Pick pet color")
        if color.isValid():
            self._color = color
            self._update_color_btn()

    def _update_color_btn(self):
        self._color_btn.setText(self._color.name())
        self._color_btn.setStyleSheet(
            f"background-color: {self._color.name()}; color: #222;")

    def get_values(self):
        traits = [t.strip() for t in self._traits.text().split(",") if t.strip()]
        return {
            "name": self._name.text().strip() or "Pip",
            "color": self._color.name(),
            "personality_traits": traits,
            "initial_prompt": self._prompt.toPlainText().strip(),
            "move_frequency": self._move_freq.currentData(),
            "message_frequency": self._msg_freq.currentData(),
            "sleep_after": self._sleep_after.value(),
            "keystroke_commentary": self._keystroke_commentary.isChecked(),
        }
