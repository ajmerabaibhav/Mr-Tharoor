"""What you said and what you typed, against what a teacher would mark.

Pronunciation is one habit. "Discuss about", "revert back", "I did not went",
"the people that is building" -- those are the other habit, and they cost the
same thing in a meeting: the listener has to work harder to follow you.

Two engines live here.

    check() / compare()   seven explicit rules and your own hand corrections.
                          Local, free, and measured: across a month of real
                          dictation they found nothing at all.

    llm_check()           the Claude Code CLI already installed on this
                          machine, given the day's raw transcripts. On one
                          real day: 23 corrections where the rules found 0.

The rules remain as the fallback when the CLI is absent or MR_THAROOR_NO_LLM
is set, because a grammar section that needs a network is worse than a thin
one that does not.

What keeps the second engine honest is not the prompt, it is the check after
it: every correction must quote a span that really appears in the transcript,
or it is dropped. A model that invents a mistake you never made loses the
whole report's credibility in one morning.

A transcript can still be wrong. Speech is marked against what the recogniser
heard, so a mishearing can read as a grammar slip; the report says so, and the
recording is there to check against.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

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
    "discuss about": "discuss",
    "one of my friend": "one of my friends",
    "cope up with": "cope with",
    # MEASURED: the checker caught "revert back" and "discussed about" but
    # skipped "am having a doubt" on all four runs of a 20-error probe. A rule
    # costs nothing and never has an off night, so the certain ones live here.
    #
    # The line these stop at matters. "am having" for "have" is a stative verb
    # in the continuous, which is grammar. "doubt" for "question", "prepone",
    # "do the needful" are Indian English vocabulary, which is not a mistake,
    # and a tool that marks them is not teaching, it is sneering.
    "am having a doubt": "have a doubt",
    "revert back": "reply",
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
    "phrase": "Check the construction in the recording before practising the suggested form.",
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
    basis: str = "legacy"  # rule | user_edit | llm; old rewrite-only findings stay archived
    why: str = ""  # the rule, in the checker's own words
    mode: str = "spoken"  # spoken | typed -- which half of the day this came from
    label: str = ""  # ONE word naming the rule, so you can say why it is wrong

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
        return self.why or RULES.get(self.kind, "")


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
    return _WORD.findall(text.lower().replace("’", "'"))


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
    # Shared first letters (computer/company, thing/think) prove nothing.
    return len(shorter) >= 3 and (
        longer in {shorter + "s", shorter + "es", shorter + "ed", shorter + "ing"}
        or (shorter.endswith("y") and longer == shorter[:-1] + "ies")
    )


def _phrase_window(words: list[str], start: int, end: int, pad: int = CONTEXT) -> str:
    lo, hi = max(start - pad, 0), min(end + pad, len(words))
    return " ".join(words[lo:hi])


def check(text: str, source: str = "", mode: str = "spoken") -> list[GrammarFinding]:
    """Small explicit grammar rules on the raw transcript, with no LLM rewrite."""
    words = _words(text)
    normalized = " ".join(words)
    out = []
    rules = [(re.escape(before), after, "phrase") for before, after in KNOWN_PHRASES.items()]
    rules += [
        (r"(he|she|it) don't", r"\1 doesn't", "verb"),
        (r"(he|she|it) are", r"\1 is", "verb"),
        (r"(we|they|you) is", r"\1 are", "verb"),
        (r"i is", "i am", "verb"),
    ]
    for pattern, replacement, kind in rules:
        for match in re.finditer(r"\b(?:" + pattern + r")\b", normalized):
            said = match.group()
            fixed = match.expand(replacement)
            change, word = _describe(_words(said), _words(fixed))
            out.append(GrammarFinding(kind, said, fixed, _around(text, said), source,
                                      change=change, word=word, basis="rule",
                                      label=kind, mode=mode))
    return out


def compare(heard: str, meant: str, source: str = "", *, edited: bool = False) -> list[GrammarFinding]:
    """Corrections between what was heard and what was meant."""
    if not edited:
        return check(heard, source)
    hw, mw = _words(heard), _words(meant)
    if not hw or not mw:
        return []
    out = check(heard, source)

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
        if not any(f.said in said for f in out):
            out.append(GrammarFinding(kind, said, fixed, heard.strip()[:160], source,
                                      change=change, word=word, basis="user_edit"))
    return out


def summarise(findings: list[GrammarFinding], limit: int = 8) -> list[dict]:
    """The habits, not the incidents. Same correction twice is a pattern."""
    counts: Counter = Counter()
    example: dict[tuple[str, str, str], GrammarFinding] = {}
    seen: set[tuple] = set()
    for f in findings:
        if f.basis == "legacy":
            continue
        key = (f.kind, f.said, f.should_be)
        occurrence = (*key, f.source)
        if f.source and occurrence in seen:
            continue
        seen.add(occurrence)
        counts[key] += 1
        example.setdefault(key, f)
    rows = []
    for key, n in counts.most_common(limit):
        f = example[key]
        rows.append({**asdict(f), "times": n})
    return rows


# --------------------------------------------------------------------------
# The checker that actually finds things.
#
# The rules above catch seven constructions. Measured against a month of real
# dictation they found nothing: every grammar.json this project has written is
# an empty list. A person's actual mistakes -- "the result which you have
# gave", "the people that is building", "tell me that whether" -- are not seven
# patterns, and writing the eighth, ninth and two-hundredth regex is a life.
#
# Claude Code is already installed on this machine and already holds a
# subscription, so the grammar half costs one subprocess call a night and no
# new dependency. Text leaves the laptop for that call; audio never does, and
# the great majority of this text was dictated or typed into Claude to begin
# with. MR_THAROOR_NO_LLM=1 turns it off and leaves the local rules.
#
# Every correction it returns is checked against the transcript before it is
# believed: if the span it claims you said is not in the text, it is dropped.
# --------------------------------------------------------------------------

LLM_MODEL = os.environ.get("MR_THAROOR_LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_BATCH = 20  # utterances per call
LLM_MAX_BATCHES = 8  # a day cannot cost more than this
LLM_TIMEOUT = 420  # seconds per call; the nightly job has all night

PROMPT = """You are an exacting English teacher marking a fluent Indian English speaker's real {kind}. Each numbered item below is one {unit}.

