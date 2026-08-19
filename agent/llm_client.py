"""
agent/llm_client.py — Groq-only LLM client with auto model selection.

- Only uses the Groq API (GROQ_API_KEY required)
- Auto-selects model from GROQ_MODEL env var or falls back to default
- Explicit error reporting: returns structured results with status
- No fallback to other providers
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "openai/gpt-oss-20b"


def _load_env() -> None:
    """Load API keys from .env if present."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


class LLMClient:
    """Groq-only LLM client."""

    def __init__(self, model: Optional[str] = None) -> None:
        _load_env()
        self._model = model or os.getenv("GROQ_MODEL", _DEFAULT_MODEL)
        self._key = os.getenv("GROQ_API_KEY", "")
        self._api_url = "https://api.groq.com/openai/v1/chat/completions"
        logger.info("LLMClient initialized with model=%s, key_set=%s", self._model, bool(self._key))

    def is_available(self) -> bool:
        """Return True if GROQ_API_KEY is set."""
        return bool(self._key)

    def chat(self, messages: list[dict], timeout: float = 120.0) -> str:
        """
        Send a chat request to Groq.

        Parameters
        ----------
        messages : list[dict]
            OpenAI-style message list, e.g.
            [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        timeout : float
            Request timeout in seconds.

        Returns
        -------
        str
            The assistant's response text.

        Raises
        ------
        RuntimeError
            If the API key is missing or the request fails.
        """
        if not self._key:
            raise RuntimeError("GROQ_API_KEY not set. Set it in .env or as an environment variable.")

        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": 2048,
        }
        # Reasoning models (gpt-oss, qwen3) spend chain-of-thought tokens by
        # default and can return an EMPTY "content" when reasoning eats the
        # whole budget. Cap the thinking so the strategy code is always emitted.
        if "gpt-oss" in self._model or "qwen3" in self._model:
            payload["reasoning_effort"] = "low"

        logger.info("Sending request to Groq (model=%s)", self._model)
        resp = httpx.post(self._api_url, json=payload, headers=headers, timeout=timeout)

        if resp.status_code in (429, 529):
            body = resp.text
            raise httpx.HTTPStatusError(
                f"Groq rate limit (429): {body[:300]}",
                request=resp.request,
                response=resp,
            )

        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        logger.info("Received response from Groq (model=%s, len=%d)", self._model, len(content))
        return content


def chat(messages: list[dict], timeout: float = 120.0) -> str:
    """Convenience function — creates a default LLMClient and calls chat()."""
    client = LLMClient()
    return client.chat(messages, timeout=timeout)
