"""Loop-safety and session constants (plan.md §8), tunable via env.

Both are named constants with tunable defaults:

  * ``SESSION_RETRY_CAP`` — max orchestrator inference rounds within a single
    hop-decision session. On exceeding, the session hard-fails as a diagnostic
    (Trace.final_status = "session_retry_exceeded"), never a crash.
  * ``MAX_HOP_COUNT`` — max hops for the entire run (~2x a typical path length in
    the existing domain). On exceeding, the run halts
    (Trace.final_status = "max_hop_exceeded"). A starting value, expected to be
    tuned empirically once the demo runs.
"""
from __future__ import annotations

import os

SESSION_RETRY_CAP = int(os.getenv("KG_SESSION_RETRY_CAP", "10"))
MAX_HOP_COUNT = int(os.getenv("KG_MAX_HOP_COUNT", "15"))
