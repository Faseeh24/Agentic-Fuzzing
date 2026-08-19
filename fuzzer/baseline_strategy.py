#!/usr/bin/env python3
"""
baseline_strategy.py — baseline fuzzer strategy.

Generates a fixed set of valid and invalid XML inputs to verify that the
fuzzer pipeline plumbing works end-to-end. This strategy does NOT attempt
to find bugs; it only confirms that inputs flow through the harness and
results are correctly classified.

Exit code contract (through run_harness):
  0  — valid            : mxml accepted the XML
  1  — invalid          : mxml rejected the input (parse error)
  2  — harness_error    : cannot read input file or I/O failure
  3  — sanitizer        : ASan or UBSan detected a violation
  4  — timeout          : input exceeded the 5-second limit
  5  — bug_crash        : unexpected crash (segfault, abort, etc.)
"""

import os
import sys

# Ensure the fuzzer package root is on sys.path
sys.path.insert(0, os.path.dirname(__file__))
from run_harness import run

# ---------------------------------------------------------------------------
# Test corpus: (xml, expected_exit_code, description)
# ---------------------------------------------------------------------------

VALID_CASES = [
    ("<root/>",                                            0, "empty element"),
    ("<doc><a>text</a></doc>",                             0, "simple nested"),
    ('<?xml version="1.0"?>\n<root/>\n',                  0, "with declaration"),
    ("<a><b><c/></b></a>",                                 0, "deep nesting"),
    ("<root attr='val'/>",                                 0, "attribute"),
    ("<root><![CDATA[hi]]></root>",                        0, "CDATA section"),
]

INVALID_CASES = [
    ("<root><a></root>",                                   1, "mismatched tags"),
    ("<root>bad < char</root>",                            1, "bare lt in content"),
    ("not xml at all",                                     1, "non-xml text"),
    ("",                                                   1, "empty input"),
    ("<!-- unclosed comment",                              1, "incomplete comment"),
    ("<root></root><other/>",                              1, "two root elements"),
    ("<!-- comment --><root/>",                            1, "comment before root"),
]

ALL_CASES = VALID_CASES + INVALID_CASES


def classify_summary(results):
    """Print a summary table of results."""
    counts = {}
    for _, exp, actual, cat in results:
        counts[cat] = counts.get(cat, 0) + 1
    print()
    print("Classification summary:")
    for cat in sorted(counts):
        print(f"  {cat:20s} : {counts[cat]}")
    print()


def run_baseline(verbose=True):
    """
    Run the baseline test corpus through the harness.

    Parameters
    ----------
    verbose : bool
        Print per-test results.

    Returns
    -------
    bool — True if all tests passed, False otherwise.
    """
    results = []
    passed = 0
    failed = 0

    for xml, expected, desc in ALL_CASES:
        actual, cat = run(xml)
        ok = (actual == expected)
        if ok:
            passed += 1
        else:
            failed += 1
        results.append((desc, expected, actual, cat))
        if verbose:
            mark = "PASS" if ok else "FAIL"
            print(f"  {mark}: {desc:30s} expected={expected} actual={actual} ({cat})")

    classify_summary(results)
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_baseline()
    sys.exit(0 if ok else 1)
