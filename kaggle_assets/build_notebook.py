#!/usr/bin/env python3
"""build_notebook.py - assembles kaggle_notebook.ipynb.

Self-contained Kaggle notebook: clones the project, builds the ASan/UBSan C
harness, writes the open-source LLM client (kaggle_assets/llm_client_hf.py) over
agent/llm_client.py via %%writefile, patches the cosmetic provider label, then
runs the full Agentic-Fuzzing pipeline with an open-source model.

Model sources (see the Configuration cell):
  "hf"               -> HuggingFace Hub repo id (MODEL_NAME)
  "kaggle_input"     -> a Kaggle Model attached as input (/kaggle/input/... dir)
  "kaggle_kagglehub" -> download via the kagglehub library (owner/model/version)
"""
import nbformat as nbf
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSET_CLIENT = ROOT / "kaggle_assets" / "llm_client_hf.py"
OUT = ROOT / "kaggle_notebook.ipynb"
PROJECT = "/kaggle/working/Agentic-Fuzzing"
WFILE = PROJECT + "/agent/llm_client.py"

cells = []
def md(text):
    cells.append(("md", text))
def code(text):
    cells.append(("code", text))

md(r'''# Agentic-Fuzzing -- Kaggle Notebook (Open-Source LLM Edition)

Runs the **full Agentic-Fuzzing** pipeline on Kaggle using an **open-source model**
(HuggingFace Hub **or** a Kaggle Model) instead of the Groq API:

> LLM (open-source) -> Hypothesis XML strategy -> C harness (ASan/UBSan) -> crash triage

| Pipeline stage | What happens |
|---|---|
| LLM (open-source) | Writes a `hypothesis` XML-generating strategy |
| `generator/` | AST-validates the strategy, then live-loads it |
| C harness `mxml_harness` | Parses each XML under ASan/UBSan, classifies exit code |
| Refine loop | Feeds acceptance-rate + crash signatures back to the LLM |
| `triage/` | Deduplicates, minimizes & verifies any crashes found |

### Before you run (important)
1. **Settings -> Accelerator -> GPU T4 (or A10G)** -- best quality for 7 B models.
   No GPU? Keep `MODEL_SOURCE = "hf"` and set `MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct"`
   (slower, but runs on CPU).
2. **Settings -> toggle "Internet" ON** -- needed to clone the repo and (for the
   `hf` source) download weights. For `kaggle_input` (an attached Kaggle Model)
   you can turn Internet OFF.

Run every cell **top-to-bottom**. Only the **Configuration** cell needs editing.
''')

code(r'''import sys, subprocess

def _need(pkg, mod):
    try:
        __import__(mod); return False
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
        return True

for pkg, mod in [
    ("hypothesis", "hypothesis"),
    ("httpx", "httpx"),
    ("python-dotenv", "dotenv"),
    ("transformers", "transformers"),
    ("torch", "torch"),
    ("huggingface_hub", "huggingface_hub"),
    ("kagglehub", "kagglehub"),
]:
    print(("installed" if _need(pkg, mod) else "ok").ljust(9), pkg)

import torch
print("torch", torch.__version__, "| cuda:", torch.cuda.is_available())
''')

md(r'''### Configuration  (edit THIS cell)

Pick the model source and the fuzzing-loop parameters.

- `MODEL_SOURCE = "hf"` -> download `MODEL_NAME` from the HuggingFace Hub
  (non-gated models work on Kaggle).
- `MODEL_SOURCE = "kaggle_input"` -> read a Kaggle Model you attached via
  **Settings -> Source -> Add model**; paste its local directory (the one
  containing `config.json`) into `KAGGLE_MODEL_REF`, e.g.
  `/kaggle/input/qwen-2-5-7b-instruct`.
- `MODEL_SOURCE = "kaggle_kagglehub"` -> fetch via the `kagglehub` library from
  `KAGGLE_MODEL_REF = "owner/model-slug"` (requires Kaggle credentials).

Sensible defaults are provided; everything else is optional to change.
''')

