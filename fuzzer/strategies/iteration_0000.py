from hypothesis import strategies as st

names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:-.",
    min_size=1,
    max_size=10
).filter(lambda x: not x.startswith("-") and not x.startswith("."))

safe_text_chars = st.one_of(
    st.sampled_from(["\t", "\n", "\r"]),
    st.characters(min_codepoint=0x20, max_codepoint=0xD7FF, blacklist_characters="<&"),
    st.characters(min_codepoint=0xE000, max_codepoint=0xFFFD, blacklist_characters="<&"),
)

entity_refs = st.sampled_from(["&amp;", "&lt;", "&gt;", "&quot;", "&apos;"])
char_refs = st.one_of(
    st.builds(lambda x: f"&#{x};", st.integers(32, 126)),
    st.builds(lambda x: f"&#x{x:x};", st.integers(32, 126))
)
text_chunk = st.text(alphabet=safe_text_chars, min_size=1, max_size=40)
content_piece = st.one_of(text_chunk, entity_refs, char_refs)

@st.composite
def gen_attribute(draw):
    """Generates a well-formed or unquoted attribute."""
    name = draw(names)
    val_type = draw(st.sampled_from(['double', 'single', 'unquoted']))
    if val_type == 'double':
        val = draw(st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xD7FF, blacklist_characters='"<'), max_size=30))
        return f'{name}="{val}"'
    elif val_type == 'single':
        val = draw(st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xD7FF, blacklist_characters="\'<"), max_size=30))
        return f"{name}='{val}'"
    else:
        val = draw(st.text(alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E, blacklist_characters='"\'=<>`'), min_size=1, max_size=15))
        return f'{name}={val}'

@st.composite
def gen_cdata(draw):
    """Generates safe CDATA blocks."""
    inner = draw(st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xD7FF), max_size=100))
    inner = inner.replace("]]>", "]] >")
    return f"<![CDATA[{inner}]]>"

@st.composite
def gen_comment(draw):
    """Generates safe comment blocks."""
    inner = draw(st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xD7FF), max_size=100))
    inner = inner.replace("--", "- -")
    if inner.endswith("-"):
        inner += " "
    return f"<!--{inner}-->"

@st.composite
def gen_pi(draw):
    """Generates processing instructions."""
    target = draw(names)
    while target.lower().startswith("xml"):
        target = draw(names)
    content = draw(st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xD7FF, blacklist_characters="?"), max_size=50))
    return f"<?{target} {content}?>"

@st.composite
def gen_dtd(draw):
    """Generates opaque DTD / declarations."""
    kind = draw(st.sampled_from(["DOCTYPE", "ENTITY", "ELEMENT", "NOTATION"]))
    name = draw(names)
    if kind == "DOCTYPE":
        return f"<!DOCTYPE {name} SYSTEM \"http://example.com\">"
    elif kind == "ENTITY":
        val = draw(st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xD7FF, blacklist_characters='"'), max_size=20))
        return f'<!ENTITY {name} "{val}">'
    elif kind == "ELEMENT":
        return f"<!ELEMENT {name} (ANY)>"
    else:
        return f"<!NOTATION {name} SYSTEM \"http://example.com\">"