Mark ONLY errors a grammar teacher would mark: subject-verb agreement, tense, articles, prepositions, singular/plural, verb form, word order, pronouns, countability, and fixed-phrase misuse ("discuss about", "revert back", "one of my friend").

Do NOT mark: punctuation, capitalisation, spelling, filler words (um, yeah, so, like), repetition or self-correction, incomplete sentences, style, wordiness, register, or anything that is merely a different way of saying the same thing. {caveat}

For each real error output ONE line of JSON and nothing else:
{{"i": <item number>, "said": "<the exact 2-8 word span, copied verbatim from the item>", "should_be": "<the corrected span>", "kind": "<article|preposition|number|verb|tense|word-order|pronoun|phrase>", "label": "<ONE lowercase word naming the rule, the word a teacher would say: agreement, article, participle, plural, preposition, tense, order, pronoun, countable, idiom, possessive, comparative, infinitive, gerund>", "why": "<max 12 words, the rule>"}}

The label matters: it is the one word the speaker should be able to say back when asked why the correction is right.

No preamble, no markdown fences, no summary, no repeated corrections. If an item has no error, output nothing for it. Be strict: when in doubt, leave it out.

ITEMS:
{items}"""

SPOKEN_CAVEAT = ("This is speech-to-text output, so a wrong word the recogniser produced is NOT an error: "
                 "skip anything that reads like a mishearing rather than a grammar slip.")
TYPED_CAVEAT = ("This is typed into a terminal, so missing capitals and apostrophes are not errors, "
                "and a typo is not a grammar mistake.")

KINDS = {"article", "preposition", "number", "verb", "tense", "word-order", "pronoun", "phrase"}


def llm_binary() -> str | None:
    """launchd's PATH is four directories long. Find the CLI ourselves."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude"),
                      Path("/usr/local/bin/claude")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def llm_available() -> bool:
    return not os.environ.get("MR_THAROOR_NO_LLM") and llm_binary() is not None


def _normalised(text: str) -> str:
    return " ".join(_words(text))


def _run_claude(prompt: str) -> str:
    """One headless call. No MCP servers: measured, they doubled the wall time.

    cwd is inside our own data directory on purpose. Claude Code writes a
    transcript for every session under ~/.claude/projects/<cwd>/, and typed.py
    reads those transcripts as the day's typing -- so a grammar call made from
    the user's own project would feed its own prompt back in tomorrow night.
    """
    from . import config

    binary = llm_binary()
    if not binary:
        return ""
    workdir = config.DATA_DIR / "llm"
    workdir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [binary, "-p", prompt, "--model", LLM_MODEL,
         "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}'],
        capture_output=True, text=True, timeout=LLM_TIMEOUT, cwd=str(workdir),
        env=_environment(),
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "claude exited non-zero").strip()[:200])
    return result.stdout


