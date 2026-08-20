# Kaggle Notebook (Open-Source LLM Edition)

A single-file, self-contained Kaggle notebook that runs the **full
Agentic-Fuzzing** pipeline using an **open-source model** (HuggingFace Hub **or**
a Kaggle Model) instead of the Groq API.

## Files

| File | Purpose |
|------|---------|
| `../kaggle_notebook.ipynb` | The deliverable notebook (repo root). |
| `llm_client_hf.py` | Open-source `LLMClient` (HF Transformers); the notebook writes it over `agent/llm_client.py` via a `%%writefile` cell. |
| `build_notebook.py` | Generator that rebuilds the notebook from the cells + `llm_client_hf.py`. Re-run after editing either. |

## MXML dependency
The notebook includes a cell that clones the `mxml` library and checks out a specific commit (`e6824d899d949387fb0156af6f4101373b9be519`) to ensure consistent fuzzing behavior.

`agent/orchestrator.py` only talks to the LLM through this interface:

    LLMClient(model=None).is_available() -> bool
    LLMClient(model=None).chat(messages, timeout=120.0) -> str

The repo ships a **Groq-only** client at `agent/llm_client.py`. The notebook's
`%%writefile` cell overwrites that file with `llm_client_hf.py`, which implements
the *same* interface using `transformers` + your model. The orchestrator therefore
runs **unchanged**; only the cosmetic `llm_provider` label is patched
(`groq` -> `local-llm`).

## Model sources (Configuration cell)

Edit the **Configuration** cell and set `MODEL_SOURCE`:

- `"hf"` (default) -> download `MODEL_NAME` from the HuggingFace Hub.
  `MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"` (GPU) or
  `"Qwen/Qwen2.5-1.5B-Instruct"` (CPU).
- `"kaggle_input"` -> use a Kaggle Model you attach via
  **Settings -> Source -> Add model**. Set `KAGGLE_MODEL_REF` to its local
  directory (the one holding `config.json`), e.g.
  `/kaggle/input/qwen-2-5-7b-instruct`. No download needed (works Internet OFF).
- `"kaggle_kagglehub"` -> fetch via the `kagglehub` library; set
  `KAGGLE_MODEL_REF = "owner/model-slug"` (requires Kaggle credentials).

In every case the resolved value is passed to `from_pretrained()`, which
accepts either a Hub repo id or a local directory path.

## Running on Kaggle

1. Upload `kaggle_notebook.ipynb` to Kaggle Kernels and open it.
2. Settings -> Accelerator -> **GPU T4** (recommended; needed for 7 B models).
3. Settings -> toggle **Internet** ON (needed for the `hf` source and `git clone`;
   turn it OFF if you use `kaggle_input`).
4. Run all cells top-to-bottom (edit only the Configuration cell).

Cell map: (1) install deps incl. `kagglehub`, (2) configure, (3) clone repo +
build the ASan/UBSan C harness, (4) inject the open-source client, (5) patch the
provider label, (6) smoke-test the model, (7) run the full pipeline, (8) inspect
results, (9) **archive artifacts to Output**.

## Robustness

- The model is loaded lazily on the first `chat()` call and cached in a
  module-level singleton, so it loads **once** per run (the smoke-test cell
  pre-loads it).
- Too big for GPU memory -> auto-retry on CPU with offloading.
- If loading/generation ever fails, `chat()` raises and the orchestrator falls
  back to the bundled `fuzzer/fallback_strategy.py`, so the loop always keeps
  running.
- No per-token cost with a local model, so `COST_BUDGET` is set high to disable
  the cost-based early-stop gate.

## Saving artifacts

The final cell copies `fuzzer/strategies/iteration_*.py`,
`fuzzer/logs/iteration_*.jsonl`, `fuzzer/logs/loop_summary.md`, and
`triage/crashes/<signature>/` into
`/kaggle/working/output/agentic_fuzzing_run/` so they are preserved in the run's
**Output** tab (visible when you commit the kernel).