code(r'''import os

# Fixed project location (the notebook clones here; keep this path).
PROJECT = "/kaggle/working/Agentic-Fuzzing"
REPO    = "https://github.com/Faseeh24/Agentic-Fuzzing.git"

# ------------------------------------------------------------------
# EDIT THESE VALUES TO CONFIGURE YOUR RUN
# ------------------------------------------------------------------
# Source of the model: "hf" (Hub id) | "kaggle_input" (attached local dir) |
# "kaggle_kagglehub" ("owner/model/version").
MODEL_SOURCE = "hf"

# Source A: HuggingFace Hub repo id. Non-gated models work on Kaggle.
#   "Qwen/Qwen2.5-7B-Instruct"            <- default (best quality, GPU)
#   "mistralai/Mistral-7B-Instruct-v0.3"
#   "Qwen/Qwen2.5-1.5B-Instruct"          <- fast / runs on CPU
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

# Source B/C: Kaggle Model reference (only used if MODEL_SOURCE != "hf").
#   kaggle_input    -> local dir with config.json, e.g. /kaggle/input/qwen-2-5-7b-instruct
#   kaggle_kagglehub -> "owner/model-slug" or "owner/model-slug/version"
KAGGLE_MODEL_REF = ""

# Fuzzing-loop parameters (the LLM makes one strategy call per iteration)
MAX_ITERATIONS = 3     # seed + refine cycles
NUM_EXAMPLES   = 100   # XML inputs generated & fuzzed per iteration
WALL_CLOCK_CAP = 1800  # seconds, overall safety back-stop
# With a local model there is no per-token cost, so this disables the
# cost-based early-stop gate inside the orchestrator.
COST_BUDGET    = 1e9
# ------------------------------------------------------------------

# Resolve model source -> a value from_pretrained() accepts (Hub id OR local dir).
# The client loads lazily on the first chat() and caches the model singleton.
if MODEL_SOURCE == "hf":
    os.environ["HF_MODEL_NAME"] = MODEL_NAME
elif MODEL_SOURCE == "kaggle_input":
    assert KAGGLE_MODEL_REF, "set KAGGLE_MODEL_REF to the /kaggle/input/... dir"
    os.environ["HF_MODEL_NAME"] = KAGGLE_MODEL_REF
elif MODEL_SOURCE == "kaggle_kagglehub":
    import kagglehub
    os.environ["HF_MODEL_NAME"] = kagglehub.model_download(KAGGLE_MODEL_REF)
else:
    raise SystemExit("MODEL_SOURCE must be 'hf' | 'kaggle_input' | 'kaggle_kagglehub'")

os.environ.setdefault("PYTHONPATH", PROJECT)

print("MODEL SOURCE:", MODEL_SOURCE)
print("MODEL PATH  :", os.environ["HF_MODEL_NAME"])
print("Loop  : iterations=%d  examples/iter=%d  wall_cap=%ds" %
      (MAX_ITERATIONS, NUM_EXAMPLES, int(WALL_CLOCK_CAP)))
''')

md(r'''### Clone the repo & build the ASan/UBSan C harness

Compiles the vendored Mini-XML library + `harness/mxml_harness.c` with
AddressSanitizer + UndefinedBehaviorSanitizer (same `Makefile` as the repo).
''')

code(r'''import os, subprocess, shutil

if not os.path.isdir(os.path.join(PROJECT, ".git")):
    subprocess.run(["git", "clone", "--depth", "1", REPO, PROJECT], check=True)
else:
    subprocess.run(["git", "-C", PROJECT, "pull"], check=False)
os.chdir(PROJECT)
os.environ["PYTHONPATH"] = PROJECT
print("Repo ready at", PROJECT)

# Ensure build tools are present (Kaggle ships these; install as fallback).
for tool in ("make", "gcc"):
    if not shutil.which(tool):
        subprocess.run(["apt-get", "update"], check=False)
        subprocess.run(["apt-get", "install", "-y", "build-essential"], check=False)

# Compile mxml + harness with -fsanitize=address,undefined
r = subprocess.run(["make", "-C", "harness", "all"], capture_output=True, text=True)
if r.returncode != 0:
    print((r.stderr or "")[-2500:])
    raise SystemExit("Harness build FAILED - see output above.")
print((r.stdout or "").strip().splitlines()[-1] if (r.stdout or "").strip() else "built")
assert os.path.exists("harness/mxml_harness"), "mxml_harness binary missing!"
print("Harness built ->", os.path.abspath("harness/mxml_harness"))
''')

