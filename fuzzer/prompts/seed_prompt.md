You are generating a Python `hypothesis` strategy that produces byte strings targeting
mxml (Mini-XML), a small C library. The ANTLR4 grammar below describes generic XML
structure — use it for shape (recursion, nesting, escaping mechanisms), not as strict
rules, because mxml's real accepted format differs from it in specific, verified ways.

GRAMMAR (ANTLR4, for structure reference only — do not try to run ANTLR, just read it):
{grammar}

VERIFIED CONSTRAINTS (from reading mxml's actual source at the pinned commit — not
guessed, not generic XML knowledge):

Must stay within these or mxml rejects the input outright:
- Entity references: ONLY `&amp;` `&lt;` `&gt;` `&quot;` `&apos;` are recognized names.
  Any other name (e.g. `&foo;`) is a parse error. Numeric refs `&#123;` and `&#x7B;` are
  always fine.
- No raw control characters below 0x20 in text or entity content, except `\t` `\n` `\r`.
- Text must be valid UTF-8, or the whole document may start with a UTF-16 BOM
  (`\xFE\xFF` big-endian or `\xFF\xFE` little-endian) — don't mix an encoding declaration
  claiming one thing with bytes that are actually something else unless you're
  deliberately testing that mismatch (see the deliberate-break section below).
- Comments (`<!-- ... -->`) and CDATA (`<![CDATA[ ... ]]>`) need their real terminators;
  don't truncate them in the well-formed majority of your output.

Need NO constraint (mxml is more permissive here than the ANTLR grammar, so don't
narrow this down — spend generation budget on it freely):
- Element/attribute names: mxml's scanner accepts things stricter XML would reject
  (e.g. names starting with digits or punctuation). Vary this freely.
- Attribute value quoting: both `attr="val"` and `attr=val` (unquoted) are accepted.
  Generate a healthy mix of both, not just quoted.

DELIBERATELY BREAK ON PURPOSE (this is the part a naive grammar-conformant generator
misses entirely, and it's the highest-value part of this strategy): a small, deliberate
fraction of your output (~15-20%) should violate the grammar's OWN structural rules,
specifically to hit named error-handling code in mxml that only runs when these exact
violations occur:
  1. Mismatched close tags — `<a><b></a></b>` shapes, not just `<a></b>` — vary how deep
     the mismatch is nested, since this hits mxml's close-tag matching logic.
  2. Duplicate attribute names on one element — `<a x="1" x="2"/>` — vary how many
     duplicates and whether they're adjacent or separated by other attributes.
  3. A second top-level root element after the first is already closed — `<a/><b/>` at
     the top level — this hits mxml's root-node enforcement.
Generate these as their own dedicated sub-strategy, not as random mutations of
well-formed output, so they reliably land exactly on these three structural violations
rather than accidentally producing something else invalid.

General requirements:
- Output ONLY a single Python file's contents. No markdown fences, no prose.
- Define a module-level Hypothesis strategy named `xml_strategy` that produces `str`.
- Use `st.recursive` or `@st.composite` for element/content recursion — do not flatten
  nesting into a fixed-depth unrolled generator. Aim for occasional nesting depth 10+.
- Separately cover: empty elements (`<a/>`), all five named entities plus numeric refs
  (decimal and hex) in attribute values and text, CDATA containing `]]`/`]>`-adjacent
  sequences (not actual nesting — XML doesn't nest CDATA), comments, processing
  instructions, and DTD-shaped `<!DOCTYPE ...>`/`<!ENTITY ...>` blocks (mxml stores these
  opaquely as DECLARATION nodes and never expands them — they're safe to include and
  worth including, since the opaque-scanning code itself is untested surface).
- Keep single documents under ~4KB by default (the harness has a 5s timeout).
- No comments in the code explaining what you're doing beyond brief docstrings —
  optimize for correctness, not exposition.

REFERENCE MATERIAL (the full source-verified grammar↔mxml comparison the constraints
above were distilled from — consult it if you need more detail than the summary gives,
e.g. exact node types, the canonical valid-document example, or additional source
line references):
{adaptations}
