"""The thing that was missing: actually listening.

Everything else decided whether to listen. Nothing did. This is the loop that
runs all day and turns a decision into audio on disk.

    context.decide()
        |
        +-- ALWAYS  a call, a huddle, dictation. Record in chunks until it ends.
        |
        +-- SAMPLE  you might be reading aloud. Open the mic for half a second,
        |           check for speech, and either commit to recording or go back
        |           to sleep. This is the only path that costs battery, and it
        |           costs a tenth of always-on.
        |
        +-- NEVER   sleep. Free.

Two rules that keep it honest:

  SILENCE IS NOT SAVED. Every chunk is checked for speech before it reaches
  disk. A meeting where you say nothing for ten minutes writes nothing.

  A CRASH MUST NOT BE SILENT. The loop logs what it decided and why, so a day
  with no report has an explanation rather than a mystery.

Chunks are short and separate on purpose. A crash at 16:40 loses the current
chunk, not the day, and short files let the nightly job skip the quiet ones
without decoding everything.
"""

from __future__ import annotations

import signal
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import config, context, log

SAMPLE_RATE = 16000
CHUNK_SECONDS = 30.0  # one file per half minute of conversation
PEEK_SECONDS = 0.4  # how long to listen when we suspect reading aloud
PEEK_EVERY = 15.0  # how often to peek. Was 5s, which kept the orange
# microphone indicator effectively lit all day. At 15s the mic is live under
# 3% of the time and the worst case is losing the first sentence you read.
IDLE_EVERY = 5.0  # how often to re-check context while asleep

# Speech has energy and a moderate zero-crossing rate. Typing and fans have
# one without the other. This is deliberately cheap: the real quality gate is
# the SNR check that runs before analysis.
#
# MEASURED: when another app already holds the microphone -- which is exactly
# the case we most want to record, because it means you are on a call or
# dictating -- our share of the signal comes back about 4.5x quieter
# (rms 0.0043 against 0.0089 alone). The old threshold of 0.004 sat right on
# top of that, so real speech during a Wispr session was thrown away as
# silence. The zero-crossing test is what actually separates speech from
# noise; the energy test only needs to rule out a dead microphone.
MIN_RMS = 0.0012
MIN_ZCR, MAX_ZCR = 0.02, 0.35

# A hard ceiling on recorded audio. An hour of speech is 115 MB, and the only
# thing that deletes it is a nightly job that can be skipped or can fail. This
# is the backstop: stop recording rather than fill someone's disk.
MAX_SESSION_MB = 2000


def sessions_dir(day: date | None = None) -> Path:
    day = day or date.today()
    path = config.DATA_DIR / "sessions" / day.isoformat()
    path.mkdir(parents=True, exist_ok=True)
    return path


def recorded_megabytes() -> float:
    """How much audio is currently on disk, across every day."""
    sessions = config.DATA_DIR / "sessions"
    if not sessions.exists():
        return 0.0
    return sum(f.stat().st_size for f in sessions.rglob("*.wav")) / 1e6


def has_speech(audio) -> bool:
    """Is there a voice in this, or just a room?"""
    import numpy as np

    if len(audio) == 0:
        return False
    rms = float(np.sqrt((audio**2).mean()))
    if rms < MIN_RMS:
        return False
    crossings = float(np.mean(np.abs(np.diff(np.sign(audio))) > 0))
    return MIN_ZCR <= crossings <= MAX_ZCR


@dataclass
class Stats:
    chunks_saved: int = 0
    chunks_dropped: int = 0
    seconds_saved: float = 0.0
    peeks: int = 0
    started: float = 0.0

    def as_dict(self) -> dict:
        return {
            "saved": self.chunks_saved,
            "dropped_silent": self.chunks_dropped,
            "minutes": round(self.seconds_saved / 60, 1),
            "peeks": self.peeks,
            "uptime_min": round((time.time() - self.started) / 60, 1),
        }


