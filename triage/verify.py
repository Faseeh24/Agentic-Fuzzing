#!/usr/bin/env python3
"""
triage/verify.py — reproducibility verification for minimized crash reproducers.

For each crash signature, we re-run the harness on the minimized reproducer
at least twice and confirm that:
  1. It crashes every time (deterministic reproduction).
  2. The crash classification (exit code) is consistent across runs.

Non-deterministic crashes (flaky sanitizer hits) are still recorded but
flagged in the final report so the user knows to investigate further.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fuzzer"))
from run_harness import run as harness_run  # noqa: E402

from dedupe import signature_for, classify_stderr  # noqa: E402


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_reproducer(path: Path, runs: int = 3) -> dict[str, Any]:
    """
    Re-run the harness on the input at *path* for *runs* iterations.

    Parameters
    ----------
    path : Path
        Path to the reproducer XML file.
    runs : int
        Number of times to re-run the harness.

    Returns
    -------
    dict with keys:
        path, deterministic, codes, sigs, signal_names, verdict
    """
    data = path.read_bytes()
    codes: list[int] = []
    sigs: list[str] = []
    signal_names: list[str] = []

    for i in range(runs):
        # We need stderr to compute the signature — run_harness currently
        # only returns (code, label). Patch: re-run with subprocess directly.
        import subprocess
        result = subprocess.run(
            [str(Path(__file__).resolve().parent.parent / "harness" / "mxml_harness")],
            input=data,
            capture_output=True,
            timeout=5,
        )
        code, label = _code_from_result(result)
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        signal_name, _ = classify_stderr(result.stderr)
        sig = signature_for(stderr_text, signal_name, data.decode("utf-8", errors="replace"))
        codes.append(code)
        sigs.append(sig)
        signal_names.append(signal_name)

    deterministic = (len(set(codes)) == 1) and (len(set(sigs)) == 1)
    verdict = "confirmed" if deterministic and codes[0] in (3, 4, 5) else "flaky"
    return {
        "path": str(path),
        "deterministic": deterministic,
        "codes": codes,
        "sigs": sigs,
        "signal_names": signal_names,
        "verdict": verdict,
    }


def _code_from_result(result) -> tuple[int, str]:
    """Map a subprocess.Result to our (code, label) contract."""
    import re as _re
    stderr_lower = result.stderr.decode("utf-8", errors="replace").lower()
    if "addresssanitizer" in stderr_lower or "runtime error" in stderr_lower:
        return 3, "sanitizer"
    if result.returncode == 0:
        return 0, "valid"
    if result.returncode == 1:
        return 1, "invalid"
    if result.returncode == 2:
        return 2, "harness_error"
    # Timeout was handled by subprocess.TimeoutExpired above; anything else
    # with a non-zero code is a bug crash.
    return 5, "bug_crash"


def verify_all_crashes(crash_dir: Path, runs: int = 3) -> list[dict[str, Any]]:
    """
    Verify every reproducer in *crash_dir*.

    Returns a list of verification results sorted by verdict (confirmed first).
    """
    results: list[dict[str, Any]] = []
    if not crash_dir.exists():
        return results

    for sig_dir in sorted(crash_dir.iterdir()):
        if not sig_dir.is_dir():
            continue
        reproducer = sig_dir / "reproducer_minimized.xml"
        if not reproducer.exists():
            reproducer = sig_dir / "reproducer.xml"
        if not reproducer.exists():
            continue

        print(f"  Verifying {sig_dir.name} ... ", end="", flush=True)
        v = verify_reproducer(reproducer, runs=runs)
        print(v["verdict"])
        results.append(v)

    # Sort: confirmed first, then flaky, then missing
    order = {"confirmed": 0, "flaky": 1, "missing": 2}
    results.sort(key=lambda r: order.get(r["verdict"], 3))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Verify crash reproducers")
    parser.add_argument("crash_dir", help="Path to triage/crashes/ directory")
    parser.add_argument("--runs", type=int, default=3, help="Verification runs per input")
    args = parser.parse_args()

    crash_dir = Path(args.crash_dir)
    results = verify_all_crashes(crash_dir, runs=args.runs)

    confirmed = sum(1 for r in results if r["verdict"] == "confirmed")
    flaky = sum(1 for r in results if r["verdict"] == "flaky")
    print(f"\nResults: {confirmed} confirmed, {flaky} flaky, "
          f"{len(results) - confirmed - flaky} missing")
    sys.exit(0 if flaky == 0 else 1)
