# Setup — running this submission

Two paths, depending on what you're doing:

- **[Path A](#path-a-the-graded-artifact)** — reproduce exactly what ADTC's automated profiler measures (the raw model via `llama-bench`). This is all the automated scoring actually touches.
- **[Path B](#path-b-the-full-hestiahealth-demo)** — run MAKO's actual orchestrator and the HestiaHealth clinical console against the local model, the way the [video](REPORT.md) demonstrates it. Not required for scoring, but it's what backs every claim in [`REPORT.md`](REPORT.md).

Both paths share the same downloaded model file, so do the download once.

---

## Prerequisites

| Tool | Why | Install |
|---|---|---|
| `llama.cpp` (`llama-bench`, `llama-server`) | Required runtime — the only one ADTC's evaluation accepts | macOS: `brew install llama.cpp`. Ubuntu (matches the ADTC Standard Laptop): build from source — see [llama.cpp's build guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md) |
| Python 3.10+ | For the profiler and (3.11+ recommended) for MAKO's orchestrator | Check with `python3 --version`; use `uv` or `venv` for isolated environments (this repo used `uv`) |
| `curl` or `wget` | Model download | Preinstalled on macOS/Ubuntu |

Confirm `llama-bench` and `llama-server` are on your `PATH` before continuing:

```bash
llama-bench --help > /dev/null && echo "llama-bench OK"
llama-server --help > /dev/null && echo "llama-server OK"
```

---

## Download the model (needed for both paths)

```bash
bash download_model.sh
```

Idempotent — safe to re-run. Downloads `model/qwen2.5-3b-instruct-q4_k_m.gguf` (~1.9GB) from the official Qwen GGUF release on Hugging Face, no credentials needed, and verifies the download against the server's `Content-Length` before accepting it (a truncated download otherwise fails much later, inside `llama.cpp`, with an opaque error).

---

## Path A — the graded artifact

This is what ADTC's automated profiler actually measures: the raw model via `llama-bench`, nothing else. Reproduce it with the official profiler tool:

```bash
python3 -m venv .venv && source .venv/bin/activate    # or: uv venv .venv
pip install "git+https://github.com/Africa-Deep-Tech-Foundation/adtc-profiler.git"

adtc-profiler run --submission . --mode participant --output submission.json --skip-accuracy
cat submission.json | python3 -m json.tool
```

`--skip-accuracy` is for a fast local smoke test (skips the `lm-eval` stage). A valid run produces `submission.json` with `"measured_on": "participant_laptop"`, throughput (`tokens_per_second_generation`), and memory (`peak_rss_mb`) — the numbers `REPORT.md`'s benchmark table quotes.

---

## Path B — the full HestiaHealth demo

This is everything `mako/` and `mako/webui/` do: MAKO's real orchestrator, and the clinical console / knowledge-graph explorer on top of it, all running against the local model started in step 1 below.

### 1. Start the local model server

```bash
llama-server -m model/qwen2.5-3b-instruct-q4_k_m.gguf --port 8811 -t 4 -c 4096
```

Leave this running — it's llama.cpp's OpenAI-compatible HTTP server. Everything below talks to `http://localhost:8811/v1`, already configured in `mako/.env` (no API keys — it's a local, unauthenticated endpoint).

### 2. Set up MAKO's orchestrator

In a second terminal:

```bash
cd mako
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # or: uv venv --python 3.11 .venv && uv pip install -r requirements.txt
```

Run one hop-decision session from the command line:

```bash
.venv/bin/python -m orchestrator.run \
  "A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement" \
  --json-only
```

Completes in a few seconds, fully offline — see [`mako-integration/README.md`](mako-integration/README.md) for what a real run looks like and why this matters (it's proof MAKO's actual code runs against this submission's model, not a description of it).

### 3. Run the clinical console + knowledge graph explorer

```bash
cd mako   # if not already there
.venv/bin/pip install -r webui/backend/requirements.txt   # fastapi + uvicorn
.venv/bin/uvicorn webui.backend.main:app --port 8001
```

Open **http://localhost:8001/** — the clinical routing console (submit a patient case, watch it route live, pause/continue with more information). Open **http://localhost:8001/graph.html** for the knowledge-graph explorer (12 domains, 71 agents, 135 handoffs). See [`mako/webui/README.md`](mako/webui/README.md) for what each view does.

---

## Troubleshooting

- **`llama-bench`/`llama-server` not found** — not installed, or not on `PATH`. Re-check the Prerequisites step.
- **`ModuleNotFoundError` running the orchestrator or webui** — you're using the wrong venv, or forgot to install `webui/backend/requirements.txt` separately (it's on top of `mako/requirements.txt`, not a replacement for it).
- **Orchestrator raises instead of running** — `v3-langraph` (what `mako/` vendors) has no offline/mock LLM path by design; it needs `llama-server` actually running and reachable at the URL in `mako/.env`. Confirm with `curl http://localhost:8811/health`.
- **Port already in use** — something else is already on `8811` or `8001`; stop it or change the port in the relevant command and `mako/.env`'s `KG_BASE_URL`.
