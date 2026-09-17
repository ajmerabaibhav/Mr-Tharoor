"""How is this word actually said? Fetch the human recording, keep it forever.

You cannot learn a sound by reading a symbol. So every word we flag gets a
real recording of a real person saying it, pulled once from Wiktionary (the
files live on Wikimedia Commons, freely licensed) and cached on disk. After
the first fetch the word is offline forever -- no network, no account, no API
key, nothing leaves the machine but the word itself.

Commons stores originals as .ogg, which macOS cannot play natively. Wikimedia
also publishes an .mp3 transcode of every audio file, and afplay handles mp3,
so we take the transcode and skip ffmpeg entirely.

When no human has recorded a word, we fall back to the macOS speech synth --
fully offline, and honest about being synthetic in the UI.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config, net

API = "https://en.wiktionary.org/w/api.php"
_AUDIO_SUFFIXES = (".ogg", ".mp3", ".wav", ".flac")


@dataclass
class Pronunciation:
    """One word, how it sounds, and where the sound lives on disk."""

    word: str
    ipa: str | None
    audio_path: str | None
    accent: str | None
    source: str  # "wiktionary" | "synthetic" | "missing" | "error"
    credit: str | None = None

    @property
    def is_human(self) -> bool:
        return self.source == "wiktionary"

    def __str__(self) -> str:
        bits = [self.word]
        if self.ipa:
            bits.append(self.ipa)
        if self.source == "wiktionary":
            bits.append(f"[{self.accent}, human]")
        elif self.source == "synthetic":
            bits.append("[synthetic]")
        elif self.source == "error":
            bits.append("[lookup failed, not cached]")
        else:
            bits.append("[no audio]")
        return "  ".join(bits)


_SAFE_KEY = re.compile(r"[^a-z0-9'-]+")


def cache_key(word: str) -> str:
    """A filesystem-safe name for a word.

    Words reach this from the command line and, later, from whatever the
    speech recogniser produces. Both are untrusted. Without this, the word
    "../../../../tmp/x" writes an mp3 outside the cache directory entirely,
    and a word beginning with "-" is read by `say` as a command-line flag.

    Apostrophes and hyphens survive because real words use them ("don't",
    "co-founder"); leading hyphens do not.
    """
    key = _SAFE_KEY.sub("", word.strip().lower()).lstrip("-'")
    if not key:
        raise ValueError(f"no usable characters in word {word!r}")
    return key[:64]


def _index() -> dict:
    if not config.INDEX_FILE.exists():
        return {}
    try:
        return json.loads(config.INDEX_FILE.read_text())
    except json.JSONDecodeError:
        # Do not silently start fresh: the next save would replace every
        # cached word with one entry. Keep the bytes, say so, refetch.
        dead = config.quarantine(config.INDEX_FILE)
        print(f"mr-roy: cache index was unreadable, kept a copy at {dead}")
        return {}


def _save_index(index: dict) -> None:
    config.write_json_atomically(config.INDEX_FILE, index)


def _get(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode({**params, 'format': 'json'})}"
    return net.get_json(url, config.USER_AGENT, config.NETWORK_TIMEOUT)


def _accent_of(filename: str) -> str | None:
    name = filename.lower()
    for accent in config.ACCENT_PREFERENCE:
        if name.startswith(f"file:{accent}-") or f"{accent}-" in name:
            return accent
    return None


def _rank(filename: str) -> int:
    """Lower is better. Prefers the accent order in config."""
    accent = _accent_of(filename)
    if accent is None:
        return len(config.ACCENT_PREFERENCE)
    return config.ACCENT_PREFERENCE.index(accent)


# File:en-us-measure.ogg  ->  accent "en-us", word "measure"
# File:en-us-data2.ogg    ->  accent "en-us", word "data"  (numbered variant)
_FILENAME = re.compile(
    r"^file:(?P<accent>en(?:-[a-z]{2,3})?)-(?P<word>.+?)\d*\.(?:ogg|mp3|wav|flac)$",
    re.IGNORECASE,
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _filename_word(title: str) -> str | None:
    match = _FILENAME.match(title)
    return match.group("word") if match else None


def _pick_audio(titles: list[str], word: str) -> str | None:
    """Choose the recording for this word and no other word.

    The filename must name EXACTLY this word. Substring matching looks
    harmless and is not: asking for "three" happily returns the recording of
    "threesome", and "read" returns "already". Playing a different word to
    someone learning pronunciation is the worst failure this tool has, and it
    fails silently -- the audio plays, it just teaches the wrong thing.
    """
    target = _slug(word)
    candidates = [
        t
        for t in titles
        if (found := _filename_word(t)) is not None and _slug(found) == target
    ]
    return min(candidates, key=_rank) if candidates else None


def _english_section(wikitext: str) -> str:
    """Wiktionary pages cover every language; we only want the English one."""
    match = re.search(r"^==\s*English\s*==(.*?)(?=^==[^=]|\Z)", wikitext, re.S | re.M)
    return match.group(1) if match else wikitext


def _extract_ipa(wikitext: str) -> str | None:
    english = _english_section(wikitext)
    # {{IPA|en|/ˈvɜːʒən/|/ˈvɝʒən/}} -- take the first slashed transcription.
    for template in re.finditer(r"\{\{IPA\|en\|([^}]+)\}\}", english):
        for field in template.group(1).split("|"):
            field = field.strip()
            if field.startswith("/") and field.endswith("/") and len(field) > 2:
                return field
    return None


def _download(url: str, dest: Path) -> bool:
    """True on success, False when the file genuinely is not there.

    Raises net.TransientError so the caller can avoid caching a network
    problem as a permanent answer.
    """
    try:
        data = net.get_bytes(url, config.USER_AGENT, config.NETWORK_TIMEOUT)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise net.TransientError(f"HTTP {exc.code} for {url}") from exc
    if len(data) < 512:  # an error page, not audio
        return False
    dest.write_bytes(data)
    return True


def _synthesise(word: str, dest: Path) -> bool:
    """Local macOS speech synth. Offline, no network, clearly marked as robot."""
    aiff = dest.with_suffix(".aiff")
    aiff.unlink(missing_ok=True)  # a stale file must not look like success
    result = subprocess.run(
        ["say", "-v", config.FALLBACK_VOICE, "-o", str(aiff), cache_key(word)],
        capture_output=True,
        timeout=20,
    )
    return result.returncode == 0 and aiff.exists()


def _fetch(word: str) -> Pronunciation:
    """One page load: audio file list and wikitext together."""
    try:
        data = _get(
            {
                "action": "query",
                "titles": word,
                "prop": "images|revisions",
                "imlimit": "100",
                "rvprop": "content",
                "rvslots": "main",
            }
        )
    except net.TransientError as exc:
        return Pronunciation(word, None, None, None, "error", str(exc))
    except (urllib.error.HTTPError, json.JSONDecodeError) as exc:
        return Pronunciation(word, None, None, None, "error", str(exc))

    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    if "missing" in page:
        return Pronunciation(word, None, None, None, "missing")

    wikitext = ""
    for rev in page.get("revisions", []):
        wikitext = rev.get("slots", {}).get("main", {}).get("*", "") or rev.get("*", "")
        break
    ipa = _extract_ipa(wikitext)

    title = _pick_audio([i["title"] for i in page.get("images", [])], word)
    if title is None:
        return _synth_entry(word, ipa)

    dest = config.AUDIO_DIR / f"{cache_key(word)}.mp3"
    try:
        downloaded = _download(net.transcode_url(title), dest)
    except net.TransientError as exc:
        return Pronunciation(word, ipa, None, None, "error", str(exc))
    if not downloaded:
        # The file exists on Commons but has no mp3 transcode. Rare, and the
        # synth is a genuine answer here, not a masked failure.
        return _synth_entry(word, ipa)

    return Pronunciation(
        word=word,
        ipa=ipa,
        audio_path=str(dest),
        accent=_accent_of(title),
        source="wiktionary",
        credit=f"{title} via Wikimedia Commons",
    )


def _synth_entry(word: str, ipa: str | None) -> Pronunciation:
    dest = config.AUDIO_DIR / f"{cache_key(word)}.aiff"
    if _synthesise(word, dest):
        return Pronunciation(word, ipa, str(dest), None, "synthetic", config.FALLBACK_VOICE)
    return Pronunciation(word, ipa, None, None, "missing")


def lookup(word: str, refresh: bool = False) -> Pronunciation:
    """Pronunciation for one word. Network only on the first ever lookup."""
    key = cache_key(word)

    index = _index()
    if not refresh and key in index:
        cached = Pronunciation(**index[key])
        # A cache entry whose audio file was deleted is worse than no entry.
        if cached.audio_path is None or Path(cached.audio_path).exists():
            return cached

    entry = _fetch(key)
    if entry.source != "error":
        index[key] = asdict(entry)
        _save_index(index)
    return entry


def play(word: str, blocking: bool = True) -> Pronunciation:
    """Say it out loud. This is the whole point of the tool."""
    entry = lookup(word)
    if entry.audio_path:
        cmd = ["afplay", entry.audio_path]
        subprocess.run(cmd) if blocking else subprocess.Popen(cmd)
    return entry


def cached_words() -> list[str]:
    return sorted(_index())


if __name__ == "__main__":
    import sys

    for w in sys.argv[1:] or ["version"]:
        print(play(w))
