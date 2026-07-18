#!/usr/bin/env python3
"""
bridge.py — Thin JSON-in/JSON-out facade over the pure-Python behavior
engine (PetEngine/PetBrain/PetMemory), built for embedding this package
into non-desktop hosts. The primary consumer is the Android app (see
`docs/android_plan.md`), which calls into this module through Chaquopy;
it is equally usable by any other host (a future web port, a CLI, tests)
that wants engine behavior without wiring PetEngine/PetBrain/PetMemory
together itself.

Contract:
  - Every function takes/returns plain strings (JSON in, JSON out) or
    JSON-serializable primitives. No host-specific objects ever cross
    this boundary in either direction.
  - This module imports nothing platform-specific (no Qt, no Android
    APIs) — it only depends on the rest of `core/`, matching the rest of
    the package.
  - `desktop_pet.py` does NOT use this module; it talks to
    PetEngine/PetBrain/PetMemory directly. This facade exists purely for
    embedding into other hosts.

Session model: a single module-level session (not a class the host
constructs) because the bridge functions themselves are the public
surface. `init()` may be called again to reset the session (e.g. on app
restart) — it does not need an explicit prior `shutdown()`.
"""

import json
import os
import random
import threading
import time

from core.pet_engine import PetEngine, Event
from core.pet_memory import PetMemory
from core.pet_brain import PetBrain, SAFE_FALLBACKS

# Mirrors `ui/pet_settings.py`'s MESSAGE_FREQUENCY_PRESETS (idle_prob/
# brain_cooldown only — idle_range_s is a desktop QTimer scheduling detail
# that has no bridge equivalent; the host schedules its own idle ticks).
# Duplicated rather than imported because `ui/` is PySide6-only and `core/`
# must stay free of Qt imports for non-desktop hosts.
MESSAGE_FREQUENCY_PRESETS = {
    "quiet":  {"idle_prob": 0.15, "brain_cooldown": 60.0},
    "normal": {"idle_prob": 0.30, "brain_cooldown": 30.0},
    "chatty": {"idle_prob": 0.55, "brain_cooldown": 12.0},
}

# App-level config shape, matching desktop `pet_config.json`'s general
# settings (see `desktop_pet.py:load_config`'s `default_config`). Fields
# with no bridge-side meaning (e.g. UI-only "color"/"pattern"/"shape") are
# accepted and ignored — the host is free to pass its full config dict.
DEFAULT_PET_CONFIG = {
    "name": "Pip",
    "personality_traits": [],
    "initial_prompt": "",
    "message_frequency": "normal",
    "llm_provider": "ollama",
    "llm_api_key": "",
    "llm_model_override": "",
    "llm_base_url": "",
    "system_prompt": "",
}

_INTERACTION_KINDS = {"tap", "drag", "fling", "longpress"}


class BridgeNotInitializedError(RuntimeError):
    """Raised when a bridge call is made before `init()`."""


class _Session:
    def __init__(self):
        self.lock = threading.RLock()
        self.engine = None
        self.brain = None
        self.memory = None
        self.pet_config = dict(DEFAULT_PET_CONFIG)
        self.last_tick_ms = None


_session = _Session()


def _require():
    if _session.engine is None:
        raise BridgeNotInitializedError("bridge.init() must be called before other bridge calls")
    return _session


def _apply_pet_config_locked(cfg):
    """Push the app-level config dict into the brain, mirroring
    `desktop_pet.py`'s `apply_runtime_settings()` (minus window/animator/
    keystroke wiring, which are host-specific UI concerns outside core/)."""
    _session.pet_config = {**DEFAULT_PET_CONFIG, **cfg}
    brain = _session.brain
    if brain is None:
        return
    freq = MESSAGE_FREQUENCY_PRESETS.get(
        _session.pet_config.get("message_frequency", "normal"),
        MESSAGE_FREQUENCY_PRESETS["normal"])
    brain.cooldown = freq["brain_cooldown"]
    brain.set_persona(
        _session.pet_config.get("personality_traits", []),
        _session.pet_config.get("initial_prompt", ""))
    brain.set_system_prompt(_session.pet_config.get("system_prompt", ""))
    brain.set_provider(
        _session.pet_config.get("llm_provider", "ollama"),
        api_key=_session.pet_config.get("llm_api_key") or None,
        model_override=_session.pet_config.get("llm_model_override") or None,
        base_url=_session.pet_config.get("llm_base_url") or None,
    )


