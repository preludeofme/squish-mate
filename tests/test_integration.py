#!/usr/bin/env python3
"""
Integration tests for the Pip pet architecture, verifying interactions
between PetEngine, PetMemory, and PetBrain with mocked LLM behaviors.
"""

import os
import sys
import unittest
import json
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


if __name__ == "__main__":
    unittest.main()
