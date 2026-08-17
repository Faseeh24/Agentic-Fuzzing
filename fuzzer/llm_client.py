#!/usr/bin/env python3
"""llm_client.py — multi-provider LLM client with fallback.

Tries providers in order: OpenRouter → Groq → Gemini.
API keys are loaded from a ``.env`` file in the project root via ``python-dotenv``.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

PROVIDERS = [
    {
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "model": os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001"),
    },
    {
        "name": "groq",
        "env_key": "GROQ_API_KEY",
        "api_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    },
    {
        "name": "gemini",
        "env_key": "GEMINI_API_KEY",
        "api_url": None,  # Uses google-generativeai SDK
        "model": os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
    },
]

# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Load API keys from .env if present."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # python-dotenv not installed; rely on os.environ


def _try_openrouter(messages: list[dict], timeout: float = 60.0) -> str:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/faseehurrehman/mxml-fuzz",
        "X-Title": "mxml-fuzz",
    }
    payload = {
        "model": os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001"),
        "messages": messages,
        "max_tokens": 4096,
    }
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _try_groq(messages: list[dict], timeout: float = 60.0) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "messages": messages,
        "max_tokens": 4096,
    }
    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _try_gemini(messages: list[dict], timeout: float = 60.0) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai package not installed")
    genai.configure(api_key=key)
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-flash-latest"))
    # Convert OpenAI-style messages to Gemini format
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        role_map = {"system": "user", "user": "user", "assistant": "model"}
        parts.append(f"{role_map.get(role, 'user')}: {msg['content']}")
    # google-generativeai doesn't accept a timeout kwarg on generate_content();
    # we call it without one and rely on the caller's own timeout discipline.
    resp = model.generate_content("\n".join(parts))
    return resp.text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class LLMClient:
    """Multi-provider LLM client with automatic fallback."""

    def __init__(self, provider_order: Optional[list[str]] = None) -> None:
        _load_env()
        self._order = provider_order or [p["name"] for p in PROVIDERS]
        self._available: dict[str, callable] = {}
        self._active_provider: Optional[str] = None
        self._initialize()

    def _initialize(self) -> None:
        """Probe each provider and register working ones."""
        for p in PROVIDERS:
            if p["name"] not in self._order:
                continue
            key = p["env_key"]
            if not os.getenv(key):
                continue
            try:
                if p["name"] == "openrouter":
                    self._available[p["name"]] = _try_openrouter
                elif p["name"] == "groq":
                    self._available[p["name"]] = _try_groq
                elif p["name"] == "gemini":
                    self._available[p["name"]] = _try_gemini
            except Exception as exc:
                print(f"  [llm] {p['name']} init failed: {exc}")

    def chat(self, messages: list[dict], timeout: float = 60.0) -> str:
        """Send a chat request, trying providers in order until one succeeds."""
        errors = []
        for name in self._order:
            fn = self._available.get(name)
            if fn is None:
                continue
            try:
                result = fn(messages, timeout=timeout)
                self._active_provider = name
                return result
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        raise RuntimeError(
            f"All LLM providers failed. Errors: {'; '.join(errors)}"
        )

    @property
    def active_provider(self) -> Optional[str]:
        return self._active_provider

    @property
    def available_providers(self) -> list[str]:
        return list(self._available.keys())


def chat(messages: list[dict], timeout: float = 60.0) -> str:
    """Convenience function — creates a default LLMClient and calls chat()."""
    client = LLMClient()
    return client.chat(messages, timeout=timeout)
