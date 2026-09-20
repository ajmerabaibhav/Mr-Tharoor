"""Which mistakes are real, and which ones are just noise.

Two separate problems get confused constantly, so they are separated here.

  AUDIO is expensive. Re-analysing a week of recordings every night would
  cook a MacBook Air. So audio lives for 3 days and then deletes itself.

  COUNTS are free. A day's findings are a few hundred bytes of JSON. Keeping
  those forever costs nothing and no CPU at all, because nothing is ever
  re-analysed -- each day is scored once, on the night it happened, and only
  the tally survives.

That split is the whole trick. You get long-memory judgement ("you have said
this wrong every day for a week") at short-memory cost.

Deciding what to show used to be a stack of hard cutoffs, and every one of
them threw information away. A 0.79-confidence detection was deleted as
though it said nothing. A word spoken once was deleted for being rare. Both
are recoverable losses only if you never make them, so now nothing is
discarded at write time above a noise floor, and the weighing happens later:

    every detection above the noise floor  ->  stored forever (bytes, not audio)
        |
        v
    evidence.py       pools every word carrying the same sound, weights each
        |             detection by its confidence, decays it by age, and asks
        |             "are we 95% sure this error rate is real?"
        |
        |             This is what lets a word said ONCE be reported: it
        |             inherits the strength of a sound you fail constantly.
        v
    verdicts()        turns that into a sentence a person will act on.
        |             "Five days running" moves someone. A posterior does not.
        v
    top 6, worst first, plus one win
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta

from . import config, evidence

HISTORY_FILE = config.DATA_DIR / "history.json"

# Detections below this are not stored at all -- not because they are wrong,
# but because they are mostly silence and noise and they bloat the file. The
# real weighing happens in evidence.py, where confidence is a weight and not
# a cliff. Everything above this floor is kept: you cannot pool evidence you
# threw away at write time, which is what the old 0.80 cutoff did.
STORAGE_FLOOR = 0.30

# Kept for the day-streak phrasing only. These no longer decide what is shown.
MIN_CONFIDENCE = 0.80
MIN_OCCURRENCES = 3
MIN_ERROR_RATE = 0.50

# How far back the verdict looks. Costs nothing: it reads tallies, not audio.
WINDOW_DAYS = 5
# Seen on this many days inside the window and it stops being a coincidence.
CHRONIC_DAYS = 3
# Gone this many days running and we call it fixed.
FIXED_AFTER_CLEAN_DAYS = 3
# A report longer than this is a report nobody opens.
MAX_ITEMS = 6

# Audio retention. Deliberately short: this is the CPU and disk knob.
AUDIO_RETENTION_DAYS = 3


@dataclass
class Finding:
    """One word said wrong, on one day."""

    word: str
    contrast: str  # e.g. "v->w" or "stress"
    said: int  # times the word came up
    wrong: float  # may be confidence-weighted evidence
    confidence: float
    analysis_version: int = 0

    @property
    def error_rate(self) -> float:
        return self.wrong / self.said if self.said else 0.0


@dataclass
class Verdict:
    """What Mr Tharoor thinks about this mistake after watching it for a while."""

    word: str
    contrast: str
    status: str  # "new" | "watch" | "chronic" | "fading" | "fixed"
    days_seen: int
    window: int
    total_wrong: int
    message: str

    @property
    def is_genuine(self) -> bool:
        """Worth telling the user it is a real problem, not a bad afternoon."""
        return self.status in ("chronic", "fading")


def passes_filter(finding: Finding) -> bool:
    """Gates 1 to 3. Cheap, runs on every raw detection."""
    if finding.confidence < MIN_CONFIDENCE:
        return False
    if finding.said >= MIN_OCCURRENCES:
        return finding.wrong > 0
    return finding.error_rate >= MIN_ERROR_RATE


def _load() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text())
    except json.JSONDecodeError:
        # This file is the only surviving record: the audio behind it is
        # deleted after AUDIO_RETENTION_DAYS and can never be re-analysed.
        # Overwriting it with {} would erase every week of history in
        # silence, so keep the bytes and make the loss visible.
        dead = config.quarantine(HISTORY_FILE)
        print(f"mr-tharoor: history was unreadable, kept a copy at {dead}")
        return {}


def _save(history: dict) -> None:
    config.write_json_atomically(HISTORY_FILE, history)


def record_day(day: date, findings: list[Finding]) -> None:
    """Store one night's tally. Idempotent -- re-running a day overwrites it.

    Stores everything above the storage floor, including things that will
    never be shown tonight. A rare word's single observation is worthless on
    its own and decisive once forty other words have voted alongside it, so
    it has to survive to be pooled later.
    """
    history = _load()
    merged: dict[tuple[str, str, int], Finding] = {}
    for finding in findings:
        if finding.confidence < STORAGE_FLOOR:
            continue
        key = finding.word, finding.contrast, finding.analysis_version
        if key in merged:
            old = merged[key]
            merged[key] = replace(old, said=old.said + finding.said,
                                  wrong=old.wrong + finding.wrong * finding.confidence)
        else:
            merged[key] = replace(finding, wrong=finding.wrong * finding.confidence, confidence=1.0)
    history[day.isoformat()] = [asdict(f) for f in merged.values()]
    _save(history)


def observations(
    window_days: int = evidence.LOOKBACK_DAYS, today: date | None = None, min_version: int = 0
) -> list[evidence.Observation]:
    """Everything on file inside the window, as evidence.

    Confidence becomes weight, not a gate. The window is honoured here rather
    than ignored: a caller asking for 7 days and silently receiving 30 would
    get a different answer than it asked for.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=window_days)
    from . import accuracy

    dismissed = {(label.day, label.word, label.contrast) for label in accuracy.labels()
                 if label.verdict == accuracy.FALSE_ALARM}
    out: list[evidence.Observation] = []
    for day_str, items in _load().items():
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        if day < cutoff or day > today:
            continue
        for item in items:
            if item.get("analysis_version", 0) < min_version:
                continue
            if (day_str, item["word"], item["contrast"]) in dismissed:
                continue
            out.append(
                evidence.Observation(
                    day=day,
                    word=item["word"],
                    contrast=item["contrast"],
                    opportunities=item["said"],
                    error_weight=item["wrong"] * item.get("confidence", 1.0),
                )
            )
    return out


