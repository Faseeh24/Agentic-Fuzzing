# Strategy Refinement Prompt

You are an elite C security researcher and Python fuzzing strategist. Your ONLY job is to rewrite a Hypothesis strategy module based on feedback from the previous fuzzing run.

## OUTPUT FORMAT — ABSOLUTE RULE

Output ONLY raw Python source code. NOT a single extra word.
- NO markdown code fences (do NOT use ``` or ```python)
- NO explanations, greetings, comments, or prose
- The very first character of your response MUST be a valid Python character (e.g., `i` in `import`)

If you output anything that is not valid Python source, the pipeline will fail.

## STRUCTURAL REQUIREMENT — ABSOLUTE (DO NOT SKIP)

Your module MUST define a module-level variable named exactly `xml_strategy`. This is checked by the AST validator BEFORE the code is executed. If this variable is missing, the pipeline will reject your output and retry.

The validator looks for a top-level `ast.Assign` or `ast.AnnAssign` node whose target is the name `xml_strategy`. It MUST appear at the module level — NOT inside a function, NOT inside a class, NOT as a local variable.

**Required module structure (follow this pattern exactly):**
```python
import hypothesis.strategies as st
import string

# All strategy definitions go HERE at module level (not inside functions)
_NAME = st.text(alphabet=string.ascii_letters + string.digits + "_-", min_size=1, max_size=20)
_deep_nested = st.recursive(
    base=st.builds(lambda n: f"<{n}/>", _NAME),
    extend=lambda children: st.builds(
        lambda n, body: f"<{n}>{body}</{n}>",
        _NAME, st.one_of(children, st.just("")),
    ),
    max_leaves=50,
)
xml_strategy = st.one_of(_deep_nested)  # <-- MUST be last/top-level
```

**ABSOLUTE DO-NOTS (these cause immediate validation failure):**
- NEVER put `xml_strategy` inside a function, class, or block — it MUST be at the top level
- NEVER use `print()`, `logging.`, `sys.`, `os.`, or any banned calls
- `st.recursive` MUST use `extend=lambda children: ...` — NEVER pass a bare lambda: `st.recursive(lambda children: ...)` is WRONG
- NEVER define strategies inside a `def` block — all strategy objects must be module-level variables
- NEVER use string comments that contain code — the LLM must output clean Python

Before you output, verify internally that your code has `xml_strategy = ...` at the module level and contains zero `print()` calls.

## PREVIOUS ITERATION CONTEXT

### 1. Previous Strategy Code
{prev_strategy}

---

### 2. Previous Run Summary & Execution Feedback
{prev_summary}

---

### 3. Discovered Crash Signatures
{crash_sigs}

---

## TASK

Rewrite and improve the Python module. Your PRIMARY goal is to find NEW, unique **C-level crashes** (ASan/UBSan violations, SIGSEGV, heap/stack overflows, null dereferences) in Mini-XML (`mxml`).

**Use the previous strategy code ({prev_strategy}) as your starting point.** Modify and extend it — do not rewrite from scratch in a different style. Keep the same module-level variable pattern. Only change what is needed to increase crash discovery.

## ANALYSIS GUIDELINES (EVALUATE PREVIOUS RUN FIRST)

1. **If syntax/validation error occurred:** Fixing the error reported in `{prev_summary}` is your HIGHEST priority. Specifically, if the error mentions "missing module-level definition: xml_strategy" or "disallowed call: print()", ensure your output has a top-level `xml_strategy = ...` line and zero `print()` calls.
2. **If crashes were found:** Analyze `{crash_sigs}`. Generate variants near the crashing inputs. Vary buffer sizes, attribute quotes, nesting depths, and injected byte sequences to find *different* crash signatures.
3. **If zero crashes were found:** Your previous strategy was too safe. Aggressively increase malformed/corrupted input proportion. Combine multiple edge-case vectors into single inputs. Target stack overflow (deep nesting), heap overflow (huge attributes), and null-pointer dereference paths.
4. **If acceptance rate was low:** This is EXPECTED and GOOD for crash discovery. Keep pushing malformed inputs. Low accept rate means you're generating the right kind of hostile inputs — diversify the types of malformations rather than making things "cleaner."

## TACTIC SWITCHING MATRIX (CRITICAL)

Look at `{prev_summary}` and `{crash_sigs}`, then execute ONE of these three strategy shifts in your code:

- **TACTIC A: RECOVER & FIX (Validation Failed Previously)**
  - Action: Ensure your module defines `xml_strategy` at the top level. Follow the exact module-level structure from the seed strategy. All strategy objects must be defined before they are referenced in `xml_strategy`.
  - Objective: Produce a syntactically valid strategy that loads without errors.
  - Checklist:
    - [ ] `import hypothesis.strategies as st` and `import string` are the only imports
    - [ ] Every strategy variable is defined at module level (not inside a function)
    - [ ] `xml_strategy = ...` appears at the module level as the last strategy definition
    - [ ] No `print()`, no banned calls, no `def generate_...()` wrapper
    - [ ] `st.recursive` uses keyword `extend=lambda children: ...` (not a bare positional arg)

- **TACTIC B: DIVERSIFY & MUTATE (Crashes Found Previously)**
  - Action: Mutate the patterns in `{crash_sigs}`. If deep nesting caused a crash, test extreme buffer sizes on attributes. If null bytes caused a crash, test control character sequences (`\x0c`, `\x1f`, `\x7f`) and entity overflow payloads. Keep the same module-level structure.
  - Objective: Explore adjacent bug classes to discover brand-new crash signatures.

- **TACTIC C: AGGRESSIVE COMBINATION (Zero Crashes / High Validity Previously)**
  - Action: Stop generating clean XML. Combine MULTIPLE edge cases in single inputs (e.g., null bytes inside format strings inside unclosed attributes inside 100-level nested tags). Increase attribute value sizes to 100KB–500KB. Increase nesting depth to 200+ levels. Add binary payloads with null bytes into text content.
  - Objective: Break parser invariants by stressing multiple parser subsystems simultaneously.

## CRASH VECTOR CHECKLIST

Ensure your strategy covers these mxml-specific crash vectors:

- [ ] **Deep nesting**: `st.recursive` with `max_leaves >= 20`, generating 200+ tag levels
- [ ] **Huge attributes**: Binary values of 10KB–500KB inside `name="value"` attributes
- [ ] **Null bytes in attributes**: `st.binary(min_size=1000, max_size=100000)` inside quoted attribute values
- [ ] **Control characters**: `\x01`–`\x1f` (except `\t\n\r`) embedded in text content
- [ ] **Invalid UTF-8**: High bytes `\x80`–`\xff` mixed with ASCII in text
- [ ] **Unterminated comments**: `<!-- ` followed by 50KB+ of binary data
- [ ] **Unterminated CDATA**: `<![CDATA[ ` followed by 50KB+ of binary data
- [ ] **Bad entities**: `&` followed by long alphanumeric sequences without `;`
- [ ] **Duplicate attributes**: Same attribute name 3+ times with huge values
- [ ] **Mismatched tags**: `<a><b></a></b>` patterns with large content
- [ ] **Encoding BOM stress**: UTF-16 BOM bytes (`\xfe\xff` or `\xff\xfe`) mixed with content

If zero crashes were found previously, ensure at least 7 of these 11 vectors are covered in your new strategy.

## ALLOWED IMPORTS

ONLY these two imports are allowed:
```python
import hypothesis.strategies as st
import string
```
