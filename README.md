# Agentic-Fuzzing

A **blackbox**, LLM-driven agentic fuzzing pipeline targeting the **Mini-XML (mxml)** C library — no coverage instrumentation drives generation; refinement is steered by parser acceptance rate and crash signatures.

```
LLM (Groq) → Python Hypothesis Strategy (st.recursive/@composite) → Hypothesis
                                                    ↓
                                            C Harness (ASan/UBSan)
                                                    ↓
                                           Crash Triage (Dedup/Min/Verify)
```

## Architecture

| Module | Purpose |
|--------|---------|
| `agent/` | LLM client (Groq), strategy planner, orchestrator loop |
| `generator/` | AST validator + loader for LLM-authored Python strategies |
| `engine/` | Fuzzing execution engine (placeholder) |
| `fuzzer/` | Harness wrapper, baseline + fallback strategies |
| `harness/` | C harness (mxmlLoadString, ASan/UBSan instrumented) |
| `grammar/` | ANTLR grammar reference + mxml-specific rules |
| `triage/` | Crash deduplication, minimization, verification |

### Pipeline States

The system reports one of these states after each run:

| State | Meaning |
|-------|---------|
| `PIPELINE_SUCCESS` | Loop completed normally, no crashes |
| `PIPELINE_FAILED` | An unrecoverable error occurred |
| `NO_CRASH_FOUND` | Loop completed, no crashes detected |
| `CRASH_FOUND` | Crashes were found and triaged |
| `LLM_UNAVAILABLE` | Groq API key missing or rate-limited |
| `HARNESS_FAILED` | C harness not built or not executable |

## Prerequisites

- **Python 3.10+** with pip
- **Groq API key** — get one at <https://console.groq.com/keys>
- **C compiler** (gcc/clang) with ASan/UBSan support
- **Docker** (optional, for sandboxed execution)
- **Mini-XML (mxml) library** — vendored in `target/mxml/`

## Installation

```bash
# Clone the repository
git clone <repo-url> && cd Agentic-Fuzzing

# Install Python dependencies
pip install -r requirements.txt

# Build the C harness (requires mxml library in target/mxml/)
make -C harness all

# Run sample tests
make -C harness test
```

### Mini-XML (mxml) Setup

The project ships with the **Mini-XML v4.0** library vendored at `target/mxml/`.
This is the exact version used throughout fuzzing — no separate download is needed.

**If you need to update or rebuild mxml:**

```bash
# Clone the mxml repository into target/mxml/ (replaces vendored copy)
rm -rf target/mxml
git clone --depth=1 --branch v4.0.5 https://github.com/michaelrsweet/mxml.git target/mxml

# Then rebuild the harness to pick up the new source
make -C harness clean all
```

**Target commit** (the version this project was developed against):

- **Commit:** `e6824d8` — _"Use mxml-private.h header in unit test program."_
- **Date:** 2026-03-21
- **Version:** Mini-XML 4.0.5-dev (pre-release v4.0.5)
- **Repository:** <https://github.com/michaelrsweet/mxml>

The vendored copy is compiled with `-fsanitize=address,undefined` to catch memory errors,
use-after-frees, and undefined behavior in mxml's parser.

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env and set GROQ_API_KEY
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GROQ_API_KEY` | **Required.** Your Groq API key | — |
| `GROQ_MODEL` | Model to use (auto-selects if empty) | `openai/gpt-oss-20b` |
| `MAX_ITERATIONS` | Agentic loop iterations | `5` |
| `NUM_EXAMPLES` | Examples per iteration | `200` |
| `WALL_CLOCK_CAP` | Time limit in seconds | `600` |
| `COST_BUDGET` | LLM cost budget in USD | `5.0` |

> **Note:** `.env` values override all hardcoded defaults. The CLI flags use `.env` values as their defaults (see `orchestrator.py`).

## Running

### Docker (recommended)

```bash
# Full pipeline: build → test → baseline → agentic loop → triage
docker compose up

# Build only
docker compose run --rm harness make -C harness all

