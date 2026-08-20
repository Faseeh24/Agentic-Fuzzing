# Seed Strategy Prompt — Aggressive Crash-Finding for mxml

You are an expert security fuzzing strategist. Your goal is to find **crashes, memory corruption, and undefined behavior** in the Mini-XML (mxml) C library by generating inputs that trigger ASan/UBSan violations.

## Task

Write a **complete Python module** that defines a module-level variable
`xml_strategy`. Its value must be a `hypothesis.strategies.SearchStrategy[str]`
used to generate XML test inputs.

## Primary Objective

**Find crashes.** The strategy should generate inputs that stress mxml's parser aggressively. Valid XML is secondary — focus on edge cases, malformed inputs, and boundary conditions that might trigger:
- Use-after-free
- Buffer overflows
- Null pointer dereferences
- Heap buffer overreads
- Integer overflows in size calculations
- Stack overflows from deep nesting

## Target library facts

mxml is a lightweight XML parsing library. Key characteristics:
- Accepts only 5 entity names: `amp`, `lt`, `gt`, `quot`, `apos`
- Rejects raw control characters (0x00-0x1F except `\t`, `\n`, `\r`)
- Requires valid UTF-8 or UTF-16 encoding (BOM-detected)
- Requires exactly one root element
- Accepts comments, CDATA, processing instructions, and DTD blocks
- Parses entity references in attribute values and text content
- Handles self-closing tags, nested elements, and mixed content

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

## CRITICAL: No Placeholders

- You MUST define every function and variable you use.
- Do NOT use placeholders like `_NAME`, `SOME_VAR`, or `...`.
- If you define a helper function (e.g., `_entity_strategy`), you MUST define it **before** `xml_strategy` uses it.

## Strategy design: Maximize crash surface

Your strategy must generate a **heavy mix of crash-inducing inputs**. Use `st.one_of()` to combine multiple sub-strategies, where the majority generate malformed or edge-case inputs.

### 1. Element name strategies

Generate varied element names including:
- Normal names: letters, digits, `_`, `:`, `-`
- Names starting with digits: `1abc`
- Empty-ish names: single character names
- Long names: up to 100 chars
- Names with special chars: `a:b-c_d`

### 2. Attribute strategies

Generate attributes with edge cases:
- Duplicate attribute names on same element
- Empty attribute values: `attr=""`
- Very long attribute values: 500+ chars
- Attribute values with special chars: `"` inside double-quoted values
- Attribute values with control characters (0x00-0x1F)
- Attribute values with unescaped entities

### 3. Content strategies

Generate text content with:
- Raw control characters (0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F)
- Null bytes embedded as text
- Very long text content (500+ chars)
- Mixed text and nested elements

### 4. Malformed XML strategies (CRASH TARGETS)

These are the most important — they target parser bugs:

**Mismatched/malformed tags:**
- `<a><b></a></b>` — mismatched open/close
- `<a><b><c></c></a>` — wrong nesting order
- `<a><b></b></a><c></c>` — two root elements
- `<a><b></a>` — unclosed inner, wrong close

**Self-closing edge cases:**
- `<a/>` followed by `</a>` — double close
- `<a//>` — double slash
- `<a /><b />` — multiple self-closing as roots
- `<a></a></a>` — extra close tag

**Attribute edge cases:**
- `<a x="1" x="2"/>` — duplicate attributes
- `<a ""/>` — empty attribute name
- `<a = "val"/>` — missing attribute name
- `<a attr="unterminated` — unterminated attribute value
- `<a attr=/>` — empty attribute value syntax

**Entity reference edge cases:**
- `<root>&unknown;</root>` — invalid entity
- `<root>&amp;</root>` — valid entity (should work)
- `<root>&</root>` — dangling ampersand
- `<root>&amp</root>` — incomplete entity
- `<root>@@;</root>` — garbage entity-like text

**Comment edge cases:**
- `<!-- comment -->` — valid comment
- `<!-- unclosed comment` — unterminated comment
- `<!-- comment -->extra` — comment followed by garbage
- `<<!-- comment -->` — double angle bracket
- `<!-- comment --></root>` — comment outside root

**CDATA edge cases:**
- `<![CDATA[data]]>` — valid CDATA
- `<![CDATA[unclosed` — unterminated CDATA
- `<![CDATA[data]]]>extra` — CDATA followed by more
- `]]>` — bare CDATA end marker
- `<![CDATA[]]>` — empty CDATA

**Processing instruction edge cases:**
- `<?xml version="1.0"?>` — valid PI
- `<?` — bare PI start
- `<?xml` — unterminated PI
- `<?xml?>` — empty PI

**Declaration edge cases:**
- `<?xml version="1.0" encoding="utf-8"?>` — valid decl
- `<` — bare angle bracket
- `<<root></root>>` — double angle brackets
- `<root>text</root>extra` — extra text after root
- `<root>text</root><root2>text2</root2>` — two roots

**Depth/size edge cases:**
- Deep nesting: 50+ levels of `<a><a><a>...</a></a></a>`
- Very wide: many sibling elements
- Very large attribute values: 1000+ chars
- Very large text content: 1000+ chars
- Mixed: deep nesting + large content

### 5. Control character injection

Generate strings containing raw control characters that mxml should reject but might mishandle:
- `\x00` (null)
- `\x01` - `\x08` (controls)
- `\x0B` (vertical tab)
- `\x0C` (form feed)
- `\x0E` - `\x1F` (controls)
- `\x7F` (delete)

These should be placed in:
- Element names
- Attribute values
- Text content
- Comment content
- CDATA content

### 6. Encoding edge cases

- BOM-prefixed strings: `﻿<root/>`
- Invalid UTF-8 sequences (high bytes without valid continuation)
- Lone surrogate halves

## Recursion rule (critical)

For `st.recursive(base=..., extend=..., ...)`, the `extend` argument must be a
**callable** `lambda children: <strategy>`. It receives a strategy object for
recursive/nested children and must return a strategy. Never pass a strategy
object directly as `extend`, and never call a strategy object as a function —
Hypothesis will raise `TypeError: 'LazyStrategy' object is not callable`.

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
    extend=st.one_of(children, ...),  # WRONG: 'extend' must be a lambda
)
```

## Constraints

- Maximum nesting depth: 30 (go deep to test stack handling)
- Maximum input size: 2048 bytes (larger to test buffer handling)
- Include control characters — they are the primary crash vector
- Entity names: mix valid (`amp`, `lt`, `gt`, `quot`, `apos`) with invalid
- Attribute values: mix well-formed with unterminated and malformed

## Strategy composition

Use `st.one_of()` to combine sub-strategies with appropriate weights. A good starting point:

```python
xml_strategy = st.one_of(
    _element_strategy(),       # ~20%
    _attribute_edge_cases(),   # ~20%
    _content_edge_cases(),     # ~15%
    _malformed_tag_strategy(), # ~20%
    _entity_edge_cases(),      # ~10%
    _comment_cdata_pis(),      # ~10%
    _control_char_strategy(),  # ~5%
)
```

## Rules

1. Output a complete Python module that defines a module-level `xml_strategy`.
2. Import only `hypothesis.strategies`, `string`, `random`.
3. The strategy must produce strings (XML text).
4. **70%+ of generated inputs should be malformed or edge-case.** Valid XML is a minority.
5. No external libraries and no I/O operations.
6. `xml_strategy` must be a module-level variable, initialized with a plain
   assignment — never defined inside a function and returned.
7. Every helper function you define must be complete and self-contained.
8. Use `random.choice()` and `random.randint()` inside helper functions if needed.