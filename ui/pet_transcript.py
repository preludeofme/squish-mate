#!/usr/bin/env python3
"""
pet_transcript.py — in-memory log of everything the pet has said, plus a
styled right-click "Transcript" viewer.

`TranscriptLog` is fed by `DesktopPetWindow.show_bubble()` (the single choke
point every bubble — LLM output or canned line — already flows through), so
capturing it here required no other call sites to change. RAM-only, capped,
not written to disk: matches the privacy posture already established for
keystroke commentary (see keystroke_monitor.py) — nothing new is persisted.
"""

import html
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

MAX_ENTRIES = 300

# Small colored tag per emotion, used in the transcript viewer only (the
# face itself is driven by pet_animator/pet_expressions).
EMOTION_COLORS = {
    "happy": "#4CA24C",
    "sad": "#5C7CC9",
    "surprised": "#D9A441",
    "angry": "#C75450",
    "scared": "#8A5FC9",
    "neutral": "#9C9C9C",
}


@dataclass
class TranscriptEntry:
    timestamp: datetime
    text: str
    emotion: str = "neutral"


class TranscriptLog:
    """Thread-safe rolling log (bubbles are shown from the GUI thread, but a
    lock is cheap insurance if that ever changes)."""

    def __init__(self, max_entries=MAX_ENTRIES):
        self._entries = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def add(self, text, emotion="neutral"):
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._entries.append(TranscriptEntry(datetime.now(), text, emotion))

    def entries(self):
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()


class TranscriptDialog(QDialog):
    """Non-modal, styled scrollback of everything Pip has said. Kept alive
    and refreshed live by the window as new bubbles come in while it's open."""

    def __init__(self, log, pet_name="Pip", parent=None):
        super().__init__(parent)
        self.log = log
        self.setWindowTitle(f"{pet_name}'s Transcript")
        # Deliberately NOT WA_DeleteOnClose: the window keeps a Python
        # reference to this dialog to re-show/raise it on the next "Transcript…"
        # click, and a deleted-on-close C++ object would make that a dangling
        # pointer. Closing just hides it (default QWidget behavior).
        self.resize(400, 500)
        self.setStyleSheet(
            "QDialog { background: #FFF8DC; }"
            "QPushButton { background: #C9A5F0; color: #2D1B36; "
            "border: 1px solid #8A6BC0; border-radius: 6px; padding: 5px 14px; }"
            "QPushButton:hover { background: #D9BFFA; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(f"What {pet_name} has said")
        title.setStyleSheet(
            "font-weight: bold; font-size: 15px; color: #5B3E8C;"
        )
        layout.addWidget(title)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet(
            "QTextEdit { background: #FFFDF5; border: 1px solid #C9A5F0; "
            "border-radius: 8px; padding: 8px; }"
        )
        layout.addWidget(self.view)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self):
        entries = self.log.entries()
        scrollbar = self.view.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        if not entries:
            self.view.setHtml(
                "<i style='color:#999;'>Nothing said yet&hellip;</i>")
            return
        rows = []
        for e in entries:
            ts = e.timestamp.strftime("%H:%M:%S")
            color = EMOTION_COLORS.get(e.emotion, EMOTION_COLORS["neutral"])
            rows.append(
                '<div style="margin-bottom:8px;">'
                f'<span style="color:#999999; font-size:11px;">{ts}</span> '
                f'<span style="background:{color}; color:white; '
                'border-radius:7px; padding:1px 7px; font-size:10px;">'
                f'{html.escape(e.emotion.capitalize())}</span><br>'
                f'<span style="color:#2D1B36;">{html.escape(e.text)}</span>'
                '</div>'
            )
        self.view.setHtml("".join(rows))
        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def _on_clear(self):
        self.log.clear()
        self.refresh()
