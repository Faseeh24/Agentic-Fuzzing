#!/usr/bin/env python3
"""Allow running the report package as a module:  python -m report"""

from report.generate import generate_report
import sys

if __name__ == "__main__":
    path = generate_report()
    print(f"Report: {path}")
    sys.exit(0)
