"""Make quiet speech legible, the way dictation apps do.

Wispr Flow, macOS dictation and every other tool that works when you mumble
at your laptop are not using a better microphone than you have. They do three
things to the audio before the model ever sees it, and they get a fourth for
free from the kind of model they use:

  1. GAIN.   Normalise to a known loudness. A recogniser trained on speech at
             -20 dBFS sees something unfamiliar at -38 dBFS.
  2. DENOISE. Estimate the room's steady hum from the quietest frames and
             subtract it from every frame. Fans, laptops and air conditioning
             are stationary; speech is not, so the difference is separable.
  3. HIGH-PASS. Below about 80 Hz there is no speech, only rumble and desk
             thumps, and that energy drags the normalisation down.

  4. And the one we cannot copy: their recogniser has a LANGUAGE MODEL. Whisper
     can miss half the phonemes and still write the right sentence, because
     English narrows the possibilities. Our phoneme model deliberately has no
     language model -- that refusal is the entire reason it can hear you say
     "wersion" instead of quietly correcting you to "version". So it has no
     safety net, and clean input matters far more to us than it does to them.

That last point is why the answer is not "use Whisper instead". It is: use
Whisper for the words, this for the sounds, and make the audio good enough
that the sounds survive.
"""

from __future__ import annotations

import numpy as np

TARGET_RMS_DBFS = -20.0  # where the model's training data lives
HIGHPASS_HZ = 80.0
N_FFT = 512
HOP = 128


def _highpass(audio: np.ndarray, rate: int, cutoff: float = HIGHPASS_HZ) -> np.ndarray:
    """One-pole high-pass. Removes rumble.

    Vectorised. The first version was a Python for-loop over every sample,
    which on a 30 second chunk is 480,000 iterations, and it ran once per
    finding. That alone was minutes of the nightly job.
    """
    alpha = 1.0 / (1.0 + 2 * np.pi * cutoff / rate)
    try:
        from scipy.signal import lfilter

        return lfilter([alpha, -alpha], [1.0, -alpha], audio).astype(audio.dtype)
    except ImportError:  # pragma: no cover
        out = np.empty_like(audio)
        out[0] = audio[0]
        for i in range(1, len(audio)):
            out[i] = alpha * (out[i - 1] + audio[i] - audio[i - 1])
        return out


def denoise(audio: np.ndarray, over_subtract: float = 2.0, floor: float = 0.05) -> np.ndarray:
    """Spectral subtraction. Estimate the room, then take it away.

    The room's noise is steady, so the quietest fifth of frames are almost
    pure noise. Average them to get its spectrum and subtract that from every
    frame, keeping a floor so the result does not turn into musical artefacts
    that the model would happily transcribe as phonemes.
    """
    if len(audio) < N_FFT * 2:
        return audio
    window = np.hanning(N_FFT)
    starts = range(0, len(audio) - N_FFT, HOP)
    spectra = np.array([np.fft.rfft(audio[s : s + N_FFT] * window) for s in starts])
    magnitude, phase = np.abs(spectra), np.angle(spectra)

    energy = magnitude.sum(axis=1)
    quiet = magnitude[energy <= np.percentile(energy, 20)]
    noise = quiet.mean(axis=0) if len(quiet) else np.zeros(magnitude.shape[1])

    cleaned = np.maximum(magnitude - over_subtract * noise, floor * magnitude)

    out = np.zeros(len(audio))
    weight = np.zeros(len(audio))
    for index, start in enumerate(starts):
        frame = np.fft.irfft(cleaned[index] * np.exp(1j * phase[index]), n=N_FFT)
        out[start : start + N_FFT] += frame * window
        weight[start : start + N_FFT] += window**2
    return out / np.maximum(weight, 1e-8)


def normalise(audio: np.ndarray, target_dbfs: float = TARGET_RMS_DBFS) -> np.ndarray:
    """Bring speech to the loudness the model was trained on, without clipping."""
    rms = float(np.sqrt((audio**2).mean()))
    if rms <= 0:
        return audio
    gain = (10 ** (target_dbfs / 20)) / rms
    out = audio * gain
    peak = float(np.abs(out).max())
    if peak > 0.99:  # never clip; clipping invents harmonics the model reads as sounds
        out = out * (0.99 / peak)
    return out


def enhance(audio: np.ndarray, rate: int, spectral: bool = False) -> np.ndarray:
    """MEASURED, not assumed. Only the high-pass earns its place.

    Isolating each step over six recordings, same words, same model:

        nothing at all                 SNR 12.5 dB   match 53%
        normalise only                 SNR 12.5 dB   match 53%   <- zero
        high-pass only                 SNR 13.2 dB   match 55%   <- the win
        high-pass + normalise          SNR 13.2 dB   match 55%
        + spectral subtraction (x2)    SNR 27.5 dB   match 55%   <- cosmetic
        + spectral subtraction (x8)    SNR 31.9 dB   match 44%   <- harmful

    Two lessons worth keeping:

    Gain does nothing because wav2vec2's own feature extractor already
    normalises to zero mean and unit variance. Making the file louder changes
    a number a human reads and nothing the model sees.

    Spectral subtraction raises SNR by 15 dB and improves understanding by
    zero. It removes noise the model was already robust to, and pushed harder
    it starts removing the fricative energy we exist to measure -- the match
    rate falls off a cliff at x8. A dictation app can afford that because its
    language model rebuilds the words; we deliberately have no language model,
    so what is smoothed away is simply gone.

    So it is off by default. `spectral=True` stays available for genuinely
    noisy recordings, where 15 dB of headroom may matter more than fidelity.
    """
    audio = _highpass(audio, rate)
    if spectral:
        audio = denoise(audio)
    return normalise(audio)


def enhance_file(source: str, destination: str) -> dict:
    """Clean one recording on disk and report what changed."""
    import soundfile as sf

    from . import listen

    audio, rate = sf.read(source, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    before = listen.audio_quality(source)
    sf.write(destination, enhance(audio, rate).astype("float32"), rate)
    after = listen.audio_quality(destination)
    return {
        "snr_before": before["snr_db"],
        "snr_after": after["snr_db"],
        "rms_before": before["rms_db"],
        "rms_after": after["rms_db"],
        "usable_now": after["usable"],
    }
