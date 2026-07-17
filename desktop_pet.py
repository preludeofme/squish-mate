#!/usr/bin/env python3
"""
Main Desktop Pet Application (PySide6).

Coordinates three pieces:
  * DesktopPetWindow — procedurally-drawn alien blob (no image assets),
  * AdvancedActivityMonitor — watches which app/window is active,
  * PetBrain/PetMemory — local Ollama LLM turns activity into short comments.

Threading model: the monitor + LLM run in a daemon thread and hand text to the
GUI by emitting the window's `bubble_requested` signal (Qt queues it onto the
main thread). Idle chatter runs on the main thread via QTimer and never calls
the LLM, so a cold model load can't freeze the pet.
"""

import json
import os
import random
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
except ImportError as e:
    print(f"PySide6 is required: {e}")
    print("Install it with: .venv/bin/pip install PySide6 "
          "(or pip install PySide6)")
    sys.exit(1)

try:
    from monitors.advanced_monitor import AdvancedActivityMonitor
    from ui.pet_window import DesktopPetWindow
    from monitors.screen_reader import ScreenReader
except ImportError as e:
    print(f"Failed to import components: {e}")
    sys.exit(1)

from ui.pet_responses import random_window_close_line
from ui.pet_settings import MESSAGE_FREQUENCY_PRESETS, PetSettingsDialog

# Global click detection (optional — pet just won't react to same-page clicks
# if pynput isn't installed).
try:
    from monitors.click_monitor import ClickMonitor
except ImportError as e:
    ClickMonitor = None
    print(f"Click monitoring unavailable: {e}")

# Minimum gap between click-triggered reactions (separate from the
# window-switch trigger, which now bypasses the brain's cooldown entirely).
CLICK_REACT_COOLDOWN = 20.0

# Global keystroke listener (optional, OPT-IN — see keystroke_monitor.py for
# the privacy contract: nothing is ever captured unless the
# "keystroke_commentary" setting is explicitly turned on, and the buffer is
# never written to disk or logged).
try:
    from monitors.keystroke_monitor import KeystrokeMonitor
except ImportError as e:
    KeystrokeMonitor = None
    print(f"Keystroke monitoring unavailable: {e}")

# Keystroke-commentary pacing: needs a decent chunk of fresh typing, then
# only "sometimes" (not every eligible moment) reacts, then a longer cooldown
# so it's an occasional aside, not a running commentary.
KEYSTROKE_REACT_COOLDOWN = 45.0
KEYSTROKE_MIN_CHARS = 24
KEYSTROKE_REACT_PROB = 0.35

# Best-effort skip list: never forward typed text to the LLM while the
# active app/window looks like it might involve sensitive input. Not
# foolproof (title/app name only), but a reasonable extra guard on top of
# the setting being opt-in in the first place.
_KEYSTROKE_SENSITIVE_KEYWORDS = (
    "password", "passwd", "login", "log in", "sign in", "credit card",
    "bank", "ssh", "private key", "secret", "2fa", "otp", "authenticator",
    "keepass", "bitwarden", "1password", "lastpass", "wallet", "seed phrase",
)

# LLM brain + memory (optional — pet still runs with safe fallbacks if absent)
try:
    from core.pet_brain import SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT
    from core.pet_brain import PetBrain
    from core.pet_memory import PetMemory
except ImportError as e:
    PetBrain = None
    PetMemory = None
    DEFAULT_SYSTEM_PROMPT = ""
    print(f"LLM brain/memory unavailable, using safe fallbacks: {e}")

# Harmless idle quips used when the LLM is unavailable. Deliberately NOT creepy.
SAFE_IDLE = [
    "*happy wobble*",
    "Tiny blob thoughts...",
    "Boop!",
    "Just practicing my squish.",
    "La la la, being a little blob.",
    "Ooo, cozy over here.",
    "*antenna sways contentedly*",
]


