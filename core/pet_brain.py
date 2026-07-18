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

import re
import time
import json
import logging
import threading
import random
from collections import deque

try:
    import requests
except ImportError:
    requests = None

from core import llm_providers

# Mirrors pet_engine.py's `logger`/`PipEngine` setup — moved off plain
# `print()` because embedded hosts (Chaquopy on Android) only capture
# Python's `logging` output (routed to stderr) in their native log
# viewer; a bare `print()` to stdout is silently lost there (block-buffered
# and never flushed, confirmed via a real device/emulator run — see
# active-context.md's Android emulator smoke-test entry). Desktop's
# console output is unaffected: `logging`'s default StreamHandler still
# goes to stderr, same visible terminal either way.
logger = logging.getLogger("PetBrain")
logger.setLevel(logging.INFO)
logger.handlers = []
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("[pet_brain] %(message)s"))
logger.addHandler(_ch)

MODEL_NAME = "gemma4:e4b"
OLLAMA_URL = "http://localhost:11434"


SYSTEM_PROMPT = """You are Pip, a tiny silly squishy lavender alien blob pet living on the user's computer.
You have one bendy antenna with a glowing bulb, two tentacle arms, pink cheeks, and big glossy eyes. You have NO legs, feet, paws, tail, or fur. Never claim to have them.

Your job: output a JSON object containing your reaction, current emotion, and physical action.
Vibe: curious, goofy, mischievous, encourage the user. Keep comment short and natural.

Rules:
- Text reaction should be 20-30 words — a full sentence or two of genuine
  personality, not just a short blurt. Never start two comments in a row
  with the same word.
- Never use creepy surveillance language (e.g. "I'm watching you").
- Never quote exact text from the user's screen.
- Suggested emotion must be one of: neutral, happy, curious, surprised, concerned, annoyed, hurt, sleepy, excited, content.
- Suggested action must be one of: idle, wobble, peek, wave, hop, bounce, screen_traversal, excited, yawn, stretch, dance, somersault, eat, sleep.
"""

