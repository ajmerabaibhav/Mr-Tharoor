"""Paths and knobs. One place, so nothing hardcodes a directory."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("MR_ROY_HOME", Path.home() / "mr-roy"))

CACHE_DIR = ROOT / "cache"
AUDIO_DIR = CACHE_DIR / "audio"
INDEX_FILE = CACHE_DIR / "index.json"

# Raw day audio and the reports built from it.
DATA_DIR = ROOT / "data"
CLIPS_DIR = DATA_DIR / "clips"
REPORTS_DIR = ROOT / "reports"

# Wikimedia asks for a descriptive User-Agent on API traffic.
USER_AGENT = "mr-roy/0.1 (personal pronunciation tool; local use)"
NETWORK_TIMEOUT = 12

# Which recording to prefer when Wiktionary has several.
ACCENT_PREFERENCE = ("en-us", "en-uk", "en-au", "en-ca", "en")

# macOS voice used only when no human recording exists for a word.
FALLBACK_VOICE = "Samantha"


def user_name() -> str:
    """Who the morning report greets. Overridable, defaults to the Mac account."""
    import subprocess

    override = os.environ.get("MR_ROY_NAME")
    if override:
        return override
    try:
        full = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=2).stdout.strip()
        return full.split()[0] if full else "there"
    except Exception:  # noqa: BLE001
        return "there"

for _d in (AUDIO_DIR, CLIPS_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def write_json_atomically(path: Path, payload: object) -> None:
    """Write, then rename. Never truncate a good file to write a bad one.

    A plain write() leaves a half-file if the process dies, the disk fills, or
    the laptop lid closes at the wrong moment. Both of this project's JSON
    files are then unreadable, and the recovery path (return {}) silently
    replaces the whole thing on the next save. For history.json that is
    unrecoverable: the audio behind it is deleted after three days, so the
    tallies are the only surviving record.

    os.replace is atomic on the same filesystem, so a reader sees either the
    old file or the new one, never a torn one.
    """
    import json
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def quarantine(path: Path) -> Path | None:
    """Move an unreadable file aside instead of overwriting it.

    Corrupt is not the same as empty. Keeping the bytes means a bad parse is
    recoverable by hand; silently starting fresh means it never is.
    """
    if not path.exists():
        return None
    from datetime import datetime

    dead = path.with_suffix(path.suffix + f".corrupt-{datetime.now():%Y%m%d-%H%M%S}")
    path.rename(dead)
    return dead
