# Agentic-Fuzzing Project Guide

## What is this system?

This is a **blackbox**, LLM-driven fuzzing pipeline that targets the
Mini-XML (mxml) C library. It combines:

1. **Large Language Models** (Groq API) for strategic guidance
2. **Hypothesis** for property-based input generation
3. **LLM-authored Hypothesis strategies** (using `st.recursive`/`@composite`)
4. **AST-based static validation** before executing LLM code
5. **ASan/UBSan** for crash detection
6. **Automated triage** (deduplication, minimization, verification)

## Architecture Overview

```
                    ┌─────────────────────┐
                    │     Orchestrator    │
                    │   (agent/orchestr.) │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
       │  Grammar    │ │  Target     │ │  Blackbox   │
       │  Analyzer   │ │  Analyzer   │ │  Feedback   │
       └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
              └────────────────┼────────────────┘
                               ▼
                      ┌─────────────────┐
                      │  Strategy       │
                      │  Planner (LLM)  │
                      └────────┬────────┘
                               │
                               ▼ Python strategy
                      ┌─────────────────┐
                      │  AST Validator  │
                      │ (generator/)    │
                      └────────┬────────┘
                               │
                               ▼ Validated strategy
                      ┌─────────────────┐
                      │  Fuzzing Engine │
                      │  (sandboxed)    │
                      └────────┬────────┘
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
                 Crash        Timeout      Bug
                Detector     Detector    Crash
                    └──────────┼──────────┘
                               ▼
                         ┌─────────────┐
                         │  Triage     │
                         │ (triage/)   │
                         └─────────────┘
```

## LLM-Authored Strategies with AST Validation

The LLM directly authors a Python module defining a module-level `xml_strategy` variable (a `hypothesis.strategies.SearchStrategy[str]`). This generated strategy code is itself a required deliverable.

### Why no JSON specs (decision history)

An earlier design had the LLM emit a JSON strategy specification that a fixed
compiler turned into Hypothesis code. That path was removed — the assignment
requires the LLM to directly produce Hypothesis strategy code, so the generator
now loads the LLM's Python module directly behind the AST validator.

### Safety without avoiding LLM code entirely

Instead of avoiding LLM-authored code, we gate execution with an AST-based static validator (`generator/strategy_validator.py`):

| Check | Purpose |
|-------|---------|
| Import allow-list | Only `hypothesis.strategies`, `string`, `random` |
| Ban list | No `os`, `subprocess`, `socket`, `sys`, `shutil`, `open`, `eval`, `exec`, `__import__`, `ctypes` |
| Required symbol | Must define module-level `xml_strategy` |
| No side effects | Top-level calls outside strategy construction are rejected |

Only files passing all checks are `exec()`-ed in a restricted namespace (no `__builtins__` beyond safe set).

## Pipeline States

The system reports one of these states after each run:

| State | Meaning |
|-------|---------|
| `PIPELINE_SUCCESS` | Loop completed normally |
| `PIPELINE_FAILED` | An unrecoverable error occurred |
| `NO_CRASH_FOUND` | Loop completed, no crashes detected |
| `CRASH_FOUND` | Crashes were found and triaged |
| `LLM_UNAVAILABLE` | Groq API key missing or rate-limited |
| `HARNESS_FAILED` | C harness not built |

## Harness Exit Codes

| Code | Label | Meaning |
|------|-------|---------|
| 0 | valid | mxml accepted the XML |
| 1 | invalid | mxml rejected the input |
| 2 | harness_error | I/O or memory failure |
| 3 | sanitizer | ASan or UBSan detected a violation |
| 4 | timeout | Input exceeded 5-second limit |
| 5 | bug_crash | Unexpected crash (segfault, abort, etc.) |

## Configuration (.env)

All configuration is done through environment variables in `.env`:

```bash
# Copy example and fill in your key
cp .env.example .env
# Edit .env and set GROQ_API_KEY
```

| Variable | Description | Default |
|----------|-------------|---------|
| `GROQ_API_KEY` | Your Groq API key (required) | — |
| `GROQ_MODEL` | Model to use (auto-selects if empty) | `openai/gpt-oss-20b` |
| `MAX_ITERATIONS` | Loop iterations | `5` |
| `NUM_EXAMPLES` | Examples per iteration | `200` |
| `WALL_CLOCK_CAP` | Time limit (seconds) | `600` |
| `COST_BUDGET` | LLM cost budget (USD) | `5.0` |

