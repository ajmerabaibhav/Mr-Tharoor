"""Is Mr Tharoor actually right? The only honest way to know is to ask you.

Every threshold in evidence.py is currently a judgement call. The report
threshold, the pooling strength, the prior -- all of them are my estimate of
what should work, and an estimate that is never checked is just a confident
guess. This module is how the guess becomes a number.

The loop is deliberately small enough to actually do:

    roy check          hear your clip, hear the correct word, say yes or no
    roy score          what those answers add up to

From that you get the two numbers that matter, and they are different
questions with different costs:

    PRECISION   of the things Mr Tharoor flagged, how many were really wrong?
                Low precision means false accusations, and false accusations
                are what make you stop opening the report.

    RECALL      of the things you really got wrong, how many did he catch?
                Low recall means a quiet report that misses your actual
                habits. Less annoying, equally useless.

Precision is cheap to measure: label what he flagged. Recall is expensive,
because it needs you to judge things he said nothing about, so `roy check
--audit` samples a handful of unflagged words at random and asks about those.
A sample gives an estimate with an honest interval rather than a false
certainty.

Counts are reported as intervals, not points. Eight out of ten correct is not
"80% accurate" when n is ten; it is somewhere between 49% and 94%, and saying
so is the difference between a measurement and a vibe.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime

from . import config, evidence

LABELS_FILE = config.DATA_DIR / "labels.json"

# Judgements you can give a single flagged or sampled item.
HIT = "hit"  # he flagged it and you agree you said it wrong
FALSE_ALARM = "false_alarm"  # he flagged it and you said it fine
MISS = "miss"  # he said nothing and you had said it wrong
CLEAN = "clean"  # he said nothing and you had said it right
UNSURE = "unsure"  # you could not tell. Counted separately, never as either.

VERDICTS = (HIT, FALSE_ALARM, MISS, CLEAN, UNSURE)


@dataclass
class Label:
    """One human judgement. This is the ground truth the whole tool is tuned to."""

    day: str  # the day the speech happened
    word: str
    contrast: str
    verdict: str
    clip: str | None = None  # path to your audio, so a label can be re-checked
    lower_bound: float | None = None  # what Mr Tharoor believed at the time
    labelled_at: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {self.verdict!r}, expected one of {VERDICTS}")
        if not self.labelled_at:
            self.labelled_at = datetime.now().isoformat(timespec="seconds")


def _load() -> list[dict]:
    if not LABELS_FILE.exists():
        return []
    try:
        return json.loads(LABELS_FILE.read_text())
    except json.JSONDecodeError:
        dead = config.quarantine(LABELS_FILE)
        print(f"mr-tharoor: labels were unreadable, kept a copy at {dead}")
        return []


def record(label: Label) -> None:
    """Append one judgement. Never overwrites an earlier one: if you change
    your mind, both answers are kept and the later one wins, because knowing
    that you changed your mind is itself a signal about a borderline call."""
    labels = _load()
    labels.append(asdict(label))
    config.write_json_atomically(LABELS_FILE, labels)


def labels(since: date | None = None) -> list[Label]:
    out = []
    seen: dict[tuple[str, str, str], Label] = {}
    for raw in _load():
        label = Label(**raw)
        if since and label.day < since.isoformat():
            continue
        seen[(label.day, label.word, label.contrast)] = label  # later wins
    out = list(seen.values())
    out.sort(key=lambda label: label.labelled_at)
    return out


def _interval(hits: int, total: int) -> tuple[float, float, float]:
    """Jeffreys interval. Reuses the beta functions already in evidence.py.

    A point estimate from ten samples is a lie told with a decimal place, so
    every rate here comes back as (low, estimate, high).
    """
    if total == 0:
        return (0.0, 0.0, 1.0)
    a, b = hits + 0.5, total - hits + 0.5
    return (
        evidence.beta_ppf(0.05, a, b),
        hits / total,
        evidence.beta_ppf(0.95, a, b),
    )


@dataclass
class Scorecard:
    """What the labels say, with honest uncertainty."""

    hits: int
    false_alarms: int
    misses: int
    clean: int
    unsure: int

    @property
    def flagged(self) -> int:
        return self.hits + self.false_alarms

    @property
    def audited(self) -> int:
        return self.misses + self.clean

    @property
    def precision(self) -> tuple[float, float, float]:
        """Of what he flagged, how much was really wrong."""
        return _interval(self.hits, self.flagged)

    @property
    def recall(self) -> tuple[float, float, float]:
        """Of what you really got wrong, how much did he catch?

        Estimated from the audit sample: the sampled words he said nothing
        about give a miss rate, which is what recall is missing.
        """
        really_wrong = self.hits + self.misses
        return _interval(self.hits, really_wrong)

    @property
    def verdict(self) -> str:
        if self.flagged < 10:
            return f"Not enough labels yet. {self.flagged} flagged items judged, want 20+."
        low, est, _ = self.precision
        if low >= 0.80:
            return "Trustworthy. Four in five flags are real, at worst."
        if low >= 0.60:
            return "Usable, but it cries wolf sometimes. Consider raising the threshold."
        if est >= 0.50:
            return "Too noisy to trust. Raise REPORT_THRESHOLD in evidence.py."
        return "Broken. More than half the flags are wrong. Do not tune, debug."


def scorecard(since: date | None = None) -> Scorecard:
    counts: defaultdict[str, int] = defaultdict(int)
    for label in labels(since):
        counts[label.verdict] += 1
    return Scorecard(
        hits=counts[HIT],
        false_alarms=counts[FALSE_ALARM],
        misses=counts[MISS],
        clean=counts[CLEAN],
        unsure=counts[UNSURE],
    )


def by_contrast(since: date | None = None) -> dict[str, Scorecard]:
    """Which sounds he is good at, and which he is guessing on.

    This is the actionable half. A tool that is 90% right on /v/ and 30% right
    on vowels should stop reporting vowels until that is fixed, rather than
    quietly poisoning your trust in the whole report.
    """
    grouped: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    for label in labels(since):
        grouped[label.contrast][label.verdict] += 1
    return {
        contrast: Scorecard(
            hits=counts[HIT],
            false_alarms=counts[FALSE_ALARM],
            misses=counts[MISS],
            clean=counts[CLEAN],
            unsure=counts[UNSURE],
        )
        for contrast, counts in sorted(grouped.items())
    }


def suggested_threshold(since: date | None = None) -> tuple[float, str] | None:
    """Where the threshold should sit, judged by your own labels.

    Walks candidate thresholds and picks the lowest one whose precision lower
    bound still clears 0.80. Lower threshold means more caught; the bound is
    what stops it from also meaning more false accusations.
    """
    scored = [label for label in labels(since) if label.lower_bound is not None]
    if len(scored) < 20:
        return None

    best: tuple[float, str] | None = None
    for candidate in [x / 20 for x in range(4, 17)]:  # 0.20 to 0.80
        kept = [label for label in scored if label.lower_bound >= candidate]
        hits = sum(1 for label in kept if label.verdict == HIT)
        flagged = sum(1 for label in kept if label.verdict in (HIT, FALSE_ALARM))
        if flagged < 8:
            continue
        low, _, _ = _interval(hits, flagged)
        if low >= 0.80:
            best = (
                candidate,
                f"{hits}/{flagged} correct at threshold {candidate:.2f} "
                f"(precision at least {low:.0%})",
            )
            break
    return best
