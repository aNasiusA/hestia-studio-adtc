# Devpost submission draft — for review before entering into the form

## Project overview

**Project name:** HestiaHealth

**Elevator pitch** (≤200 chars, currently 195):
> A knowledge-graph multi-agent clinical orchestrator, powered by a local Qwen2.5-3B model via llama.cpp — routes patient cases between specialist agents fully offline, on an 8GB budget laptop.

---

## Project details

### Story (Markdown, public page)

## Inspiration

Cloud-hosted LLMs require API fees, stable fiber, and sustained electricity — three things that are unreliable or unaffordable in many African clinics. MAKO, my final-year engineering project, is a knowledge-graph-based multi-agent orchestrator: agents, their capabilities, the tools they own, and the handoffs between them all live in an RDF/Turtle knowledge graph, and the execution sequence is *inferred* from the graph at runtime rather than hard-coded. Its most advanced routing mode, `v3-langraph`, is genuinely autonomous — a ReAct-style LLM orchestrator decides the next hop one step at a time, querying the graph for valid transitions and validating each decision before committing to it. Demoed on a 71-agent healthcare knowledge graph (Cardiology, Emergency Medicine, Oncology, Neurology, Orthopedics, Lab/Pathology), every one of those hop decisions currently needs a cloud LLM call. HestiaHealth is what happens when that call becomes local.

## What it does

HestiaHealth runs MAKO's hop-by-hop clinical routing decisions entirely offline. Given a patient case and the set of specialist agents available at that point in the graph, a local Qwen2.5-3B-Instruct model (GGUF, Q4_K_M quantization) — running through llama.cpp, no GPU, no internet — decides which agent should act next and justifies the decision, the same way MAKO's orchestrator would query a cloud LLM to do today. It runs comfortably within an 8GB RAM / integrated-graphics-only laptop profile.

## How we built it

- Started from MAKO's existing `v3-langraph` orchestrator (LangGraph `StateGraph` governing one hop decision at a time, with an action-masking gate so a `commit` is only accepted immediately after a `validate_decision` success for that exact agent).
- Selected Qwen2.5-3B-Instruct as the base model — small enough to leave real headroom under the 7GB memory budget, strong enough at structured/constrained output to reliably produce a parseable "next agent + justification" decision.
- Quantized to GGUF Q4_K_M (~2GB) — the standard balance point between output quality and memory footprint.
- Wired the model into llama.cpp (the only runtime ADTC's evaluation framework accepts — no Ollama, no llama-cpp-python server wrapper for the graded path) and validated it against MAKO's real orchestrator via llama.cpp's OpenAI-compatible `llama-server`.
- Benchmarked with the official `adtc-profiler` tool, which drives `llama-bench` directly: **30.33 tok/s generation, 3.84GB peak RSS, no thermal throttling**, schema-valid submission report.

## Challenges we ran into

- ADTC's evaluation framework mandates llama.cpp + GGUF exclusively — no Ollama, despite MAKO's existing provider abstraction supporting it as a first-class backend. Had to re-validate the whole local-inference path against llama.cpp specifically.
- A truncated model download (1.79GB instead of the expected 2.10GB) initially produced a "tensor data not within file bounds" error from llama.cpp — a silent `curl | tail` pipeline had swallowed the real exit code. Caught by comparing the downloaded file size against the `Content-Length` header before trusting the file.
- Sizing the model against the 7GB RAM budget while keeping enough capability for structured decision-making meant explicitly rejecting both a 7B-class model (too much RAM pressure once KV cache and orchestrator overhead are added) and a sub-1.5B model (unreliable at holding the required output structure).

## What we learned

The actual graded artifact in this challenge is narrower than the multi-agent system around it — ADTC's profiler benchmarks the raw GGUF model directly via `llama-bench`, not custom application code. The real leverage is in picking and sizing the right base model for MAKO's specific decision-making shape (short, structured, single-decision prompts) rather than trying to move the whole orchestrator on-device.

## What's next

Expanding past the healthcare domain to MAKO's other knowledge graphs (legal, and eventually the full multi-domain graph), and moving from the Q4_K_M single-model setup to a routing-aware benchmark across several small local models to see which is most reliable specifically on hop-decision-shaped prompts.

---

**Built with:** `llama.cpp`, `GGUF`, `Qwen2.5-3B-Instruct`, `Python`, `RDF/Turtle`, `rdflib`, `LangGraph`, `LangSmith`, `Knowledge Graph`, `ReAct`, `Homebrew`, `Hugging Face`, `Ubuntu`, `macOS`

**Try it out links:**
- https://github.com/aNasiusA/hestia-studio-adtc

**Video demo link:** *(pending — need to record)*

---

## Additional info (for judges)

**Project Report Public URL on GitHub:**
https://github.com/aNasiusA/hestia-studio-adtc/blob/main/REPORT.md

**Test Prompt 1:**
You are the orchestration agent for a multi-agent clinical system with no internet access. Current case: a 54-year-old patient presents with chest pain; the Cardiology Triage agent has just finished its assessment and flagged possible cardiac involvement. Available next agents and what they handle: Cardiology_ECGInterpretation (reads and interprets ECG traces), Cardiology_EchoAnalysis (interprets echocardiograms), Cardiology_TreatmentPlanning (builds a cardiac treatment plan; requires ECG and echo results first), Cardiology_StressTestAnalysis (interprets stress test results). Decide which single agent should act next, name it exactly, and give a one-sentence clinical justification for why it comes before the others.

**Test Prompt 2:**
You are an autonomous routing agent in a clinical multi-agent system. A patient case has just received an EEG interpretation (Neurology_EEGInterpretation) showing abnormal results consistent with a possible stroke. Two candidate next agents are available: Neurology_StrokeAssessment (performs focused stroke workup) and Neurology_TreatmentPlanning (builds a general neurological treatment plan). State which agent should handle the case next and justify your decision in one sentence, explicitly noting what would go wrong clinically if the agents were run in the opposite order.

**Select Problem Domain:** Autonomous AI Agents

**Self Reported Profiler Performance Score (Sperf):** 100.0
*(min(30.33 / 15.0, 1.0) × 100 — capped at max)*

**Self Reported Profiler Efficiency Score (Seff):** 45.2
*(max(0, (7.0 − 3.835) / 7.0) × 100)*
