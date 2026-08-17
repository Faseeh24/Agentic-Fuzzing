#!/usr/bin/env python3
"""
triage/run.py — main triage pipeline entry point.

After the agentic loop produces crash candidates (exit codes 3, 4, 5),
this module:
  1. Collects all crash inputs from the iteration logs.
  2. Deduplicates them by normalized crash signature.
  3. Saves each unique signature to ``triage/crashes/{sig}/``.
  4. Minimizes each reproducer using Hypothesis.
  5. Verifies each minimized reproducer for deterministic reproduction.
  6. Produces a final triage report at ``report/triage_report.md``.

Run:
    python -m triage.run [--max-iterations N] [--crash-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
FUZZER_DIR = ROOT / "fuzzer"
LOGS_DIR = FUZZER_DIR / "logs"
CRASH_DIR = ROOT / "triage" / "crashes"
REPORT_DIR = ROOT / "report"


def _import_dedupe():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import triage.dedupe as m
    return m


def _import_minimize():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import triage.minimize as m
    return m


def _import_verify():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import triage.verify as m
    return m


# ---------------------------------------------------------------------------
# Crash collection from iteration logs
# ---------------------------------------------------------------------------


def collect_crashes_from_logs(logs_dir: Path) -> list[dict[str, Any]]:
    """
    Scan all ``iteration_N.jsonl`` files in *logs_dir* and extract every
    crash example (codes 3, 4, 5).

    Each iteration log is a JSONL file where each line is a dict with keys:
        results (dict with code counts), examples (list of (input, code, label))

    Returns a list of dicts:
        {input, code, label, stderr_preview, iteration}
    """
    crashes: list[dict[str, Any]] = []
    if not logs_dir.exists():
        return crashes

    for log_file in sorted(logs_dir.glob("iteration_*.jsonl")):
        iteration = int(log_file.stem.split("_")[1])
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            for input_text, code, label in record.get("examples", []):
                if code in (3, 4, 5):
                    crashes.append({
                        "input": input_text,
                        "code": code,
                        "label": label,
                        "iteration": iteration,
                        "stderr": "",  # run_harness doesn't return stderr; captured at save time
                    })
    return crashes


# ---------------------------------------------------------------------------
# Full crash run (with stderr capture)
# ---------------------------------------------------------------------------

def _run_with_stderr(input_text: str) -> tuple[int, str, str]:
    """
    Run the harness and return (exit_code, label, stderr_text).
    """
    import subprocess
    harness = str(ROOT / "harness" / "mxml_harness")
    try:
        result = subprocess.run(
            [harness],
            input=input_text.encode("utf-8"),
            capture_output=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return 4, "timeout", result.stderr.decode("utf-8", errors="replace") if hasattr(result, 'stderr') else ""

    stderr_text = result.stderr.decode("utf-8", errors="replace")
    stderr_lower = stderr_text.lower()

    if "addresssanitizer" in stderr_lower or "runtime error" in stderr_lower:
        return 3, "sanitizer", stderr_text
    if result.returncode == 0:
        return 0, "valid", stderr_text
    if result.returncode == 1:
        return 1, "invalid", stderr_text
    if result.returncode == 2:
        return 2, "harness_error", stderr_text
    return 5, "bug_crash", stderr_text


def run_triage(
    max_iterations: int = 5,
    crash_dir: Path | None = None,
    num_examples: int = 500,
) -> dict[str, Any]:
    """
    Run the full triage pipeline:
      1. Collect crashes from logs (or run fresh if no logs).
      2. Deduplicate by signature.
      3. Save each unique crash.
      4. Minimize each reproducer.
      5. Verify each minimized reproducer.
      6. Write the final report.

    Parameters
    ----------
    max_iterations : int
        Max agentic loop iterations to consider (used when running fresh).
    crash_dir : Path | None
        Override crash directory (default: ``triage/crashes/``).
    num_examples : int
        Examples per iteration when running fresh.

    Returns
    -------
    dict with keys:
        total_crashes, unique_sigs, minimized, confirmed, report_path
    """
    crash_dir = crash_dir or CRASH_DIR
    crash_dir.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    dedupe = _import_dedupe()
    minimize = _import_minimize()
    verify = _import_verify()

    print("=" * 60)
    print("Crash Triage Pipeline")
    print("=" * 60)

    # ── Step 1: Collect crashes ────────────────────────────────────────────
    print("\n[1/4] Collecting crashes from iteration logs ...")
    crashes = collect_crashes_from_logs(LOGS_DIR)
    print(f"  Found {len(crashes)} crash examples across logs.")

    if not crashes:
        # Try to collect from any saved crash directories
        existing = dedupe.load_crash_records(LOGS_DIR)
        if existing:
            crashes = [
                {
                    "input": c.get("input_text", ""),
                    "code": c["code"],
                    "label": c["signal_name"],
                    "iteration": 0,
                    "stderr": c.get("stderr_text", ""),
                }
                for c in existing
            ]
            print(f"  Loaded {len(crashes)} crashes from existing crash dir.")

    if not crashes:
        print("  No crashes found. Nothing to triage.")
        report_path = _write_empty_report(crash_dir)
        return {"total_crashes": 0, "unique_sigs": 0, "minimized": 0, "confirmed": 0, "report_path": str(report_path)}

    # ── Step 2: Deduplicate ────────────────────────────────────────────────
    print("\n[2/4] Deduplicating crashes ...")
    groups = dedupe.deduplicate(crashes)
    unique_sigs = len(groups)
    print(f"  {len(crashes)} total → {unique_sigs} unique signatures")

    # Save each unique crash to its signature directory
    for sig, sig_crashes in groups.items():
        # Use the first crash as the canonical reproducer
        canonical = sig_crashes[0]
        stderr_text = canonical.get("stderr", "")
        if not stderr_text:
            # Re-run with stderr capture
            _, _, stderr_text = _run_with_stderr(canonical["input"])
        dedupe.save_crash_record(
            crash_dir=crash_dir,
            input_text=canonical["input"],
            stderr_text=stderr_text,
            signal_name=canonical.get("label", "unknown"),
            code=canonical["code"],
        )
    print(f"  Saved {unique_sigs} crash records to {crash_dir}")

    # ── Step 3: Minimize ───────────────────────────────────────────────────
    print("\n[3/4] Minimizing reproducers ...")
    min_results = minimize.minimize_all_crashes(crash_dir, max_examples=300)
    print(f"  Minimized {len(min_results)} reproducer(s)")

    # ── Step 4: Verify ─────────────────────────────────────────────────────
    print("\n[4/4] Verifying reproducers ...")
    ver_results = verify.verify_all_crashes(crash_dir, runs=3)
    confirmed = sum(1 for v in ver_results if v["verdict"] == "confirmed")
    flaky = sum(1 for v in ver_results if v["verdict"] == "flaky")
    print(f"  {confirmed} confirmed, {flaky} flaky")

    # ── Step 5: Write report ───────────────────────────────────────────────
    print("\nWriting triage report ...")
    report_path = _write_report(
        crash_dir=crash_dir,
        total_crashes=len(crashes),
        unique_sigs=unique_sigs,
        min_results=min_results,
        ver_results=ver_results,
    )
    print(f"  Report → {report_path}")

    return {
        "total_crashes": len(crashes),
        "unique_sigs": unique_sigs,
        "minimized": len(min_results),
        "confirmed": confirmed,
        "flaky": flaky,
        "report_path": str(report_path),
    }


def _write_empty_report(crash_dir: Path) -> Path:
    """Write a minimal report when no crashes are found."""
    report_path = REPORT_DIR / "triage_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "# Crash Triage Report\n\n"
        "No crashes were found during the fuzzing run.\n\n"
        f"**Triage timestamp:** {datetime.now(timezone.utc).isoformat()}\n\n"
        f"**Crash directory:** `{crash_dir}`\n\n"
        "### Why no crashes were found\n\n"
        "The mxml library's parser may be robust against the inputs generated\n"
        "by the current strategy. Possible next steps:\n\n"
        "- Increase the deliberate-break fraction in the seed strategy.\n"
        "- Target specific mxml source paths that handle edge cases.\n"
        "- Run with a longer agentic loop (more iterations).\n"
        "- Introduce coverage feedback to steer generation toward unexplored paths.\n",
        encoding="utf-8",
    )
    return report_path


def _write_report(
    crash_dir: Path,
    total_crashes: int,
    unique_sigs: int,
    min_results: list[dict[str, Any]],
    ver_results: list[dict[str, Any]],
) -> Path:
    """Write the final triage report in markdown."""
    report_path = REPORT_DIR / "triage_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Crash Triage Report",
        "",
        f"**Generated:** {now}",
        f"**Total crash examples collected:** {total_crashes}",
        f"**Unique crash signatures:** {unique_sigs}",
        "",
        "---",
        "",
        "## Crash Signatures",
        "",
    ]

    for sig_dir in sorted(crash_dir.iterdir()):
        if not sig_dir.is_dir():
            continue
        meta_path = sig_dir / "meta.json"
        reproducer = sig_dir / "reproducer.xml"
        minimized = sig_dir / "reproducer_minimized.xml"
        sanitizer = sig_dir / "sanitizer_report.txt"

        if not meta_path.exists():
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        sig = sig_dir.name
        signal = meta.get("signal", "unknown")
        code = meta.get("code", 3)
        timed_out = meta.get("timed_out", False)

        lines += [
            f"### Signature: `{sig}`",
            "",
            f"- **Code:** {code} ({signal})",
            f"- **Timed out:** {'Yes' if timed_out else 'No'}",
        ]

        # Show minimized version if available
        if minimized.exists():
            min_text = minimized.read_text(encoding="utf-8")
            lines += [
                "",
                "#### Minimized reproducer",
                "",
                "```xml",
                min_text[:1000],
                "```",
            ]
            if len(min_text) > 1000:
                lines.append(f"\n*(truncated, {len(min_text)} bytes total)*")
        elif reproducer.exists():
            orig_text = reproducer.read_text(encoding="utf-8")
            lines += [
                "",
                "#### Reproducer (not yet minimized)",
                "",
                "```xml",
                orig_text[:1000],
                "```",
            ]

        # Show sanitizer report if available
        if sanitizer.exists():
            san_text = sanitizer.read_text(encoding="utf-8")
            lines += [
                "",
                "#### Sanitizer report",
                "",
                "```",
                san_text[:2000],
                "```",
            ]
            if len(san_text) > 2000:
                lines.append(f"\n*(truncated, {len(san_text)} bytes total)*")

        lines += ["", "---", ""]

    # Summary table
    lines += [
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total crash examples | {total_crashes} |",
        f"| Unique signatures | {unique_sigs} |",
        f"| Minimized | {len(min_results)} |",
        f"| Confirmed deterministic | {sum(1 for v in ver_results if v['verdict'] == 'confirmed')} |",
        f"| Flaky | {sum(1 for v in ver_results if v['verdict'] == 'flaky')} |",
        "",
        "## Normalization Choices",
        "",
        "Crash signatures are computed by normalizing ASan/UBSan stack traces:",
        "",
        "- **Stripped frames:** `__interceptor_malloc`, `__interceptor_free`, "
        "`malloc`, `free`, `__libc_start_main`, `_start` — these are allocator/"
        "runtime boilerplate that appear in every crash.",
        "- **Top N frames hashed:** 5 frames. Too few over-merges distinct bugs; "
        "too many under-merges due to ASLR/inlining noise.",
        "- **Bare timeouts:** signed as `timeout|struct=<structural_hash>` so "
        "similar pathological inputs group together.",
        "",
        "## Minimization Strategy",
        "",
        "Minimization uses Hypothesis's built-in shrinker via a structured "
        "sub-document strategy that:",
        "",
        "- Randomly drops child elements.",
        "- Randomly drops or shortens attributes.",
        "- Flattens entity references to their literal equivalents.",
        "- Reduces nesting depth.",
        "",
        "The `@given` test asserts that the same crash code is produced; "
        "Hypothesis shrinks until it finds the smallest input that still "
        "triggers the exact same signature.",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crash triage pipeline for mxml fuzzer")
    parser.add_argument("--max-iterations", type=int, default=5,
                        help="Max agentic loop iterations (for fresh runs)")
    parser.add_argument("--crash-dir", type=str, default=None,
                        help="Override crash directory")
    parser.add_argument("--num-examples", type=int, default=500,
                        help="Examples per iteration")
    args = parser.parse_args()

    result = run_triage(
        max_iterations=args.max_iterations,
        crash_dir=Path(args.crash_dir) if args.crash_dir else None,
        num_examples=args.num_examples,
    )
    print("\nDone.")
    sys.exit(0 if result.get("confirmed", 0) > 0 else 1)
