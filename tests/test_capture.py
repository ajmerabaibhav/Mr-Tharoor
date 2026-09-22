"""Capture setup must follow the active input route and never leak scratch files."""

import sys
from types import ModuleType

import pytest

from mr_tharoor import capture, config


def test_tap_setup_failure_removes_scratch_and_uses_input_format(tmp_path, monkeypatch):
    class Format:
        def sampleRate(self):
            return 48_000

        def channelCount(self):
            return 2

        def settings(self):
            return {}

    fmt = Format()

    class Node:
        def inputFormatForBus_(self, bus):
            assert bus == 0
            return fmt

        def outputFormatForBus_(self, bus):
            raise AssertionError("capture must not use the stale output format")

        def installTapOnBus_bufferSize_format_block_(self, bus, size, tap_format, block):
            assert tap_format is fmt
            raise RuntimeError("format mismatch")

    node = Node()

    class Engine:
        def inputNode(self):
            return node

        def stop(self):
            pass

    class EngineFactory:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return Engine()

    class AudioFile:
        @classmethod
        def alloc(cls):
            return cls()

        def initForWriting_settings_error_(self, url, settings, error):
            return self, None

    av = ModuleType("AVFoundation")
    av.AVAudioEngine = EngineFactory
    av.AVAudioFile = AudioFile
    av.AVLinearPCMIsFloatKey = "float"
    av.AVLinearPCMBitDepthKey = "bits"

    class URL:
        @staticmethod
        def fileURLWithPath_(path):
            return path

    foundation = ModuleType("Foundation")
    foundation.NSURL = URL

    monkeypatch.setitem(sys.modules, "AVFoundation", av)
    monkeypatch.setitem(sys.modules, "Foundation", foundation)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="format mismatch"):
        capture.record(0, str(tmp_path / "result.wav"), voice_processing=False)

    assert list((tmp_path / "scratch").iterdir()) == []
