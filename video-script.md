# HestiaHealth — 2 minute video script

Target: **110 seconds** (10s buffer under the 120s hard limit). Read the narration
naturally — don't rush; the demo commands are already tested and fast.

Record with macOS's built-in screen recorder: **Cmd+Shift+5** → "Record Selected
Portion" (select just your Terminal window) or full screen if you also want to
show the GitHub repo in a browser tab. It records system audio + mic if you
enable the mic in the little control bar that pops up — make sure mic is ON.

Two windows to have ready before you hit record:
1. A **Terminal**, already `cd`'d into `/Users/anasiusa/Development/hestia-studio-adtc`
2. A **browser tab** open to `https://github.com/aNasiusA/hestia-studio-adtc`

The local model server is already running in the background on port 8811 —
don't restart it mid-recording, it's warm and fast right now.

---

## 0:00 – 0:15 — The problem (talk to camera or over the GitHub repo page)

> "Cloud-hosted LLMs need API fees, stable fiber, and constant electricity —
> three things a lot of African clinics can't rely on. This is HestiaHealth:
> making a real multi-agent clinical AI system I built — called MAKO — run
> its decision-making entirely offline, on an 8 gigabyte budget laptop."

*(Show the GitHub repo README/REPORT.md briefly while saying this.)*

## 0:15 – 0:35 — What MAKO actually does

> "MAKO routes a patient case between specialist agents — cardiology,
> neurology, oncology and more — using a knowledge graph. At every step, an
> LLM has to decide which specialist should act next. Today that decision
> requires a call to a cloud model. HestiaHealth replaces that one call with
> a small model running locally through llama.cpp — Qwen 2.5, 3 billion
> parameters, quantized to about 2 gigabytes."

*(Scroll REPORT.md's Design Decisions section briefly.)*

## 0:35 – 1:10 — Live demo: the model making a real hop decision, offline

Switch to Terminal. Say this while you run the command:

> "Here it is actually deciding. This is the exact prompt MAKO's orchestrator
> would send — a real patient case, cardiac chest pain, deciding which
> specialist agent goes next — running against the local model, no internet
> involved."

Paste and run:

```bash
curl -s http://localhost:8811/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role":"user","content":"You are the orchestration agent for a multi-agent clinical system with no internet access. Current case: a 54-year-old patient presents with chest pain; the Cardiology Triage agent has just finished its assessment and flagged possible cardiac involvement. Available next agents and what they handle: Cardiology_ECGInterpretation (reads and interprets ECG traces), Cardiology_EchoAnalysis (interprets echocardiograms), Cardiology_TreatmentPlanning (builds a cardiac treatment plan; requires ECG and echo results first), Cardiology_StressTestAnalysis (interprets stress test results). Decide which single agent should act next, name it exactly, and give a one-sentence clinical justification for why it comes before the others."}],
    "max_tokens": 120,
    "temperature": 0.2
  }' | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'])"
```

It answers in under a second: **"Cardiology_ECGInterpretation..."** with a
correct clinical justification. Let it finish on screen, then say:

> "Right agent, right reasoning, sub-second — fully local."

## 1:10 – 1:35 — The numbers

> "Benchmarked with ADTC's own profiler tool, which drives llama-bench
> directly — this is the same measurement path judges use."

Paste and run:

```bash
cat submission.json | python3 -m json.tool | grep -A5 throughput
cat submission.json | python3 -m json.tool | grep -A4 memory
```

> "Thirty tokens a second, three point eight gigabytes peak memory — inside
> the seven gigabyte budget — and no thermal throttling."

## 1:35 – 1:55 — Wrap

> "The repo has the full report, the benchmarks, the design decisions — why
> Qwen 2.5 at this size, why Q4_K_M quantization, what I rejected and why.
> This is HestiaHealth — MAKO's autonomous clinical routing, running
> entirely offline, on hardware people already have."

*(Show the repo's file listing or REPORT.md one more time.)*

## 1:55 – end — Stop recording

---

## After recording

1. Upload to YouTube — **Unlisted** is fine, it just needs to be viewable via
   link, doesn't need to be public-searchable.
2. Copy the YouTube URL.
3. Tell me the URL, or paste it yourself into the Devpost "Video demo link"
   field at:
   https://devpost.com/submit-to/30091-africa-deep-tech-challenge-2026/manage/submissions/1145912-hestiahealth/project_details/edit
