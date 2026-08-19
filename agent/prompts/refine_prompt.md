# Strategy Refinement Prompt

## Previous strategy code

{prev_strategy}

## Previous iteration results

{prev_summary}

## Existing crash signatures

{crash_sigs}

## Your task

Based on the information above, **rewrite the complete Python strategy module**
and improve the `xml_strategy` definition. Consider:

- If the acceptance rate is low, adjust the constraints (depth, size limits)
- If deliberately malformed inputs did not produce crashes, increase their
  proportion
- If crashes were found, generate nearby variant inputs
- Keep a balanced mix of valid and malformed tests

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

## Recursion rule (critical)

For `st.recursive(base=..., extend=..., ...)`, the `extend` argument must be a
**callable** `lambda children: <strategy>`. It receives a strategy object for
recursive/nested children and must return a new strategy. Never pass a strategy
object directly as `extend`, and never call a strategy object as a function —
Hypothesis raises `TypeError: 'LazyStrategy' object is not callable`.