class Listener:
    """One long-running loop. Stop it with Ctrl-C or SIGTERM."""

    def __init__(self, use_voice_processing: bool = True):
        self.stats = Stats(started=time.time())
        self.running = True
        self.voice_processing = use_voice_processing
        self.logger = log.get("listener")

    def stop(self, *_):
        self.running = False

    def _record(self, seconds: float, path: str):
        from . import capture

        return capture.record(seconds, path, voice_processing=self.voice_processing)

    def _peek(self) -> bool:
        """Half a second of audio: is anyone talking?

Uses sounddevice, not AVAudioEngine, and never touches the voice path.

        MEASURED: a 0.4s peek through AVAudioEngine holds the device for
        1.54s, almost all of it engine setup and teardown, and lights the
        orange microphone indicator for every bit of it. The same peek through
        sounddevice holds it for 0.39s. Four times less, for a job that only
        asks whether there is energy shaped like speech: no echo cancellation,
        no beamforming, and critically no ducking of whatever else the Mac is
        playing.

        Quality capture still goes through the voice path. Detection and
        recording are different jobs and want different tools.
        """
        import sounddevice as sd

        self.stats.peeks += 1
        try:
            audio = sd.rec(
                int(PEEK_SECONDS * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
            )
            sd.wait()
            return has_speech(audio[:, 0])
        except Exception as exc:
            self.logger.warning(f"peek failed: {type(exc).__name__}: {exc}")
            return False

    def _capture_chunk(self, reason: str) -> bool:
        """Record one chunk. Returns whether it held speech and was kept."""
        import soundfile as sf

        stamp = datetime.now().strftime("%H%M%S")
        path = sessions_dir() / f"{stamp}.wav"
        try:
            self._record(CHUNK_SECONDS, str(path))
        except Exception as exc:
            self.logger.error(f"capture failed: {type(exc).__name__}: {exc}")
            time.sleep(5)
            return False

        try:
            audio, _ = sf.read(str(path), dtype="float32")
        except Exception:
            path.unlink(missing_ok=True)
            return False

        if not has_speech(audio):
            path.unlink(missing_ok=True)  # never keep a recording of a quiet room
            self.stats.chunks_dropped += 1
            return False

        self.stats.chunks_saved += 1
        self.stats.seconds_saved += len(audio) / SAMPLE_RATE
        self.logger.info(f"kept {path.name} ({len(audio)/SAMPLE_RATE:.0f}s, {reason})")
        return True

    def run(self, max_seconds: float | None = None) -> Stats:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        log.event("listener_start", voice_processing=self.voice_processing)
        self.logger.info("listening (context-aware). Ctrl-C to stop.")

        last_mode = None
        deadline = time.time() + max_seconds if max_seconds else None

        while self.running:
            if deadline and time.time() > deadline:
                break
            used = recorded_megabytes()
            if used > MAX_SESSION_MB:
                self.logger.error(
                    f"{used:.0f} MB of audio on disk, over the {MAX_SESSION_MB} MB "
                    f"ceiling. Not recording. Run `roy analyse-day` or delete "
                    f"{config.DATA_DIR / 'sessions'}."
                )
                time.sleep(300)
                continue

            decision = context.decide()
            if decision.mode != last_mode:
                self.logger.info(f"{decision.mode.upper()}: {decision.reason}")
                last_mode = decision.mode

            if decision.mode == context.LISTEN_ALWAYS:
                self._capture_chunk(decision.reason)
            elif decision.mode == context.LISTEN_SAMPLE:
                if self._peek():
                    self.logger.info("heard you start talking, recording")
                    while self.running and context.decide().mode != context.LISTEN_NEVER:
                        if not self._capture_chunk("reading aloud"):
                            break  # you stopped; go back to peeking
                else:
                    time.sleep(PEEK_EVERY - PEEK_SECONDS)
            else:
                time.sleep(IDLE_EVERY)

        log.event("listener_stop", **self.stats.as_dict())
        self.logger.info(f"stopped: {self.stats.as_dict()}")
        return self.stats


# Chunks are named HHMMSS.wav. Anything else in the folder is not a recording.
_CHUNK = __import__("re").compile(r"^\d{6}\.wav$")


def todays_audio(day: date | None = None) -> list[Path]:
    """Every completed chunk recorded on a day, oldest first.

    Matches the naming pattern rather than globbing *.wav, so a scratch file
    or a half-written stray is never handed to the analyser as speech.
    """
    folder = config.DATA_DIR / "sessions" / (day or date.today()).isoformat()
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if _CHUNK.match(p.name))
