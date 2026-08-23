import hypothesis.strategies as st
import string

_NAME = st.text(alphabet=string.ascii_letters + string.digits + "_-", min_size=1, max_size=20)

# Deep nesting strategy for stack overflow
_deep_nested = st.recursive(
    base=st.builds(lambda n: f"<{n}/>", _NAME),
    extend=lambda children: st.builds(
        lambda n, body: f"<{n}>{body}</{n}>",
        _NAME, st.one_of(children, st.just("")),
    ),
    max_leaves=50,
)

# Hostile text with control chars and null bytes
_hostile_content = st.binary(min_size=100, max_size=100000)

# Huge attributes for heap stress
_huge_attr_val = st.binary(min_size=5000, max_size=500000)

# Tag with huge attribute
_huge_attr_tag = st.builds(
    lambda n, v: f'<{n} data="{v}"/>',
    _NAME, _huge_attr_val,
)

# Mismatched tag pairs
_mismatched = st.builds(
    lambda a, b: f"<{a}><{b}></{a}></{b}>",
    _NAME, _NAME,
)

# Duplicate attributes
_dup_attr = st.builds(
    lambda n, v: f'<{n} x="{v}" x="{v}" x="{v}"/>',
    _NAME, _huge_attr_val,
)

# Mix of all strategies
xml_strategy = st.one_of(
    _deep_nested,
    _huge_attr_tag,
    _mismatched,
    _dup_attr,
    st.builds(lambda h: f"<root>{h}</root>", _hostile_content),
    st.builds(lambda c: f"<!-- {c}", _hostile_content),  # unterminated comment
    st.builds(lambda c: f"<![CDATA[{c}", _hostile_content),  # unterminated CDATA
    st.builds(lambda e: f"<root>&{e};</root>", _NAME),  # bad entity
)