def _environment() -> dict:
    """The environment launchd does not necessarily give us.

    MEASURED, and the reason this function exists: with USER unset the CLI
    answers "Not logged in - please run /login" and exits 0, so the nightly
    job would have found nothing every night and said nothing about why. PATH
    is widened for the same class of reason: the CLI runs the user's own
    hooks, and those call node.
    """
    import pwd

    env = dict(os.environ)
    env.setdefault("HOME", str(Path.home()))
    try:
        env.setdefault("USER", pwd.getpwuid(os.getuid()).pw_name)
    except KeyError:
        pass
    parts = env.get("PATH", "").split(":")
    for extra in (str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"):
        if extra not in parts:
            parts.append(extra)
    env["PATH"] = ":".join(p for p in parts if p)
    return env


def _objects(reply: str):
    """Every JSON object in the reply, however it chose to lay them out.

    One object per line is what the prompt asks for, but a reply that puts two
    on one line, or wraps them in an array, used to parse to nothing at all --
    silently, because the line still began with a brace. A scanner does not
    care about the layout.
    """
    decoder = json.JSONDecoder()
    at = 0
    while True:
        start = reply.find("{", at)
        if start < 0:
            return
        try:
            row, end = decoder.raw_decode(reply, start)
        except ValueError:
            at = start + 1
            continue
        at = end
        if isinstance(row, dict):
            yield row


def _around(text: str, said: str, width: int = 150) -> str:
    """The sentence around the mistake. The first 150 characters of a two
    minute dictation are usually nowhere near it, which teaches nothing."""
    text = " ".join(text.split())
    at = text.lower().find(said.lower().strip())
    if at < 0:  # matched on normalised words, so the raw span may differ
        first = _words(said)[0] if _words(said) else ""
        at = text.lower().find(first) if first else -1
    if at < 0:
        return text[:width]
    start = max(0, at - width // 3)
    snippet = text[start:start + width]
    return ("..." if start else "") + snippet + ("..." if start + width < len(text) else "")


def parse_llm(reply: str, items: list[tuple[str, str]], mode: str = "spoken") -> list[GrammarFinding]:
    """Believe a correction only when the span it quotes is really in the text."""
    out: list[GrammarFinding] = []
    seen: set[tuple] = set()
    for row in _objects(reply):
        try:
            index = int(row["i"]) - 1
            said, should_be = str(row["said"]).strip(), str(row["should_be"]).strip()
            kind, why = str(row.get("kind", "")).strip(), str(row.get("why", "")).strip()
            label = str(row.get("label", "")).strip().lower().split()[0][:18] if row.get("label") else ""
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= index < len(items)) or not said or not should_be:
            continue
        source, text = items[index]
        if _normalised(said) not in _normalised(text):
            continue  # not in the transcript: a paraphrase or an invention
        if _normalised(said) == _normalised(should_be):
            continue
        key = (source, _normalised(said), _normalised(should_be))
        if key in seen:
            continue
        seen.add(key)
        change, word = _describe(_words(said), _words(should_be))
        if kind == "word-order":
            change, word = "", ""  # "use X" is meaningless when the words only moved
        out.append(GrammarFinding(
            kind=kind if kind in KINDS else "phrase", said=said, should_be=should_be,
            context=_around(text, said), source=source, change=change, word=word,
            basis="llm", why=why[:90], mode=mode, label=label,
        ))
    return out


def merge(llm: list[GrammarFinding], rules: list[GrammarFinding]) -> list[GrammarFinding]:
    """Rule findings the model did not already make, so nothing is said twice."""
    covered = {(f.source, _normalised(f.said)) for f in llm}
    extra = []
    for f in rules:
        spans = _normalised(f.said)
        if any(source == f.source and (spans in said or said in spans)
               for source, said in covered):
            continue
        extra.append(f)
    return llm + extra


def llm_check(items: list[tuple[str, str]], mode: str = "spoken", *, logger=None) -> list[GrammarFinding]:
    """Grammar over a day's utterances. `items` is [(source label, text), ...]."""
    items = [(source, text) for source, text in items if len(_words(text)) >= 4]
    if not items or not llm_available():
        return []
    out: list[GrammarFinding] = []
    batches = [items[i:i + LLM_BATCH] for i in range(0, len(items), LLM_BATCH)][:LLM_MAX_BATCHES]
    for batch in batches:
        listing = "\n".join(f"[{n}] {text.strip()[:600]}" for n, (_, text) in enumerate(batch, 1))
        prompt = PROMPT.format(
            kind="speech" if mode == "spoken" else "writing",
            unit="utterance" if mode == "spoken" else "message",
            caveat=SPOKEN_CAVEAT if mode == "spoken" else TYPED_CAVEAT,
            items=listing,
        )
        try:
            reply = _run_claude(prompt)
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            if logger:
                logger.warning(f"grammar check failed ({mode}): {type(exc).__name__}: {exc}")
            break
        found = parse_llm(reply, batch, mode)
        if not found and reply.strip() and logger:
            # An empty reply is normal; an empty reply that is not JSON at all
            # is the CLI telling us something, usually that it is logged out.
            # A reply that produced nothing is either a clean day or a format
            # change that has quietly switched the grammar half off. Either way
            # it goes in the log, because the second one is invisible otherwise.
            logger.warning(f"grammar checker returned no usable correction; it said: "
                           f"{reply.strip()[:160]}")
        out += found
    return out
