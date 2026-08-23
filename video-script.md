# HestiaHealth — 2 minute video script

Target: **112 seconds** (8s buffer under the 120s hard limit). This maps to
the three things the rules actually ask for: "explaining your solution and
development journey," "screenshots or short videos showing your build in
action," and it's the video embedded at the top of the Devpost page — the
first thing a judge sees.

Record with macOS's built-in screen recorder: **Cmd+Shift+5** → "Record
Selected Portion" (select your browser window) or full screen. Enable the
mic in the control bar that pops up.

## Before you hit record

Both servers are already running — don't restart them:
- `llama-server` on port 8811 (the local model)
- The clinical console backend on port 8001

Open **`http://localhost:8001/`** and confirm the HestiaHealth console
loads. Have a second tab ready at
`https://github.com/aNasiusA/hestia-studio-adtc` for the opening/closing
shots. If either server isn't running, tell me and I'll restart them.

---

## 0:00 – 0:15 — The problem, and what this is

*(Over the GitHub repo page)*

> "Cloud-hosted LLMs need API fees, stable fiber, and constant electricity —
> three things a lot of African clinics can't rely on. This is HestiaHealth:
> a real multi-agent clinical AI system I built — called MAKO — with its
> decision-making running entirely offline, on an 8 gigabyte budget laptop."

## 0:15 – 0:45 — Live demo: submit a real case

*(Switch to the HestiaHealth console at localhost:8001)*

> "MAKO routes a patient case between specialist agents — cardiology,
> neurology, and more — using a knowledge graph, deciding who acts next at
> every step. This console is a clinical front end for that."

Type into "New case":

```
A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement.
```

Click **Route case**. Narrate as the timeline streams in:

> "It's picking an entry agent from the knowledge graph now — no internet
> involved anywhere in this. Each card is a real decision: which agent
> acted, what it decided, and the exact handoff it used — including when
> the graph validator rejected a proposal before accepting one."

## 0:45 – 1:10 — The development-journey beat: a real limitation, fixed

Let the case run until it **pauses** — you'll see the amber "Routing
paused" banner and a "Continue this case" form appear.

> "Here's something that was actually broken until recently: when the model
> needed more information, this used to be a dead end — no way to give it
> anything and continue. I went back into the orchestrator itself, made the
> pause state resumable, and built this."

Type into the continue form:

```
The on-call cardiologist confirms the patient should be admitted for observation.
```

Click **Continue routing** and let a new step stream in.

> "Same case, picking back up with new information — not starting over."

## 1:10 – 1:35 — The numbers

*(Switch to Terminal, in the submission repo directory)*

> "Benchmarked with ADTC's own profiler, which drives llama-bench directly —
> the same measurement path judges use."

```bash
cat submission.json | python3 -m json.tool | grep -A5 throughput
cat submission.json | python3 -m json.tool | grep -A4 memory
```

> "Thirty tokens a second, three point eight gigabytes peak memory — inside
> the seven gigabyte budget — no thermal throttling."

## 1:35 – 1:52 — Wrap

*(Back to the GitHub repo — scroll the file tree: `mako/`, `mako-integration/`, `REPORT.md`)*

> "The repo has the full report, the benchmarks, and MAKO's actual
> orchestrator code — not a description of it, the real thing, vendored in
> and verified working. This is HestiaHealth: MAKO's autonomous clinical
> routing, running entirely offline, on hardware people already have."

## 1:52 – end — Stop recording

---

## Fallback demo (if the live pause/continue doesn't want to cooperate on camera)

Some cases pause at agents with no further handoffs in the graph (a genuine
terminal point, not a bug) — if that happens on your first try, just submit
a second case rather than waiting. This one reliably pauses after 2 hops:

```
A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement.
```

If the console itself misbehaves on camera, the raw local-model call is
pre-verified and much simpler to fall back to (run from the submission repo
directory — responds in under a second):

```bash
curl -s http://localhost:8811/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role":"user","content":"You are the orchestration agent for a multi-agent clinical system with no internet access. Current case: a 54-year-old patient presents with chest pain; the Cardiology Triage agent has just finished its assessment and flagged possible cardiac involvement. Available next agents and what they handle: Cardiology_ECGInterpretation (reads and interprets ECG traces), Cardiology_EchoAnalysis (interprets echocardiograms), Cardiology_TreatmentPlanning (builds a cardiac treatment plan; requires ECG and echo results first), Cardiology_StressTestAnalysis (interprets stress test results). Decide which single agent should act next, name it exactly, and give a one-sentence clinical justification for why it comes before the others."}],
    "max_tokens": 120,
    "temperature": 0.2
  }' | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'])"
```

---

## After recording

1. Upload to YouTube — **Unlisted** is fine.
2. Copy the YouTube URL.
3. Tell me the URL, or paste it yourself into the Devpost "Video demo link"
   field at:
   https://devpost.com/submit-to/30091-africa-deep-tech-challenge-2026/manage/submissions/1145912-hestiahealth/project_details/edit

Also worth grabbing 2–3 plain screenshots (Cmd+Shift+4) of the console
mid-run — ideally one showing the pause/continue form — for the Devpost
image gallery. The rules specifically ask for "screenshots or short videos
showing your build in action."
