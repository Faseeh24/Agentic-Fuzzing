#!/usr/bin/env python3
"""
agent/orchestrator.py — Main agentic fuzzing loop.

Pipeline states:
  PIPELINE_SUCCESS     — loop completed, no crashes found
  PIPELINE_FAILED      — loop failed due to error
  NO_CRASH_FOUND       — loop completed, no crashes
  CRASH_FOUND          — crashes were found and triaged
  LLM_UNAVAILABLE      — Groq API unavailable
  HARNESS_FAILED       — C harness not built or not executable
"""

from __future__ import annotations

import argparse
import json
import os
import re as _re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Suppress Hypothesis interactive-example warning (we call .example() manually)
warnings.filterwarnings("ignore", category=UserWarning, module="hypothesis")

# ── pipeline states ───────────────────────────────────────────────────────────
PIPELINE_SUCCESS = "PIPELINE_SUCCESS"
PIPELINE_FAILED = "PIPELINE_FAILED"
NO_CRASH_FOUND = "NO_CRASH_FOUND"
CRASH_FOUND = "CRASH_FOUND"
LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
HARNESS_FAILED = "HARNESS_FAILED"

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = Path(__file__).resolve().parent
GENERATOR_DIR = ROOT / "generator"
FUZZER_DIR = ROOT / "fuzzer"
GRAMMAR_DIR = ROOT / "grammar"
LOGS_DIR = FUZZER_DIR / "logs"
STRATEGIES_DIR = FUZZER_DIR / "strategies"
CRASH_DIR = ROOT / "triage" / "crashes"


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def _import_llm_client():
    sys.path.insert(0, str(AGENT_DIR))
    from agent.llm_client import LLMClient
    return LLMClient


def _import_generator():
    sys.path.insert(0, str(GENERATOR_DIR))
    from generator.deterministic_generator import compile_strategy
    from generator.strategy_spec import StrategySpec
    return compile_strategy, StrategySpec


def _import_run_harness():
    sys.path.insert(0, str(FUZZER_DIR))
    from fuzzer.run_harness import run
    return run


def check_harness() -> bool:
    """Check if the C harness is built and executable."""
    candidates = [
        ROOT / "harness" / "mxml_harness",
        ROOT / "harness" / "mxml_harness.exe",
    ]
    return any(p.exists() for p in candidates)


def _extract_json(text: str) -> str:
    """Strip markdown fences and whitespace to extract raw JSON."""
    text = text.strip()
    text = _re.sub(r"^```(?:json)?\s*", "", text, flags=_re.MULTILINE)
    text = _re.sub(r"\s*```\s*$", "", text, flags=_re.MULTILINE)
    return text


def _compute_grammar_coverage(examples: list) -> dict[str, int]:
    """Count which grammar productions appear in the generated examples."""
    GRAMMAR_PRODS = [
        ("element_empty", r"<[^>/\s][^>]*\s*/>"),
        ("element_nested", r"<[^>/\s][^>]*>.*?</[^>/\s]+>"),
        ("attr_quoted_double", r'[^<\s][^=]*="[^"]*"'),
        ("comment", r"<!--.*?-->"),
        ("cdata", r"<!\[CDATA\[.*?\]\]>"),
        ("pi", r"<\?[^\?]*\?>"),
        ("xml_decl", r"<\?xml[^>]*\?>"),
        ("entity_ref_builtin", r"&amp;|&lt;|&gt;|&quot;|&apos;"),
        ("char_ref_decimal", r"&#\d+;"),
        ("char_ref_hex", r"&#x[0-9a-fA-F]+;"),
    ]
    counts: dict[str, int] = {name: 0 for name, _ in GRAMMAR_PRODS}
    for tup in examples:
        text = tup[0] if tup else ""
        if not text:
            continue
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        for name, pattern in GRAMMAR_PRODS:
            if _re.search(pattern, text):
                counts[name] += 1
    covered = sum(1 for c in counts.values() if c > 0)
    return {**counts, "covered_prods": covered, "total_prods": len(GRAMMAR_PRODS)}


