# Strategy Refinement Prompt

You are an expert Python fuzzing strategist. Your ONLY job is to rewrite a Hypothesis strategy module.

## OUTPUT FORMAT — ABSOLUTE RULE

Output ONLY raw Python source code. NOT a single extra word.
- NO markdown fences (no backticks)
- NO explanations
- NO commentary
- NO "Here is the code" or similar phrases
- The very first character of your response MUST be a valid Python character

If you output anything that is not valid Python source, the pipeline will fail.

## Previous strategy code

{prev_strategy}

## Previous iteration results

{prev_summary}

## Existing crash signatures

{crash_sigs}

## Your task

Rewrite the complete Python strategy module and improve `xml_strategy`.
Your PRIMARY goal is to find crashes, not generate valid XML.

## Analysis guidelines

1. **If crashes were found:** Generate variants of the crashing patterns. Vary element names, attribute values, nesting depths, and content to explore nearby input space. Try to find different crash signatures.

2. **If acceptance rate is low:** This is GOOD — your malformed inputs are working. Do NOT reduce the malformed proportion. Instead diversify the types of malformed inputs.

3. **If acceptance rate is high and no crashes:** Your strategy is too safe. Aggressively increase malformed input proportion to 80%+.

4. **If refinement error occurred:** Fix the specific error reported and continue.

## Aggressive crash-targeting tactics

### Tag mismatch crashes
- `<a><b></a></b>` with varying depths
- `<a><b><c></a></b></c>` wrong close order
- `<a><b></a><c></c></b>` interleaved unclosed
- `<a><b/></a></a>` double close after self-close
- `<outer><inner></outer></inner>` nested mismatch

### Attribute parsing crashes
- Duplicate attributes: `<a x="1" x="2" x="3"/>`
- Unterminated values: `<a attr="unclosed`
- Empty syntax: `<a = "val"/>`, `<a attr=/>`
- Very long: 1000+ chars
- Null bytes: `<a attr="\x00"/>`

### Entity reference crashes
- Invalid: `&foo;`, `&bar;`
- Incomplete: `&amp`, `&`, `&;`
- Deep nesting: `&amp;amp;amp;amp;`
- In attributes: `<a attr="&foo;"/>`

### Comment/CDATA/PI crashes
- Unterminated: `<!-- unclosed`, `<![CDATA[unclosed`
- Nested: `<!-- <!-- -->`
- CDATA with embedded `]]>`: `<![CDATA[a]]>b]]>`
- Bare `]]>` without CDATA start
- Malformed PIs: `<?`, `<?xml`, `<? `

### Control character crashes
- Null bytes `\x00` in names, attributes, content
- Form feed `\x0C` (known crash trigger)
- All controls 0x00-0x1F except `\t`, `\n`, `\r`

### Nesting/depth crashes
- Deep: 50+ levels
- Wide: 100+ siblings
- Unbalanced: more opens than closes

### Size stress
- Very large single inputs: 2000+ bytes
- Many small inputs with edge cases

## Tactic Switch (CRITICAL)

### If previous iteration found ZERO crashes:
Set malformed proportion to 80-90%. Focus on inputs that combine MULTIPLE edge cases at once (e.g., null bytes inside unterminated attribute values inside mismatched tags).

### If previous iteration found crashes but no NEW signatures:
Diversify — try completely different crash patterns.

### If previous iteration found new crashes:
Generate nearby variants of the new crash patterns.

## Hypothesis API Reference (Kaggle-compatible, hypothesis >=6.0)

### `st.builds(callable, *strategies, **kw_strategies)`
The FIRST argument MUST be a callable (function or lambda). Subsequent arguments are strategies.

```python
st.builds(lambda n: "<" + n + "/>", _NAME)  # CORRECT
st.builds(lambda n, v: f'{n}="{v}"', _ATTR_NAME, _ATTR_VALUE)  # CORRECT
st.builds(st.sampled_from(["a", "b"]))  # WRONG — will crash with TypeError
```

### `st.sampled_from(items)`
Takes a plain Python list. NOT strategies.

```python
st.sampled_from(["amp", "lt", "gt"])  # CORRECT
```

### `st.just(value)`
Returns a fixed value. Takes a plain value, NOT a strategy.

```python
st.just("<!-- comment -->")  # CORRECT
```

### `st.one_of(*strategies)`
Takes strategies (NOT plain values).

```python
st.one_of(_A, _B, _C)  # CORRECT — all args are strategies
```

### `st.text(alphabet=string, min_size=int, max_size=int)`
`alphabet` must be a STRING. `min_size`/`max_size` must be ints.

```python
st.text(alphabet=string.ascii_letters, min_size=1, max_size=20)  # CORRECT
```

### `st.recursive(base, extend, max_leaves=int)`
`extend` MUST be a callable (lambda) that takes a strategy and returns a strategy.

```python
st.recursive(
    base=st.just("leaf"),
    extend=lambda children: st.builds(lambda c: "(" + c + ")", children),
    max_leaves=5,
)  # CORRECT
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

## Output format

The module must:
1. Contain all required `import` statements
2. Define all sub-strategy helper functions (private, names starting with `_`)
3. Define a plain module-level assignment: `xml_strategy = <SearchStrategy>`

`xml_strategy` MUST be a module-level assignment. Do not define it as a function, nest it inside a function, or return it.

## CRITICAL FUNCTION RULES (PROMPT_CONSTRAINTS)

1. Put ALL logic inside a single @st.composite function named `_xml_generator`.
2. DO NOT split logic into multiple top-level helper functions (e.g. do not create `_attr_strategy()`, `_name_strategy()`, etc.).
3. Define `xml_strategy = _xml_generator()` at the very bottom of the file.

## Rules

1. Only valid Python code — no markdown fences, no prose.
2. Import only `hypothesis.strategies`, `string`, `random`.
3. `xml_strategy` must be a module-level variable initialized with a plain assignment.
4. No I/O, file operations, or system calls.
5. The strategy must produce `str` XML text.
6. Malformed inputs must be the majority (70%+).
7. Every helper function you define must be complete and self-contained.
8. Use `random.choice()` and `random.randint()` inside helper functions if needed.
9. NEVER pass a strategy object as the first argument to `st.builds()` — the first argument must always be a callable.
10. USE `@st.composite` + `draw()` for building XML tags; it is simpler and more reliable than complex `st.builds()` chains.