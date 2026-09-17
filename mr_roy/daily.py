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


def _cut(source_wav: str, second: float, destination: Path) -> str | None:
    """Cut the moment out of the recording, enhanced so it is audible."""
    import numpy as np
    import soundfile as sf

    audio, rate = sf.read(source_wav, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = clean.enhance(audio, rate)

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
    """Every scored mistake in one recording, with both clips cut."""
    result = listen.analyse(wav_path, text)
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
            wav_path,
            diff.second,
            config.CLIPS_DIR / f"{label}-{index}-{diff.word}.wav",
        )
        pronunciation = dictionary.lookup(diff.word)
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
                correct_path=pronunciation.audio_path,
                ipa=pronunciation.ipa,
                quality=quality_weight,
            )
        )
    return out


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
