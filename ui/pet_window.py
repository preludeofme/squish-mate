#!/usr/bin/env python3
"""
pet_window.py — transparent always-on-top PySide6 window hosting the blob.

A tiny real-time vector animation engine:

  QTimer tick (~30 FPS)
    → PetAnimator.update(dt, cursor, screen)  (state machine → Pose)
    → move the window if the pet is wandering
    → repaint: BlobRenderer redraws the entire character from the Pose

The speech bubble is a separate frameless translucent window so it can float
above the pet and never clips. `bubble_requested` is a Qt signal, so background
threads (the activity monitor / LLM brain) can emit text safely; Qt queues the
delivery onto the GUI thread.
"""

import random
import time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QMenu, QWidget

from ui.blob_renderer import BlobRenderer
from ui.pet_animator import PetAnimator, Pose
from ui.pet_debug import DebugDialog
from ui.pet_expressions import Emotion, classify_emotion
from ui.pet_responses import random_drag_line
from ui.pet_settings import MOVE_FREQUENCY_PRESETS
from ui.pet_transcript import TranscriptDialog, TranscriptLog

FRAME_MS = 33  # ~30 FPS
CLICK_DRAG_THRESHOLD = 6  # px of travel before a press becomes a drag

# Even when a bubble's tone is confidently classified as non-neutral, only
# actually animate the face this often — Ryan: "it's OK to have it only have
# an emotional response once in a while, I don't want every message to have
# an emotion." The transcript still records the classified tone regardless.
EXPRESSION_SHOW_PROB = 0.45
EXPRESSION_MIN_GAP_S = 6.0  # and never back-to-back even if the roll hits

_PET_FLAGS = (Qt.WindowType.FramelessWindowHint
              | Qt.WindowType.WindowStaysOnTopHint
              | Qt.WindowType.Tool)