md(r'''### Use an open-source LLM (swap out the Groq client)

The next cell writes a local HuggingFace Transformers `LLMClient` over the
repo's `agent/llm_client.py`. It exposes the *same interface*
(`LLMClient(model=None)`, `.is_available()`, `.chat(messages, timeout)`), so
`agent/orchestrator.py` runs **unchanged**. The model comes from `HF_MODEL_NAME`
(resolved in the Configuration cell above).

Then run the patch cell and the smoke-test cell.
''')

client_text = ASSET_CLIENT.read_text(encoding="utf-8")
c_client = "%%writefile " + WFILE + "\n" + client_text + "\n"
code(c_client)

md(r'''### Patch the cosmetic provider label

Relabels the `"groq"` provider tag in `agent/orchestrator.py` to `"local-llm"`
so the run summary is accurate. (Orchestrator LOGIC is not touched.)
''')

code(r'''import os
op = os.path.join(PROJECT, "agent", "orchestrator.py")
src = open(op, encoding="utf-8").read()
patches = [
    ('llm_provider = "groq"', 'llm_provider = "local-llm"'),
    ("mxml (Groq)", "mxml (Local LLM)"),
    ("Groq API key not set. Set GROQ_API_KEY in .env", "open-source model unavailable"),
]
for old, new in patches:
    assert old in src, "pattern not found: " + repr(old)
    src = src.replace(old, new)
open(op, "w", encoding="utf-8").write(src)
print("Patched agent/orchestrator.py -> provider='local-llm'")
''')

md(r'''### Pre-load the model & smoke test

Downloads (first run only) and loads the model, then asks it for a tiny code
snippet. This gives fast feedback that the LLM backend works before the full
pipeline. The loaded model is cached (`_CACHE`) and reused by the pipeline cell.
''')

code(r'''import os, sys
os.environ.setdefault("HF_MODEL_NAME", MODEL_NAME)
sys.path.insert(0, PROJECT)

print("Loading model from:", os.environ["HF_MODEL_NAME"])

from agent.llm_client import LLMClient

client = LLMClient()
print("LLM backend:", type(client).__module__ + "." + type(client).__name__,
      "-> model:", client._model_name)
print("is_available:", client.is_available())

resp = client.chat([
    {"role": "system", "content": "You are a terse assistant. Reply with ONLY a python code snippet, no prose."},
    {"role": "user",   "content": "Write a one-line python snippet that prints the number 42."},
], timeout=120)

print("---- model reply ----")
print(resp.strip())
looks_code = "print" in resp.lower() and "42" in resp
if resp.strip() and looks_code:
    print("Smoke test passed - model responds with code.")
else:
    print("WARNING - no code detected; full pipeline will still run (the")
    print("built-in validator + fallback strategy keep things safe).")
''')

md(r'''### Run the full pipeline

Seeds an XML strategy from the LLM, AST-validates + live-loads it, fuzzes it
through the ASan/UBSan harness, refines using acceptance-rate + crash
signatures, and finally runs crash triage (dedupe / minimize / verify).
''')

code(r'''import os, sys
os.environ.setdefault("HF_MODEL_NAME", MODEL_NAME)
os.environ["PYTHONPATH"] = PROJECT
sys.path.insert(0, PROJECT)

from agent.orchestrator import run_orchestrator

result = run_orchestrator(
    max_iterations=MAX_ITERATIONS,
    num_examples=NUM_EXAMPLES,
    wall_clock_cap=WALL_CLOCK_CAP,
    cost_budget=COST_BUDGET,
    run_triage=True,
)

print("\n======== PIPELINE RESULT ========")
for k, v in result.items():
    print(f"  {k}: {v}")
''')

