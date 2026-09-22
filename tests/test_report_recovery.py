"""Failures must be visible, retryable, and must preserve a working report."""

import argparse
import json
from datetime import date, datetime, timedelta
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


def fake_browser(monkeypatch, fail=False):
    monkeypatch.setattr(config, "user_name", lambda: "Test")
    monkeypatch.setattr(report, "CHROMIUM", Path("/fake/browser"))
    monkeypatch.setattr(report.shutil, "which", lambda name: None)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if fail:
            return SimpleNamespace(returncode=1)
        target = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--print-to-pdf="))
        Path(target).write_bytes(b"%PDF-1.4\n" + b"x" * 1200)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(report.subprocess, "run", run)
    return calls


def test_failed_export_preserves_previous_pdf(monkeypatch):
    day = date.today()
    path = config.REPORTS_DIR / f"{day}.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"previous" * 200)
    before = path.read_bytes()
    calls = fake_browser(monkeypatch, fail=True)
    output = report.write([], day)
    assert "pdf" not in output
    assert path.read_bytes() == before
    assert len(calls) == 2
    assert "--single-process" in calls[1]


def test_pdf_repair_uses_saved_results_and_updates_status(monkeypatch):
    day = date.today() - timedelta(days=1)
    daily.save([], day)
    metadata = {"version": 2, "completed_at": datetime.now().isoformat(), "outputs": ["html"]}
    fake_browser(monkeypatch)
    assert report.repair_exports(day, metadata)
    assert report.valid_pdf(config.REPORTS_DIR / f"{day}.pdf")
    assert "pdf" in json.loads((config.REPORTS_DIR / f"{day}-analysis.json").read_text())["outputs"]


def test_open_report_puts_pdf_in_preview_after_interactive_review(monkeypatch):
    day = date.today() - timedelta(days=1)
    html_path = config.REPORTS_DIR / f"{day}.html"
    pdf_path = html_path.with_suffix(".pdf")
    html_path.write_text("report")
    pdf_path.write_bytes(b"%PDF-1.4\n" + b"x" * 1200)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(report.subprocess, "run", run)
    assert report.open_report(day) == str(pdf_path)
    assert calls == [
        ["open", str(html_path)],
        ["open", "-a", "Preview", str(pdf_path)],
    ]


def test_open_report_falls_back_to_html_when_pdf_is_missing(monkeypatch):
    day = date.today() - timedelta(days=1)
    html_path = config.REPORTS_DIR / f"{day}.html"
    html_path.write_text("report")
    monkeypatch.setattr(
        report.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    assert report.open_report(day) == str(html_path)


def test_pending_repairs_missing_export_without_reanalysing(monkeypatch):
    for back in range(1, 4):
        day = date.today() - timedelta(days=back)
        daily.save([], day)
        config.write_json_atomically(config.REPORTS_DIR / f"{day}-analysis.json",
                                     {"version": 2, "completed_at": datetime.now().isoformat()})
    fake_browser(monkeypatch)
    monkeypatch.setattr(cli, "cmd_analyse_day", lambda args: pytest.fail("decoded completed audio again"))
    assert cli.cmd_analyse_pending(argparse.Namespace(force=True)) == 0
    assert len(list(config.REPORTS_DIR.glob("*.pdf"))) == 3


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
    assert calls[:3] == [str(date.today() - timedelta(days=back)) for back in range(1, 4)]


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