@st.composite
def gen_element(draw, max_depth=10):
    """Recursively generates elements with depth limits."""
    name = draw(names)
    attrs = draw(st.lists(gen_attribute(), max_size=5))
    seen = set()
    unique_attrs = []
    for attr in attrs:
        attr_name = attr.split("=")[0]
        if attr_name not in seen:
            seen.add(attr_name)
            unique_attrs.append(attr)
    attr_str = " " + " ".join(unique_attrs) if unique_attrs else ""

    if max_depth <= 0:
        leaf_type = draw(st.sampled_from(["empty", "text"]))
        if leaf_type == "empty":
            return f"<{name}{attr_str}/>"
        else:
            text = draw(st.lists(content_piece, min_size=1, max_size=5).map("".join))
            return f"<{name}{attr_str}>{text}</{name}>"

    num_children = draw(st.integers(0, 4))
    if num_children == 0:
        leaf_type = draw(st.sampled_from(["empty", "text"]))
        if leaf_type == "empty":
            return f"<{name}{attr_str}/>"
        else:
            text = draw(st.lists(content_piece, min_size=1, max_size=5).map("".join))
            return f"<{name}{attr_str}>{text}</{name}>"

    children = []
    for _ in range(num_children):
        child_type = draw(st.sampled_from(["element", "text", "cdata", "comment", "pi", "dtd"]))
        if child_type == "element":
            children.append(draw(gen_element(max_depth - 1)))
        elif child_type == "text":
            children.append(draw(st.lists(content_piece, min_size=1, max_size=3).map("".join)))
        elif child_type == "cdata":
            children.append(draw(gen_cdata()))
        elif child_type == "comment":
            children.append(draw(gen_comment()))
        elif child_type == "pi":
            children.append(draw(gen_pi()))
        elif child_type == "dtd":
            children.append(draw(gen_dtd()))

    return f"<{name}{attr_str}>{''.join(children)}</{name}>"

@st.composite
def gen_prolog(draw):
    """Generates optional BOM and XML declaration."""
    bom = "\uFEFF" if draw(st.booleans()) else ""
    decl = '<?xml version="1.0" encoding="UTF-8"?>\n' if draw(st.booleans()) else ""
    return bom + decl

@st.composite
def gen_mismatched_tags(draw):
    """Intentionally violates close tag matching."""
    t1, t2, t3 = draw(st.lists(names, min_size=3, max_size=3, unique=True))
    shape = draw(st.integers(1, 3))
    if shape == 1:
        return f"<{t1}><{t2}></{t1}></{t2}>"
    elif shape == 2:
        return f"<{t1}><{t2}><{t3}></{t2}></{t1}></{t3}>"
    else:
        return f"<{t1}><{t2}><{t3}></{t1}></{t3}></{t2}>"

@st.composite
def gen_duplicate_attributes(draw):
    """Intentionally generates duplicate attributes on one element."""
    elem = draw(names)
    dup_attr = draw(names)
    val1 = draw(st.text(alphabet="abcdef", min_size=1, max_size=5))
    val2 = draw(st.text(alphabet="123456", min_size=1, max_size=5))
    other_attrs = draw(st.lists(gen_attribute(), max_size=3))
    other_attrs = [a for a in other_attrs if not a.startswith(dup_attr + "=")]
    parts = [f'{dup_attr}="{val1}"'] + other_attrs + [f'{dup_attr}="{val2}"']
    if draw(st.booleans()):
        parts = [f'{dup_attr}="{val1}"', f'{dup_attr}="{val2}"'] + other_attrs
    return f"<{elem} {' '.join(parts)}/>"

@st.composite
def gen_multiple_roots(draw):
    """Intentionally generates multiple root nodes."""
    root1 = draw(gen_element(max_depth=2))
    root2 = draw(gen_element(max_depth=2))
    return f"{root1}\n{root2}"

@st.composite
def xml_strategy_impl(draw):
    """Main strategy selecting between normal and broken flows."""
    prolog = draw(gen_prolog())
    choices = ['well_formed', 'mismatched', 'duplicate_attrs', 'multiple_roots']
    weights = [80, 7, 7, 6]
    total = sum(weights)
    idx = draw(st.integers(0, total - 1))
    cum = 0
    selected = 'well_formed'
    for i, w in enumerate(weights):
        cum += w
        if idx < cum:
            selected = choices[i]
            break

    if selected == 'well_formed':
        body = draw(gen_element(max_depth=5))
    elif selected == 'mismatched':
        body = draw(gen_mismatched_tags())
    elif selected == 'duplicate_attrs':
        body = draw(gen_duplicate_attributes())
    else:
        body = draw(gen_multiple_roots())
    return prolog + body

xml_strategy = xml_strategy_impl()