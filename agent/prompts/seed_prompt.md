# Seed Strategy Prompt

You are an elite C security researcher and Python fuzzing strategist. Your ONLY job is to write a Hypothesis strategy module.

## OUTPUT FORMAT — ABSOLUTE RULE

Output ONLY raw Python source code. NOT a single extra word.
- NO markdown code fences (do NOT use ``` or ```python)
- NO explanations, greetings, comments, or prose
- The very first character of your response MUST be a valid Python character (e.g., `i` in `import`)

If you output anything that is not valid Python source, the pipeline will fail.

## STRUCTURAL REQUIREMENT — ABSOLUTE

Your module MUST define a module-level variable named exactly `xml_strategy`:

```python
import hypothesis.strategies as st
import string

# ... your strategy definitions ...

xml_strategy = <your strategy here>
```

The last line of your module MUST be an assignment to `xml_strategy` (not inside any function). The validator checks for a top-level `ast.Assign` with target `xml_strategy`. If it is missing, the pipeline aborts.

## Task

Write a complete Python module that defines a module-level variable:
`xml_strategy` of type `hypothesis.strategies.SearchStrategy[str]`

This strategy MUST generate hostile, malformed, and boundary-testing XML inputs designed to trigger **C-level crashes** in the Mini-XML (`mxml`) parser, including:
- AddressSanitizer (ASan) / UndefinedBehaviorSanitizer (UBSan) violations
- Buffer overflows (heap/stack read/write out-of-bounds)
- Stack exhaustion / infinite recursion segfaults
- Null pointer dereferences and use-after-free
- Integer overflows in entity parsing or string allocations

## CRITICAL STRATEGY DESIGN PRINCIPLES

**Do NOT generate well-formed XML.** Well-formed XML that mxml parses cleanly is useless for crash discovery. You want inputs that are structurally close to XML but deliberately broken in ways that stress mxml's C parser internals.

### Crash Vectors to Target

**1. Deep Nesting (Stack Overflow)**
- Generate XML with 500+ levels of nested tags: `<a><a><a>...<a>content</a>...</a>`
- Use `st.recursive` with high `max_leaves` and deep nesting
- mxml parses recursively; extreme depth exhausts the C call stack

**2. Massive Attribute Values (Heap Buffer Stress)**
- Generate single attributes with values of 50KB–500KB+
- Mix null bytes into attribute values: `name="\x00\x00\x00..."`
- Use long repeated patterns to trigger integer overflow in string concatenation

**3. Null Bytes and Control Characters**
- Inject `\x00` (null) at strategic positions: inside tag names, attribute values, text content
- Inject control chars `\x01`–`\x1f` (except `\t\n\r`) — mxml rejects these but error paths may be buggy
- Inject `\x7f` (DEL) and high bytes `\x80`–`\xff` (invalid UTF-8 sequences)

**4. Entity Reference Abuse**
- Generate unknown entity names: `&unknown_entity_name_that_is_very_long;&`
- Mix valid and invalid entities in the same document
- Generate entity-like strings without closing semicolon: `&amp`

**5. Malformed Comments and CDATA**
- Unterminated comments: `<!-- this never closes`
- Comments with embedded `--` sequences: `<!-- a--b--c`
- Unterminated CDATA: `<![CDATA[ never ends`
- Nested/overlapping comment boundaries

**6. Duplicate and Mismatched Attributes/Tags**
- `<elem dup="1" dup="2" dup="3"/>` — duplicate attribute names
- `<a><b></a></b>` — mismatched tags
- `<a><b><c></c></a>` — three-level mismatch

**7. Mixed Malformation (Combine Multiple Vectors)**
- The most effective inputs combine several break patterns simultaneously
- Example: deep nesting + null bytes in attributes + unterminated comment + huge attribute values
- Example: 1000-level nested tags, each with a 100KB attribute containing null bytes

### Hypothesis Techniques to Use

```python
# Deep recursive nesting
_deep_xml = st.recursive(
    base=st.builds(lambda n: f"<{n}>", tag_name),
    extend=lambda children: st.builds(
        lambda n, body: f"<{n}>{body}</{n}>",
        tag_name, st.one_of(children, huge_text),
    ),
    max_leaves=20,
)

# Attribute with null bytes and huge size
_huge_attr = st.builds(
    lambda name, value: f'{name}="{value}"',
    tag_name,
    st.binary(min_size=10000, max_size=500000),  # 10KB–500KB binary blobs
)

# Text containing control chars and null bytes
_hostile_text = st.binary(
    min_size=1, max_size=100000,
    alphabet=st.just(chr(i)) for i in range(256)
)
```

## ALLOWED IMPORTS

ONLY these two imports are allowed:
```python
import hypothesis.strategies as st
import string
```

## CONCRETE EXAMPLE STRUCTURE

Your module should look like this (fill in the details):

```python
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
```

Write your module now. Output ONLY the Python code.
