# Seed Strategy Prompt

You are an expert Python fuzzing strategist. Your ONLY job is to write a Hypothesis strategy module.

## OUTPUT FORMAT — ABSOLUTE RULE

Output ONLY raw Python source code. NOT a single extra word.
- NO markdown fences (no backticks)
- NO explanations
- NO commentary
- NO "Here is the code" or similar phrases
- The very first character of your response MUST be a valid Python character

If you output anything that is not valid Python source, the pipeline will fail.

## Task

Write a complete Python module that defines a module-level variable `xml_strategy`.
Its value must be a `hypothesis.strategies.SearchStrategy[str]` that generates XML test inputs for fuzzing the Mini-XML (mxml) C parser.

Allowed imports: `hypothesis.strategies as st`, `string`, `random`.
Nothing else.

## Target: Mini-XML (mxml) crash discovery

mxml accepts only 5 entities: `amp`, `lt`, `gt`, `quot`, `apos`.
Rejects raw control chars (0x00-0x1F except `\t`, `\n`, `\r`).
Requires valid UTF-8. Requires exactly one root element.

Your PRIMARY goal is to FIND CRASHES — ASan/UBSan violations, segfaults, undefined behavior.
Valid XML is secondary. Malformed and edge-case inputs should be the majority (70%+).

## Design requirements

- `xml_strategy` MUST be a plain module-level assignment: `xml_strategy = <strategy expression>`
- Do NOT define it inside a function or return it
- All helper functions must be named with leading underscore and defined BEFORE `xml_strategy`
- Every function and variable you reference MUST be defined
- No placeholders, no `...`, no `_NAME` unbound variables

## Hypothesis API Reference (Kaggle-compatible, hypothesis >=6.0)

### `st.builds(callable, *strategies, **kw_strategies)`
The FIRST argument MUST be a callable (function or lambda). All subsequent arguments are strategies that generate values passed to the callable.

```python
# CORRECT — first arg is a lambda (callable):
st.builds(lambda n: "<" + n + "/>", _NAME)
st.builds(lambda n, v: f'{n}="{v}"', _ATTR_NAME, _ATTR_VALUE)
st.builds(lambda n, a, v: f"<{n} {a}=\"{v}\">", _NAME, _ATTR_NAME, _ATTR_VALUE)

# WRONG — first arg is a strategy object, NOT a callable:
st.builds(st.sampled_from(["a", "b"]))  # WRONG — will crash with TypeError
```

### `st.sampled_from(items)`
Takes a plain Python list of values (NOT strategies). Returns one item from the list.

```python
st.sampled_from(["amp", "lt", "gt"])  # CORRECT
```

### `st.just(value)`
Returns a fixed value every time. Takes a plain Python value (NOT a strategy).

```python
st.just("<!-- comment -->")  # CORRECT
```

### `st.one_of(*strategies)`
Takes zero or more strategies (NOT plain values). Picks one at random.

```python
st.one_of(_A, _B, _C)  # CORRECT — all args are strategies
```

### `st.text(alphabet=string, min_size=int, max_size=int)`
`alphabet` must be a STRING (not a strategy). `min_size` and `max_size` must be ints.

```python
st.text(alphabet=string.ascii_letters, min_size=1, max_size=20)  # CORRECT
```

### `st.lists(strategy, min_size=int, max_size=int)`
First arg is a strategy (generates list elements).

```python
st.lists(_ATTR, min_size=0, max_size=5)  # CORRECT
```

### `st.recursive(base, extend, max_leaves=int)`
`base` is a strategy. `extend` MUST be a callable (lambda) that takes a strategy and returns a strategy.

```python
st.recursive(
    base=st.just("leaf"),
    extend=lambda children: st.builds(lambda c: "(" + c + ")", children),
    max_leaves=5,
)  # CORRECT

st.recursive(
    base=st.just("leaf"),
    extend=st.one_of(...),  # WRONG — extend must be callable, not a strategy
)  # WRONG
```

### `st.integers(min_value=int, max_value=int)`
```python
st.integers(min_value=0, max_value=100)  # CORRECT
```

