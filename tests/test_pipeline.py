"""Regression checks for false corrections and the automatic review pipeline."""

import argparse
import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from mr_tharoor import accuracy, cli, config, daily, grammar, listen, remind, report, schedule, streaks, wispr


def finding(word="version", contrast="v->w", **overrides):
    values = dict(word=word, contrast=contrast, said="w", should_be="v", second=1.0,
                  confidence=0.95, source="source", sentence="The new version is available.",
                  analysis_version=daily.ANALYSIS_VERSION)
    return daily.Finding(**(values | overrides))


def seed(day=None, count=30, errors=27):
    day = day or date.today()
    streaks.record_day(day, [streaks.Finding("version", "v->w", count, errors, 1.0,
                                            analysis_version=daily.ANALYSIS_VERSION)])


def test_sentence_only_receives_its_own_audio(tmp_path, monkeypatch):
    rate = 16000
    audio = np.concatenate([np.ones(rate), np.full(rate, 0.5), np.zeros(rate)]).astype("float32")
    source = tmp_path / "source.wav"
    sf.write(source, audio, rate, subtype="FLOAT")
    calls = []

    def analyse(path, text, label, **kwargs):
        samples, _ = sf.read(path)
        calls.append((samples, text, kwargs))
        return []

    monkeypatch.setattr(daily, "findings_for", analyse)
    segments = [
        {"start": 0, "end": 1, "text": "first", "words": [{"word": "first", "probability": 0.99}]},
        {"start": 1, "end": 2, "text": "second", "words": [{"word": "second", "probability": 0.4}]},
    ]
    daily.findings_for_segments(str(source), segments, "example", tallies=[])
    assert len(calls) == 2
    assert len(calls[0][0]) == len(calls[1][0]) == rate
    assert np.allclose(calls[0][0], 1.0)
    assert np.allclose(calls[1][0], 0.5)
    assert calls[1][2]["offset"] == 1
    assert calls[1][2]["excluded_words"] == {"second"}


def test_rewrite_does_not_become_pronunciation_ground_truth():
    assert "mission" in daily.uncertain_words("the mission is live", "the version is live")
    assert daily.uncertain_words("It's live.", "It’s live!") == set()


def test_repeated_homograph_can_have_two_pronunciations():
    forms = listen.variants("read")
    assert len(forms) > 1
    actual = [listen.Token(p, 0.99, i * 0.1) for i, p in enumerate(forms[0] + forms[1])]
    expected, _, _ = listen.expected_with_words("read read", actual)
    assert tuple(expected) == forms[0] + forms[1]


def test_ctc_confidence_uses_whole_run_and_keeps_blank_separated_repeats():
    tokens = listen._collapse_frames([1, 1, 0, 1, 2], [0.6, 1, 1, 0.9, 1],
                                    {1: "v", 2: "|"}, 0, 0.02)
    assert len(tokens) == 2
    assert tokens[0].confidence == 0.8
    assert tokens[0].second == 0.01
    assert tokens[1].symbol == "v"


def mock_audio(monkeypatch, phones, quality=1.0):
    monkeypatch.setattr(listen, "audio_quality", lambda _: {"usable": quality > 0, "weight": quality})
    monkeypatch.setattr(listen, "heard", lambda _: [listen.Token(p, 0.95, i * 0.1) for i, p in enumerate(phones)])


def test_correct_word_is_not_flagged(monkeypatch):
    mock_audio(monkeypatch, listen.canonical("version"))
    result = listen.analyse("unused.wav", "version")
    assert result["scored"] == []
    assert result["contrast_chances"][("version", "v->w")] == 1


def test_clear_isolated_contrast_can_still_be_detected(monkeypatch):
    phones = list(listen.canonical("version"))
    phones[0] = "w"
    mock_audio(monkeypatch, phones)
    result = listen.analyse("unused.wav", "version")
    assert [d.contrast for d in result["scored"]] == ["v->w"]
    assert not listen.analyse("unused.wav", "version", excluded_words={"version"})["scored"]


def test_untracked_audio_has_no_evidence(monkeypatch):
    mock_audio(monkeypatch, ["k", "æ"])
    result = listen.analyse("unused.wav", "version")
    assert result["scored"] == []
    assert result["contrast_chances"] == {}


