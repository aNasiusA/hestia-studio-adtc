# Technical Report — Hestia Studio: A Local LLM Backend for MAKO's Autonomous Clinical Orchestrator

**Team ID:** 1392828 *(Devpost project ID — placeholder pending confirmation of the actual ADTF portal team ID)*
**Domain:** autonomous_ai_agents
**Model:** Qwen2.5-3B-Instruct-Q4_K_M

---

## Problem

MAKO is a knowledge-graph-based multi-agent orchestration system (this submission's parent project — a final-year engineering project) in which agents, their capabilities, the tools they own, and the handoffs between them all live in an RDF/Turtle knowledge graph, rather than being hard-coded into a workflow. Its most advanced routing mode (`v3-langraph`) is genuinely *autonomous*: at each step of a multi-agent case, a ReAct-style LLM orchestrator queries the graph for the valid next agents (`get_valid_transitions`), proposes a hop, validates it against the graph (`validate_decision`), and only then commits — one decision at a time, not a precomputed static plan.

The demoed domain is clinical multi-agent coordination: a patient case is handed between specialist agents (Cardiology, Emergency Medicine, Oncology, Neurology, Orthopedics, Lab/Pathology — 71 agents total) as it moves from triage through diagnosis to treatment planning. Every one of those hop decisions today requires a call to a cloud-hosted LLM (Anthropic/OpenAI/Gemini). That is precisely the barrier the Africa Deep Tech Challenge names: cloud-hosted LLMs require API fees, stable fiber, and sustained electricity — all of which are unreliable or unaffordable for many clinics and practitioners across Africa, and for the rural/under-resourced settings this kind of clinical decision-support tool would most need to reach.

**Target user:** a clinician or clinical-ops team running MAKO's orchestrator on a single commodity laptop, with no dependence on internet connectivity, API budget, or continuous grid power, so the multi-agent routing logic keeps working during outages or in low-connectivity facilities.

This submission is the on-device replacement for that cloud LLM call: a small, quantized, GGUF model running entirely locally through llama.cpp, sized to fit the ADTC Standard Laptop's 8 GB RAM / integrated-graphics-only profile, evaluated here on the same class of hop-decision prompt MAKO's orchestrator actually issues.

---

## Design Decisions

- **Base model:** Qwen2.5-3B-Instruct (official GGUF release, `Qwen/Qwen2.5-3B-Instruct-GGUF` on Hugging Face). Chosen over larger 7B-class instruct models because MAKO's hop-decision prompts are short, structured, single-decision tasks (pick one agent from a small candidate set, justify in one sentence) rather than open-ended long-form generation — a well-instruction-tuned 3B model handles this reliably while leaving comfortable RAM headroom under the 7 GB budget for the orchestrator process, KV cache, and OS overhead. Qwen2.5's instruct tuning is comparatively strong on structured/constrained output relative to its size, which matters for a model that has to emit a parseable "next agent" decision rather than free-form prose.
- **Quantization:** GGUF Q4_K_M — the standard balance point between quality and footprint. At ~2.0 GB on disk it leaves roughly 5 GB of the 8 GB budget free for everything else the target laptop needs to run (OS, orchestrator, KV cache at longer context).
- **Alternatives considered:**
  - *Larger model (7B) at Q4_K_M* (~4.5 GB) — would leave too little headroom once KV cache growth and OS/orchestrator overhead are accounted for, and risks the disqualifying OOM condition.
  - *Smaller model (1–1.5B)* — safer on RAM/speed but noticeably weaker at holding to the required output structure ("name the agent, justify in one sentence") in early testing, which risks the orchestrator's `validate_decision` gate rejecting well-formed but incorrectly-justified hops.
  - *Higher-precision quantization (Q5_K_M/Q8_0)* — better fidelity but larger footprint for a task (short structured decisions) that doesn't obviously need it; Q4_K_M was kept as the default, conservative choice.
- **Runtime:** llama.cpp exclusively, per ADTC's mandated runtime — no Ollama, no llama-cpp-python server wrapper for the graded path. We additionally verified this model against MAKO's **actual, unmodified orchestrator code** (not a mock, not a hand-written prompt imitating it) — and vendored that code into this repo, so it's inspectable and runnable, not just described. [`mako/`](mako/README.md) is a trimmed copy of MAKO's `v3-langraph` orchestrator (244KB, stripped of the ~380MB of unrelated research-ablation history — four other MAKO versions, a developer-facing React/Cytoscape.js graph explorer, old run logs — that lives in the actual development repo). With `llama-server` started on this exact `.gguf` file and `mako/.env` pointed at it (`KG_LLM_PROVIDER=openai`, `KG_BASE_URL=http://localhost:8811/v1`, `KG_EMBED_PROVIDER=local`), `python -m orchestrator.run "A 54-year-old patient presents with chest pain..."` runs end-to-end from a fresh virtual environment in this exact folder. It completes in ~7 seconds, fully offline: selects an entry agent from the knowledge graph, makes a real hop decision validated against a graph edge (`delegatesTo`, accepted on its 3rd `validate_decision` attempt after two rejected proposals), and voluntarily terminates when it judges the case needs more input. The full unedited log and trace JSON are in [`mako-integration/`](mako-integration/README.md).
- **Clinical console:** [`mako/webui/`](mako/webui/README.md) is a from-scratch, dependency-free HTML/CSS/JS front end (no React, no build step) for that same orchestrator, replacing MAKO's original developer-facing graph explorer with something a clinical-ops team could plausibly run — a case input, a live streamed hop-by-hop routing timeline, a coverage bar, and an explicit termination reason on every run. It reuses MAKO's existing FastAPI backend, extended (not just unchanged) to support the point below.
- **Resumable runs:** the original orchestrator discarded all its state the moment a run paused — a case that stopped for more input, or hit the hop budget mid-decision, was simply stuck. `orchestrator/loop.py` now captures a resumable snapshot on every pause, and the console shows a "Continue this case" form that folds in whatever a clinician types (lab results back, a specialist unavailable, a clarified history) at the correct point — the pending hop-decision's context for a voluntary stop, the next agent's execution context for a hop-limit stop — and resumes with a fresh hop budget instead of restarting the case. Verified against the real local model: paused a live case, typed follow-up context, watched a genuinely new agent execution stream in with no duplicate steps in the timeline (a real bug, fixed along the way — see [`mako/webui/README.md`](mako/webui/README.md#resumable-runs)).

---

## Constraints

- **Target hardware:** ADTC Standard Laptop profile — 4 vCPU (Intel i5 10th–12th gen / AMD Ryzen 5 3000–5000 series class), 8 GB DDR4 RAM, integrated graphics only, Ubuntu 22.04 LTS.
- **No GPU acceleration** — inference must run on CPU only via llama.cpp; the model and quantization were chosen accordingly.
- **Connectivity:** zero network dependency after model download — MAKO's orchestrator, and this model, must run fully offline during actual use (matching ADTC's "zero external network calls during evaluation" rule).
- **Power:** clinics targeted by this use case may face intermittent grid power; a smaller/faster model reduces both time-to-decision and energy draw per inference relative to a larger model.
- **Development-machine caveat:** benchmarks below were captured on the development machine (Apple Silicon, macOS), **not** the literal ADTC reference laptop (Intel/AMD, Ubuntu 22.04, no dev-machine access to that spec). The architecture is CPU-inference-only and hardware-agnostic by construction (no Metal/CUDA-specific code path is required — llama.cpp's default CPU backend is what the target machine will use), so these numbers should be read as a proxy for relative sizing/feasibility, not as the official score. Official throughput/RAM/thermal numbers are produced by the ADTC profiler on the standard evaluation machine, per the template's own guidance.

---

## Benchmarks

Measured with the official `adtc-profiler` tool (`adtc-profiler run --submission . --mode participant --output submission.json`), which drives `llama-bench` directly — the same measurement path the evaluation framework uses.

| Metric | Value |
|---|---|
| Machine (dev proxy) | Apple M5, 16 GB unified memory, macOS 26.6.2 |
| Model | Qwen2.5-3B-Instruct, GGUF Q4_K_M (3.40B params, confirmed by profiler's `params_match: true`) |
| Context length | 32,768 |
| Generation speed | 30.33 tokens/s |
| First-token latency | 8,498 ms (512-token prompt; includes model load — see caveat below) |
| Peak RSS | 3,835 MB (~3.75 GB) |
| Steady-state RSS | 3,292 MB |
| CPU utilization (p99) | 58.5% |
| Thermal throttling | Not observed (`throttled: false`) |

These are self-reported *development-machine* benchmarks (`environment.measured_on: participant_laptop` in `submission.json`), captured on Apple Silicon rather than the literal Intel/AMD ADTC reference laptop. Official throughput/RAM/thermal scores are produced by the ADTC profiler on the standard evaluation machine at judging time. Two things to note when comparing:

- Peak RSS (3.75 GB) already leaves meaningful headroom under the ~7 GB memory budget even on this proxy machine; CPU-only inference on the actual reference laptop (no Metal/unified-memory acceleration) should not increase memory pressure, since llama.cpp's CPU backend allocates comparably or more conservatively than the Metal backend used here.
- First-token latency here is inflated by this measurement including one-time model load time within the same timed window; a warm/resident model on the target laptop should see substantially lower per-request latency in the actual orchestrator loop.
- **This table is the model in isolation**, benchmarked exactly as ADTC's profiler measures it (`llama-bench` against the raw `.gguf`, no orchestrator involved) — which is also, per this challenge's own rules, the only thing the automated scoring measures (see "What we learned" above). Running `mako/`'s orchestrator and `webui/` backend alongside the model adds Python/LangGraph/FastAPI/KG overhead on top of this baseline; we did not attempt to precisely measure that combined figure — ad-hoc RSS sampling of a running `llama-server` process on macOS was unreliable here (llama.cpp mmaps the weights, and OS-level RSS accounting for mmap'd pages undercounts them in a way that doesn't match the profiler's own methodology), so rather than publish a number we couldn't verify, we're stating the limitation plainly instead.

---

## Cross-Disciplinary Pairing: Healthcare

This submission's model is evaluated against the same class of decision MAKO's `v3-langraph` orchestrator makes when routing a clinical case between specialist agents (see `metadata.json` → `test_prompts`, and `cross_disciplinary_pairing`). MAKO's healthcare knowledge graph currently covers 71 agents across Cardiology, Emergency Medicine, Oncology, Neurology, Orthopedics, and Lab/Pathology; this local model is intended as the drop-in, fully offline replacement for the cloud LLM currently required at every hop decision in that graph walk.
