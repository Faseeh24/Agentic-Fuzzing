import hypothesis.strategies as st
import string

_NAME = st.text(alphabet=string.ascii_letters + string.digits + "_-", min_size=1, max_size=20)

_mismatched = st.builds(
    lambda a, b: f"<{a}><{b}></{a}></{b}>",
    _NAME, _NAME,
)

_dup_attr = st.builds(
    lambda n, v: f'<{n} x="{v}" x="{v}" x="{v}"/>',
    _NAME, st.text(min_size=1, max_size=200),
)

xml_strategy = st.one_of(
    _mismatched,
    _mismatched,
    _dup_attr,
)