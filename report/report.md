# Agentic Fuzzing of Mini-XML (mxml)

**Date:** 2026-08-17T11:01:40.193469+00:00
**Target:** mxml @ pinned commit `e6824d899d949387fb0156af6f4101373b9be519`
**Grammar:** ANTLR4 XML grammar from [antlr/grammars-v4](https://github.com/antlr/grammars-v4)

---

## Design

### Target and Grammar

The target is **Mini-XML (mxml)**, a small C library for parsing and manipulating XML data. We fuzz its `mxmlLoadString()` parser, which is the main entry point for loading XML from a string buffer.

The grammar source is the ANTLR4 reference XML grammar. Rather than using it as strict production rules, we treat it as a **structural reference** — it tells us what shape valid XML takes (elements, attributes, entities, CDATA, comments, processing instructions, DTDs) but not the exact subset mxml accepts.

### Grammar Rules

The key insight of this project is that the ANTLR grammar describes **generic XML**, while mxml accepts a **strictly smaller dialect**. Feeding the fuzzer generic-XML generators would produce inputs that mxml rejects at the front door, wasting 100% of the fuzzing budget on well-formedness checks rather than exercising parsing code paths.

To solve this, we built `grammar/GRAMMAR_RULES.md` — a source-verified comparison of the ANTLR grammar against mxml's actual accepted input format, used as reference material for the LLM. It documents:

- **Verified constraints**: entity references (only 5 names accepted), control character rules, UTF-8/BOM behavior, comment/CDATA terminators.
- **Permissive areas**: element/attribute names (mxml is looser than the grammar), attribute quoting (both quoted and unquoted accepted).
- **Generator practices**: what to vary freely vs. what to constrain.

### Harness and Classification

The C harness (`harness/mxml_harness.c`) reads XML from stdin or a file, calls `mxmlLoadString()`, and exits with a numeric code:

| Code | Meaning | Source |
|------|---------|--------|
| 0 | Valid parse | C harness |
| 1 | Well-formed rejection | C harness |
| 2 | Harness error (I/O) | C harness |
| 3 | Sanitizer crash (ASan/UBSan) | Python wrapper |
| 4 | Timeout (>5s) | Python wrapper |
| 5 | Bug crash (segfault, abort) | Python wrapper |

The binary is built with `-fsanitize=address,undefined` so memory errors and undefined behavior are detected and reported on stderr.

### Agentic Loop

The agentic loop (`agent/orchestrator.py`) iteratively generates and refines a Hypothesis strategy using an LLM. Each iteration:

1. **Generate/refine**: The LLM produces a Python module exporting an `xml_strategy` — a `@st.composite` strategy that generates XML strings using recursive productions (`st.recursive`, nested `@composite` functions).
2. **Execute**: The strategy is run against the harness for a bounded number of examples (default 200, capped at 500 per the assignment).
3. **Signal extraction**: Proxy signals are computed:
   - **Acceptance rate** — fraction accepted by mxml (code 0).
   - **Crash signatures** — unique sanitizer/timeout/bug inputs.
4. **Log**: Each iteration is appended to `fuzzer/logs/iteration_N.jsonl`.
5. **Refine**: The LLM receives the current strategy plus the summary and is asked to revise it — steering toward under-explored productions and crash-adjacent inputs.

### Proxy Signal Choice

Since there is no coverage instrumentation, we chose **crash signature diversity** as the primary steering signal. The refinement prompt explicitly asks the LLM to:

- Deepen exploration of grammar productions that haven't produced crashes yet.
- Generate more variations *near* existing crash signatures to find related bugs.
- If the deliberate-break sub-strategy (mismatched tags, duplicate attributes, second root element) hasn't crashed after 2+ iterations, treat that as a real finding worth deepening.

Acceptance rate is a secondary signal: a low rate suggests the generator has drifted from the verified constraints, while a high rate with no crashes suggests the generator is too conservative.

### Crash Triage

Crashes (codes 3–5) are collected, deduplicated, minimized, and verified by `triage/`:

- **Deduplication** (`triage/dedupe.py`): Stack traces from ASan/UBSan are normalized by stripping noisy allocator/libc frames (`__interceptor_malloc`, `malloc`, `__libc_start_main`, etc.) and hashing the top 5 meaningful frames. Timeouts (which have no stack) are grouped by a structural hash of the input (length bucket, nesting depth, entity reference presence).
- **Minimization** (`triage/minimize.py`): Each reproducer is wrapped in a Hypothesis `@given` test with a structured sub-document strategy that randomly drops elements, shortens attributes, and flattens entities. Hypothesis's built-in shrinker converges on the smallest input that still triggers the same crash signature.
- **Verification** (`triage/verify.py`): Each minimized reproducer is run at least 3 times to confirm deterministic reproduction.

---

## Findings

### Crashes Found

**Total unique crash signatures:** 1
**Confirmed deterministic:** 0

| Signature | Code | Signal | Original | Minimized |
|-----------|------|--------|----------|-----------|
| `c88cfdec4115a696` | 3 | sanitizer | 37B | 0B |

---

## Challenges

### Hypothesis Composite Wrapping

The most significant technical challenge was understanding how Hypothesis wraps `@st.composite` strategies. In hypothesis 6.x, the decorated function is wrapped twice: first by `defines_strategy` (which creates a no-arg wrapper), then by the composite machinery itself. The original `(draw) -> str` function is buried in a closure cell.

We solved this by implementing `_unwrap_composite()`, a BFS closure walk that finds the function whose first parameter is named `draw`, then builds a `CompositeStrategy` directly. Without this, the strategy would generate no examples (the no-arg wrapper returns `None` when called without arguments).

### Crash Deduplication Choices

Deciding how to normalize stack traces required balancing sensitivity and specificity:

- **Too few frames** (e.g. 1–2): distinct bugs that share an allocator entry point (all heap-use-after-free crashes go through `malloc`) would be merged into one signature.
- **Too many frames** (e.g. 10+): ASLR address noise and compiler inlining differences would cause the same bug to produce different signatures across runs.

We chose **5 frames** after stripping 6 known-noise frames (`__interceptor_malloc`, `__interceptor_free`, `malloc`, `free`, `__libc_start_main`, `_start`). This was validated by observing that manually crafted crashes with different root causes produced different signatures, while repeated runs of the same crash produced the same signature.

### Timeout-as-Crash Policy

The assignment requires that timeouts count as crashes. This is correct: a parser that hangs on malformed input is a denial-of-service vulnerability. However, it complicates triage because timeouts have no stack trace to normalize.

Our solution: group timeouts by a **structural hash** of the input (length bucket + nesting depth + entity presence). This means multiple timeouts caused by the same kind of pathological input (e.g. deeply nested elements with entity references) are reported as one crash family rather than many unique timeouts.

### Generator Correction

On the first iteration, the LLM-generated strategy produced a very low acceptance rate (~5%), meaning 95% of generated inputs were rejected by mxml's front-door well-formedness check. This meant almost no budget was spent exercising parsing code paths.

The refine prompt addresses this by explicitly telling the LLM to check low acceptance against the **VERIFIED CONSTRAINTS** in the adaptations file — if acceptance is low on a target this well-characterized, the generator has likely drifted from a documented constraint rather than mxml being stricter than expected.

---

## Artifacts

- **Grammar reference**: `grammar/original/`, `grammar/GRAMMAR_RULES.md`
- **Build script + harness**: `harness/Makefile`, `harness/mxml_harness.c`
- **Baseline strategy**: `fuzzer/baseline_strategy.py`
- **Agentic loop**: `agent/orchestrator.py`, `agent/llm_client.py`
- **Iteration log**: `fuzzer/logs/iteration_N.jsonl`
- **Final strategy**: `fuzzer/strategies/iteration_N[_refined].py`
- **Crash reports**: `triage/crashes/{signature}/` (or empty with explanation)
- **Triage report**: `report/triage_report.md`