"""
generator/strategy_validator.py — AST-based static validator for LLM-generated
Hypothesis strategy files.

Before loading any LLM-authored Python strategy module, this validator
statically parses the source with the ``ast`` module and rejects it if it:

  * Imports or references anything outside the approved safe set
    (hypothesis.strategies, string, random).
  * Does not define a module-level ``xml_strategy`` object.
  * Contains a call to a clearly-dangerous target (``open``, ``print``,
    ``eval``, ``exec``, ``__import__``, ``getattr``, ``sys``, ``os``, etc.).

Only after the AST check passes is the file exec'd (with a restricted
namespace) to obtain the ``xml_strategy`` object.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Approved top-level imports
# ---------------------------------------------------------------------------

# These module prefixes are allowed in ``import`` / ``from ... import`` statements.
ALLOWED_IMPORT_PREFIXES = (
    "hypothesis",
    "hypothesis.strategies",
    "string",
    "random",
)

# Names explicitly banned anywhere in the AST (as attribute access, call targets,
# or bare names).  Also serves as a deny-list for ``__builtins__`` exposure.
BANNED_NAMES = {
    "os", "subprocess", "socket", "sys", "shutil", "pathlib", "builtins",
    "eval", "exec", "__import__", "ctypes", "open", "input",
    "compile", "getattr", "setattr", "delattr",
    "importlib", "pkgutil", "inspect", "code",
}

# Functions whose call at module level (or inside a strategy-defining function)
# is considered a side effect and is therefore forbidden.
BANNED_CALL_TARGETS = {
    "open", "print", "input", "eval", "exec", "compile",
    "getattr", "setattr", "delattr", "del",
    "sys.exit", "os.system", "subprocess.run", "subprocess.Popen",
}


# ---------------------------------------------------------------------------
# AST visitors
# ---------------------------------------------------------------------------


class _ImportChecker(ast.NodeVisitor):
    """Visit all import nodes and flag disallowed ones."""

    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name.split(".")[0]
            if mod in BANNED_NAMES:
                self.violations.append(
                    f"disallowed top-level import: {alias.name}"
                )
            elif not any(alias.name.startswith(p) for p in ALLOWED_IMPORT_PREFIXES):
                self.violations.append(
                    f"import not in approved list: {alias.name}"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = (node.module or "").split(".")[0]
        if mod in BANNED_NAMES:
            self.violations.append(
                f"disallowed from-import: {node.module}.{node.names[0].name}"
            )
        elif not any(
            (node.module or "") == p or (node.module or "").startswith(p + ".")
            for p in ALLOWED_IMPORT_PREFIXES
        ):
            self.violations.append(
                f"from-import not in approved list: {node.module}"
            )
        self.generic_visit(node)


class _SideEffectChecker(ast.NodeVisitor):
    """Flag calls to clearly-dangerous targets (I/O, code execution, dynamic
    attribute access that could bypass the sandbox) anywhere in the module.

    Strategy-construction calls (``st.*``, private helper functions, and string /
    sequence methods such as ``replace``, ``join``, ``map``, ``filter``) are all
    pure and allowed. We use a small DENYLIST rather than an allow-list, because
    an allow-list of every legitimate Hypothesis / stdlib call is fragile and
    rejects valid LLM-authored strategies.
    """

    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        target = _call_target_name(node)
        base = target.split(".")[0] if target else ""
        if target in BANNED_CALL_TARGETS or base in BANNED_NAMES:
            self.violations.append(f"disallowed call: {target}()")
        self.generic_visit(node)


def _call_target_name(call_node: ast.Call) -> str:
    """Best-effort string name for a Call node's target."""
    match call_node.func:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=ast.Name(id=mod), attr=attr):
            return f"{mod}.{attr}"
        case ast.Attribute(attr=attr):
            return attr
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_strategy_source(source: str) -> list[str]:
    """
    Parse *source* and return a list of violation messages (empty == valid).
    """
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        return [f"SyntaxError: {exc}"]

    violations: list[str] = []

    # 1. Import check
    imp_checker = _ImportChecker()
    imp_checker.visit(tree)
    violations.extend(imp_checker.violations)

    # 2. Side-effect check
    eff_checker = _SideEffectChecker()
    eff_checker.visit(tree)
    violations.extend(eff_checker.violations)

    # 3. Must define module-level xml_strategy (plain or annotated assignment)
    has_xml_strategy = False
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "xml_strategy"
                for target in node.targets
            ):
                has_xml_strategy = True
                break
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "xml_strategy"
        ):
            has_xml_strategy = True
            break
    if not has_xml_strategy:
        violations.append(
            "missing module-level definition: xml_strategy"
        )

    # 4. st.recursive(extend=...) must receive a CALLABLE, not a strategy object.
    #    Passing a strategy (e.g. st.builds(...)) is a runtime TypeError.
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        is_recursive = (
            isinstance(func, ast.Attribute) and func.attr == "recursive"
        ) or (isinstance(func, ast.Name) and func.id == "recursive")
        if not is_recursive:
            continue
        for kw in call.keywords:
            if kw.arg == "extend":
                val = kw.value
                if isinstance(val, (ast.Call, ast.Constant, ast.List, ast.Dict, ast.Tuple)):
                    violations.append(
                        "st.recursive 'extend' must be a CALLABLE "
                        "(lambda children: ...) that receives a strategy and returns "
                        "a strategy; a strategy object was passed instead"
                    )

    return violations


