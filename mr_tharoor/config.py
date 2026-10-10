"""Paths and knobs. One place, so nothing hardcodes a directory."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(os.environ.get("MR_THAROOR_HOME", Path.home() / "mr-tharoor"))

DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"

# Everything this tool stores about a day -- the page, its corrections, what
# you typed -- is deleted on the night KEEP_DAYS later: a day
# is analysed that night, read the next morning, and gone the night after.
# Nobody opening this laptop can scroll back through old mistakes.
KEEP_DAYS = 2

# Apps whose text boxes textboxes.py never reads. Password managers and
# settings for the obvious reason; terminals because Claude Code and Codex
# are read from their own logs and the rest is commands; private messaging
# because those are conversations, not writing practice. Add a bundle id
# (osascript -e 'id of app "Name"') to keep any other app out.
TYPING_BLOCKED = frozenset({
    "com.1password.1password", "com.agilebits.onepassword7", "com.bitwarden.desktop",
    "com.apple.keychainaccess", "com.apple.Passwords", "com.apple.systempreferences",
    "com.apple.Terminal", "com.googlecode.iterm2", "dev.warp.Warp-Stable",
    "com.mitchellh.ghostty", "net.kovidgoyal.kitty",
    "com.apple.MobileSMS", "net.whatsapp.WhatsApp", "desktop.WhatsApp",
    "org.whispersystems.signal-desktop", "ru.keepcoder.Telegram", "com.tdesktop.Telegram",
    "com.electron.wispr-flow",
})

def user_name() -> str:
    """Who the morning report greets. Overridable, defaults to the Mac account."""
    import subprocess

    override = os.environ.get("MR_THAROOR_NAME")
    if override:
        return override
    try:
        full = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=2).stdout.strip()
        return full.split()[0] if full else "there"
    except Exception:  # noqa: BLE001
        return "there"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def purge_expired(today: date | None = None) -> tuple[int, float]:
    """Delete everything stored about expired days. Returns (files, megabytes).

    Report pages and their JSON, and what textboxes.py saved of your typing.
    Runs whether or not tonight's analysis does: a laptop on battery at
    23:30 must still forget on time.
    """
    from datetime import timedelta

    cutoff = ((today or date.today()) - timedelta(days=KEEP_DAYS - 1)).isoformat()
    files = [f for f in REPORTS_DIR.glob("????-??-??*") if f.name[:10] < cutoff]
    files += [f for f in (DATA_DIR / "typed").glob("????-??-??.jsonl") if f.name[:10] < cutoff]
    removed, freed = 0, 0
    for f in files:
        try:
            freed += f.stat().st_size
            f.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed, round(freed / 1e6, 1)


def write_json_atomically(path: Path, payload: object) -> None:
    """Write, then rename. Never truncate a good file to write a bad one.

    A plain write() leaves a half-file if the process dies, the disk fills, or
    the laptop lid closes at the wrong moment, and a torn report JSON is a
    morning with no lesson.

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
