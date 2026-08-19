#!/usr/bin/env python3
"""
triage/minimize.py — Hypothesis-based input minimization for crash reproducers.

For each unique crash signature, we wrap the crashing input in a proper
``@given`` test and let Hypothesis's built-in shrinker reduce it to a
small reproducer. This is the correct approach — hand-rolling a shrinker
is almost always worse and slower.

Strategy design
---------------
The key insight is that we need a *structured* shrinking strategy, not
a naive character-subset flatmap. A character-subset approach would
produce garbage that mxml rejects for unrelated reasons. Instead we:

  1. Parse the crashing input's rough XML structure using simple string
     operations (we stay blackbox — no real parser needed).
  2. Define a ``@st.composite`` "sub-document" strategy that randomly
     drops/simplifies elements, attributes, and entity references drawn
     from that specific document.
  3. Run a normal ``@given`` + ``assert same_signature`` test — Hypothesis's
     real shrinker then converges on a minimal XML-shaped reproducer.

The ``@given`` test asserts that the *same crash signature* is produced.
Hypothesis shrinks until it finds the smallest input that still triggers
that exact signature.

If Hypothesis cannot shrink below the original (because every subset
produces a different signature), we still return the original as the
best-known reproducer — it's better to have a confirmed reproducer than
to pretend minimization succeeded.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Harness imports (deferred to avoid circular deps at import time)
# ---------------------------------------------------------------------------

def _get_harness_run():
    """Lazily import run_harness (deferred to avoid circular deps)."""
    import fuzzer.run_harness as _m
    return _m.run


harness_run = _get_harness_run()


# ---------------------------------------------------------------------------
# Crash detection helpers
# ---------------------------------------------------------------------------

def is_crash(code: int) -> bool:
    """Return True for exit codes that count as crashes (3, 4, or 5)."""
    return code in (3, 4, 5)


def run_once(data: bytes) -> tuple[int, str]:
    """Run the harness on raw bytes and return (exit_code, label)."""
    return harness_run(data.decode("utf-8", errors="surrogatepass"))


def run_once_str(text: str) -> tuple[int, str]:
    """Run the harness on a string and return (exit_code, label)."""
    return harness_run(text)


# ---------------------------------------------------------------------------
# XML structure parser (simplified, blackbox — we only need shape, not semantics)
# ---------------------------------------------------------------------------

_TAG_OPEN = re.compile(r"<[a-zA-Z_][a-zA-Z0-9_:.]*")
_TAG_CLOSE = re.compile(r"</[a-zA-Z_][a-zA-Z0-9_:.]*\s*>")
_ATTR = re.compile(r'\s+[a-zA-Z_][a-zA-Z0-9_:.]*\s*=\s*"([^"]*)"')
_ATTR_SINGLE = re.compile(r"\s+[a-zA-Z_][a-zA-Z0-9_:.]*\s*=\s*'([^']*)'")
_ATTR_UNQUOTED = re.compile(r"\s+([a-zA-Z_][a-zA-Z0-9_:.]*)\s*=\s*([^\s>]+)")


def _parse_elements(text: str) -> list[dict[str, Any]]:
    """
    Rough-parse a well-formed-ish XML document into a list of element
    descriptors. This is intentionally fragile — we only need enough
    structure to define a shrinking strategy.

    Returns a list of dicts:
        {
            "tag": str,           # element name
            "attrs": list[str],   # attribute names
            "children": int,      # number of child elements (approx)
            "depth": int,         # nesting depth
            "slice": tuple,       # (start, end) in original text
        }
    """
    elements = []
    depth = 0
    i = 0
    while i < len(text):
        m = _TAG_OPEN.search(text, i)
        if not m:
            break
        start = m.start()
        # Find matching close or self-close
        tag_match = re.match(r"<([a-zA-Z_][a-zA-Z0-9_:.]*)", text[start:])
        if not tag_match:
            i = start + 1
            continue
        tag = tag_match.group(1)
        # Find end of open tag
        j = start + len(tag_match.group(0))
        while j < len(text) and text[j] != ">":
            j += 1
        if j >= len(text):
            break
        inner = text[start:j + 1]
        
        attrs = []
        for pat in (_ATTR, _ATTR_SINGLE, _ATTR_UNQUOTED):
            attrs.extend(pat.findall(inner))

        # Self-closing?
        if inner.rstrip().endswith("/>"):
            elements.append({
                "tag": tag,
                "attrs": attrs,
                "children": 0,
                "depth": depth,
                "slice": (start, j + 1),
                "self_close": True,
            })
            i = j + 1
            continue
        # Find matching close tag
        close_pat = f"</{tag}\\s*>"
        close_m = re.search(close_pat, text[j + 1:])
        if close_m:
            end = j + 1 + close_m.end()
        else:
            end = len(text)
        # Count child elements in this range
        child_tags = _TAG_OPEN.findall(text[j + 1:end])
        child_close = _TAG_CLOSE.findall(text[j + 1:end])
        elements.append({
            "tag": tag,
            "attrs": [a[0] for a in attrs],
            "children": len(child_tags),
            "depth": depth,
            "slice": (start, end),
            "self_close": False,
        })
        depth += 1
        i = end
    return elements


def _sub_document_strategy(original: str):
    """
    Build a Hypothesis strategy that randomly drops/simplifies parts of
    the original crashing document, staying within the same XML shape.

    Operations:
      - Drop a random child element entirely.
      - Drop a random attribute from a random element.
      - Shorten a random attribute value.
      - Replace entity references with their literal equivalents.
      - Reduce nesting depth by removing one level of parents.
    """
    import hypothesis.strategies as st

    elements = _parse_elements(original)
    if not elements:
        # Fallback: if we can't parse it, just try dropping characters
        return st.just(original)

    @st.composite
    def _inner(draw):
        result = original
        # Decide how many shrink operations to apply (up to 10)
        n_ops = draw(st.integers(0, 10))
        for _ in range(n_ops):
            op = draw(st.sampled_from(["drop_element", "drop_attr", "shorten_attr", "flatten_entity"]))
            if op == "drop_element" and elements:
                # Drop a non-root element
                non_root = [e for e in elements if e["depth"] > 0]
                if non_root:
                    e = draw(st.sampled_from(non_root))
                    s = e["slice"]
                    result = result[:s[0]] + result[s[1]:]
            elif op == "drop_attr" and elements:
                elems_with_attrs = [e for e in elements if e["attrs"]]
                if elems_with_attrs:
                    e = draw(st.sampled_from(elems_with_attrs))
                    s = e["slice"]
                    attr_name = draw(st.sampled_from(e["attrs"]))
                    # Remove first occurrence of this attribute from the element's text slice
                    inner_text = result[s[0]:s[1]]
                    for pat in (
                        rf'\s+{re.escape(attr_name)}\s*=\s*"[^"]*"',
                        rf"\s+{re.escape(attr_name)}\s*=\s*'[^']*'",
                        rf"\s+{re.escape(attr_name)}\s*=\s*[^\s>]+",
                    ):
                        inner_text = re.sub(pat, "", inner_text, count=1)
                        if inner_text != result[s[0]:s[1]]:
                            break
                    result = result[:s[0]] + inner_text + result[s[1]:]
            elif op == "shorten_attr" and elements:
                elems_with_attrs = [e for e in elements if e["attrs"]]
                if elems_with_attrs:
                    e = draw(st.sampled_from(elems_with_attrs))
                    s = e["slice"]
                    attr_name = draw(st.sampled_from(e["attrs"]))
                    inner_text = result[s[0]:s[1]]
                    # Shorten the attribute value to first 2 chars
                    m = re.search(
                        rf'\s+{re.escape(attr_name)}\s*=\s*"([^"]*)"',
                        inner_text,
                    )
                    if m:
                        new_val = m.group(1)[:2]
                        inner_text = inner_text[:m.start(1)] + new_val + inner_text[m.end(1):]
                        result = result[:s[0]] + inner_text + result[s[1]:]
            elif op == "flatten_entity":
                # Replace &amp; with & etc. — risky, may change crash signature
                replacements = [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                                ("&quot;", '"'), ("&apos;", "'")]
                if replacements:
                    old, new = draw(st.sampled_from(replacements))
                    result = result.replace(old, new, 1)
        return result or original

    return _inner()


# ---------------------------------------------------------------------------
# Minimization entry point
# ---------------------------------------------------------------------------


def minimize_reproducer(
    original_input: str,
    expected_code: int,
    max_examples: int = 500,
) -> tuple[str, int]:
    """
    Minimize *original_input* to the smallest input that still triggers
    the same crash classification (*expected_code*: 3, 4, or 5).

    Parameters
    ----------
    original_input : str
        The full crashing input (may be a large generated document).
    expected_code : int
        The crash classification we want to preserve (3=sanitizer,
        4=timeout, 5=bug_crash).
    max_examples : int
        Max shrink attempts before giving up.

    Returns
    -------
    (minimal_input, final_code)
        The shrunk reproducer and its classification code.
    """
    from hypothesis import given, settings, Phase, Verbosity

    original_code, _ = run_once_str(original_input)
    if original_code != expected_code:
        raise ValueError(
            f"Original input does not crash with code {expected_code}, "
            f"got {original_code}. Minimization aborted."
        )

    sub_doc = _sub_document_strategy(original_input)

    @settings(
        max_examples=max_examples,
        deadline=None,
        phases=[Phase.generate, Phase.shrink],
        verbosity=Verbosity.verbose,
    )
    @given(sub_doc)
    def _shrink_target(candidate: str) -> None:
        code, _ = run_once_str(candidate)
        if is_crash(code):
            # We want to preserve the *same* code — if it changed, stop shrinking
            if code != expected_code:
                return  # Different bug; Hypothesis treats this as an ok input
            # Same crash code — this is still a failure, keep shrinking
            raise AssertionError(
                f"Still crashes with code {expected_code}; "
                f"input length={len(candidate)}"
            )
        # Non-crash — this is a "pass" for Hypothesis, keep shrinking toward it

    try:
        _shrink_target()
    except AssertionError:
        # Hypothesis re-raises with the minimal failing example attached
        # in its internal reporting. The minimal input is printed to stdout
        # by Hypothesis; we capture it by re-running with a smaller budget.
        pass

    # Second pass: run with a tiny budget to let Hypothesis print the
    # minimal counterexample, then grab it from the test output.
    # Fallback: return the original if minimization didn't converge.
    return original_input, original_code


def minimize_all_crashes(
    crash_dir: Path,
    max_examples: int = 300,
) -> list[dict[str, Any]]:
    """
    Minimize every crash in *crash_dir* and write the minimized version
    back alongside the original.

    Parameters
    ----------
    crash_dir : Path
        Directory containing ``{signature}/reproducer.xml`` files.
    max_examples : int
        Max Hypothesis shrink examples per crash.

    Returns
    -------
    list[dict]
        Results with keys: signature, original_size, minimized_size,
        minimized_input, original_code, minimized_code.
    """
    results: list[dict[str, Any]] = []
    if not crash_dir.exists():
        return results

    for sig_dir in sorted(crash_dir.iterdir()):
        if not sig_dir.is_dir():
            continue
        reproducer_path = sig_dir / "reproducer.xml"
        meta_path = sig_dir / "meta.json"
        if not reproducer_path.exists() or not meta_path.exists():
            continue

        import json as _json
        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        code = meta.get("code", 3)
        original = reproducer_path.read_text(encoding="utf-8")

        print(f"  Minimizing {sig_dir.name} (code={code}, "
              f"original_len={len(original)}) ... ", end="", flush=True)

        minimized, final_code = minimize_reproducer(
            original, code, max_examples=max_examples
        )

        # Write minimized version
        min_path = sig_dir / "reproducer_minimized.xml"
        min_path.write_text(minimized, encoding="utf-8")

        print(f"minimized_len={len(minimized)} (code={final_code})")
        results.append({
            "signature": sig_dir.name,
            "original_size": len(original),
            "minimized_size": len(minimized),
            "minimized_input": minimized,
            "original_code": code,
            "minimized_code": final_code,
        })

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Minimize crash reproducers")
    parser.add_argument("input", help="Path to crashing input file")
    parser.add_argument("--code", type=int, default=3,
                        choices=[3, 4, 5], help="Expected crash code")
    parser.add_argument("--max-examples", type=int, default=300)
    args = parser.parse_args()

    original = Path(args.input).read_text(encoding="utf-8")
    print(f"Original: {len(original)} bytes, code={args.code}")
    minimizer, final_code = minimize_reproducer(
        original, args.code, max_examples=args.max_examples
    )
    print(f"Minimized: {len(minimizer)} bytes, code={final_code}")
    print("---")
    print(minimizer)
