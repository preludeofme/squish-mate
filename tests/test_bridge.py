#!/usr/bin/env python3
"""
Unit tests for `core/bridge.py` — the JSON facade used to embed the engine
into non-desktop hosts (see docs/android_plan.md). Exercises the full
public API headlessly, including a simulated day of ticks + activity
events, without any network access (the brain is configured with a
key-less hosted provider so `available()` short-circuits instead of
attempting a real network call).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bridge


# No API key -> PetBrain.available() returns False immediately (no network
# round-trip), so every bridge call in these tests exercises the
# SAFE_FALLBACKS path deterministically and fast.
NO_NETWORK_CONFIG = json.dumps({
    "name": "TestPip",
    "llm_provider": "openai",
    "llm_api_key": "",
    "message_frequency": "chatty",
})


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.storage_dir = tempfile.mkdtemp(prefix="squish-mate-bridge-test-")

    def tearDown(self):
        bridge.shutdown()
        shutil.rmtree(self.storage_dir, ignore_errors=True)

    def test_requires_init_before_calls(self):
        bridge.shutdown()  # ensure no session leaks from another test
        with self.assertRaises(bridge.BridgeNotInitializedError):
            bridge.tick(0)
        with self.assertRaises(bridge.BridgeNotInitializedError):
            bridge.get_state()

    def test_init_creates_state_file(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        self.assertTrue(os.path.exists(os.path.join(self.storage_dir, "pet_state.json")))

    def test_init_never_touches_desktop_config_dir(self):
        desktop_dir = os.path.expanduser("~/.config/squish-mate")
        existed_before = os.path.exists(desktop_dir)
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        if not existed_before:
            self.assertFalse(os.path.exists(desktop_dir))

    def test_tick_returns_valid_snapshot(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        raw = bridge.tick(1_000)
        snap = json.loads(raw)
        for key in ("speech", "emotion", "action", "sleeping", "energy"):
            self.assertIn(key, snap)
        self.assertIsNone(snap["speech"])  # tick never speaks, only acts

    def test_tick_uses_supplied_clock_for_dt(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        bridge.tick(0)
        self.assertEqual(bridge._session.last_tick_ms, 0)
        bridge.tick(5_000)
        self.assertEqual(bridge._session.last_tick_ms, 5_000)
        # A large forward jump (e.g. host was backgrounded for an hour) must
        # not raise and must still yield a valid snapshot.
        snap = json.loads(bridge.tick(60 * 60 * 1000 + 5_000))
        self.assertIn(snap["action"], (
            "idle", "sleep", "wobble", "peek", "wave", "hop", "bounce",
            "screen_traversal", "excited", "yawn", "stretch", "dance",
            "somersault", "eat", "wander",
        ))

    def test_on_activity_falls_back_without_network(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        # A freshly created engine sets lastSpeechAt to "now", so the very
        # first event within the global speech cooldown window would
        # legitimately be gated silent — push it into the past so this test
        # exercises the "gating allows speech" path deterministically.
        bridge._session.engine.state["behavior"]["lastSpeechAt"] = "2000-01-01T00:00:00"
        raw = bridge.on_activity(json.dumps({
            "active_app": "vscode",
            "window_title": "bridge.py",
            "process_name": "vscode",
            "reason": "activity change",
        }))
        snap = json.loads(raw)
        # First event of a session is a meaningful topic change -> speech
        # allowed -> brain unavailable -> a SAFE_FALLBACKS line.
        self.assertIsInstance(snap["speech"], str)
        self.assertTrue(len(snap["speech"]) > 0)

    def test_on_interaction_never_calls_brain(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        raw = bridge.on_interaction("tap")
        snap = json.loads(raw)
        self.assertIsNone(snap["speech"])

    def test_on_interaction_unknown_kind_defaults_to_tap(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        raw = bridge.on_interaction("not_a_real_kind")
        snap = json.loads(raw)
        self.assertIn("emotion", snap)

    def test_on_interaction_wakes_sleeping_pet(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        bridge._session.engine.force_sleep()
        self.assertTrue(bridge._session.engine.is_sleeping())
        bridge.on_interaction("longpress")
        self.assertFalse(bridge._session.engine.is_sleeping())

    def test_idle_comment_falls_back_without_network(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        raw = bridge.idle_comment()
        snap = json.loads(raw)
        self.assertIn("speech", snap)

    def test_update_config_applies_persona_live(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        bridge.update_config(json.dumps({
            "llm_provider": "openai",
            "llm_api_key": "",
            "personality_traits": ["sarcastic", "sleepy"],
            "message_frequency": "quiet",
        }))
        self.assertIn("sarcastic", bridge._session.brain._persona_extra)
        self.assertEqual(bridge._session.brain.cooldown, 60.0)

    def test_get_state_shape(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        state = json.loads(bridge.get_state())
        for key in ("emotion", "energy", "energyMaximum", "needs", "relationship",
                    "growth", "sleeping", "currentAction", "currentTopic"):
            self.assertIn(key, state)

    def test_shutdown_flushes_and_resets_session(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        state_path = os.path.join(self.storage_dir, "pet_state.json")
        bridge.shutdown()
        self.assertTrue(os.path.exists(state_path))
        with self.assertRaises(bridge.BridgeNotInitializedError):
            bridge.get_state()

    def test_reinit_resets_session_cleanly(self):
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        bridge.on_interaction("tap")
        other_dir = tempfile.mkdtemp(prefix="squish-mate-bridge-test-2-")
        try:
            bridge.init(other_dir, NO_NETWORK_CONFIG)
            self.assertTrue(os.path.exists(os.path.join(other_dir, "pet_state.json")))
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)

    def test_simulated_day_of_ticks_and_activity_headless(self):
        """Exit-criterion smoke test from docs/android_plan.md Phase 0:
        simulate roughly a day of engine ticks interleaved with activity
        events with no crashes, producing valid JSON throughout."""
        bridge.init(self.storage_dir, NO_NETWORK_CONFIG)
        apps = ["vscode", "firefox", "discord", "steam", "unknown_app"]
        now_ms = 0
        for i in range(200):
            now_ms += 2_000  # 2s engine-tick cadence
            snap = json.loads(bridge.tick(now_ms))
            self.assertIn(snap["action"], (
                "idle", "sleep", "wobble", "peek", "wave", "hop", "bounce",
                "screen_traversal", "excited", "yawn", "stretch", "dance",
                "somersault", "eat", "wander",
            ))
            if i % 7 == 0:
                app = apps[i % len(apps)]
                json.loads(bridge.on_activity(json.dumps({
                    "active_app": app,
                    "window_title": f"{app} window {i}",
                    "process_name": app,
                    "reason": "activity change",
                })))
            if i % 11 == 0:
                json.loads(bridge.on_interaction("tap"))
            if i % 30 == 0:
                json.loads(bridge.idle_comment())
        # Engine survived a simulated day without raising.
        self.assertIsNotNone(bridge._session.engine.state)

    def test_ondevice_generator_wired_into_brain(self):
        """docs/android_plan.md §5.4 item 3 — provider 'ondevice' has no
        HTTP call of its own; PetBridge.kt registers a Kotlin-object
        callback via set_ondevice_generator(). Simulate that with a plain
        Python object exposing .generate(...), matching the shape Chaquopy
        would hand PetBrain._chat_ondevice() for a real Kotlin object."""
        class FakeOnDeviceEngine:
            def __init__(self):
                self.calls = []

            def generate(self, system, user, num_predict):
                self.calls.append((system, user, num_predict))
                return "a real on-device reply"

        fake_engine = FakeOnDeviceEngine()
        bridge.init(self.storage_dir, json.dumps({
            "name": "TestPip",
            "llm_provider": "ondevice",
            "message_frequency": "chatty",
        }))
        bridge.set_ondevice_generator(fake_engine)
        bridge.update_config(json.dumps({
            "name": "TestPip",
            "llm_provider": "ondevice",
            "message_frequency": "chatty",
        }))

        self.assertTrue(bridge._session.brain.available())
        text = bridge._session.brain.think({"active_app": "TestApp"}, force=True)
        self.assertEqual(text["text"], "a real on-device reply")
        self.assertEqual(len(fake_engine.calls), 1)

    def test_ondevice_generator_survives_reinit(self):
        """A fresh init() (e.g. app restart) replaces `brain`, but the
        host's already-loaded on-device model/callback is still valid and
        should carry over without the host having to re-register it."""
        class FakeOnDeviceEngine:
            def generate(self, system, user, num_predict):
                return "still here after reinit"

        bridge.init(self.storage_dir, json.dumps({"llm_provider": "ondevice"}))
        bridge.set_ondevice_generator(FakeOnDeviceEngine())
        bridge.init(self.storage_dir, json.dumps({"llm_provider": "ondevice"}))

        self.assertTrue(bridge._session.brain.available())

    def test_ondevice_generator_failure_falls_back_safely(self):
        """A raising/broken callback must never surface as a bridge
        exception — same 'always get a usable line' contract as network
        failures for the hosted providers."""
        class BrokenOnDeviceEngine:
            def generate(self, system, user, num_predict):
                raise RuntimeError("native inference crashed")

        bridge.init(self.storage_dir, json.dumps({
            "name": "TestPip", "llm_provider": "ondevice", "message_frequency": "chatty",
        }))
        bridge.set_ondevice_generator(BrokenOnDeviceEngine())
        bridge.update_config(json.dumps({
            "name": "TestPip", "llm_provider": "ondevice", "message_frequency": "chatty",
        }))

        # Call the brain directly (bypassing engine gating, which can
        # legitimately withhold speech for reasons unrelated to this test —
        # e.g. cooldowns) to isolate "does a broken on-device callback still
        # yield a usable fallback line."
        comment = bridge._session.brain.idle_comment(force=True)
        self.assertIsInstance(comment["text"], str)
        self.assertTrue(len(comment["text"]) > 0)


if __name__ == "__main__":
    unittest.main()
