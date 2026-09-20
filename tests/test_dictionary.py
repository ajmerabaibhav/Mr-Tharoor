"""The dictionary's job: correct audio, cached, and never lying about failure.

The parsing and URL-derivation checks run offline. The one network test is
skipped when the network is unavailable, so this suite stays useful on a plane.

Run: python3 tests/test_dictionary.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mr_tharoor import dictionary as d
from mr_tharoor import net


def test_commons_url_capitalisation():
    """MediaWiki uppercases the first letter before hashing. Miss it and every
    derived URL 404s, which is exactly the bug that made real words look
    unrecorded."""
    url = net.commons_url("File:en-us-version.ogg")
    assert url == (
        "https://upload.wikimedia.org/wikipedia/commons/b/b3/En-us-version.ogg"
    ), url
    assert net.transcode_url("File:en-us-version.ogg").endswith(
        "/transcoded/b/b3/En-us-version.ogg/En-us-version.ogg.mp3"
    )
    print("commons url derivation      ok")


def test_pick_audio_requires_the_word():
    """A page links audio for related forms too. Picking one of those means
    playing the wrong word at someone trying to learn it."""
    titles = [
        "File:en-us-third.ogg",
        "File:en-us-three.ogg",
        "File:en-uk-three.ogg",
        "File:Some diagram.svg",
    ]
    assert d._pick_audio(titles, "three") == "File:en-us-three.ogg"
    assert d._pick_audio(["File:en-us-third.ogg"], "three") is None
    assert d._pick_audio([], "three") is None
    print("audio selection             ok")


def test_never_plays_a_different_word():
    """The worst bug this tool can have, because it fails silently: the audio
    plays, it just teaches the wrong word. Substring matching caused exactly
    this -- "three" returned threesome, "read" returned already."""
    assert d._pick_audio(["File:en-us-threesome.ogg"], "three") is None
    assert d._pick_audio(["File:en-us-already.ogg"], "read") is None
    assert d._pick_audio(["File:en-us-available.ogg"], "ai") is None
    assert d._pick_audio(["File:en-us-versioning.ogg"], "version") is None
    # numbered variants of the SAME word are still the right word
    assert d._pick_audio(["File:en-us-data2.ogg"], "data") == "File:en-us-data2.ogg"
    # a sentence recording that merely mentions the word is not a pronunciation
    assert d._pick_audio(["File:LL-Q1860 (eng)-I said measure.wav"], "measure") is None
    print("never the wrong word        ok")


def test_words_cannot_escape_the_cache_directory():
    """Words arrive from the command line and, later, from the speech
    recogniser. Both are untrusted. Before this, the word "../../../../tmp/x"
    wrote an mp3 outside the project entirely."""
    from mr_tharoor import config

    for hostile in ("../../../../tmp/roy-escape", "/etc/passwd", "..\\..\\win", "a/b/c"):
        key = d.cache_key(hostile)
        assert "/" not in key and ".." not in key, key
        path = (config.AUDIO_DIR / f"{key}.mp3").resolve()
        assert str(path).startswith(str(config.AUDIO_DIR.resolve())), path

    # a word that `say` would read as a flag must not reach it as one
    assert not d.cache_key("--help").startswith("-")
    # real words keep their real characters
    assert d.cache_key("don't") == "don't"
    assert d.cache_key("co-founder") == "co-founder"
    assert d.cache_key("  Version  ") == "version"
    try:
        d.cache_key("///")
    except ValueError:
        pass
    else:
        raise AssertionError("a word with no usable characters must be rejected")
    print("no escaping the cache dir   ok")


def test_corrupt_index_is_kept_not_overwritten():
    """A half-written file used to read as empty, and the next save replaced
    every cached word with one entry. Silent, total cache loss."""
    from mr_tharoor import config

    real = config.INDEX_FILE.read_bytes() if config.INDEX_FILE.exists() else None
    try:
        config.INDEX_FILE.write_text('{"version": {truncated')
        assert d._index() == {}
        kept = list(config.CACHE_DIR.glob("index.json.corrupt-*"))
        assert kept, "the corrupt bytes must be kept, not discarded"
        assert b"truncated" in kept[0].read_bytes()
        for f in kept:
            f.unlink()
    finally:
        if real is None:
            config.INDEX_FILE.unlink(missing_ok=True)
        else:
            config.INDEX_FILE.write_bytes(real)
    print("corrupt index quarantined   ok")


def test_accent_preference():
    """US first, then UK. Order comes from config, not from dict ordering."""
    titles = ["File:en-au-data.ogg", "File:en-uk-data.ogg", "File:en-us-data.ogg"]
    assert d._pick_audio(titles, "data") == "File:en-us-data.ogg"
    assert d._pick_audio(titles[:2], "data") == "File:en-uk-data.ogg"
    print("accent preference           ok")


def test_ipa_from_english_section_only():
    """Wiktionary pages cover every language that spells a word this way.
    Reading the German IPA for an English word would be worse than no IPA."""
    wikitext = (
        "==German==\n{{IPA|de|/faˈziːt/}}\n"
        "==English==\n===Pronunciation===\n{{IPA|en|/ˈvɜːʒn̩/|/ˈvɝʒən/}}\n"
        "==Spanish==\n{{IPA|es|/beɾˈsjon/}}\n"
    )
    assert d._extract_ipa(wikitext) == "/ˈvɜːʒn̩/"
    assert d._extract_ipa("==English==\nno transcription here") is None
    print("ipa extraction              ok")


def test_transient_errors_are_not_cached():
    """A rate limit must never be written down as 'this word has no sound'.
    That poisons the cache permanently and silently."""
    calls = {"n": 0}

    def boom(params):
        calls["n"] += 1
        raise net.TransientError("HTTP 429 for test")

    original = d._get
    d._get = boom
    try:
        entry = d.lookup("a-word-that-will-429", refresh=True)
        assert entry.source == "error", entry
        assert "a-word-that-will-429" not in d._index(), "error got cached"
        d.lookup("a-word-that-will-429", refresh=False)
        assert calls["n"] == 2, "second lookup served a cached failure"
    finally:
        d._get = original
    print("transient errors uncached   ok")


def test_cache_is_fast_and_offline():
    """First lookup hits the network; every later one must not."""
    try:
        entry = d.lookup("version")
    except Exception as exc:  # pragma: no cover - offline machine
        print(f"network test skipped        ({type(exc).__name__})")
        return
    if entry.source == "error":
        print("network test skipped        (lookup failed)")
        return

    assert entry.is_human, f"expected a human recording for 'version', got {entry}"
    assert entry.ipa and entry.ipa.startswith("/"), entry.ipa
    assert Path(entry.audio_path).exists(), entry.audio_path
    assert Path(entry.audio_path).stat().st_size > 1000, "audio file is suspiciously small"

    start = time.perf_counter()
    again = d.lookup("version")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05, f"cached lookup took {elapsed * 1000:.0f}ms, cache is not working"
    assert again.audio_path == entry.audio_path
    print(f"cached lookup               ok  ({elapsed * 1000:.1f}ms, {entry.accent})")


def test_renaming_the_checkout_does_not_orphan_the_audio():
    """The index stores absolute paths; renaming the folder broke 94 of 95.

    Each orphan would have been silently re-downloaded, one a second, inside
    a 90 second nightly budget -- so the report would have gone days without
    the human recording that is the entire point of it.
    """
    from dataclasses import replace

    real = d.Pronunciation(
        word="version", ipa="/x/", audio_path=str(d.config.AUDIO_DIR / "version.mp3"),
        accent="en-us", source="wiktionary",
    )
    d.config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    made = not Path(real.audio_path).exists()
    if made:
        Path(real.audio_path).write_bytes(b"not really audio")
    try:
        stale = replace(real, audio_path="/Users/someone/mr-roy/cache/audio/version.mp3")
        assert d._relocate(stale).audio_path == real.audio_path, "orphan not recovered"
        # A file that genuinely is not there must stay missing, not be invented.
        gone = replace(real, audio_path="/Users/someone/mr-roy/cache/audio/nosuch.mp3")
        assert d._relocate(gone).audio_path == gone.audio_path, "invented a file"
    finally:
        if made:
            Path(real.audio_path).unlink(missing_ok=True)
    print("moved checkout keeps audio  ok")


def main() -> int:
    test_commons_url_capitalisation()
    test_pick_audio_requires_the_word()
    test_never_plays_a_different_word()
    test_words_cannot_escape_the_cache_directory()
    test_corrupt_index_is_kept_not_overwritten()
    test_accent_preference()
    test_ipa_from_english_section_only()
    test_transient_errors_are_not_cached()
    test_cache_is_fast_and_offline()
    test_renaming_the_checkout_does_not_orphan_the_audio()
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
