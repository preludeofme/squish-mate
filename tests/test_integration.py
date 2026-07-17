#!/usr/bin/env python3
"""
Integration tests for the Pip pet architecture, verifying interactions
between PetEngine, PetMemory, and PetBrain with mocked LLM behaviors.
"""

import os
import sys
import unittest
import json
import time
from unittest.mock import patch, MagicMock

# Add project path to python imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pet_engine import PetEngine
from core.pet_memory import PetMemory
from core.pet_brain import PetBrain


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.test_state_path = os.path.expanduser("~/.config/squish-mate/pet_state_integration_test.json")
        if os.path.exists(self.test_state_path):
            os.remove(self.test_state_path)
        self.engine = PetEngine(state_path=self.test_state_path)
        self.memory = PetMemory(engine=self.engine)
        self.brain = PetBrain(memory=self.memory, engine=self.engine, cooldown=0.0)

    def tearDown(self):
        if os.path.exists(self.test_state_path):
            os.remove(self.test_state_path)
        backup_path = self.test_state_path + ".bak"
        if os.path.exists(backup_path):
            os.remove(backup_path)

    def test_memory_delegation(self):
        # Adding fact via compatibility wrapper
        self.memory.add_fact("Likes JavaScript code")
        # Adding note via compatibility wrapper
        self.memory.add_note("Saw terminal window", category="activity")

        # Verify engine state contains these memories
        memories = self.engine.state["memories"]
        self.assertTrue(any(m["summary"] == "Likes JavaScript code" for m in memories))
        self.assertTrue(any("Saw terminal window" in m["summary"] for m in memories))

        # Test memory snippet formatting matching the current topic
        self.engine.state["behavior"]["currentTopic"] = "javascript"
        snippet = self.memory.snippet()
        self.assertIn("Likes JavaScript code", snippet)

    @patch("requests.post")
    def test_brain_think_structured_json(self, mock_post):
        # Setup mock for Ollama successful JSON response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "text": "Code looks neat!",
                    "suggestedEmotion": "curious",
                    "suggestedAction": "wobble"
                })
            }
        }
        mock_post.return_value = mock_response

        # Execute think
        context = {"active_app": "vscode", "window_title": "index.js"}
        res = self.brain.think(context, force=True)

        self.assertIsInstance(res, dict)
        self.assertEqual(res["text"], "Code looks neat!")
        self.assertEqual(res["suggestedEmotion"], "curious")
        self.assertEqual(res["suggestedAction"], "wobble")

    @patch("requests.post")
    def test_brain_think_fallback_on_invalid_json(self, mock_post):
        # Setup mock to return invalid/creepy response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "content": "I am watching you code this Squish-Mate app."
            }
        }
        mock_post.return_value = mock_response

        # Execute think (should fail validation and hit SAFE_FALLBACKS)
        context = {"active_app": "vscode", "window_title": "index.js"}
        res = self.brain.think(context, force=True)

        self.assertIsInstance(res, dict)
        # Should be one of the safe fallbacks
        self.assertNotEqual(res["text"], "I am watching you code this Squish-Mate app.")
        self.assertIn("text", res)
        self.assertIn("suggestedEmotion", res)
        self.assertIn("suggestedAction", res)

    def test_pet_click_wakes_engine(self):
        # Put pet to sleep
        self.engine.force_sleep()
        self.assertTrue(self.engine.is_sleeping())

        # Mock DesktopPet window to avoid launching real GUI in headless test environment
        from desktop_pet import DesktopPet
        
        with patch('desktop_pet.QApplication'), \
             patch('desktop_pet.DesktopPetWindow'), \
             patch('core.pet_performance.OllamaClient'):
             
            pet = DesktopPet()
            pet.engine = self.engine
            
            # Trigger the click handler directly
            pet._on_pet_clicked("click")
            
            # The engine should wake up
            self.assertFalse(self.engine.is_sleeping())

    def test_keystroke_monitor_activity(self):
        from monitors.keystroke_monitor import KeystrokeMonitor
        km = KeystrokeMonitor()
        self.assertEqual(km.get_last_keystroke_time(), 0.0)

        km.set_enabled(True)
        # Mock a key press
        class MockKey:
            char = 'a'
        km._on_press(MockKey())
        self.assertGreater(km.get_last_keystroke_time(), 0.0)

        # Disable should reset timestamp
        km.set_enabled(False)
        self.assertEqual(km.get_last_keystroke_time(), 0.0)

    def test_typing_suppression_bypass(self):
        from desktop_pet import DesktopPet
        from core.pet_engine import Event
        
        with patch('desktop_pet.QApplication'), \
             patch('desktop_pet.DesktopPetWindow'), \
             patch('core.pet_performance.OllamaClient'):
             
            pet = DesktopPet()
            pet.engine = self.engine
            # Enable keystroke commentary
            pet.config["keystroke_commentary"] = True
            
            # Case 1: No typing recently (timestamp is 0.0)
            pet.keystroke_monitor.last_keystroke_time = 0.0
            
            # Calling _maybe_react_to_keystrokes should return early and not register event
            with patch.object(self.engine, 'register_event', wraps=self.engine.register_event) as mock_register:
                pet._maybe_react_to_keystrokes({"active_app": "vscode", "window_title": "index.js"})
                mock_register.assert_not_called()

            # Case 2: User typing active (last keystroke was just now)
            pet.keystroke_monitor.last_keystroke_time = time.time()
            with patch.object(self.engine, 'register_event', wraps=self.engine.register_event) as mock_register:
                pet._maybe_react_to_keystrokes({"active_app": "vscode", "window_title": "index.js"})
                mock_register.assert_called_once()

            # Case 3: Test direct interaction bypasses typing suppression
            from datetime import datetime
            self.engine.state["behavior"]["lastTypingAt"] = datetime.now().isoformat()
            direct_event = Event("direct_interaction", "ui", "Clicked pet", is_direct=True)
            gating_direct = self.engine.get_behavior_gating(direct_event)
            self.assertTrue(gating_direct["allowSpeech"])

            # Case 4: Test typing_continued event bypasses typing suppression
            typing_event = Event("typing_continued", "editor", "Typing", is_direct=False)
            gating_typing = self.engine.get_behavior_gating(typing_event)
            self.assertNotEqual(gating_typing["reason"], "typing_suppression")

    def test_animator_triggers(self):
        from ui.pet_animator import PetAnimator, PetState
        animator = PetAnimator(150, 180)
        animator.last_screen = (0, 0, 800, 600)
        
        # Test trigger_wander
        self.assertFalse(animator.moving)
        animator.trigger_wander(force=True)
        self.assertTrue(animator.moving)
        self.assertEqual(animator.state, PetState.IDLE)
        self.assertTrue(0 <= animator.target_x <= 800 - 150)
        self.assertTrue(60 <= animator.target_y <= 600 - 180)

        # Reset moving
        animator.moving = False
        animator.trigger_screen_traversal(force=True)
        self.assertTrue(animator.moving)

        # Test aliases
        animator.trigger_wobble(force=True)
        self.assertEqual(animator.state, PetState.HOP)

    def test_stay_still_prevention(self):
        from ui.pet_animator import PetAnimator
        animator = PetAnimator(150, 180)
        animator.last_screen = (0, 0, 800, 600)
        animator.stay_still = True
        
        # Test scheduled wander is blocked when stay_still is True
        animator.t = animator._next_wander + 1.0
        animator._update_behavior((0, 0, 800, 600))
        self.assertFalse(animator.moving)

        # Test select_action blocks wander and screen_traversal when stayStill is True
        gating_result = {"stayStill": True}
        action = self.engine.select_action(gating_result)
        self.assertNotIn(action, ("wander", "screen_traversal"))

    def test_waking_and_energy_charge(self):
        # Force sleep
        self.engine.force_sleep()
        self.assertTrue(self.engine.is_sleeping())
        self.engine.state["energy"]["current"] = 10.0
        self.engine.state["needs"]["sleepiness"] = 0.8
        
        # Test click waking (gives 30 energy and wakes up immediately)
        self.engine.register_event("direct_interaction", "ui", "Clicked pet", is_direct=True)
        self.assertFalse(self.engine.is_sleeping())
        self.assertEqual(self.engine.state["energy"]["current"], 40.0)
        self.assertEqual(self.engine.state["needs"]["sleepiness"], 0.2)

        # Force sleep again
        self.engine.force_sleep()
        self.assertTrue(self.engine.is_sleeping())
        self.engine.state["energy"]["current"] = 10.0
        self.engine.state["needs"]["sleepiness"] = 0.8

        # Hovering should add 2 energy and reduce sleepiness but not wake up if below 80.0
        self.engine.register_event("hover_interaction", "ui", "Hovered pet", is_direct=True)
        self.assertTrue(self.engine.is_sleeping())
        self.assertEqual(self.engine.state["energy"]["current"], 12.0)
        self.assertEqual(self.engine.state["needs"]["sleepiness"], 0.78)

        # Hovering enough to charge energy to >= 80.0 should wake up
        self.engine.state["energy"]["current"] = 79.0
        self.engine.register_event("hover_interaction", "ui", "Hovered pet", is_direct=True)
        self.assertFalse(self.engine.is_sleeping())


if __name__ == "__main__":
    import time
    unittest.main()
