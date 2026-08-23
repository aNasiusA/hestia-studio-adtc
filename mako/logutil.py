"""Structured, colour-coded logging for v3 — console *and* file simultaneously.

This is the shared global logger (the same one used across v1/v1.1/v2), with
one v3 change: every record is emitted to **both** ``stderr`` (colour-coded,
for interactive use) **and** a log file (plain text, for later inspection).
Modules import it exactly as before::

    from logutil import get_logger

    log = get_logger(__name__)     # or get_logger("recall"), etc.
    log.debug("cache miss for %s", uri)
    log.info("recalled %d capabilities", n)
    log.success("pipeline finished")     # bonus level, between INFO and WARNING

There is also a ready-made module logger for quick scripts::

    from logutil import log
    log.info("hello")

Rules, chosen so it never surprises:
  * **File + console together.** Console output goes to ``stderr`` (keeping
    ``stdout`` clean for real program output); the same records are also
    appended to a log file. The file path is read once from ``KG_LOG_FILE``
    (default ``<v3 root>/logs/v3.log``); its parent directory is created if
    missing. Set ``KG_LOG_FILE`` to an empty string to disable file logging.
  * Colour is auto-detected for the console: on only when stderr is a TTY.
    ``NO_COLOR`` forces it off and ``KG_LOG_COLOR=1``/``FORCE_COLOR`` forces it
    on. The file is always written *without* colour codes so it stays greppable.
  * The threshold is read once from ``KG_LOG_LEVEL`` (default ``INFO``); accepts
    a name (``DEBUG``) or number. Call :func:`set_level` to change it at runtime.
  * Handlers are attached exactly once, so importing this from many modules
    never produces duplicated lines.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Union

# A custom level sitting just above INFO for "good news" milestones. Standard
# handlers treat unknown levels fine; we register a name so it prints nicely.
SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCCESS")

# ANSI colour codes keyed by level number.
_RESET = "\033[0m"
_BOLD = "\033[1m"
_LEVEL_COLOR = {
    logging.DEBUG:    "\033[36m",         # cyan
    logging.INFO:     "\033[34m",         # blue
    SUCCESS:          "\033[32m",         # green
    logging.WARNING:  "\033[33m",         # yellow
    logging.ERROR:    "\033[31m",         # red
    logging.CRITICAL: "\033[1;37;41m",    # bold white on red
}

_ROOT_NAME = "kg"
_configured = False

# Default log file lives under the v3 root (this file's directory), so it
# resolves the same no matter which module or cwd triggers configuration.
_DEFAULT_LOG_FILE = Path(__file__).resolve().parent / "logs" / "v3.log"


def _color_enabled() -> bool:
    """Colour on iff stderr is a TTY, unless env overrides that decision."""
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("FORCE_COLOR") or os.getenv("KG_LOG_COLOR"):
        return True
    return bool(getattr(sys.stderr, "isatty", lambda: False)())


def _log_file_path() -> Optional[Path]:
    """Resolve the log file path from ``KG_LOG_FILE`` (default under v3/logs).

    Returns ``None`` when file logging is explicitly disabled via an empty
    ``KG_LOG_FILE``.
    """
    raw = os.getenv("KG_LOG_FILE")
    if raw is None:
        return _DEFAULT_LOG_FILE
    raw = raw.strip()
    if raw == "":
        return None
    return Path(raw).expanduser()


def _safe_message(record: logging.LogRecord) -> str:
    """Render the record's message, tolerating print-style calls.

    Stdlib logging expects ``log.info("%s done", x)``; a call like
    ``log.info("done", x)`` (no placeholder, extra arg) makes ``msg % args``
    raise ``TypeError``. Rather than crash the whole log call, fall back to
    appending the stray args space-separated.
    """
    try:
        return record.getMessage()
    except (TypeError, ValueError):
        args = record.args
        if isinstance(args, tuple):
            extra = " ".join(str(a) for a in args)
        else:
            extra = str(args)
        return f"{record.msg} {extra}".rstrip()


class _ColorFormatter(logging.Formatter):
    """Formats one record as ``HH:MM:SS LEVEL   [name] message`` with the level
    (and, for CRITICAL, the whole line) colour-coded when colour is enabled."""

    def __init__(self, use_color: bool) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.datefmt)
        level = record.levelname
        # Strip the shared root prefix so "kg.recall" shows as "recall".
        name = record.name
        if name == _ROOT_NAME:
            name = ""
        elif name.startswith(_ROOT_NAME + "."):
            name = name[len(_ROOT_NAME) + 1:]

        message = _safe_message(record)
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"

        scope = f"[{name}] " if name else ""
        line = f"{ts} {level:<8} {scope}{message}"

        if self.use_color:
            color = _LEVEL_COLOR.get(record.levelno, "")
            if record.levelno >= logging.CRITICAL:
                line = f"{color}{line}{_RESET}"
            else:
                # Colour just the level token, leaving the message readable.
                colored_level = f"{_BOLD}{color}{level:<8}{_RESET}"
                line = f"{ts} {colored_level} {scope}{message}"
        return line


def _resolve_level(value: Union[str, int, None], default: int = logging.INFO) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    value = str(value).strip().upper()
    if value.isdigit():
        return int(value)
    return logging.getLevelName(value) if isinstance(logging.getLevelName(value), int) else default


def _configure() -> logging.Logger:
    """Attach one console + one file handler to the shared root (idempotent)."""
    global _configured
    root = logging.getLogger(_ROOT_NAME)
    if _configured:
        return root

    level = _resolve_level(os.getenv("KG_LOG_LEVEL"))

    # Console handler: colour-coded, to stderr.
    console = logging.StreamHandler(stream=sys.stderr)
    console.setFormatter(_ColorFormatter(use_color=_color_enabled()))
    root.addHandler(console)

    # File handler: plain (no colour), same records. Best-effort — if the file
    # can't be opened we degrade to console-only rather than crash the app.
    log_path = _log_file_path()
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(_ColorFormatter(use_color=False))
            root.addHandler(file_handler)
        except OSError as exc:  # pragma: no cover - filesystem edge case
            root.addHandler(console)  # already added; keep going
            console.handle(root.makeRecord(
                _ROOT_NAME, logging.WARNING, __file__, 0,
                "file logging disabled (%s): %s", (log_path, exc), None,
            ))

    root.setLevel(level)
    # Don't bubble up to the interpreter's root logger (avoids double output if
    # the host app also configured logging).
    root.propagate = False
    _configured = True
    return root


def _success(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(SUCCESS):
        self._log(SUCCESS, message, args, **kwargs)


# Expose ``logger.success(...)`` on every Logger instance.
logging.Logger.success = _success  # type: ignore[attr-defined]


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a colour-coded logger writing to console *and* file.

    ``name`` is namespaced under the shared ``kg`` root so all modules share
    one pair of handlers and one threshold. Passing ``__name__`` is fine — the
    module path is used verbatim as the scope shown in ``[brackets]``.
    """
    _configure()
    if not name or name == _ROOT_NAME:
        return logging.getLogger(_ROOT_NAME)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


def set_level(level: Union[str, int]) -> None:
    """Raise or lower the global threshold at runtime (e.g. ``set_level("DEBUG")``)."""
    logging.getLogger(_ROOT_NAME).setLevel(_resolve_level(level))


# Ready-to-use module logger for quick scripts: ``from logutil import log``.
log = get_logger()


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    set_level("DEBUG")
    demo = get_logger("demo")
    demo.debug("a debug detail: %s", {"cache": "miss"})
    demo.info("informational message")
    demo.success("something completed successfully")
    demo.warning("a warning worth noticing")
    demo.error("an error occurred")
    demo.critical("critical failure")
    try:
        1 / 0
    except ZeroDivisionError:
        demo.error("caught an exception", exc_info=True)
