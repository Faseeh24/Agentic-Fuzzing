# Agentic-Fuzzing Project Guide

## What is this system?

This is a coverage-guided, LLM-driven fuzzing pipeline that targets the
Mini-XML (mxml) C library. It combines:

1. **Large Language Models** (Groq API) for strategic guidance
2. **Hypothesis** for property-based input generation
3. **Deterministic compilation** from strategy specs to generators
4. **ASan/UBSan** for crash detection
5. **Automated triage** (deduplication, minimization, verification)

## Architecture Overview

```
                    ┌─────────────────────┐
                    │     Orchestrator    │
                    │   (agent/orchestr.） │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
       │  Grammar    │ │  Target     │ │  Coverage   │
       │  Analyzer   │ │  Analyzer   │ │  Analyzer   │
       └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
              └────────────────┼────────────────┘
                               ▼
                      ┌─────────────────┐
                      │  Strategy       │
                      │  Planner (LLM)  │
                      └────────┬────────┘
                               │
                               ▼ JSON spec
                      ┌─────────────────┐
                      │  Deterministic  │
                      │  Generator      │
                      │ (generator/)    │
                      └────────┬────────┘
                               │
                               ▼ Hypothesis strategy
                      ┌─────────────────┐
                      │  Fuzzing Engine │
                      │  (sandboxed)    │
                      └────────┬────────┘
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
                 Coverage    Crash      Timeout
                 Collector  Detector   Detector
                    │          │          │
                    └──────────┼──────────┘
                               ▼
                         ┌─────────────┐
                         │  Triage     │
                         │ (triage/)   │
                         └─────────────┘
```

## What is a Deterministic Generator?

A deterministic generator is a fixed, auditable Python module that converts
a structured strategy specification (JSON) into a Hypothesis search strategy.

### Why use one?

| LLM-generated code | Deterministic generator |
|-------------------|------------------------|
| LLM writes Python | LLM writes JSON spec |
| Risk of hallucinated API | No code execution risk |
| Hard to debug | Easy to unit test |
| Depends on LLM being correct | Generator is fixed, tested |

### How it works:

```
LLM output (JSON)          Generator              Hypothesis Strategy
┌─────────────────┐        ┌──────────────────┐    ┌──────────────┐
│ {              │        │                  │    │              │
│   "objectives": │───────▶│ compile_strategy │───▶│ SearchStrategy│
│    [...],      │        │                  │    │  .example()  │
│   "constraints":│        │ • max_depth      │    │              │
│    [...],      │        │ • entity_whitelist│    │ produces:    │
│   "mutations":  │        │ • build_elements │    │  "<root/>"   │
│    [...]       │        │ • build_breaks   │    │  "<a><b/>"   │
│ }              │        │                  │    │  ...         │
└─────────────────┘        └──────────────────┘    └─────────────┘
```

The generator is a pure function: same input spec → same strategy → same inputs.
This makes the system **reproducible** and **debuggable**.

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
| `GROQ_MODEL` | Model to use (auto-selects if empty) | `llama-3.3-70b-versatile` |
| `MAX_ITERATIONS` | Loop iterations | `5` |
| `NUM_EXAMPLES` | Examples per iteration | `200` |
| `WALL_CLOCK_CAP` | Time limit (seconds) | `600` |
| `COST_BUDGET` | LLM cost budget (USD) | `5.0` |
| `HARNESS_TIMEOUT` | Per-input timeout (seconds) | `5` |
| `COVERAGE_ENABLED` | Enable coverage collection | `true` |

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

1. **No LLM-generated code execution** — The LLM only produces JSON; the generator is fixed.
2. **Groq-only** — Simplifies configuration, removes fallback complexity.
3. **Explicit pipeline states** — Failures are visible, not hidden.
4. **Structured crash reporting** — Exit code, signal, stderr captured separately.
5. **Harness bug fix** — `ferror()` checked before `fclose()` to avoid use-after-close.
6. **Real grammar reference** — All rules in `grammar/GRAMMAR_RULES.md` for LLM context.
7. **Deterministic generator** — Safe, auditable, testable Python module.

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
├── generator/                     # Strategy spec + deterministic generator
│   ├── __init__.py
│   ├── strategy_spec.py           # Pydantic model
│   └── deterministic_generator.py # JSON → Hypothesis compiler
├── coverage/                      # Coverage collection
│   ├── __init__.py
│   └── collector.py
├── engine/                        # Fuzzing execution engine
│   └── __init__.py
├── fuzzer/                        # Baseline + legacy wrapper
│   ├── __init__.py
│   ├── __main__.py
│   ├── baseline_strategy.py
│   └── run_harness.py
├── harness/                       # C harness (bug fixed)
│   ├── mxml_harness.c
│   ├── Makefile
│   └── sample_tests/
├── grammar/                       # Grammar reference
│   ├── original/
│   │   ├── XMLLexer.g4
│   │   └── XMLParser.g4
│   ├── ADAPTATIONS.md
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

### "Strategy parsing failed"

Check the LLM response in `fuzzer/logs/loop_summary.md`. The LLM may have
returned non-JSON text. Try again or adjust the prompt.

### Rate limiting

If you hit rate limits, wait a few minutes and retry. The system includes
automatic rate-limit detection and will report `LLM_UNAVAILABLE` state.

## License

MIT
