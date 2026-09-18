"""Yesterday's mistakes, ready to hear this morning.

One finding is one sentence a person can act on:

    "You said WERSION. It is VERSION. Here is you, here is it said properly."

That needs four things joined together, and until now they lived in four
different places:

    the word          from the transcript, so it can be named
    the moment        from the phoneme timestamps, so a clip can be cut
    YOUR audio        cut from the recording, enhanced so you can hear it
    THE RIGHT audio   the human recording already cached by dictionary.py

The pairing is the whole product. A list of IPA symbols teaches nothing. Your
own voice next to a correct voice teaches in one second, because the ear does
the work that the eye cannot.

Clips are cut from ENHANCED audio deliberately. Playing back the raw recording
would be more honest about what the microphone captured and less useful for
learning, because you would be straining to hear the thing you are supposed to
be judging.
"""

from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from . import clean, config, dictionary, listen

CLIP_PAD_BEFORE = 0.35
CLIP_PAD_AFTER = 0.45
MIN_CONFIDENCE = 0.45


@dataclass
class Finding:
    """One mistake, with both sounds attached."""

    word: str
    contrast: str
    said: str  # the sound that came out
    should_be: str  # the sound the word needs
    second: float
    confidence: float
    source: str  # which recording it came from
    sentence: str
    clip_path: str | None = None  # you, saying it
    correct_path: str | None = None  # a human, saying it properly
    ipa: str | None = None
    quality: float = 1.0  # how clean the audio was, 0 to 1

    @property
    def evidence_weight(self) -> float:
        """What this finding is worth when tallies are accumulated.

        Kept separate from `confidence` on purpose. Confidence answers "is the
        model sure about the sound it heard"; quality answers "how much should
        a finding from audio this noisy count". Folding them together and then
        testing the product against a fixed threshold made noisy days
        mathematically incapable of producing any finding at all -- one cliff
        traded for another.
        """
        return self.confidence * self.quality

    @property
    def headline(self) -> str:
        return f"{self.word}: you said /{self.said}/, it is /{self.should_be}/"


def _load_enhanced(source_wav: str):
    """Read and enhance a recording ONCE. Every clip is cut from this."""
    import soundfile as sf

    audio, rate = sf.read(source_wav, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return clean.enhance(audio, rate), rate


def _cut(audio, rate: int, second: float, destination: Path) -> str | None:
    """Cut the moment out of an already-enhanced recording.

    The earlier version re-read and re-filtered the whole 30 second chunk for
    every single finding. Ten findings in a chunk meant ten full passes.
    """
    import soundfile as sf

    start = max(int((second - CLIP_PAD_BEFORE) * rate), 0)
    end = min(int((second + CLIP_PAD_AFTER) * rate), len(audio))
    if end - start < int(0.15 * rate):
        return None

    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destination), audio[start:end].astype("float32"), rate)
    return str(destination)


def to_m4a(wav_path: str) -> str | None:
    """Compress for the browser. afconvert ships with macOS, no ffmpeg needed."""
    out = str(Path(wav_path).with_suffix(".m4a"))
    result = subprocess.run(
        ["afconvert", "-f", "m4af", "-d", "aac", "-b", "32000", wav_path, out],
        capture_output=True,
    )
    return out if result.returncode == 0 and Path(out).exists() else None


def findings_for(wav_path: str, text: str, label: str) -> list[Finding]:
    """Every scored mistake in one recording, with your clip cut.

    Does NOT fetch the correct pronunciation here. That is a network call per
    new word, throttled to one a second, and a first night has hundreds of new
    words -- it was the single biggest reason a 40 minute day never finished.
    The report fetches audio only for the handful of words it actually shows.
    """
    result = listen.analyse(wav_path, text)
    enhanced, rate = _load_enhanced(wav_path)
    # Noisy audio does not get thrown away, it gets discounted. The pooling in
    # evidence.py already knows how to accumulate weak evidence; what it cannot
    # do is recover evidence a gate deleted.
    quality_weight = result["quality"].get("weight", 1.0)
    out: list[Finding] = []
    for index, diff in enumerate(result["scored"]):
        # The gate is on the DETECTOR's confidence alone. Noise is accounted
        # for downstream as evidence weight, where it can accumulate instead
        # of disqualifying the whole day.
        if diff.confidence < MIN_CONFIDENCE or not diff.word:
            continue
        clip = _cut(
            enhanced,
            rate,
            diff.second,
            config.CLIPS_DIR / f"{label}-{index}-{diff.word}.wav",
        )
        out.append(
            Finding(
                word=diff.word,
                contrast=diff.contrast or "",
                said=diff.actual or "",
                should_be=diff.expected or "",
                second=diff.second,
                confidence=diff.confidence,
                source=label,
                sentence=text,
                clip_path=clip,
                correct_path=None,
                ipa=None,
                quality=quality_weight,
            )
        )
    return out


