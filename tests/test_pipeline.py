"""Regression checks for false corrections and the automatic review pipeline."""

import argparse
import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from mr_tharoor import cli, config, grammar, report, schedule, wispr


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
    from mr_tharoor import log

    monkeypatch.setattr(log, "get", lambda *a: SimpleNamespace(info=lambda *a: None, warning=lambda *a: None,
                                                             error=lambda *a: None))
    monkeypatch.setattr(schedule, "on_battery", lambda: False)
    assert cli.cmd_analyse_day(argparse.Namespace(day=str(date.today()), force=False)) == 0
    marker = json.loads((config.REPORTS_DIR / f"{date.today()}-analysis.json").read_text())
    assert marker["grammar_found"] == 0 and marker["version"] == report.ANALYSIS_VERSION
    assert (config.REPORTS_DIR / f"{date.today()}.html").exists()


def test_wispr_snapshot_is_read_only(tmp_path, monkeypatch):
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
    rows = wispr.dictations()
    assert len(rows) == 1
    assert rows[0].heard == "he don't know"
    assert db.read_bytes() == before


def test_report_shows_corrections_and_no_pronunciation():
    row = asdict(grammar.check("he don't know", "one", "typed")[0]) | {"times": 1}
    rendered = report.build_html(date.today(), [row])
    assert "he doesn&#x27;t" in rendered and "What you typed" in rendered
    assert "Pronunciation" not in rendered and "<audio" not in rendered
