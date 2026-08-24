# HestiaHealth

MAKO's clinical multi-agent orchestration, running entirely offline on an 8GB budget laptop — a submission to the [Africa Deep Tech Challenge 2026](https://adtc-2026.devpost.com) (Laptop LLM Challenge, Autonomous AI Agents track).

MAKO is a knowledge-graph-based multi-agent orchestrator (a separate final-year engineering project): agents, capabilities, tools, and handoffs live in an RDF/Turtle knowledge graph, and a ReAct-style LLM decides the next hop one step at a time, validating each decision against the graph before committing to it. Every one of those decisions normally needs a cloud LLM call. HestiaHealth replaces that call with a local Qwen2.5-3B-Instruct model (GGUF, Q4_K_M), running through `llama.cpp` — no GPU, no internet, no API fees.

**➡️ [SETUP.md](SETUP.md) — how to download the model and run this, either just the graded artifact or the full demo (orchestrator + clinical console + knowledge-graph explorer).**

**➡️ [REPORT.md](REPORT.md) — the full technical writeup: problem, design decisions, constraints, benchmarks.**

## What's in this repo

```
metadata.json          ADTC-required submission metadata
download_model.sh       Downloads the model weights (verified against Content-Length)
REPORT.md               Technical writeup — problem / design / constraints / benchmarks
SETUP.md                How to run this — both the graded artifact and the full demo
model/                  Downloaded here by download_model.sh (gitignored — not committed)
mako/                   MAKO's actual orchestrator, vendored and trimmed to what's needed
  webui/                 The HestiaHealth clinical console + knowledge-graph explorer
mako-integration/       Unedited log + trace JSON proving mako/ runs against this model
```

`mako/` is not a description of MAKO — it's MAKO's real, unmodified orchestrator code, copied in and verified working against this submission's model (trimmed from MAKO's ~380MB development repo down to the 32 files actually needed to run a session; see [`mako/README.md`](mako/README.md)). `mako-integration/` has the unedited proof.

## Compliance with ADTC's official template

This repo follows the [ADTC 2026 submission template](https://github.com/Africa-Deep-Tech-Foundation/adtc-2026-submission-template) structure: `metadata.json`, `download_model.sh`, `REPORT.md`, and a gitignored `model/` directory populated fresh by the download script. `llama.cpp` is the only runtime used, per the challenge's rules — no Ollama, no other wrapper, on the graded path. See ADTC's own template repo for the general requirements this structure satisfies; see [SETUP.md](SETUP.md) here for how to actually run this specific submission.

## License

This project's original code is licensed under the terms of the [GNU GPL v3 License](LICENSE) (carried over from the ADTC submission template).
