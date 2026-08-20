# Strategy Refinement Prompt

You are an expert Python fuzzing strategist. Your ONLY job is to write a Hypothesis strategy module.

## OUTPUT FORMAT — ABSOLUTE RULE

Output ONLY raw Python source code. NOT a single extra word.
- NO markdown fences (no backticks)
- NO explanations
- NO commentary
- NO "Here is the code" or similar phrases
- The very first character of your response MUST be `i`, `d`, `f`, `x`, `#`, or whitespace

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
- Embedded quotes in values
- Very long: 1000+ chars
- Null bytes: `<a attr="\x00"/>`

### Entity reference crashes
- Invalid: `&foo;`, `&bar;`
- Incomplete: `&amp`, `&`, `&;`
- Deep nesting: `&amp;amp;amp;amp;`
- In attributes: `<a attr="&foo;"/>`
- Many invalid entities in one input

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
- Controls in attribute values, element names, entity names

### Nesting/depth crashes
- Deep: 50+ levels
- Wide: 100+ siblings
- Unbalanced: more opens than closes

### Size stress
- Very large single inputs: 2000+ bytes
- Many small inputs with edge cases

## Tactic Switch (CRITICAL)

### If previous iteration found ZERO crashes:
Set malformed proportion to 80-90%. Focus on inputs that combine MULTIPLE edge cases at once (e.g., null bytes inside unterminated attribute values inside mismatched tags). Try inputs that might cause infinite loops or stack overflows.

### If previous iteration found crashes but no NEW signatures:
Diversify — try completely different crash patterns. If you found memory leaks, try buffer overflows. If you found parse errors, try encoding issues.

### If previous iteration found new crashes:
Generate nearby variants of the new crash patterns to find similar bugs.

## CRITICAL Hypothesis API rules (Kaggle-compatible, works in hypothesis >=6.0)

1. **`st.recursive` extend must be a callable lambda:**
   `st.recursive(base=..., extend=lambda children: st.one_of(children, ...), max_leaves=20)`
   NEVER pass a strategy object directly as `extend`.

2. **`st.dictionaries` uses `keys=` and `values=`, NOT `key_type=` / `value_type=`:**
   `st.dictionaries(keys=st.text(min_size=1), values=st.integers())`

3. **Never pass a strategy object where a plain Python value is expected:**
   `alphabet=` must be a string. `min_size=` / `max_size=` must be ints.

4. **F-strings: double literal braces:**
   Prefer string concatenation (`+`) over f-strings for building XML.
   If using f-strings, `{{` and `}}` produce literal `{` and `}`.

5. **Only use these Hypothesis APIs (all available since hypothesis 6.0):**
   `st.text`, `st.integers`, `st.sampled_from`, `st.just`, `st.one_of`,
   `st.builds`, `st.lists`, `st.recursive`, `st.dictionaries`,
   `st.fixed_dictionaries`, `st.binary`, `st.booleans`, `st.none`,
   `string` module, `random` module.

## Output format

The module must:
1. Contain all required `import` statements
2. Define all sub-strategy helper functions (private, names starting with `_`)
3. Define a plain module-level assignment: `xml_strategy = <SearchStrategy>`

`xml_strategy` MUST be a module-level assignment. Do not define it as a function, nest it inside a function, or return it.

## Rules

1. Only valid Python code — no markdown fences, no prose.
2. Import only `hypothesis.strategies`, `string`, `random`.
3. `xml_strategy` must be a module-level variable initialized with a plain assignment.
4. No I/O, file operations, or system calls.
5. The strategy must produce `str` XML text.
6. Malformed inputs must be the majority (70%+).
7. Every helper function you define must be complete and self-contained.
8. Use `random.choice()` and `random.randint()` inside helper functions if needed.