def _brain_available_locked():
    brain = _session.brain
    if brain is None or brain.model == "engine_only":
        return False
    return brain.available()


def _speak_or_fallback(thinker):
    """Run a brain call and always return a usable comment dict
    (`{"text", "suggestedEmotion", "suggestedAction"}`), falling back to a
    random `SAFE_FALLBACKS` line whenever the brain is unavailable
    entirely (no key/no network) — mirrors the desktop app's "brain not
    available" guard, which skips calling the brain rather than letting it
    fail. `PetBrain.think()`/`idle_comment()` already fall back internally
    on validation failure, so this only needs to guard the "don't even
    try" case and unexpected exceptions."""
    if not _brain_available_locked():
        return random.choice(SAFE_FALLBACKS)
    try:
        return thinker() or random.choice(SAFE_FALLBACKS)
    except Exception:
        return random.choice(SAFE_FALLBACKS)


def _state_snapshot(speech=None, action="idle"):
    engine = _session.engine
    state = engine.state
    return {
        "speech": speech,
        "emotion": state["emotion"]["current"],
        "action": action,
        "sleeping": engine.is_sleeping(),
        "energy": state["energy"]["current"],
    }


def init(storage_dir, config_json=""):
    """Create a fresh embedded engine/brain/memory session rooted at
    `storage_dir` — an app-private, writable directory (e.g. Android's
    `context.filesDir`). Never pass the desktop app's `~/.config` path
    here; PetEngine only skips its legacy-directory migration when given a
    non-default `state_path`, but a mobile/embedded host should still own
    a directory no other process touches.

    `config_json` is the same shape as desktop `pet_config.json`'s general
    settings (see `DEFAULT_PET_CONFIG`); pass "" or "{}" for defaults.
    Safe to call again to reset the session (e.g. app restart)."""
    with _session.lock:
        os.makedirs(storage_dir, exist_ok=True)
        state_path = os.path.join(storage_dir, "pet_state.json")
        _session.engine = PetEngine(state_path=state_path)
        _session.memory = PetMemory(engine=_session.engine)
        _session.brain = PetBrain(memory=_session.memory, engine=_session.engine)
        _session.memory.summarizer = _session.brain.summarize
        _session.last_tick_ms = None
        cfg = json.loads(config_json) if config_json else {}
        _apply_pet_config_locked(cfg)


def update_config(config_json):
    """Live-update the app-level config (e.g. after a Settings screen
    save) without recreating the engine/state."""
    with _session.lock:
        _require()
        cfg = json.loads(config_json) if config_json else {}
        _apply_pet_config_locked(cfg)


def tick(now_ms=None):
    """Advance the metabolic engine by one step and, if awake and gating
    allows movement, select a physical action. Matches desktop's fixed
    2.0s `QTimer` cadence by default; if `now_ms` (host epoch millis) is
    supplied on successive calls, the actual elapsed time between calls is
    used instead — useful for a host whose tick scheduling isn't a strict
    fixed interval (e.g. throttled while backgrounded). Returns the same
    JSON shape as `on_activity`/`on_interaction`."""
    session = _require()
    engine = session.engine

    with session.lock:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        prev = session.last_tick_ms
        dt_seconds = 2.0 if prev is None else max(0.0, (now_ms - prev) / 1000.0)
        session.last_tick_ms = now_ms

    engine.tick(dt_seconds)

    if engine.is_sleeping():
        return json.dumps(_state_snapshot(action="sleep"))

    event = Event("idle_tick", "system", "Periodic idle tick")
    gating = engine.get_behavior_gating(event)
    action = "idle"
    if gating["allowMovement"]:
        action = engine.select_action(gating)

    return json.dumps(_state_snapshot(action=action))


