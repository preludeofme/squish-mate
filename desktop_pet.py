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
    from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
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
from ui.pet_library_dialog import ChangePetDialog
from core.pet_library import get_pet

# Global click detection (optional — pet just won't react to same-page clicks
# if pynput isn't installed).
try:
    from monitors.click_monitor import ClickMonitor
except ImportError as e:
    ClickMonitor = None
    print(f"Click monitoring unavailable: {e}")

# Minimum gap between click-triggered reactions (separate from the
# window-switch trigger, which now bypasses the brain's cooldown entirely).
CLICK_REACT_COOLDOWN = 12.0

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
KEYSTROKE_REACT_COOLDOWN = 25.0
KEYSTROKE_MIN_CHARS = 16
KEYSTROKE_REACT_PROB = 0.55

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

        # Setup Request Queue and Worker
        from core.pet_performance import BoundedRequestQueue, RuntimeAdaptationMonitor, OllamaClient, detect_hardware, recommend_mode_static, PERFORMANCE_MODES
        self.request_queue = BoundedRequestQueue(maxsize=5)
        self.ollama_client = OllamaClient()
        self._currently_loaded_model = None

        # Idle-chatter cadence, driven by config["message_frequency"];
        # concrete values are (re)applied by apply_runtime_settings().
        self._idle_range_s = (25, 70)
        self._idle_prob = 0.30

    # ------------------------------------------------------------------ config
    def load_config(self):
        default_config = {
            "name": "Pip",
            "color": "#C9A5F0",
            # Which core.pet_library.PET_LIBRARY entry is active. Selecting
            # a different pet via the right-click "Change Pet…" dialog
            # updates this plus "color"/"pattern" together; shape, rig, and
            # every animation are identical across all pets.
            "pet_species": "pip",
            "pattern": "plain",
            "shape": "round",
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
            # LLM backend selection. "ollama" (default) runs fully local and
            # needs no key. The others are opt-in hosted alternatives (see
            # core/llm_providers.py) — set an API key in Settings to use
            # them. llm_model_override lets a user pin a specific model id;
            # blank uses each provider's sane default.
            "llm_provider": "ollama",
            "llm_api_key": "",
            "llm_model_override": "",
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
            self.brain.set_provider(
                self.config.get("llm_provider", "ollama"),
                api_key=self.config.get("llm_api_key") or None,
                model_override=self.config.get("llm_model_override") or None,
            )
        if self.keystroke_monitor:
            self.keystroke_monitor.set_enabled(
                bool(self.config.get("keystroke_commentary", False)))

    def open_settings(self):
        dialog = PetSettingsDialog(self.config, engine=self.engine, parent=self.window)
        if dialog.exec():
            vals = dialog.get_values()
            self.config.update(vals["general"])
            self.save_config()
            
            if self.engine:
                with self.engine.lock:
                    self.engine.state["performance"].update(vals["performance"])
                    # If mode is auto, resolve it based on recommendation
                    selected = self.engine.state["performance"]["selectedMode"]
                    if selected == "auto":
                        self.engine.state["performance"]["resolvedMode"] = self.engine.state["performance"]["recommendedMode"]
                    else:
                        self.engine.state["performance"]["resolvedMode"] = selected
                self.engine.save_state(immediate=True)
                
            self.apply_runtime_settings()

    def open_change_pet(self):
        dialog = ChangePetDialog(self.config.get("pet_species", "pip"), parent=self.window)
        if dialog.exec():
            species = get_pet(dialog.selected_id)
            self.config["pet_species"] = species["id"]
            self.config["color"] = species["color"]
            self.config["pattern"] = species["pattern"]
            self.config["shape"] = species["shape"]
            self.save_config()
            self.apply_runtime_settings()
            if self.window:
                self.window.show_bubble(f"Ta-da, I'm {species['name']} now!", duration_ms=2200)

    def _on_pet_clicked(self, interaction_type):
        if self.engine:
            raw_type = "hover_interaction" if interaction_type == "hover" else "direct_interaction"
            self.engine.register_event(
                raw_type=raw_type,
                source="ui",
                raw_summary=f"User performed {interaction_type} on pet",
                is_direct=True
            )

    # ------------------------------------------------------------------- brain
    def process_activity_change(self, activity, reason="activity change"):
        active_app = activity.get("active_app", "unknown")
        window_title = activity.get("window_title", "unknown")
        process_name = activity.get("process_name") or active_app
        print(f"{reason.capitalize()} detected: {active_app}")

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
            print(
                f"[gating] Speech blocked: {gating['reason']} "
                f"(event={event.type} source='{event.source}' topic='{event.topic}' "
                f"summary='{event.summary}')"
            )
            return

        def task():
            # Check model switching
            current_model = self.brain.model if self.brain else "engine_only"
            if current_model != self._currently_loaded_model:
                if self._currently_loaded_model and self._currently_loaded_model != "engine_only":
                    self.ollama_client.unload_model(self._currently_loaded_model)
                self._currently_loaded_model = current_model

            comment = None
            if not self.brain:
                print("[brain] PetBrain not initialized")
            elif self.brain.model == "engine_only":
                pass
            elif not self.brain.available():
                print("[brain] Ollama unreachable right now")
            else:
                try:
                    ctx = {
                        "active_app": activity.get("active_app"),
                        "window_title": activity.get("window_title"),
                        "process_name": process_name,
                        "recent_apps": list(getattr(self.monitor, "apps_seen", []))[-10:],
                    }
                    screenshot_b64 = self.screen_reader.latest()
                    comment = self.brain.think(ctx, force=True, screenshot_b64=screenshot_b64)
                except Exception as e:
                    print(f"Brain error: {e}")

            if not comment:
                comment = random.choice(SAFE_IDLE)

            if self.window:
                self.window.bubble_requested.emit(comment)
            
            msg_text = comment["text"] if isinstance(comment, dict) else str(comment)
            self.interaction_history.append({
                "timestamp": datetime.now().isoformat(),
                "type": "activity_change",
                "app": active_app,
                "message": msg_text,
            })

        req_type = "direct_message" if "click" in reason else "ambient_comment"
        self.request_queue.put({
            "type": req_type,
            "timestamp": time.time(),
            "task": task
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
        if not self.brain:
            return

        # Check if the user is actually typing (meaning a keystroke occurred within the last 15 seconds)
        # If not, return immediately without registering a typing event or suppressing speech.
        if (time.time() - km.get_last_keystroke_time()) > 15.0:
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
            print(f"[gating] Typing commentary blocked: {gating['reason']}")
            return

        now = time.time()
        remaining_cooldown = KEYSTROKE_REACT_COOLDOWN - (now - self._last_keystroke_reaction)
        if remaining_cooldown > 0:
            print(f"[gating] Typing commentary blocked: keystroke_cooldown_{int(remaining_cooldown)}s")
            return
        buffered = km.buffered_length()
        if buffered < KEYSTROKE_MIN_CHARS:
            print(f"[gating] Typing commentary blocked: buffer_too_short_{buffered}/{KEYSTROKE_MIN_CHARS}chars")
            return
        if random.random() > KEYSTROKE_REACT_PROB:
            print("[gating] Typing commentary blocked: probability_roll")
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

        def task():
            current_model = self.brain.model if self.brain else "engine_only"
            if current_model != self._currently_loaded_model:
                if self._currently_loaded_model and self._currently_loaded_model != "engine_only":
                    self.ollama_client.unload_model(self._currently_loaded_model)
                self._currently_loaded_model = current_model

            comment = None
            if self.brain.model == "engine_only":
                pass
            elif not self.brain.available():
                print("[brain] Ollama unreachable right now")
            else:
                try:
                    comment = self.brain.comment_on_typing(text)
                except Exception as e:
                    print(f"Brain error (typing commentary): {e}")

            if comment and self.window:
                self.window.bubble_requested.emit(comment)
            
            msg_text = comment["text"] if isinstance(comment, dict) else str(comment)
            self.interaction_history.append({
                "timestamp": datetime.now().isoformat(),
                "type": "typing_commentary",
                "app": activity.get("active_app"),
                "message": msg_text,
            })

        self.request_queue.put({
            "type": "ambient_comment",
            "timestamp": time.time(),
            "task": task
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
        # Idle comments are periodic/ambient by design, not tied to an
        # activity change, so they're exempt from meaningful-change gating
        # (unlike application/window events, which go through
        # engine.register_event() and earn this flag via the detector).
        event.isMeaningfulChange = True
        gating = self.engine.get_behavior_gating(event)
        if not gating["allowSpeech"]:
            print(f"[gating] Idle speech blocked: {gating['reason']}")
            return

        def task():
            # Check model switching
            current_model = self.brain.model if self.brain else "engine_only"
            if current_model != self._currently_loaded_model:
                if self._currently_loaded_model and self._currently_loaded_model != "engine_only":
                    self.ollama_client.unload_model(self._currently_loaded_model)
                self._currently_loaded_model = current_model

            comment = None
            if self.brain and self.brain.model != "engine_only" and self.brain.available():
                try:
                    comment = self.brain.idle_comment(force=True)
                except Exception as e:
                    print(f"Brain error (idle): {e}")

            if not comment:
                comment = random.choice(SAFE_IDLE)

            if self.window:
                self.window.bubble_requested.emit(comment)

        self.request_queue.put({
            "type": "ambient_comment",
            "timestamp": time.time(),
            "task": task
        })

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
                    if self._currently_loaded_model and self._currently_loaded_model != "engine_only":
                        self.ollama_client.unload_model(self._currently_loaded_model)
            else:
                if self.window.animator.current_state == "sleep":
                    self.window.animator.wake()

                # Behavior gating for physical movement
                from core.pet_engine import Event
                event = Event("idle_tick", "system", "Periodic idle tick")
                gating = self.engine.get_behavior_gating(event)
                if self.config.get("stay_still", False):
                    gating["stayStill"] = True
                if gating["allowMovement"]:
                    # Only select a new action when the pet is currently idle and not moving!
                    if self.window.animator.current_state == "idle" and not self.window.animator.moving:
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
        self.window.change_pet_requested.connect(self.open_change_pet)
        self.window.quit_requested.connect(self.stop)
        self.window.pet_clicked.connect(self._on_pet_clicked)
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

        # Start Request Queue worker thread
        self.queue_worker_thread = threading.Thread(target=self._queue_worker_loop, daemon=True)
        self.queue_worker_thread.start()

        # Run first-run setup after Qt event loop starts
        QTimer.singleShot(1000, self._check_first_run_setup)

        # Setup periodic system adaptation timer (runs every 15 seconds)
        self._adaptation_timer = QTimer(self.window)
        self._adaptation_timer.setInterval(15000)
        self._adaptation_timer.timeout.connect(self._check_runtime_adaptation)
        self._adaptation_timer.start()

        QTimer.singleShot(8000, self._random_bubble)

        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        monitor_thread.start()

        print("Desktop pet is running. Press Ctrl+C to stop.")
        print("Click the pet to shoo it aside; drag it to reposition it.")
        return self.app.exec()

    def _queue_worker_loop(self):
        while self.is_running:
            req = self.request_queue.get()
            if not req:
                time.sleep(0.1)
                continue
            try:
                req["task"]()
            except Exception as e:
                print(f"Error in queue worker task: {e}")

    def _check_first_run_setup(self):
        """First launch setup wizard to select performance mode and download model."""
        if not self.engine:
            return

        perf = self.engine.state.get("performance", {})
        # If recommendedMode is not set, this is the first run after performance system implementation
        if not perf.get("recommendedMode"):
            print("[performance] First-run performance check initiated.")
            from ui.pet_settings import AIDownloadDialog
            hw = detect_hardware()
            rec = recommend_mode_static(hw)
            
            with self.engine.lock:
                perf["recommendedMode"] = rec
                perf["hardwareSummary"] = hw
                perf["selectedMode"] = "auto"
                perf["resolvedMode"] = rec
                self.engine.state["performance"] = perf
            self.engine.save_state(immediate=True)

            cfg = PERFORMANCE_MODES.get(rec)
            if not cfg:
                return
                
            model_name = cfg["model"]
            if not self.ollama_client.available():
                QMessageBox.warning(
                    self.window,
                    "Ollama Not Running",
                    "Ollama is not running on localhost:11434.\n"
                    "Pip will start in Engine-only fallback mode. "
                    "Make sure Ollama is running and configure the performance tier in Settings."
                )
                with self.engine.lock:
                    self.engine.state["performance"]["resolvedMode"] = "engine_only"
                self.engine.save_state(immediate=True)
                return

            if not self.ollama_client.is_model_installed(model_name):
                # Prompt setup dialog
                res = QMessageBox.question(
                    self.window,
                    "First-Run AI Setup",
                    f"Welcome to Squish-Mate!\n\n"
                    f"Based on your system hardware, Pip recommends the '{rec.upper()}' performance tier.\n"
                    f"To enable local AI, Pip needs to download the model:\n{model_name} (~{cfg['minimumFreeDiskGb'] - 2:.1f} GB)\n\n"
                    f"Would you like to download it now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if res == QMessageBox.StandardButton.Yes:
                    from core.pet_performance import ModelManager
                    model_manager = ModelManager(self.ollama_client)
                    if not model_manager.check_disk_space_for_model(rec):
                        QMessageBox.warning(
                            self.window,
                            "Disk Space Warning",
                            "Your home directory might have insufficient disk space. Attempting download anyway."
                        )

                    dlg = AIDownloadDialog(model_manager, model_name, self.window)
                    if dlg.exec() != QDialog.Accepted:
                        # Cancelled/failed -> set resolved mode to engine_only
                        with self.engine.lock:
                            self.engine.state["performance"]["resolvedMode"] = "engine_only"
                        self.engine.save_state(immediate=True)
                        return
                else:
                    # Declined -> set resolved mode to engine_only
                    with self.engine.lock:
                        self.engine.state["performance"]["resolvedMode"] = "engine_only"
                    self.engine.save_state(immediate=True)
                    QMessageBox.information(
                        self.window,
                        "Engine-Only Mode",
                        "Pip will run in Engine-only mode. You can download models and change performance tiers in Settings at any time."
                    )
                    return

            # Model is installed (was already present, or just downloaded) —
            # verify it can actually deliver a response within the latency
            # budget before committing to this tier. A "faster" machine's
            # static hardware specs (RAM/VRAM) can recommend a big model that
            # still cold-loads for 30-100+s in practice; don't let that
            # silently become the active tier unverified.
            self._benchmark_and_enforce_budget(rec, model_name)

    def _benchmark_and_enforce_budget(self, tier, model_name):
        """Run a quick benchmark against `model_name` and step the active
        tier down if it can't meet the response-latency budget — same
        enforcement as the Settings "Run Diagnostic" button, applied
        automatically right after a tier is first activated/downloaded."""
        from core.pet_performance import BenchmarkService, step_down_tier, DEFAULT_LATENCY_BUDGET_S
        from ui.pet_settings import BenchmarkDialog

        bench_service = BenchmarkService(self.ollama_client)
        dlg = BenchmarkDialog(bench_service, model_name, self.window)
        if dlg.exec() != QDialog.Accepted or not dlg.result:
            return  # cancelled/failed to run — leave the tier as-is

        res = dlg.result
        with self.engine.lock:
            perf = self.engine.state["performance"]
            perf.setdefault("benchmarkResults", {})[tier] = res
            perf["benchmarkTimestamp"] = datetime.now().isoformat()

            if res.get("classification") == "failed" and tier != "engine_only":
                lower = step_down_tier(tier)
                perf["selectedMode"] = lower
                perf["resolvedMode"] = lower
                budget = res.get("latency_budget_s", DEFAULT_LATENCY_BUDGET_S)
                QMessageBox.warning(
                    self.window,
                    "Performance Tier Automatically Downgraded",
                    f"'{tier.upper()}' can't reliably respond within the {budget:.0f}s "
                    f"budget (cold load: {res.get('cold_load_time', 0.0):.1f}s, warm "
                    f"latency: {res.get('warm_latency', 0.0):.2f}s).\n\n"
                    f"Automatically stepped down to '{lower.upper()}'. You can change "
                    "this any time in Settings."
                )
        self.engine.save_state(immediate=True)

    def _check_runtime_adaptation(self):
        """Runs periodic system load checks and adapts performance tier under resource pressure."""
        if not self.engine:
            return
        
        from core.pet_performance import RuntimeAdaptationMonitor
        monitor = RuntimeAdaptationMonitor(self.engine, self.ollama_client)
        
        # Capture old fallback state
        old_fallback = self.engine.state.get("performance", {}).get("temporaryFallbackState")
        
        # Apply adaptation
        monitor.apply_temporary_adaptation()
        
        new_fallback = self.engine.state.get("performance", {}).get("temporaryFallbackState")
        if old_fallback != new_fallback:
            if new_fallback:
                print(f"[adaptation] System resource pressure detected ({new_fallback}). Temporarily downshifting performance tier.")
            else:
                print("[adaptation] System resource pressure cleared. Restoring performance tier.")

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
