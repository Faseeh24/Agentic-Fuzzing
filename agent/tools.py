"""
agent/tools.py — 提供给 LLM 代理的工具接口。

每个工具返回结构化数据，LLM 可据此做出决策。
工具由 Orchestrator 调用，而非直接由 LLM 调用（避免工具调用开销）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def analyze_target() -> dict[str, Any]:
    """
    分析目标库 (mxml)。
    返回：函数签名、节点类型、编码支持。
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
    返回与 mxml 解析相关的 ANTLR 语法规则。
    """
    grammar_dir = Path(__file__).resolve().parent.parent / "grammar"

    parser_path = grammar_dir / "original" / "XMLParser.g4"
    lexer_path = grammar_dir / "original" / "XMLLexer.g4"
    adaptations_path = grammar_dir / "ADAPTATIONS.md"

    parser = parser_path.read_text(encoding="utf-8") if parser_path.exists() else ""
    lexer = lexer_path.read_text(encoding="utf-8") if lexer_path.exists() else ""
    adaptations = adaptations_path.read_text(encoding="utf-8") if adaptations_path.exists() else ""

    return {
        "parser": parser,
        "lexer": lexer,
        "adaptations": adaptations,
    }


def get_coverage_stats() -> dict[str, Any]:
    """
    返回当前覆盖率统计信息。
    """
    # 占位符 — 将在后续实现中连接 coverage/collector.py
    return {
        "total_lines": 0,
        "covered_lines": 0,
        "coverage_pct": 0.0,
        "new_edges": 0,
        "total_edges": 0,
    }


def get_crash_signatures() -> list[dict[str, Any]]:
    """
    返回迄今为止找到的唯一崩溃签名。
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
    返回上一轮迭代的历史记录，供上下文参考。
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
    返回已保存的策略规范历史。
    """
    strategies_dir = Path(__file__).resolve().parent.parent / "fuzzer" / "strategies"
    if not strategies_dir.exists():
        return []

    strategies = []
    for f in sorted(strategies_dir.glob("*.json")):
        strategies.append(
            {
                "filename": f.name,
                "content": json.loads(f.read_text(encoding="utf-8")),
            }
        )
    return strategies
