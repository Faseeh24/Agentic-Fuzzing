# Agentic-Fuzzing

Fuzzing the [Mini-XML (mxml)](https://github.com/michaelrsweet/mxml) C library using
ANTLR-generated grammars and [Hypothesis](https://hypothesis.works/) property-based testing.

---

## Overview

This project performs agentic fuzzing of the mxml XML parsing library. An ANTLR XML grammar
(from [antlr/grammars-v4](https://github.com/antlr/grammars-v4)) drives a Hypothesis-based
fuzzer to generate valid and invalid XML inputs against a vendored mxml binary.

The approach:

1. **Grammar source** — The reference ANTLR XML grammar defines the syntactic surface of
   XML that the fuzzer generates from.
2. **Target** — A pinned version of mxml (Mini-XML) is vendored under `target/mxml/` as the
   fuzzing target.
3. **Comparison** — `grammar/ADAPTATIONS.md` (source-verified) is loaded into the LLM as
   reference material; `grammar/README.md` is the human-readable version of the same content.
   and mxml's actual accepted dialect, so the generator only emits inputs mxml can parse.
4. **Harness** — `harness/mxml_harness.c` is a minimal C harness that loads XML from a file
   and reports whether mxml accepts or rejects it.
5. **Fuzzer** — The Hypothesis-driven fuzzer in `fuzzer/` uses strategies derived from the
   grammar to generate XML corpus entries, feeding them through the harness.

---

## Repository Structure

```
Agentic-Fuzzing/
├── grammar/                    # ANTLR grammar sources and comparison docs
│   ├── README.md               # Human-readable grammar comparison docs
│   ├── ADAPTATIONS.md          # LLM-facing grammar↔mxml comparison (reference material)
│   ├── original/               # Verbatim ANTLR reference XML grammar
│   │   ├── XMLLexer.g4
│   │   └── XMLParser.g4
│   └── adapted/                # (future) mxml-adapted grammar variants
├── target/                     # Vendored target library
│   └── mxml/                   # Mini-XML at pinned commit
├── harness/                    # C harness for feeding inputs to mxml
│   ├── mxml_harness.c
│   ├── Makefile
│   └── sample_tests/           # Sample XML inputs for harness validation
├── fuzzer/                     # Hypothesis-based XML fuzzer
│   ├── baseline_strategy.py    # Baseline strategy (proves pipeline works)
│   ├── run_harness.py          # Python wrapper around C harness (timeout + sanitizer detection)
│   └── test_wrapper.py         # Wrapper classification tests
├── agent/                      # Agentic orchestration layer
├── tests/                      # Test suites
├── baseline/                   # Baseline fuzzing runs
├── runs/                       # Fuzzing run artifacts
├── crashes/                    # Crash inputs collected during fuzzing
├── reports/                    # Fuzzing reports and statistics
├── scripts/                    # Utility and automation scripts
├── requirements.txt            # Python dependencies
└── README.md                   # This file
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

## Grammar Source

| Property         | Value                                                          |
|------------------|----------------------------------------------------------------|
| Repository       | [antlr/grammars-v4](https://github.com/antlr/grammars-v4)      |
| Path             | `xml/`                                                         |
| Files            | `XMLLexer.g4`, `XMLParser.g4`                                  |
| License          | BSD (Terence Parr, 2013)                                       |
| ANTLR Version    | 4                                                              |

The original grammar files are copied verbatim into `grammar/original/` to ensure
reproducibility. See `grammar/README.md` for the full feature-by-feature comparison
between the ANTLR grammar and mxml's actual accepted XML dialect.

---

## Building the Harness

Build and test the harness with a single Docker command:

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

### Baseline Strategy

`fuzzer/baseline_strategy.py` runs a fixed set of known-valid and known-invalid
XML inputs through the harness and verifies each classification is correct.
It does **not** attempt to find bugs — it only confirms the pipeline is wired
up properly.

```bash
# Run baseline strategy (Docker)
docker compose run --rm harness python3 -m fuzzer.baseline_strategy

# Run baseline strategy (native)
PYTHONPATH=fuzzer python3 -m fuzzer.baseline_strategy
```

## Fuzzer Architecture

```
fuzzer/
├── run_harness.py          # Python wrapper: runs C harness, detects timeout/sanitizer/bug crashes
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
   adaptation notes from `grammar/README.md`.
2. **Execute** — the strategy is run against the C harness via `run_harness.py`,
   collecting exit-code statistics over a configurable number of examples.
3. **Signal extraction** — proxy signals are computed:
   - **Acceptance rate** — fraction of inputs mxml accepts (code 0)
   - **Grammar coverage** — which XML grammar productions appear in the corpus
   - **Crash signatures** — unique sanitizer / timeout / bug-crash inputs
4. **Log** — every iteration is appended to `fuzzer/logs/iteration_N.jsonl`
   and a markdown summary is written to `fuzzer/logs/loop_summary.md`.
5. **Decide** — the loop stops when a crash is found, convergence is reached,
   or the max-iteration budget is exhausted. The refine prompt steers the next
   strategy toward unexplored grammar productions and crash-adjacent inputs.

### Proxy Signals

| Signal | How it's measured | Steering effect |
|--------|------------------|----------------|
| Acceptance rate | `valid / total` | Low rate → LLM tightens well-formed cases |
| Grammar coverage | Regex detection of production tokens in corpus | Missing productions → LLM adds coverage |
| Crash signatures | Distinct code-3/4/5 examples | Existing crashes → LLM generates near-miss variants |

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
    --max-iterations 10 --num-examples 200

# Native (Windows / Linux, requires Python + hypothesis + httpx)
python -m fuzzer.agentic_loop --max-iterations 10
```

Optional: seed the loop with an existing strategy:

```bash
python -m fuzzer.agentic_loop --seed-strategy strategies/iteration_0000.py
```

### Artifacts

| Path | Content |
|------|---------|
| `fuzzer/strategies/iteration_N[_refined].py` | Generated Hypothesis strategy modules |
| `fuzzer/logs/iteration_N.jsonl` | Per-iteration JSONL log (strategy, results, coverage, signatures) |
| `fuzzer/logs/loop_summary.md` | Markdown summary of the full run |

---

## Running the Fuzzer

```bash
# Docker (recommended)
docker compose run --rm harness python3 -m fuzzer.baseline_strategy

# Native (Windows/Linux)
cd fuzzer
PYTHONPATH=. python3 -m fuzzer.baseline_strategy
```

(Advanced fuzzer strategies using Hypothesis and LLM-driven generation will be
documented as they are implemented.)

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
