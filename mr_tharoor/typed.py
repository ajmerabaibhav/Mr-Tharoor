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

Codex users get the same: ~/.codex/history.jsonl is Codex's own list of the
prompts you typed, one {"ts", "text"} row each. Our own grammar calls run with
--ephemeral and never land there.

Everything else you type -- Mail, Slack, a browser box -- comes from
textboxes.py, which reads the box you are typing in while you type.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
CODEX_HISTORY = Path.home() / ".codex" / "history.jsonl"

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


def _plain(text: str) -> str:
    """Letters and spaces only, for comparing what was said with what was typed.

    Wispr punctuates; fingers in a terminal do not. Comparing the two with
    punctuation left in meant "I don\'t know what he\'s doing." and "i dont know
    what hes doing" were different sentences, and the same mistake was counted
    once as speech and once as typing -- which is how one slip is dressed up as
    a habit.
    """
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


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
    """Everything typed into Claude Code or Codex on `day`, as [(source label, text)].

    `exclude` is the day's dictations: text that was spoken into a text box is
    not typing, and counting it twice would make one mistake look like a habit.
    """
    spoken = [_plain(t) for t in (exclude or []) if t]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def keep(label: str, text: str) -> None:
        if not text or len(text) > MAX_CHARS or len(text.split()) < MIN_WORDS:
            return
        key = _plain(text)
        # `in k`, not `== k`: a text box saves a sentence of the message the
        # chat's transcript also holds whole, and one mistake read twice
        # showed as "2 times" (6 Oct, Claude desktop).
        if any(key in k for k in seen) or any(key in utterance or utterance in key for utterance in spoken):
            return
        seen.add(key)
        out.append((label, text))

    for transcript in sorted(PROJECTS.glob("*/*.jsonl")):
        if "mr-tharoor" in transcript.parent.name or "mr_tharoor" in transcript.parent.name:
            continue
        if datetime.fromtimestamp(transcript.stat().st_mtime).date() < day - timedelta(days=1):
            continue  # nothing written on or after the day in question, with a
            # day of slack: a row's timezone can put it after its file's mtime
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
            keep(f"{day}-typed-{transcript.stem[:8]}-{number}", _text(row))
    try:
        codex = CODEX_HISTORY.read_text(errors="replace").splitlines()
    except OSError:
        codex = []
    for number, line in enumerate(codex):
        try:
            row = json.loads(line)
            when = datetime.fromtimestamp(row["ts"]).date()
        except (json.JSONDecodeError, TypeError, KeyError, ValueError, OSError):
            continue
        if when == day:
            keep(f"{day}-typed-codex-{number}", _text({"message": {"content": row.get("text")}}))
    from . import textboxes

    for number, (_, text) in enumerate(textboxes.for_day(day)):
        keep(f"{day}-typed-ax-{number}", text)
    return out
