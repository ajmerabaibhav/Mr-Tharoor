"""What sounds actually left your mouth.

This is the part everything else was built on top of, and the part that has
never been tested. Two independent views of the same audio:

    what you MEANT    the words, from the text (for the probe we know them
                      already; in the real product this comes from ASR)
                           |
                           v  CMUdict, then ARPABET -> IPA
                      the canonical phoneme sequence

    what you SAID     wav2vec2-lv-60-espeak-cv-ft reads the audio and emits
                      phonemes directly. It carries no language model, so it
                      will not quietly correct you into the word you meant.
                      That refusal to be helpful is the entire point.

Align the two and the differences fall out. Alignment is Needleman-Wunsch,
because the two sequences are near-identical with a few substitutions and the
occasional dropped or inserted sound, which is exactly the problem that
algorithm was written for.

One honest caveat that no amount of code fixes: CMUdict gives the citation
form of a word, said in isolation. Real connected speech legitimately reduces
and drops sounds. So a raw difference is a candidate, never a verdict, and
only differences on the tracked contrasts are ever scored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from . import config

MODEL_NAME = "facebook/wav2vec2-lv-60-espeak-cv-ft"
SAMPLE_RATE = 16000

# ARPABET (what CMUdict speaks) to the IPA-ish symbols eSpeak and the model
# emit. Stress digits are stripped before lookup.
ARPABET_TO_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "EH": "ɛ", "ER": "ɚ",
    "EY": "eɪ", "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "i",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "OW": "oʊ", "OY": "ɔɪ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "UH": "ʊ", "UW": "u", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}

# The contrasts we score. Everything else the aligner finds is ignored on
# purpose: normal fast speech drops and blurs sounds, and calling that an
# error is how you build a tool nobody opens twice.
CONTRASTS: dict[str, tuple[str, tuple[str, ...]]] = {
    #  name          expected   things you might have said instead
    "v->w": ("v", ("w", "ʋ", "β")),
    "w->v": ("w", ("v", "ʋ")),
    "th->t": ("θ", ("t", "t̪", "s")),
    "dh->d": ("ð", ("d", "d̪", "z")),
    "z->s": ("z", ("s",)),
    "zh->j": ("ʒ", ("dʒ", "z", "ʃ")),
    "ae->e": ("æ", ("ɛ", "e", "a")),
    "o->aw": ("oʊ", ("ɔ", "o", "ɒ")),
    "f->ph": ("f", ("p", "pʰ")),
    "t->retroflex": ("t", ("ʈ", "ʈʰ")),
    "d->retroflex": ("d", ("ɖ",)),
    "final-d": ("d", ("t",)),
}

# Broad phonetic classes, used to stop the aligner pairing unrelated sounds.
VOWELS = set("iɪeɛæaɑɒɔoʊuʌəɚɝ") | {"aɪ", "aʊ", "ɔɪ", "eɪ", "oʊ", "ɪə", "eə", "ʊə"}
_MANNER = {
    "stop": set("pbtdkɡʈɖq"),
    "fricative": set("fvθðszʃʒhxɣ"),
    "affricate": {"tʃ", "dʒ"},
    "nasal": set("mnŋɱɳ"),
    "liquid": set("lɹrɾɻɭ"),
    "glide": set("wjɥ"),
}


def _manner(symbol: str) -> str | None:
    for name, members in _MANNER.items():
        if symbol in members:
            return name
    return None


@lru_cache(maxsize=65536)
def _substitution_score(expected: str, actual: str) -> float:
    """How plausible is it that this expected sound came out as that one?

    Without this the aligner treats every mismatch alike, and because a
    mismatch cost the same as a gap it always preferred a nonsense pairing to
    opening a gap. The first run produced ð -> p, f -> k and z -> aɪ, which
    are not confusions any mouth makes; they were alignment debris, and they
    dragged the measured agreement down to 15%.

    Pairs we are actively hunting are the cheapest of all to align, so a real
    v -> w is found rather than hidden behind a gap.
    """
    if expected == actual:
        return 2.0
    # An intervocalic flap IS how /t/ and /d/ are said in normal English.
    # Calling "data" -> [ɾ] an error would flag correct speech.
    if actual == "ɾ" and expected in ("t", "d"):
        return 2.0
    for want, instead in CONTRASTS.values():
        if expected == want and actual in instead:
            return -0.5  # exactly the confusion we are looking for
    expected_vowel, actual_vowel = expected in VOWELS, actual in VOWELS
    if expected_vowel != actual_vowel:
        return -5.0  # a vowel is never a consonant. Two gaps are cheaper.
    if expected_vowel:
        return -1.0  # vowels blur into each other constantly
    manner_a, manner_b = _manner(expected), _manner(actual)
    if manner_a and manner_a == manner_b:
        return -1.0  # same kind of consonant, a plausible slip
    return -3.0


_STRESS = re.compile(r"\d")
_WORD = re.compile(r"[a-z']+")

# The model speaks eSpeak, CMUdict speaks ARPABET, and they write the same
# sounds differently. Length marks are the big one: the model's "iː" and our
# "i" are one sound, and counting them as a disagreement made the first run
# look like the model could not hear at all.
_ESPEAK_TO_IPA = {
    "iː": "i", "uː": "u", "ɑː": "ɑ", "ɔː": "ɔ", "ɜː": "ɚ", "oː": "oʊ",
    "ɑːɹ": "ɑ", "ɔːɹ": "ɔ", "ɐ": "ʌ", "ᵻ": "ɪ", "ɨ": "ɪ", "ʉ": "u",
    "r": "ɹ", "a": "æ", "e": "ɛ", "o": "oʊ", "ɒ": "ɑ", "əɜ": "ɚ",
    "oɪ": "ɔɪ", "ɡ": "ɡ", "g": "ɡ",
}
_VARIANT = re.compile(r"[0-9.]")


def normalise(symbol: str) -> str:
    """Model output into the same alphabet as the dictionary.

    The eSpeak vocabulary carries length marks, tone digits and variant
    suffixes that say nothing about which sound was made. Strip them, then
    map the remaining spelling differences.
    """
    cleaned = _VARIANT.sub("", symbol).strip()
    if cleaned in _ESPEAK_TO_IPA:
        return _ESPEAK_TO_IPA[cleaned]
    without_length = cleaned.replace("ː", "")
    return _ESPEAK_TO_IPA.get(without_length, without_length)


@dataclass
class Token:
    """One phoneme the model heard, and how sure it was."""

    symbol: str
    confidence: float
    second: float


@dataclass
class Diff:
    """One place the sounds you made differ from the sounds the words need."""

    expected: str | None  # None when you inserted a sound
    actual: str | None  # None when you dropped one
    contrast: str | None  # set only when this is a difference we score
    confidence: float
    index: int
    second: float = 0.0  # when in the recording, so a clip can be cut
    word: str = ""  # which word it happened in

    @property
    def scored(self) -> bool:
        return self.contrast is not None


@lru_cache(maxsize=1)
def _model():
    """Loaded once, lazily, so importing this module stays free.

    Deliberately avoids AutoProcessor. Its tokenizer class refuses to
    instantiate without the `phonemizer` package, which in turn wants an
    espeak-ng binary this machine has no Homebrew to install. We only need
    two things: the feature extractor (which just normalises audio) and the
    index-to-symbol vocabulary, which is a plain JSON file on the hub.
    """
    import json

    import torch
    from huggingface_hub import hf_hub_download
    from transformers import AutoModelForCTC, Wav2Vec2FeatureExtractor

    extractor = Wav2Vec2FeatureExtractor.from_pretrained(MODEL_NAME)
    with open(hf_hub_download(MODEL_NAME, "vocab.json")) as handle:
        vocab = {index: symbol for symbol, index in json.load(handle).items()}

    model = AutoModelForCTC.from_pretrained(MODEL_NAME)
    model.eval()
    # MPS gives roughly a 3x speedup on Apple silicon and falls back cleanly.
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)
    return extractor, vocab, model, device


def _arpabet_to_ipa(phone: str) -> str:
    """One ARPABET phone to IPA, keeping what the stress digit tells us.

    CMUdict marks unstressed vowels with a trailing 0, and an unstressed AH
    is a schwa, not a wedge. Stripping the digit before lookup mapped every
    reduced vowel in English to the wrong symbol, which alone accounted for
    a large share of the first run's apparent disagreement.
    """
    unstressed = phone.endswith("0")
    base = _STRESS.sub("", phone)
    if unstressed:
        if base == "AH":
            return "ə"
        if base == "ER":
            return "ɚ"
    return ARPABET_TO_IPA.get(base, "")


@lru_cache(maxsize=1)
def _cmudict() -> dict:
    """Load the dictionary once.

    cmudict.dict() reparses all 126,000 entries on every call and caches
    nothing, so calling it per word turned a 2 second analysis into 30.
    """
    import cmudict

    return cmudict.dict()


@lru_cache(maxsize=4096)
def variants(word: str) -> tuple[tuple[str, ...], ...]:
    """EVERY pronunciation this word legitimately has.

    "record" is /rEk@rd/ as a noun and /rI'kOrd/ as a verb. Comparing you
    against only the first means half the time you are marked wrong for
    saying the other correct one -- and stress is a contrast we score, so
    this misfires on exactly the feature it should serve. Same for read,
    present, object, address, live, close, lead.
    """
    entries = _cmudict().get(word.lower())
    if not entries:
        return ()
    seen: list[tuple[str, ...]] = []
    for entry in entries:
        form = tuple(p for p in (_arpabet_to_ipa(phone) for phone in entry) if p)
        if form and form not in seen:
            seen.append(form)
    return tuple(seen)


@lru_cache(maxsize=4096)
def canonical(word: str) -> tuple[str, ...]:
    """The most common pronunciation. Empty if unknown."""
    forms = variants(word)
    return forms[0] if forms else ()


def expected_phonemes(text: str) -> tuple[list[str], list[str]]:
    """Canonical phonemes for a sentence, plus the words that produced them."""
    phonemes, _, words = expected_with_words(text)
    return phonemes, words


def _build(text: str, choice: dict[str, int]) -> tuple[list[str], list[str], list[str]]:
    phonemes: list[str] = []
    owner: list[str] = []
    words: list[str] = []
    for word in _WORD.findall(text.lower()):
        forms = variants(word)
        if not forms:
            continue  # unknown word: skip rather than guess and mis-score
        form = forms[min(choice.get(word, 0), len(forms) - 1)]
        for phone in form:
            phonemes.append(phone)
            owner.append(word)
        words.append(word)
    return phonemes, owner, words


def _score(expected: list[str], actual: list[Token]) -> float:
    """Total alignment score. Higher means the two agree more.

    Matches earn, substitutions and gaps cost, using the same phonetic
    similarity the aligner uses, so the comparison between two candidate
    pronunciations is on the same footing as the alignment itself.
    """
    diffs = align(expected, actual)
    total = 0.0
    consumed = 0
    for diff in diffs:
        if diff.expected and diff.actual:
            total += _substitution_score(diff.expected, diff.actual)
            consumed += 1
        else:
            total -= 1.5
            consumed += 1 if diff.expected else 0
    return total + 2.0 * (len(expected) - consumed)


def expected_with_words(
    text: str, actual: list[Token] | None = None
) -> tuple[list[str], list[str], list[str]]:
    """Phonemes, the word each belongs to, and the word list.

    When the heard audio is supplied, each word with more than one valid
    pronunciation is tested against it and the better-fitting one is kept.
    That is the homograph fix: you are only marked wrong when you match NONE
    of the ways the word is legitimately said, rather than whichever one the
    dictionary happened to list first.
    """
    if actual is None:
        return _build(text, {})

    choice: dict[str, int] = {}
    best = _score(_build(text, choice)[0], actual)
    for word in dict.fromkeys(_WORD.findall(text.lower())):
        forms = variants(word)
        if len(forms) < 2:
            continue
        for index in range(1, len(forms)):
            trial = {**choice, word: index}
            score = _score(_build(text, trial)[0], actual)
            if score > best:
                best, choice = score, trial
    return _build(text, choice)


def heard(wav_path: str, enhance: bool = True) -> list[Token]:
    """Run the phoneme model over one recording.

    Enhancement is on by default and it is not cosmetic: on a first real
    recording it took SNR from 12 dB to 29 dB and the phoneme match rate from
    32% to 46%. The model has no language model to fall back on, so it cannot
    guess its way past noise the way a dictation app can.
    """
    import numpy as np
    import soundfile as sf
    import torch

    from .clean import enhance as enhance_audio

    extractor, vocab, model, device = _model()
    audio, rate = sf.read(wav_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if enhance:
        audio = enhance_audio(audio, rate).astype("float32")
    if rate != SAMPLE_RATE:
        raise ValueError(f"{wav_path} is {rate}Hz, expected {SAMPLE_RATE}")

    inputs = extractor(
        audio,
        sampling_rate=SAMPLE_RATE,
        return_tensors="pt",
        return_attention_mask=True,
        padding=True,
    )
    with torch.no_grad():
        # lv-60 was trained WITH an attention mask and its output degrades
        # badly without one. Omitting it turned the back half of longer
        # sentences into nonsense.
        logits = model(
            inputs.input_values.to(device),
            attention_mask=inputs.attention_mask.to(device),
        ).logits[0]
    probs = torch.softmax(logits.float(), dim=-1)
    best = probs.argmax(dim=-1)
    confidences = probs.max(dim=-1).values

    seconds_per_frame = len(audio) / SAMPLE_RATE / len(best)
    blank = model.config.pad_token_id

    tokens: list[Token] = []
    previous = None
    for frame, (index, confidence) in enumerate(
        zip(best.tolist(), confidences.tolist())
    ):
        if index == blank or index == previous:  # CTC collapse
            previous = index
            continue
        previous = index
        symbol = normalise(vocab.get(index, ""))
        if symbol and not symbol.startswith("<"):
            tokens.append(
                Token(
                    symbol=symbol,
                    confidence=float(confidence),
                    second=round(frame * seconds_per_frame, 3),
                )
            )
    return tokens


# Below this, the model produces confident nonsense rather than admitting it
# cannot hear. Measured on this machine: clean reference recordings sit near
# 37 dB and score 83%; a first pass recorded at arm's length sat at 12 dB and
# scored 32%. The sounds that vanish first are the fricatives, which is most
# of what we are trying to measure.
MIN_SNR_DB = 18.0


def audio_quality(wav_path: str) -> dict:
    """Level and signal-to-noise for one recording, before we trust it."""
    import numpy as np
    import soundfile as sf

    audio, rate = sf.read(wav_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    frame = max(int(0.02 * rate), 1)
    energies = np.array(
        [
            np.sqrt((audio[i : i + frame] ** 2).mean())
            for i in range(0, max(len(audio) - frame, 1), frame)
        ]
    )
    energies = energies[energies > 0]
    if energies.size == 0:
        return {"snr_db": 0.0, "rms_db": -99.0, "usable": False,
                "advice": "silent recording: wrong microphone, or it was muted"}

    noise = float(np.percentile(energies, 10))
    signal = float(np.percentile(energies, 90))
    snr = 20 * float(np.log10(signal / noise)) if noise > 0 else 99.0
    rms = 20 * float(np.log10(float(np.sqrt((audio ** 2).mean())) + 1e-12))

    advice = ""
    if snr < MIN_SNR_DB:
        advice = (
            f"SNR {snr:.0f} dB is too low to judge fricatives. Speak closer to "
            f"the microphone (a hand-span, not arm's length), somewhere quiet."
        )
    return {"snr_db": round(snr, 1), "rms_db": round(rms, 1),
            "usable": snr >= MIN_SNR_DB, "advice": advice}


@lru_cache(maxsize=1)
def _whisper():
    """Words, from speech that had no script.

    The probe knew its own text. Real speech does not, so something has to
    supply the words before the sounds can be judged against them. Whisper is
    used ONLY for that: what you meant. What you actually said still comes
    from the phoneme model, which has no language model and therefore no
    ability to quietly correct you.
    """
    from faster_whisper import WhisperModel

    # small.en, not base.en. Measured on real recordings: base turned
    # "go through the numbers together before Thursday" into "go through the
    # most together for photos". small gets that sentence perfectly. The
    # extra 2 seconds per chunk is nothing in a job that runs at 23:30.
    return WhisperModel("small.en", device="cpu", compute_type="int8")


# Below this, the recogniser was guessing at the word rather than hearing it.
MISHEARD_PROBABILITY = 0.55


def transcribe(wav_path: str) -> list[dict]:
    """Segments of speech, with per-word confidence.

    The confidence matters more than it looks. Measured on real recordings,
    the words Whisper got wrong were not random: "version" became "mission",
    "vulnerable" became "wondering", "delivery" became "telephony". Every one
    of them a /v/ word, from a speaker who produces /w/ for /v/.

    Whisper was not failing. It was correctly transcribing what was actually
    said. That is the circularity at the heart of this design: to judge how a
    word was pronounced we need to know which word was meant, and the only
    evidence is a pronunciation wrong enough to change the word.

    It is also the most useful signal available, because it is the real-world
    consequence rather than a proxy for it. A machine trained on enormous
    amounts of speech misheard you; a person in a meeting would too. So a low
    word probability is kept and surfaced, not discarded.
    """
    try:
        model = _whisper()
    except Exception:
        return []
    segments, _ = model.transcribe(
        wav_path, language="en", vad_filter=True, word_timestamps=True
    )
    out = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        words = [
            {
                "word": w.word.strip(),
                "start": w.start,
                "probability": w.probability,
                "misheard": w.probability < MISHEARD_PROBABILITY,
            }
            for w in (segment.words or [])
        ]
        out.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": text,
                "words": words,
                "misheard": [w for w in words if w["misheard"]],
            }
        )
    return out


def _classify(expected: str, actual: str) -> str | None:
    """Is this difference one of the ones we care about?"""
    for name, (want, instead) in CONTRASTS.items():
        if expected == want and actual in instead:
            return name
    return None


def align(expected: list[str], actual: list[Token]) -> list[Diff]:
    """Needleman-Wunsch. Substitutions are what we want; gaps are noise.

    A dropped or inserted sound is usually connected speech or a model slip,
    so gaps are recorded but never classified as a contrast error.
    """
    n, m = len(expected), len(actual)
    gap = -1.5
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i * gap
    for j in range(1, m + 1):
        score[0][j] = j * gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = _substitution_score(expected[i - 1], actual[j - 1].symbol)
            score[i][j] = max(
                score[i - 1][j - 1] + same, score[i - 1][j] + gap, score[i][j - 1] + gap
            )

    diffs: list[Diff] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            same = _substitution_score(expected[i - 1], actual[j - 1].symbol)
            if abs(score[i][j] - (score[i - 1][j - 1] + same)) < 1e-9:
                if expected[i - 1] != actual[j - 1].symbol:
                    diffs.append(
                        Diff(
                            expected=expected[i - 1],
                            actual=actual[j - 1].symbol,
                            contrast=_classify(expected[i - 1], actual[j - 1].symbol),
                            confidence=actual[j - 1].confidence,
                            index=i - 1,
                            second=actual[j - 1].second,
                        )
                    )
                i, j = i - 1, j - 1
                continue
        if i > 0 and abs(score[i][j] - (score[i - 1][j] + gap)) < 1e-9:
            diffs.append(Diff(expected[i - 1], None, None, 0.0, i - 1))
            i -= 1
        else:
            diffs.append(
                Diff(None, actual[j - 1].symbol, None, actual[j - 1].confidence, i,
                     actual[j - 1].second)
            )
            j -= 1
    diffs.reverse()
    return diffs


def analyse(wav_path: str, text: str) -> dict:
    """Everything about one recording, with the text already known.

    Quality is measured first and reported alongside. A finding from audio
    the model cannot hear is worse than no finding, because it looks
    identical to a real one.
    """
    quality = audio_quality(wav_path)
    actual = heard(wav_path)
    expected, owner, words = expected_with_words(text, actual)
    diffs = align(expected, actual)
    for diff in diffs:  # name the word each difference happened in
        if 0 <= diff.index < len(owner):
            diff.word = owner[diff.index]
    scored = [d for d in diffs if d.scored]
    matched = sum(
        1 for d in diffs if d.expected is not None and d.actual is not None
    )
    return {
        "path": wav_path,
        "quality": quality,
        "text": text,
        "words": words,
        "expected_count": len(expected),
        "heard_count": len(actual),
        "expected": expected,
        "heard": [t.symbol for t in actual],
        "diffs": diffs,
        "scored": scored,
        "substitutions": matched,
        "agreement": 1 - (len(diffs) / max(len(expected), 1)),
    }