def test_weak_vowel_and_alignment_debris_are_not_errors():
    diff = listen.Diff("æ", "ɛ", "ae->e", 0.99, 1, word="than")
    assert not listen._locally_supported(diff, [diff], ["ð", "æ", "n"])
    diff = listen.Diff("v", "w", "v->w", 0.99, 0, word="version")
    debris = listen.Diff("ɚ", None, None, 0, 1)
    assert not listen._locally_supported(diff, [diff, debris], ["v", "ɚ", "ʒ", "ə", "n"])


def test_silent_audio_never_loads_phoneme_model(monkeypatch):
    monkeypatch.setattr(listen, "audio_quality", lambda _: {"usable": False, "weight": 0})
    monkeypatch.setattr(listen, "heard", lambda _: (_ for _ in ()).throw(AssertionError("model loaded")))
    assert listen.analyse("unused.wav", "version")["scored"] == []


def test_counts_include_clean_words_once(monkeypatch):
    result = {"quality": {"weight": 1}, "agreement": 1, "scored": [],
              "contrast_chances": {("version", "v->w"): 8, ("very", "v->w"): 12}}
    monkeypatch.setattr(listen, "analyse", lambda *a, **k: result)
    tallies = []
    assert daily.findings_for("unused", "", "test", tallies=tallies) == []
    assert sum(t.said for t in tallies) == 20
    assert sum(t.wrong for t in tallies) == 0
    streaks.record_day(date.today(), tallies)
    assert len(streaks.observations(min_version=2)) == 2


def test_clean_recordings_reduce_reported_error_rate():
    seed()
    before = daily.trustworthy_contrasts([finding()])["v->w"]
    streaks.record_day(date.today(), [streaks.Finding("version", "v->w", 30, 27, 1, 2),
                                    streaks.Finding("very", "v->w", 1000, 0, 1, 2)])
    after = daily.trustworthy_contrasts([finding()])["v->w"]
    assert after < before
    assert daily.group([finding()]) == {}


def test_no_fallback_or_legacy_findings():
    assert daily.group([finding()]) == {}
    seed()
    assert daily.group([finding(analysis_version=0)]) == {}
    assert daily.group([finding(confidence=0.5)]) == {}
    assert "v->w" in daily.group([finding()])


def test_repeated_analysis_does_not_duplicate_counts():
    rows = [streaks.Finding("version", "v->w", 5, 2, 1, 2)] * 2
    streaks.record_day(date.today(), rows)
    streaks.record_day(date.today(), rows)
    observations = streaks.observations()
    assert len(observations) == 1
    assert observations[0].opportunities == 10
    assert observations[0].error_weight == 4


def test_style_and_regional_phrases_are_not_grammar_errors():
    for text in ["Kindly send the same document", "Please prepone this meeting",
                 "An order for the office", "We do the needful", "The company is growing"]:
        assert grammar.compare(text, "A model wrote something completely different") == []
    assert not grammar._same_stem("computer", "company")
    assert not grammar._same_stem("thing", "think")


def test_local_grammar_rules_work_without_rewritten_text():
    rows = grammar.check("He don’t discuss about the plan", "dictation1")
    assert {r.should_be for r in rows} == {"he doesn't", "discuss"}
    assert all(r.basis == "rule" for r in rows)
    assert grammar.compare("I am engineer", "I am an engineer") == []
    assert grammar.compare("I am engineer today", "I am an engineer today", edited=True)[0].basis == "user_edit"


def test_grammar_habits_require_distinct_sources():
    one = grammar.check("he don't know", "one")
    two = grammar.check("he don't know", "two")
    assert grammar.summarise(one + one)[0]["times"] == 1
    assert grammar.summarise(one + two)[0]["times"] == 2


def test_reminders_ignore_legacy_and_repeat_analysis(monkeypatch):
    old = remind.Card("old", "v->w", "w", "v", due="2020-01-01T00:00:00")
    remind._save([old])
    assert remind.due_now() == []
    assert remind.enqueue([finding()]) == 0
    seed()
    assert remind.enqueue([finding()]) == 1
    remind.answer("version", "v->w", True)
    remind.enqueue([finding()])
    assert next(c for c in remind._load() if c.word == "version").correct_streak == 1


def test_reminders_have_actual_daily_limit(monkeypatch):
    cards = [remind.Card(str(n), "v->w", "w", "v", due="2020-01-01T00:00:00",
                        analysis_version=2, last_seen=str(date.today())) for n in range(6)]
    remind._save(cards)
    monkeypatch.setattr(remind, "may_interrupt", lambda: (True, ""))
    monkeypatch.setattr(remind, "notify", lambda *a, **k: True)
    assert remind.run()["sent"] == 3
    assert remind.run()["sent"] == 0


