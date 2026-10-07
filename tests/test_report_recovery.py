"""Failures must be visible, retryable, and must preserve a working report."""

import argparse
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from mr_tharoor import cli, config, daily, listen, report, schedule


def test_install_rejects_false_success_from_launchctl(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(schedule, "service_state", lambda label: {"loaded": False, "detail": "missing"})
    calls = []

    def launch(*args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(schedule, "_launchctl", launch)
    with pytest.raises(schedule.InstallationError, match="installation failed"):
        schedule.install()
    assert any(call[:2] == ("bootstrap", schedule._domain()) for call in calls)
    assert not any(call[0] == "load" for call in calls)


def test_status_queries_gui_service_and_reports_crash(monkeypatch):
    calls = []

    def launch(*args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="state = not running\nlast exit code = 1\n", stderr="")

    monkeypatch.setattr(schedule, "_launchctl", launch)
    lines = schedule.status()
    assert all("last exit 1" in line for line in lines)
    assert all(call[0] == "print" and call[1].startswith("gui/") for call in calls)


def test_install_command_returns_failure(monkeypatch):
    def fail(**kwargs):
        raise schedule.InstallationError("not loaded")

    monkeypatch.setattr(schedule, "install", fail)
    assert cli.cmd_install(argparse.Namespace(remove=False, status=False, dry_run=False)) == 1


def test_report_is_html_only(monkeypatch):
    monkeypatch.setattr(config, "user_name", lambda: "Test")
    today = date.today()
    assert report.write([], today) == {"html": str(config.REPORTS_DIR / f"{today}.html")}
    assert not list(config.REPORTS_DIR.glob(f"{today}.pdf")) + list(config.REPORTS_DIR.glob(f"{today}.docx"))


def test_open_report_opens_the_page(monkeypatch):
    day = date.today() - timedelta(days=1)
    html_path = config.REPORTS_DIR / f"{day}.html"
    html_path.write_text("report")
    calls = []
    monkeypatch.setattr(report.subprocess, "run",
                        lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0))
    assert report.open_report(day) == str(html_path)
    assert calls == [["open", str(html_path)]]


def test_pending_repairs_missing_export_without_reanalysing(monkeypatch):
    # Today is seeded as well. After 23:30 the pending job includes the current
    # day, so a test that only seeded the three previous ones failed every night
    # between 23:30 and midnight -- on the clock, not on the code.
    for back in range(0, 4):
        day = date.today() - timedelta(days=back)
        daily.save([], day)
        finished = (datetime.combine(day, time(23, 30)) if back == 0 else datetime.now())
        config.write_json_atomically(config.REPORTS_DIR / f"{day}-analysis.json",
                                     {"version": 2, "completed_at": finished.isoformat()})
    monkeypatch.setattr(config, "user_name", lambda: "Test")
    for back in range(1, 4):
        (config.REPORTS_DIR / f"{date.today() - timedelta(days=back)}.html").unlink(missing_ok=True)
    monkeypatch.setattr(cli, "cmd_analyse_day", lambda args: pytest.fail("decoded completed audio again"))
    assert cli.cmd_analyse_pending(argparse.Namespace(force=True)) == 0
    for back in range(1, config.KEEP_DAYS + 1):  # older days are retention's to delete
        day = date.today() - timedelta(days=back)
        assert (config.REPORTS_DIR / f"{day}.html").exists(), f"no page rebuilt for {day}"


def test_partial_day_and_processing_counts_are_visible():
    day = date.today()
    rendered = report.build_html([], day, analysis={"completed_at": f"{day}T10:00:00",
            "sources": {"wispr": 5, "own": 2, "typed": 3}, "opportunities": 20, "candidates": 1})
    assert "5 Wispr recordings, 2 reading recordings and 3 typed messages read" in rendered
    assert "20 sound opportunities checked" in rendered
    assert "partial-day report" in rendered


def test_empty_report_explains_abstention_without_claiming_zero_quality():
    day = date.today() - timedelta(days=1)
    rendered = report.build_html(
        [], day, analysis={"completed_at": datetime.now().isoformat(), "opportunities": 51}
    )
    assert "checked 51 sound opportunities" in rendered
    assert "does not prove the speech was error-free" in rendered
    assert "no qualifying examples" in rendered
    assert '<div class="stat-value">0%</div>' not in rendered


def test_pending_prioritises_yesterday_and_continues_after_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "cmd_analyse_day", lambda args: calls.append(args.day) or 1)
    assert cli.cmd_analyse_pending(argparse.Namespace(force=True)) == 1
    kept = range(1, config.KEEP_DAYS + 1)  # daytime: yesterday and what retention still holds
    assert calls[:len(kept)] == [str(date.today() - timedelta(days=back)) for back in kept]
    # A day retention already deleted is never rebuilt (4 Oct, rebuilt on 7 Oct).
    assert str(date.today() - timedelta(days=config.KEEP_DAYS + 1)) not in calls


def test_daytime_preview_is_reanalysed_at_night(monkeypatch):
    import datetime as dates

    class Night(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.combine(date.today(), dates.time(23, 40))

    monkeypatch.setattr(dates, "datetime", Night)
    day = date.today()
    config.write_json_atomically(config.REPORTS_DIR / f"{day}-analysis.json",
                                 {"version": 2, "completed_at": f"{day}T11:00:00"})
    calls = []
    monkeypatch.setattr(cli, "cmd_analyse_day", lambda args: calls.append(args.day) or 0)
    cli.cmd_analyse_pending(argparse.Namespace(force=True))
    assert str(day) in calls


def test_cached_model_never_requests_network():
    calls = []

    def loader(name, *, local_files_only):
        calls.append(local_files_only)
        return "cached-model"

    assert listen._cached_first(loader, "model") == "cached-model"
    assert calls == [True]


def test_missing_model_still_downloads_on_first_use():
    calls = []

    def loader(name, *, local_files_only):
        calls.append(local_files_only)
        if local_files_only:
            raise FileNotFoundError("no cached model")
        return "downloaded-model"

    assert listen._cached_first(loader, "model") == "downloaded-model"
    assert calls == [True, False]


def test_model_computation_error_is_not_retried_as_download():
    def loader(name, *, local_files_only):
        raise RuntimeError("model is incompatible")

    with pytest.raises(RuntimeError, match="incompatible"):
        listen._cached_first(loader, "model")


def test_day_whose_grammar_failed_offline_is_redone_once_online(monkeypatch):
    # 5 Oct: lid shut mid-run, the grammar call ran in DarkWake with no network,
    # and the day was marked done with every typed message unchecked.
    yesterday = date.today() - timedelta(days=1)
    for back in range(0, 4):
        day = date.today() - timedelta(days=back)
        config.write_json_atomically(config.REPORTS_DIR / f"{day}-analysis.json", {
            "version": 2, "completed_at": (datetime.combine(day, time(23, 30)) if back == 0
                                           else datetime.now() - timedelta(hours=2)).isoformat(),
            "grammar_failed": ["typed"] if day == yesterday else []})
    monkeypatch.setattr(report, "repair_exports", lambda day, completed: True)
    calls = []
    monkeypatch.setattr(cli, "cmd_analyse_day", lambda args: calls.append(args.day) or 0)
    monkeypatch.setattr(cli, "_online", lambda: False)
    cli.cmd_analyse_pending(argparse.Namespace(force=True))
    assert calls == [], "re-ran with no network"
    monkeypatch.setattr(cli, "_online", lambda: True)
    cli.cmd_analyse_pending(argparse.Namespace(force=True))
    assert calls == [str(yesterday)]
