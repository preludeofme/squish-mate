#!/usr/bin/env python3
"""
pet_memory.py — Compatibility wrapper that routes all memory storage,
retrieval, and deduplication to the authoritative PetEngine.
"""

import os
import threading

DEFAULT_PATH = os.path.expanduser("~/.config/squish-mate/memory.md")
MAX_CHARS = 12000

class PetMemory:
    def __init__(self, path=DEFAULT_PATH, max_chars=MAX_CHARS, summarizer=None, engine=None):
        self.path = os.path.expanduser(path)
        self.max_chars = max_chars
        self.summarizer = summarizer
        self.engine = engine
        self._lock = threading.Lock()

    def read(self):
        if self.engine:
            with self.engine.lock:
                memories = self.engine.state.get("memories", [])
                lines = ["# Desktop Pet Memory\n", "## Stable facts & preferences"]
                for m in memories:
                    if m.get("type") == "user_provided_fact":
                        lines.append(f"- {m['summary']}")
                lines.append("\n## Recent context")
                for m in memories:
                    if m.get("type") != "user_provided_fact":
                        lines.append(f"- {m['summary']}")
                return "\n".join(lines)
        return "# Desktop Pet Memory\n\n## Stable facts & preferences\n\n## Recent context\n"

    def snippet(self, max_chars=1500):
        """Retrieve relevant memories matching the current engine topic."""
        if self.engine:
            topic = self.engine.state["behavior"]["currentTopic"]
            relevant = self.engine.retrieve_relevant_memories(topic)
            if relevant:
                return "\n".join(f"- {r}" for r in relevant)
        return ""

    def add_note(self, note, category="observation"):
        if self.engine:
            self.engine.add_explicit_memory(note, topic=category)

    def add_fact(self, fact):
        if self.engine:
            self.engine.add_explicit_memory(fact, topic="user_provided")

    def _compact(self, text):
        # Handled deterministically inside the engine's memory system
        return text
