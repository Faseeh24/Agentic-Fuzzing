# Agentic Fuzzing of Mini-XML (mxml)

Fuzzing the [Mini-XML (mxml)](https://github.com/michaelrsweet/mxml) C library using
ANTLR-generated grammars, [Hypothesis](https://hypothesis.works/) property-based testing,
and an LLM-driven agentic loop with crash triage.

---

## Overview

This project implements a complete agentic fuzzing pipeline (Steps 4–6 of the assignment):

1. **Grammar source** — ANTLR4 XML grammar from [antlr/grammars-v4](https://github.com/antlr/grammars-v4) drives structural generation.
2. **Adaptations** — `grammar/ADAPTATIONS.md` (source-verified) maps the grammar onto mxml's actual accepted dialect, so the generator only emits inputs mxml can parse.
3. **Harness** — `harness/mxml_harness.c` loads XML via `mxmlLoadString()` with ASan + UBSan.
4. **Agentic loop** — `fuzzer/agentic_loop.py` iteratively generates and refines Hypothesis strategies using an LLM.
5. **Crash triage** — `triage/` deduplicates, minimizes, and verifies crash reproducers.
6. **Report** — `report/report.md` is filled in manually with the final design, findings, and challenges.

---

## Repository Structure

```
Agentic-Fuzzing/
├── grammar/                          # ANTLR grammar sources and comparison docs
│   ├── README.md                     # Human-readable grammar comparison
│   ├── ADAPTATIONS.md                # LLM-facing grammar↔mxml comparison (reference)
│   ├── original/                     # Verbatim ANTLR reference XML grammar
│   │   ├── XMLLexer.g4
│   │   └── XMLParser.g4
│   └── adapted/                      # (future) mxml-adapted grammar variants
├── target/                           # Vendored target library
│   └── mxml/                         # Mini-XML at pinned commit e6824d8
├── harness/                          # C harness for feeding inputs to mxml
│   ├── mxml_harness.c
│   ├── Makefile
│   └── sample_tests/                 # Sample XML inputs for harness validation
├── fuzzer/                           # Hypothesis-based XML fuzzer
│   ├── baseline_strategy.py          # Baseline: fixed corpus to verify pipeline
│   ├── run_harness.py                # Python wrapper: timeout + sanitizer detection
│   ├── test_wrapper.py               # Wrapper classification tests
│   ├── agentic_loop.py               # LLM-driven agentic fuzzing loop
│   ├── llm_client.py                 # Multi-provider LLM client (OpenRouter/Groq/Gemini)
│   ├── strategies/                   # Generated Hypothesis strategies
│   ├── logs/                         # JSONL iteration logs + loop_summary.md
│   └── prompts/                      # LLM prompt templates
│       ├── seed_prompt.md
│       └── refine_prompt.md
├── triage/                           # Crash triage pipeline
│   ├── dedupe.py                     # Signature extraction and deduplication
│   ├── minimize.py                   # Hypothesis-based input minimization
│   ├── verify.py                     # Deterministic reproduction verification
│   └── run.py                        # Main triage entry point
├── report/                           # Written report (filled in manually)
│   └── report.md                     # Two-page written report (design, findings, challenges)
├── .env.example                      # API key placeholders
├── Dockerfile                        # Debian trixie-slim with sanitizers + Python deps
├── docker-compose.yml                # Full pipeline orchestration
├── requirements.txt                  # Python dependencies
└── README.md                         # This file
```

---

## Target: mxml

| Property        | Value                                                          |
|-----------------|----------------------------------------------------------------|
| Repository      | [michaelrsweet/mxml](https://github.com/michaelrsweet/mxml)    |
| Pinned commit   | `e6824d899d949387fb0156af6f4101373b9be519`                     |
| Version         | Mini-XML 4.x                                                   |
| Language        | C (C99)                                                        |
| License         | BSD-like                                                       |

### Cloning the Target

```bash
git clone https://github.com/michaelrsweet/mxml.git target/mxml
cd target/mxml
git checkout e6824d899d949387fb0156af6f4101373b9be519
cd ..
```

---

## Building the Harness

Build and test the full pipeline with a single Docker command:

```bash
docker compose up
```

Or build only:

```bash
docker compose run --rm harness make -C harness all
```

Run sample tests only:

```bash
docker compose run --rm harness make -C harness test
```

The harness compiles `mxml_harness.c` against the vendored mxml library with
`-fsanitize=address,undefined` inside a Debian container.

### Running the Harness

```bash
docker compose run --rm harness /src/harness/mxml_harness input.xml
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0`  | Valid parse — mxml accepted the XML |
| `1`  | Well-formed rejection — mxml rejected the input (parse error) |
| `2`  | Harness error — cannot read input file or I/O failure |
| `3`  | Sanitizer crash — ASan or UBSan detected a memory/UB violation |
| `4`  | Timeout — input exceeded the 5-second limit |
| `5`  | Bug crash — unexpected crash (segfault, abort, etc.) |

Codes 0–2 are emitted directly by the C harness. Codes 3–5 are added by
the Python wrapper in `fuzzer/run_harness.py` (timeout enforcement and
sanitizer-output detection).

### Sample Tests

```bash
# C harness sample tests
docker compose run --rm harness make -C harness test

# Python wrapper classification tests
docker compose run --rm harness make -C harness test-wrapper

# Baseline fuzzer strategy (proves pipeline plumbing works)
docker compose run --rm harness python3 -m fuzzer.baseline_strategy
```

---

## Fuzzer Architecture

```
fuzzer/
├── run_harness.py          # Python wrapper: runs C harness, detects timeout/sanitizer/bug
├── baseline_strategy.py    # Baseline: fixed corpus to verify pipeline plumbing
├── agentic_loop.py         # LLM-driven agentic fuzzing loop
├── llm_client.py           # Multi-provider LLM client (OpenRouter / Groq / Gemini)
├── strategies/             # Generated Hypothesis strategies (iteration_*.py)
├── logs/                   # JSONL iteration logs + loop_summary.md
└── prompts/                # LLM prompt templates (seed_prompt.md, refine_prompt.md)
```

**Exit code contract** (0–5):

| Code | Meaning | Source |
|------|---------|--------|
| `0`  | Valid parse — mxml accepted the XML | C harness |
| `1`  | Well-formed rejection — mxml rejected the input | C harness |
| `2`  | Harness error — cannot read input or I/O failure | C harness |
| `3`  | Sanitizer crash — ASan/UBSan detected a violation | Python wrapper |
| `4`  | Timeout — input exceeded 5-second limit | Python wrapper |
| `5`  | Bug crash — unexpected crash (segfault, abort, etc.) | Python wrapper |

---

## Agentic Loop

The agentic loop (`fuzzer/agentic_loop.py`) iteratively generates and refines a
Hypothesis XML strategy using an LLM. Each iteration:

1. **Generate / refine strategy** — the LLM produces (or revises) a Python module
   exporting `xml_strategy`, based on the ANTLR grammar and mxml-specific
   adaptation notes from `grammar/ADAPTATIONS.md`.
2. **Execute** — the strategy is run against the C harness via `run_harness.py`,
   collecting exit-code statistics over a configurable number of examples.
3. **Signal extraction** — proxy signals are computed:
   - **Acceptance rate** — fraction of inputs mxml accepts (code 0)
   - **Grammar coverage** — which XML grammar productions appear in the corpus
   - **Crash signatures** — unique sanitizer / timeout / bug-crash inputs
4. **Log** — every iteration is appended to `fuzzer/logs/iteration_N.jsonl`
   and a markdown summary is written to `fuzzer/logs/loop_summary.md`.
5. **Decide** — the loop stops when a crash is found, convergence is reached,
   or the max-iteration budget is exhausted.
6. **Triage** — any crashes are passed to `triage/` for deduplication, minimization,
   and verification.

### Proxy Signals

| Signal | How it's measured | Steering effect |
|--------|------------------|----------------|
| Acceptance rate | `valid / total` | Low rate → LLM tightens well-formed cases |
| Grammar coverage | Regex detection of production tokens in corpus | Missing productions → LLM adds coverage |
| Crash signatures | Distinct code-3/4/5 examples | Existing crashes → LLM generates near-miss variants |

### Strategy Design

The LLM-generated strategies use `@st.composite` for recursive productions
rather than flattening the grammar. Key structural elements:

- **`st.recursive`** for nested element/content structures
- **Dedicated sub-strategies** for the three highest-value deliberate breaks:
  1. Mismatched close tags (`<a><b></a></b>`)
  2. Duplicate attribute names (`<a x="1" x="2"/>`)
  3. Second top-level root element (`<a/><b/>`)
- **Verified constraints** from `ADAPTATIONS.md`: only 5 entity names,
  no control chars, proper UTF-8/BOM handling, real comment/CDATA terminators.

### Configuration

Copy `.env.example` to `.env` and fill in at least one API key:

```bash
cp .env.example .env
# edit .env and add your key(s)
```

Supported providers (auto-fallback in order: OpenRouter → Groq → Gemini):

| Provider | Env var | Default model |
|----------|---------|--------------|
| OpenRouter | `OPENROUTER_API_KEY` | `google/gemini-2.0-flash-001` |
| Groq | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| Gemini | `GEMINI_API_KEY` | `gemini-2.0-flash` |

### Running the Loop

```bash
# Docker (recommended — harness must be built first)
docker compose run --rm harness \
    PYTHONPATH=/src python3 -m fuzzer.agentic_loop \
    --max-iterations 5 --num-examples 200

# Native (Windows / Linux, requires Python + hypothesis + httpx)
python -m fuzzer.agentic_loop --max-iterations 5

# With a seed strategy
python -m fuzzer.agentic_loop --seed-strategy fuzzer/strategies/iteration_0000.py

# Skip triage (loop only)
python -m fuzzer.agentic_loop --no-triage
```

**Constraints enforced:**
- Maximum 500 examples per iteration, 10-minute wall-clock backstop
- Maximum 5 agentic loop iterations (~$5 LLM spend)
- 5-second timeout per input (timeouts count as crashes)

### Artifacts

| Path | Content |
|------|---------|
| `fuzzer/strategies/iteration_N[_refined].py` | Generated Hypothesis strategy modules |
| `fuzzer/logs/iteration_N.jsonl` | Per-iteration JSONL log (strategy, results, coverage, signatures) |
| `fuzzer/logs/loop_summary.md` | Markdown summary of the full loop run |

---

## Crash Triage (Step 5)

After the agentic loop, `triage/` processes all crash candidates:

### Pipeline

1. **Detect** — collect all code-3/4/5 examples from iteration logs.
2. **Deduplicate** — normalize ASan/UBSan stack traces and hash signatures.
3. **Save** — each unique signature gets a directory under `triage/crashes/{sig}/`:
   - `reproducer.xml` — the original crashing input
   - `sanitizer_report.txt` — full stderr output
   - `meta.json` — signal type and exit code
4. **Minimize** — wrap each reproducer in a Hypothesis `@given` test with a
   structured sub-document strategy; the shrinker converges on the smallest
   input that still triggers the same signature.
5. **Verify** — re-run each minimized reproducer 3 times to confirm deterministic
   reproduction.

### Normalization Choices (documented for the report)

| Choice | Value | Rationale |
|--------|-------|-----------|
| Stripped frames | `__interceptor_malloc`, `__interceptor_free`, `malloc`, `free`, `__libc_start_main`, `_start` | Allocator/runtime boilerplate present in every crash |
| Top N frames hashed | 5 | Too few over-merges distinct bugs sharing an allocator entry; too many under-merges due to ASLR/inlining noise |
| Bare timeout signature | `timeout\|struct=<structural_hash>` | Groups timeouts by input shape (length bucket, nesting depth, entity presence) rather than treating each as unique |

### Running Triage

```bash
# Docker
docker compose run --rm harness python3 -m triage.run

# Native
python -m triage.run

# With a custom crash directory
python -m triage.run --crash-dir /path/to/crashes
```

### Triage Artifacts

| Path | Content |
|------|---------|
| `triage/crashes/{signature}/reproducer.xml` | Original crashing input |
| `triage/crashes/{signature}/reproducer_minimized.xml` | Hypothesis-shrunk reproducer |
| `triage/crashes/{signature}/sanitizer_report.txt` | Full ASan/UBSan stderr |
| `triage/crashes/{signature}/meta.json` | Signal type, exit code, timeout flag |
| `triage/crashes/{signature}/meta.json` | Signal type, exit code, timeout flag |

---

The written report (`report/report.md`) is filled in manually after the pipeline completes.

## Full Pipeline

Run everything end-to-end:

```bash
docker compose up
```

This executes:
1. `make -C harness all test` — build and test the C harness
2. `make -C harness test-wrapper` — run Python wrapper classification tests
3. `python3 -m fuzzer.baseline_strategy` — verify pipeline plumbing
4. `python3 -m fuzzer.agentic_loop --max-iterations 5 --num-examples 200` —
   run the agentic fuzzing loop (5 iterations, 200 examples per iteration)
5. `python3 -m triage.run` — triage any crashes found (skipped if none)

---

## Grammar Comparison

See [`grammar/ADAPTATIONS.md`](grammar/ADAPTATIONS.md) for the source-verified comparison
used as LLM reference material; [`grammar/README.md`](grammar/README.md) is the
human-readable documentation version.

- Feature-by-feature comparison table (ANTLR grammar vs mxml)
- Generator constraints for safe Hypothesis strategies
- Source-code traceability to mxml's C implementation
- Canonical valid mxml example from the AFL seed corpus

---

## License

This project uses the BSD-licensed ANTLR reference XML grammar and the BSD-like
Mini-XML library. See individual source files for license details.