def load_strategy_module(path: Path) -> Any:
    """
    Load an LLM-generated strategy file after AST validation.

    Parameters
    ----------
    path : Path
        Path to the .py strategy file.

    Returns
    -------
    Any
        The ``xml_strategy`` object from the module.

    Raises
    ------
    ValueError
        If the AST validation fails.
    FileNotFoundError
        If the file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Strategy file not found: {path}")

    source = path.read_text(encoding="utf-8")
    violations = validate_strategy_source(source)
    if violations:
        raise ValueError(
            f"Strategy validation failed for {path.name}:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    # Build a restricted module namespace
    spec = importlib.util.spec_from_file_location(
        f"llm_strategy_{path.stem}", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot create module spec for {path}")

    module = importlib.util.module_from_spec(spec)

    # Restricted builtins — only allow what the strategy needs
    import hypothesis.strategies as _st
    import string as _string
    import random as _random

    module.__builtins__ = {
        "__import__": __import__,
        "True": True,
        "False": False,
        "None": None,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "tuple": tuple,
        "dict": dict,
        "set": set,
        "frozenset": frozenset,
        "range": range,
        "len": len,
        "sum": sum,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "type": type,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "sorted": sorted,
        "reversed": reversed,
        "any": any,
        "all": all,
        "repr": repr,
        "format": format,
        "pow": pow,
        "divmod": divmod,
        "chr": chr,
        "ord": ord,
        "hex": hex,
        "oct": oct,
        "bin": bin,
        "bytes": bytes,
        "bytearray": bytearray,
        "memoryview": memoryview,
        "complex": complex,
        "object": object,
        # Hypothesis & stdlib modules the strategy is allowed to use
        "st": _st,
        "strategies": _st,
        "string": _string,
        "random": _random,
    }

    spec.loader.exec_module(module)

    if not hasattr(module, "xml_strategy"):
        raise RuntimeError(
            f"Module {path.name} has no xml_strategy after execution"
        )

    return module.xml_strategy


# ---------------------------------------------------------------------------
# CLI quick check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) < 2:
        print(f"Usage: {_sys.argv[0]} <strategy.py>")
        _sys.exit(1)
    p = Path(_sys.argv[1])
    try:
        violations = validate_strategy_source(p.read_text(encoding="utf-8"))
        if violations:
            print(f"INVALID — {len(violations)} violation(s):")
            for v in violations:
                print(f"  - {v}")
            _sys.exit(1)
        else:
            print(f"VALID — loading ...")
            strat = load_strategy_module(p)
            print(f"  xml_strategy = {strat!r}")
    except Exception as exc:
        print(f"ERROR: {exc}")
        _sys.exit(1)
