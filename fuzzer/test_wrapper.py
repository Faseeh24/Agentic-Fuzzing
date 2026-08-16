#!/usr/bin/env python3
"""
test_wrapper.py — verify run_harness classification against known inputs.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from run_harness import run

CASES = [
    ("<root/>",                              0, "valid"),
    ("<root><a></root>",                     1, "invalid"),
    ("not xml at all",                       1, "invalid"),
    ("<root>bad < char</root>",              1, "invalid"),
    ('<?xml version="1.0"?><doc/>',          0, "valid"),
    ("",                                     1, "invalid"),
    ("<!-- comment --><root/>",              1, "comment before root"),
]


def main():
    passed = failed = 0
    for xml, expected, label in CASES:
        code, category = run(xml)
        if code == expected:
            print(f"  PASS: {label} (exit={code})")
            passed += 1
        else:
            print(f"  FAIL: {label} (expected exit={expected}, got {code})")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(main())