# Run agentic loop only
docker compose run --rm harness python3 -m agent.orchestrator --max-iterations 5 --num-examples 200

# Run triage only
docker compose run --rm harness python3 -m triage.run
```

### Native

> **Note:** The C harness is a Linux ELF binary built with gcc. Native Windows
> runs require either WSL2 or a cross-compiler. Docker is the recommended
> environment on Windows.

```bash
# Build harness
make -C harness all

# Run sample tests
make -C harness test

# Run baseline strategy
python -m fuzzer.baseline_strategy

# Run agentic fuzzing loop
python -m agent.orchestrator --max-iterations 5 --num-examples 200

# Run crash triage
python -m triage.run
```

### CLI Options

```
python -m agent.orchestrator [OPTIONS]

  --max-iterations INT       Max refine cycles (default: from $MAX_ITERATIONS or 5)
  --num-examples INT         Examples per iteration (default: from $NUM_EXAMPLES or 200)
  --wall-clock-cap FLOAT     Wall-clock cap in seconds (default: from $WALL_CLOCK_CAP or 600)
  --cost-budget FLOAT        Cost budget in USD (default: from $COST_BUDGET or 5.0)
  --no-triage                Skip crash triage after loop
```

## Output Artifacts

| Path | Description |
|------|-------------|
| `fuzzer/logs/iteration_*.jsonl` | Per-iteration JSONL logs (includes real stderr) |
| `fuzzer/logs/loop_summary.md` | Human-readable loop summary |
| `fuzzer/strategies/iteration_*.py` | **LLM-generated Python Hypothesis strategies** |
| `triage/crashes/<sig>/` | Deduplicated crash records |
| `triage/crashes/<sig>/reproducer_minimized.xml` | Minimized reproducer |
| `triage/crashes/<sig>/meta.json` | Crash metadata |

## How It Works

### 1. Strategy Planning (LLM)

The LLM **directly generates a Python file** defining a module-level `xml_strategy` using `hypothesis.strategies.recursive` and `@composite` for recursive grammar productions. This strategy file is itself a required deliverable and graded artifact.

The LLM output is **not executed blindly** — before loading, an AST-based static validator (`generator/strategy_validator.py`) checks that the file:
- Only imports from `hypothesis.strategies`, `string`, `random`
- Defines a module-level `xml_strategy`
- Contains no top-level side-effecting calls (I/O, subprocess, eval, etc.)

Only after passing this AST check is the file `exec()`-ed in a restricted namespace.

### 2. Fuzzing Engine

The Hypothesis strategy generates XML inputs, which are fed to the C harness. The harness classifies each input into one of six categories:

| Code | Category | Meaning |
|------|----------|---------|
| 0 | valid | mxml accepted the XML |
| 1 | invalid | mxml rejected the input |
| 2 | harness_error | I/O or memory failure |
| 3 | sanitizer | ASan/UBSan violation |
| 4 | timeout | Input exceeded timeout |
| 5 | bug_crash | Unexpected crash |

**Real stderr is captured at fuzzing time** and written to the JSONL logs, so crash signatures can be computed from actual ASan/UBSan stack traces without re-running.

### 3. Blackbox Proxy Signals (No Coverage Instrumentation)

Per the assignment constraints, this is a **blackbox fuzzer** — no coverage-guided mutation, no instrumentation beyond sanitizers. Refinement is steered by two proxy signals computed from the raw fuzzing output:

1. **Parser acceptance rate** — ratio of valid parses to total inputs
2. **Crash signatures** — normalized ASan/UBSan stack traces (or structural fallback for timeouts)

These are the *only* signals the orchestrator feeds back to the LLM for refinement.

### 4. Crash Triage

Crashes are:
1. **Deduplicated** by normalized signature (computed exactly once, from real stderr)
2. **Minimized** using Hypothesis
3. **Verified** for deterministic reproduction

If a signature directory already exists, the new reproducer is compared against the existing one — shorter (better minimized) versions replace the original; others are stored as variants in `triage/crashes/<sig>/reproducers/` rather than silently overwriting.

## Blackbox Fuzzer — Design Clarification

This is a **blackbox fuzzer per the assignment's constraints**. Coverage is **never** used to steer generation. The proxy signals (parser acceptance rate and crash signatures) are the intentional substitute for coverage feedback.

## Key Design Decisions

1. **LLM authors Hypothesis code directly; AST validator gates execution** — The LLM produces a full Python strategy file using `st.recursive`/`@composite`. An AST-based static validator (`generator/strategy_validator.py`) rejects unsafe imports, missing `xml_strategy`, or side-effecting calls before the file is loaded in a restricted namespace. This is a deliberate tradeoff: it gives the LLM full expressive power while maintaining a safety boundary that is auditable and reviewable.

2. **Groq-only** — Simplifies configuration, removes fallback complexity.
   Kaggle notebook supports open-source LLMs (Qwen, etc.) via `kaggle_assets/llm_client_hf.py`.

3. **Explicit pipeline states** — Failures are visible, not hidden.

4. **Structured crash reporting** — Exit code, signal, and stderr captured separately at fuzzing time.

5. **Harness bug fix** — `ferror()` checked before `fclose()` to avoid use-after-close.

6. **Real grammar reference** — All rules consolidated in `grammar/GRAMMAR_RULES.md`.

7. **Robust LLM strategy production** — The LLM's output is validated with an AST checker **and** actually loaded + sample-generated before it is used. If the model produces an unusable strategy (empty reply, hallucinated API, misused `st.recursive`), the orchestrator falls back to a bundled known-good strategy (`fuzzer/fallback_strategy.py`) so the loop still runs. The LLM client also caps chain-of-thought for reasoning models (`reasoning_effort=low` for GPT-OSS/Qwen) so that a strategy is always emitted instead of an empty `content`.

## Kaggle Notebook (Open-Source LLM Edition) - Notes

A single-file, self-contained Kaggle notebook runs the full pipeline with an
**open-source HuggingFace model** (no Groq API key required):

- **Notebook:** `kaggle_notebook.ipynb` (repo root) -- upload to Kaggle and run
  top-to-bottom.
- **Open-source LLM client:** `kaggle_assets/llm_client_hf.py` -- an
  interface-compatible `LLMClient` (HF Transformers) that the notebook writes
  over `agent/llm_client.py` via a `%%writefile` cell. The orchestrator runs
  unchanged (only the cosmetic `llm_provider` label is patched).
- **Generator:** `kaggle_assets/build_notebook.py` rebuilds the notebook from
  the cells + the client source.

Set `MODEL_SOURCE` / `MODEL_NAME` in the notebook's Configuration cell. E.g.
`MODEL_SOURCE = "hf"` + `MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"` (GPU), or
`MODEL_SOURCE = "kaggle_input"` + `KAGGLE_MODEL_REF = "/kaggle/input/..."` to use a
Kaggle Model you attached via the UI. See `kaggle_assets/README.md` for details.

A final "Save artifacts to Output" cell copies strategies, per-iteration logs
and crash reproducers into `/kaggle/working/output/agentic_fuzzing_run/` so they
are preserved in the run's Output tab.

## Summary of Results

The agentic loop successfully evolved a Hypothesis strategy to discover **4 unique crash signatures** in the Mini-XML library across **5 iterations**, generating **2,500 test cases**.

**Key Findings:**
- **1,164 crash candidates** detected, reduced to 4 unique signatures after triage
- Main vulnerabilities: memory leaks during error paths, heap buffer stress from massive attributes, stack overflow from deep tag nesting
- The LLM adapted from well-formed XML (93% valid) to hostile inputs that triggered ASan violations

**Deliverables Location:**
| Category | Location |
|----------|----------|
| Iteration logs | `fuzzer/logs/iteration_*.jsonl` |
| Loop summary | `fuzzer/logs/loop_summary.md` |
| LLM-generated strategies | `fuzzer/strategies/iteration_*.py` |
| Unique crash reports | `triage/crashes/<sig>/reproducer_minimized.xml` |
| Full technical report | `report/report.md` |

## License

MIT
