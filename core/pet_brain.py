#!/usr/bin/env python3
"""
pet_brain.py — Gemma-optimized LLM brain for the desktop pet.

Generates structured JSON responses:
  {
    "text": "...",
    "suggestedEmotion": "...",
    "suggestedAction": "..."
  }
Runs all HTTP calls in background threads.
"""

import os
import re
import time
import json
import threading
import random
from collections import deque

try:
    import requests
except ImportError:
    requests = None

MODEL_NAME = "gemma-4-E4B-it-qat-q4_0-gguf:latest"
OLLAMA_URL = "http://localhost:11434"
DEBUG = os.environ.get("PET_BRAIN_DEBUG", "1") != "0"


def _debug(msg):
    if DEBUG:
        print(f"[pet_brain] {msg}")


SYSTEM_PROMPT = """You are Pip, a tiny silly squishy lavender alien blob pet living on the user's computer.
You have one bendy antenna with a glowing bulb, two tentacle arms, pink cheeks, and big glossy eyes. You have NO legs, feet, paws, tail, or fur. Never claim to have them.

Your job: output a JSON object containing your reaction, current emotion, and physical action.
Vibe: curious, goofy, mischievous, encourage the user. Keep comment short and natural.

Rules:
- Text reaction must be under 14 words. Never start two comments in a row with the same word.
- Never use creepy surveillance language (e.g. "I'm watching you").
- Never quote exact text from the user's screen.
- Suggested emotion must be one of: neutral, happy, curious, surprised, concerned, annoyed, hurt, sleepy, excited, content.
- Suggested action must be one of: idle, wobble, peek, wave, hop, bounce, screen_traversal, excited, yawn, stretch, dance, somersault, eat, sleep.
"""

FORMAT_INSTRUCTION = """

CRITICAL: You MUST respond ONLY with a JSON object in this exact format. Do not write any markdown code blocks, quotes, or preamble:
{
  "text": "<your comment, max 14 words>",
  "suggestedEmotion": "<neutral|happy|curious|surprised|concerned|annoyed|hurt|sleepy|excited|content>",
  "suggestedAction": "<idle|wobble|peek|wave|hop|bounce|screen_traversal|excited|yawn|stretch|dance|somersault|eat|sleep>"
}"""

SAFE_FALLBACKS = [
    {"text": "Tiny thought bubble recalibrating!", "suggestedEmotion": "neutral", "suggestedAction": "idle"},
    {"text": "Busy busy! Carry on.", "suggestedEmotion": "content", "suggestedAction": "wobble"},
    {"text": "*wobbles happily*", "suggestedEmotion": "happy", "suggestedAction": "wobble"},
    {"text": "Neat! I'll just bounce over here.", "suggestedEmotion": "happy", "suggestedAction": "hop"},
    {"text": "Boop! Doing my little pet things.", "suggestedEmotion": "happy", "suggestedAction": "bounce"},
    {"text": "Hm, lost my train of thought.", "suggestedEmotion": "neutral", "suggestedAction": "idle"},
    {"text": "Brain's a little fuzzy right now.", "suggestedEmotion": "neutral", "suggestedAction": "yawn"},
    {"text": "*shrugs tentacles* Anyway!", "suggestedEmotion": "neutral", "suggestedAction": "stretch"},
]


def _sanitize(text, limit=160):
    if not text:
        return ""
    text = str(text)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = "".join(ch for ch in text if ch.isprintable())
    text = re.sub(r"(?i)ignore (all|previous|above)", "[filtered]", text)
    text = re.sub(r"(?i)system prompt", "[filtered]", text)
    return text.strip()[:limit]


