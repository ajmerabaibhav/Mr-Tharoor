"""Did the English actually get better this week, or does it only feel that way.

One number: corrections per thousand words. Corrections alone say nothing --
a quiet week produces fewer of them without anything improving -- so the
count is always divided by how much you actually said and wrote.

Two rules keep this honest.

    Only days the same checker looked at are counted. Before 22 September the
    grammar rules found nothing at all, and comparing a week of that against a
    week of the real checker would show a magnificent collapse in your English
    that never happened.

    A difference smaller than the noise is reported as no difference. With a
    few thousand words a week the counts are small, and small counts move
    about on their own. The test is deliberately crude and deliberately
    conservative: twice the combined standard error, or it does not count.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

from . import config

WINDOW = 7


def _analysed_days(days: list[date]) -> list[date]:
    """Days whose grammar came from the current checker. Nothing else compares."""
    out = []
    for day in days:
        marker = config.REPORTS_DIR / f"{day}-analysis.json"
        if not marker.exists():
            continue
        try:
            if json.loads(marker.read_text()).get("grammar_engine") == "claude-cli":
                out.append(day)
        except (ValueError, TypeError):
            continue
    return out


def _findings(day: date) -> list[dict]:
    path = config.REPORTS_DIR / f"{day}-grammar-raw.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (ValueError, TypeError):
        return []


def _word_counts(days: list[date]) -> dict[date, int]:
    """How much you produced each day, from the same sources the checker read."""
    counts = {day: 0 for day in days}
    if not days:
        return counts
    try:
        from . import wispr

        if wispr.available():
            for d in wispr.dictations(with_audio=False):
                day = d.when.date()
                if day in counts:
                    counts[day] += len((d.heard or d.meant).split())
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import typed

        for day in days:
            counts[day] += sum(len(text.split()) for _, text in typed.for_day(day))
    except Exception:  # noqa: BLE001
        pass
    return counts


def _rate(found: int, words: int) -> float | None:
    return (found / words * 1000) if words else None


def _labels(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = (row.get("label") or row.get("kind") or "").lower()
        if key:
            out[key] = out.get(key, 0) + 1
    return out


def week(today: date | None = None) -> dict | None:
    """The last seven analysed days against the seven before them."""
    today = today or date.today()
    span = [today - timedelta(days=n) for n in range(0, WINDOW * 2)]
    analysed = set(_analysed_days(span))
    if not analysed:
        return None
    recent = [d for d in span[:WINDOW] if d in analysed]
    earlier = [d for d in span[WINDOW:] if d in analysed]
    words = _word_counts(recent + earlier)

    def side(days: list[date]) -> dict:
        found = sum(len(_findings(day)) for day in days)
        total = sum(words.get(day, 0) for day in days)
        return {"days": len(days), "found": found, "words": total,
                "rate": _rate(found, total)}

    now, before = side(recent), side(earlier)
    out = {"this_week": now, "last_week": before, "change": None, "verdict": "", "fixed": [],
           "persisting": []}
    if not now["words"]:
        out["verdict"] = "Not enough material this week to measure anything."
        return out
    if not before["days"] or not before["words"]:
        out["verdict"] = (f"{now['found']} corrections in {now['words']:,} words "
                          f"({now['rate']:.1f} per thousand). Next week can be compared with this one.")
        return out

    # Poisson-ish: the standard error of a count is its square root.
    se_now = math.sqrt(max(now["found"], 1)) / now["words"] * 1000
    se_before = math.sqrt(max(before["found"], 1)) / before["words"] * 1000
    noise = 2 * math.hypot(se_now, se_before)
    gap = before["rate"] - now["rate"]
    out["change"] = (gap / before["rate"] * 100) if before["rate"] else None
    if abs(gap) < noise:
        out["verdict"] = (
            f"{now['rate']:.1f} corrections per thousand words this week against "
            f"{before['rate']:.1f} last week. On {now['words']:,} words that difference is "
            f"smaller than the noise: nothing has been proved either way yet."
        )
    elif gap > 0:
        out["verdict"] = (
            f"{now['rate']:.1f} corrections per thousand words this week against "
            f"{before['rate']:.1f} last week: {out['change']:.0f}% fewer, and the gap is "
            "larger than this much material can produce by chance. That is an improvement."
        )
    else:
        out["verdict"] = (
            f"{now['rate']:.1f} corrections per thousand words this week against "
            f"{before['rate']:.1f} last week: more, not fewer. Worth reading the list below "
            "rather than explaining it away."
        )
    now_labels = _labels([row for day in recent for row in _findings(day)])
    was_labels = _labels([row for day in earlier for row in _findings(day)])
    out["fixed"] = sorted((k for k in was_labels if k not in now_labels),
                          key=lambda k: -was_labels[k])[:5]
    out["persisting"] = sorted((k for k in now_labels if k in was_labels),
                               key=lambda k: -now_labels[k])[:5]
    return out


if __name__ == "__main__":  # a check that does not need a week of history
    assert _rate(4, 2000) == 2.0 and _rate(0, 0) is None
    assert _labels([{"label": "Agreement"}, {"label": "agreement"}, {"kind": "article"}]) == {
        "agreement": 2, "article": 1}
    print("progress self-check ok")