def _key(item: dict) -> tuple[str, str]:
    return (item["word"], item["contrast"])


def _days_in_window(history: dict, today: date, window: int) -> list[str]:
    """Calendar days, not recorded days.

    Using recorded days would let a week off work look like a week of
    improvement, which is the kind of flattering lie that makes a tool
    useless.
    """
    return [(today - timedelta(days=i)).isoformat() for i in range(window)]


def verdicts(today: date | None = None, window: int = WINDOW_DAYS) -> list[Verdict]:
    """What to actually show tonight, worst first."""
    today = today or date.today()
    history = _load()
    recent = _days_in_window(history, today, window)
    older = _days_in_window(history, today - timedelta(days=window), window)

    seen: Counter = Counter()
    wrong_total: Counter = Counter()
    for day in recent:
        for item in history.get(day, []):
            if item["wrong"] <= 0:
                continue
            seen[_key(item)] += 1
            wrong_total[_key(item)] += item["wrong"]

    # Something that used to be chronic and has gone quiet deserves saying so.
    previously: Counter = Counter()
    for day in older:
        for item in history.get(day, []):
            if item["wrong"] <= 0:
                continue
            previously[_key(item)] += 1

    out: list[Verdict] = []
    for key in set(seen) | set(previously):
        word, contrast = key
        days_seen = seen[key]
        clean_run = _clean_run(history, key, today, window)

        if days_seen == 0 and previously[key] >= CHRONIC_DAYS and clean_run >= FIXED_AFTER_CLEAN_DAYS:
            status = "fixed"
            message = f"You have not said {word} wrong in {clean_run} days. That one is done."
        elif days_seen >= CHRONIC_DAYS:
            status = "chronic"
            message = (
                f"{days_seen} of the last {window} days. This is not a bad day, "
                f"it is a habit. Listen to {word} and say it back."
            )
        elif days_seen == 0:
            continue
        elif previously[key] >= CHRONIC_DAYS and days_seen < CHRONIC_DAYS:
            status = "fading"
            message = f"Down to {days_seen} of {window} days from a daily habit. Keep going."
        elif days_seen == 2:
            status = "watch"
            message = f"Twice in {window} days. One more and Mr Tharoor calls it a habit."
        else:
            status = "new"
            message = "First time this week. Might be nothing."

        out.append(
            Verdict(
                word=word,
                contrast=contrast,
                status=status,
                days_seen=days_seen,
                window=window,
                total_wrong=wrong_total[key],
                message=message,
            )
        )

    priority = {"chronic": 0, "watch": 1, "fading": 2, "new": 3, "fixed": 4}
    out.sort(key=lambda v: (priority[v.status], -v.total_wrong, v.word))
    return out


def _clean_run(history: dict, key: tuple[str, str], today: date, window: int) -> int:
    """Consecutive days, counting back from today, with no sign of this mistake."""
    run = 0
    for i in range(window * 2):
        day = (today - timedelta(days=i)).isoformat()
        if day not in history:
            break  # no recording that day proves nothing either way
        relevant = [item for item in history[day] if _key(item) == key]
        if not relevant or any(item["wrong"] > 0 for item in relevant):
            break
        run += 1
    return run


