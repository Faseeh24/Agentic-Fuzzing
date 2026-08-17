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


def _is_rate_limit(resp: httpx.Response) -> bool:
    """Return True if the response indicates a rate-limit / quota error."""
    return resp.status_code in (429, 529)


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
    if _is_rate_limit(resp):
        body = resp.text
        raise httpx.HTTPStatusError(
            f"OpenRouter rate limit (429): {body[:300]}",
            request=resp.request,
            response=resp,
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
    if _is_rate_limit(resp):
        body = resp.text
        raise httpx.HTTPStatusError(
            f"Groq rate limit (429): {body[:300]}",
            request=resp.request,
            response=resp,
        )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _is_gemini_quota_error(exc: Exception) -> bool:
    """Detect Gemini quota / rate-limit errors from the SDK."""
    text = str(exc)
    return "quota" in text.lower() or "429" in text or "rate limit" in text.lower()


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
    try:
        resp = model.generate_content("\n".join(parts))
        return resp.text
    except Exception as exc:
        if _is_gemini_quota_error(exc):
            raise RuntimeError(
                f"Gemini quota exceeded (429): {exc}"
            ) from exc
        raise


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
        """Send a chat request, trying providers in order until one succeeds.

        Raises ``RuntimeError`` with a detailed message when every provider
        fails, distinguishing between missing keys, quota/rate-limit hits,
        and other errors.
        """
        errors: list[str] = []
        missing_keys: list[str] = []
        quota_hits: list[str] = []
        for p in PROVIDERS:
            name = p["name"]
            if name not in self._order:
                continue
            key = p["env_key"]
            if not os.getenv(key):
                missing_keys.append(name)
                continue
            fn = self._available.get(name)
            if fn is None:
                continue
            try:
                result = fn(messages, timeout=timeout)
                self._active_provider = name
                return result
            except Exception as exc:
                err_str = str(exc)
                if "quota" in err_str.lower() or "429" in err_str or "rate limit" in err_str.lower():
                    quota_hits.append(f"{name}: {exc}")
                else:
                    errors.append(f"{name}: {exc}")

        parts: list[str] = []
        if quota_hits:
            parts.append("RATE-LIMITED: " + "; ".join(quota_hits))
        if missing_keys:
            parts.append(f"Missing API keys for: {', '.join(missing_keys)}")
        if errors:
            parts.append("OTHER ERRORS: " + "; ".join(errors))
        if not parts:
            parts.append("All configured providers are unavailable.")
        raise RuntimeError("\n".join(parts))

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
