You are generating a Python `hypothesis` strategy that produces byte strings in the
language of the following ANTLR4 grammar for XML, adapted for a specific C library
(mxml) whose real accepted format differs from strict XML in documented ways.

GRAMMAR (ANTLR4, for structure reference only — do not try to run ANTLR, just read it):
{grammar}

DOCUMENTED ADAPTATIONS (the target library's real behavior vs this grammar):
{adaptations}

Requirements:
- Output ONLY a single Python file's contents. No markdown fences, no prose.
- Define a module-level Hypothesis strategy named `xml_strategy` that produces `str`.
- Use `st.recursive` or `@st.composite` for the element/content recursion — do not
  flatten nesting into a fixed-depth unrolled generator.
- Explicitly and separately cover: empty elements (`<a/>`), deep nesting (aim for
  occasional depth 10+), duplicate attribute names on one element, attribute values
  containing all five predefined entities and at least one numeric char ref
  (decimal and hex), unicode element/attribute names near the XML NameStartChar
  boundary, CDATA sections (including ones containing literal `]]>`-adjacent
  sequences like `]]` or `]>`), comments, processing instructions, and a minority
  (~15%) of near-valid-but-malformed documents (unclosed tags, mismatched close
  tags, unterminated CDATA/comments, unquoted or mismatched-quote attribute
  values, unknown entity names).
- Bias the default weighting toward inputs that are LIKELY to be accepted by a
  real XML-ish parser (most well-formed, a controlled minority malformed) — a
  generator that's mostly rejected doesn't exercise interesting code paths.
- Keep single documents under ~4KB by default (the harness has a 5s timeout).
- No comments in the code explaining what you're doing beyond brief docstrings —
  optimize for correctness, not exposition.
  