class SpeechBubble(QWidget):
    """Floating rounded-rect bubble with a tail, drawn procedurally too."""

    PAD_X, PAD_Y, TAIL_H, MAX_TEXT_W = 12, 8, 10, 260

    def __init__(self):
        super().__init__(None, _PET_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._text = ""
        self._tail_down = True
        self._font = QFont("Sans Serif", 10)

    def set_text(self, text):
        self._text = text
        fm = QFontMetrics(self._font)
        rect = fm.boundingRect(QRect(0, 0, self.MAX_TEXT_W, 1000),
                               Qt.TextFlag.TextWordWrap, text)
        self.setFixedSize(rect.width() + self.PAD_X * 2,
                          rect.height() + self.PAD_Y * 2 + self.TAIL_H)
        self.update()

    def set_tail_down(self, down):
        if self._tail_down != down:
            self._tail_down = down
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        top = 0 if self._tail_down else self.TAIL_H
        body = QRectF(1, top + 1, w - 2, h - self.TAIL_H - 2)

        path = QPainterPath()
        path.addRoundedRect(body, 10, 10)
        cx = w / 2
        tail = QPainterPath()
        if self._tail_down:
            tail.moveTo(cx - 7, body.bottom() - 1)
            tail.lineTo(cx, h - 1)
            tail.lineTo(cx + 7, body.bottom() - 1)
        else:
            tail.moveTo(cx - 7, body.top() + 1)
            tail.lineTo(cx, 1)
            tail.lineTo(cx + 7, body.top() + 1)
        tail.closeSubpath()
        path = path.united(tail)

        painter.setPen(QPen(QColor("#8A6BC0"), 1.6))
        painter.setBrush(QColor("#FFF8DC"))
        painter.drawPath(path)

        painter.setPen(QColor("#222222"))
        painter.setFont(self._font)
        painter.drawText(
            QRectF(self.PAD_X, top + self.PAD_Y,
                   w - self.PAD_X * 2, h - self.TAIL_H - self.PAD_Y * 2),
            Qt.TextFlag.TextWordWrap, self._text)


class DesktopPetWindow(QWidget):
    """Transparent window that owns the animator, renderer, and bubble."""

    bubble_requested = Signal(object)  # thread-safe entry point for the brain
    window_closed_reaction = Signal(str)  # thread-safe: an app window closed
    settings_requested = Signal()   # right-click → Settings…
    quit_requested = Signal()       # right-click → Quit

    W, H = 150, 180

    def __init__(self):
        super().__init__(None, _PET_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.W, self.H)

        self.animator = PetAnimator(self.W, self.H)
        self.renderer = BlobRenderer(self.W, self.H)
        self._pose = Pose()
        self._last_tick = time.monotonic()
        self._pet_name = "Pip"

        self.bubble = SpeechBubble()
        self._bubble_hide = QTimer(self)
        self._bubble_hide.setSingleShot(True)
        self._bubble_hide.timeout.connect(self.hide_bubble)

        self._frame = QTimer(self)
        self._frame.setInterval(FRAME_MS)
        self._frame.timeout.connect(self._tick)

        self.bubble_requested.connect(self.show_bubble)
        self.window_closed_reaction.connect(self._on_window_closed)

        # Right-click → Transcript: every line said, timestamped. Storage is
        # self-contained here (no config needed), so it's handled locally
        # rather than routed through a signal to DesktopPet.
        self.transcript = TranscriptLog()
        self._transcript_dialog = None
        self._last_expression_t = -999.0

        # Right-click → Debug…: buttons to force any animation/emotion for
        # testing (see pet_debug.py). Same lazy-reuse pattern as transcript.
        self._debug_dialog = None

        # Drag bookkeeping.
        self._press_pos = None
        self._press_window_pos = None
        self._dragging = False

    # -------------------------------------------------------------- lifecycle
    def start(self):
        """Show the pet bottom-right and start the frame loop."""
        geo = self._screen_geometry()
        x = geo.x() + max(50, geo.width() - self.W - 40)
        y = geo.y() + max(80, geo.height() - self.H - 40)
        self.animator.set_pos(x, y)
        self.move(x, y)
        self.show()
        self._last_tick = time.monotonic()
        self._frame.start()
        QTimer.singleShot(1000, lambda: self.show_bubble(
            "I'm awake! I'll wander around now."))

    def stop(self):
        self._frame.stop()
        self._bubble_hide.stop()
        self.bubble.close()
        self.close()

    def apply_settings(self, config):
        """Push live config (color + movement cadence) into the renderer and
        animator. Safe to call before or after start()."""
        color = config.get("color")
        if color:
            self.renderer.apply_color(color)
        ranges = MOVE_FREQUENCY_PRESETS.get(
            config.get("move_frequency", "normal"), MOVE_FREQUENCY_PRESETS["normal"])
        self.animator.set_frequencies(
            hop_range=ranges["hop"], wave_range=ranges["wave"],
            wander_range=ranges["wander"],
            sleep_after=config.get("sleep_after", 120))
        self._pet_name = config.get("name") or self._pet_name
        self.update()

    def closeEvent(self, event):
        self._frame.stop()
        self.bubble.close()
        super().closeEvent(event)

    # ------------------------------------------------------------- frame loop
    def _screen_geometry(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _tick(self):
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        geo = self._screen_geometry()
        cursor = QCursor.pos()
        self._pose = self.animator.update(
            dt, (cursor.x(), cursor.y()),
            (geo.x(), geo.y(), geo.width(), geo.height()))

        ix, iy = int(self.animator.x), int(self.animator.y)
        if (ix, iy) != (self.x(), self.y()):
            self.move(ix, iy)
            if self.bubble.isVisible():
                self._position_bubble()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        self.renderer.draw(painter, self._pose)

    # ---------------------------------------------------------------- bubbles
    def show_bubble(self, data, duration_ms=4000):
        if isinstance(data, dict):
            text = data.get("text", "")
            suggested_emotion = data.get("suggestedEmotion", "neutral")
            suggested_action = data.get("suggestedAction", "idle")
        else:
            text = str(data)
            suggested_emotion = "neutral"
            suggested_action = "idle"

        text = text.strip()[:200]
        if not text:
            return
        self.animator.notify_activity()
        
        # Every bubble (LLM output or a canned line) flows through here, so
        # this is the single choke point to both log the transcript and
        # drive the face from tone — see pet_expressions.classify_emotion.
        emotion = classify_emotion(text)
        self.transcript.add(text, emotion.name.lower())
        if self._transcript_dialog is not None and self._transcript_dialog.isVisible():
            self._transcript_dialog.refresh()

        final_emotion = Emotion.NEUTRAL
        if suggested_emotion != "neutral":
            try:
                final_emotion = Emotion[suggested_emotion.upper()]
            except KeyError:
                final_emotion = emotion
        else:
            final_emotion = emotion

        self._maybe_show_expression(final_emotion, duration_ms)

        if suggested_action != "idle":
            trigger_method = f"trigger_{suggested_action}"
            if hasattr(self.animator, trigger_method):
                try:
                    getattr(self.animator, trigger_method)(force=True)
                except Exception:
                    pass

        self.bubble.set_text(text)
        self._position_bubble()
        self.bubble.show()
        self.bubble.raise_()
        self._bubble_hide.start(duration_ms)

    def hide_bubble(self):
        self.bubble.hide()

    def _maybe_show_expression(self, emotion, duration_ms):
        """Gate how often a classified tone actually reaches the face.

        Ryan: emotions were showing up too often (mostly SURPRISED) and he
        wants an emotion only "once in a while", not on every line. The
        transcript records the classified tone regardless of this gate —
        only the visible face reaction is throttled."""
        if emotion is Emotion.NEUTRAL:
            return
        now = time.monotonic()
        if (now - self._last_expression_t) < EXPRESSION_MIN_GAP_S:
            return
        if random.random() >= EXPRESSION_SHOW_PROB:
            return
        self._last_expression_t = now
        self.animator.set_expression(emotion, duration=duration_ms / 1000.0 + 0.6)

    # ------------------------------------------------------------ transcript
    def open_transcript(self):
        if self._transcript_dialog is None or not self._transcript_dialog.isVisible():
            self._transcript_dialog = TranscriptDialog(
                self.transcript, pet_name=self._pet_name, parent=self)
            self._transcript_dialog.show()
        else:
            self._transcript_dialog.raise_()
            self._transcript_dialog.activateWindow()

    # ----------------------------------------------------------------- debug
    def open_debug(self):
        if self._debug_dialog is None or not self._debug_dialog.isVisible():
            self._debug_dialog = DebugDialog(self, parent=self)
            self._debug_dialog.show()
        else:
            self._debug_dialog.raise_()
            self._debug_dialog.activateWindow()

    def _on_window_closed(self, text):
        """An app window closed elsewhere on the desktop — instant canned
        goodbye (no LLM call, so it lands right away instead of ~a minute
        late)."""
        self.show_bubble(text, duration_ms=3000)
        self.animator.trigger_wave()

    def _position_bubble(self):
        geo = self._screen_geometry()
        bw, bh = self.bubble.width(), self.bubble.height()
        bx = self.x() + self.W // 2 - bw // 2
        by = self.y() - bh + 14  # tuck toward the antenna headroom
        tail_down = True
        if by < geo.y():
            by = self.y() + self.H - 6
            tail_down = False
        bx = max(geo.x(), min(bx, geo.x() + geo.width() - bw))
        self.bubble.set_tail_down(tail_down)
        self.bubble.move(int(bx), int(by))

    # ------------------------------------------------------------ interaction
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Settings…", self.settings_requested.emit)
        menu.addAction("Transcript…", self.open_transcript)
        menu.addAction("Debug…", self.open_debug)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_requested.emit)
        menu.exec(event.globalPos())

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_pos = event.globalPosition()
        self._press_window_pos = QPointF(self.x(), self.y())
        self._dragging = False
        self.animator.wake()

    def mouseMoveEvent(self, event):
        if self._press_pos is None:
            return
        delta = event.globalPosition() - self._press_pos
        if (not self._dragging
                and max(abs(delta.x()), abs(delta.y())) > CLICK_DRAG_THRESHOLD):
            self._dragging = True
            self.animator.start_drag()
            # Instant canned reaction (no LLM) so it fires the moment the
            # drag starts, not seconds/minutes later.
            self.show_bubble(random_drag_line(), duration_ms=1400)
        if self._dragging:
            nx = self._press_window_pos.x() + delta.x()
            ny = self._press_window_pos.y() + delta.y()
            self.animator.set_pos(nx, ny)
            self.move(int(nx), int(ny))
            if self.bubble.isVisible():
                self._position_bubble()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        was_drag = self._dragging
        self._press_pos = None
        self._dragging = False
        if was_drag:
            self.animator.end_drag()
            return
        # Plain click → startled hop, then scoot out of the way.
        geo = self._screen_geometry()
        self.show_bubble("Okay, moving out of your way!", duration_ms=1800)
        self.animator.surprise_and_flee(
            (geo.x(), geo.y(), geo.width(), geo.height()))


# Manual demo: python3 pet_window.py (from a graphical terminal)
if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    pet = DesktopPetWindow()
    pet.start()
    QTimer.singleShot(3000, pet.animator.trigger_wave)
    QTimer.singleShot(6000, pet.animator.trigger_hop)
    sys.exit(app.exec())
