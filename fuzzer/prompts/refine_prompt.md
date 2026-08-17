Here is the strategy you generated last iteration:
```python
{prev_code}
```

Here is what happened when it ran against the real target:
{prev_summary}

Revise the strategy. Specifically:
- If acceptance rate is low, tighten the well-formed cases (they're likely being
  rejected on a syntax detail — check quoting, closing tags, and entity syntax
  again against the grammar).
- If acceptance rate is high but few/no crashes, increase structural diversity:
  push nesting deeper, generate more attribute/entity combinations, spend more
  weight on the malformed-but-close cases in the adaptations list that haven't
  produced crashes yet.
- If there are existing crash signatures, generate more variations *near* those
  inputs (similar shape, mutated sizes/depths/character sets) to help minimization
  and to check for a family of related bugs, while still spending some budget on
  unexplored grammar productions.
- Output ONLY the full revised Python file contents, same interface (`xml_strategy`).
