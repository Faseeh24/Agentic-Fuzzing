"""
fuzzer/fallback_strategy.py — bundled, crash-focused Hypothesis strategy.

Used by the orchestrator as a safety net when the LLM-generated seed strategy
fails AST validation or cannot be loaded at runtime. This fallback is designed
to be **aggressive** — it generates malformed XML that stresses mxml's parser,
increasing the chance of finding crashes (ASan/UBSan violations, segfaults, etc.).
"""

import random
import string

import hypothesis.strategies as st


# ---------------------------------------------------------------------------
# Safe alphabet for text content (avoids accidental well-formedness)
# ---------------------------------------------------------------------------
_SAFE = string.printable.replace("&", "").replace("<", "").replace(">", "").replace('"', "").replace("'", "")

# ---------------------------------------------------------------------------
# Element names — include edge cases
# ---------------------------------------------------------------------------
_NAME_NORMAL = st.text(alphabet=string.ascii_letters + string.digits + "_-:", min_size=1, max_size=10)
_NAME_DIGIT_START = st.builds(lambda c, rest: c + rest, st.text(alphabet=string.digits, min_size=1, max_size=1),
                              _NAME_NORMAL)
_NAME_LONG = st.text(alphabet=string.ascii_letters + string.digits + "_-:", min_size=50, max_size=200)
_NAME = st.one_of(_NAME_NORMAL, _NAME_DIGIT_START, _NAME_LONG)

# ---------------------------------------------------------------------------
# Attribute strategies — including malformed ones
# ---------------------------------------------------------------------------
_ATTR_NAME = st.text(alphabet=string.ascii_letters + string.digits + "_-:", min_size=1, max_size=20)
_ATTR_VALUE_SAFE = st.text(alphabet=_SAFE, min_size=0, max_size=30)
_ATTR_VALUE_LONG = st.text(alphabet=_SAFE, min_size=200, max_size=1000)
_ATTR_VALUE_CONTROL = st.builds(lambda v, c: v + c + v, _ATTR_VALUE_SAFE,
                                st.just(random.choice(["\x00", "\x01", "\x0c", "\x1f"])))

_ATTR_PAIR = st.builds(lambda n, v: f'{n}="{v}"', _ATTR_NAME, _ATTR_VALUE_SAFE)
_ATTR_PAIR_LONG = st.builds(lambda n, v: f'{n}="{v}"', _ATTR_NAME, _ATTR_VALUE_LONG)
_ATTR_PAIR_CONTROL = st.builds(lambda n, v: f'{n}="{v}"', _ATTR_NAME, _ATTR_VALUE_CONTROL)
_ATTR_DUPLICATE = st.builds(lambda n, v1, v2: f'{n}="{v1}" {n}="{v2}"', _ATTR_NAME, _ATTR_VALUE_SAFE, _ATTR_VALUE_SAFE)
_ATTR_UNTERMINATED = st.builds(lambda n, v: f'{n}="{v}', _ATTR_NAME, _ATTR_VALUE_SAFE)
_ATTR_NO_VALUE = st.builds(lambda n: f'{n}=', _ATTR_NAME)
_ATTR_EMPTY = st.builds(lambda n: f'{n}=""', _ATTR_NAME)
_ATTR_BAD_QUOTES = st.builds(lambda n, v: f'{n}=\'{v}\'', _ATTR_NAME, _ATTR_VALUE_SAFE)

_ATTR = st.one_of(_ATTR_PAIR, _ATTR_PAIR_LONG, _ATTR_PAIR_CONTROL,
                  _ATTR_DUPLICATE, _ATTR_UNTERMINATED, _ATTR_NO_VALUE,
                  _ATTR_EMPTY, _ATTR_BAD_QUOTES)
_ATTRS = st.lists(_ATTR, min_size=1, max_size=5)

# ---------------------------------------------------------------------------
# Text content — including edge cases
# ---------------------------------------------------------------------------
_TEXT_NORMAL = st.text(alphabet=_SAFE, min_size=0, max_size=20)
_TEXT_LONG = st.text(alphabet=_SAFE, min_size=200, max_size=1000)
_TEXT_CONTROL = st.builds(lambda t, c: t + c + t, _TEXT_NORMAL,
                          st.just(random.choice(["\x00", "\x01", "\x0c", "\x1f", "\x0b"])))
_TEXT_ENTITY = st.text(alphabet="&;", min_size=1, max_size=10)
_TEXT = st.one_of(_TEXT_NORMAL, _TEXT_LONG, _TEXT_CONTROL, _TEXT_ENTITY)

# ---------------------------------------------------------------------------
# Entity reference strategies
# ---------------------------------------------------------------------------
_ENTITY_VALID = st.sampled_from(["amp", "lt", "gt", "quot", "apos"])
_ENTITY_INVALID = st.text(alphabet=string.ascii_letters, min_size=1, max_size=10)
_ENTITY = st.builds(lambda name: f"&{name};", st.one_of(_ENTITY_VALID, _ENTITY_INVALID))
_ENTITY_INCOMPLETE = st.sampled_from(["&", "&amp", "&lt", "&foo", "&;"])
_ENTITY_REF = st.one_of(_ENTITY, _ENTITY_INCOMPLETE)

# ---------------------------------------------------------------------------
# Malformed tag strategies
# ---------------------------------------------------------------------------
def _make_mismatched():
    """Generate mismatched tag pairs like <a><b></a></b>"""
    names = st.lists(_NAME, min_size=2, max_size=4)
    return st.builds(lambda ns: "".join(f"<{ns[i]}></{ns[-1-i]}>" for i in range(len(ns))), names)

