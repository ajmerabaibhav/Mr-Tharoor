"""The go/no-go test. Twenty sentences that decide whether this project lives.

Everything built so far assumes one thing: that a phoneme model can hear the
difference between the sound you made and the sound the word needs, in real
speech. That assumption has never been tested. If it is false, the statistics
above it are a beautiful machine processing noise.

The set is deliberately split in half, and the split IS the experiment:

  BLOCK A, minimal pairs.  "The vet was wet." Two words that differ by exactly
  one sound, said slowly and clearly. This is the easy case and the published
  research case. If the model fails here, it fails everywhere and we stop.

  BLOCK B, connected speech.  Normal sentences at normal speed, the way you
  actually talk on a call. Words run together, sounds get dropped, and that is
  correct English, not sloppiness. Published accuracy numbers almost never
  cover this, because nobody records people mid-meeting.

The gap between A and B is the number that matters. High on both means build
the rest. High on A and low on B means the tool only works when you already
know you are being tested, which is useless. Low on both means stop.

Each sentence targets specific contrasts so a failure points somewhere. Read
them the way you would say them to a colleague, not the way you would read
them to a class. Reading carefully is the one way to get a misleading result.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from . import config

PROBE_DIR = config.DATA_DIR / "probe"
MANIFEST = PROBE_DIR / "manifest.json"

SAMPLE_RATE = 16000  # what both the ASR and the phoneme model expect

# Microphones we refuse to run the experiment on, in order of preference for
# what to use instead. A Bluetooth headset applies noise suppression and
# bandwidth limiting tuned for call intelligibility, and the first thing that
# throws away is high-frequency detail. That detail is precisely what
# separates /th/ from /t/, /s/ from /z/ and /f/ from /v/ -- the contrasts this
# test exists to measure. Recording the probe on AirPods would measure the
# microphone and blame the model.
PREFERRED_INPUTS = ("MacBook Air Microphone", "MacBook Pro Microphone", "Built-in")


@dataclass(frozen=True)
class Sentence:
    number: int
    block: str  # "A" minimal pairs, "B" connected speech
    text: str
    targets: tuple[str, ...]  # contrasts this sentence is built to expose
    note: str = ""


SENTENCES: tuple[Sentence, ...] = (
    # ---- BLOCK A: minimal pairs, said clearly. The easy case. ----
    Sentence(1, "A", "The vet was wet, and the vine grew on the wine barrel.",
             ("v->w", "w->v"), "v and w back to back, both directions"),
    Sentence(2, "A", "I think the thin tin is worth three hundred.",
             ("th->t",), "voiceless th against t"),
    Sentence(3, "A", "They said then, but the den was already there.",
             ("dh->d",), "voiced th against d"),
    Sentence(4, "A", "The zoo sued us, so the prize price rose.",
             ("z->s",), "z against s, including final position"),
    Sentence(5, "A", "Measure the major pleasure of the vision.",
             ("zh->j",), "zh against j"),
    Sentence(6, "A", "A bad bed, a bat bet, a sad said.",
             ("ae->e",), "the trap vowel against the dress vowel"),
    Sentence(7, "A", "The cot caught the coat, and the boat bought bark.",
             ("o->aw",), "back vowels that collapse together"),
    Sentence(8, "A", "Photo, phone, profit, fifty, fine, phase.",
             ("f->ph",), "f in every position"),
    Sentence(9, "A", "Two dots, ten doors, a bitter daughter at the door.",
             ("t->retroflex", "d->retroflex"), "alveolar t and d, the retroflex trap"),
    Sentence(10, "A", "I need a build, and the world should hold the gold.",
             ("final-d",), "final voiced stops, often devoiced"),

    # ---- BLOCK B: connected speech, normal speed. The real case. ----
    Sentence(11, "B", "So the new version is already live, and the delivery "
                      "date has not moved.",
             ("v->w",), "v inside running speech, unstressed"),
    Sentence(12, "B", "I think we should go through the numbers together "
                      "before Thursday.",
             ("th->t", "dh->d"), "both th sounds, unstressed and fast"),
    Sentence(13, "B", "The results of the analysis were a bit of a surprise, "
                      "honestly.",
             ("z->s", "ae->e"), "final z and the trap vowel, mid sentence"),
    Sentence(14, "B", "Can you send me the data so I can update the model "
                      "before the meeting?",
             ("t->retroflex", "d->retroflex"), "t and d you will flap or retroflex"),
    Sentence(15, "B", "It is not comfortable, but that category is where the "
                      "opportunity is.",
             ("stress",), "three words that get stressed on the wrong syllable"),
    Sentence(16, "B", "We are vulnerable on pricing, and I am not confident we "
                      "can develop it in time.",
             ("v->w", "stress"), "rare v word plus a stress trap"),
    Sentence(17, "B", "Honestly, the whole thing was worth it, even though it "
                      "took three weeks.",
             ("th->t", "w->v"), "th and w in fast unstressed positions"),
    Sentence(18, "B", "Let me measure how much the schedule actually changed "
                      "this week.",
             ("zh->j", "stress"), "zh mid word, plus schedule"),
    Sentence(19, "B", "That is a valid point, but the advantage is that we own "
                      "the whole channel.",
             ("v->w", "ae->e"), "v twice, trap vowel twice"),
    Sentence(20, "B", "I will get back to you once I have discussed it with "
                      "the team, probably by Friday.",
             ("dh->d", "final-d"), "natural closing phrasing, final stops"),
)


def blocks() -> dict[str, tuple[Sentence, ...]]:
    return {
        "A": tuple(s for s in SENTENCES if s.block == "A"),
        "B": tuple(s for s in SENTENCES if s.block == "B"),
    }


def wav_path(number: int) -> "config.Path":
    return PROBE_DIR / f"{number:02d}.wav"


def recorded() -> list[int]:
    return sorted(int(p.stem) for p in PROBE_DIR.glob("*.wav") if p.stem.isdigit())


def choose_input() -> tuple[int | None, str, str | None]:
    """Pick the microphone to run the experiment on.

    Returns (device index or None for system default, its name, a warning).
    Prefers a built-in mic because this is a controlled measurement and the
    microphone must not be the variable under test.
    """
    import sounddevice as sd

    devices = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    if not inputs:
        return None, "no input device", "No microphone found at all."

    for wanted in PREFERRED_INPUTS:
        for index, device in inputs:
            if wanted.lower() in device["name"].lower():
                current = sd.query_devices(kind="input")["name"]
                warning = None
                if current != device["name"]:
                    warning = (
                        f"Your system mic is {current!r}. Recording on "
                        f"{device['name']!r} instead: a Bluetooth mic strips the "
                        f"high frequencies this test measures."
                    )
                return index, device["name"], warning

    current = sd.query_devices(kind="input")
    return (
        None,
        current["name"],
        f"No built-in mic found, using {current['name']!r}. If that is a "
        f"Bluetooth headset the results will understate how well this works.",
    )


def record_one(
    sentence: Sentence, seconds: float = 12.0, device: int | None = None
) -> "config.Path":
    """Record one sentence to 16kHz mono wav. Press enter to stop early.

    Imported lazily so that reading the sentence list, checking progress, or
    running the tests never requires an audio device to exist.
    """
    import sys

    import sounddevice as sd
    import soundfile as sf

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * SAMPLE_RATE)
    audio = sd.rec(
        frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device
    )
    if sys.stdin.isatty():
        try:
            input()  # enter stops early; otherwise it runs the full duration
            sd.stop()
        except (EOFError, KeyboardInterrupt):
            sd.stop()
            raise
    else:
        # No keyboard to wait on (a test, a script, a piped run). Record the
        # full duration rather than reading EOF as "stop now", which would
        # silently write an empty file and look like a broken microphone.
        sd.wait()
    sd.wait()

    # Trim the trailing silence left when you stop early.
    import numpy as np

    loud = np.abs(audio[:, 0]) > 0.01
    end = int(np.argmax(loud[::-1] == True)) if loud.any() else 0  # noqa: E712
    keep = len(audio) - end + int(0.2 * SAMPLE_RATE)
    audio = audio[: min(keep, len(audio))]

    path = wav_path(sentence.number)
    sf.write(str(path), audio, SAMPLE_RATE)
    _write_manifest(sentence, path, len(audio) / SAMPLE_RATE)
    return path


def _write_manifest(sentence: Sentence, path, duration: float) -> None:
    manifest = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text())
        except json.JSONDecodeError:
            config.quarantine(MANIFEST)
    manifest[str(sentence.number)] = {
        **asdict(sentence),
        "path": str(path),
        "duration_s": round(duration, 2),
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }
    config.write_json_atomically(MANIFEST, manifest)


def manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text())
    except json.JSONDecodeError:
        return {}


if __name__ == "__main__":
    for block, items in blocks().items():
        kind = "minimal pairs, say them clearly" if block == "A" else "normal speed, like a call"
        print(f"\nBLOCK {block} — {kind}\n")
        for s in items:
            print(f"  {s.number:2d}. {s.text}")
            print(f"      targets: {', '.join(s.targets)}")