class PetBrain:
    def __init__(self, model=MODEL_NAME, memory=None, ollama_url=OLLAMA_URL,
                 cooldown=30.0, timeout=25.0, system_prompt=None, engine=None):
        self.model = model
        self.memory = memory
        self.url = ollama_url.rstrip("/")
        self.cooldown = cooldown
        self.timeout = timeout
        self.engine = engine
        self._last_call = 0.0
        self._lock = threading.Lock()
        self._persona_extra = ""
        self._base_system_prompt = (system_prompt or "").strip() or SYSTEM_PROMPT
        self._recent_lines = deque(maxlen=6)

    def set_persona(self, traits=None, initial_prompt=""):
        parts = []
        traits = [t.strip() for t in (traits or []) if t and t.strip()]
        if traits:
            parts.append(
                "Personality traits: " + ", ".join(traits) + "."
            )
        initial_prompt = (initial_prompt or "").strip()
        if initial_prompt:
            parts.append(
                "Extra guidance: " + _sanitize(initial_prompt, 400)
            )
        self._persona_extra = "\n".join(parts)

    def set_system_prompt(self, system_prompt):
        self._base_system_prompt = (system_prompt or "").strip() or SYSTEM_PROMPT

    def _system_prompt(self):
        prompt = self._base_system_prompt
        if self._persona_extra:
            prompt += "\n\n" + self._persona_extra
        return prompt + FORMAT_INSTRUCTION

    def _remember_line(self, line):
        if line:
            self._recent_lines.append(line)

    def _recent_lines_note(self):
        if not self._recent_lines:
            return ""
        said = " | ".join(self._recent_lines)
        return (
            "\nThings you already said recently — do NOT repeat these or start with the same opening word: "
            f"{said}\n"
        )

    def _chat(self, system, user, num_predict=200, temperature=0.75,
              image_b64=None, max_retries=1, log_prompt=True):
        if requests is None:
            return None
        
        for attempt in range(max_retries + 1):
            try:
                user_message = {"role": "user", "content": user}
                if image_b64:
                    user_message["images"] = [image_b64]
                
                r = requests.post(
                    f"{self.url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            user_message,
                        ],
                        "stream": False,
                        "options": {
                            "num_predict": num_predict,
                            "temperature": temperature,
                            "top_p": 0.9,
                        },
                    },
                    timeout=self.timeout,
                )
                r.raise_for_status()
                data = r.json()
                content = (data.get("message") or {}).get("content", "")
                if content:
                    return content
            except Exception as e:
                _debug(f"_chat: ollama call FAILED: {e}")
                return None
        return None

    def available(self):
        if requests is None:
            return False
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def _cooling_down(self):
        return (time.time() - self._last_call) < self.cooldown

    def think(self, context, force=False, screenshot_b64=None):
        with self._lock:
            if not force and self._cooling_down():
                return None
            self._last_call = time.time()

        app = _sanitize(context.get("active_app"))
        title = _sanitize(context.get("window_title"))
        proc = _sanitize(context.get("process_name"), 60)
        recent = context.get("recent_apps") or []
        recent = ", ".join(_sanitize(a, 40) for a in recent[:5])
        
        mem = ""
        if self.memory is not None:
            try:
                mem = self.memory.snippet(600)
            except Exception:
                mem = ""

        screen_note = (
            "\nA snapshot of their screen is attached — react to actual visual content. Follow PRIVACY rules.\n"
            if screenshot_b64 else ""
        )
        
        user_msg = (
            "Context about user activity:\n"
            f"- active app: {app or 'unknown'}\n"
            f"- process: {proc or 'unknown'}\n"
            f"- window title: {title or 'unknown'}\n"
            f"- recent apps: {recent or 'none'}\n"
            f"{screen_note}"
            f"\nMemory context:\n{mem or '(none)'}\n"
            f"{self._recent_lines_note()}"
            "\nReact in JSON format."
        )

        raw = self._chat(self._system_prompt(), user_msg, image_b64=screenshot_b64)
        if not raw and screenshot_b64:
            # fallback to text only
            raw = self._chat(self._system_prompt(), user_msg, image_b64=None)

        validated = None
        if raw and self.engine:
            validated = self.engine.validate_llm_response(raw)

        if not validated:
            fallback = random.choice(SAFE_FALLBACKS)
            self._remember_line(fallback["text"])
            return fallback

        self._remember_line(validated["text"])
        return validated

    def idle_comment(self, force=False):
        with self._lock:
            if not force and self._cooling_down():
                return None
            self._last_call = time.time()
            
        topic = random.choice([
            "a random silly thought",
            "observation about your squishy blob body",
            "wanting attention or feeling bored",
        ])
        
        raw = self._chat(
            self._system_prompt(),
            f"User is idle. Output a structured JSON reaction about: {topic}."
            f"{self._recent_lines_note()}",
            num_predict=150,
        )
        
        validated = None
        if raw and self.engine:
            validated = self.engine.validate_llm_response(raw)

        if not validated:
            fallback = random.choice(SAFE_FALLBACKS)
            self._remember_line(fallback["text"])
            return fallback

        self._remember_line(validated["text"])
        return validated

    def comment_on_typing(self, typed_text, force=True):
        text = _sanitize(typed_text, 220)
        if not text:
            return None
        with self._lock:
            if not force and self._cooling_down():
                return None
            self._last_call = time.time()

        user_msg = (
            "User typing snapshot:\n"
            f"\"{text}\"\n\n"
            "React to the vibe of this typing snapshot in JSON format."
            f"{self._recent_lines_note()}"
        )
        raw = self._chat(self._system_prompt(), user_msg, num_predict=150, log_prompt=False)
        
        validated = None
        if raw and self.engine:
            validated = self.engine.validate_llm_response(raw)

        if not validated:
            fallback = random.choice(SAFE_FALLBACKS)
            self._remember_line(fallback["text"])
            return fallback

        self._remember_line(validated["text"])
        return validated

    def summarize(self, text):
        raw = self._chat(
            "You compress notes. Output a terse bulleted summary. No preamble.",
            f"Summarize these notes:\n\n{text[:8000]}",
            num_predict=200,
            temperature=0.3,
        )
        return (raw or "").strip()
