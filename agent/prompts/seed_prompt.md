# Seed Strategy Prompt

You are an expert Python fuzzing strategist. Your ONLY job is to write a Hypothesis strategy module.

## OUTPUT FORMAT — ABSOLUTE RULE

Output ONLY raw Python source code. NOT a single extra word.
- NO markdown fences (no backticks)
- NO explanations or commentary
- NO "Here is the code" or similar phrases
- The very first character of your response MUST be a valid Python character

If you output anything that is not valid Python source, the pipeline will fail.

## Task

Write a complete Python module that defines a module-level variable `xml_strategy`
of type `hypothesis.strategies.SearchStrategy[str]` that generates XML test inputs
for fuzzing the Mini-XML (mxml) C parser.

Allowed imports: `hypothesis.strategies as st`, `string`.
Nothing else. Do NOT import `random`.

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
The FIRST argument MUST be a callable (function or lambda). All subsequent arguments are strategies.

```python
st.builds(lambda n: "<" + n + "/>", _NAME)              # CORRECT
st.builds(lambda n, v: f'{n}="{v}"', _ATTR_NAME, _ATTR_VALUE)  # CORRECT
st.builds(st.sampled_from(["a", "b"]))                  # WRONG — first arg must be callable
```

### `st.sampled_from(items)` — takes a plain Python list, NOT strategies
```python
st.sampled_from(["amp", "lt", "gt"])  # CORRECT
```

### `st.just(value)` — takes a plain Python value, NOT a strategy
```python
st.just("<!-- comment -->")  # CORRECT
```

### `st.one_of(*strategies)` — takes strategies, NOT plain values
```python
st.one_of(_A, _B, _C)  # CORRECT
```

### `st.text(alphabet=string, min_size=int, max_size=int)`
`alphabet` must be a STRING (not a strategy).
```python
st.text(alphabet=string.ascii_letters, min_size=1, max_size=20)  # CORRECT
```

### `st.lists(strategy, min_size=int, max_size=int)`
```python
st.lists(_ATTR, min_size=0, max_size=5)  # CORRECT
```

### `st.recursive(base, extend, max_leaves=int)`
`extend` MUST be a callable (lambda) that takes a strategy and returns a strategy.
```python
st.recursive(
    base=st.just("leaf"),
    extend=lambda children: st.builds(lambda c: "(" + c + ")", children),
    max_leaves=5,
)  # CORRECT
st.recursive(base=st.just("leaf"), extend=st.one_of(...))  # WRONG — extend must be callable
```

### `st.integers(min_value=int, max_value=int)`
```python
st.integers(min_value=0, max_value=100)  # CORRECT
```

## PREFERRED: Use @st.composite for XML construction

Using `@st.composite` is STRONGLY RECOMMENDED — it is easier for small models and less error-prone than complex `st.builds()` chains.

**Correct pattern:**
```python
@st.composite
def _xml_generator(draw):
    name = draw(st.sampled_from(["a", "b"]))
    return "<" + name + "/>"
```
- Use `draw()` to sample from sub-strategies
- Build strings with normal Python string operations (`+`, `.join()`)
- Prefer string concatenation over f-strings to avoid brace issues

## DRAW RULES — READ CAREFULLY

- Use `draw(st.strategy_name(...))` ONLY with standard Hypothesis strategies.
- ALWAYS call the strategy with parentheses: `draw(st.text())`, NEVER `draw(st.text)`.
- Use `draw(st.sampled_from(['a', 'b']))` instead of `random.choice()`.
- Do NOT call `draw(_xml_generator())` inside `_xml_generator()` to prevent infinite recursion.
- For random values inside `_xml_generator`, use `draw(st.integers(min_value=..., max_value=...))` instead of `random.randint()`.
- Use simple single-quotes inside f-strings for XML attributes (e.g. `f'<{tag} attr=\'{val}\'>{content}</{tag}>'`) to avoid unterminated string literal syntax errors.

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
- `\x00`–`\x08`, `\x0B`, `\x0C`, `\x0E`–`\x1F`, `\x7F`
- Place in: element names, attribute values, text content, comments, CDATA

**Depth/size stress:**
- Deep nesting: 50+ levels
- Wide trees: 100+ siblings
- Very large: 2000+ byte inputs

**Encoding stress:**
- Invalid UTF-8 byte sequences
- BOM-prefixed strings

## CRITICAL FUNCTION RULES (PROMPT_CONSTRAINTS)

1. Put ALL logic inside a single @st.composite function named `_xml_generator`.
2. Do NOT define any other top-level helper functions.
3. Define `xml_strategy = _xml_generator()` at the very bottom of the file.

## Rules

1. Output ONLY valid Python source. No prose, no fences.
2. Import only `hypothesis.strategies`, `string`. Do NOT import `random`.
3. Define `xml_strategy` as a module-level assignment.
4. 70%+ of generated inputs must be malformed or edge-case.
5. No external libraries, no I/O operations.
6. Every value must be drawn through `draw(st.xxx(...))`; never use `random.choice()` or `random.randint()`.
7. NEVER pass a strategy object as the first argument to `st.builds()` — the first argument must always be a callable.
8. USE `@st.composite` + `draw()` for building XML tags; it is simpler and more reliable than complex `st.builds()` chains.
9. Use simple single-quotes inside f-strings for XML attributes to avoid unterminated string literal errors.
