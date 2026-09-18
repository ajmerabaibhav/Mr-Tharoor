"""What you said, against what you meant to say. The grammar half.

Pronunciation is one habit. "Discuss about", "revert back", "I am having a
doubt", a missing article, a preposition off by one -- those are the other
habit, and they cost the same thing in a meeting: the listener has to work
harder to follow you.

Wispr Flow already produces the comparison. Its recogniser writes down what
you said; its language model rewrites it into what you meant; and when you
correct that by hand, you produce the best version of all. The difference
between the first and the last is a list of your own corrections, made for
you, every time you dictate.

Most of that difference is NOT grammar. The model also strips fillers, moves
commas, and rephrases for style. So the diff is filtered hard, and only the
kinds of change that a grammar teacher would mark survive:

    preposition     "discuss about it"  ->  "discuss it"
    article         "I am engineer"     ->  "I am an engineer"
    number          "one of the thing"  ->  "one of the things"
    verb form       "he don't"          ->  "he doesn't"
    fixed phrase    "revert back"       ->  "reply"

Everything else -- rewording, reordering, a sentence cut in half -- is
discarded, because reporting a style preference as a mistake is how a tool
loses someone's trust in one morning.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import asdict, dataclass

FILLERS = {"um", "uh", "umm", "uhh", "hmm", "like", "yeah", "yep", "okay", "ok", "so",
           "basically", "actually", "literally", "you know", "i mean", "right", "well"}
PREPOSITIONS = {"at", "on", "in", "for", "to", "of", "about", "with", "by", "from",
                "into", "onto", "upon", "over", "under", "through", "during", "since",
                "till", "until", "after", "before", "than", "as"}
ARTICLES = {"a", "an", "the"}
AUXILIARIES = {"is", "are", "was", "were", "am", "be", "been", "being",
               "has", "have", "had", "do", "does", "did", "will", "would",
               "shall", "should", "can", "could", "may", "might", "must"}

# Indian English fixed phrases that a native-trained model reliably rewrites.
# Kept explicit because they are the highest-value catches and the diff alone
# cannot tell "revert back -> reply" from an ordinary rewording.
KNOWN_PHRASES = {
    "revert back": "reply",
    "discuss about": "discuss",
    "prepone": "bring forward",
    "do the needful": "do what is needed",
    "i am having a doubt": "I have a question",
    "having a doubt": "have a question",
    "out of station": "out of town",
    "the same": "it",
    "kindly": "please",
    "updation": "update",
    "one of my friend": "one of my friends",
    "cope up with": "cope with",
    "order for": "order",
    "return back": "return",
}

_WORD = re.compile(r"[a-z']+")


@dataclass
class GrammarFinding:
    """One correction, with enough context to hear yourself in it."""

    kind: str  # preposition | article | number | verb | phrase
    said: str
    should_be: str
    context: str  # the sentence you said, as heard
    source: str  # which dictation

    @property
    def headline(self) -> str:
        return f'you said "{self.said}", it should be "{self.should_be}"'


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _is_filler_only(words: list[str]) -> bool:
    return bool(words) and all(w in FILLERS for w in words)


def _classify(before: list[str], after: list[str]) -> str | None:
    """What kind of correction is this, or None if it is not one we report."""
    b, a = " ".join(before), " ".join(after)
    if not before and not after:
        return None
    if _is_filler_only(before) and not after:
        return None  # a filler removed is editing, not grammar
    if b == a:
        return None

    if b in KNOWN_PHRASES:
        return "phrase"

    # Single-word swaps are the clearest signal.
    if len(before) == 1 and len(after) == 1:
        x, y = before[0], after[0]
        if x in PREPOSITIONS and y in PREPOSITIONS:
            return "preposition"
        if x in ARTICLES and y in ARTICLES:
            return "article"
        if x in AUXILIARIES and y in AUXILIARIES:
            return "verb"
        if _same_stem(x, y):
            if (x.endswith("s") != y.endswith("s")) and abs(len(x) - len(y)) <= 2:
                return "number"
            return "verb"
        return None  # a different word altogether: vocabulary, not grammar

    # An article or preposition inserted or removed.
    if not before and len(after) == 1 and after[0] in ARTICLES:
        return "article"
    if len(before) == 1 and not after and before[0] in ARTICLES:
        return "article"
    if len(before) == 1 and not after and before[0] in PREPOSITIONS:
        return "preposition"
    if not before and len(after) == 1 and after[0] in PREPOSITIONS:
        return "preposition"

    # "discuss about it" -> "discuss it": a preposition dropped inside a phrase.
    if len(before) == len(after) + 1:
        extra = [w for w in before if w not in after]
        if len(extra) == 1 and extra[0] in PREPOSITIONS:
            return "preposition"
    return None


def _same_stem(x: str, y: str) -> bool:
    shorter, longer = sorted((x, y), key=len)
    return len(shorter) >= 3 and longer.startswith(shorter[: max(3, len(shorter) - 2)])


def _phrase_window(words: list[str], start: int, end: int, pad: int = 2) -> str:
    lo, hi = max(start - pad, 0), min(end + pad, len(words))
    return " ".join(words[lo:hi])


def compare(heard: str, meant: str, source: str = "") -> list[GrammarFinding]:
    """Corrections between what was heard and what was meant."""
    hw, mw = _words(heard), _words(meant)
    if not hw or not mw:
        return []
    out: list[GrammarFinding] = []

    # Fixed phrases first, on the raw text, so they are never split by the diff.
    lowered = " " + " ".join(hw) + " "
    for phrase, fix in KNOWN_PHRASES.items():
        if f" {phrase} " in lowered and phrase not in " ".join(mw):
            out.append(GrammarFinding("phrase", phrase, fix, heard.strip()[:160], source))

    matcher = difflib.SequenceMatcher(None, hw, mw, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before, after = hw[i1:i2], mw[j1:j2]
        if len(before) > 4 or len(after) > 4:
            continue  # a rewrite, not a correction
        kind = _classify(before, after)
        if kind is None or kind == "phrase":
            continue
        said = _phrase_window(hw, i1, i2) if before else _phrase_window(hw, i1, i1)
        fixed = _phrase_window(mw, j1, j2) if after else _phrase_window(mw, j1, j1)
        if said == fixed:
            continue
        out.append(GrammarFinding(kind, said, fixed, heard.strip()[:160], source))
    return out


def summarise(findings: list[GrammarFinding], limit: int = 8) -> list[dict]:
    """The habits, not the incidents. Same correction twice is a pattern."""
    counts: Counter = Counter()
    example: dict[tuple[str, str, str], GrammarFinding] = {}
    for f in findings:
        key = (f.kind, f.said, f.should_be)
        counts[key] += 1
        example.setdefault(key, f)
    rows = []
    for key, n in counts.most_common(limit):
        f = example[key]
        rows.append({**asdict(f), "times": n})
    return rows