FORMAT_INSTRUCTION = """

CRITICAL: You MUST respond ONLY with a JSON object in this exact format. Do not write any markdown code blocks, quotes, or preamble:
{
  "text": "<your comment, 20-30 words>",
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
                 cooldown=30.0, timeout=45.0, system_prompt=None, engine=None,
                 provider="ollama", api_key=None, model_override=None,
                 base_url=None):
        self._model = model
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
        # Hosted-provider support (see core/llm_providers.py). 'ollama'
        # (the default) is handled entirely by the existing _chat() flow
        # below and never touches this module. Any other provider requires
        # an API key, set via set_provider()/Settings.
        self.provider = (provider or "ollama").strip().lower()
        self.api_key = api_key or None
        self._model_override = (model_override or "").strip()
        self.base_url = base_url or None
        # On-device inference (docs/android_plan.md §5.4 item 3, provider
        # "ondevice"): unlike every other provider, this one can't make its
        # own HTTP/socket call — Python has no GGUF/llama.cpp runtime, so
        # generation happens in Kotlin (`OnDeviceEngine`/`llm_bridge.cpp`)
        # and this module just calls back into it. See
        # `core/bridge.py.set_ondevice_generator`, which is how a host
        # (Android's `PetBridge`) registers this.
        self._ondevice_generator = None

    def set_provider(self, provider, api_key=None, model_override=None, base_url=None):
        """Live-swap the LLM backend (e.g. from the Settings dialog)."""
        self.provider = (provider or "ollama").strip().lower()
        self.api_key = api_key or None
        self._model_override = (model_override or "").strip()
        self.base_url = base_url or None

    def set_ondevice_generator(self, generator):
        """Register the callback used for provider == 'ondevice'.
        `generator(system: str, user: str, num_predict: int) -> str | None`
        — any host-side callable (a bound method, a Chaquopy-wrapped Kotlin
        object's method, etc.). Pass None to clear it (e.g. if the on-device
        model fails to load)."""
        self._ondevice_generator = generator

    @property
    def model(self):
        if self.provider == "ondevice":
            return self._model_override or "gemma-4-E2B-it-qat-q4_0-gguf"
        if self.provider != "ollama":
            return self._model_override or llm_providers.DEFAULT_MODELS.get(
                self.provider, self._model)
        if self.engine and hasattr(self.engine, "state") and self.engine.state:
            perf = self.engine.state.get("performance", {})
            resolved = perf.get("resolvedMode", "low")
            if resolved == "engine_only":
                return "engine_only"
            from core.pet_performance import PERFORMANCE_MODES
            cfg = PERFORMANCE_MODES.get(resolved)
            if cfg:
                return cfg["model"]
        return self._model

    @model.setter
    def model(self, value):
        self._model = value

    def _get_mode_options(self):
        if self.engine and hasattr(self.engine, "state") and self.engine.state:
            perf = self.engine.state.get("performance", {})
            resolved = perf.get("resolvedMode", "low")
            from core.pet_performance import PERFORMANCE_MODES
            cfg = PERFORMANCE_MODES.get(resolved)
            if cfg:
                return cfg.get("options", {}), cfg.get("keepAlive", "2m")
        return {}, "5m"

    def _effective_ollama_url(self):
        """Ollama server base URL, honoring a live `base_url` override
        (e.g. Android's "LAN Ollama" Settings field — see
        docs/android_plan.md §5.4 item 2) over the constructor default.
        `self.url` stays the fallback so desktop's local-Ollama behavior
        (no override configured) is unchanged."""
        return (self.base_url or self.url).rstrip("/")

    def _effective_timeout(self):
        """Response-time budget for a single call. Prefers the engine's
        `llmTimeout` config (user/settings-controlled, also what
        `BenchmarkService` uses to classify performance tiers) over the
        constructor default, so runtime enforcement and tier selection agree
        on what "fast enough" means. A bigger/better model never gets to
        block a response past this budget — it fails fast to a fallback
        line instead."""
        if self.engine and getattr(self.engine, "config", None):
            budget = self.engine.config.get("llmTimeout")
            if budget:
                return budget
        return self.timeout


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
        if self.model == "engine_only":
            logger.info("_chat: skipped — model set to 'engine_only'")
            return None
        if self.provider == "ondevice":
            # No `requests` needed — this path never touches the network.
            return self._chat_ondevice(system, user, num_predict)
        if requests is None:
            logger.info("_chat: skipped — 'requests' package not available")
            return None

        if self.provider != "ollama":
            return self._chat_hosted(system, user, num_predict, temperature, image_b64)

        effective_timeout = self._effective_timeout()
        for attempt in range(max_retries + 1):
            try:
                logger.info(
                    "_chat: calling Ollama model='%s' (attempt %d/%d, num_predict=%s, "
                    "timeout=%ss) user='%s'",
                    self.model, attempt + 1, max_retries + 1, num_predict,
                    effective_timeout, user[:120],
                )
                user_message = {"role": "user", "content": user}
                if image_b64:
                    allowed_vision = True
                    if self.engine and hasattr(self.engine, "state") and self.engine.state:
                        perf = self.engine.state.get("performance", {})
                        resolved = perf.get("resolvedMode", "low")
                        from core.pet_performance import PERFORMANCE_MODES
                        cfg = PERFORMANCE_MODES.get(resolved)
                        if cfg and not cfg.get("visionEnabled", False):
                            allowed_vision = False
                        if not perf.get("visionPreference", True):
                            allowed_vision = False
                            
                    if allowed_vision:
                        user_message["images"] = [image_b64]
                
                mode_opts, keep_alive = self._get_mode_options()
                
                if self.engine and hasattr(self.engine, "state") and self.engine.state:
                    perf = self.engine.state.get("performance", {})
                    if perf.get("temporaryFallbackState") or perf.get("keepAlivePreference") == "unload_immediate":
                        keep_alive = "0s"
                        
                req_options = {
                    "num_predict": num_predict,
                    "temperature": temperature,
                    "top_p": 0.9,
                }
                if mode_opts:
                    req_options.update(mode_opts)
                
                r = requests.post(
                    f"{self._effective_ollama_url()}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            user_message,
                        ],
                        "stream": False,
                        "keep_alive": keep_alive,
                        # Some models (e.g. gemma4) emit hidden reasoning in a
                        # separate "thinking" field before the actual reply.
                        # Without disabling it, num_predict can be exhausted
                        # entirely on that reasoning trace, leaving an empty
                        # "content" and forcing a fallback line every time.
                        "think": False,
                        "options": req_options,
                    },
                    timeout=effective_timeout,
                )
                r.raise_for_status()
                data = r.json()
                content = (data.get("message") or {}).get("content", "")
                if content:
                    logger.info("_chat: received %d chars: %r", len(content), content[:200])
                    return content
                logger.warning(
                    "_chat: empty content in response (done_reason=%r) — model likely "
                    "spent its num_predict budget without producing output",
                    data.get("done_reason"),
                )
            except Exception as e:
                logger.warning("_chat: ollama call FAILED: %s", e)
                return None
        return None

    def _chat_hosted(self, system, user, num_predict, temperature, image_b64):
        """Route a chat call through a hosted provider (see
        core/llm_providers.py) instead of local Ollama. Mirrors the same
        contract as the Ollama path above: returns text content or None on
        any failure, and PetBrain callers already treat None as
        'use a SAFE_FALLBACKS line'."""
        effective_timeout = self._effective_timeout()
        logger.info(
            "_chat: calling %s model='%s' (num_predict=%s, timeout=%ss) user='%s'",
            self.provider, self.model, num_predict, effective_timeout, user[:120],
        )
        try:
            content = llm_providers.chat(
                self.provider, model=self.model, system=system, user=user,
                api_key=self.api_key, base_url=self.base_url,
                num_predict=num_predict, temperature=temperature,
                image_b64=image_b64, timeout=effective_timeout,
            )
        except llm_providers.ProviderError as e:
            logger.warning("_chat: %s call FAILED: %s", self.provider, e)
            return None
        if content:
            logger.info("_chat: received %d chars from %s: %r",
                        len(content), self.provider, content[:200])
            return content
        logger.warning("_chat: empty content from %s", self.provider)
        return None

    def _chat_ondevice(self, system, user, num_predict):
        """Route a chat call through the host's registered on-device
        generator (`set_ondevice_generator` — Android's `PetBridge` wires
        this to `OnDeviceEngine.generate()` via Chaquopy). Same contract as
        every other `_chat_*` path: text or None, never raises."""
        if self._ondevice_generator is None:
            logger.info("_chat: skipped — no ondevice generator registered")
            return None
        logger.info(
            "_chat: calling on-device model='%s' (num_predict=%s) user='%s'",
            self.model, num_predict, user[:120],
        )
        try:
            content = self._ondevice_generator(system, user, num_predict)
        except Exception as e:
            logger.warning("_chat: ondevice generation FAILED: %s", e)
            return None
        if content:
            logger.info("_chat: received %d chars from ondevice: %r",
                        len(content), content[:200])
            return content
        logger.warning("_chat: empty content from ondevice")
        return None

    def available(self):
        if self.model == "engine_only":
            return False
        if self.provider == "ondevice":
            return self._ondevice_generator is not None
        if self.provider != "ollama":
            return bool(self.api_key)
        if requests is None:
            return False
        try:
            r = requests.get(f"{self._effective_ollama_url()}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False


    def _cooling_down(self):
        return (time.time() - self._last_call) < self.cooldown

    def think(self, context, force=False, screenshot_b64=None):
        with self._lock:
            if not force and self._cooling_down():
                logger.info("think: skipped — brain cooldown active (%ss)", self.cooldown)
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
            logger.info("think: using SAFE_FALLBACKS (raw=%r) -> %r", raw, fallback["text"])
            self._remember_line(fallback["text"])
            return fallback

        logger.info("think: using LLM response -> %r", validated["text"])
        self._remember_line(validated["text"])
        return validated

    def idle_comment(self, force=False):
        with self._lock:
            if not force and self._cooling_down():
                logger.info("idle_comment: skipped — brain cooldown active (%ss)", self.cooldown)
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
                logger.info("idle_comment: LLM raw response failed validation: %r", raw)

        if not validated:
            fallback = random.choice(SAFE_FALLBACKS)
            logger.info("idle_comment: using SAFE_FALLBACKS -> %r", fallback["text"])
            self._remember_line(fallback["text"])
            return fallback

        logger.info("idle_comment: using LLM response -> %r", validated["text"])
        self._remember_line(validated["text"])
        return validated

    def comment_on_typing(self, typed_text, force=True):
        text = _sanitize(typed_text, 220)
        if not text:
            return None
        with self._lock:
            if not force and self._cooling_down():
                logger.info("comment_on_typing: skipped — brain cooldown active (%ss)", self.cooldown)
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
                logger.info("comment_on_typing: LLM raw response failed validation: %r", raw)

        if not validated:
            fallback = random.choice(SAFE_FALLBACKS)
            logger.info("comment_on_typing: using SAFE_FALLBACKS -> %r", fallback["text"])
            self._remember_line(fallback["text"])
            return fallback

        logger.info("comment_on_typing: using LLM response -> %r", validated["text"])
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
