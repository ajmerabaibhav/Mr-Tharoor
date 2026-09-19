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
CONTEXT = 2  # matching words required on each side of a correction

# How far back habits are counted. MEASURED on real history: 7 days gave 1
# habit, 14 gave 2, 30 gave 4, 60 gave 8. A grammar habit is stable over a
# month, and a month is recent enough that fixing it still matters. Seven
# days was my guess and the data did not support it.
HABIT_WINDOW_DAYS = 30


# What actually changed, and the rule behind it. A correction that only
# shows two phrases makes you find the difference yourself; naming the word
# and the reason is the part that teaches.
RULES = {
    "article": "English wants an article here. Count nouns rarely stand alone.",
    "preposition": "The verb governs which preposition follows it, and it is not free choice.",
    "number": "The noun and its determiner must agree in number.",
    "verb": "The verb must agree with its subject, in person and in tense.",
    "phrase": "A fixed expression that reads as Indian English to other ears.",
}


@dataclass
class GrammarFinding:
    """One correction, with enough context to hear yourself in it."""

    kind: str  # preposition | article | number | verb | phrase
    said: str
    should_be: str
    context: str  # the sentence you said, as heard
    source: str  # which dictation
    change: str = ""  # "add", "use", "drop"
    word: str = ""  # the word to add, use, or drop

    @property
    def headline(self) -> str:
        return f'you said "{self.said}", it should be "{self.should_be}"'

    @property
    def instruction(self) -> str:
        """The single actionable sentence: which word, and what to do with it."""
        if self.change == "add":
            return f'add "{self.word}"'
        if self.change == "drop":
            return f'drop "{self.word}"'
        if self.change == "use":
            return f'use "{self.word}"'
        return ""

    @property
    def rule(self) -> str:
        return RULES.get(self.kind, "")


def _describe(before: list[str], after: list[str]) -> tuple[str, str]:
    """Which word changed, and whether it was added, dropped or swapped."""
    missing = [w for w in after if w not in before]
    extra = [w for w in before if w not in after]
    if missing and not extra:
        return "add", missing[0]
    if extra and not missing:
        return "drop", extra[0]
    if missing:
        return "use", missing[0]
    return "", ""


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


def _phrase_window(words: list[str], start: int, end: int, pad: int = CONTEXT) -> str:
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
            out.append(GrammarFinding("phrase", phrase, fix, heard.strip()[:160], source,
                                      change="use", word=fix))

    matcher = difflib.SequenceMatcher(None, hw, mw, autojunk=False)
    opcodes = matcher.get_opcodes()
    for n, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            continue
        # A correction is ISOLATED: at least CONTEXT matching words on each
        # side of it. difflib always alternates equal and changed runs, so
        # "is the neighbour equal" is trivially true; what leaked was a
        # one-word equal run between two changes, which the two-word context
        # window then read straight across into the neighbouring rewrite,
        # producing "what use computer use" -> "out use the computer use".
        # Those were never corrections; they were fragments of a different
        # sentence. Now the matching run must be as wide as the window.
        def _run(k: int) -> int:
            if k < 0 or k >= len(opcodes) or opcodes[k][0] != "equal":
                return 0
            return opcodes[k][2] - opcodes[k][1]

        at_start, at_end = n == 0, n == len(opcodes) - 1
        if not ((at_start or _run(n - 1) >= CONTEXT) and (at_end or _run(n + 1) >= CONTEXT)):
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
        change, word = _describe(before, after)
        out.append(GrammarFinding(kind, said, fixed, heard.strip()[:160], source,
                                  change=change, word=word))
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
