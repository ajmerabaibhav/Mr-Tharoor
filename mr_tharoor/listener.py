"""The thing that was missing: actually listening.

Everything else decided whether to listen. Nothing did. This is the loop that
runs all day and turns a decision into audio on disk.

    context.decide()
        |
        +-- ALWAYS  record in chunks until it ends. Nothing asks for this
        |           any more: see context.decide(). Kept because the loop is
        |           the part that would need writing again.
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
CHUNK_SECONDS = 30.0  # a call: long chunks, the mic is on anyway
READING_CHUNK_SECONDS = 10.0  # reading aloud: short, so it lets go quickly

# Reading aloud is speculative: nobody asked us to record, we guessed from a
# half-second peek. So it is rationed. Measured on a real day the old loop
# kept 213 chunks -- 106 minutes with the microphone lit -- because it
# re-armed every time speech was heard anywhere near the machine.
READING_BUDGET_MINUTES = 20.0  # per day, for the speculative path only
READING_COOLDOWN_SECONDS = 120.0  # after a burst, leave the microphone alone
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
    chunks_too_far: int = 0
    seconds_saved: float = 0.0
    reading_seconds: float = 0.0  # the speculative path only
    peeks: int = 0
    started: float = 0.0

    def as_dict(self) -> dict:
        return {
            "reading_min": round(self.reading_seconds / 60, 1),
            "saved": self.chunks_saved,
            "dropped_silent": self.chunks_dropped,
            "dropped_too_far": self.chunks_too_far,
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
        self.cooldown_until = 0.0

    def reading_budget_left(self) -> float:
        """Seconds of speculative recording still allowed today."""
        used = self.stats.reading_seconds + _reading_seconds_on_disk()
        return max(READING_BUDGET_MINUTES * 60 - used, 0.0)

    def stop(self, *_):
        self.running = False

    def _record(self, seconds: float, path: str, voice: bool):
        """Two capture paths, chosen per situation, not per install.

        The voice path (Apple's echo cancellation, beamforming, gain) is
        worth having on a call, where the room is noisy and the other side
        is playing through your speakers. It also ducks every other sound
        the Mac makes, and there is no setting that turns that off entirely.

        Reading aloud at a desk needs none of that: you are close, the room
        is quiet, and the one thing you do not want is your video going
        quiet because a coach started listening. So that path is raw.
        """
        from . import capture

        return capture.record(seconds, path, voice_processing=voice)

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
            # PortAudio occasionally refuses the device for a moment (error
            # -9986) when another app is grabbing or releasing it. Seen in
            # production, intermittently, with no pattern. Fall back to the
            # heavier raw AVAudioEngine path for this one peek rather than
            # silently deciding nobody is talking.
            self.logger.warning(f"peek via sounddevice failed ({type(exc).__name__}), using raw engine")
            import soundfile as sf

            from . import capture

            scratch = str(config.DATA_DIR / ".peek.wav")
            try:
                capture.record(PEEK_SECONDS, scratch, voice_processing=False)
                audio, _ = sf.read(scratch, dtype="float32")
                return has_speech(audio if audio.ndim == 1 else audio[:, 0])
            except Exception as exc2:  # noqa: BLE001
                self.logger.warning(f"peek failed on both paths: {type(exc2).__name__}: {exc2}")
                time.sleep(PEEK_EVERY)  # back off; do not hammer a device that is refusing us
                return False
            finally:
                Path(scratch).unlink(missing_ok=True)

    def _capture_chunk(self, reason: str, voice: bool = True,
                       seconds: float = CHUNK_SECONDS) -> bool:
        """Record one chunk. Returns whether it held speech and was kept."""
        import soundfile as sf

        from . import listen

        stamp = datetime.now().strftime("%H%M%S")
        path = sessions_dir() / f"{stamp}.wav"
        try:
            self._record(seconds, str(path), voice)
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

        # The analyser refuses anything under listen.MIN_SNR_DB, so keeping it
        # is pure cost: disk tonight, a decode at 23:30, then a deletion.
        # MEASURED on 2026-09-20, 61 own-microphone chunks: 82% sat under the
        # floor, median 3.1 dB, against 24.0 dB for the same voice through
        # Wispr's close microphone. The same threshold as the analyser on
        # purpose -- this changes what gets stored, never which findings exist.
        #
        # It is also the only place feedback is worth anything. The one lever
        # on signal-to-noise is distance, and the person holding the laptop is
        # the only one who can pull it. TOO_FAR is what `roy logs` counts.
        snr = listen.snr_of(audio, SAMPLE_RATE)
        if snr < listen.MIN_SNR_DB:
            path.unlink(missing_ok=True)
            self.stats.chunks_too_far += 1
            self.logger.info(f"{log.TOO_FAR}: {snr:.0f} dB, microphone too far ({reason})")
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
                self._capture_chunk(decision.reason, voice=self.voice_processing)
            elif decision.mode == context.LISTEN_SAMPLE:
                budget = self.reading_budget_left()
                if budget <= 0:
                    if last_mode != "spent":
                        self.logger.info(
                            f"reading-aloud budget for today is spent "
                            f"({READING_BUDGET_MINUTES:.0f} min). Calls still record."
                        )
                        last_mode = "spent"
                    time.sleep(IDLE_EVERY * 6)
                elif time.time() < self.cooldown_until:
                    time.sleep(IDLE_EVERY)
                elif self._peek():
                    self.logger.info("heard you reading aloud, recording")
                    # Short chunks, and re-check the world between each one.
                    # The old loop held the microphone for a full 30 seconds
                    # before asking whether it should still be listening.
                    while self.running and self.reading_budget_left() > 0:
                        if context.decide().mode != context.LISTEN_SAMPLE:
                            break
                        kept = self._capture_chunk(
                            "reading aloud", voice=False, seconds=READING_CHUNK_SECONDS
                        )
                        self.stats.reading_seconds += READING_CHUNK_SECONDS
                        if not kept:
                            break  # you stopped; go back to peeking
                    # Whatever happened, step away from the microphone for a
                    # while. Without this it re-armed the moment you spoke
                    # again, and the orange indicator never went out.
                    self.cooldown_until = time.time() + READING_COOLDOWN_SECONDS
                else:
                    time.sleep(PEEK_EVERY - PEEK_SECONDS)
            else:
                # NEVER, or SKIP because Wispr Flow is already recording.
                time.sleep(IDLE_EVERY)

        log.event("listener_stop", **self.stats.as_dict())
        self.logger.info(f"stopped: {self.stats.as_dict()}")
        return self.stats


# Chunks are named HHMMSS.wav. Anything else in the folder is not a recording.
_CHUNK = __import__("re").compile(r"^\d{6}\.wav$")


def _reading_seconds_on_disk(day: date | None = None) -> float:
    """Speculative recording already banked today, so a restart cannot reset it."""
    total = 0.0
    for wav in todays_audio(day):
        try:
            total += wav.stat().st_size / (SAMPLE_RATE * 2)
        except OSError:
            pass
    return total


def todays_audio(day: date | None = None) -> list[Path]:
    """Every completed chunk recorded on a day, oldest first.

    Matches the naming pattern rather than globbing *.wav, so a scratch file
    or a half-written stray is never handed to the analyser as speech.
    """
    folder = config.DATA_DIR / "sessions" / (day or date.today()).isoformat()
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if _CHUNK.match(p.name))
