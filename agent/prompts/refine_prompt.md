# Strategy Refinement Prompt — Crash-Focused

## Previous strategy code

{prev_strategy}

## Previous iteration results

{prev_summary}

## Existing crash signatures

{crash_sigs}

## Your task

Based on the information above, **rewrite the complete Python strategy module**
and improve the `xml_strategy` definition. Your **primary goal is to find crashes**, not to generate valid XML.

## Analysis guidelines

1. **If crashes were found:** Generate **variants** of the crashing patterns. Modify element names, attribute values, nesting depths, and content to explore nearby input space. Try to find **different crash signatures** (different crash types).

2. **If acceptance rate is low:** This is GOOD — it means your malformed inputs are working. Do NOT reduce malformed input proportion. Instead, diversify the types of malformed inputs.

3. **If acceptance rate is high and no crashes:** This means your strategy is too safe. Aggressively increase malformed input proportion to 80%+.

4. **If refinement error occurred:** Fix the specific error reported and continue crash-finding focus.

## Aggressive crash-targeting tactics

### Always include these crash vectors:

**Tag mismatch crashes:**
- `<a><b></a></b>` with varying depths
- `<a><b><c></a></b></c>` wrong close order
- `<a><b></a><c></c></b>` interleaved unclosed
- `<a><b/></a></a>` double close after self-close
- Nested mismatch: `<outer><inner></outer></inner>`

**Attribute parsing crashes:**
- Duplicate attributes: `<a x="1" x="2" x="3"/>`
- Unterminated attribute values: `<a attr="unclosed`
- Empty attribute syntax: `<a = "val"/>`, `<a attr=/>`
- Attribute values with embedded quotes: `<a attr="a\"b"/>`
- Very long attribute values: 1000+ chars
- Null bytes in attributes: `<a attr="\x00"/>`

**Entity reference crashes:**
- Invalid entities: `&foo;`, `&bar;`, `&unknown;`
- Incomplete entities: `&amp`, `&`, `&;`
- Deeply nested entities: `&amp;amp;amp;amp;`
- Entities in attribute values: `<a attr="&foo;"/>`
- Many invalid entities in one input

**Comment/CDATA/PI crashes:**
- Unterminated comments: `<!-- unclosed`
- Nested comments: `<!-- <!-- -->`
- CDATA with embedded `]]>`: `<![CDATA[a]]>b]]>`
- Bare `]]>` without CDATA start
- Malformed PIs: `<?`, `<?xml`, `<? `

**Control character crashes:**
- Null bytes: `\x00` in element names, attributes, content
- Form feed: `\x0C` (this is the one that triggered the known crash)
- All controls 0x00-0x1F except `\t`, `\n`, `\r`
- Control characters in attribute values
- Control characters in element names
- Control characters in entity names

**Nesting/depth crashes:**
- Deep nesting: 50+ levels
- Wide trees: 100+ siblings
- Deep + wide combined
- Unbalanced nesting: more opens than closes

**Encoding crashes:**
- Invalid UTF-8 byte sequences
- BOM in unexpected places
- Lone surrogates

**Size stress:**
- Very large single inputs (2000+ bytes)
- Many small inputs with edge cases
- inputs with many special characters

## Tactic Switch (CRITICAL — READ CAREFULLY)

### If previous iteration found ZERO crashes:

You MUST shift to an **extremely aggressive** crash-finding posture:
- Set malformed input proportion to **80-90%**
- Focus on inputs that combine MULTIPLE edge cases at once (e.g., null bytes inside unterminated attribute values inside mismatched tags)
- Generate inputs that test parser recovery paths
- Try inputs that might cause infinite loops or stack overflows

### If previous iteration found crashes but no NEW signatures:

Focus on **diversifying** — try completely different crash patterns:
- If you found memory leaks, try buffer overflows
- If you found parse errors, try encoding issues
- If you found tag mismatches, try attribute edge cases
- Combine multiple edge cases in single inputs

### If previous iteration found new crashes:

Generate **nearby variants** of the new crash patterns to see if similar bugs exist.

## Output format — IMPORTANT

Output **ONLY** the complete Python source file. Do **NOT** wrap the code in
markdown fences (no triple backticks) and do not include any prose. The module
must:

1. Contain all required `import` statements
2. Define all sub-strategy helper functions (private, names starting with `_`)
3. Define a plain **module-level assignment** `xml_strategy = <SearchStrategy>`

`xml_strategy` MUST be a module-level assignment. Do not define it as a
function, do not nest it inside a function, and do not return it.

## Rules

1. Only valid Python code — no markdown code fences, no prose.
2. Import only `hypothesis.strategies`, `string`, `random`.
3. Ensure `xml_strategy` is a module-level variable, initialized with a plain
   assignment — never defined inside a function and returned.
4. No I/O, file operations, or system calls.
5. The strategy must produce `str` XML text.
6. **Malformed inputs must be the majority (70%+).**

## CRITICAL: No Placeholders

- You MUST define every function and variable you use.
- Do NOT use placeholders like `_NAME`, `SOME_VAR`, or `...`.
- If you define a helper function, you MUST define it **before** `xml_strategy` uses it.

## Recursion rule (critical)

For `st.recursive(base=..., extend=..., ...)`, the `extend` argument must be a
**callable** `lambda children: <strategy>`. It receives a strategy object for
recursive/nested children and must return a strategy. Never pass a strategy
object directly as `extend`, and never call a strategy object as a function —
Hypothesis raises `TypeError: 'LazyStrategy' object is not callable`.

**Correct:**
```python
xml_strategy = st.recursive(
    base=...,
    extend=lambda children: st.one_of(children, ...),
)
```

**Incorrect (will fail):**
```python
xml_strategy = st.recursive(
    base=...,
    extend=st.one_of(children, ...),  # WRONG
)
```
