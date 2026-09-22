"""The two new sources: a checked LLM reply, and the day's typing."""

import json
from datetime import date, datetime, timezone

from mr_tharoor import grammar, typed

ITEMS = [("a", "the result which you have gave is not new"),
         ("b", "can you check the people that is building it")]


def _reply(*rows):
    return "```json\n" + "\n".join(json.dumps(r) for r in rows) + "\n```"


def test_parse_keeps_real_corrections():
    out = grammar.parse_llm(_reply(
        {"i": 1, "said": "you have gave", "should_be": "you have given",
         "kind": "verb", "why": "past participle after have"},
    ), ITEMS)
    assert len(out) == 1
    f = out[0]
    assert (f.said, f.should_be, f.kind, f.basis, f.mode) == (
        "you have gave", "you have given", "verb", "llm", "spoken")
    assert f.instruction == 'use "given"'
    assert f.rule == "past participle after have"  # the checker's reason, not the generic one


def test_parse_drops_what_was_never_said():
    """A correction whose span is not in the transcript is an invention."""
    out = grammar.parse_llm(_reply(
        {"i": 1, "said": "I are going home", "should_be": "I am going home", "kind": "verb"},
        {"i": 9, "said": "you have gave", "should_be": "you have given", "kind": "verb"},
        {"i": 2, "said": "the people that is", "should_be": "the people that is", "kind": "verb"},
    ), ITEMS)
    assert out == []


def test_parse_dedupes_and_survives_junk():
    row = {"i": 2, "said": "people that is building", "should_be": "people that are building",
           "kind": "verb", "why": "plural subject"}
    out = grammar.parse_llm("Here you go:\n" + _reply(row, row) + "\nnot json at all", ITEMS)
    assert len(out) == 1 and out[0].source == "b"


def test_typed_reads_only_what_a_person_typed(tmp_path, monkeypatch):
    monkeypatch.setattr(typed, "PROJECTS", tmp_path)
    folder = tmp_path / "-Users-someone-work"
    folder.mkdir()
    when = datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc)

    def row(text, **extra):
        return json.dumps({"type": "user", "timestamp": when.isoformat().replace("+00:00", "Z"),
                           "message": {"role": "user", "content": text}, **extra})

    (folder / "session.jsonl").write_text("\n".join([
        row("can you check whether the build is working or not"),
        row("/clear"),                                    # a command, not prose
        row("<system-reminder>be good</system-reminder>"),  # never typed
        row("look at this <pasted_content id=1>x y z q</pasted_content>"),  # too short once stripped
        row("[Request interrupted by user for tool use]"),  # written by the tool
        row("yes"),                                        # too short
        row("i said this one out loud into the microphone"),  # dictated, not typed
        json.dumps({"type": "assistant", "timestamp": when.isoformat(),
                    "message": {"content": "reply from the model here"}}),
        "{ broken json",
    ]) + "\n")
    # A transcript belonging to this project is our own grammar call coming back.
    ours = tmp_path / "-Users-someone-mr-tharoor-data-llm"
    ours.mkdir()
    (ours / "s.jsonl").write_text(row("this prompt was written by the checker itself") + "\n")

    out = typed.for_day(date(2026, 9, 20),
                        exclude=["I said this one out loud into the microphone."])
    assert [text for _, text in out] == ["can you check whether the build is working or not"]


def test_llm_is_optional(monkeypatch):
    monkeypatch.setattr(grammar, "llm_binary", lambda: "/bin/echo")
    monkeypatch.delenv("MR_THAROOR_NO_LLM", raising=False)
    assert grammar.llm_available()
    monkeypatch.setenv("MR_THAROOR_NO_LLM", "1")
    assert not grammar.llm_available()
    assert grammar.llm_check(ITEMS) == []  # and nothing is spawned


def test_label_is_one_word_and_verified():
    out = grammar.parse_llm(_reply(
        {"i": 1, "said": "you have gave", "should_be": "you have given", "kind": "verb",
         "label": "Participle form", "why": "past participle after have"},
    ), ITEMS)
    assert out[0].label == "participle"  # one word, lowercased


def test_said_as_letters_not_ipa():
    """A printed page cannot play a sound, so it must show the word misspelt."""
    from mr_tharoor import report

    assert report._as_heard("version", "v->w") == "wersion"
    assert report._as_heard("that", "th->t") == "tat"
    assert report._as_heard("word", "t->retroflex") is None  # letters cannot show it
    assert report._as_heard("cat", "v->w") is None  # no v to swap


def test_week_refuses_to_invent_progress(tmp_path, monkeypatch):
    """Days the old checker looked at must never be compared with the new one."""
    import json as _json
    from datetime import date, timedelta

    from mr_tharoor import config, progress

    today = date(2026, 9, 22)
    for back, engine, found in ((1, "claude-cli", 6), (9, "local-rules", 0)):
        day = today - timedelta(days=back)
        (config.REPORTS_DIR / f"{day}-analysis.json").write_text(
            _json.dumps({"grammar_engine": engine, "version": 2}))
        (config.REPORTS_DIR / f"{day}-grammar-raw.json").write_text(
            _json.dumps([{"label": "agreement"}] * found))
    monkeypatch.setattr(progress, "_word_counts", lambda days: {d: 500 for d in days})

    summary = progress.week(today)
    assert summary["this_week"]["found"] == 6
    assert summary["last_week"]["days"] == 0  # the local-rules day is not comparable
    assert "Next week can be compared" in summary["verdict"]
    assert summary["change"] is None
