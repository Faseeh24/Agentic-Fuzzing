#!/usr/bin/env python3
"""Allow running the fuzzer package as a module:  python -m fuzzer"""

from fuzzer.baseline_strategy import run_baseline
import sys

if __name__ == "__main__":
    ok = run_baseline()
    sys.exit(0 if ok else 1)
