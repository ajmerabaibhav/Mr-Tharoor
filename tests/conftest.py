"""Keep all automated checks away from the user's speech and judgement history."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mr_tharoor import accuracy, config, remind, schedule, streaks, wispr


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    for name, suffix in (("ROOT", ""), ("DATA_DIR", "data"), ("CLIPS_DIR", "data/clips"),
                         ("REPORTS_DIR", "reports"), ("CACHE_DIR", "cache"),
                         ("AUDIO_DIR", "cache/audio")):
        path = tmp_path / suffix
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, name, path)
    monkeypatch.setattr(streaks, "HISTORY_FILE", tmp_path / "data/history.json")
    monkeypatch.setattr(config, "INDEX_FILE", tmp_path / "cache/index.json")
    monkeypatch.setattr(accuracy, "LABELS_FILE", tmp_path / "data/labels.json")
    monkeypatch.setattr(remind, "QUEUE_FILE", tmp_path / "data/reminders.json")
    monkeypatch.setattr(remind, "DELIVERIES_FILE", tmp_path / "data/deliveries.json")
    monkeypatch.setattr(wispr, "DB_PATH", tmp_path / "absent.sqlite")
    monkeypatch.setattr(schedule, "LOG_DIR", tmp_path / "logs")


@pytest.fixture
def tmp(tmp_path):
    """Compatibility with the original script-style test functions."""
    return tmp_path