class DesktopPet:
    def __init__(self, config_file="pet_config.json"):
        self.config_file = config_file
        self.config = self.load_config()
        self.monitor = AdvancedActivityMonitor()
        self.screen_reader = ScreenReader()
        self.click_monitor = ClickMonitor() if ClickMonitor else None
        self._last_click_reaction = 0.0
        self.keystroke_monitor = KeystrokeMonitor() if KeystrokeMonitor else None
        self._last_keystroke_reaction = 0.0
        self.app = None
        self.window = None
        self.is_running = False
        self.interaction_history = deque(maxlen=20)

        # Initialize authoritative PetEngine
        from core.pet_engine import PetEngine
        self.engine = PetEngine()

        # LLM brain + token-capped memory. Memory summarizes via the brain.
        self.memory = PetMemory(engine=self.engine) if PetMemory else None
        self.brain = PetBrain(memory=self.memory, engine=self.engine) if PetBrain else None
        if self.memory is not None and self.brain is not None:
            self.memory.summarizer = self.brain.summarize
        self._brain_busy = False

        # Idle-chatter cadence, driven by config["message_frequency"];
        # concrete values are (re)applied by apply_runtime_settings().
        self._idle_range_s = (25, 70)
        self._idle_prob = 0.30

    # ------------------------------------------------------------------ config
    def load_config(self):
        default_config = {
            "name": "Pip",
            "color": "#C9A5F0",
            "personality_traits": [],
            "initial_prompt": "",
            "move_frequency": "normal",
            "message_frequency": "normal",
            "sleep_after": 120,
            "max_bubble_length": 200,
            # OFF by default — opt-in only. See keystroke_monitor.py: when
            # on, a small in-memory buffer of recent keystrokes is
            # occasionally passed to the LLM for a one-off reaction, never
            # written to disk/logged, and cleared immediately after use.
            "keystroke_commentary": False,
            # The full LLM system prompt (pet_brain.SYSTEM_PROMPT by
            # default). Deliberately editable here and ONLY here — NOT
            # exposed in the Settings dialog UI — so it's a config-file-only
            # power-user knob for experimenting with prompt variations.
            # Blank/missing always falls back to the built-in default.
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
        }
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    loaded = json.load(f)
                config = {**default_config, **loaded}
                if "system_prompt" not in loaded:
                    # First run after this field was added — persist the
                    # default into the file now so it's immediately visible
                    # and editable there without waiting for a Settings save.
                    self._write_config_file(config)
                return config
            except Exception as e:
                print(f"Error loading config, using defaults: {e}")
        return default_config

    def _write_config_file(self, config):
        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

    def save_config(self):
        self._write_config_file(self.config)

    def apply_runtime_settings(self):
        """Push self.config into the window/animator/renderer/brain. Called
        once at startup and again after Settings… is saved."""
        if self.window:
            self.window.apply_settings(self.config)
        msg_freq = MESSAGE_FREQUENCY_PRESETS.get(
            self.config.get("message_frequency", "normal"),
            MESSAGE_FREQUENCY_PRESETS["normal"])
        self._idle_range_s = msg_freq["idle_range_s"]
        self._idle_prob = msg_freq["idle_prob"]
        if self.brain:
            self.brain.cooldown = msg_freq["brain_cooldown"]
            self.brain.set_persona(
                self.config.get("personality_traits", []),
                self.config.get("initial_prompt", ""))
            self.brain.set_system_prompt(self.config.get("system_prompt", ""))
        if self.keystroke_monitor:
            self.keystroke_monitor.set_enabled(
                bool(self.config.get("keystroke_commentary", False)))

    def open_settings(self):
        dialog = PetSettingsDialog(self.config, parent=self.window)
        if dialog.exec():
            self.config.update(dialog.get_values())
            self.save_config()
            self.apply_runtime_settings()

    # ------------------------------------------------------------------- brain
    def process_activity_change(self, activity, reason="activity change"):
        """Feed context about what the user is doing to the LLM brain and show
        its comment. Runs inside the monitor daemon thread, so the blocking
        brain.think() call is safe here; the text reaches the GUI thread via
        the window's queued `bubble_requested` signal."""
        active_app = activity.get("active_app", "unknown")
        window_title = activity.get("window_title", "unknown")
        process_name = activity.get("process_name") or active_app
        print(f"{reason.capitalize()} detected: {active_app}")

        # Guard against stacking multiple brain calls during rapid app switches.
        if self._brain_busy:
            return

        # 1. Register event in PetEngine
        event_type = "application_changed"
        if "click" in reason:
            event_type = "click_activity"
        elif "typing" in reason or "keystroke" in reason:
            event_type = "typing_continued"

        event = self.engine.register_event(
            raw_type=event_type,
            source=process_name,
            raw_summary=window_title,
            topic=self.engine.detector.guess_topic(active_app, window_title)
        )

        # 2. Check behavior gating
        gating = self.engine.get_behavior_gating(event)
        if not gating["allowSpeech"]:
            print(f"[gating] Speech blocked: {gating['reason']}")
            return

        comment = None
        if not self.brain:
            print("[brain] PetBrain not initialized (import failed at startup?)")
        elif not self.brain.available():
            print("[brain] Ollama unreachable right now — using canned idle line")
        else:
            self._brain_busy = True
            try:
                ctx = {
                    "active_app": activity.get("active_app"),
                    "window_title": activity.get("window_title"),
                    "process_name": process_name,
                    "recent_apps": list(getattr(self.monitor, "apps_seen", []))[-10:],
                }
                screenshot_b64 = self.screen_reader.latest()
                print(f"[brain] calling think() — screenshot={'yes' if screenshot_b64 else 'no'}")
                comment = self.brain.think(ctx, force=True, screenshot_b64=screenshot_b64)
            except Exception as e:
                print(f"Brain error: {e}")
            finally:
                self._brain_busy = False

        if not comment:
            print("[brain] think() returned nothing (brain unavailable/error) — using canned idle line")
            comment = random.choice(SAFE_IDLE)

        print(f"Sending message: {comment}")
        if self.window:
            self.window.bubble_requested.emit(comment)
        
        msg_text = comment["text"] if isinstance(comment, dict) else str(comment)
        self.interaction_history.append({
            "timestamp": datetime.now().isoformat(),
            "type": "activity_change",
            "app": active_app,
            "message": msg_text,
        })

    # --------------------------------------------------------- window closed
    def _react_to_window_close(self, app_name):
        """Instant canned goodbye (no LLM round-trip) for an app window that
        just closed elsewhere on the desktop."""
        self.engine.register_event(
            raw_type="window_closed",
            source=app_name,
            raw_summary=f"Closed window of {app_name}"
        )
        line = random_window_close_line(app_name)
        print(f"Window closed: {app_name} -> {line}")
        if self.window:
            self.window.window_closed_reaction.emit(line)
        self.interaction_history.append({
            "timestamp": datetime.now().isoformat(),
            "type": "window_closed",
            "app": app_name,
            "message": line,
        })

    # --------------------------------------------------------- typing (opt-in)
    def _maybe_react_to_keystrokes(self, activity):
        """OPT-IN: occasionally comment on what the user is typing."""
        km = self.keystroke_monitor
        if not km or not self.config.get("keystroke_commentary", False):
            return
        if not self.brain or self._brain_busy:
            return

        active_app = activity.get("active_app", "unknown")
        window_title = activity.get("window_title", "unknown")
        process_name = activity.get("process_name") or active_app

        event = self.engine.register_event(
            raw_type="typing_continued",
            source=process_name,
            raw_summary=window_title,
            topic=self.engine.detector.guess_topic(active_app, window_title)
        )

        gating = self.engine.get_behavior_gating(event)
        if not gating["allowSpeech"]:
            return

        now = time.time()
        if (now - self._last_keystroke_reaction) < KEYSTROKE_REACT_COOLDOWN:
            return
        if km.buffered_length() < KEYSTROKE_MIN_CHARS:
            return
        if random.random() > KEYSTROKE_REACT_PROB:
            return  # eligible, but only "sometimes" actually reacts

        title = (activity.get("window_title") or "").lower()
        app = (activity.get("active_app") or "").lower()
        if any(k in title or k in app for k in _KEYSTROKE_SENSITIVE_KEYWORDS):
            km.snapshot_and_clear()  # discard either way — never send it
            return

        text = km.snapshot_and_clear()
        if not text.strip():
            return

        self._last_keystroke_reaction = now
        self._brain_busy = True
        try:
            comment = self.brain.comment_on_typing(text)
        except Exception as e:
            print(f"Brain error (typing commentary): {e}")
            comment = None
        finally:
            self._brain_busy = False

        if comment and self.window:
            self.window.bubble_requested.emit(comment)
        
        msg_text = comment["text"] if isinstance(comment, dict) else str(comment)
        self.interaction_history.append({
            "timestamp": datetime.now().isoformat(),
            "type": "typing_commentary",
            "app": activity.get("active_app"),
            "message": msg_text,
        })

    # ------------------------------------------------------------ idle chatter
    def _schedule_random_bubble(self):
        lo, hi = self._idle_range_s
        interval_ms = random.randint(int(lo), int(hi)) * 1000
        QTimer.singleShot(interval_ms, self._random_bubble)

    def _random_bubble(self):
        if not self.is_running or not self.window:
            return
        try:
            if random.random() < self._idle_prob:
                self._trigger_idle_comment()
        except Exception as e:
            print(f"Error in random bubbles: {e}")
        finally:
            self._schedule_random_bubble()

    def _trigger_idle_comment(self):
        from core.pet_engine import Event
        event = Event("idle_comment", "system", "Periodic idle comment")
        gating = self.engine.get_behavior_gating(event)
        if not gating["allowSpeech"]:
            print(f"[gating] Idle speech blocked: {gating['reason']}")
            return

        if self.brain and not self._brain_busy:
            threading.Thread(target=self._idle_comment_worker, daemon=True).start()
        elif self.window:
            self.window.show_bubble(random.choice(SAFE_IDLE))

    def _idle_comment_worker(self):
        self._brain_busy = True
        comment = None
        try:
            comment = self.brain.idle_comment()
        except Exception as e:
            print(f"Brain error (idle): {e}")
        finally:
            self._brain_busy = False
        if not comment:
            comment = random.choice(SAFE_IDLE)
        if self.window:
            self.window.bubble_requested.emit(comment)

    # ------------------------------------------------------------ engine tick
    def _tick_engine(self):
        if not self.is_running or not self.window:
            return
        try:
            # Tick metabolic needs (2.0 seconds elapsed)
            self.engine.tick(2.0)

            # Enforce sleep/wake visuals based on metabolic state
            is_sleeping = self.engine.is_sleeping()
            if is_sleeping:
                if self.window.animator.current_state != "sleep":
                    self.window.animator.trigger_sleep(force=True)
            else:
                if self.window.animator.current_state == "sleep":
                    self.window.animator.trigger_wake(force=True)

                # Behavior gating for physical movement
                from core.pet_engine import Event
                event = Event("idle_tick", "system", "Periodic idle tick")
                gating = self.engine.get_behavior_gating(event)
                if gating["allowMovement"]:
                    action = self.engine.select_action(gating)
                    if action != "idle":
                        trigger_method = f"trigger_{action}"
                        if hasattr(self.window.animator, trigger_method):
                            try:
                                getattr(self.window.animator, trigger_method)(force=True)
                            except Exception:
                                pass
        except Exception as e:
            print(f"Error in engine tick: {e}")

    # -------------------------------------------------------------- monitoring
    def _monitor_loop(self):
        last_activity = None
        self._last_click_reaction = time.time()  # don't react to startup clicks
        while self.is_running:
            try:
                for closed_app in self.monitor.poll_closed_windows():
                    self._react_to_window_close(closed_app)
                activity = self.monitor.get_current_activity()
                self._maybe_react_to_keystrokes(activity)
                if (last_activity is None
                        or activity.get("active_app")
                        != last_activity.get("active_app")):
                    self.process_activity_change(activity)
                    last_activity = dict(activity)
                    self._last_click_reaction = time.time()
                elif (self.click_monitor
                      and (time.time() - self._last_click_reaction) > CLICK_REACT_COOLDOWN
                      and self.click_monitor.clicked_since(self._last_click_reaction)):
                    self._last_click_reaction = time.time()
                    self.process_activity_change(activity, reason="click activity")
            except Exception as e:
                print(f"Error in monitor loop: {e}")
            time.sleep(2)

    # --------------------------------------------------------------- lifecycle
    def start(self):
        """Start the desktop pet (must run on the main thread)."""
        print("Starting desktop pet...")
        self.is_running = True

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(True)
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl+C quits cleanly

        self.window = DesktopPetWindow()
        self.window.settings_requested.connect(self.open_settings)
        self.window.quit_requested.connect(self.stop)
        self.apply_runtime_settings()
        self.window.start()
        self.screen_reader.start()  # GUI-thread QTimer; screenshots cached for the brain
        if self.click_monitor:
            self.click_monitor.start()
        if self.keystroke_monitor:
            self.keystroke_monitor.start()  # capture stays off until enabled via config

        # GUI-thread QTimer to tick engine and manage sleep/metabolism
        self._engine_timer = QTimer(self.window)
        self._engine_timer.setInterval(2000)
        self._engine_timer.timeout.connect(self._tick_engine)
        self._engine_timer.start()

        QTimer.singleShot(8000, self._random_bubble)

        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        monitor_thread.start()

        print("Desktop pet is running. Press Ctrl+C to stop.")
        print("Click the pet to shoo it aside; drag it to reposition it.")
        return self.app.exec()

    def stop(self):
        print("Stopping desktop pet...")
        self.is_running = False
        try:
            self.screen_reader.stop()
        except Exception:
            pass
        if self.click_monitor:
            try:
                self.click_monitor.stop()
            except Exception:
                pass
        if self.keystroke_monitor:
            try:
                self.keystroke_monitor.stop()  # also wipes any buffered text
            except Exception:
                pass
        if self.window:
            try:
                self.window.stop()
            except Exception:
                pass
        if self.app:
            try:
                self.app.quit()
            except Exception:
                pass
        print("Desktop pet stopped.")


def main():
    pet = DesktopPet()
    try:
        sys.exit(pet.start())
    except KeyboardInterrupt:
        pet.stop()
        print("Desktop pet exited gracefully.")


if __name__ == "__main__":
    main()
