"""
agent/llm_client.py — Open-source LLM client for the Kaggle notebook.

This file OVERWRITES the repo's Groq-only client (agent/llm_client.py) so the
same orchestrator pipeline (agent/orchestrator.py) runs locally with any
HuggingFace open-source model instead of calling the Groq HTTP API.

The public interface is identical to the original Groq LLMClient, so
agent/orchestrator.py works UNCHANGED:

    LLMClient(model=None).is_available() -> bool
    LLMClient(model=None).chat(messages, timeout=120.0) -> str

Model selection
---------------
    os.environ["HF_MODEL_NAME"]  -> model repo id (set in the notebook config cell)

The model is loaded lazily on the first chat() call. A module-level singleton
cache makes the (slow) load happen only once across every LLMClient() created
during a notebook run — the smoke-test cell pre-loads it, then the pipeline
reuses the cached instance.

Robustness
----------
If a model is too big for GPU memory, generation auto-retries on CPU. If loading
or generation ever fails, chat() raises RuntimeError — the orchestrator catches
that exception and degrades gracefully to the bundled known-good strategy
(fuzzer/fallback_strategy.py), so the loop ALWAYS keeps running.

Suggested (non-gated) models for Kaggle:
    Qwen/Qwen2.5-7B-Instruct          (best quality, needs a GPU T4/A10G)
    mistralai/Mistral-7B-Instruct-v0.3
    Qwen/Qwen2.5-1.5B-Instruct        (fast / works without a GPU)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

# Singleton cache: model name -> LLMClient instance whose model is loaded.
# Re-using the cache means the heavy download+load happens just once.
_CACHE: dict = {}


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


class LLMClient:
    """Open-source LLM client backed by HuggingFace Transformers."""

    def __init__(self, model: Optional[str] = None) -> None:
        self._model_name = model or os.getenv("HF_MODEL_NAME", _DEFAULT_MODEL)
        self._tokenizer = None
        self._model = None
        self._device = "cuda" if _cuda_available() else "cpu"
        logger.info("LLMClient configured model=%s device=%s",
                     self._model_name, self._device)

    # -- model lifecycle -------------------------------------------------

    def _load(self) -> None:
        """Load (or reuse) the tokenizer + model. Idempotent and cached."""
        cached = _CACHE.get(self._model_name)
        if cached is not None and cached._model is not None:
            self._tokenizer = cached._tokenizer
            self._model = cached._model
            self._device = cached._device
            print(f"[llm_client] Reusing cached model: {self._model_name}")
            return

        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM

        print(f"[llm_client] Loading open-source model: {self._model_name}  "
              f"(device={self._device})")
        t0 = time.time()
        self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        # Some tokenizers (e.g. Qwen) have no pad token; fall back to eos.
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        weight_dtype = torch.bfloat16 if self._device == "cuda" else torch.float32
        try:
            self._model = AutoModelForCausalLM.from_pretrained(
                self._model_name,
                dtype=weight_dtype,
                device_map="auto",
            )
        except Exception as exc:
            # GPU OOM / dtype issues -> retry on CPU with offloading.
            print(f"[llm_client] GPU load failed ({exc!r}); "
                  f"retrying on CPU (float32, offloaded).")
            import gc
            gc.collect()
            try:
                self._model = AutoModelForCausalLM.from_pretrained(
                    self._model_name,
                    dtype=torch.float32,
                    device_map="auto",
                    offload_folder="offload",
                )
            except Exception as exc2:
                raise RuntimeError(
                    f"Failed to load model '{self._model_name}': {exc2!r}"
                ) from exc2

        self._model.eval()
        _CACHE[self._model_name] = self
        print(f"[llm_client] Model '{self._model_name}' loaded "
              f"in {time.time() - t0:.1f}s")
    def is_available(self) -> bool:
        """Return True.

        The local model is treated as available; any load/generation failure
        surfaces as an exception in chat(), which the orchestrator catches and
        degrades to the bundled fallback strategy. This mirrors the Groq client
        whose is_available() gate only guards against a missing API key.
        """
        return True

    # -- generation ------------------------------------------------------

    def chat(self, messages: list[dict], timeout: float = 120.0) -> str:
        """Generate a response from the open-source model.

        Parameters
        ----------
        messages : list[dict]
            OpenAI-style messages, e.g.
            [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        timeout : float
            Accepted for interface compatibility (a local model is not
            rate-limited); not enforced.

        Returns
        -------
        str
            The assistant's response text (everything generated after the prompt).
        """
        if self._model is None:
            self._load()
        if self._model is None or self._tokenizer is None:
            raise RuntimeError(
                f"Open-source model '{self._model_name}' is not loaded."
            )

        # Normalise to plain role/content dicts.
        msgs = [
            {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
            for m in messages
        ]

        # Use the tokenizer's native chat template when available
        # (Qwen / Mistral / Llama-3 all ship one). Fall back to a flat concat.
        try:
            input_ids = self._tokenizer.apply_chat_template(
                msgs, return_tensors="pt", add_generation_prompt=True
            )
        except Exception:
            rendered = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
            enc = self._tokenizer(rendered, return_tensors="pt")
            input_ids = enc["input_ids"] if isinstance(enc, dict) else enc
        input_ids = input_ids.to(self._model.device)

        # Don't let the prompt blow the context window.
        max_total = getattr(self._tokenizer, "model_max_length", 4096) or 4096
        tailroom = max_total - 2048
        if input_ids.shape[-1] > tailroom:
            input_ids = input_ids[..., -tailroom:]

        import torch
        with torch.no_grad():
            generated = self._model.generate(
                input_ids,
                max_new_tokens=2048,
                temperature=0.2,
                do_sample=True,
                top_p=0.95,
                repetition_penalty=1.05,
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
            )

        # Drop the prompt and decode only the newly generated tokens.
        prompt_len = input_ids.shape[-1]
        text = self._tokenizer.decode(
            generated[0][prompt_len:], skip_special_tokens=True
        )
        return text


def chat(messages: list[dict], timeout: float = 120.0) -> str:
    """Convenience helper — mirrors the Groq module-level chat()."""
    return LLMClient().chat(messages, timeout=timeout)

