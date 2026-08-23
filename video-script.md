# HestiaHealth — 2 minute video script

Target: **110 seconds** (10s buffer under the 120s hard limit). Read the narration
naturally — don't rush; the demo commands are already tested and fast.

Record with macOS's built-in screen recorder: **Cmd+Shift+5** → "Record Selected
Portion" (select just your Terminal window) or full screen if you also want to
show the GitHub repo in a browser tab. It records system audio + mic if you
enable the mic in the little control bar that pops up — make sure mic is ON.

Two windows to have ready before you hit record:
1. A **Terminal**, split or two tabs:
   - Tab A: `cd /Users/anasiusa/Development/hestia-studio-adtc`
   - Tab B: `cd /Users/anasiusa/Development/final-year-project/Mako-Demo/v3-langraph`
2. A **browser tab** open to `https://github.com/aNasiusA/hestia-studio-adtc`

The local model server is already running in the background on port 8811 —
don't restart it mid-recording, it's warm and fast right now. Both demo
commands below are pre-verified against it.

---

## 0:00 – 0:15 — The problem (talk to camera or over the GitHub repo page)

> "Cloud-hosted LLMs need API fees, stable fiber, and constant electricity —
> three things a lot of African clinics can't rely on. This is HestiaHealth:
> making a real multi-agent clinical AI system I built — called MAKO — run
> its decision-making entirely offline, on an 8 gigabyte budget laptop."

*(Show the GitHub repo README/REPORT.md briefly while saying this.)*

## 0:15 – 0:30 — What MAKO actually does

> "MAKO routes a patient case between specialist agents — cardiology,
> neurology, oncology and more — using a knowledge graph. At every step, an
> LLM decides which specialist should act next. Today that decision needs a
> cloud model. HestiaHealth replaces that one call with Qwen 2.5, 3 billion
> parameters, quantized to about 2 gigabytes, running locally through
> llama.cpp."

## 0:30 – 1:05 — Live demo: MAKO's actual orchestrator, not a mock

Switch to **Terminal Tab B** (the MAKO `v3-langraph` directory). Say this
while you run the command:

> "This isn't a prompt imitating MAKO — this is MAKO's real orchestrator
> code, pointed at the local model instead of the cloud, deciding a real
> patient case live."

Paste and run:

```bash
python -m orchestrator.run "A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement"
```

Let the log stream on screen — it takes about 6 seconds and shows, live:
- entry agent selected from the knowledge graph
- a hop decision proposed, rejected, and retried against the graph
- the accepted handoff, and why
- the orchestrator's own decision to stop and ask for more input

> "Entry agent picked from the graph, a handoff decision validated against a
> real graph edge — it even rejected its own proposals twice before landing
> on one that passed — and then it stopped itself when it judged the case
> needed more information. That's the actual orchestrator, running fully
> offline, in about six seconds."

## 1:05 – 1:30 — The numbers

Switch to **Terminal Tab A** (the submission repo).

> "Benchmarked with ADTC's own profiler tool, which drives llama-bench
> directly — the same measurement path judges use."

Paste and run:

```bash
cat submission.json | python3 -m json.tool | grep -A5 throughput
cat submission.json | python3 -m json.tool | grep -A4 memory
```

> "Thirty tokens a second, three point eight gigabytes peak memory — inside
> the seven gigabyte budget — no thermal throttling."

## 1:30 – 1:55 — Wrap

> "The repo has the full report, the benchmarks, the design decisions, and
> the unedited trace from that live MAKO run so it's checkable, not just
> claimed. This is HestiaHealth — MAKO's autonomous clinical routing,
> running entirely offline, on hardware people already have."

*(Show the repo's `mako-integration/` folder or `REPORT.md` one more time.)*

## 1:55 – end — Stop recording

---

## Fallback demo (if the live MAKO run doesn't want to cooperate on camera)

The raw local-model call is also pre-verified and much simpler to reuse —
run from the **submission repo** directory:

```bash
curl -s http://localhost:8811/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role":"user","content":"You are the orchestration agent for a multi-agent clinical system with no internet access. Current case: a 54-year-old patient presents with chest pain; the Cardiology Triage agent has just finished its assessment and flagged possible cardiac involvement. Available next agents and what they handle: Cardiology_ECGInterpretation (reads and interprets ECG traces), Cardiology_EchoAnalysis (interprets echocardiograms), Cardiology_TreatmentPlanning (builds a cardiac treatment plan; requires ECG and echo results first), Cardiology_StressTestAnalysis (interprets stress test results). Decide which single agent should act next, name it exactly, and give a one-sentence clinical justification for why it comes before the others."}],
    "max_tokens": 120,
    "temperature": 0.2
  }' | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'])"
```

Responds in under a second with a correct clinical decision. Use this if you
want a shorter, guaranteed-fast segment instead of the full orchestrator run.

---

## After recording

1. Upload to YouTube — **Unlisted** is fine, it just needs to be viewable via
   link, doesn't need to be public-searchable.
2. Copy the YouTube URL.
3. Tell me the URL, or paste it yourself into the Devpost "Video demo link"
   field at:
   https://devpost.com/submit-to/30091-africa-deep-tech-challenge-2026/manage/submissions/1145912-hestiahealth/project_details/edit
