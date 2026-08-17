Here is the strategy you generated last iteration:
```python
{prev_code}
```

Here is what happened when it ran against the real target:
{prev_summary}

Revise the strategy. Specifically:
- If acceptance rate is low, tighten the well-formed majority (check it against the
  VERIFIED CONSTRAINTS above literally — a low acceptance rate on a target this
  well-characterized usually means the well-formed generator drifted from a documented
  constraint, not that mxml is stricter than expected).
- If the deliberate-break sub-strategy (mismatched tags / duplicate attrs / second root)
  hasn't produced any crashes yet after 2+ iterations, that's a real (negative) finding
  worth deepening rather than abandoning — try nesting the mismatch deeper, or combining
  it with the other constraints (e.g. a duplicate attribute whose value contains a
  numeric char ref) before concluding those error paths are simply solid.
- If acceptance is high and the deliberate-break minority is running but nothing's
  crashing, widen structural diversity elsewhere: deeper nesting, more DTD-shaped opaque
  blocks, UTF-16 BOM-prefixed documents, or attribute values mixing multiple entity
  types in one value.
- If there are existing crash signatures, generate more variations *near* those inputs
  (similar shape, mutated sizes/depths/character sets) to aid minimization and check for
  a family of related bugs, while still spending some budget on unexplored areas.
- Output ONLY the full revised Python file contents, same interface (`xml_strategy`).

HYPOTHESIS API CONSTRAINTS (strict — do NOT violate these):
- `st.frequency()` DOES NOT EXIST in Hypothesis. Do NOT use it.
- For weighted mixing, use `st.one_of(...)` for equal weight or a `@st.composite`
  function that draws an index and dispatches, as shown in the seed prompt.
- The module must expose exactly one attribute: `xml_strategy` (a Hypothesis SearchStrategy).
