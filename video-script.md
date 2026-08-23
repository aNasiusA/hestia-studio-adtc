# HestiaHealth — 2 minute video script

Target: **110 seconds** (10s buffer under the 120s hard limit). Read the narration
naturally — don't rush.

Record with macOS's built-in screen recorder: **Cmd+Shift+5** → "Record Selected
Portion" (select your Safari/Chrome window) or full screen. Enable the mic in
the control bar that pops up.

## Before you hit record

Both servers are already running in the background — don't restart them:
- `llama-server` on port 8811 (the local model)
- The clinical console backend on port 8001

Just open **`http://localhost:8001/`** in your browser and confirm it loads
the HestiaHealth console before you start recording. If either server isn't
running, tell me and I'll restart them.

Have a second tab ready at `https://github.com/aNasiusA/hestia-studio-adtc`
for the opening/closing shots.

---

## 0:00 – 0:15 — The problem

*(Over the GitHub repo page)*

> "Cloud-hosted LLMs need API fees, stable fiber, and constant electricity —
> three things a lot of African clinics can't rely on. This is HestiaHealth:
> a real multi-agent clinical AI system I built — called MAKO — with its
> decision-making running entirely offline, on an 8 gigabyte budget laptop."

## 0:15 – 0:30 — What it does

*(Switch to the HestiaHealth console at localhost:8001)*

> "MAKO routes a patient case between specialist agents — cardiology,
> neurology, and more — using a knowledge graph. At every step it has to
> decide which specialist acts next. This console is a clinical front end
> for that: type in a case, and watch it route, live, against a model
> running entirely on this laptop."

## 0:30 – 1:10 — Live demo: submit a real case

Click into the "New case" box and type (or paste):

```
A 62-year-old patient presents with sudden-onset facial droop, slurred speech, and left arm weakness starting 40 minutes ago.
```

Click **Route case**. Narrate as the timeline streams in:

> "It's picking an entry agent from the knowledge graph now — there's no
> internet connection involved anywhere in this. Each card here is a real
> step: which agent acted, what it decided, and the exact handoff edge it
> used to hand off to the next one. It even shows when the graph validator
> rejected a proposal before accepting one — that's the action-masking gate
> that stops the model from committing to a handoff it hasn't justified."

Let 2–3 steps stream in (roughly 10–15 seconds), then:

> "Every one of these decisions, generated locally, in real time."

## 1:10 – 1:35 — The numbers

*(Switch to Terminal, in the submission repo directory)*

> "Benchmarked with ADTC's own profiler tool, which drives llama-bench
> directly — the same measurement path judges use."

```bash
cat submission.json | python3 -m json.tool | grep -A5 throughput
cat submission.json | python3 -m json.tool | grep -A4 memory
```

> "Thirty tokens a second, three point eight gigabytes peak memory — inside
> the seven gigabyte budget — no thermal throttling."

## 1:35 – 1:55 — Wrap

*(Back to the GitHub repo — scroll the file tree showing `mako/`, `mako-integration/`, `REPORT.md`)*

> "The repo has the full report, the benchmarks, and MAKO's actual
> orchestrator code — not a description of it, the real thing, vendored in
> and verified working. This is HestiaHealth: MAKO's autonomous clinical
> routing, running entirely offline, on hardware people already have."

## 1:55 – end — Stop recording

---

## Fallback demo (if the live console doesn't want to cooperate on camera)

Raw local-model call, from the submission repo directory — responds in
under a second:

```bash
curl -s http://localhost:8811/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role":"user","content":"You are the orchestration agent for a multi-agent clinical system with no internet access. Current case: a 54-year-old patient presents with chest pain; the Cardiology Triage agent has just finished its assessment and flagged possible cardiac involvement. Available next agents and what they handle: Cardiology_ECGInterpretation (reads and interprets ECG traces), Cardiology_EchoAnalysis (interprets echocardiograms), Cardiology_TreatmentPlanning (builds a cardiac treatment plan; requires ECG and echo results first), Cardiology_StressTestAnalysis (interprets stress test results). Decide which single agent should act next, name it exactly, and give a one-sentence clinical justification for why it comes before the others."}],
    "max_tokens": 120,
    "temperature": 0.2
  }' | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'])"
```

Or from `mako/`, the CLI version of the same live orchestrator run:

```bash
cd /Users/anasiusa/Development/hestia-studio-adtc/mako
.venv/bin/python -m orchestrator.run "A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement"
```

---

## After recording

1. Upload to YouTube — **Unlisted** is fine.
2. Copy the YouTube URL.
3. Tell me the URL, or paste it yourself into the Devpost "Video demo link"
   field at:
   https://devpost.com/submit-to/30091-africa-deep-tech-challenge-2026/manage/submissions/1145912-hestiahealth/project_details/edit

It's also worth grabbing 2–3 plain screenshots (Cmd+Shift+4) of the console
mid-run for the Devpost image gallery — the rules specifically ask for
"screenshots or short videos showing your build in action."
