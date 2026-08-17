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
    readme = _load_text(GRAMMAR_DIR / "README.md")
    # Extract the "Documented Adaptations" / feature table section
    # We take the whole file; the prompt template will slot it in.
    return readme


# ── strategy execution ────────────────────────────────────────────────────────


def execute_strategy(
    strategy_code: str,
    num_examples: int = 200,
    max_examples_per_run: int = 50,
    timeout_per_example: float = 4.5,
) -> dict[str, Any]:
    """Run a Hypothesis strategy and collect classification stats.

    Returns a dict with keys:
        total, valid, invalid, harness_error, sanitizer, timeout, bug_crash,
        acceptance_rate, examples — list of (input_text, code, label) tuples
    """
    harness_run = _import_run_harness()

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
        return candidate

    def _generate_one():
        # Support @st.composite (function wrapping draw) and SearchStrategy
        # (has .example()). For composites, extract the original draw-taking
        # function via closure walk and build a CompositeStrategy directly.
        try:
            if callable(xml_strategy) and not hasattr(xml_strategy, "example"):
                inner = _unwrap_composite(xml_strategy)
                return CompositeStrategy(inner, (), {}).example()
            return xml_strategy.example()
        except Exception:
            return None

    results = {"examples": []}
    for counter in range(num_examples):
        example = _generate_one()
        if example is None:
            continue

        code, label = harness_run(example)
        results.setdefault(code, 0)
        results[code] += 1
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


def compute_grammar_coverage(examples: list[tuple[str, int, str]]) -> dict[str, int]:
    """Count which grammar productions appear in the generated examples."""
    counts: dict[str, int] = {prod: 0 for prod, _ in GRAMMAR_PRODS}
    for text, _, _ in examples:
        for name, pattern in GRAMMAR_PRODS:
            if _re.search(pattern, text):
                counts[name] += 1
    total_with_coverage = sum(1 for c in counts.values() if c > 0)
    return {**counts, "covered_prods": total_with_coverage, "total_prods": len(GRAMMAR_PRODS)}


def compute_crash_signatures(results: dict[str, Any]) -> list[dict[str, str]]:
    """Extract unique crash/timeout/sanitizer examples."""
    sigs: list[dict[str, str]] = []
    seen: set[tuple[int, str]] = set()
    for text, code, label in results.get("examples", []):
        if code not in (3, 4, 5):
            continue
        # Truncate text for key; use first 200 chars
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
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return log_path


# ── convergence check ────────────────────────────────────────────────────────


def has_converged(
    prev_results: dict[str, Any],
    curr_results: dict[str, Any],
    max_iters: int,
    iteration: int,
) -> bool:
    """Decide whether to stop early.

    Convergence criteria (any one triggers stop):
      - Max iterations reached
      - A bug crash (code 5) was found
      - Acceptance rate dropped below 0.01 for two consecutive iterations
    """
    if iteration >= max_iters:
        return True
    if curr_results.get(5, 0) > 0:
        return True  # bug found — stop and report
    # Stability: if acceptance rate hasn't changed much and no new crashes
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


def run_loop(
    max_iterations: int = 10,
    seed_strategy_path: Optional[str] = None,
    num_examples: int = 200,
) -> dict[str, Any]:
    """Run the agentic fuzzing loop.

    Args:
        max_iterations: maximum refine cycles to perform
        seed_strategy_path: optional path to an existing strategy to seed the loop
        num_examples: how many examples to generate per iteration
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

    for iteration in range(1, max_iterations + 1):
        print(f"\n{'─' * 60}")
        print(f"[loop] Iteration {iteration}")
        print(f"{'─' * 60}")

        t0 = time.time()
        results = execute_strategy(
            strategy_code,
            num_examples=num_examples,
        )
        elapsed = time.time() - t0

        grammar_coverage = compute_grammar_coverage(results.get("examples", []))
        crash_sigs = compute_crash_signatures(results)

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

        if bug_count > 0 or san_count > 0:
            print(f"\n  ★ CRASH/SANITIZER FOUND — stopping loop")
            final_results = results
            final_results["_log_path"] = str(log_path)
            final_results["_iteration"] = iteration
            break

        final_results = results
        final_results["_log_path"] = str(log_path)
        final_results["_iteration"] = iteration

        if has_converged(prev_results, results, max_iterations, iteration):
            print("\n  → Converged (no improvement); stopping.")
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

    # ── write loop summary ──────────────────────────────────────────────────
    summary_md = LOGS_DIR / "loop_summary.md"
    with open(summary_md, "w", encoding="utf-8") as f:
        f.write("# Agentic Loop Summary\n\n")
        f.write(f"**Iterations:** {final_results.get('_iteration', 0)}\n\n")
        f.write(f"**LLM provider:** {client.active_provider or 'N/A'}\n\n")
        f.write("## Final Results\n\n")
        f.write(build_summary(final_results))
        f.write("\n\n")
        f.write("## Log Files\n\n")
        for p in sorted(LOGS_DIR.glob("iteration_*.jsonl")):
            f.write(f"- `{p.name}`\n")
    print(f"\n[loop] Summary written → {summary_md}")

    return final_results


# ── CLI entry point ──────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agentic fuzzing loop for mxml")
    parser.add_argument("--max-iterations", type=int, default=10, help="Max refine cycles")
    parser.add_argument("--seed-strategy", type=str, default=None, help="Path to initial strategy")
    parser.add_argument("--num-examples", type=int, default=200, help="Examples per iteration")
    args = parser.parse_args()

    result = run_loop(
        max_iterations=args.max_iterations,
        seed_strategy_path=args.seed_strategy,
        num_examples=args.num_examples,
    )
    sys.exit(0 if result.get(5, 0) == 0 else 1)
