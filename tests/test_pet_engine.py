#!/usr/bin/env python3
"""
Unit tests for the PetEngine behavior, persistence, metabolic needs, memory, and LLM boundary logic.
"""

import os
import sys
import unittest
import json
import time
from datetime import datetime, timedelta

# Add project path to python imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pet_engine import PetEngine, PrivacyFilter, Event, check_similarity


class TestPetEngine(unittest.TestCase):
    def setUp(self):
        self.test_state_path = os.path.expanduser("~/.config/squish-mate/pet_state_test.json")
        if os.path.exists(self.test_state_path):
            os.remove(self.test_state_path)
        self.engine = PetEngine(state_path=self.test_state_path)

    def tearDown(self):
        if os.path.exists(self.test_state_path):
            os.remove(self.test_state_path)
        backup_path = self.test_state_path + ".bak"
        if os.path.exists(backup_path):
            os.remove(backup_path)

    # 1. Event Normalization and Privacy Filtering
    def test_privacy_filtering(self):
        raw_text = "My API key is AIzaSyD1234567890abcdef and password is 'supersecret'"
        filtered = PrivacyFilter.filter_text(raw_text)
        self.assertIn("filtered", filtered.lower())
        self.assertNotIn("AIzaSyD1234567890abcdef", filtered)
        self.assertNotIn("supersecret", filtered)

        raw_email = "Please contact me at admin@test.com"
        filtered_email = PrivacyFilter.filter_text(raw_email)
        self.assertIn("[email filtered]", filtered_email)
        self.assertNotIn("admin@test.com", filtered_email)

    def test_event_normalization(self):
        evt = self.engine.register_event("build_failed", "terminal", "Failed to build: API_KEY=abc123xyz")
        self.assertEqual(evt.type, "build_failed")
        self.assertEqual(evt.source, "terminal")
        self.assertNotIn("abc123xyz", evt.summary)

    # 2. Gating and Cooldowns
    def test_speech_gating_cooldowns(self):
        event = Event("application_changed", "vscode", "Editing main file", topic="coding")
        event.isMeaningfulChange = True

        # First speech attempt should be approved if cooldown elapsed
        self.engine.state["behavior"]["lastSpeechAt"] = (datetime.now() - timedelta(seconds=100)).isoformat()
        gating = self.engine.get_behavior_gating(event)
        self.assertTrue(gating["allowSpeech"], gating.get("reason"))

        # Triggering speech now should update lastSpeechAt (via LLM validation completion)
        validated = self.engine.validate_llm_response({"text": "Hello coding friend!"})
        self.assertIsNotNone(validated)

        # Immediate next gating request should fail due to global cooldown
        gating2 = self.engine.get_behavior_gating(event)
        self.assertFalse(gating2["allowSpeech"])
        self.assertIn("global_cooldown", gating2["reason"])

    def test_typing_suppression(self):
        self.engine.register_event("typing_started", "editor", "User started typing")
        event = Event("application_changed", "vscode", "Editing main file", topic="coding")
        event.isMeaningfulChange = True
        
        gating = self.engine.get_behavior_gating(event)
        self.assertFalse(gating["allowSpeech"])
        self.assertEqual(gating["reason"], "typing_suppression")

    # 3. Energy and Sleep
    def test_energy_drain_and_costs(self):
        initial_energy = self.engine.state["energy"]["current"]
        self.assertEqual(initial_energy, 100.0)

        # Tick 10 minutes awake
        self.engine.tick(600.0)
        drained_energy = self.engine.state["energy"]["current"]
        expected_drain = self.engine.config["energyPassiveDrainRate"] * 10.0
        self.assertAlmostEqual(initial_energy - drained_energy, expected_drain)

        # Triggering an action should consume energy
        self.engine.state["emotion"]["current"] = "happy"
        self.engine.state["energy"]["current"] = 80.0
        gating = {"allowMovement": True}
        action = self.engine.select_action(gating)
        self.assertNotEqual(action, "idle")
        final_energy = self.engine.state["energy"]["current"]
        self.assertTrue(final_energy < 80.0)

    def test_sleep_and_wake(self):
        # Force Sleepiness
        self.engine.state["energy"]["current"] = 5.0
        self.engine.tick(2.0)  # should trigger sleep
        self.assertTrue(self.engine.is_sleeping())
        self.assertEqual(self.engine.state["emotion"]["current"], "sleepy")

        # Set energy higher so it doesn't immediately become sleepy again on wake
        self.engine.state["energy"]["current"] = 50.0
        self.engine.save_state(immediate=True)

        # Wake on direct interaction
        self.engine.register_event("direct_message", "ui", "Hello Pip!", is_direct=True)
        self.assertFalse(self.engine.is_sleeping())
        self.assertEqual(self.engine.state["emotion"]["current"], "happy")

    def test_offline_time(self):
        # Close awake, open 5 hours later
        self.engine.state["energy"]["current"] = 80.0
        self.engine.state["lastActiveAt"] = (datetime.now() - timedelta(hours=5)).isoformat()
        self.engine.save_state(immediate=True)
        
        # Reloading should trigger offline restoration/drain
        self.engine.load_state()
        final_energy = self.engine.state["energy"]["current"]
        # Awake offline should drain, but capped to not reach 0 (holds min 15)
        self.assertTrue(final_energy < 80.0)
        self.assertTrue(final_energy >= 15.0)

    # 4. Memories
    def test_memory_candidates_and_deduplication(self):
        # Create a memory candidate (high importance)
        self.engine.register_event("build_failed", "terminal", "TypeScript build failed with 2 errors", importance=0.8)
        self.assertEqual(len(self.engine.state["memories"]), 1)
        self.assertEqual(self.engine.state["memories"][0]["summary"], "TypeScript build failed with 2 errors")

        # Submit duplicate event
        self.engine.register_event("build_failed", "terminal", "TypeScript build failed with 2 errors", importance=0.8)
        # Should not duplicate, but reinforce confidence/recall
        self.assertEqual(len(self.engine.state["memories"]), 1)

    # 5. LLM Validation Boundaries
    def test_llm_response_validation(self):
        # Invalid anatomy check
        invalid_resp = {"text": "I will stretch my furry legs and scratch my paws.", "suggestedEmotion": "happy"}
        validated = self.engine.validate_llm_response(invalid_resp)
        self.assertIsNone(validated)

        # Surveillance language check
        surveillance_resp = {"text": "I am always here watching you code.", "suggestedEmotion": "neutral"}
        validated2 = self.engine.validate_llm_response(surveillance_resp)
        self.assertIsNone(validated2)

        # Valid response
        valid_resp = {"text": "That code looks interesting!", "suggestedEmotion": "curious"}
        validated3 = self.engine.validate_llm_response(valid_resp)
        self.assertIsNotNone(validated3)
        self.assertEqual(validated3["text"], "That code looks interesting!")
        self.assertEqual(validated3["suggestedEmotion"], "curious")

    # 6. Persistent State Corruption & Backup Recovery
    def test_state_corruption_recovery(self):
        # Corrupt the state file manually
        with open(self.test_state_path, "w") as f:
            f.write("{invalid_json: true")

        # Reloading should fall back to backup or default state gracefully without crashing
        self.engine.load_state()
        self.assertIsNotNone(self.engine.state)
        self.assertEqual(self.engine.state["petId"], "pip")


if __name__ == "__main__":
    unittest.main()
