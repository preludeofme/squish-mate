#!/usr/bin/env python3
"""
screen_reader.py — periodic full-screen capture for the pet's brain.

Grabbing the screen requires the Qt GUI thread, so a QTimer on the main
thread takes a downscaled JPEG snapshot every few seconds and caches it
(base64-encoded) behind a lock. The monitor/brain background thread reads
the latest cached snapshot via `latest()` without touching Qt itself.
"""

import base64
import threading

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QTimer, Qt
from PySide6.QtGui import QGuiApplication

MAX_DIMENSION = 1024  # downscale so the vision call stays fast and cheap
JPEG_QUALITY = 70


class ScreenReader:
    """Owns a QTimer that periodically grabs the primary screen."""

    def __init__(self, interval_ms=5000):
        self.interval_ms = interval_ms
        self._lock = threading.Lock()
        self._latest_b64 = None
        self._timer = None

    def start(self):
        """Must be called on the Qt GUI thread, after QApplication exists."""
        self._capture()  # seed a snapshot immediately
        self._timer = QTimer()
        self._timer.timeout.connect(self._capture)
        self._timer.start(self.interval_ms)

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _capture(self):
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                return
            if pixmap.width() > MAX_DIMENSION or pixmap.height() > MAX_DIMENSION:
                pixmap = pixmap.scaled(
                    MAX_DIMENSION,
                    MAX_DIMENSION,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            buf = QByteArray()
            qbuf = QBuffer(buf)
            qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(qbuf, "JPEG", JPEG_QUALITY)
            qbuf.close()
            b64 = base64.b64encode(bytes(buf)).decode("ascii")
            with self._lock:
                self._latest_b64 = b64
        except Exception as e:
            print(f"[screen_reader] capture failed: {e}")

    def latest(self):
        """Thread-safe read of the most recent snapshot (base64 JPEG or None)."""
        with self._lock:
            return self._latest_b64


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    reader = ScreenReader()
    reader.start()
    snap = reader.latest()
    print(f"captured snapshot: {len(snap) if snap else 0} base64 chars")
