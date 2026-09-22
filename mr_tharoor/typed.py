"""The other half of the day: the English you type, not the English you say.

Wispr Flow covers dictation. The rest of the day goes through a keyboard --
and the same habits come out of the fingers as out of the mouth: "the result
which you have gave", "can you check that whether it is working".

Nothing new is recorded to get at it. Claude Code already keeps every message
you type, as JSONL, in ~/.claude/projects/<folder>/<session>.jsonl, and that
is the one place on this machine where a day's typed prose already sits in
plain text. So this reads that, and only that.

What is deliberately excluded: pasted blocks, slash commands, shell
passthroughs, tool results, system reminders, and anything under a project
folder belonging to Mr Tharoor itself -- the grammar checker is Claude Code,
its own prompts land in a transcript, and without that filter tonight's
prompt becomes tomorrow's homework.

# ponytail: Claude Code only. Everything else you type -- Slack, Mail, the
# browser -- needs an Accessibility keylogger, which is a password-shaped
# risk for a grammar report. Add one only if the typing section proves itself.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"

# Blocks that are in the message but were never typed by a person.
NOISE = re.compile(
    r"<pasted_content.*?</pasted_content[^>]*>|<system-reminder>.*?</system-reminder>"
    r"|<local-command-[^>]*>.*?</local-command-[^>]*>|<command-[^>]*>.*?</command-[^>]*>"
    r"|<[a-z-]*-caveat>.*?</[a-z-]*-caveat>",
    re.DOTALL | re.IGNORECASE,
)
MIN_WORDS = 4
MAX_CHARS = 1200  # longer than this and it was pasted, not typed
# Rows Claude Code writes as if the user had typed them.
NOT_TYPED = ("[Request interrupted", "Caveat:", "This session is being continued",
             "API Error", "[Image #")


def _text(row: dict) -> str:
    content = (row.get("message") or {}).get("content")
    if isinstance(content, list):
        content = " ".join(part.get("text", "") for part in content
                           if isinstance(part, dict) and part.get("type") == "text")
    if not isinstance(content, str):
        return ""
    cleaned = NOISE.sub(" ", content).strip()
    if cleaned.startswith(("/", "!", "<", "#")) or cleaned.startswith(NOT_TYPED):
        return ""
    return " ".join(cleaned.split())


def _when(row: dict) -> datetime | None:
    stamp = row.get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def for_day(day: date, exclude: list[str] | None = None) -> list[tuple[str, str]]:
    """Everything typed into Claude Code on `day`, as [(source label, text)].

    `exclude` is the day's dictations: text that was spoken into a text box is
    not typing, and counting it twice would make one mistake look like a habit.
    """
    spoken = [" ".join(t.lower().split()) for t in (exclude or []) if t]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for transcript in sorted(PROJECTS.glob("*/*.jsonl")):
        if "mr-tharoor" in transcript.parent.name or "mr_tharoor" in transcript.parent.name:
            continue
        if datetime.fromtimestamp(transcript.stat().st_mtime).date() < day:
            continue  # nothing written on or after the day in question
        try:
            lines = transcript.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines):
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if row.get("type") != "user" or row.get("isMeta"):
                continue
            when = _when(row)
            if when is None or when.date() != day:
                continue
            text = _text(row)
            if not text or len(text) > MAX_CHARS or len(text.split()) < MIN_WORDS:
                continue
            key = " ".join(text.lower().split())
            if key in seen or any(key in utterance or utterance in key for utterance in spoken):
                continue
            seen.add(key)
            out.append((f"{day}-typed-{transcript.stem[:8]}-{number}", text))
    return out
