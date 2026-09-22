"""Read what Wispr Flow already recorded, instead of recording it again.

Every dictation Wispr Flow takes is stored on this machine: the WAV, the raw
recogniser output, the LLM-cleaned text, and where you fixed it by hand, your
fix. That is the exact pair this project needs -- clean close-mic audio plus
the words you meant -- and it is better than anything our own capture
produces, because the "words you meant" were worked out by a model that had
the whole sentence in front of it, not a phoneme recogniser guessing.

So for dictation, this is the primary source. Our own listener stays for the
cases Wispr does not cover: a Google Meet, a WhatsApp call, reading aloud.

    ~/Library/Application Support/Wispr Flow/flow.sqlite
        History
          asrText         what the machine heard
          formattedText   what you meant
          editedText      what you corrected it to, when you did
          audio           the WAV, 16 kHz mono, exactly what the models want
          timestamp       UTC
          status          'formatted' is a good row

This is a read of another company's private database. Two rules keep it
honest: the schema is checked before anything is trusted, and a failure is
loud. If Wispr renames a column in a release, the nightly job says so in
plain English rather than quietly finding nothing.

Nothing is ever written to Wispr's file. It is copied through SQLite's backup
API, which is safe against a live writer and includes the write-ahead log,
and the copy is what gets read.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config

DB_PATH = Path.home() / "Library" / "Application Support" / "Wispr Flow" / "flow.sqlite"
CURSOR_FILE = config.DATA_DIR / "wispr_cursor.json"

REQUIRED = {"transcriptEntityId", "asrText", "formattedText", "editedText",
            "audio", "timestamp", "status", "app"}


class SchemaChanged(RuntimeError):
    """Wispr's database no longer looks the way this reader expects."""


@dataclass
class Dictation:
    """One thing you said into Wispr Flow."""

    id: str
    when: datetime
    heard: str  # raw recogniser output
    meant: str  # LLM-cleaned, or your own edit if you made one
    edited: bool  # did you correct it by hand
    app: str
    audio: bytes | None

    @property
    def has_audio(self) -> bool:
        return bool(self.audio) and len(self.audio) > 1000


def available() -> bool:
    return DB_PATH.exists()


def _snapshot() -> Path:
    """A consistent copy of a database that another app is writing to."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Wispr Flow database not found at {DB_PATH}")
    handle, path = tempfile.mkstemp(suffix=".sqlite", prefix="wispr-ro-")
    os.close(handle)
    source = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise
    finally:
        source.close()
    return Path(path)


def _check_schema(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "History" not in tables:
        raise SchemaChanged("no History table; Wispr Flow has changed its storage")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(History)")}
    missing = REQUIRED - columns
    if missing:
        raise SchemaChanged(
            f"History is missing {sorted(missing)}; this reader was written for an "
            f"older Wispr Flow. Update mr_tharoor/wispr.py or run the built-in listener."
        )


def _parse_time(raw: str) -> datetime:
    # '2026-09-18 08:15:50.672 +00:00'
    text = raw.strip().replace(" +00:00", "+00:00").replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.fromisoformat(text[:19])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def dictations(since: datetime | None = None, with_audio: bool = True) -> list[Dictation]:
    """Everything you dictated after `since`, oldest first."""
    snapshot = _snapshot()
    try:
        conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        try:
            _check_schema(conn)
            audio_column = "audio" if with_audio else "NULL"
            rows = conn.execute(
                "SELECT transcriptEntityId, timestamp, asrText, formattedText, editedText, "
                f"app, {audio_column} FROM History WHERE status = 'formatted' AND formattedText IS NOT NULL "
                "ORDER BY timestamp ASC"
            ).fetchall()
        finally:
            conn.close()
    finally:
        snapshot.unlink(missing_ok=True)

    out: list[Dictation] = []
    for row_id, stamp, asr, formatted, edited, app, audio in rows:
        when = _parse_time(stamp)
        if since and when <= since:
            continue
        meant = (edited or "").strip() or (formatted or "").strip()
        if not meant:
            continue
        out.append(
            Dictation(
                id=str(row_id),
                when=when,
                heard=(asr or "").strip(),
                meant=meant,
                edited=bool((edited or "").strip()) and edited.strip() != (formatted or "").strip(),
                app=app or "",
                audio=bytes(audio) if (with_audio and audio) else None,
            )
        )
    return out


def for_day(day: date) -> list[Dictation]:
    start = datetime.combine(day, datetime.min.time()).astimezone()
    end = start + timedelta(days=1)
    return [d for d in dictations(since=start - timedelta(seconds=1)) if d.when < end]


def cursor() -> datetime | None:
    if not CURSOR_FILE.exists():
        return None
    try:
        return datetime.fromisoformat(json.loads(CURSOR_FILE.read_text())["last"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def advance_cursor(to: datetime) -> None:
    config.write_json_atomically(CURSOR_FILE, {"last": to.isoformat()})


def write_wav(dictation: Dictation, folder: Path) -> Path | None:
    """Put the stored WAV where the analyser can read it."""
    if not dictation.has_audio:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"wispr-{dictation.when:%H%M%S}-{dictation.id[:8]}.wav"
    path.write_bytes(dictation.audio)
    return path


def health() -> dict:
    """For `tharoor setup` and `tharoor logs`: is this source usable right now."""
    if not DB_PATH.exists():
        return {"available": False, "reason": "Wispr Flow is not installed, or has no history yet"}
    try:
        recent = dictations(with_audio=False)
    except SchemaChanged as exc:
        return {"available": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    edited = sum(1 for d in recent if d.edited)
    return {
        "available": True,
        "dictations": len(recent),
        "hand_corrected": edited,
        "latest": recent[-1].when.isoformat(timespec="minutes") if recent else None,
    }
