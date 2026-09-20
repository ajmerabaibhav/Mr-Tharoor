"""The daemon must recover after midnight, restarts, and unavailable reports."""

import argparse
import datetime as dates
import json
from types import SimpleNamespace

from mr_tharoor import cli, config, context, daily, listener, micgate, remind, report


def test_reading_budget_does_not_count_saved_audio_twice(monkeypatch):
    monkeypatch.setattr(listener, "_reading_seconds_on_disk", lambda day=None: 100)
    worker = listener.Listener()
    assert worker.reading_budget_left() == listener.READING_BUDGET_MINUTES * 60 - 100
    worker.reading_used += 10
    worker.stats.reading_seconds += 10
    monkeypatch.setattr(listener, "_reading_seconds_on_disk", lambda day=None: 110)
    assert worker.reading_budget_left() == listener.READING_BUDGET_MINUTES * 60 - 110


def test_reading_budget_resets_next_day(monkeypatch):
    monkeypatch.setattr(listener, "_reading_seconds_on_disk", lambda day=None: 0)
    worker = listener.Listener()
    worker.reading_used = 1200
    worker.reading_day -= dates.timedelta(days=1)
    assert worker.reading_budget_left() == 1200


def test_unknown_microphone_activity_does_not_open_capture(monkeypatch):
    monkeypatch.setattr(micgate, "mic_users", lambda: [])
    monkeypatch.setattr(micgate, "is_mic_in_use", lambda: True)
    monkeypatch.setattr(context, "frontmost", lambda: "com.apple.Preview")
    assert context.decide().mode == context.LISTEN_NEVER


def test_ambiguous_holder_does_not_trigger_sampling(monkeypatch):
    monkeypatch.setattr(micgate, "mic_users", lambda: [micgate.MicUser(99, "com.apple.Siri")])
    monkeypatch.setattr(context, "dictating", lambda: None)
    monkeypatch.setattr(context, "frontmost", lambda: "com.apple.Preview")
    assert context.decide().mode == context.LISTEN_NEVER


def test_renamed_daemon_is_still_excluded(monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="python /bin/tharoor listen\n"))
    assert micgate._is_our_listener(12)


def test_automatic_morning_opens_only_once_and_retries_missing_report(monkeypatch):
    class Morning(dates.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.combine(dates.date.today(), dates.time(10))

    monkeypatch.setattr(dates, "datetime", Morning)
    monkeypatch.setattr(micgate, "is_mic_in_use", lambda: False)
    monkeypatch.setattr(config, "user_name", lambda: "Test")
    monkeypatch.setattr(remind, "run", lambda: {"sent": 0})
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    calls = []
    monkeypatch.setattr(report, "open_report", lambda day: calls.append(day) or "report.html")
    args = argparse.Namespace(automatic=True)
    assert cli.cmd_morning(args) == 0
    assert calls == []
    yesterday = dates.date.today() - dates.timedelta(days=1)
    (config.REPORTS_DIR / f"{yesterday}.html").write_text("report")
    config.write_json_atomically(config.REPORTS_DIR / f"{yesterday}-analysis.json", {"version": 2})
    daily.save([], yesterday)
    assert cli.cmd_morning(args) == 0
    assert cli.cmd_morning(args) == 0
    assert calls == [yesterday]
    state = json.loads((config.DATA_DIR / "morning.json").read_text())
    assert state["opened_on"] == str(dates.date.today())


def test_report_with_no_candidates_has_no_habit_greeting(monkeypatch):
    monkeypatch.setattr(daily, "trustworthy_contrasts", lambda *a, **k: {"v->w": 0.9})
    rendered = report.build_html([], dates.date.today())
    assert "there is a habit here" not in rendered
