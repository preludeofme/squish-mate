#!/usr/bin/env python3
"""
click_monitor.py — lightweight global left/right-click detector.

So the pet can react to what the user is doing (scrolling, clicking around a
page, interacting with the same window) even when the active window/app
hasn't changed — not just on window switches. Uses `pynput`'s global mouse
listener (X11 backend). Only click timing is tracked; no click positions,
keystrokes, or content are recorded.
"""

import threading
import time

try:
    from pynput import mouse
    _PYNPUT_OK = True
except ImportError:
    _PYNPUT_OK = False


class ClickMonitor:
    """Tracks the timestamp of the most recent mouse click, thread-safely."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last_click = 0.0
        self._listener = None

    def available(self):
        return _PYNPUT_OK

    def start(self):
        if not _PYNPUT_OK:
            print("[click_monitor] pynput not installed; click reactions disabled")
            return
        try:
            self._listener = mouse.Listener(on_click=self._on_click)
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:
            print(f"[click_monitor] failed to start: {e}")
            self._listener = None

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def _on_click(self, x, y, button, pressed):
        if pressed:
            with self._lock:
                self._last_click = time.time()

    def clicked_since(self, timestamp):
        """True if a click has landed after `timestamp` (time.time()-based)."""
        with self._lock:
            return self._last_click > timestamp
