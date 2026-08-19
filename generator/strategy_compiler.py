"""
generator/strategy_compiler.py — compiles an LLM-generated Python strategy file
into a Hypothesis SearchStrategy, using AST-based static validation.

The LLM directly authors a Python module that defines a module-level
``xml_strategy`` variable. Before loading, the source is validated with an
AST checker (see ``strategy_validator``) to reject unsafe imports or
side-effecting calls. Only files that pass validation are executed in a
restricted namespace.

Usage:
    from generator.strategy_compiler import load_strategy_from_file

    strategy = load_strategy_from_file(Path("fuzzer/strategies/iteration_0001.py"))
    example = strategy.example()
"""

from __future__ import annotations

from pathlib import Path

from generator.strategy_validator import load_strategy_module, validate_strategy_source


def load_llm_strategy(path: Path):
    """
    Load and validate an LLM-generated Hypothesis strategy file.

    Parameters
    ----------
    path : Path
        Path to the .py strategy file.

    Returns
    -------
    hypothesis.strategies.SearchStrategy
        The ``xml_strategy`` object.

    Raises
    ------
    ValueError
        If AST validation fails (unsafe imports, side effects, missing
        ``xml_strategy``).
    FileNotFoundError
        If the file does not exist.
    """
    return load_strategy_module(path)


def quick_validate(source: str) -> list[str]:
    """
    Validate LLM-generated Python source and return a list of violation
    messages (empty list means the source is valid).
    """
    return validate_strategy_source(source)
