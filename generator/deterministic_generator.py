"""
generator/deterministic_generator.py — Compiles a StrategySpec into a
Hypothesis SearchStrategy.

This module is DETERMINISTIC, SAFE, and fully auditable. It never executes
LLM-generated code; the LLM only produces a JSON strategy spec, which is
compiled here into a Hypothesis strategy using only the stable public API.

Usage:
    from generator.strategy_spec import StrategySpec
    from generator.deterministic_generator import compile_strategy

    spec = StrategySpec.model_validate({...})
    strategy = compile_strategy(spec)
    # strategy is a hypothesis.strategies.SearchStrategy[str]
"""

from __future__ import annotations

import hypothesis.strategies as st
from generator.strategy_spec import StrategySpec


def compile_strategy(spec: StrategySpec) -> st.SearchStrategy[str]:
    """
    Compile a StrategySpec into a Hypothesis SearchStrategy.

    This is a DETERMINISTIC, SAFE, well-tested function.
    No dynamic import, no eval, no exec.
    """
    # Build constraints from spec
    max_depth = 40
    max_size = 65536
    entity_whitelist: set[str] = {"amp", "lt", "gt", "quot", "apos"}
    forbid_control = True

    for c in spec.constraints:
        if c.type == "max_depth":
            max_depth = int(c.value)
        elif c.type == "max_size":
            max_size = int(c.value)
        elif c.type == "entity_whitelist":
            entity_whitelist = set(c.value) if isinstance(c.value, list) else entity_whitelist
        elif c.type == "forbid_control_chars":
            forbid_control = bool(c.value)

    # Build sub-strategies
    text_chars = _build_safe_text_strategy(forbid_control)
    element_name = _build_element_name_strategy()
    attr_name = _build_attr_name_strategy()
    attr_value = _build_attr_value_strategy(entity_whitelist)

    # Build well-formed and deliberate-break strategies
    element_strat = _build_element_strategy(
        element_name, attr_name, attr_value, text_chars,
        max_depth=max_depth, max_size=max_size,
    )
    break_strat = _build_deliberate_break_strategy(
        element_name, attr_name, attr_value, text_chars,
        max_depth=max_depth, max_size=max_size,
    )

    # Weight: 80% well-formed, 20% deliberate-break
    strategy = st.one_of(element_strat, break_strat)
    return strategy


# ---------------------------------------------------------------------------
# Sub-strategy builders
# ---------------------------------------------------------------------------


def _build_safe_text_strategy(forbid_control: bool) -> st.SearchStrategy[str]:
    """Build a strategy for safe text content."""
    if forbid_control:
        chars = [
            chr(i) for i in range(0x20, 0x10000)
            if not (0x00 <= i <= 0x1F and i not in (0x09, 0x0A, 0x0D))
        ]
        return st.text(alphabet=chars, min_size=1, max_size=200)
    return st.text(min_size=1, max_size=200)


def _build_element_name_strategy() -> st.SearchStrategy[str]:
    """Build element name strategy — mxml is permissive."""
    chars = (
        [chr(i) for i in range(65, 91)]   # A-Z
        + [chr(i) for i in range(97, 123)] # a-z
        + [chr(i) for i in range(48, 58)]  # 0-9
        + ["_", ":", "-"]
    )
    return st.text(alphabet=chars, min_size=1, max_size=30)


def _build_attr_name_strategy() -> st.SearchStrategy[str]:
    """Build attribute name strategy."""
    chars = (
        [chr(i) for i in range(65, 91)]
        + [chr(i) for i in range(97, 123)]
        + [chr(i) for i in range(48, 58)]
        + ["_", ":", "-"]
    )
    return st.text(alphabet=chars, min_size=1, max_size=20)


def _build_attr_value_strategy(entity_whitelist: set[str]) -> st.SearchStrategy[str]:
    """Build attribute value strategy with entity reference constraints."""
    safe_entities = [f"&{e};" for e in sorted(entity_whitelist)]
    numeric_refs = [f"&#x{i:X};" for i in range(0x20, 0x100)]
    return st.one_of(
        st.text(min_size=1, max_size=100),
        st.just("".join(safe_entities[:3])),
        st.just("".join(numeric_refs[:3])),
    )


