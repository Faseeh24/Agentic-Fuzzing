# Strategy Refinement Prompt

You are an elite C security researcher and vulnerability researcher. Your ONLY job is to **refine and mutate an existing Hypothesis strategy module** (`{prev_strategy}`) based on execution feedback to discover new C-level crashes in `mxml`.

---

## PREVIOUS ITERATION CONTEXT (read this first)

### 1. Previous Strategy Code
{prev_strategy}

---

### 2. Previous Run Summary & Execution Feedback
{prev_summary}

---

### 3. Discovered Crash Signatures
{crash_sigs}

---

## CRITICAL RULE: THIS IS APPEND-ONLY REFINEMENT, NOT A REWRITE

Your output MUST be `{prev_strategy}` with additions and targeted parameter changes —
never a smaller or restructured replacement.

- **Every named sub-strategy that exists in `{prev_strategy}` MUST still exist in your
  output**, under the same name, still included in the final `xml_strategy` definition.
  Do not delete a branch, rename it, or fold it into something else, even if you think
  it's redundant — you don't have enough information from one run to know that, and
  removing it can silently throw away the exact branch that produced a crash.
- You may only: (a) add new sub-strategies as new branches, (b) adjust `min_size`/
  `max_size`/`max_leaves`/character sets *within* an existing sub-strategy's definition,
  or (c) add the sub-strategy again as an additional entry in the final `st.one_of(...)`
  list to increase how often it gets sampled (see "Boosting known crash producers" below).
- If `{prev_summary}` shows 0 crashes this round, that is informative about *this specific
  strategy version* — it is not license to discard everything and start over. Keep
  building on what's there.

---

## BOOSTING KNOWN CRASH PRODUCERS

Hypothesis's `st.one_of(...)` does not sample its branches with explicit weights, but you
can bias sampling frequency by **listing a productive branch more than once** in the final
`st.one_of(...)` call. If section 3 above shows crashes came from, say, the mismatched-tag
or duplicate-attribute branch, include that branch 2–3 times in the final `st.one_of(...)`
list (it's the same strategy object referenced multiple times — this is a legitimate,
common Hypothesis pattern, not a hack) so roughly 2–3x more of your generation budget goes
toward that shape without touching its internals.

---

## SIZE GUARDRAILS — DO NOT LET GENERATION RUNTIME BLOW UP

The harness enforces a 5-second-per-input timeout, and you have a fixed budget of examples
per run (typically 100–500). Extremely large payloads (hundreds of KB) mostly get rejected
by mxml's UTF-8/control-character validation on the very first bad byte — they cost a lot
of generation and serialization time for very little marginal chance of reaching new code.

- Cap any single generated document at **8KB by default**. Do not scale a working
  strategy's `max_size` past roughly 8–16KB unless section 2 above specifically shows
  large inputs are the ones surviving to be accepted (`valid`/`invalid` split, not just
  outright rejected) — if most large inputs are being rejected instantly, bigger isn't
  the lever to pull.
- If section 2 shows a run taking unusually long relative to its example count
  (e.g. minutes instead of seconds for 100 examples), that's a signal your generator has
  drifted toward oversized payloads — shrink `min_size`/`max_size` back down rather than
  escalating further.

---

## REFINEMENT PRIORITY ORDER (apply the first one that matches)

### 1. Execution/validation fix (if section 2 shows the previous output was rejected)
- Remove any disallowed statement entirely — replace it with nothing, don't replace it
  with a different variant of the same mistake.
- Confirm `xml_strategy = ...` exists at true module top level (not inside a function or
  `if __name__`).
- Confirm every `st.recursive(...)` call uses `extend=lambda children: ...` correctly and
  every `st.builds(...)` lambda's argument count matches the strategies passed to it.
- Otherwise, the rest of `{prev_strategy}` should be unchanged from before the failed
  attempt — a validation failure means the format was wrong, not that the strategy design
  was wrong.

