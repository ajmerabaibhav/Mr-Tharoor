"""Keep all automated checks away from the user's real data."""

import sys
import logging
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mr_tharoor import config, log, schedule, typed, wispr


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    # Deliberately failing export tests must not look like production failures.
    monkeypatch.setattr(log, "get", lambda name="": logging.getLogger(f"tharoor-test.{name}"))
    for name, suffix in (("ROOT", ""), ("DATA_DIR", "data"), ("REPORTS_DIR", "reports")):
        path = tmp_path / suffix
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, name, path)
    monkeypatch.setattr(wispr, "DB_PATH", tmp_path / "absent.sqlite")
    # The typing source reads the real ~/.claude/projects, and the grammar
    # checker shells out to the real Claude CLI. A test does neither.
    monkeypatch.setattr(typed, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr(typed, "CODEX_HISTORY", tmp_path / "codex-history.jsonl")
    monkeypatch.setenv("MR_THAROOR_NO_LLM", "1")
    monkeypatch.setattr(schedule, "LOG_DIR", tmp_path / "logs")


@pytest.fixture
def tmp(tmp_path):
    """Compatibility with the original script-style test functions."""
    return tmp_path
