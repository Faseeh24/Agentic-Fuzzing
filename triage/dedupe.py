#!/usr/bin/env python3
"""
triage/dedupe.py — crash signature extraction and deduplication.

For each crash (exit code 3 sanitizer, 4 timeout, 5 bug_crash), we:
  1. Parse the stderr for an ASan/UBSan stack trace.
  2. Normalize the top stack frames (strip noisy libc/allocator frames).
  3. Hash the normalized frames to produce a deterministic crash signature.
  4. Group crashes by signature so the same underlying bug is reported once.

Timeouts (code 4) have no stack trace, so we fall back to a structural
hash of the input shape (nesting depth, approximate length buckets) so that
multiple timeouts caused by the same pathological pattern are still grouped.

Normalization choices (documented for the report):
  - Stripped frames: ``__interceptor_malloc``, ``__interceptor_free``,
    ``malloc``, ``free``, ``__libc_start_main``, ``_start`` — these appear
    in every crash and carry no diagnostic information.
  - Top N frames: 5 is a reasonable default. Too few over-merges distinct
    bugs that share an allocator entry point; too many under-merges because
    ASLR / inlining noise creeps in past the interesting frames.
  - Bare timeout signature: ``timeout|<structural hash of input>`` — groups
    timeouts by input shape rather than treating every timeout as unique.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex for extracting stack frames from ASan / UBSan output
# ---------------------------------------------------------------------------

# Matches lines like:
#   #0 0x5555557a3f20 in mxml_xml_load_string callback_t * /src/target/mxml/mxml-attr.c:142:28
#   #1 0x7ffff7a1e243 in __interceptor_malloc ...
# We only need the function name (the part after "in").
STACK_FRAME_RE = re.compile(
    r"^\s*#\d+\s+0x[0-9a-f]+\s+in\s+(.+)$", re.MULTILINE
)

# Also catch UBSan-style "runtime error:" which doesn't have #N frames —
# we capture the summary line and the first function name after it.
UBSAN_SUMMARY_RE = re.compile(
    r"runtime error: (.+)$", re.MULTILINE
)
UBSAN_FRAME_RE = re.compile(
    r"\s*#?\d+\s+0x[0-9a-f]+ in (\S+)", re.MULTILINE
)

# ---------------------------------------------------------------------------
# Noise frames to strip — these are allocator / runtime boilerplate
# ---------------------------------------------------------------------------

NOISY_FRAMES = {
    "__interceptor_malloc",
    "__interceptor_free",
    "malloc",
    "free",
    "__libc_start_main",
    "_start",
    "__interceptor_realloc",
    "realloc",
}

# ---------------------------------------------------------------------------
# Helpers ────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


def _extract_stack_frames(stderr_text: str) -> list[str]:
    """Extract raw function names from ASan-style stack traces."""
    frames: list[str] = []
    for match in STACK_FRAME_RE.finditer(stderr_text):
        raw = match.group(1).strip()
        # The raw text is usually "func_name ... /path/to/file:line" or
        # "func_name (opt+0x...)"; keep only the leading identifier.
        parts = raw.split()
        if parts:
            func = parts[0]
            # Strip trailing parentheses / angle-bracket noise
            func = re.sub(r"[<(].*$", "", func)
            frames.append(func)
    return frames


def _extract_ubsan_frames(stderr_text: str) -> list[str]:
    """Extract frames from UBSan output (different format than ASan)."""
    frames: list[str] = []
    for match in UBSAN_FRAME_RE.finditer(stderr_text):
        raw = match.group(1).strip()
        parts = raw.split()
        if parts:
            func = re.sub(r"[<(].*$", "", parts[0])
            frames.append(func)
    return frames


def _structural_hash(input_text: str) -> str:
    """
    Compute a coarse structural fingerprint of the input for timeout dedup.

    Buckets by:
      - Total byte length (narrow buckets for small inputs, wide for large)
      - Max nesting depth (count of opening tags)
      - Presence of entity references

    This is intentionally coarse — the goal is to group *similar* pathological
    inputs, not to produce a unique fingerprint.
    """
    # Nesting depth: count '<' that start a tag
    open_tags = len(re.findall(r"<[a-zA-Z/!?]", input_text))
    # Length bucket
    blen = len(input_text.encode("utf-8"))
    if blen < 100:
        len_bucket = "tiny"
    elif blen < 500:
        len_bucket = "small"
    elif blen < 2000:
        len_bucket = "medium"
    else:
        len_bucket = "large"
    # Entity reference presence
    has_entities = "&" in input_text
    key = f"{len_bucket}|depth={open_tags}|ents={has_entities}"
    return hashlib.sha256(key.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Public API ─────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


def normalize_stack(
    stderr_text: str, top_n: int = 5
) -> tuple[str, ...]:
    """
    Return the top *top_n* meaningful stack frames from *stderr_text*,
    with noisy allocator/libc frames stripped.

    Falls back to UBSan-format extraction if no ASan-style frames are found.
    """
    raw_frames = _extract_stack_frames(stderr_text)
    if not raw_frames:
        raw_frames = _extract_ubsan_frames(stderr_text)

    cleaned = [f for f in raw_frames if f not in NOISY_FRAMES]
    return tuple(cleaned[:top_n])


def signature_for(
    stderr_text: str,
    signal_name: str | None,
    input_text: str | None = None,
) -> str:
    """
    Return a 16-character hex crash signature for the given stderr / signal.

    Signature computation happens exactly once, from real stderr data.
    - If a real stack trace is present, hash the normalized frames.
    - If it's a bare timeout (or stripped binary with no frames), fall back
      to a structural hash of the input so similar timeouts group together.
      In this case, log clearly that a fallback was used.
    """
    frames = normalize_stack(stderr_text)
    if frames:
        basis = "|".join(frames)
    else:
        # No usable stack — use signal name + structural input hash
        if input_text is not None and input_text.strip():
            struct_hash = _structural_hash(input_text)
            basis = f"{signal_name or 'unknown'}|struct={struct_hash}"
            logger.warning(
                "No stack trace found for crash; using input-structure fallback. "
                "This signature is weaker than a real stack-based one."
            )
        else:
            struct_hash = "unknown"
            basis = f"{signal_name or 'unknown'}|struct={struct_hash}"
            logger.warning(
                "No stack trace and no input text for crash signature; "
                "using minimal fallback."
            )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def classify_stderr(stderr_bytes: bytes) -> tuple[str, str]:
    """
    Return ``(signal_name, summary_line)`` from raw stderr bytes.

    signal_name: one of ``"sanitizer"`` (ASan/UBSan), ``"timeout"`` (no output),
    ``"bug_crash"`` (non-zero exit, no sanitizer text), ``"valid"``, ``"invalid"``.
    summary_line: first non-empty line of stderr, or a short descriptor.
    """
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    stderr_lower = stderr_text.lower()

    if "addresssanitizer" in stderr_lower or "runtime error:" in stderr_lower:
        first_line = stderr_text.strip().splitlines()[0] if stderr_text.strip() else "sanitizer diagnostic"
        return "sanitizer", first_line
    if not stderr_text.strip():
        return "timeout", "(no output)"
    first_line = stderr_text.strip().splitlines()[0]
    return "bug_crash", first_line


def load_crash_records(log_dir: Path) -> list[dict[str, Any]]:
    """
    Load crash records from the JSONL iteration logs in *log_dir*.

    Each JSONL record has a ``crash_signatures`` field containing dicts with
    ``code``, ``label``, and ``input_preview``. We enrich these with full
    stderr info by re-running the harness on saved reproducer files when
    available (see ``save_crash()`` below).

    Returns a list of dicts with keys:
        signature, code, signal_name, summary, input_path, input_text
    """
    crashes: list[dict[str, Any]] = []
    crash_dir = log_dir.parent.parent / "triage" / "crashes"
    if not crash_dir.exists():
        return crashes

    for sig_dir in sorted(crash_dir.iterdir()):
        if not sig_dir.is_dir():
            continue
        meta_path = sig_dir / "meta.json"
        reproducer_path = sig_dir / "reproducer.xml"
        sanitizer_path = sig_dir / "sanitizer_report.txt"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        input_text = reproducer_path.read_text(encoding="utf-8") if reproducer_path.exists() else ""
        stderr_text = sanitizer_path.read_text(encoding="utf-8") if sanitizer_path.exists() else ""
        sig = sig_dir.name
        signal_name = meta.get("signal", "unknown")
        summary = stderr_text.strip().splitlines()[0] if stderr_text.strip() else signal_name
        crashes.append({
            "signature": sig,
            "code": meta.get("code", 3),
            "signal_name": signal_name,
            "summary": summary,
            "input_text": input_text,
            "stderr_text": stderr_text,
            "path": sig_dir,
        })
    return crashes


def save_crash_record(
    crash_dir: Path,
    input_text: str,
    stderr_text: str,
    signal_name: str,
    code: int,
) -> Path:
    """
    Save a single crash record into its signature-named directory.

    If the signature directory already exists, checks whether the new
    reproducer is meaningfully different (e.g. shorter after minimization)
    before deciding to replace or store as an additional variant.

    Returns the path to the directory created/used.
    """
    sig = signature_for(stderr_text, signal_name, input_text)
    sig_dir = crash_dir / sig

    if sig_dir.exists():
        existing_repro = sig_dir / "reproducer.xml"
        if existing_repro.exists():
            existing_text = existing_repro.read_text(encoding="utf-8")
            # If the new reproducer is shorter, it's likely a better (minimized) version
            if len(input_text) < len(existing_text):
                logger.info(
                    "Signature %s already exists; replacing reproducer "
                    "(new %d chars < existing %d chars)",
                    sig, len(input_text), len(existing_text),
                )
                existing_repro.write_text(input_text, encoding="utf-8")
                (sig_dir / "sanitizer_report.txt").write_text(
                    stderr_text, encoding="utf-8"
                )
                meta = {"signal": signal_name, "code": code, "timed_out": code == 4}
                (sig_dir / "meta.json").write_text(
                    json.dumps(meta, indent=2), encoding="utf-8"
                )
            else:
                # Store as additional reproducer variant instead of overwriting
                repro_dir = sig_dir / "reproducers"
                repro_dir.mkdir(exist_ok=True)
                variant_idx = len(list(repro_dir.glob("*.xml"))) + 1
                variant_path = repro_dir / f"reproducer_{variant_idx:03d}.xml"
                logger.info(
                    "Signature %s already exists; saving new reproducer "
                    "(%d chars) as variant %s",
                    sig, len(input_text), variant_path.name,
                )
                variant_path.write_text(input_text, encoding="utf-8")
        else:
            # Directory exists but no reproducer yet — write it
            sig_dir.mkdir(parents=True, exist_ok=True)
            (sig_dir / "sanitizer_report.txt").write_text(stderr_text, encoding="utf-8")
            (sig_dir / "reproducer.xml").write_text(input_text, encoding="utf-8")
            meta = {"signal": signal_name, "code": code, "timed_out": code == 4}
            (sig_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    else:
        sig_dir.mkdir(parents=True, exist_ok=True)
        (sig_dir / "sanitizer_report.txt").write_text(stderr_text, encoding="utf-8")
        (sig_dir / "reproducer.xml").write_text(input_text, encoding="utf-8")
        meta = {"signal": signal_name, "code": code, "timed_out": code == 4}
        (sig_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return sig_dir


def deduplicate(crashes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Group crash records by their normalized signature.

    Parameters
    ----------
    crashes : list[dict]
        Each dict must have ``stderr`` (str) and ``input`` (str) keys,
        plus ``code`` and ``label``.

    Returns
    -------
    dict[str, list[dict]]
        Mapping from 16-char signature → list of crashes sharing that signature.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in crashes:
        sig = signature_for(
            c.get("stderr", ""),
            c.get("label"),  # Use label as signal_name
            c.get("input", ""),
        )
        groups.setdefault(sig, []).append(c)
    return groups


# ---------------------------------------------------------------------------
# CLI — quick signature checker
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Usage: python -m triage.dedupe < some_stderr.txt
    raw = sys.stdin.buffer.read()
    sig = sys.argv[1] if len(sys.argv) > 1 else ""
    signal, summary = classify_stderr(raw)
    if sig:
        # Compare against provided signature
        print(f"signal      : {signal}")
        print(f"summary     : {summary}")
        print(f"signature   : {signature_for(raw.decode('utf-8', errors='replace'), signal)}")
        print(f"expected    : {sig}")
    else:
        print(f"signal      : {signal}")
        print(f"summary     : {summary[:120]}")
        frames = normalize_stack(raw.decode("utf-8", errors="replace"))
        print(f"frames      : {frames}")
        print(f"signature   : {signature_for(raw.decode('utf-8', errors='replace'), signal)}")
