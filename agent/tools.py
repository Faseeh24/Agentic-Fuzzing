"""
agent/tools.py — tool interface provided to the LLM agent.

Each tool returns structured data the LLM can use to make decisions.
Tools are invoked by the Orchestrator, not directly by the LLM (this avoids
tool-call overhead).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def analyze_target() -> dict[str, Any]:
    """
    Analyze the target library (mxml).
    Returns: function signatures, node types, and encoding support.
    """
    return {
        "target": "mxml",
        "version": "4.x",
        "commit": "e6824d899d949387fb0156af6f4101373b9be519",
        "entry_points": ["mxmlLoadString", "mxmlLoadFd", "mxmlLoadFile"],
        "node_types": [
            "MXML_ELEMENT",
            "MXML_TEXT",
            "MXML_CDATA",
            "MXML_COMMENT",
            "MXML_DECLARATION",
            "MXML_DIRECTIVE",
        ],
        "encodings": ["UTF-8", "UTF-16-BE", "UTF-16-LE"],
        "constraints": {
            "max_entity_names": ["amp", "lt", "gt", "quot", "apos"],
            "forbidden_control_chars": list(range(0, 0x20)) + [
                i for i in range(0x7F, 0xA0)
            ],
            "requires_single_root": True,
        },
    }


def get_grammar() -> dict[str, Any]:
    """
    Return the ANTLR grammar rules relevant to mxml parsing.
    """
    grammar_dir = Path(__file__).resolve().parent.parent / "grammar"

    parser_path = grammar_dir / "original" / "XMLParser.g4"
    lexer_path = grammar_dir / "original" / "XMLLexer.g4"

    parser = parser_path.read_text(encoding="utf-8") if parser_path.exists() else ""
    lexer = lexer_path.read_text(encoding="utf-8") if lexer_path.exists() else ""

    return {
        "parser": parser,
        "lexer": lexer,
    }


def get_crash_signatures() -> list[dict[str, Any]]:
    """
    Return the unique crash signatures found so far.
    """
    crash_dir = Path(__file__).resolve().parent.parent / "triage" / "crashes"
    if not crash_dir.exists():
        return []

    sigs = []
    for d in sorted(crash_dir.iterdir()):
        if d.is_dir():
            meta_path = d / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                sigs.append(
                    {
                        "signature": d.name,
                        "code": meta.get("code"),
                        "signal": meta.get("signal"),
                    }
                )
    return sigs


def get_iteration_history() -> list[dict[str, Any]]:
    """
    Return the iteration history from previous rounds, for context.
    """
    logs_dir = Path(__file__).resolve().parent.parent / "fuzzer" / "logs"
    if not logs_dir.exists():
        return []

    history = []
    for f in sorted(logs_dir.glob("iteration_*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                history.append(json.loads(line))
    return history


def get_strategy_logs() -> list[dict[str, Any]]:
    """
    Return the saved strategy source history.
    """
    strategies_dir = Path(__file__).resolve().parent.parent / "fuzzer" / "strategies"
    if not strategies_dir.exists():
        return []

    strategies = []
    for f in sorted(strategies_dir.glob("*.py")):
        strategies.append(
            {
                "filename": f.name,
                "content": f.read_text(encoding="utf-8"),
            }
        )
    return strategies