PRONUNCIATION_BUDGET_SECONDS = 90.0
PRONUNCIATION_WORD_SECONDS = 20.0


def _with_deadline(fn, seconds: float):
    """Run fn in a thread; give up on it after `seconds`, whatever it is doing.

    A socket timeout does not cover DNS resolution. On this network a
    getaddrinfo call can hang indefinitely, and it did: the nightly job
    finished every dictation, cut 430 clips, then sat at 0% CPU for eight
    minutes inside one dictionary lookup, past a budget that could only be
    checked between words. A stuck daemon thread is abandoned and dies with
    the process; the job moves on and the word gets its audio tomorrow.
    """
    import threading

    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        return None
    return box.get("value")


def attach_pronunciations(findings: list[Finding], limit_words: int = 30) -> None:
    """Fetch the correct audio for the words that will be shown, in place.

    Under a hard time budget. Each new word is a network fetch, and on a bad
    night -- rate limited, or the dead-IPv6 stall this network has -- one
    word can take a minute of retries. Thirty of those and the job that was
    supposed to run while you slept is still running when you wake up, at
    0% CPU, waiting on a socket. Measured: that is exactly what happened.

    Cached words are free and always attached. New words are fetched, most
    frequent first, until the budget runs out; the rest get their audio
    tomorrow. A report with a few missing play buttons beats no report.
    """
    import time

    from . import log

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.word] = counts.get(f.word, 0) + 1
    words = sorted(counts, key=lambda w: -counts[w])[:limit_words]

    cached_keys = set(dictionary.cached_words())
    fetched = {}
    started = time.monotonic()
    skipped = 0
    for word in words:
        key = dictionary.cache_key(word)
        if key in cached_keys:
            fetched[word] = dictionary.lookup(word)  # disk only, instant
            continue
        if time.monotonic() - started > PRONUNCIATION_BUDGET_SECONDS:
            skipped += 1
            continue
        entry = _with_deadline(lambda w=word: dictionary.lookup(w), PRONUNCIATION_WORD_SECONDS)
        if entry is None:
            skipped += 1
            log.get("nightly").warning(f"pronunciation fetch for {word!r} abandoned after "
                                       f"{PRONUNCIATION_WORD_SECONDS:.0f}s")
            continue
        fetched[word] = entry
    if skipped:
        log.get("nightly").warning(
            f"{skipped} words left without correct-pronunciation audio tonight; retried tomorrow"
        )
    for f in findings:
        entry = fetched.get(f.word)
        if entry:
            f.correct_path = entry.audio_path
            f.ipa = entry.ipa


def group(findings: list[Finding]) -> dict[str, list[Finding]]:
    """By sound, worst first. One lesson per sound, not one per word."""
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.contrast, []).append(finding)
    for items in grouped.values():
        items.sort(key=lambda f: -f.confidence)
    return dict(sorted(grouped.items(), key=lambda kv: -len(kv[1])))


def embed(path: str | None) -> str | None:
    """Base64 for the page. Compressed first so a day fits in one file."""
    if not path or not Path(path).exists():
        return None
    source = path
    if path.endswith(".wav"):
        source = to_m4a(path) or path
    data = Path(source).read_bytes()
    if len(data) > 400_000:  # a clip this big is a bug, not a clip
        return None
    kind = "audio/mp4" if source.endswith(".m4a") else (
        "audio/mpeg" if source.endswith(".mp3") else "audio/wav"
    )
    return f"data:{kind};base64,{base64.b64encode(data).decode()}"


def save(findings: list[Finding], day: date | None = None) -> Path:
    """Write the day's findings where the report generator can read them."""
    day = day or date.today()
    path = config.REPORTS_DIR / f"{day.isoformat()}.json"
    config.write_json_atomically(path, [asdict(f) for f in findings])
    return path


def load(day: date) -> list[Finding]:
    path = config.REPORTS_DIR / f"{day.isoformat()}.json"
    if not path.exists():
        return []
    return [Finding(**row) for row in json.loads(path.read_text())]
