# Seed Strategy Prompt — Python Hypothesis Strategy Generation

You are a professional fuzzing strategy planner. Your goal is to generate a
high-quality Hypothesis test strategy for the Mini-XML (mxml) C library.

## Task

Write a **complete Python module** that defines a module-level variable
`xml_strategy`. Its value must be a `hypothesis.strategies.SearchStrategy[str]`
used to generate XML test inputs.

## Target library facts

mxml is a lightweight XML parsing library. Key characteristics:
- Accepts only 5 entity names: `amp`, `lt`, `gt`, `quot`, `apos`
- Rejects raw control characters (0x00-0x1F except `\t`, `\n`, `\r`)
- Requires valid UTF-8 or UTF-16 encoding (BOM-detected)
- Requires exactly one root element
- Accepts comments, CDATA, processing instructions, and DTD blocks

## Output format — IMPORTANT

- Output **ONLY** the complete Python source file.
- Do **NOT** wrap the code in markdown fences (no triple backticks) and do not
  include any prose, explanations, or comments outside the code.
- The module must define a plain **module-level assignment**:

      xml_strategy = <a Hypothesis SearchStrategy>

  `xml_strategy` MUST be a module-level assignment. Do not define it as a
  function, do not nest it inside a function, and do not return it.

The module should look like this (structure only):

```python
import hypothesis.strategies as st
import string
import random

# --- sub-strategy helpers ---

def _safe_text_strategy():
    ...

def _element_name_strategy():
    ...

# ... more private helpers (names beginning with underscore) ...

# --- main strategy: a plain module-level assignment ---
# IMPORTANT: st.recursive(base=..., extend=..., ...) requires `extend` to be a
# CALLABLE `lambda children: <strategy>`. It receives a strategy (for nested
# children) and MUST return a strategy. Passing a strategy object directly as
# `extend` raises:
#   TypeError: 'LazyStrategy' object is not callable
xml_strategy = st.recursive(
    base=st.text(alphabet=string.ascii_letters, min_size=1, max_size=50),
    extend=lambda children: st.one_of(
        children,
        st.text(alphabet=string.ascii_letters, min_size=1, max_size=50),
    ),
    max_leaves=20,
)
```

## Strategy design guidelines

Use `st.recursive` and/or `@st.composite` to build a recursive XML syntax:

- **Element names**: letters, digits, `_`, `:`, `-`
- **Attributes**: names and values; values may contain entity references
- **Content**: text, nested elements, or mixed content
- **Tag styles**: self-closing (`<a/>`), empty (`<a></a>`), with content (`<a>...</a>`)
- **Special structures**: CDATA, comments, processing instructions, XML declaration

### Recursion rule (critical)

For `st.recursive(base=..., extend=..., ...)`, the `extend` argument must be a
**callable** `lambda children: <strategy>`. It receives a strategy object for
recursive/nested children and must return a new strategy. Never pass a strategy
object directly as `extend`, and never call a strategy object as a function —
Hypothesis will raise `TypeError: 'LazyStrategy' object is not callable`.

## Intentional breakage (high-value testing)

Generate both **well-formed XML** and **deliberately malformed XML**; the latter
exercises mxml's error-handling paths:

1. Mismatched tags: `<a><b></a></b>`
2. Duplicate attribute names: `<a x="1" x="2"/>`
3. Second root node: `<a/><b/>`
4. Invalid entity: `<root>&foo;</root>`
5. Unclosed comment: `<!-- unclosed comment`
6. Unclosed CDATA: `<![CDATA[unclosed cdata`

Malformed inputs should be roughly 15-20% of the generated examples.

## Constraints

- Maximum nesting depth: 10
- Maximum input size: 1024 bytes
- No control characters (except `\t`, `\n`, `\r`)
- Only entities: `amp`, `lt`, `gt`, `quot`, `apos`

## Rules

1. Output a complete Python module that defines a module-level `xml_strategy`.
2. Import only `hypothesis.strategies`, `string`, `random`.
3. The strategy must produce strings (XML text).
4. Mix valid and deliberately malformed XML inputs.
5. No external libraries and no I/O operations.
6. `xml_strategy` must be a module-level variable, initialized with a plain
   assignment — never defined inside a function and returned.