md(r'''### Results & artifacts

Inspect generated strategies, per-iteration classification logs, and any crash
reproducers under `triage/crashes/<signature>/`.
''')

code(r'''import json
from pathlib import Path

root = Path(PROJECT)

summ = root / "fuzzer" / "logs" / "loop_summary.md"
if summ.exists():
    print("loop_summary.md:")
    print(summ.read_text())

print("\nstrategy files:")
for f in sorted((root / "fuzzer/strategies").glob("iteration_*.py")):
    print(f"  {f.name}  ({f.stat().st_size} bytes)")

print("\niteration logs:")
for f in sorted((root / "fuzzer/logs").glob("iteration_*.jsonl")):
    rec = json.loads(f.read_text(encoding="utf-8").splitlines()[0])
    r = rec["results"]
    print(f"  {f.name}: total={r['total']} accept={r['acceptance_rate']:.0%} "
          f"sanitizer={r['sanitizer']} timeout={r['timeout']} bug_crash={r['bug_crash']}")

print("\ntriage (crashes):")
cd = root / "triage" / "crashes"
if cd.exists() and any(cd.iterdir()):
    for d in sorted(cd.iterdir()):
        if not d.is_dir():
            continue
        repro = "reproducer_minimized.xml" if (d / "reproducer_minimized.xml").exists() else "reproducer.xml"
        print(f"  {d.name} -> {repro}")
        rep = d / repro
        if rep.exists():
            print("    input:", repr(rep.read_text(encoding="utf-8")[:120]))
        sr = d / "sanitizer_report.txt"
        if sr.exists():
            print("    stderr:", sr.read_text(encoding="utf-8")[:300])
else:
    print("  (no crashes found - nothing to triage)")
''')

md(r'''### Save artifacts to Output

Kaggle preserves files under `/kaggle/working/` when you **commit** the run.
To make the generated strategies, per-iteration logs and crash reproducers easy
to recover, this cell copies them into
`/kaggle/working/output/agentic_fuzzing_run/` (shown in the run's Output tab).
''')

code('''import shutil
from pathlib import Path

out_root = Path("/kaggle/working/output/agentic_fuzzing_run")
out_root.mkdir(parents=True, exist_ok=True)
root = Path(PROJECT)

copied = []
for src_sub, dst_name in [
    ("fuzzer/strategies", "strategies"),
    ("fuzzer/logs", "logs"),
    ("triage/crashes", "triage_crashes"),
]:
    src = root / src_sub
    dst = out_root / dst_name
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        copied.append(dst_name)

ls = root / "fuzzer" / "logs" / "loop_summary.md"
if ls.exists():
    shutil.copy2(ls, out_root / "loop_summary.md")

print("Saved artifacts to", out_root)
for name in copied:
    d = out_root / name
    print(" ", name, "/", len(list(d.rglob("*"))), "entries")
for p in sorted(out_root.rglob("*")):
    if p.is_file():
        print("  ", p.relative_to(out_root), f"({p.stat().st_size} bytes)")
''')

md(r'''### Done

- To re-run with a different model: edit the **Configuration** cell (the
  `MODEL_SOURCE` / `MODEL_NAME` / `KAGGLE_MODEL_REF` line), then
  **Runtime -> Restart and run all** (or run from the smoke-test cell onward).
- Generated strategies: `fuzzer/strategies/iteration_*.py`
- Per-example logs (incl. real ASan/UBSan stderr): `fuzzer/logs/iteration_*.jsonl`
- Confirmed crash reproducers: `triage/crashes/<signature>/`
- Archived copy (strategies + logs + crashes + summary) saved to
  `/kaggle/working/output/agentic_fuzzing_run/`
''')

nb = nbf.v4.new_notebook()
for src, kind in cells:
    if src == "md":
        nb["cells"].append(nbf.v4.new_markdown_cell(kind))
 
    else:
        nb["cells"].append(nbf.v4.new_code_cell(kind))

nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.10"},
}
nb["nbformat"] = 4
nb["nbformat_minor"] = 5

nbf.write(nb, str(OUT))
print("Wrote", OUT, "with", len(cells), "cells")