### 2. Crash-proximity mutation (if section 3 above is non-empty)
This is your highest-value action when there ARE crashes to build on — prioritize it over
adding unrelated new vectors:
- Identify which named branch(es) in `{prev_strategy}` most plausibly produced each crash
  listed in section 3 (match by structural shape: mismatched tags, duplicate attributes,
  entity content, CDATA/comment boundaries, etc.).
- Add those branches again to the final `st.one_of(...)` (see "Boosting known crash
  producers").
- Within those specific branches only, make small targeted variations: nesting depth ±,
  number of duplicate attributes, quote style, adjacent byte values around a boundary —
  changes that explore the neighborhood of what worked, not changes that replace it.

### 3. Structural diversity expansion (if section 3 is empty and acceptance rate is
reasonable, e.g. 20%+)
Add NEW branches targeting structural shapes not yet represented in `{prev_strategy}`,
rather than scaling up existing ones. Check what's genuinely new relative to what's
already there — for example: deeper mismatched-tag nesting (3+ levels apart, not just
adjacent), a second top-level root element after the first closes, DTD-shaped
`<!DOCTYPE...>`/`<!ENTITY...>` blocks, entity references mixed inside attribute values
specifically (not just text content), or a UTF-16 BOM-prefixed document. Add these as new
`st.one_of(...)` branches; do not touch existing branches to make room.

### 4. Parameter/size escalation (last resort only, and always capped)
Only reach for this if priorities 1–3 don't apply and acceptance rate is very low
(under ~10%, suggesting the generator itself is producing mostly-garbage that mxml
rejects trivially) — and even then, apply the SIZE GUARDRAILS above. Escalating size on
a generator that's already being rejected for structural reasons (e.g. missing a closing
tag) won't help; fix the structural issue in priority 1 first.

---

## WHAT YOU ARE WRITING

You are writing a **strategy module**, not a test. This module is imported by an external
harness that already handles running examples, calling the parser, and detecting crashes.
You never see the parser and you never call it.

Your output's only executable top-level statements must be strategy-building calls
(`st.text`, `st.builds`, `st.recursive`, `st.one_of`, `st.sampled_from`, etc.) and simple
variable assignments, ending in a module-level `xml_strategy = ...`. Nothing else executes,
prints, asserts, decorates a function, or calls anything outside this module. If your
previous attempt was rejected for containing something outside this list, the fix is to
delete that code and return to editing `{prev_strategy}`'s actual strategy definitions —
not to produce a different variant of the same kind of statement.

## OUTPUT FORMAT — ABSOLUTE RULE

Output ONLY raw Python source code. NOT a single extra word.
- NO markdown code fences (do NOT use ``` or ```python)
- NO explanations, greetings, comments, or prose
- The very first character of your response MUST be a valid Python character (e.g., `i` in `import`)

## ALLOWED IMPORTS

ONLY these two imports are allowed:
```python
import hypothesis.strategies as st
import string
```

## OUTPUT SHAPE — YOUR ANSWER MUST LOOK EXACTLY LIKE THIS

This is a minimal but complete example of a valid refined module (illustrative content
only — your real output keeps every branch from `{prev_strategy}`, this is just showing
the shape: assignments and strategy-building calls only, nothing else):

```python
import hypothesis.strategies as st
import string

_NAME = st.text(alphabet=string.ascii_letters + string.digits + "_-", min_size=1, max_size=20)

_mismatched = st.builds(
    lambda a, b: f"<{a}><{b}></{a}></{b}>",
    _NAME, _NAME,
)

_dup_attr = st.builds(
    lambda n, v: f'<{n} x="{v}" x="{v}" x="{v}"/>',
    _NAME, st.text(min_size=1, max_size=200),
)

xml_strategy = st.one_of(
    _mismatched,
    _mismatched,
    _dup_attr,
)
```

Now write your refined module. Output ONLY the Python code, starting with `import`.
