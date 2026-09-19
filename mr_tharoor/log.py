"""Say what happened, so a failure at 23:30 is not silence at 08:30.

The design's own first rule is that nothing fails quietly, and until now the
code broke that rule everywhere. A nightly job that dies leaves no trace, and
the only symptom is a report that never appears, days later, with nothing to
read.

Two sinks, on purpose:

  a rotating file    the whole story, for when something is wrong
  stderr             only warnings and errors, so a command stays quiet
                     when all is well

Both structured enough to grep and plain enough to read without a tool. The
log is also where the daily run records its own numbers -- how long, how much
audio, how many findings -- which is what turns "it feels slow" into a fact.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import time
from contextlib import contextmanager
from pathlib import Path

from . import config

LOG_DIR = config.ROOT / "logs"
LOG_FILE = LOG_DIR / "mr-tharoor.log"
MAX_BYTES = 2_000_000
BACKUPS = 3

_configured = False


ROOT_NAME = "mr-tharoor"


def get(name: str = ROOT_NAME) -> logging.Logger:
    """A logger that writes to disk and only bothers the terminal on trouble.

    Handlers live on ONE parent logger; every other name is a child that
    propagates to it. The first version attached the handlers to whichever
    name was asked for first, so the nightly job's own "start nightly" lines
    went to a logger with no handlers and vanished. A log that only records
    some callers is a log you cannot trust.
    """
    global _configured
    child = None if name == ROOT_NAME else name
    logger = logging.getLogger(ROOT_NAME)
    if _configured:
        return logging.getLogger(f"{ROOT_NAME}.{child}") if child else logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)

    to_file = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUPS
    )
    to_file.setLevel(logging.DEBUG)
    to_file.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s")
    )

    to_screen = logging.StreamHandler()
    to_screen.setLevel(logging.WARNING)  # silence is success
    to_screen.setFormatter(logging.Formatter("mr-tharoor: %(levelname)s: %(message)s"))

    logger.addHandler(to_file)
    logger.addHandler(to_screen)
    logger.propagate = False
    _configured = True
    return logging.getLogger(f"{ROOT_NAME}.{child}") if child else logger


@contextmanager
def step(name: str, **facts):
    """Time one step and record how it ended, including when it throws.

    The `finally` is the point: a job that dies mid-step still writes a line
    saying which step and why, which is the difference between debugging and
    guessing.
    """
    logger = get()
    detail = " ".join(f"{k}={v}" for k, v in facts.items())
    logger.info(f"start {name} {detail}".rstrip())
    started = time.monotonic()
    failed = None
    try:
        yield
    except BaseException as exc:
        failed = exc
        raise
    finally:
        elapsed = time.monotonic() - started
        if failed is None:
            logger.info(f"done  {name} in {elapsed:.1f}s")
        else:
            logger.error(
                f"FAILED {name} after {elapsed:.1f}s: "
                f"{type(failed).__name__}: {failed}",
                exc_info=True,
            )


def event(kind: str, **facts) -> None:
    """One machine-readable line. For counting runs, not for reading prose."""
    get().info(f"{kind} {json.dumps(facts, default=str)}")


def tail(lines: int = 40) -> str:
    if not LOG_FILE.exists():
        return "(nothing logged yet)"
    return "\n".join(LOG_FILE.read_text(errors="replace").splitlines()[-lines:])


def health() -> dict:
    """Did the scheduled jobs actually run? The question logs exist to answer."""
    if not LOG_FILE.exists():
        return {"runs": 0, "failures": 0, "last": None, "log": str(LOG_FILE)}
    runs = failures = 0
    last = None
    for line in LOG_FILE.read_text(errors="replace").splitlines():
        if " FAILED " in line:
            failures += 1
        if "done  nightly" in line or "done  morning" in line:
            runs += 1
            last = line.split()[0] + " " + line.split()[1]
    return {"runs": runs, "failures": failures, "last": last, "log": str(LOG_FILE)}