**Important:** `.env` values are loaded via `python-dotenv` and serve as the defaults for CLI flags. Run `python -m agent.orchestrator --help` to see the effective defaults.

## Running the System

### Docker (recommended)

```bash
# Full pipeline
docker compose up

# Build only
docker compose run --rm harness make -C harness all

# Run agentic loop
docker compose run --rm harness python3 -m agent.orchestrator --max-iterations 5 --num-examples 200

# Run triage
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

## Key Design Decisions

1. **LLM authors Hypothesis code directly; AST validator gates execution** — The LLM produces a full Python strategy file using `st.recursive`/`@composite`. An AST-based static validator rejects unsafe imports, missing `xml_strategy`, or side-effecting calls before the file is loaded in a restricted namespace. This is a deliberate tradeoff: it gives the LLM full expressive power while maintaining a safety boundary that is auditable and reviewable.

2. **Groq-only** — Simplifies configuration, removes fallback complexity.

3. **Explicit pipeline states** — Failures are visible, not hidden.

4. **Structured crash reporting** — Exit code, signal, and stderr captured separately at fuzzing time.

5. **Harness bug fix** — `ferror()` checked before `fclose()` to avoid use-after-close.

6. **Real grammar reference** — All rules in `grammar/GRAMMAR_RULES.md` for LLM context.

7. **Blackbox by design** — No coverage instrumentation in the live loop. Proxy signals (acceptance rate, grammar-production coverage tagging, crash signatures) are the intentional substitute.

## Directory Structure

```
Agentic-Fuzzing/
├── agent/                         # LLM interaction, strategy planning
│   ├── __init__.py
│   ├── llm_client.py              # Groq-only client
│   ├── orchestrator.py            # Main agentic loop
│   ├── tools.py                   # Tool interface
│   └── prompts/                   # LLM prompts
│       ├── seed_prompt.md
│       └── refine_prompt.md
├── generator/                     # Strategy validation + loading
│   ├── __init__.py
│   ├── strategy_validator.py      # AST static checks
│   └── strategy_compiler.py       # AST validator + loader
├── engine/                        # Fuzzing execution engine (placeholder)
│   └── __init__.py
├── fuzzer/                        # Harness wrapper + baseline/fallback strategies
│   ├── __init__.py
│   ├── __main__.py
│   ├── baseline_strategy.py
│   ├── fallback_strategy.py       # Known-good strategy used if the LLM's fails
│   ├── run_harness.py
│   └── test_wrapper.py
├── harness/                       # C harness (bug fixed)
│   ├── mxml_harness.c
│   ├── Makefile
│   └── sample_tests/
├── grammar/                       # Grammar reference
│   ├── original/
│   │   ├── XMLLexer.g4
│   │   └── XMLParser.g4
│   └── GRAMMAR_RULES.md
├── triage/                        # Crash triage
│   ├── __init__.py
│   ├── __main__.py
│   ├── dedupe.py
│   ├── minimize.py
│   ├── verify.py
│   └── run.py
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
└── PROJECT_GUIDE.md
```

## Troubleshooting

### "Groq API key not set"

Set `GROQ_API_KEY` in `.env`:

```bash
echo "GROQ_API_KEY=gsk_..." >> .env
```

### "C harness not found"

Build the harness:

```bash
make -C harness all
```

### "Strategy validation failed"

Check the LLM response in `fuzzer/logs/loop_summary.md`. The LLM may have
returned invalid Python or used disallowed imports. Try again or adjust the prompt.

### Rate limiting

If you hit rate limits, wait a few minutes and retry. The system includes
automatic rate-limit detection and will report `LLM_UNAVAILABLE` state.

### ".env values not taking effect"

Ensure you have `python-dotenv` installed (`pip install python-dotenv`).
The orchestrator loads `.env` at startup and CLI defaults are drawn from
those values via `_get_env_int()` / `_get_env_float()` helpers.

## License

MIT