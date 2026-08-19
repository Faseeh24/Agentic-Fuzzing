# Agentic-Fuzzing

A coverage-guided, LLM-driven fuzzing pipeline targeting the **Mini-XML (mxml)** C library.

```
LLM (Groq) → JSON Strategy Spec → Deterministic Generator → Hypothesis Strategy
                                                    ↓
                                            C Harness (ASan/UBSan)
                                                    ↓
                                           Crash Triage (Dedup/Min/Verify)
```

## Architecture

| Module | Purpose |
|--------|---------|
| `agent/` | LLM client (Groq), strategy planner, orchestrator loop |
| `generator/` | Pydantic strategy spec + deterministic Hypothesis compiler |
| `coverage/` | Coverage collection (LLVM/gcov — stub for now) |
| `engine/` | Fuzzing execution engine with feedback collection |
| `fuzzer/` | Baseline strategies, harness wrapper, legacy baseline |
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

## Installation

```bash
# Clone the repository
git clone <repo-url> && cd Agentic-Fuzzing

# Install Python dependencies
pip install -r requirements.txt

# Build the C harness
make -C harness all

# Run sample tests
make -C harness test
```

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
| `GROQ_MODEL` | Model to use (auto-selects if empty) | `llama-3.3-70b-versatile` |
| `MAX_ITERATIONS` | Agentic loop iterations | `5` |
| `NUM_EXAMPLES` | Examples per iteration | `200` |
| `WALL_CLOCK_CAP` | Time limit in seconds | `600` |
| `COST_BUDGET` | LLM cost budget in USD | `5.0` |
| `HARNESS_TIMEOUT` | Per-input timeout (seconds) | `5` |
| `COVERAGE_ENABLED` | Enable coverage collection | `true` |

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

  --max-iterations INT       Max refine cycles (default: 5)
  --num-examples INT         Examples per iteration (default: 200)
  --wall-clock-cap FLOAT     Wall-clock cap in seconds (default: 600)
  --cost-budget FLOAT        Cost budget in USD (default: 5.0)
  --no-triage                Skip crash triage after loop
```

## Output Artifacts

| Path | Description |
|------|-------------|
| `fuzzer/logs/iteration_*.jsonl` | Per-iteration JSONL logs |
| `fuzzer/logs/loop_summary.md` | Human-readable loop summary |
| `fuzzer/strategies/iteration_*.json` | Strategy specs (JSON) |
| `triage/crashes/<sig>/` | Deduplicated crash records |
| `triage/crashes/<sig>/reproducer_minimized.xml` | Minimized reproducer |
| `triage/crashes/<sig>/meta.json` | Crash metadata |
| `coverage/summary.json` | Coverage statistics |

## How It Works

### 1. Strategy Planning (LLM)

The LLM generates a **JSON strategy specification** describing:
- Objectives (what to cover: CDATA, nesting, entities, etc.)
- Constraints (max depth, entity whitelist, control char filtering)
- Mutations (probability of deliberate break patterns)

### 2. Deterministic Generation

The spec is compiled into a **Hypothesis SearchStrategy** by a fixed, auditable
Python module. The LLM never writes or executes Python code — it only produces
structured JSON.

### 3. Fuzzing Engine

The Hypothesis strategy generates XML inputs, which are fed to the C harness.
The harness classifies each input into one of six categories:

| Code | Category | Meaning |
|------|----------|---------|
| 0 | valid | mxml accepted the XML |
| 1 | invalid | mxml rejected the input |
| 2 | harness_error | I/O or memory failure |
| 3 | sanitizer | ASan/UBSan violation |
| 4 | timeout | Input exceeded timeout |
| 5 | bug_crash | Unexpected crash |

### 4. Crash Triage

Crashes are:
1. **Deduplicated** by normalized signature
2. **Minimized** using Hypothesis
3. **Verified** for deterministic reproduction

## Key Design Decisions

1. **No LLM-generated code execution** — The LLM only produces JSON; the generator is fixed and auditable.
2. **Groq-only** — Simplifies configuration, removes fallback complexity.
3. **Explicit pipeline states** — Failures are visible, not hidden.
4. **Structured crash reporting** — Exit code, signal, and stderr captured separately.
5. **Harness bug fix** — `ferror()` checked before `fclose()` to avoid use-after-close.
6. **Real grammar reference** — All rules consolidated in `grammar/GRAMMAR_RULES.md`.

## License

MIT