@dataclass
class ReportRow:
    """One SOUND, not one word.

    Showing "version", "very", "available" and "delivery" as four separate
    findings is one lesson printed four times, and it crowds out every other
    sound you need to hear. Group by the contrast, list the words inside it,
    and the cap starts limiting lessons instead of limiting examples.
    """

    contrast: str
    words: list[str]  # worst first
    borrowed_words: list[str]  # only visible because the sound pooled
    opportunities: float
    errors: float
    lower_bound: float
    verdict: Verdict  # day-streak phrasing, taken from the worst word
    message: str

    @property
    def rate(self) -> float:
        return self.errors / self.opportunities if self.opportunities else 0.0


def tonights_report(today: date | None = None) -> list[ReportRow]:
    """What to show tonight, and why.

    Two systems, each doing the job it is good at:

      evidence.py decides WHETHER something is real. It pools every word
      carrying the same sound, weights each detection by confidence, decays
      by age, and answers "are we 95% sure this rate is real". That is what a
      day count cannot do, and it is what lets a word said once get through.

      verdicts() decides HOW TO SAY IT. "Five days running" is a sentence a
      person acts on; "posterior lower bound 0.62" is not.
    """
    today = today or date.today()
    reported = [a for a in evidence.assess(observations(today=today), today) if a.report]
    by_key = {(v.word, v.contrast): v for v in verdicts(today)}

    grouped: dict[str, list[evidence.Assessment]] = {}
    for assessment in reported:
        grouped.setdefault(assessment.contrast, []).append(assessment)

    rows: list[ReportRow] = []
    for contrast, group in grouped.items():
        group.sort(key=lambda a: (-a.errors, -a.lower_bound))
        worst = group[0]
        verdict = by_key.get((worst.word, worst.contrast)) or Verdict(
            word=worst.word,
            contrast=contrast,
            status="new",
            days_seen=1,
            window=WINDOW_DAYS,
            total_wrong=round(worst.errors),
            message=worst.explain(),
        )
        pooled = [a for a in group if a.borrowed]
        borrowed = [a.word for a in pooled]
        message = verdict.message
        if pooled and verdict.status not in ("chronic", "fading"):
            message = pooled[0].explain()
        elif pooled:
            example = pooled[0]
            how_often = "once" if example.observations < 1.5 else "twice"
            message = (
                f"{message} It has spread: {example.word} came up only "
                f"{how_often} and you still missed it."
            )

        rows.append(
            ReportRow(
                contrast=contrast,
                words=[a.word for a in group],
                borrowed_words=borrowed,
                opportunities=sum(a.observations for a in group),
                errors=sum(a.errors for a in group),
                lower_bound=max(a.lower_bound for a in group),
                verdict=verdict,
                message=message,
            )
        )

    priority = {"chronic": 0, "watch": 1, "fading": 2, "new": 3, "fixed": 4}
    rows.sort(key=lambda r: (priority[r.verdict.status], -r.errors))
    return rows[:MAX_ITEMS]


def expired_audio_days(today: date | None = None) -> list[str]:
    """Days whose raw audio should be deleted tonight. Counts are kept.

    Reads the session folders on disk, not the tally file. Audio recorded on a
    day that was never analysed has no tally, and keying off tallies meant
    exactly those days -- the ones a failed or skipped job left behind -- were
    the ones never cleaned up.
    """
    today = today or date.today()
    cutoff = (today - timedelta(days=AUDIO_RETENTION_DAYS)).isoformat()
    sessions = config.DATA_DIR / "sessions"
    days = {day for day in _load()}
    if sessions.exists():
        days |= {folder.name for folder in sessions.iterdir() if folder.is_dir()}
    return sorted(day for day in days if day < cutoff)


def purge_expired_audio(today: date | None = None) -> tuple[int, float]:
    """Delete audio past the retention window. Returns (files, megabytes).

    Deliberately independent of analysis. It used to run only at the end of a
    successful nightly job, so a laptop that was on battery at 23:30 every
    night -- the normal case -- never cleaned up at all, and an hour of speech
    is 115 MB. Deleting files is cheap and safe; it runs regardless.
    """
    removed = 0
    freed = 0.0
    for day in expired_audio_days(today):
        folder = config.DATA_DIR / "sessions" / day
        if not folder.exists():
            continue
        for wav in folder.glob("*.wav"):
            freed += wav.stat().st_size
            wav.unlink()
            removed += 1
        try:
            folder.rmdir()
        except OSError:
            pass  # something else is in there; leave it alone
    return removed, round(freed / 1e6, 1)


if __name__ == "__main__":
    for row in tonights_report():
        print(f"{row.verdict.status:8} {row.lower_bound:.2f}  {row.contrast:10} "
              f"{', '.join(row.words[:5])}")
        print(f"         {row.message}")
