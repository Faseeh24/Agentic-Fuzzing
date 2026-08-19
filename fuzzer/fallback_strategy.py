"""
fuzzer/fallback_strategy.py — bundled, known-good Hypothesis strategy.

Used by the orchestrator as a safety net when the LLM-generated seed strategy
fails AST validation or cannot be loaded at runtime (e.g. the model hallucinated
an API or misused st.recursive). It guarantees the fuzzing loop can still run
and produce examples. The primary path always tries the LLM-authored strategy
first; this file is only a fallback.
"""

import string

import hypothesis.strategies as st


# Printable ASCII without the XML-significant characters, so generated text
# does not accidentally break well-formedness detection.
_SAFE = string.printable.replace("&", "").replace("<", "").replace(">", "").replace('"', "").replace("'", "")

_NAME = st.text(alphabet=string.ascii_letters + string.digits + "_-:", min_size=1, max_size=10)
_TEXT = st.text(alphabet=_SAFE, min_size=0, max_size=20)


def _attr() -> st.SearchStrategy[str]:
    return st.builds(lambda n, v: f'{n}="{v}"', _NAME, _TEXT)


_ATTRS = st.lists(_attr(), max_size=3)


def _open_tag(name: str, attrs: list[str]) -> str:
    return f"<{name}{' ' + ' '.join(attrs) if attrs else ''}"


_SELF_CLOSING = st.builds(lambda n, a: f"{_open_tag(n, a)}/>", _NAME, _ATTRS)
_LEAF = st.builds(lambda n, a, t: f"{_open_tag(n, a)}>{t}</{n}>", _NAME, _ATTRS, _TEXT)

_NESTED = st.recursive(
    base=st.one_of(_SELF_CLOSING, _LEAF),
    extend=lambda children: st.builds(
        lambda n, a, body: f"{_open_tag(n, a)}>{body}</{n}>",
        _NAME,
        _ATTRS,
        st.one_of(children, _TEXT),
    ),
    max_leaves=10,
)

xml_strategy = st.one_of(_NESTED, _TEXT)
