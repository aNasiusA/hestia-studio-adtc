# HestiaHealth — 2 minute video script

Target: **115 seconds** (5s buffer under the 120s hard limit). Maps to what
the rules actually ask for: "explaining your solution and development
journey," "screenshots or short videos showing your build in action," and
it's the video embedded at the top of the Devpost page.

Record with macOS's built-in screen recorder: **Cmd+Shift+5** → "Record
Selected Portion" (select your browser window) or full screen. Enable the
mic in the control bar that pops up.

## Before you hit record

Both servers are already running — don't restart them:
- `llama-server` on port 8811 (the local model)
- The clinical console backend on port 8001

Have three tabs ready:
1. `http://localhost:8001/graph.html` (the knowledge graph explorer)
2. `http://localhost:8001/` (the console)
3. `https://github.com/aNasiusA/hestia-studio-adtc` (for the opening/closing shots)

If either server isn't running, tell me and I'll restart them.

---

## 0:00 – 0:15 — The problem, and what this is

*(GitHub repo page)*

> "Cloud-hosted LLMs need API fees, stable fiber, and constant electricity —
> three things a lot of African clinics can't rely on. This is HestiaHealth
> — an app I built on top of MAKO, a multi-agent clinical AI system, with
> its decision-making running entirely offline, on an 8 gigabyte budget
> laptop."

## 0:15 – 0:35 — How the whole system works (graph explorer)

*(Switch to `localhost:8001/graph.html`, already on "All domains")*

> "This is the actual knowledge graph MAKO reasons over — twelve clinical
> domains, seventy-one agents, a hundred and thirty-five possible handoffs
> between them. Every line is a real referral or escalation path a case can
> take."

Click into **Cardiology**.

> "Drilling into one domain shows its actual agents and how they hand a
> case to each other — this is what the model is choosing between at every
> routing decision."

## 0:35 – 1:05 — Live demo: submit a real case

*(Switch to the console at `localhost:8001/`)*

> "Here's that decision happening live, fully offline, no internet
> involved anywhere in this."

Type into "New case":

```
A 54-year-old patient presents with chest pain; triage flags possible cardiac involvement.
```

Click **Route case**, let 2 steps stream in.

> "Each card is a real decision — which agent acted, what it decided, the
> exact handoff it used, and when the graph validator rejected a proposal
> before accepting one."

## 1:05 – 1:25 — The development-journey beat: a real limitation, fixed

Let the case pause — the amber "Routing paused" banner and continue form
appear.

> "This used to be a dead end — when the model needed more input, there
> was no way to give it anything and continue. I went back into the
> orchestrator, made the pause state resumable, and built this."

Type into the continue form and click **Continue routing**:

```
The on-call cardiologist confirms the patient should be admitted for observation.
```

## 1:25 – 1:45 — The numbers

*(Terminal, in the submission repo directory)*

> "Benchmarked with ADTC's own profiler — the same measurement path judges
> use: thirty tokens a second, three point eight gigabytes peak memory,
> inside the seven gigabyte budget, no thermal throttling."

```bash
cat submission.json | python3 -m json.tool | grep -A5 throughput
```

## 1:45 – 2:00 — Wrap

*(Back to the GitHub repo — scroll `mako/`, `mako-integration/`, `REPORT.md`)*

> "The repo has the full report, the benchmarks, and MAKO's actual
> orchestrator code — not a description of it, the real thing, verified
> working. This is HestiaHealth, built on MAKO: autonomous clinical
> routing, running entirely offline, on hardware people already have."

## Stop recording

---

## Fallback / timing notes

- If a case pauses at a genuine dead-end agent (no outgoing edges — the
  graph shows this is real, not a bug) on your first try, just submit the
  chest-pain case above — it reliably pauses after 2 hops with a resumable
  state.
- Running long? Cut the graph-explorer domain drill-down (0:15–0:35 can end
  right after the overview line) or trim the wrap to one sentence.
- If the console misbehaves on camera, the raw local-model call is
  pre-verified and simpler (run from the submission repo directory):

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

Also worth grabbing 2–3 plain screenshots (Cmd+Shift+4) — one of the graph
explorer, one of the console mid-run — for the Devpost image gallery.
