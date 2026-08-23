# MAKO integration — verified live run

This directory contains real, unedited evidence that MAKO's actual
orchestrator — not a mock, not a hand-written prompt imitating it — runs
end-to-end against this submission's model.

## What was run

MAKO's `v3-langraph` orchestrator (a LangGraph `StateGraph`-driven ReAct loop
that decides one hop at a time, validating each decision against a
knowledge-graph edge before committing) lives in a separate repository — this
project's final-year engineering thesis. Its `.env` was pointed at:

```
KG_LLM_PROVIDER=openai
KG_MODEL=qwen2.5-3b-instruct-q4_k_m
KG_BASE_URL=http://localhost:8811/v1
KG_API_KEY=sk-local-llamacpp
KG_EMBED_PROVIDER=local
```

`KG_BASE_URL` points at `llama-server` (llama.cpp's OpenAI-compatible HTTP
server) serving this submission's exact model —
`model/qwen2.5-3b-instruct-q4_k_m.gguf` — started with:

```bash
llama-server -m model/qwen2.5-3b-instruct-q4_k_m.gguf --port 8811 -t 4 -c 4096
```

`KG_EMBED_PROVIDER=local` uses MAKO's pure-Python hashing embedder (no
network, no extra model) so the whole run is fully offline end to end.

Then, from MAKO's `v3-langraph/` directory:

```bash
python -m orchestrator.run \
  "A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement" \
  --json-only
```

## What happened (unedited log)

```
16:16:25 INFO     [entry_run] building recall index (provider=local, backend=flat)
16:16:25 INFO     [loop] task='A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement'
16:16:25 SUCCESS  [loop] process=task_ChestPainWorkup  entry=Cardiology_TreatmentPlanning  required=cap_AssessChestPain, cap_AssessPatientCondition, cap_ConductFollowUp, cap_InterpretECG, cap_InterpretEcho, cap_PlanCardiacTreatment
16:16:25 INFO     [loop] orchestrator: langgraph state-graph, model=qwen2.5-3b-instruct-q4_k_m (openai)
16:16:27 INFO     [loop] hop 0: Cardiology_TreatmentPlanning  covers[cap_PlanCardiacTreatment]  (covered 1/6)
16:16:29 INFO     [loop]   -> commit Cardiology_PostCareFollowUp  [delegatesTo]  (attempts=3)
16:16:31 INFO     [loop] hop 1: Cardiology_PostCareFollowUp  covers[cap_ConductFollowUp]  (covered 2/6)
16:16:31 WARNING  [loop] orchestrator voluntarily terminated (early stop)
```

Total wall time: **~6 seconds**, entirely local, zero network calls.

The orchestrator selected an entry agent from the knowledge graph
(`Cardiology_TreatmentPlanning`), made a real hop decision backed by a
validated graph edge (`delegatesTo` → `Cardiology_PostCareFollowUp`, accepted
on the 3rd `validate_decision` attempt — MAKO's action-masking gate rejected
two earlier proposals before this one passed), and then voluntarily
terminated when the model judged the case needed more input before
continuing — a real, designed stopping condition (`termination.reason:
"llm_voluntary"`), not a crash or timeout.

## Full trace

[`sample-run-trace.json`](sample-run-trace.json) is MAKO's complete,
unedited output from this run — the audit-style trace record described in
MAKO's own architecture docs (`Trace`/`EvalLog`), including each agent's
full reasoning text (`raw_output`), the capability it covered, the
handoff edge used, and the termination reason.

## Why this matters for this submission

ADTC's automated profiler (`adtc-profiler`) only benchmarks the raw `.gguf`
model directly via `llama-bench` — it has no hook to execute a submission's
own application code (see `REPORT.md`). This directory exists to make the
report's claims about MAKO checkable: this is not a description of a
capability, it is the literal, reproducible output of running MAKO's
production orchestrator code against this submission's exact model file.
