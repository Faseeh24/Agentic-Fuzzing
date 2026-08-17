#!/usr/bin/env python3
"""
run_harness.py — wrapper around the mxml C harness.

Runs the C harness with a 5-second timeout and sanitizer-detection,
classifying each input into one of six categories:

  0  — valid            : mxml accepted the XML
  1  — invalid          : mxml rejected the input (parse error)
  2  — harness_error    : cannot read input file or I/O failure
  3  — sanitizer        : ASan or UBSan detected a violation
  4  — timeout          : input exceeded the 5-second limit
  5  — bug_crash        : unexpected crash (segfault, abort, etc.)
"""

import os
import sys
import subprocess

TIMEOUT_SEC = 5


def _harness_path():
    """Locate the compiled harness binary."""
    candidates = [
        # Docker container path
        os.path.join("/src", "harness", "mxml_harness"),
        # Relative to this file
        os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "harness", "mxml_harness")
        ),
        # Windows exe variant
        os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "harness", "mxml_harness.exe")
        ),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    # Fallback: assume it is on PATH
    return "mxml_harness"


def run(input_text, input_path=None, return_stderr=False):
    """
    Run the harness with the given input.

    Parameters
    ----------
    input_text : str or None
        XML text to feed via stdin. Ignored if input_path is given.
    input_path : str or None
        Path to a file containing XML. If None, input is read from stdin.
    return_stderr : bool
        If True, also return the raw stderr text (for triage). Adds a small
        overhead but is essential for crash signature extraction.

    Returns
    -------
    If return_stderr is False:
        (exit_code, category) — exit_code 0-5, category human-readable
    If return_stderr is True:
        (exit_code, category, stderr_text)
    """
    harness = _harness_path()

    if input_path is not None:
        cmd = [harness, input_path]
        proc_input = None
    else:
        cmd = [harness]
        proc_input = input_text.encode("utf-8") if isinstance(input_text, str) else input_text

    try:
        result = subprocess.run(
            cmd,
            input=proc_input,
            capture_output=True,
            timeout=TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        if return_stderr:
            return 4, "timeout", ""
        return 4, "timeout"

    stderr_text = result.stderr.decode("utf-8", errors="replace")
    stderr_lower = stderr_text.lower()

    # Sanitizer detection: ASan / UBSan print recognizable messages to stderr
    if "addresssanitizer" in stderr_lower or "runtime error" in stderr_lower:
        code = 3
        label = "sanitizer"
    elif result.returncode == 0:
        code, label = 0, "valid"
    elif result.returncode == 1:
        code, label = 1, "invalid"
    elif result.returncode == 2:
        code, label = 2, "harness_error"
    else:
        code, label = 5, "bug_crash"

    if return_stderr:
        return code, label, stderr_text
    return code, label


if __name__ == "__main__":
    # Quick smoke test when run directly
    for xml, expected in [
        ("<root/>", 0),
        ("<root><a></root>", 1),
        ("not xml", 1),
    ]:
        code, cat = run(xml)
        status = "OK" if code == expected else "WRONG"
        print(f"  {status}: {xml!r:30s} → exit={code} ({cat})  expected={expected}")
