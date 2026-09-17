"""Record through Apple's voice path, not the raw one.

First principles on why the audio was bad, and what actually fixes it.

Signal-to-noise is decided at the microphone. Nothing downstream recovers
detail the microphone never resolved. The first real session measured 12 dB
SNR, and the sounds we most need -- s, z, th, f, v -- are the quietest parts
of speech and the first to vanish into a room.

There are only three levers, and they are not equal:

  1. DISTANCE.  Sound pressure falls with distance, so halving it buys about
     6 dB. Arm's length to a hand-span is roughly +12 dB, free, no code.
     A headset mic three centimetres from your mouth is about +26 dB, which
     is why dictation apps feel so much better through AirPods.

  2. DIRECTION. This Mac has THREE microphones. Used together they can steer
     a beam at whoever is in front of the screen and reject the rest of the
     room. Reading one channel and ignoring the other two, which is what a
     plain CoreAudio capture does, throws that away.

  3. CLEANUP.   Spectral subtraction, the thing we wrote first, removes
     steady hum well and non-steady noise (a voice nearby, a door) poorly.
     It bought about 15 dB. Useful, and the least powerful of the three.

Apple already ships 2 and most of 3, tuned in anechoic chambers and running
on dedicated silicon: echo cancellation, three-mic beamforming, non-stationary
noise suppression and automatic gain. One call turns it on:

    inputNode.setVoiceProcessingEnabled_error_(True, None)

This module exists because Python's usual audio libraries talk to CoreAudio's
raw HAL and never see any of it. Writing our own beamformer to compete would
be a worse version of a solved problem. The lazy answer is the right one.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import config

TARGET_RATE = 16000  # what the phoneme model and the ASR both want


def available() -> bool:
    try:
        import AVFoundation  # noqa: F401

        return True
    except ImportError:
        return False


def _resample_to_16k(audio, rate: int):
    """Downsample with an anti-aliasing filter.

    48000 / 16000 is exactly 3, so this is a clean decimation. Skipping the
    low-pass would fold everything above 8 kHz back down into the speech
    band as alias, which lands squarely on the fricatives we are measuring.
    """
    import numpy as np

    if rate == TARGET_RATE:
        return audio
    factor = rate / TARGET_RATE
    if abs(factor - round(factor)) < 1e-6:
        factor = int(round(factor))
        taps = np.sinc(np.arange(-30, 31) / factor) * np.hanning(61)
        taps /= taps.sum()
        return np.convolve(audio, taps, mode="same")[::factor]
    target_length = int(len(audio) * TARGET_RATE / rate)
    return np.interp(
        np.linspace(0, len(audio) - 1, target_length), np.arange(len(audio)), audio
    )


def record(seconds: float, destination: str, voice_processing: bool = True) -> dict:
    """Record to a 16 kHz mono wav. Returns what actually happened.

    `voice_processing=False` records the raw microphone instead, which exists
    so the two can be measured against each other rather than assumed.
    """
    import AVFoundation
    import numpy as np
    import soundfile as sf
    from Foundation import NSURL

    engine = AVAudioEngine = AVFoundation.AVAudioEngine.alloc().init()
    node = engine.inputNode()

    enabled = False
    if voice_processing:
        ok, error = node.setVoiceProcessingEnabled_error_(True, None)
        enabled = bool(ok) and bool(node.isVoiceProcessingEnabled())
        if not ok:
            print(f"mr-roy: voice processing unavailable ({error}), recording raw")

    fmt = node.outputFormatForBus_(0)
    rate = int(fmt.sampleRate())

    # Write at the hardware rate through AVAudioFile, which handles the
    # buffer plumbing, then resample once in numpy. Writing 48k buffers into
    # a 16k file does not resample, it corrupts.
    # NOT next to the destination. This is a scratch file at the hardware
    # rate, and writing it as "<name>.raw48.wav" inside the session folder
    # meant an interrupted recording left a 13 MB stray that the nightly job
    # then tried to analyse as speech.
    import tempfile

    scratch_dir = config.DATA_DIR / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    handle, raw_path = tempfile.mkstemp(suffix=".wav", dir=str(scratch_dir))
    import os as _os

    _os.close(handle)
    # Take the settings from the node's own format. Writing a three-channel
    # buffer into a file declared as mono fails on every write, and because a
    # dropped buffer must not crash a recording, it fails silently: you get a
    # perfectly valid wav file containing nothing.
    settings = dict(fmt.settings())
    settings[AVFoundation.AVLinearPCMIsFloatKey] = False
    settings[AVFoundation.AVLinearPCMBitDepthKey] = 16
    audio_file, error = AVFoundation.AVAudioFile.alloc().initForWriting_settings_error_(
        NSURL.fileURLWithPath_(raw_path), settings, None
    )
    if audio_file is None:
        raise OSError(f"cannot open {raw_path}: {error}")

    failures = {"count": 0}

    def tap(buffer, when):
        written, write_error = audio_file.writeFromBuffer_error_(buffer, None)
        if not written:
            failures["count"] += 1

    node.installTapOnBus_bufferSize_format_block_(0, 4096, fmt, tap)
    ok, error = engine.startAndReturnError_(None)
    if not ok:
        raise OSError(f"cannot start audio engine: {error}")

    try:
        time.sleep(seconds)
    except BaseException:
        node.removeTapOnBus_(0)
        engine.stop()
        del audio_file
        Path(raw_path).unlink(missing_ok=True)  # never leave scratch behind
        raise
    finally:
        try:
            node.removeTapOnBus_(0)
            engine.stop()
            del audio_file  # flush and close before reading it back
        except Exception:
            pass

    if failures["count"]:
        print(f"mr-roy: {failures['count']} buffers failed to write")
    audio, file_rate = sf.read(raw_path, dtype="float32")
    channel_levels: list[float] = []
    if audio.ndim > 1:
        # With voice processing on, the node hands back three channels but the
        # processed, beamformed signal is not spread across them -- averaging
        # buried it 15 dB under two near-silent neighbours. Take the loudest
        # channel instead: correct whichever one Apple decides to use.
        channel_levels = [
            float(np.sqrt((audio[:, c] ** 2).mean())) for c in range(audio.shape[1])
        ]
        audio = audio[:, int(np.argmax(channel_levels))]
    if len(audio) == 0:
        raise OSError("recording produced no audio: check microphone permission")
    audio = _resample_to_16k(audio, file_rate).astype("float32")
    sf.write(destination, audio, TARGET_RATE)
    Path(raw_path).unlink(missing_ok=True)

    return {
        "path": destination,
        "seconds": len(audio) / TARGET_RATE,
        "hardware_rate": rate,
        "channels": int(fmt.channelCount()),
        "voice_processing": enabled,
        "peak": float(np.abs(audio).max()) if len(audio) else 0.0,
        "channel_levels_db": [
            round(20 * float(np.log10(level + 1e-12)), 1) for level in channel_levels
        ],
    }