## PREFERRED: Use @st.composite for XML construction

Using `@st.composite` is STRONGLY RECOMMENDED for building XML tag strategies. It is easier to understand and less error-prone than complex `st.builds()` chains.

**Correct @composite pattern for XML tags:**

```python
@st.composite
def _open_tag(draw):
    name = draw(_name_strategy())
    attrs = draw(_attr_strategy())
    if attrs:
        return "<" + name + " " + " ".join(attrs) + ">"
    return "<" + name + ">"

@st.composite
def _self_closing_tag(draw):
    name = draw(_name_strategy())
    attrs = draw(_attr_strategy())
    if attrs:
        return "<" + name + " " + " ".join(attrs) + "/>"
    return "<" + name + "/>"
```

**Key benefits:**
- Use `draw()` to sample from sub-strategies
- Build complex strings with normal Python string operations
- Less likely to have `st.builds()` first-arg mistakes
- Easier for small models to follow

## Rules for composing strategies

1. Use `st.one_of()` to combine sub-strategies with appropriate weights
2. Use `@st.composite` + `draw()` for complex XML construction
3. Use `st.sampled_from([...])` to pick from a fixed list of strings
4. Use `st.recursive()` for nested/recursive XML structures
5. Define ALL helper strategies as module-level variables or functions BEFORE `xml_strategy`

## Strategy composition

Majority should be malformed (70%+). Use `st.one_of()` to combine:
```python
xml_strategy = st.one_of(
    _element_strategy(),
    _attribute_edge_cases(),
    _content_edge_cases(),
    _malformed_tag_strategy(),
    _entity_edge_cases(),
    _comment_cdata_pis(),
    _control_char_strategy(),
)
```

## Crash vectors to cover

**Malformed tags (highest priority):**
- Mismatched: `<a><b></a></b>`, `<a><b><c></c></a>`
- Double close: `<a/></a></a>`, `<a></a></a>`
- Double slash: `<a//>`
- Two roots: `<a/><b/>`
- Interleaved: `<a><b></a><c></c></b>`
- Unterminated: `<a><b><c`, `<a attr="unclosed`
- Bare angle: `<`, `<<`

**Attribute edge cases:**
- Duplicate: `<a x="1" x="2"/>`
- Unterminated value: `attr="unclosed`
- Empty value: `attr=`
- Null bytes: `\x00` in values
- Very long: 1000+ char values

**Entity edge cases:**
- Invalid: `&foo;`, `&unknown;`
- Incomplete: `&`, `&amp`, `&;`
- Deep nesting: `&amp;amp;amp;`
- In attributes: `<a attr="&foo;"/>`

**Comment/CDATA/PI edge cases:**
- Unterminated: `<!-- unclosed`, `<![CDATA[unclosed`
- Nested: `<!-- <!-- -->`
- Bare markers: `]]>`, `<?`
- Invalid decl: `<?xml`, `<?xml version=`

**Control character injection:**
- `\x00` through `\x08`, `\x0B`, `\x0C`, `\x0E`-`\x1F`, `\x7F`
- Place in: element names, attribute values, text content, comments, CDATA

**Depth/size stress:**
- Deep nesting: 50+ levels
- Wide trees: 100+ siblings
- Very large: 2000+ byte inputs

**Encoding stress:**
- Invalid UTF-8 byte sequences
- BOM-prefixed strings

## Rules

1. Output ONLY valid Python source. No prose, no fences.
2. Import only `hypothesis.strategies`, `string`, `random`.
3. Define `xml_strategy` as a module-level assignment.
4. 70%+ of generated inputs must be malformed or edge-case.
5. No external libraries, no I/O operations.
6. Use `random.choice()` and `random.randint()` inside helper functions if needed.
7. Every helper must be complete and self-contained.
8. All helpers must be defined before `xml_strategy` references them.
9. NEVER pass a strategy object as the first argument to `st.builds()` — the first argument must always be a callable.
10. USE `@st.composite` + `draw()` for building XML tags; it is simpler and more reliable than complex `st.builds()` chains.