#!/usr/bin/env python3
"""agentic_loop.py — LLM-driven agentic fuzzing loop for mxml.

Sequence per iteration:
  1. Build prompt (seed on first iteration, refine afterwards) from grammar,
     documented adaptations, and prior results.
  2. Call LLM to generate (or revise) a Hypothesis strategy.
  3. Save the generated strategy to ``strategies/iteration_N.py``.
  4. Execute the strategy against the C harness via ``run_harness.run()``.
  5. Compute proxy signals (acceptance rate, grammar-coverage, crash signatures).
  6. Log iteration to ``logs/iteration_N.jsonl``.
  7. If a crash/signature is found, stop and report; otherwise refine and loop.

Run:
    python -m fuzzer.agentic_loop [--max-iterations N] [--seed-strategy PATH]
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
FUZZER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT  # Agentic-Fuzzing/
HARNESS_DIR = PROJECT_ROOT / "harness"
GRAMMAR_DIR = PROJECT_ROOT / "grammar"
# Primary LLM-facing adaptations reference (source-verified grammar↔mxml comparison).
# Kept as ADAPTATIONS.md; README.md is the human-readable documentation version.
ADAPTATIONS_FILE = "ADAPTATIONS.md"
STRATEGIES_DIR = FUZZER_DIR / "strategies"
LOGS_DIR = FUZZER_DIR / "logs"
PROMPTS_DIR = FUZZER_DIR / "prompts"

# ── imports (deferred to avoid circular deps) ────────────────────────────────


def _import_run_harness():
    sys.path.insert(0, str(FUZZER_DIR))
    from run_harness import run as harness_run

    return harness_run


def _import_llm_client():
    sys.path.insert(0, str(FUZZER_DIR))
    from llm_client import LLMClient

    return LLMClient


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── grammar / adaptations loading ────────────────────────────────────────────


def load_grammar() -> str:
    parser = _load_text(GRAMMAR_DIR / "original" / "XMLParser.g4")
    lexer = _load_text(GRAMMAR_DIR / "original" / "XMLLexer.g4")
    return f"=== XMLParser.g4 ===\n{parser}\n\n=== XMLLexer.g4 ===\n{lexer}"


def load_adaptations() -> str:
    path = GRAMMAR_DIR / ADAPTATIONS_FILE
    if not path.exists():
        # Fallback to README.md if ADAPTATIONS.md doesn't exist yet
        path = GRAMMAR_DIR / "README.md"
    return _load_text(path)


# ── strategy execution ────────────────────────────────────────────────────────


def _fix_common_llm_errors(code: str) -> str:
    """Patch common LLM-generated strategy mistakes before execution.

    The LLM sometimes hallucinates Hypothesis API names or wraps output in
    markdown. This function normalises the most frequent failures so the
    strategy can still be tested instead of being silently skipped.
    """
    import re as _re

    # Strip markdown code fences if the LLM wrapped the output
    code = _re.sub(r"^```(?:python)?\s*\n", "", code, flags=_re.MULTILINE)
    code = _re.sub(r"\n```\s*$", "", code, flags=_re.MULTILINE)

    # st.frequency(...) → st.one_of(...) with equal weights (safest fallback)
    # Pattern: st.frequency( (w1, strat1), (w2, strat2), ... )
    # We need to strip the weight tuples and keep only the strategy expressions.
    if "st.frequency" in code:
        idx = code.index("st.frequency")
        # Find opening paren
        start = idx + len("st.frequency")
        while start < len(code) and code[start] in " \t\n":
            start += 1
        assert code[start] == "(", f"Expected '(' after st.frequency, got {code[start]!r}"
        # Find matching closing paren
        depth = 0
        end = start
        for j in range(start, len(code)):
            if code[j] == "(":
                depth += 1
            elif code[j] == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        inner = code[start + 1 : end]
        # Split on top-level commas (respecting nested parens/brackets/braces)
        args: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in inner:
            if ch in "([{":
                depth += 1
                current.append(ch)
            elif ch in ")]}":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            args.append("".join(current).strip())
        # Strip weight tuples: "(82, well_formed_document())" → "well_formed_document()"
        cleaned: list[str] = []
        for arg in args:
            # Match leading "(NUMBER, " and trailing ")"
            m = _re.match(r"^\(\s*\d+\s*,\s*(.+)\)\s*$", arg)
            if m:
                cleaned.append(m.group(1).strip())
            else:
                cleaned.append(arg)
        replacement = "st.one_of(\n    " + ",\n    ".join(cleaned) + "\n)"
        code = code[:idx] + replacement + code[end + 1 :]

    return code


def execute_strategy(
    strategy_code: str,
    num_examples: int = 200,
    max_examples_per_run: int = 500,
    timeout_per_example: float = 4.5,
    capture_stderr: bool = False,
) -> dict[str, Any]:
    """Run a Hypothesis strategy and collect classification stats.

    Returns a dict with keys:
        total, valid, invalid, harness_error, sanitizer, timeout, bug_crash,
        acceptance_rate, examples — list of (input_text, code, label[, stderr])
        tuples. Stderr is included only when capture_stderr=True and the example
        crashed (codes 3, 4, 5).
    """
    harness_run = _import_run_harness()

    # Fix common LLM-generated errors before writing to disk
    strategy_code = _fix_common_llm_errors(strategy_code)

    # Write strategy to a temp module so we can import it
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=str(STRATEGIES_DIR), delete=False, encoding="utf-8"
    ) as f:
        f.write(strategy_code)
        strategy_path = f.name

    strategy_module_name = Path(strategy_path).stem
    sys.path.insert(0, str(STRATEGIES_DIR))

    try:
        import importlib

        mod = importlib.import_module(strategy_module_name)
        xml_strategy = getattr(mod, "xml_strategy", None)
        if xml_strategy is None:
            raise AttributeError(
                f"Module {strategy_module_name} has no attribute 'xml_strategy'"
            )
    except Exception as exc:
        return {
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "harness_error": 0,
            "sanitizer": 0,
            "timeout": 0,
            "bug_crash": 0,
            "acceptance_rate": 0.0,
            "examples": [],
            "error": str(exc),
        }
    finally:
        # Clean up the temp import
        sys.path.remove(str(STRATEGIES_DIR))
        try:
            del sys.modules[strategy_module_name]
        except KeyError:
            pass
        os.unlink(strategy_path)

    import inspect
    from hypothesis import strategies as _st
    from hypothesis.strategies._internal.core import CompositeStrategy

    def _unwrap_composite(candidate):
        """Walk closure chain to find the draw-taking function inside
        a @st.composite wrapper. hypothesis wraps it twice; we need the
        original (draw) -> str function to build a working CompositeStrategy."""
        seen = set()
        queue = [candidate]
        while queue:
            fn = queue.pop(0)
            if id(fn) in seen:
                continue
            seen.add(id(fn))
            try:
                sig = inspect.signature(fn)
                params = list(sig.parameters.values())
                if params and params[0].name == "draw":
                    return fn
            except (ValueError, TypeError):
                pass
            if hasattr(fn, "__closure__") and fn.__closure__:
                for cell in fn.__closure__:
                    try:
                        inner = cell.cell_contents
                        if callable(inner):
                            queue.append(inner)
                    except ValueError:
                        pass
            # Also check __wrapped__ (used by some decorators)
            if hasattr(fn, "__wrapped__") and callable(getattr(fn, "__wrapped__", None)):
                queue.append(fn.__wrapped__)
        return candidate

    def _generate_one():
        # Support @st.composite (function wrapping draw) and SearchStrategy
        # (has .example()). For composites, extract the original draw-taking
        # function via closure walk and build a CompositeStrategy directly.
        try:
            # Case 1: it's a proper SearchStrategy with .example()
            if hasattr(xml_strategy, "example"):
                return xml_strategy.example()
            # Case 2: it's a @st.composite wrapped function — unwrap and build
            # a CompositeStrategy from the inner draw-taking function
            if callable(xml_strategy):
                inner = _unwrap_composite(xml_strategy)
                if inner is not xml_strategy:  # we found an inner function
                    return CompositeStrategy(inner, (), {}).example()
            # Case 3: it's something else unexpected
            raise TypeError(
                f"xml_strategy is {type(xml_strategy).__name__}, "
                f"expected SearchStrategy or @st.composite function"
            )
        except Exception:
            return None

    results = {"examples": []}
    for counter in range(num_examples):
        example = _generate_one()
        if example is None:
            continue
        # Some Hypothesis examples contain lone surrogate code points which
        # cannot be encoded as UTF-8. Skip them — they're never useful for
        # hitting mxml and would silently kill the loop.
        try:
            example.encode("utf-8")
        except (UnicodeEncodeError, AttributeError):
            continue

        if capture_stderr:
            code, label, stderr_text = harness_run(example, return_stderr=True)
        else:
            code, label = harness_run(example)
            stderr_text = ""

        results.setdefault(code, 0)
        results[code] += 1
        if capture_stderr and code in (3, 4, 5):
            results["examples"].append((example, code, label, stderr_text))
        else:
            results["examples"].append((example, code, label))

        if len(results["examples"]) >= max_examples_per_run:
            break

    total = sum(v for k, v in results.items() if k not in ("examples", "error"))
    valid = results.get(0, 0)
    results["total"] = total
    results["acceptance_rate"] = valid / total if total > 0 else 0.0
    return results


# ── grammar coverage (proxy signal) ──────────────────────────────────────────

GRAMMAR_PRODS = [
    ("element_empty", r"<[^>/\s][^>]*\s*/>"),
    ("element_nested", r"<[^>/\s][^>]*>.*?</[^>/\s]+>"),
    ("attr_quoted_double", r'[^<\s][^=]*="[^"]*"'),
    ("attr_quoted_single", r"[^<\s][^=]*='[^']*'"),
    ("comment", r"<!--.*?-->"),
    ("cdata", r"<!\[CDATA\[.*?\]\]>"),
    ("pi", r"<\?[^\?]*\?>"),
    ("xml_decl", r"<\?xml[^>]*\?>"),
    ("entity_ref_builtin", r"&amp;|&lt;|&gt;|&quot;|&apos;"),
    ("char_ref_decimal", r"&#\d+;"),
    ("char_ref_hex", r"&#x[0-9a-fA-F]+;"),
    ("deep_nesting", r"<a(<b(<c(<d)>)>)>"),
]

import re as _re


def compute_grammar_coverage(examples: list[Any]) -> dict[str, int]:
    """Count which grammar productions appear in the generated examples.

    Each example may be a 3-tuple ``(input, code, label)`` or a 4-tuple
    ``(input, code, label, stderr)``; only the input text is used here.
    """
    counts: dict[str, int] = {prod: 0 for prod, _ in GRAMMAR_PRODS}
    for tup in examples:
        text = tup[0] if tup else ""
        if not text:
            continue
        for name, pattern in GRAMMAR_PRODS:
            if _re.search(pattern, text):
                counts[name] += 1
    total_with_coverage = sum(1 for c in counts.values() if c > 0)
    return {**counts, "covered_prods": total_with_coverage, "total_prods": len(GRAMMAR_PRODS)}


def compute_crash_signatures(results: dict[str, Any]) -> list[dict[str, str]]:
    """Extract unique crash/timeout/sanitizer examples."""
    sigs: list[dict[str, str]] = []
    seen: set[tuple[int, str]] = set()
    for tup in results.get("examples", []):
        text = tup[0]
        code = tup[1]
        label = tup[2]
        if code not in (3, 4, 5):
            continue
        key = (code, text[:200])
        if key in seen:
            continue
        seen.add(key)
        sigs.append({"code": code, "label": label, "input_preview": text[:300]})
    return sigs


# ── iteration logging ─────────────────────────────────────────────────────────


def log_iteration(
    iteration: int,
    strategy_code: str,
    results: dict[str, Any],
    grammar_coverage: dict[str, int],
    crash_sigs: list[dict[str, str]],
    llm_provider: Optional[str],
    prompt_type: str,
) -> Path:
    """Append a JSONL record to logs/iteration_N.jsonl and return the path."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"iteration_{iteration:04d}.jsonl"

    # Examples may include stderr (4-tuple) or not (3-tuple). Normalise to
    # a JSON-serialisable shape: store the input + code only, plus a parallel
    # stderr file per crash in the triage/crashes/ dir.
    examples_for_log = []
    for tup in results.get("examples", []):
        if len(tup) == 4:
            text, code, label, _stderr = tup
        else:
            text, code, label = tup
        # Ensure text is clean UTF-8 for JSON serialization
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        examples_for_log.append({"input": text, "code": code, "label": label})

    # Ensure strategy_code is clean UTF-8
    if isinstance(strategy_code, bytes):
        strategy_code = strategy_code.decode("utf-8", errors="replace")

    record = {
        "iteration": iteration,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_type": prompt_type,
        "llm_provider": llm_provider,
        "strategy_code": strategy_code,
        "results": {
            "total": results.get("total", 0),
            "valid": results.get(0, 0),
            "invalid": results.get(1, 0),
            "harness_error": results.get(2, 0),
            "sanitizer": results.get(3, 0),
            "timeout": results.get(4, 0),
            "bug_crash": results.get(5, 0),
            "acceptance_rate": results.get("acceptance_rate", 0.0),
        },
        "grammar_coverage": grammar_coverage,
        "crash_signatures": crash_sigs,
        "examples": examples_for_log,
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")

    return log_path


# ── convergence check ────────────────────────────────────────────────────────


def has_converged(
    prev_results: dict[str, Any],
    curr_results: dict[str, Any],
    max_iters: int,
    iteration: int,
    loop_elapsed: float,
    wall_clock_cap_sec: float = 600.0,
    cost_per_example: float = 0.001,
) -> bool:
    """Decide whether to stop early.

    Convergence criteria (any one triggers stop):
      - Max iterations reached
      - Wall-clock cap exceeded
      - Estimated LLM cost exceeds the $5 budget
      - Acceptance rate hasn't moved for two consecutive iterations (stall)
    """
    if iteration >= max_iters:
        return True
    # Budget stop: $5 ≈ ~5M input tokens at current small-model pricing.
    # Coarse proxy: $0.001 per example × total examples generated so far.
    total_examples_so_far = (
        prev_results.get("total", 0) + curr_results.get("total", 0)
    )
    est_cost = total_examples_so_far * cost_per_example
    if est_cost >= 5.0:
        print(f"\n  → LLM cost budget (~$5) exhausted (est. ${est_cost:.2f}); stopping.")
        return True
    if loop_elapsed >= wall_clock_cap_sec:
        return True
    # Stall: if the strategy is no longer improving acceptance rate
    prev_accept = prev_results.get("acceptance_rate", 0.0)
    curr_accept = curr_results.get("acceptance_rate", 0.0)
    if iteration > 1 and abs(curr_accept - prev_accept) < 0.02:
        return True
    return False


# ── summary for LLM ──────────────────────────────────────────────────────────


def build_summary(results: dict[str, Any]) -> str:
    """Human-readable summary of a run for the LLM refine prompt."""
    total = results.get("total", 0)
    valid = results.get(0, 0)
    invalid = results.get(1, 0)
    harness_err = results.get(2, 0)
    sanitizer = results.get(3, 0)
    timeout = results.get(4, 0)
    bug_crash = results.get(5, 0)
    accept_rate = results.get("acceptance_rate", 0.0)

    lines = [
        f"- Total examples run: {total}",
        f"- Acceptance rate: {accept_rate:.1%} ({valid}/{total})",
        f"- Valid (code 0): {valid}",
        f"- Invalid / rejected (code 1): {invalid}",
        f"- Harness error (code 2): {harness_err}",
        f"- Sanitizer crash (code 3): {sanitizer}",
        f"- Timeout (code 4): {timeout}",
        f"- Bug crash (code 5): {bug_crash}",
    ]
    if results.get("error"):
        lines.insert(0, f"Strategy execution error: {results['error']}")
    return "\n".join(lines)


# ── main loop ────────────────────────────────────────────────────────────────


# ── triage integration ───────────────────────────────────────────────────────


def _import_trage():
    sys.path.insert(0, str(FUZZER_DIR.parent / "triage"))
    import triage.run as tr
    return tr


def run_loop(
    max_iterations: int = 5,
    seed_strategy_path: Optional[str] = None,
    num_examples: int = 200,
    run_triage: bool = True,
    wall_clock_cap_sec: float = 600.0,
) -> dict[str, Any]:
    """Run the agentic fuzzing loop with optional triage.

    Args:
        max_iterations: maximum refine cycles to perform
        seed_strategy_path: optional path to an existing strategy to seed the loop
        num_examples: how many examples to generate per iteration
        run_triage: whether to run crash triage after the loop
    Returns:
        Summary dict with final results and log path
    """
    print("=" * 60)
    print("Agentic Fuzzing Loop — mxml")
    print("=" * 60)

    grammar = load_grammar()
    adaptations = load_adaptations()

    client = _import_llm_client()()
    harness_run = _import_run_harness()

    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Live crash directory: every sanitizer/timeout/bug_crash input is saved
    # here as soon as it happens, so triage can read crashes from disk instead
    # of re-running the harness (and so that a crashed loop leaves a record).
    CRASH_DIR = FUZZER_DIR.parent / "triage" / "crashes"
    CRASH_DIR.mkdir(parents=True, exist_ok=True)

    # Track all crash examples with stderr for triage
    all_crashes: list[dict[str, Any]] = []

    def _save_crash_live(input_text: str, code: int, label: str, stderr: str) -> None:
        """Persist a crash immediately, using dedupe's save_crash_record."""
        try:
            sys.path.insert(0, str(FUZZER_DIR.parent / "triage"))
            from triage.dedupe import save_crash_record
            save_crash_record(
                crash_dir=CRASH_DIR,
                input_text=input_text,
                stderr_text=stderr or "",
                signal_name=label,
                code=code,
            )
        except Exception as exc:
            # Don't let a triage-save failure abort the loop
            print(f"  [warn] failed to save crash: {exc}")

    # Load seed strategy or generate one
    strategy_code = ""
    if seed_strategy_path and Path(seed_strategy_path).exists():
        strategy_code = Path(seed_strategy_path).read_text(encoding="utf-8")
        print(f"[loop] Using seed strategy from {seed_strategy_path}")
    else:
        seed_prompt = _load_prompt("seed_prompt.md").format(
            grammar=grammar, adaptations=adaptations
        )
        print("[loop] Generating seed strategy via LLM ...")
        try:
            strategy_code = client.chat(
                [
                    {"role": "system", "content": "You are a careful XML strategy generator."},
                    {"role": "user", "content": seed_prompt},
                ],
                timeout=120.0,
            )
        except Exception as exc:
            print(f"[loop] LLM seed call failed: {exc}")
            return {"error": str(exc), "iteration": 0}

        # Save seed strategy
        seed_path = STRATEGIES_DIR / "iteration_0000.py"
        seed_path.write_text(strategy_code, encoding="utf-8")
        print(f"[loop] Seed strategy saved → {seed_path}")

    prev_results: dict[str, Any] = {}
    final_results: dict[str, Any] = {}
    loop_start = time.time()

    for iteration in range(1, max_iterations + 1):
        # Wall-clock backstop: 10-minute cap on the full run
        if (time.time() - loop_start) >= wall_clock_cap_sec:
            print(f"\n  → Wall-clock cap ({wall_clock_cap_sec:.0f}s) reached; stopping.")
            break

        print(f"\n{'─' * 60}")
        print(f"[loop] Iteration {iteration}")
        print(f"{'─' * 60}")

        t0 = time.time()
        results = execute_strategy(
            strategy_code,
            num_examples=num_examples,
            capture_stderr=True,
        )
        elapsed = time.time() - t0

        grammar_coverage = compute_grammar_coverage(results.get("examples", []))
        crash_sigs = compute_crash_signatures(results)

        # Collect crash examples with full stderr for triage, and persist
        # them to disk immediately so triage has access to the full reports.
        for tup in results.get("examples", []):
            # examples are (input, code, label) or (input, code, label, stderr)
            if len(tup) == 4:
                text, code, label, stderr_text = tup
            else:
                text, code, label = tup
                stderr_text = ""
            if code in (3, 4, 5):
                all_crashes.append({
                    "input": text,
                    "code": code,
                    "label": label,
                    "iteration": iteration,
                    "stderr": stderr_text,
                })
                _save_crash_live(text, code, label, stderr_text)

        log_path = log_iteration(
            iteration=iteration,
            strategy_code=strategy_code,
            results=results,
            grammar_coverage=grammar_coverage,
            crash_sigs=crash_sigs,
            llm_provider=client.active_provider,
            prompt_type="seed" if iteration == 1 else "refine",
        )

        accept_rate = results.get("acceptance_rate", 0.0)
        bug_count = results.get(5, 0)
        san_count = results.get(3, 0)
        timeout_count = results.get(4, 0)

        print(f"  provider       : {client.active_provider or 'N/A'}")
        print(f"  total          : {results.get('total', 0)}  (in {elapsed:.1f}s)")
        print(f"  accept rate    : {accept_rate:.1%}")
        print(f"  valid(0)       : {results.get(0, 0)}")
        print(f"  invalid(1)     : {results.get(1, 0)}")
        print(f"  sanitizer(3)   : {san_count}")
        print(f"  timeout(4)     : {timeout_count}")
        print(f"  bug_crash(5)   : {bug_count}")
        print(f"  grammar cov    : {grammar_coverage.get('covered_prods', 0)}/{grammar_coverage.get('total_prods', 0)}")
        print(f"  log            : {log_path}")
        if san_count or timeout_count or bug_count:
            print(f"  ★ {san_count + timeout_count + bug_count} crash candidate(s) saved to triage/crashes/")

        # Per assignment spec: don't stop on first crash — run every iteration
        # within the budget to gather a *family* of related bugs, not just the
        # first one. Stop only on wall-clock cap, max iterations, or budget.
        final_results = results
        final_results["_log_path"] = str(log_path)
        final_results["_iteration"] = iteration

        # Convergence: stop only if budget or wall-clock reached, or if
        # acceptance rate has stalled for two consecutive iterations.
        if has_converged(
            prev_results, results, max_iterations, iteration,
            loop_elapsed=(time.time() - loop_start),
            wall_clock_cap_sec=wall_clock_cap_sec,
        ):
            print("\n  → Converged; stopping loop.")
            break

        # ── refine ──────────────────────────────────────────────────────
        refine_prompt = _load_prompt("refine_prompt.md").format(
            prev_code=strategy_code,
            prev_summary=build_summary(results),
        )
        print(f"\n  Refining strategy via LLM ...")
        try:
            strategy_code = client.chat(
                [
                    {
                        "role": "system",
                        "content": "You are a careful XML strategy generator. Output only valid Python.",
                    },
                    {"role": "user", "content": refine_prompt},
                ],
                timeout=120.0,
            )
        except Exception as exc:
            print(f"  [loop] LLM refine call failed: {exc}")
            break

        # Save refined strategy
        refine_path = STRATEGIES_DIR / f"iteration_{iteration:04d}_refined.py"
        refine_path.write_text(strategy_code, encoding="utf-8")
        print(f"  Refined strategy saved → {refine_path}")

        prev_results = dict(results)

    loop_elapsed = time.time() - loop_start

    # ── write loop summary ──────────────────────────────────────────────────
    summary_md = LOGS_DIR / "loop_summary.md"
    with open(summary_md, "w", encoding="utf-8") as f:
        f.write("# Agentic Loop Summary\n\n")
        f.write(f"**Iterations:** {final_results.get('_iteration', 0)}\n\n")
        f.write(f"**LLM provider:** {client.active_provider or 'N/A'}\n\n")
        f.write(f"**Wall-clock:** {loop_elapsed:.1f}s\n\n")
        f.write("## Final Results\n\n")
        f.write(build_summary(final_results))
        f.write("\n\n")
        f.write("## Log Files\n\n")
        for p in sorted(LOGS_DIR.glob("iteration_*.jsonl")):
            f.write(f"- `{p.name}`\n")
    print(f"\n[loop] Summary written → {summary_md}")

    # ── triage ─────────────────────────────────────────────────────────────
    # Only run triage when crashes were actually found — skip if the loop
    # finished with zero crash candidates to avoid unnecessary work.
    crash_dir = Path(__file__).resolve().parent.parent / "triage" / "crashes"
    has_crashes = len(all_crashes) > 0 or (crash_dir.exists() and any(crash_dir.iterdir()))
    if run_triage and has_crashes:
        print(f"\n{'=' * 60}")
        print("Running crash triage ...")
        print(f"{'=' * 60}")
        try:
            triage_mod = _import_trage()
            triage_result = triage_mod.run_triage(
                crash_dir=crash_dir,
                num_examples=num_examples,
            )
            final_results["_triage"] = triage_result
            print(f"\n[loop] Triage complete: "
                  f"{triage_result.get('unique_sigs', 0)} unique sigs, "
                  f"{triage_result.get('confirmed', 0)} confirmed")
        except Exception as exc:
            print(f"[loop] Triage failed: {exc}")
            final_results["_triage_error"] = str(exc)
    else:
        print("\nNo crashes found; triage skipped.")

    final_results["_loop_elapsed"] = loop_elapsed
    final_results["_total_crashes"] = len(all_crashes)
    return final_results


# ── CLI entry point ──────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agentic fuzzing loop for mxml")
    parser.add_argument("--max-iterations", type=int, default=5,
                        help="Max refine cycles (hard cap: 5 per assignment)")
    parser.add_argument("--seed-strategy", type=str, default=None, help="Path to initial strategy")
    parser.add_argument("--num-examples", type=int, default=200,
                        help="Examples per iteration (max 500 per assignment)")
    parser.add_argument("--no-triage", action="store_true", help="Skip crash triage after loop")
    args = parser.parse_args()

    # Enforce assignment constraints
    max_iterations = min(args.max_iterations, 5)
    num_examples = min(args.num_examples, 500)
    if args.max_iterations > 5:
        print(f"[loop] Capping max-iterations to 5 (assignment constraint)")
    if args.num_examples > 500:
        print(f"[loop] Capping num-examples to 500 (assignment constraint)")

    result = run_loop(
        max_iterations=max_iterations,
        seed_strategy_path=args.seed_strategy,
        num_examples=num_examples,
        run_triage=not args.no_triage,
    )
    sys.exit(0 if result.get(5, 0) == 0 else 1)
