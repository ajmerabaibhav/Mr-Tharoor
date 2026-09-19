"""The judgement calls. If these are wrong the whole report is noise.

Run: python3 tests/test_streaks.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mr_tharoor import streaks
from mr_tharoor.streaks import Finding

TODAY = date(2026, 9, 15)


def fresh_history(tmp: Path):
    streaks.HISTORY_FILE = tmp / "history.json"
    if streaks.HISTORY_FILE.exists():
        streaks.HISTORY_FILE.unlink()


def seed(days_ago_list, word="version", contrast="v->w", said=9, wrong=7):
    for n in days_ago_list:
        streaks.record_day(
            TODAY - timedelta(days=n),
            [Finding(word=word, contrast=contrast, said=said, wrong=wrong, confidence=0.9)],
        )


def test_filter_drops_model_noise():
    """Low confidence is the model guessing, not you mispronouncing."""
    assert not streaks.passes_filter(Finding("version", "v->w", 9, 7, confidence=0.4))
    assert streaks.passes_filter(Finding("version", "v->w", 9, 7, confidence=0.9))
    print("confidence gate             ok")


def test_filter_drops_one_offs():
    """Said once, wrong once, is a slip. Said nine times, wrong seven, is a habit."""
    # said once and wrong once = 100% error rate, so it survives on rate
    assert streaks.passes_filter(Finding("gnocchi", "k->tʃ", said=1, wrong=1, confidence=0.9))
    # said four times, wrong once: enough occurrences that one error counts
    assert streaks.passes_filter(Finding("version", "v->w", said=4, wrong=1, confidence=0.9))
    # said twice, wrong zero, nothing to report
    assert not streaks.passes_filter(Finding("version", "v->w", said=2, wrong=0, confidence=0.9))
    print("frequency gate              ok")


def test_two_days_is_not_yet_a_habit(tmp: Path):
    """The whole point of your question: do not shout after two days."""
    fresh_history(tmp)
    seed([0, 1])
    verdict = next(v for v in streaks.verdicts(TODAY) if v.word == "version")
    assert verdict.status == "watch", verdict
    assert not verdict.is_genuine
    print("2 days -> watch, not shout  ok")


def test_three_days_in_five_is_genuine(tmp: Path):
    """Three of five days and Mr Tharoor is allowed to call it a real problem."""
    fresh_history(tmp)
    seed([0, 2, 4])
    verdict = next(v for v in streaks.verdicts(TODAY) if v.word == "version")
    assert verdict.status == "chronic", verdict
    assert verdict.is_genuine
    assert "habit" in verdict.message
    print("3 of 5 days -> chronic      ok")


def test_a_beaten_habit_is_reported_as_fixed(tmp: Path):
    """Being told you beat one is the only reason anyone opens this twice."""
    fresh_history(tmp)
    seed([5, 6, 7, 8])  # chronic last week
    for n in (0, 1, 2, 3, 4):  # clean all week, but still recording
        streaks.record_day(TODAY - timedelta(days=n), [])
    verdict = next(v for v in streaks.verdicts(TODAY) if v.word == "version")
    assert verdict.status == "fixed", verdict
    print("beaten habit -> fixed       ok")


def test_a_holiday_is_not_improvement(tmp: Path):
    """No recordings means no evidence. It must not read as progress."""
    fresh_history(tmp)
    seed([5, 6, 7, 8])
    # days 0-4 simply never recorded, laptop shut
    verdict = next((v for v in streaks.verdicts(TODAY) if v.word == "version"), None)
    assert verdict is not None
    assert verdict.status == "fixed"
    assert streaks._clean_run({}, ("version", "v->w"), TODAY, 5) == 0, (
        "a day with no recording must not count toward a clean run"
    )
    print("holiday != improvement      ok")


def test_report_is_capped_but_keeps_the_win(tmp: Path):
    """Nobody reads a list of twenty. The one win still gets through."""
    fresh_history(tmp)
    for i in range(10):
        for n in (0, 1, 2):
            history_word = f"word{i}"
            existing = streaks._load().get((TODAY - timedelta(days=n)).isoformat(), [])
            streaks._save(
                {
                    **streaks._load(),
                    (TODAY - timedelta(days=n)).isoformat(): existing
                    + [
                        {
                            "word": history_word,
                            "contrast": "v->w",
                            "said": 9,
                            "wrong": 9 - i,
                            "confidence": 0.9,
                        }
                    ],
                }
            )
    report = streaks.tonights_report(TODAY)
    assert len(report) <= streaks.MAX_ITEMS, len(report)
    # ten words, all the same sound -> one lesson, not ten findings
    assert len(report) == 1, f"same contrast must collapse to one row, got {len(report)}"
    assert len(report[0].words) > 1, "the words themselves are still listed"
    # the fixture seeds error rates from 100% down to 0%, so the clean words
    # must NOT appear -- grouping is not an excuse to stop discriminating
    assert "word9" not in report[0].words, "a word with zero errors was reported"
    assert "word0" in report[0].words, "the worst word must be there"
    print(f"ten words -> {len(report)} lesson, "
          f"{len(report[0].words)} named   ok")


def test_audio_expiry_is_three_days(tmp: Path):
    """The CPU knob. Audio goes, tallies stay."""
    fresh_history(tmp)
    seed([0, 1, 2, 5, 9])
    expired = streaks.expired_audio_days(TODAY)
    assert (TODAY - timedelta(days=9)).isoformat() in expired
    assert (TODAY - timedelta(days=5)).isoformat() in expired
    assert (TODAY - timedelta(days=1)).isoformat() not in expired
    # and the counts for those expired days survive
    assert (TODAY - timedelta(days=9)).isoformat() in streaks._load()
    print("audio expires, counts stay  ok")


def test_rare_word_reaches_the_report(tmp: Path):
    """End to end: a word said once, on a sound he fails everywhere else,
    must appear in tonight's report. This is the behaviour the old hard
    filters made impossible."""
    fresh_history(tmp)
    for n in range(3):
        day = TODAY - timedelta(days=n)
        common = [
            Finding(word=f"w{i}", contrast="v->w", said=6, wrong=5, confidence=0.9)
            for i in range(12)
        ]
        streaks.record_day(day, common)
    # today only, said once, wrong once
    day_items = streaks._load()[TODAY.isoformat()]
    day_items.append(
        {"word": "vulnerable", "contrast": "v->w", "said": 1, "wrong": 1, "confidence": 0.9}
    )
    history = streaks._load()
    history[TODAY.isoformat()] = day_items
    streaks._save(history)

    report = streaks.tonights_report(TODAY)
    row = next(r for r in report if r.contrast == "v->w")
    assert "vulnerable" in row.words, f"rare word missing: {row.words}"
    assert "vulnerable" in row.borrowed_words, "should be marked as pooled evidence"
    assert len(report) <= streaks.MAX_ITEMS
    print("rare word reaches report    ok")
    print(f"    -> {row.message}")


def test_low_confidence_is_kept_not_deleted(tmp: Path):
    """The old gate deleted anything under 0.80. Twenty hesitant detections
    carry real information and must survive to be pooled."""
    fresh_history(tmp)
    streaks.record_day(
        TODAY, [Finding(word="version", contrast="v->w", said=20, wrong=14, confidence=0.6)]
    )
    stored = streaks._load()[TODAY.isoformat()]
    assert stored, "a 0.60 detection must be stored, not dropped"
    obs = streaks.observations()
    assert obs[0].error_weight == 14 * 0.6
    print("0.60 detections survive     ok")


def test_history_survives_a_torn_write(tmp: Path):
    """history.json is the only surviving record: the audio behind it is
    deleted after three days. A truncated write must never read as empty and
    get replaced, or weeks of evidence vanish without a word."""
    fresh_history(tmp)
    seed([0, 1, 2])
    assert len(streaks._load()) == 3

    streaks.HISTORY_FILE.write_text('{"2026-09-15": [{"word": "ver')  # torn
    assert streaks._load() == {}
    kept = list(tmp.glob("history.json.corrupt-*"))
    assert kept, "torn history must be kept for recovery"
    assert b"ver" in kept[0].read_bytes()
    for f in kept:
        f.unlink()
    print("torn history quarantined    ok")


def test_observations_honours_its_window(tmp: Path):
    """The window parameter used to be accepted and ignored: a caller asking
    for 7 days silently received 30."""
    fresh_history(tmp)
    seed([0, 3, 20])
    assert len(streaks.observations(window_days=7, today=TODAY)) == 2
    assert len(streaks.observations(window_days=30, today=TODAY)) == 3
    print("window is honoured          ok")


def main() -> int:
    tmp = Path(__file__).resolve().parent / "_tmp"
    tmp.mkdir(exist_ok=True)
    original = streaks.HISTORY_FILE
    try:
        test_filter_drops_model_noise()
        test_filter_drops_one_offs()
        test_two_days_is_not_yet_a_habit(tmp)
        test_three_days_in_five_is_genuine(tmp)
        test_a_beaten_habit_is_reported_as_fixed(tmp)
        test_a_holiday_is_not_improvement(tmp)
        test_report_is_capped_but_keeps_the_win(tmp)
        test_audio_expiry_is_three_days(tmp)
        test_rare_word_reaches_the_report(tmp)
        test_low_confidence_is_kept_not_deleted(tmp)
        test_history_survives_a_torn_write(tmp)
        test_observations_honours_its_window(tmp)
    finally:
        streaks.HISTORY_FILE = original
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
