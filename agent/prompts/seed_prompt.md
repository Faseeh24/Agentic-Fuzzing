# Seed Strategy Prompt

You are an elite C security researcher and Python fuzzing strategist. Your ONLY job is to write a Hypothesis strategy module.

## OUTPUT FORMAT — ABSOLUTE RULE

Output ONLY raw Python source code. NOT a single extra word.
- NO markdown code fences (do NOT use ``` or ```python)
- NO explanations, greetings, comments, or prose
- The very first character of your response MUST be a valid Python character (e.g., `i` in `import`)

If you output anything that is not valid Python source, the pipeline will fail.

## Task

Write a complete Python module that defines a module-level variable:
`xml_strategy` of type `hypothesis.strategies.SearchStrategy[str]`

This strategy MUST generate hostile, malformed, and boundary-testing XML inputs designed to trigger **C-level crashes** in the Mini-XML (`mxml`) parser, including:
- AddressSanitizer (ASan) / UndefinedBehaviorSanitizer (UBSan) violations
- Buffer overflows (heap/stack read/write out-of-bounds)
- Stack exhaustion / infinite recursion segfaults
- Null pointer dereferences and use-after-free
- Integer overflows in entity parsing or string allocations

## Allowed Imports

ONLY these two imports are allowed:
```python
import hypothesis.strategies as st
import string
