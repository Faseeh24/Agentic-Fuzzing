```python
import hypothesis.strategies as st

name_start_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
name_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"

@st.composite
def name_strategy_func(draw):
    start = draw(st.sampled_from(name_start_chars))
    rest = draw(st.text(alphabet=st.sampled_from(name_chars), min_size=0, max_size=14))
    return start + rest

name_strategy = name_strategy_func()
pi_name_strategy = name_strategy.filter(lambda x: not x.lower().startswith('xml'))

# Safe XML Character Strategies (excluding surrogates and non-characters)
xml_char_strategy = st.one_of(
    st.characters(min_codepoint=0x20, max_codepoint=0xD7FF),
    st.characters(min_codepoint=0xE000, max_codepoint=0xFFFD),
    st.sampled_from(['\t', '\n', '\r'])
)

double_quote_attrs_chars = st.one_of(
    st.characters(min_codepoint=0x20, max_codepoint=0xD7FF, blacklist_characters='"<&'),
    st.characters(min_codepoint=0xE000, max_codepoint=0xFFFD, blacklist_characters='"<&'),
    st.sampled_from(['\t', '\n', '\r'])
)

single_quote_attrs_chars = st.one_of(
    st.characters(min_codepoint=0x20, max_codepoint=0xD7FF, blacklist_characters="'<&"),
    st.characters(min_codepoint=0xE000, max_codepoint=0xFFFD, blacklist_characters="'<&"),
    st.sampled_from(['\t', '\n', '\r'])
)

text_content_chars = st.one_of(
    st.characters(min_codepoint=0x20, max_codepoint=0xD7FF, blacklist_characters="<&"),
    st.characters(min_codepoint=0xE000, max_codepoint=0xFFFD, blacklist_characters="<&"),
    st.sampled_from(['\t', '\n', '\r'])
)

@st.composite
def attributes_dict(draw, allow_duplicates=False):
    """Generates lists of attributes with quoted values."""
    names = draw(st.lists(name_strategy, min_size=0, max_size=5, unique=not allow_duplicates))
    attrs = []
    for name in names:
        quote_type = draw(st.sampled_from(['double', 'single']))
        if quote_type == 'double':
            val_chars = draw(st.text(alphabet=double_quote_attrs_chars, min_size=0, max_size=20))
            val = f'"{val_chars}"'
        else:
            val_chars = draw(st.text(alphabet=single_quote_attrs_chars, min_size=0, max_size=20))
            val = f"'{val_chars}'"
        attrs.append((name, val))
    return attrs

@st.composite
def element_strategy(draw, current_depth=0, max_depth=8):
    """Recursively generates well-formed elements within safe nesting bounds. Returns (name, element_str)"""
    name = draw(name_strategy)
    attrs_list = draw(attributes_dict(allow_duplicates=False))
    attrs_str = "".join(f" {k}={v}" for k, v in attrs_list)

    is_self_closing = draw(st.booleans())
    if is_self_closing or current_depth >= max_depth:
        return name, f"<{name}{attrs_str}/>"
    
    num_children = draw(st.integers(min_value=0, max_value=4))
    children = []
    for _ in range(num_children):
        child_type = draw(st.sampled_from(['element', 'text', 'cdata', 'comment', 'pi']))
        if child_type == 'element':
            _, child_str = draw(element_strategy(current_depth + 1, max_depth))
            children.append(child_str)
        elif child_type == 'text':
            text_parts = draw(st.lists(st.one_of(
                st.text(alphabet=text_content_chars, min_size=1, max_size=20),
                st.sampled_from(['&amp;', '&lt;', '&gt;', '&quot;', '&apos;']),
                st.integers(min_value=32, max_value=0xD7FF).map(lambda x: f"&#{x};"),
                st.integers(min_value=0xE000, max_value=0xFFFD).map(lambda x: f"&#{x};"),
                st.integers(min_value=32, max_value=0xD7FF).map(lambda x: f"&#x{x:x};"),
                st.integers(min_value=0xE000, max_value=0xFFFD).map(lambda x: f"&#x{x:x};"),
            ), min_size=1, max_size=3))
            children.append("".join(text_parts))
        elif child_type == 'cdata':
            cdata_content = draw(st.text(alphabet=xml_char_strategy, min_size=0, max_size=50))
            while ']]>' in cdata_content:
                cdata_content = cdata_content.replace(']]>', ']}')
            children.append(f"<![CDATA[{cdata_content}]]>")
        elif child_type == 'comment':
            comment_content = draw(st.text(alphabet=xml_char_strategy, min_size=0, max_size=50))
            while '--' in comment_content:
                comment_content = comment_content.replace('--', '- -')
            if comment_content.endswith('-'):
                comment_content += ' '
            children.append(f"<!--{comment_content}-->")
        elif child_type == 'pi':
            pi_name = draw(pi_name_strategy)
            pi_content = draw(st.text(alphabet=xml_char_strategy, min_size=0, max_size=50))
            while '?>' in pi_content:
                pi_content = pi_content.replace('?>', '? >')
            children.append(f"<?{pi_name} {pi_content}?>")
            
    content_str = "".join(children)
    return name, f"<{name}{attrs_str}>{content_str}</{name}>"

@st.composite
def dtd_strategy(draw, root_name):
    """Generates DOCTYPE declaration mapped to the root element name."""
    has_internal = draw(st.booleans())
    if not has_internal:
        return draw(st.sampled_from([
            f'<!DOCTYPE {root_name} SYSTEM "Note.dtd">',
            f'<!DOCTYPE {root_name} PUBLIC "Note" "Note.dtd">',
            ''
        ]))
    else:
        return f'<!DOCTYPE {root_name} [\n  <!ENTITY info "Value">\n  <!ELEMENT {root_name} ANY>\n  <!ATTLIST {root_name} id CDATA #IMPLIED>\n]>'

@st.composite
def well_formed_document(draw):
    """Generates complete valid XML documents including optional prologs, BOM, and misc nodes."""
    bom = draw(st.sampled_from(['\ufeff', '']))
    has_prolog = draw(st.booleans())
    prolog = ""
    if has_prolog:
        version = draw(st.sampled_from(['1.0', '1.1']))
        encoding = draw(st.sampled_from(['UTF-8', 'utf-8', 'UTF-16', '']))
        encoding_str = f' encoding="{encoding}"' if encoding else ''
        standalone = draw(st.sampled_from(['yes', 'no', '']))
        standalone_str = f' standalone="{standalone}"' if standalone else ''
        prolog = f'<?xml version="{version}"{encoding_str}{standalone_str}?>\n'
        
    misc_before_list = draw(st.lists(st.one_of(
        st.just("<!-- comment before -->"),
        st.just("<?pi_before info?>"),
        st.just("\n   \t\n")
    ), min_size=0, max_size=3))
    misc_before = "".join(misc_before_list)
    
    root_name, root_str = draw(element_strategy(current_depth=0, max_depth=5))
    
    has_dtd = draw(st.booleans())
    dtd_str = ""
    if has_dtd:
        dtd_str = draw(dtd_strategy(root_name)) + "\n"
    
    misc_after_list = draw(st.lists(st.one_of(
        st.just("<!-- comment after -->"),
        st.just("<?pi_after info?>"),
        st.just("\n   \t\n")
    ), min_size=0, max_size=3))
    misc_after = "".join(misc_after_list)
    
    return f"{bom}{prolog}{misc_before}{dtd_str}{root_str}{misc_after}"

@st.composite
def mismatched_tags_strategy(draw):
    """Generates deeply nested mismatched elements to hit tag pairing check logic."""
    depth = draw(st.integers(min_value=2, max_value=6))
    names = [draw(name_strategy) for _ in range(depth)]
    
    open_tags = []
    for name in names:
        attrs_list = draw(attributes_dict(allow_duplicates=False))
        attrs_str = "".join(f" {k}={v}" for k, v in attrs_list)
        open_tags.append(f"<{name}{attrs_str}>")
    
    open_tags_str = "".join(open_tags)
    content = draw(st.text(alphabet=text_content_chars, min_size=0, max_size=20))
    
    close_names = list(names)
    mutation_type = draw(st.sampled_from(['reverse', 'mismatch_one', 'shuffle']))
    if mutation_type == 'reverse':
        close_names.reverse()
    elif mutation_type == 'mismatch_one':
        idx = draw(st.integers(0, len(close_names) - 1))
        close_names[idx] = close_names[idx] + "_bad"
    else:
        if len(close_names) > 1:
            idx = draw(st.integers(0, len(close_names) - 2))
            close_names[idx], close_names[idx+1] = close_names[idx+1], close_names[idx]
            
    if close_names == names:
        close_names[0] = close_names[0] + "_force_bad"
        
    close_tags = "".join(f"</{name}>" for name in close_names)
    return f"{open_tags_str}{content}{close_tags}"

@st.composite
def duplicate_attributes_strategy(draw):
    """Generates elements containing duplicate attributes, with optional character entity values."""
    name = draw(name_strategy)
    other_attrs = draw(attributes_dict(allow_duplicates=False))
    dup_name = draw(name_strategy.filter(lambda x: x not in [k for k, _ in other_attrs]))
    
    char_ref1 = draw(st.sampled_from(['&#32;', '&#x20;', '&#65;', '&#x41;']))
    char_ref2 = draw(st.sampled_from(['&#33;', '&#x21;', '&#66;', '&#x42;']))
    
    val1 = f'"{char_ref1}' + draw(st.text(alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"), min_size=1, max_size=5)) + '"'
    val2 = f'"{char_ref2}' + draw(st.text(alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"), min_size=1, max_size=5)) + '"'
    
    attrs = list(other_attrs)
    attrs.insert(draw(st.integers(0, len(attrs))), (dup_name, val1))
    attrs.insert(draw(st.integers(0, len(attrs))), (dup_name, val2))
    
    attrs_str = " ".join(f"{k}={v}" for k, v in attrs)
    is_self_closing = draw(st.booleans())
    if is_self_closing:
        return f"<{name} {attrs_str}/>"
    else:
        return f"<{name} {attrs_str}>content</{name}>"

@st.composite
def multiple_roots_strategy(draw):
    """Generates documents with multiple root elements to trigger root validation."""
    _, root1 = draw(element_strategy(current_depth=0, max_depth=3))
    _, root2 = draw(element_strategy(current_depth=0, max_depth=3))
    maybe_more_list = draw(st.lists(element_strategy(current_depth=0, max_depth=2), min_size=0, max_size=2))
    maybe_more = [r for _, r in maybe_more_list]
    all_roots = [root1, root2] + maybe_more
    return "\n".join(all_roots)

@st.composite
def unquoted_attribute_strategy(draw):
    """Generates documents with unquoted attribute values to trigger syntax parser errors."""
    name = draw(name_strategy)
    bad_attr_name = draw(name_strategy)
    bad_attr_val = draw(st.text(alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"), min_size=1, max_size=10))
    return f"<{name} {bad_attr_name}={bad_attr_val}>content</{name}>"

@st.composite
def deliberate_break_strategy(draw):
    """Selects one of the targeted XML validation error conditions."""
    violation_type = draw(st.sampled_from(['mismatch', 'duplicate', 'multi_root', 'unquoted_attr']))
    if violation_type == 'mismatch':
        return draw(mismatched_tags_strategy())
    elif violation_type == 'duplicate':
        return draw(duplicate_attributes_strategy())
    elif violation_type == 'multi_root':
        return draw(multiple_roots_strategy())
    else:
        return draw(unquoted_attribute_strategy())

@st.composite
def xml_strategy_generator(draw):
    """Probabilistically chooses between generating well-formed documents or deliberate schema breaks."""
    choice = draw(st.integers(min_value=1, max_value=100))
    if choice <= 82:
        return draw(well_formed_document())
    else:
        return draw(deliberate_break_strategy())

xml_strategy = xml_strategy_generator()
```