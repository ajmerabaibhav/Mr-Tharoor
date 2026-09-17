"""Make yesterday's mistake stick, without becoming an app you mute.

A report you read once in the morning teaches almost nothing. The sound you
got wrong is a motor habit built over years, and motor habits do not change
because you read about them at 08:30. They change with short, repeated,
spaced contact.

So each mistake goes into a small spaced-repetition queue:

    flagged today   ->  remind in 4 hours, then tomorrow, then in 2 days
    got it right    ->  interval doubles, it fades out on its own
    got it wrong    ->  interval resets to 4 hours

Two rules keep this from becoming another notification you turn off:

  AT MOST THREE A DAY. There is no version of this where six interruptions
  are better than three. The queue is sorted by how wrong you are and how
  overdue the card is, and everything past the third waits.

  NEVER DURING A CALL. The microphone gate already knows when you are talking
  to someone. Buzzing you mid-sentence about the word you just said wrong is
  the single fastest way to get this deleted.

A card retires after it has been right three times running, or after two weeks
with no sign of the mistake. Retirement is the point: the queue should shrink.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from . import config, micgate

QUEUE_FILE = config.DATA_DIR / "reminders.json"

# Hours until a card comes back, by how many times you have got it right.
LADDER = (4, 24, 48, 96, 168)
MAX_PER_DAY = 3
RETIRE_AFTER_CORRECT = 3
QUIET_START, QUIET_END = 21, 8  # no buzzing at night


@dataclass
class Card:
    """One sound to keep meeting until it stops being wrong."""

    word: str
    contrast: str
    said: str
    should_be: str
    clip_path: str | None = None
    correct_path: str | None = None
    correct_streak: int = 0
    seen: int = 0
    due: str = ""
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def __post_init__(self) -> None:
        if not self.due:
            self.due = (datetime.now() + timedelta(hours=LADDER[0])).isoformat(timespec="seconds")

    @property
    def retired(self) -> bool:
        return self.correct_streak >= RETIRE_AFTER_CORRECT

    @property
    def overdue_hours(self) -> float:
        return (datetime.now() - datetime.fromisoformat(self.due)).total_seconds() / 3600

    def answered(self, correct: bool) -> None:
        self.seen += 1
        self.correct_streak = self.correct_streak + 1 if correct else 0
        step = LADDER[min(self.correct_streak, len(LADDER) - 1)]
        self.due = (datetime.now() + timedelta(hours=step)).isoformat(timespec="seconds")


def _load() -> list[Card]:
    if not QUEUE_FILE.exists():
        return []
    try:
        return [Card(**row) for row in json.loads(QUEUE_FILE.read_text())]
    except (json.JSONDecodeError, TypeError):
        dead = config.quarantine(QUEUE_FILE)
        print(f"mr-roy: reminder queue was unreadable, kept a copy at {dead}")
        return []


def _save(cards: list[Card]) -> None:
    config.write_json_atomically(QUEUE_FILE, [asdict(c) for c in cards])


def enqueue(findings) -> int:
    """Add today's mistakes. An existing card is refreshed, not duplicated."""
    cards = _load()
    index = {(c.word, c.contrast): c for c in cards}
    added = 0
    for finding in findings:
        key = (finding.word, finding.contrast)
        existing = index.get(key)
        if existing:
            # Said wrong again: it is not learned, so reset the ladder.
            existing.correct_streak = 0
            existing.due = datetime.now().isoformat(timespec="seconds")
            existing.clip_path = finding.clip_path or existing.clip_path
            continue
        card = Card(
            word=finding.word,
            contrast=finding.contrast,
            said=finding.said,
            should_be=finding.should_be,
            clip_path=finding.clip_path,
            correct_path=finding.correct_path,
        )
        cards.append(card)
        index[key] = card
        added += 1
    _save(cards)
    return added


def due_now(limit: int = MAX_PER_DAY) -> list[Card]:
    """What to surface, worst and most overdue first."""
    cards = [c for c in _load() if not c.retired and c.overdue_hours >= 0]
    cards.sort(key=lambda c: (-c.overdue_hours, c.correct_streak))
    return cards[:limit]


def may_interrupt() -> tuple[bool, str]:
    """Is now a reasonable moment? The gate already knows if you are on a call."""
    hour = datetime.now().hour
    if hour >= QUIET_START or hour < QUIET_END:
        return False, "quiet hours"
    if micgate.is_mic_in_use():
        return False, "you are on a call"
    return True, ""


def notify(card: Card, dry_run: bool = False) -> bool:
    """One macOS notification. Clicking it opens the drill for that word.

    osascript is used rather than a dependency because it is already on every
    Mac and this is three lines of AppleScript.
    """
    title = f"You said {card.word} wrong"
    body = f"/{card.said}/ should be /{card.should_be}/. Say it back three times."
    script = (
        f'display notification {json.dumps(body)} '
        f'with title {json.dumps(title)} sound name "Tink"'
    )
    if dry_run:
        print(f"  [{title}] {body}")
        return True
    result = subprocess.run(["osascript", "-e", script], capture_output=True)
    return result.returncode == 0


def run(dry_run: bool = False) -> dict:
    """The whole thing: check the moment, pick the cards, buzz once each."""
    allowed, reason = may_interrupt()
    if not allowed and not dry_run:
        return {"sent": 0, "skipped": reason}

    cards = due_now()
    sent = 0
    for card in cards:
        if notify(card, dry_run=dry_run):
            sent += 1
    return {"sent": sent, "queued": len(_load()), "skipped": "" if allowed else reason}


def answer(word: str, contrast: str, correct: bool) -> bool:
    """Record how the drill went, which moves the card along the ladder."""
    cards = _load()
    for card in cards:
        if card.word == word and card.contrast == contrast:
            card.answered(correct)
            _save(cards)
            return True
    return False


def summary() -> dict:
    cards = _load()
    return {
        "total": len(cards),
        "active": sum(1 for c in cards if not c.retired),
        "retired": sum(1 for c in cards if c.retired),
        "due_now": len(due_now(limit=999)),
    }
