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
│   └── Makefile
├── fuzzer/                     # Hypothesis-based XML fuzzer
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

```bash
cd harness
make
```

The harness compiles `mxml_harness.c` against the vendored mxml library and produces
an executable that reads an XML file from a path argument and reports `ACCEPT` or
`REJECT`.

---

## Running the Fuzzer

```bash
python -m fuzzer
```

(Additional run commands and configuration options will be documented as the fuzzer
is implemented.)

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