def test_false_alarm_feedback_suppresses_report_and_reminder():
    seed()
    remind.enqueue([finding()])
    accuracy.record(accuracy.Label(str(date.today()), "version", "v->w", accuracy.FALSE_ALARM))
    assert daily.group([finding()]) == {}
    assert streaks.observations() == []
    assert remind.due_now() == []


def test_latest_report_after_weekend_uses_completed_version():
    day = date.today() - timedelta(days=3)
    (config.REPORTS_DIR / f"{day}.html").write_text("report")
    assert report.latest_day() is None
    config.write_json_atomically(config.REPORTS_DIR / f"{day}-analysis.json", {"version": 2})
    assert report.latest_day() == day


def test_schedule_handles_spaces_and_retries(monkeypatch):
    monkeypatch.setattr(schedule.shutil, "which", lambda _: "/A folder/venv/bin/tharoor")
    job = schedule.plist_for("com.tharoor.morning", schedule.JOBS["com.tharoor.morning"])
    assert job["ProgramArguments"][0] == "/A folder/venv/bin/tharoor"
    assert job["RunAtLoad"] and job["StartInterval"] == 900
    assert "--automatic" in job["ProgramArguments"]
    assert "analyse-pending" in schedule.JOBS["com.tharoor.nightly"]["args"]


def test_analysis_lock_excludes_second_process():
    with schedule.job_lock("test") as first:
        assert first
        with schedule.job_lock("test") as second:
            assert not second
    with schedule.job_lock("test") as again:
        assert again


def test_pending_retries_previous_day_after_midnight(monkeypatch):
    yesterday = date.today() - timedelta(days=1)
    for back in range(1, 4):
        day = date.today() - timedelta(days=back)
        config.write_json_atomically(config.REPORTS_DIR / f"{day}-analysis.json",
                                     {"version": 2, "completed_at": datetime.now().isoformat()})
    config.write_json_atomically(config.REPORTS_DIR / f"{yesterday}-analysis.json",
                                 {"version": 2, "completed_at": f"{yesterday}T23:35:00"})
    calls = []
    monkeypatch.setattr(cli, "cmd_analyse_day", lambda args: calls.append(args.day) or 0)
    cli.cmd_analyse_pending(argparse.Namespace(force=True))
    assert str(yesterday) in calls


def test_empty_day_is_completed_and_saved(monkeypatch):
    from mr_tharoor import listener, log

    monkeypatch.setattr(log, "get", lambda *a: SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                                             error=lambda *a: None))
    monkeypatch.setattr(streaks, "purge_expired_audio", lambda *a: (0, 0))
    monkeypatch.setattr(schedule, "on_battery", lambda: False)
    monkeypatch.setattr(listener, "todays_audio", lambda *a: [])
    monkeypatch.setattr(report, "write", lambda *a, **k: {"html": "report.html"})
    assert cli.cmd_analyse_day(argparse.Namespace(day=str(date.today()), force=False)) == 0
    marker = json.loads((config.REPORTS_DIR / f"{date.today()}-analysis.json").read_text())
    assert marker["opportunities"] == marker["shown"] == 0
    assert daily.load(date.today()) == []


def test_wispr_snapshot_is_read_only_and_does_not_require_audio(tmp_path, monkeypatch):
    db = tmp_path / "wispr.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE History (transcriptEntityId TEXT, asrText TEXT, formattedText TEXT, "
                 "editedText TEXT, audio BLOB, timestamp TEXT, status TEXT, app TEXT)")
    conn.execute("INSERT INTO History VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 ("id", "he don't know", "he doesn't know", "", b"a" * 1500,
                  "2026-09-20 08:00:00.000 +00:00", "formatted", "test"))
    conn.commit()
    conn.close()
    before = db.read_bytes()
    monkeypatch.setattr(wispr, "DB_PATH", db)
    rows = wispr.dictations(with_audio=False)
    assert len(rows) == 1 and rows[0].audio is None
    assert rows[0].heard == "he don't know"
    assert db.read_bytes() == before


def test_report_does_not_call_candidates_mistakes():
    rendered = report.build_html([finding()], date.today())
    assert "0 examples across 0 sound patterns" in rendered
    assert "No pronunciation pattern passed" in rendered
    assert "1 mistakes" not in rendered
