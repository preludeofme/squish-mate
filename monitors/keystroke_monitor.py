#!/usr/bin/env python3
"""
keystroke_monitor.py — OPT-IN global keystroke listener for occasional pet
commentary on what the user is typing (e.g. venting in an email: "this guy!
I can't stand him" -> a quick playful reaction).

===========================================================================
PRIVACY — read this before wiring it up anywhere:
===========================================================================
  * OFF by default. Nothing is captured unless the "keystroke commentary"
    setting is explicitly turned on (see pet_settings.py / pet_config.json
    "keystroke_commentary").
  * Keystrokes are held ONLY in a small in-memory buffer, capped to a
    couple hundred characters (older characters roll off automatically).
  * NOTHING is ever written to disk, added to `pet_memory.PetMemory`
    (which does persist to disk), or logged/printed anywhere by this
    module or its callers.
  * The buffer is read via `snapshot_and_clear()` — the ONLY way to read
    it — which returns the text and immediately wipes it in the same
    step. There is no way to read the buffer without clearing it.
  * Turning the setting off calls `set_enabled(False)`, which also wipes
    whatever's currently buffered right away.
  * Modifier/navigation/function keys are ignored entirely — only
    printable characters, space, enter, and backspace (for natural
    editing) are ever added to the buffer.
===========================================================================
"""

import threading
import time

try:
    from pynput import keyboard
    _PYNPUT_OK = True
except ImportError:
    _PYNPUT_OK = False

MAX_BUFFER_CHARS = 240


class KeystrokeMonitor:
    """Global keyboard listener. See module docstring for the privacy
    contract — in short: in-memory only, capped size, cleared on every
    read, and only active while explicitly enabled."""

    def __init__(self, max_chars=MAX_BUFFER_CHARS):
        self._lock = threading.Lock()
        self._buffer = []
        self._max_chars = max_chars
        self._listener = None
        self._enabled = False
        self.last_keystroke_time = 0.0

    def available(self):
        return _PYNPUT_OK

    def set_enabled(self, enabled):
        """Turn capture on/off live (mirrors the Settings checkbox). When
        disabled, any currently-buffered text is dropped immediately."""
        with self._lock:
            self._enabled = bool(enabled)
            if not self._enabled:
                self._buffer.clear()
                self.last_keystroke_time = 0.0

    def start(self):
        """Start the global listener (still a no-op capture-wise until
        `set_enabled(True)` is also called)."""
        if not _PYNPUT_OK:
            print("[keystroke_monitor] pynput not installed; keystroke commentary disabled")
            return
        try:
            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:
            print(f"[keystroke_monitor] failed to start: {e}")
            self._listener = None

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        with self._lock:
            self._buffer.clear()
            self.last_keystroke_time = 0.0

    def _on_press(self, key):
        if not self._enabled:
            return
        try:
            char = getattr(key, "char", None)
        except Exception:
            char = None
        with self._lock:
            self.last_keystroke_time = time.time()
            if char and char.isprintable():
                self._buffer.append(char)
            elif key == keyboard.Key.space:
                self._buffer.append(" ")
            elif key == keyboard.Key.enter:
                self._buffer.append(" ")
            elif key == keyboard.Key.backspace:
                if self._buffer:
                    self._buffer.pop()
            # Everything else (shift/ctrl/alt, arrows, F-keys, etc.) is
            # intentionally ignored — never added to the buffer.
            if len(self._buffer) > self._max_chars:
                del self._buffer[: len(self._buffer) - self._max_chars]

    def buffered_length(self):
        with self._lock:
            return len(self._buffer)

    def get_last_keystroke_time(self):
        with self._lock:
            return self.last_keystroke_time

    def snapshot_and_clear(self):
        """Return the buffered text and IMMEDIATELY wipe it. This is the
        ONLY way to read the buffer — by design there is no peek-without-
        clearing, so typed content never outlives its one use."""
        with self._lock:
            text = "".join(self._buffer)
            self._buffer.clear()
            return text
