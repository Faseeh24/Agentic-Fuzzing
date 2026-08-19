"""
coverage/collector.py — Coverage collection for mxml harness.

Supports:
  - LLVM coverage (llvm-cov) — requires -fprofile-instr-generate -fcoverage-mapping
  - gcov coverage — requires -ftest-coverage
  - Simple edge counting via ASan instrumentation

Integration with the orchestrator provides feedback like:
  - New edges covered this iteration
  - Uncovered functions
  - Coverage percentage

NOTE: Full coverage instrumentation requires rebuilding the harness with
coverage flags. This module provides the interface; the actual instrumentation
is done via the Makefile when COVERAGE_ENABLED=true.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class CoverageCollector:
    """Collects coverage data from the mxml harness."""

    def __init__(
        self,
        coverage_dir: Path,
        format: str = "text",
        enabled: bool = True,
    ):
        self.coverage_dir = coverage_dir
        self.format = format
        self.enabled = enabled
        self.coverage_dir.mkdir(parents=True, exist_ok=True)
        self._prev_edges: set[str] = set()
        self._total_runs: int = 0

    def run_and_collect(self, input_text: str) -> dict[str, Any]:
        """
        Run harness on input and collect coverage data.

        Returns a dict with keys:
            new_edges, total_edges, coverage_pct
        """
        if not self.enabled:
            return {"new_edges": 0, "total_edges": 0, "coverage_pct": 0.0}

        self._total_runs += 1
        # TODO: Integrate with llvm-cov when harness is built with coverage flags
        # For now, return empty coverage data
        return {"new_edges": 0, "total_edges": 0, "coverage_pct": 0.0}

    def get_summary(self) -> dict[str, Any]:
        """Return current coverage summary."""
        if not self.enabled:
            return {
                "total_lines": 0,
                "covered_lines": 0,
                "coverage_pct": 0.0,
                "new_edges": 0,
                "total_edges": 0,
            }

        # TODO: Parse coverage output files when available
        return {
            "total_lines": 0,
            "covered_lines": 0,
            "coverage_pct": 0.0,
            "new_edges": 0,
            "total_edges": 0,
        }

    def merge_iteration(self, iteration_data: dict[str, Any]) -> None:
        """Merge coverage data from a completed iteration."""
        # TODO: Update internal state with new edges from iteration_data
        pass


def get_coverage_summary(coverage_dir: Path) -> dict[str, Any]:
    """
    Read coverage summary from disk (for post-hoc reporting).

    Returns a dict compatible with CoverageCollector.get_summary().
    """
    summary_path = coverage_dir / "summary.json"
    if not summary_path.exists():
        return {
            "total_lines": 0,
            "covered_lines": 0,
            "coverage_pct": 0.0,
            "new_edges": 0,
            "total_edges": 0,
        }
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "total_lines": 0,
            "covered_lines": 0,
            "coverage_pct": 0.0,
            "new_edges": 0,
            "total_edges": 0,
        }


def save_coverage_summary(coverage_dir: Path, data: dict[str, Any]) -> None:
    """Save coverage summary to disk."""
    summary_path = coverage_dir / "summary.json"
    summary_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