def on_activity(event_json):
    """Feed an activity-context event (foreground app changed, etc.) into
    the engine and, if gating allows speech, get a reaction from the
    brain. `event_json` shape: `{"active_app", "window_title",
    "process_name", "reason", "recent_apps"}` — all optional; Android's
    shallower `UsageStatsManager` context (package + app label, no window
    title) fits the same fields with `window_title` simply omitted."""
    session = _require()
    engine = session.engine
    payload = json.loads(event_json) if event_json else {}

    active_app = payload.get("active_app") or "unknown"
    window_title = payload.get("window_title") or active_app
    process_name = payload.get("process_name") or active_app
    reason = payload.get("reason") or "activity change"

    event_type = "application_changed"
    if "click" in reason:
        event_type = "click_activity"
    elif "typing" in reason:
        event_type = "typing_continued"

    event = engine.register_event(
        raw_type=event_type,
        source=process_name,
        raw_summary=window_title,
        topic=engine.detector.guess_topic(active_app, window_title),
    )

    gating = engine.get_behavior_gating(event)
    if not gating["allowSpeech"]:
        return json.dumps(_state_snapshot(action=gating.get("suggestedAction", "idle")))

    ctx = {
        "active_app": active_app,
        "window_title": window_title,
        "process_name": process_name,
        "recent_apps": payload.get("recent_apps") or [],
    }
    comment = _speak_or_fallback(lambda: session.brain.think(ctx, force=True))
    return json.dumps(_state_snapshot(
        speech=comment.get("text"),
        action=comment.get("suggestedAction", "idle"),
    ))


def on_interaction(kind):
    """Register a direct touch interaction with the pet itself (tap/drag/
    fling/long-press — Android's equivalent of the desktop click monitor).
    Purely feeds the engine's needs/relationship/energy state and wake
    logic; like desktop's own click handler, it does NOT call the brain —
    the host's native animator reacts to the touch visually on its own."""
    session = _require()
    engine = session.engine
    kind = (kind or "tap").strip().lower()
    if kind not in _INTERACTION_KINDS:
        kind = "tap"
    engine.register_event(
        raw_type="direct_interaction",
        source="ui",
        raw_summary=f"User performed {kind} on pet",
        is_direct=True,
    )
    return json.dumps(_state_snapshot())


def idle_comment():
    """Ask the brain for an ambient idle line (no triggering event) —
    the bridge equivalent of desktop's periodic `_trigger_idle_comment`.
    The host decides when/how often to call this (e.g. driven by
    `MESSAGE_FREQUENCY_PRESETS[...]["idle_prob"]` on its own timer)."""
    session = _require()
    engine = session.engine

    event = Event("idle_comment", "system", "Periodic idle comment")
    event.isMeaningfulChange = True
    gating = engine.get_behavior_gating(event)
    if not gating["allowSpeech"]:
        return json.dumps(_state_snapshot(action=gating.get("suggestedAction", "idle")))

    comment = _speak_or_fallback(lambda: session.brain.idle_comment(force=True))
    return json.dumps(_state_snapshot(
        speech=comment.get("text"),
        action=comment.get("suggestedAction", "idle"),
    ))


def get_state():
    """Full needs/energy/relationship snapshot for a settings/status UI."""
    session = _require()
    engine = session.engine
    state = engine.state
    return json.dumps({
        "emotion": state["emotion"]["current"],
        "energy": state["energy"]["current"],
        "energyMaximum": state["energy"]["maximum"],
        "needs": dict(state["needs"]),
        "relationship": dict(state["relationship"]),
        "growth": dict(state["growth"]),
        "sleeping": engine.is_sleeping(),
        "currentAction": state["behavior"]["currentAction"],
        "currentTopic": state["behavior"]["currentTopic"],
    })


def shutdown():
    """Flush state to disk and drop the session. Safe to call even if
    `init()` was never called."""
    with _session.lock:
        if _session.engine is not None:
            try:
                _session.engine.save_state(immediate=True)
            except Exception:
                pass
        _session.engine = None
        _session.brain = None
        _session.memory = None
        _session.pet_config = dict(DEFAULT_PET_CONFIG)
        _session.last_tick_ms = None
