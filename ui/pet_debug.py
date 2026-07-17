#!/usr/bin/env python3
"""
pet_debug.py — right-click "Debug…" panel: buttons to fire any animation
state or facial emotion on demand, for testing pet_animator.py /
pet_expressions.py changes without waiting for the real triggers (random
idle scheduling, LLM tone classification, clicks/drags) to happen naturally.

Wired directly to the live `DesktopPetWindow` (`self.window`), so clicks
take effect immediately on the currently-running pet — nothing here is
simulated separately.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ui.pet_expressions import Emotion

# (button label, PetAnimator.trigger_* method name)
ACTION_BUTTONS = [
    ("Hop", "trigger_hop"),
    ("Wave", "trigger_wave"),
    ("Yawn", "trigger_yawn"),
    ("Stretch", "trigger_stretch"),
    ("Dance", "trigger_dance"),
    ("Somersault", "trigger_somersault"),
    ("Eat", "trigger_eat"),
    ("Sleep", "trigger_sleep"),
]

# (button label, Emotion)
EMOTION_BUTTONS = [
    ("Neutral", Emotion.NEUTRAL),
    ("Happy", Emotion.HAPPY),
    ("Sad", Emotion.SAD),
    ("Surprised", Emotion.SURPRISED),
    ("Angry", Emotion.ANGRY),
    ("Scared", Emotion.SCARED),
]


class DebugDialog(QDialog):
    """Non-modal test panel. Kept alive as a single reused instance by
    `DesktopPetWindow.open_debug()`, same pattern as TranscriptDialog."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setWindowTitle("Pip's Debug Panel")
        self.resize(360, 460)
        self.setStyleSheet(
            "QDialog { background: #FFF8DC; }"
            "QGroupBox { font-weight: bold; color: #5B3E8C; "
            "border: 1px solid #C9A5F0; border-radius: 8px; margin-top: 10px; "
            "padding-top: 12px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; "
            "padding: 0 4px; }"
            "QPushButton { background: #C9A5F0; color: #2D1B36; "
            "border: 1px solid #8A6BC0; border-radius: 6px; padding: 6px 8px; }"
            "QPushButton:hover { background: #D9BFFA; }"
            "QLineEdit { background: #FFFDF5; border: 1px solid #C9A5F0; "
            "border-radius: 6px; padding: 4px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        title = QLabel("Fire any animation or emotion on demand")
        title.setStyleSheet("font-weight: bold; font-size: 13px; color: #5B3E8C;")
        title.setWordWrap(True)
        layout.addWidget(title)

        layout.addWidget(self._build_actions_box())
        layout.addWidget(self._build_emotions_box())
        layout.addWidget(self._build_bubble_box())

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    # ------------------------------------------------------------------ ui
    def _build_actions_box(self):
        box = QGroupBox("Actions (force-triggered, ignores current state)")
        grid = QGridLayout(box)
        entries = list(ACTION_BUTTONS)
        entries += [
            ("Wake", None),
            ("Surprise + Flee", None),
            ("Drag pose (3s)", None),
        ]
        handlers = (
            [self._make_action_handler(name) for _, name in ACTION_BUTTONS]
            + [self._on_wake, self._on_surprise_flee, self._on_drag_pose]
        )
        for i, ((label, _), handler) in enumerate(zip(entries, handlers)):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            grid.addWidget(btn, i // 2, i % 2)
        return box

    def _build_emotions_box(self):
        box = QGroupBox("Emotions (bypasses the normal odds/cooldown gate)")
        grid = QGridLayout(box)
        for i, (label, emotion) in enumerate(EMOTION_BUTTONS):
            btn = QPushButton(label)
            btn.clicked.connect(self._make_emotion_handler(emotion))
            grid.addWidget(btn, i // 3, i % 3)
        return box

    def _build_bubble_box(self):
        box = QGroupBox("Test bubble text (runs through classify_emotion)")
        row = QHBoxLayout(box)
        self.bubble_input = QLineEdit()
        self.bubble_input.setPlaceholderText("Type a line and press Enter…")
        self.bubble_input.returnPressed.connect(self._on_send_bubble)
        send_btn = QPushButton("Say it")
        send_btn.clicked.connect(self._on_send_bubble)
        row.addWidget(self.bubble_input)
        row.addWidget(send_btn)
        return box

    # ------------------------------------------------------------- handlers
    def _make_action_handler(self, method_name):
        def handler():
            getattr(self.window.animator, method_name)(force=True)
        return handler

    def _make_emotion_handler(self, emotion):
        def handler():
            self.window.animator.set_expression(emotion, duration=4.0)
        return handler

    def _on_wake(self):
        self.window.animator.wake()

    def _on_surprise_flee(self):
        geo = self.window._screen_geometry()
        self.window.animator.surprise_and_flee(
            (geo.x(), geo.y(), geo.width(), geo.height()))

    def _on_drag_pose(self):
        self.window.animator.start_drag()
        QTimer.singleShot(3000, self.window.animator.end_drag)

    def _on_send_bubble(self):
        text = self.bubble_input.text().strip()
        if not text:
            return
        self.window.show_bubble(text)
        self.bubble_input.clear()