def _make_unclosed():
    """Generate unterminated tags like <a><b><c"""
    depth = st.integers(2, 8)
    return st.builds(lambda d: "".join(f"<n{i}" for i in range(d)), depth)

def _make_double_close():
    """Generate double close tags like <a></a></a>"""
    return st.builds(lambda n: f"<{n}></{n}></{n}>", _NAME)

def _make_two_roots():
    """Generate two root elements like <a/><b/>"""
    return st.builds(lambda n1, n2: f"<{n1}/><{n2}/> ", _NAME, _NAME)

def _make_interleaved():
    """Generate interleaved unclosed tags like <a><b></a><c></c></b>"""
    return st.builds(lambda n1, n2, n3: f"<{n1}><{n2}</{n1}><{n3}></{n3}></{n2}>", _NAME, _NAME, _NAME)

def _make_selfclose_extra():
    """Generate self-close followed by extra close like <a/></a></a>"""
    return st.builds(lambda n: f"<{n}/></{n}></{n}>", _NAME)

def _make_double_slash():
    """Generate double-slash self-close like <a//>"""
    return st.builds(lambda n: f"<{n}//>", _NAME)

def _make_unterminated_attr():
    """Generate tag with unterminated attribute like <a attr="unclosed"""
    return st.builds(lambda n, a, v: f"<{n} {a}=\"{v}", _NAME, _ATTR_NAME, _ATTR_VALUE_SAFE)

def _make_bare_angle():
    """Generate bare angle bracket or invalid sequences"""
    return st.sampled_from(["<", "<<", "< >", "<>"])

def _make_null_in_name():
    """Generate element name with null byte"""
    return st.builds(lambda n: f"<{n}\x00/>", _NAME)

# ---------------------------------------------------------------------------
# Comment/CDATA/PI strategies
# ---------------------------------------------------------------------------
_COMMENT_VALID = st.builds(lambda c: f"<!-- {c} -->", _TEXT_NORMAL)
_COMMENT_UNTERMINATED = st.builds(lambda c: f"<!-- {c}", _TEXT_NORMAL)
_COMMENT_NESTED = st.just("<!-- <!-- -->")
_COMMENT_EXTRA = st.builds(lambda c: f"<!-- {c} -->extra", _TEXT_NORMAL)

_CDATA_VALID = st.builds(lambda d: f"<![CDATA[{d}]]>", _TEXT_NORMAL)
_CDATA_UNTERMINATED = st.builds(lambda d: f"<![CDATA[{d}", _TEXT_NORMAL)
_CDATA_EXTRA = st.builds(lambda d: f"<![CDATA[{d}]]]>extra", _TEXT_NORMAL)
_CDATA_END_ONLY = st.just("]]>")

_PI_VALID = st.builds(lambda p: "<?" + p + "?>", st.text(alphabet=string.ascii_letters + string.digits + " _", min_size=1, max_size=20))
_PI_UNTERMINATED = st.builds(lambda p: "<?" + p, st.text(alphabet=string.ascii_letters, min_size=1, max_size=10))
_PI_BARE = st.just("<?")

_DECL = st.just('<?xml version="1.0"?>')
_DECL_INVALID = st.sampled_from(['<?xml', '<?xml version=', '<?xml version="1.0"'])

# ---------------------------------------------------------------------------
# Well-formed element strategies (for mixing in)
# ---------------------------------------------------------------------------
_OPEN_TAG = st.builds(lambda n, a: f"<{n}{' ' + ' '.join(a) if a else ''}", _NAME, _ATTRS)
_SELF_CLOSING = st.builds(lambda n, a: f"<{n}{' ' + ' '.join(a) if a else ''}/> ", _NAME, _ATTRS)
_LEAF = st.builds(lambda n, a, t: f"<{n}{' ' + ' '.join(a) if a else ''}>{t}</{n}>", _NAME, _ATTRS, _TEXT)
_NESTED = st.recursive(
    base=st.one_of(_SELF_CLOSING, _LEAF),
    extend=lambda children: st.builds(
        lambda n, a, body: f"<{n}{' ' + ' '.join(a) if a else ''}>{body}</{n}>",
        _NAME,
        st.lists(_ATTR, min_size=0, max_size=3),
        st.one_of(children, _TEXT),
    ),
    max_leaves=8,
)

# ---------------------------------------------------------------------------
# Main strategy: heavy emphasis on malformed inputs
# ---------------------------------------------------------------------------
_malformed = st.one_of(
    _make_mismatched(),
    _make_unclosed(),
    _make_double_close(),
    _make_two_roots(),
    _make_interleaved(),
    _make_selfclose_extra(),
    _make_double_slash(),
    _make_unterminated_attr(),
    _make_bare_angle(),
    _make_null_in_name(),
    _COMMENT_UNTERMINATED,
    _COMMENT_NESTED,
    _CDATA_UNTERMINATED,
    _CDATA_EXTRA,
    _CDATA_END_ONLY,
    _PI_UNTERMINATED,
    _PI_BARE,
    _DECL_INVALID,
    st.builds(lambda n, e: f"<{n}>{e}</{n}>", _NAME, st.just("&foo;")),
    st.builds(lambda n, e: f"<{n}>{e}</{n}>", _NAME, _TEXT_ENTITY),
    st.builds(lambda n: f"<{n}>{"x" * 500}</{n}>", _NAME),
    st.builds(lambda n: f"<{n} attr=\"{"x" * 800}\"></{n}>", _NAME),
)

_xml_safe = st.one_of(
    _SELF_CLOSING,
    _LEAF,
    _NESTED,
    _COMMENT_VALID,
    _CDATA_VALID,
    _PI_VALID,
    _DECL,
    _TEXT_NORMAL,
)

xml_strategy = st.one_of(
    _malformed,
    _xml_safe,
)