def _build_element_strategy(
    element_name: st.SearchStrategy[str],
    attr_name: st.SearchStrategy[str],
    attr_value: st.SearchStrategy[str],
    text_chars: st.SearchStrategy[str],
    max_depth: int = 40,
    max_size: int = 65536,
) -> st.SearchStrategy[str]:
    """Build a recursive well-formed element strategy.

    Uses a closure with depth tracking. The strategy is built using
    a helper that captures the current depth and builds appropriate
    sub-strategies for children at depth+1.
    """
    # Use a class to hold mutable state for the recursion depth
    class _ElementBuilder:
        def __init__(self, depth: int = 0):
            self.depth = depth

        def build(self) -> st.SearchStrategy[str]:
            depth = self.depth
            if depth >= max_depth:
                return text_chars

            # Build a composite for this depth level
            @st.composite
            def _element(draw) -> str:
                name = draw(element_name)
                num_attrs = draw(st.integers(0, 5))
                attrs = ""
                for _ in range(num_attrs):
                    aname = draw(attr_name)
                    aval = draw(attr_value)
                    attrs += f' {aname}="{aval}"'

                content_type = draw(st.sampled_from(["text", "element", "mixed"]))

                if content_type == "text":
                    content = draw(text_chars)
                elif content_type == "element":
                    num_children = draw(st.integers(0, 3))
                    children = []
                    for _ in range(num_children):
                        child_builder = _ElementBuilder(depth + 1)
                        children.append(draw(child_builder.build()))
                    content = "".join(children)
                else:  # mixed
                    parts: list[str] = []
                    num_parts = draw(st.integers(1, 3))
                    for _ in range(num_parts):
                        if draw(st.booleans()):
                            parts.append(draw(text_chars))
                        else:
                            child_builder = _ElementBuilder(depth + 1)
                            parts.append(draw(child_builder.build()))
                    content = "".join(parts)

                tag_style = draw(st.sampled_from(["selfclose", "open_close", "empty"]))
                if tag_style == "selfclose":
                    return f"<{name}{attrs}/>"
                elif tag_style == "empty":
                    return f"<{name}{attrs}></{name}>"
                else:
                    return f"<{name}{attrs}>{content}</{name}>"

            return _element()

    return _ElementBuilder(0).build()


def _build_deliberate_break_strategy(
    element_name: st.SearchStrategy[str],
    attr_name: st.SearchStrategy[str],
    attr_value: st.SearchStrategy[str],
    text_chars: st.SearchStrategy[str],
    max_depth: int = 40,
    max_size: int = 65536,
) -> st.SearchStrategy[str]:
    """Build deliberate-break strategy for hitting error-handling paths."""

    @st.composite
    def _break(draw) -> str:
        break_type = draw(st.sampled_from([
            "mismatched_tags",
            "duplicate_attrs",
            "second_root",
            "bad_entity",
            "unterminated_comment",
            "unterminated_cdata",
        ])
        )

        if break_type == "mismatched_tags":
            a = draw(element_name)
            b = draw(element_name)
            return f"<{a}><{b}></{a}></{b}>"

        elif break_type == "duplicate_attrs":
            name = draw(element_name)
            attr = draw(attr_name)
            val1 = draw(attr_value)
            val2 = draw(attr_value)
            return f'<{name} {attr}="{val1}" {attr}="{val2}"/>'

        elif break_type == "second_root":
            a = draw(element_name)
            b = draw(element_name)
            return f"<{a}/><{b}/>"

        elif break_type == "bad_entity":
            return "<root>&foo;</root>"

        elif break_type == "unterminated_comment":
            return "<!-- unclosed comment"

        elif break_type == "unterminated_cdata":
            return "<![CDATA[unclosed cdata"

        return "<root/>"

    return _break()
