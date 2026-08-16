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
3. **Comparison** — `grammar/README.md` documents the differences between the ANTLR grammar
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
│   ├── README.md               # ANTLR grammar ↔ mxml feature comparison
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

### Fuzzer Architecture

```
fuzzer/
├── run_harness.py       # Python wrapper: runs C harness, detects timeout/sanitizer/bug crashes
├── baseline_strategy.py # Baseline: fixed corpus to verify pipeline plumbing
├── strategies/          # (future) Hypothesis-based XML generation strategies
├── agentic_loop.py      # (future) Agentic orchestration loop
└── llm_client.py        # (future) LLM integration for adaptive fuzzing
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

See [`grammar/README.md`](grammar/README.md) for the complete analysis, including:

- Feature-by-feature comparison table (ANTLR grammar vs mxml)
- Generator constraints for safe Hypothesis strategies
- Source-code traceability to mxml's C implementation
- Canonical valid mxml example from the AFL seed corpus

---

## License

This project uses the BSD-licensed ANTLR reference XML grammar and the BSD-like
Mini-XML library. See individual source files for license details.
