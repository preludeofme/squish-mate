#!/usr/bin/env python3
"""
llm_providers.py — pluggable hosted-LLM backends for PetBrain.

Ollama stays the default and is handled entirely inside pet_brain.py (it's
local, free, no key needed, and already tightly integrated with the
performance-tier system in core/pet_performance.py). This module only
covers the OPT-IN hosted alternatives Ryan asked for: OpenAI, Anthropic
(Claude), and OpenRouter — so anyone can bring their own API key instead of
running a local model.

Every function here returns the same thing PetBrain._chat() already expects
from Ollama: the raw text content string (or raises ProviderError, which
PetBrain catches and treats exactly like an Ollama failure — falls back to
a canned SAFE_FALLBACKS line).
"""

try:
    import requests
except ImportError:
    requests = None

# Sane default model per provider, used when the user leaves the "model
# override" field blank in Settings.
DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-20241022",
    "openrouter": "meta-llama/llama-3.1-8b-instruct",
}

PROVIDER_LABELS = {
    "ollama": "Ollama (local, default)",
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "openrouter": "OpenRouter",
}

HOSTED_PROVIDERS = ("openai", "anthropic", "openrouter")


class ProviderError(Exception):
    pass


def chat(provider, *, model, system, user, api_key=None, base_url=None,
         num_predict=200, temperature=0.75, image_b64=None, timeout=45.0):
    """Dispatch a single chat completion call to a hosted provider. Not
    used for 'ollama' — pet_brain.py keeps that path unchanged."""
    if requests is None:
        raise ProviderError("'requests' package not available")
    if not api_key:
        raise ProviderError(f"no API key configured for provider '{provider}'")

    if provider == "openai":
        return _chat_openai(model, system, user, api_key, num_predict,
                             temperature, image_b64, timeout, base_url=base_url)
    if provider == "openrouter":
        return _chat_openai(model, system, user, api_key, num_predict,
                             temperature, image_b64, timeout,
                             base_url=base_url or "https://openrouter.ai/api/v1")
    if provider == "anthropic":
        return _chat_anthropic(model, system, user, api_key, num_predict,
                                temperature, image_b64, timeout, base_url=base_url)
    raise ProviderError(f"unknown provider: {provider!r}")


def _chat_openai(model, system, user, api_key, num_predict, temperature,
                  image_b64, timeout, base_url=None):
    """OpenAI-compatible /chat/completions (also used for OpenRouter, which
    implements the same request/response shape)."""
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    user_content = user
    if image_b64:
        user_content = [
            {"type": "text", "text": user},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": num_predict,
                "temperature": temperature,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise ProviderError(str(e)) from e
    choices = data.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content", "") or ""


def _chat_anthropic(model, system, user, api_key, num_predict, temperature,
                     image_b64, timeout, base_url=None):
    url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
    user_content = [{"type": "text", "text": user}]
    if image_b64:
        user_content.insert(0, {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
        })
    try:
        r = requests.post(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "system": system,
                "messages": [{"role": "user", "content": user_content}],
                "max_tokens": num_predict,
                "temperature": temperature,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise ProviderError(str(e)) from e
    parts = data.get("content") or []
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")
