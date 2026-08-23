"""Minimal, dependency-free ``.env`` loader.

There is no third-party dotenv dependency. This walks up from this file's
directory to the first ``.env`` it finds (the shared repo-root one) and loads
simple ``KEY=VALUE`` lines into ``os.environ``.

Rules, chosen so it never surprises:
  * Real environment variables win — an entry already present in
    ``os.environ`` is left untouched (so ``export`` and inline
    ``KEY=v python -m ...`` prefixes still override the file).
  * Empty values (``KEY=``) are skipped, so a blank line in ``.env`` does not
    clobber provider auto-detection.
  * ``#`` comments and optional ``export`` prefixes are handled; values may be
    quoted.

Call :func:`load_env` at import time from the modules that read configuration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_loaded = False


def find_env(start: Optional[Path] = None) -> Optional[Path]:
    start = (start or Path(__file__).resolve().parent)
    for d in [start, *start.parents]:
        candidate = d / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env(*, override: bool = False) -> Optional[Path]:
    """Load the nearest ``.env`` into ``os.environ`` once; return its path."""
    global _loaded
    if _loaded:
        return None
    _loaded = True

    path = find_env()
    if path is None:
        return None

    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key or val == "":
            continue
        if override or key not in os.environ:
            os.environ[key] = val
    return path
