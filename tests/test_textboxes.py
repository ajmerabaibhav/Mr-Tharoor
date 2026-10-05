"""Typing captured from other apps' text boxes: what is kept, what never is."""

import os
from datetime import date, timedelta

from mr_tharoor import config, streaks, textboxes, typed


def type_into(box, text, start=""):
    """Feed a box one short burst at a time, the way fingers fill it."""
    value = start
    out = []
    for i in range(0, len(text), 8):
        value += text[i:i + 8]
        out += box.see(value)
    return value, out


def test_only_new_sentences_leave_a_box():
    quoted = "Hi team. The meeting is moved to Friday."
    box = textboxes.Box("k", "com.apple.mail", quoted)
    value, out = type_into(box, "\n\nI have went through the document yesterday.", quoted)
    assert out == []
    assert box.commit("") == ["I have went through the document yesterday."]


def test_paste_and_dictation_are_not_your_typing():
    box = textboxes.Box("k", "app", "")
    value, _ = type_into(box, "I am having a doubt about this. ")
    pasted = "Someone else wrote this long paragraph that was pasted in one go."
    box.see(value + pasted)
    assert box.commit("") == ["I am having a doubt about this."]


def test_send_clears_the_box_and_commits_it():
    box = textboxes.Box("k", "app", "")
    value, _ = type_into(box, "can you check that whether it is working or not")
    assert box.see("") == ["can you check that whether it is working or not"]
    assert box.commit("") == []  # nothing counted twice


def test_scrubbed_before_disk_and_private_file():
    textboxes.write("app", ["mail me at a.b@example.com or call +91 98765 43210 today",
                            "token sk2abcdefghij1234567890xyz is here now",
                            "too short"])
    target = textboxes.folder() / f"{date.today()}.jsonl"
    text = target.read_text()
    assert "example.com" not in text and "98765" not in text and "sk2abc" not in text
    assert "[email]" in text and "[number]" in text and "[key]" in text
    assert "too short" not in text
    assert oct(os.stat(target).st_mode & 0o777) == "0o600"


def test_reaches_the_nightly_typed_source_and_is_forgotten():
    today = date.today()
    textboxes.write("com.apple.mail", ["I have went through the document yesterday."], today)
    assert ("com.apple.mail", "I have went through the document yesterday.") in textboxes.for_day(today)
    assert any(t == "I have went through the document yesterday." for _, t in typed.for_day(today))
    streaks.purge_expired(today + timedelta(days=config.KEEP_DAYS))
    assert textboxes.for_day(today) == []


def test_password_managers_terminals_and_chats_are_blocked():
    for bundle in ("com.1password.1password", "com.apple.Terminal", "net.whatsapp.WhatsApp"):
        assert bundle in config.TYPING_BLOCKED