def _log_iteration(
    iteration: int,
    spec_text: str,
    results: dict[str, Any],
    feedback: dict[str, Any],
    llm_provider: str,
    prompt_type: str,
) -> Path:
    """Append a JSONL record to logs/iteration_N.jsonl and return the path."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"iteration_{iteration:04d}.jsonl"

    examples_for_log = []
    for tup in results.get("examples", []):
        text = tup[0] if tup else ""
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        code = tup[1] if len(tup) > 1 else 0
        label = tup[2] if len(tup) > 2 else ""
        examples_for_log.append({"input": text, "code": code, "label": label})

    record = {
        "iteration": iteration,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_type": prompt_type,
        "llm_provider": llm_provider,
        "strategy_spec": spec_text,
        "results": {
            "total": results.get("total", 0),
            "valid": results.get(0, 0),
            "invalid": results.get(1, 0),
            "harness_error": results.get(2, 0),
            "sanitizer": results.get(3, 0),
            "timeout": results.get(4, 0),
            "bug_crash": results.get(5, 0),
            "acceptance_rate": results.get("acceptance_rate", 0.0),
            "examples": examples_for_log,
        },
        "feedback": feedback,
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")
    return log_path


def _build_summary(results: dict[str, Any]) -> str:
    total = results.get("total", 0)
    valid = results.get(0, 0)
    return (
        f"- Total examples run: {total}\n"
        f"- Acceptance rate: {results.get('acceptance_rate', 0.0):.1%} ({valid}/{total})\n"
        f"- Valid (code 0): {valid}\n"
        f"- Invalid / rejected (code 1): {results.get(1, 0)}\n"
        f"- Harness error (code 2): {results.get(2, 0)}\n"
        f"- Sanitizer crash (code 3): {results.get(3, 0)}\n"
        f"- Timeout (code 4): {results.get(4, 0)}\n"
        f"- Bug crash (code 5): {results.get(5, 0)}"
    )


def _has_converged(
    prev: dict,
    curr: dict,
    iteration: int,
    total_examples: int,
    loop_elapsed: float,
    wall_clock_cap: float,
    cost_budget: float,
) -> bool:
    if iteration >= 5:
        return True
    if loop_elapsed >= wall_clock_cap:
        return True
    est_cost = total_examples * 0.001
    if est_cost >= cost_budget:
        print(f"  → LLM cost budget (~${cost_budget}) exhausted (est. ${est_cost:.2f}); stopping.")
        return True
    prev_accept = prev.get("acceptance_rate", 0.0)
    curr_accept = curr.get("acceptance_rate", 0.0)
    if iteration > 1 and abs(curr_accept - prev_accept) < 0.02:
        return True
    return False


def _execute_strategy(strategy, num_examples: int, harness_run) -> dict[str, Any]:
    """Run a Hypothesis strategy and collect classification results."""
    results: dict[str, Any] = {"examples": []}
    for _ in range(num_examples):
        try:
            example = strategy.example()
        except Exception:
            continue

        try:
            example.encode("utf-8")
        except (UnicodeEncodeError, AttributeError):
            continue

        code, label = harness_run(example)
        results.setdefault(code, 0)
        results[code] += 1
        results["examples"].append((example, code, label))

        if len(results["examples"]) >= 500:
            break

    total = sum(v for k, v in results.items() if k not in ("examples", "error"))
    valid = results.get(0, 0)
    results["total"] = total
    results["acceptance_rate"] = valid / total if total > 0 else 0.0
    return results


# ── main orchestrator ─────────────────────────────────────────────────────────

def run_orchestrator(
    max_iterations: int = 5,
    num_examples: int = 200,
    wall_clock_cap: float = 600.0,
    cost_budget: float = 5.0,
    run_triage: bool = True,
) -> dict[str, Any]:
    """
    Run the agentic fuzzing loop.

    Returns:
        dict with keys:
          state: one of the PIPELINE_* constants
          iterations: number of iterations completed
          total_examples: total examples generated
          crashes_found: number of unique crash signatures
          llm_provider: "groq" or None
          ... other metadata
    """
    _load_env()

    print("=" * 60)
    print("Agentic Fuzzing Loop — mxml (Groq)")
    print("=" * 60)

    # ── Pre-flight checks ─────────────────────────────────────────────────
    if not check_harness():
        print("[orch] ERROR: C harness not found. Run 'make -C harness all' first.")
        return {"state": HARNESS_FAILED, "error": "harness not built"}

    client = _import_llm_client()()
    if not client.is_available():
        print("[orch] ERROR: Groq API key not set. Set GROQ_API_KEY in .env")
        return {"state": LLM_UNAVAILABLE, "error": "Groq API key missing"}

    compile_strategy, StrategySpec = _import_generator()
    harness_run = _import_run_harness()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    CRASH_DIR.mkdir(parents=True, exist_ok=True)

    all_crashes: list[dict[str, Any]] = []
    loop_start = time.time()
    total_examples = 0
    prev_results: dict[str, Any] = {}
    current_spec_text = ""
    llm_provider = "groq"

    # ── Seed strategy generation ─────────────────────────────────────────
    print("\n[orch] Generating seed strategy via LLM ...")
    seed_prompt_path = AGENT_DIR / "prompts" / "seed_prompt.md"
    seed_prompt = seed_prompt_path.read_text(encoding="utf-8")

    try:
        response = client.chat(
            [
                {"role": "system", "content": "You are a fuzzing strategy planner. Output only valid JSON."},
                {"role": "user", "content": seed_prompt},
            ],
            timeout=120.0,
        )
    except Exception as exc:
        err_str = str(exc)
        print(f"[orch] LLM seed call FAILED: {err_str}")
        if "RATE-LIMITED" in err_str or "quota" in err_str.lower() or "429" in err_str:
            return {"state": LLM_UNAVAILABLE, "error": "Groq rate limit hit", "rate_limited": True}
        return {"state": LLM_UNAVAILABLE, "error": err_str}

    # Parse LLM response as JSON strategy spec
    try:
        json_str = _extract_json(response)
        spec = StrategySpec.model_validate_json(json_str)
        current_spec_text = json.dumps(spec.model_dump(), indent=2)
        print(f"[orch] Seed strategy parsed: {len(spec.objectives)} objectives, "
              f"{len(spec.constraints)} constraints, {len(spec.mutations)} mutations")
    except Exception as exc:
        print(f"[orch] Failed to parse LLM response as StrategySpec: {exc}")
        print(f"[orch] Response was: {response[:500]}")
        return {
            "state": PIPELINE_FAILED,
            "error": f"strategy parsing failed: {exc}",
            "llm_response_preview": response[:500],
        }

    # Save seed spec
    seed_path = STRATEGIES_DIR / "iteration_0000_spec.json"
    seed_path.write_text(current_spec_text, encoding="utf-8")
    print(f"[orch] Seed spec saved → {seed_path}")

    # ── Main loop ────────────────────────────────────────────────────────
    for iteration in range(1, max_iterations + 1):
        # Wall-clock backstop
        if (time.time() - loop_start) >= wall_clock_cap:
            print(f"\n  → Wall-clock cap ({wall_clock_cap:.0f}s) reached; stopping.")
            break

        print(f"\n{'─' * 60}")
        print(f"[orch] Iteration {iteration}")
        print(f"{'─' * 60}")

        # Compile spec → Hypothesis strategy
        try:
            strategy = compile_strategy(spec)
            print(f"[orch] Strategy compiled successfully")
        except Exception as exc:
            print(f"[orch] Strategy compilation FAILED: {exc}")
            # Try to refine with LLM
            try:
                refine_prompt_path = AGENT_DIR / "prompts" / "refine_prompt.md"
                refine_prompt = refine_prompt_path.read_text()
                refine_prompt = refine_prompt.replace(
                    "{prev_spec}", current_spec_text,
                ).replace(
                    "{prev_summary}", f"Compilation error: {exc}",
                ).replace(
                    "{coverage_feedback}", "",
                ).replace(
                    "{crash_sigs}", "",
                )
                response = client.chat([
                    {"role": "system", "content": "You are a fuzzing strategy planner."},
                    {"role": "user", "content": refine_prompt},
                ], timeout=120.0)
                json_str = _extract_json(response)
                spec = StrategySpec.model_validate_json(json_str)
                current_spec_text = json.dumps(spec.model_dump(), indent=2)
                strategy = compile_strategy(spec)
                print(f"[orch] Strategy re-compiled after refinement")
            except Exception as exc2:
                print(f"[orch] Re-compilation also failed: {exc2}")
                continue

        # Execute strategy
        t0 = time.time()
        results = _execute_strategy(strategy, num_examples, harness_run)
        elapsed = time.time() - t0
        total_examples += results.get("total", 0)

        # Compute feedback signals
        feedback = {
            "grammar_coverage": _compute_grammar_coverage(results.get("examples", [])),
            "new_edges": 0,  # Placeholder — real coverage in future
            "crash_count": sum(1 for t in results.get("examples", []) if len(t) > 1 and t[1] in (3, 4, 5)),
        }

        # Log iteration
        log_path = _log_iteration(
            iteration=iteration,
            spec_text=current_spec_text,
            results=results,
            feedback=feedback,
            llm_provider=llm_provider,
            prompt_type="seed" if iteration == 1 else "refine",
        )

        # Print results
        print(f"  provider      : {llm_provider}")
        print(f"  total         : {results.get('total', 0)}  (in {elapsed:.1f}s)")
        print(f"  accept rate   : {results.get('acceptance_rate', 0.0):.1%}")
        print(f"  valid(0)      : {results.get(0, 0)}")
        print(f"  invalid(1)    : {results.get(1, 0)}")
        print(f"  sanitizer(3)  : {results.get(3, 0)}")
        print(f"  timeout(4)    : {results.get(4, 0)}")
        print(f"  bug_crash(5)  : {results.get(5, 0)}")
        print(f"  new_coverage  : {feedback.get('new_edges', 0)} edges")
        print(f"  log           : {log_path}")

        # Collect crashes
        if results.get(3, 0) or results.get(4, 0) or results.get(5, 0):
            crash_count = results.get(3, 0) + results.get(4, 0) + results.get(5, 0)
            print(f"  ★ {crash_count} crash candidate(s) found!")
            for tup in results.get("examples", []):
                if len(tup) >= 3 and tup[1] in (3, 4, 5):
                    all_crashes.append({
                        "input": tup[0],
                        "code": tup[1],
                        "label": tup[2],
                        "iteration": iteration,
                        "stderr": tup[3] if len(tup) == 4 else "",
                    })

        # Convergence check
        if _has_converged(prev_results, results, iteration, total_examples,
                          loop_elapsed=(time.time() - loop_start),
                          wall_clock_cap=wall_clock_cap, cost_budget=cost_budget):
            print("\n  → Converged; stopping loop.")
            break

        # ── Refine ─────────────────────────────────────────────────────
        refine_prompt_path = AGENT_DIR / "prompts" / "refine_prompt.md"
        refine_prompt = refine_prompt_path.read_text()
        refine_prompt = refine_prompt.replace(
            "{prev_spec}", current_spec_text,
        ).replace(
            "{prev_summary}", _build_summary(results),
        ).replace(
            "{coverage_feedback}", json.dumps(feedback, indent=2),
        ).replace(
            "{crash_sigs}", json.dumps([
                {"sig": c.get("input", "")[:100], "code": c["code"]}
                for c in all_crashes[-10:]
            ], indent=2),
        )
        print(f"\n  Refining strategy via LLM ...")
        try:
            response = client.chat([
                {"role": "system", "content": "You are a fuzzing strategy planner. Output only valid JSON."},
                {"role": "user", "content": refine_prompt},
            ], timeout=120.0)
            json_str = _extract_json(response)
            spec = StrategySpec.model_validate_json(json_str)
            current_spec_text = json.dumps(spec.model_dump(), indent=2)
            refine_path = STRATEGIES_DIR / f"iteration_{iteration:04d}_spec.json"
            refine_path.write_text(current_spec_text, encoding="utf-8")
            print(f"  Refined spec saved → {refine_path}")
        except Exception as exc:
            err_str = str(exc)
            if "RATE-LIMITED" in err_str or "quota" in err_str.lower() or "429" in err_str:
                print(f"  [orch] LLM refine call FAILED — rate-limit/quota hit")
            else:
                print(f"  [orch] LLM refine call failed: {exc}")
            break

        prev_results = dict(results)

    loop_elapsed = time.time() - loop_start

    # ── Write summary ────────────────────────────────────────────────────
    summary_md = LOGS_DIR / "loop_summary.md"
    with open(summary_md, "w", encoding="utf-8") as f:
        f.write("# Agentic Loop Summary\n\n")
        final_state = CRASH_FOUND if all_crashes else PIPELINE_SUCCESS
        f.write(f"**State:** {final_state}\n\n")
        f.write(f"**Iterations:** {len(prev_results) + 1}\n\n")
        f.write(f"**LLM provider:** {llm_provider}\n\n")
        f.write(f"**Wall-clock:** {loop_elapsed:.1f}s\n\n")
        f.write(f"**Total examples:** {total_examples}\n\n")
        f.write(f"**Crashes found:** {len(all_crashes)}\n\n")
        f.write("## Log Files\n\n")
        for p in sorted(LOGS_DIR.glob("iteration_*.jsonl")):
            f.write(f"- `{p.name}`\n")
    print(f"\n[orch] Summary written → {summary_md}")

    # ── Triage ───────────────────────────────────────────────────────────
    if run_triage and all_crashes:
        print(f"\n{'=' * 60}")
        print("Running crash triage ...")
        print(f"{'=' * 60}")
        try:
            sys.path.insert(0, str(ROOT / "triage"))
            from triage.run import run_triage as triage_run
            triage_result = triage_run(crash_dir=CRASH_DIR)
            print(f"\n[orch] Triage complete: "
                  f"{triage_result.get('unique_sigs', 0)} unique sigs, "
                  f"{triage_result.get('confirmed', 0)} confirmed")
        except Exception as exc:
            print(f"[orch] Triage failed: {exc}")

    # Determine final state
    if all_crashes:
        state = CRASH_FOUND
    else:
        state = NO_CRASH_FOUND

    return {
        "state": state,
        "iterations": len(prev_results) + 1,
        "total_examples": total_examples,
        "crashes_found": len(all_crashes),
        "llm_provider": llm_provider,
        "loop_elapsed": loop_elapsed,
        "_log_path": str(summary_md),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic fuzzing orchestrator for mxml")
    parser.add_argument("--max-iterations", type=int, default=5,
                        help="Max refine cycles (default: 5)")
    parser.add_argument("--num-examples", type=int, default=200,
                        help="Examples per iteration (default: 200)")
    parser.add_argument("--wall-clock-cap", type=float, default=600.0,
                        help="Wall-clock cap in seconds (default: 600)")
    parser.add_argument("--cost-budget", type=float, default=5.0,
                        help="Cost budget in USD (default: 5.0)")
    parser.add_argument("--no-triage", action="store_true",
                        help="Skip crash triage after loop")
    args = parser.parse_args()

    result = run_orchestrator(
        max_iterations=args.max_iterations,
        num_examples=args.num_examples,
        wall_clock_cap=args.wall_clock_cap,
        cost_budget=args.cost_budget,
        run_triage=not args.no_triage,
    )
    state = result.get("state", "")
    # Non-zero exit for errors, crashes found, or LLM/harness unavailability
    if state in (HARNESS_FAILED, LLM_UNAVAILABLE, PIPELINE_FAILED):
        sys.exit(2)
    elif state == CRASH_FOUND:
        sys.exit(0)  # Crashes found — success
    else:
        sys.exit(0)  # No crashes — also success (just no findings)
