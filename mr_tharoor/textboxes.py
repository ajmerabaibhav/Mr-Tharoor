"""What you type everywhere else: Mail, Slack, ChatGPT, Notes, a browser box.

typed.py reads the two places that already keep your typing (Claude Code and
Codex). Everything else forgets it the moment you press Send, so this reads
the text box you are typing in, through the macOS Accessibility API, while
you type -- the same way a screen reader does. It is not a keylogger: it
never sees a keystroke, only the text a box already shows on screen.

How a box becomes sentences:

    focus a box      remember what was already in it (the baseline)
    every 2 s        read it again; anything that appeared faster than a
                     person types (paste, autocomplete, Wispr) is marked
    leave the box,   diff baseline -> last text; the sentences you added
    clear it (Send),   are written to data/typed/<day>.jsonl, minus any
    or pause 60 s      sentence touching a marked paste

What it refuses to read, before the text is ever fetched:
  - anything while macOS Secure Input is on (a password field has focus
    anywhere, or a terminal's Secure Keyboard Entry)
  - secure text fields, and every box that is not a multi-line text area:
    URL bars, search boxes and login forms are single-line fields
  - the apps in config.TYPING_BLOCKED: password managers, terminals (Claude
    Code is already read from its transcript), and private messaging

What is scrubbed before it touches the disk: email addresses, links, long
numbers (cards, phones, OTPs) and key-shaped tokens.

Off until you grant Accessibility to the Python that runs `tharoor listen`.
It asks macOS once; a grant reaches only a process started after it, so
setup restarts the listener while it waits, and on its own it restarts every
RECHECK seconds until granted. Removing it there switches this off. Files go with everything else,
KEEP_DAYS later.
"""

from __future__ import annotations

import ctypes
import difflib
import json
import os
import re
import signal
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

from . import config

POLL = 2.0
PAUSE = 60.0  # this long untouched and the box is committed
BURST = 40  # chars appearing within one poll that no one typed
MAX_FIELD = 20000  # a box bigger than this is a document dump, not typing
READABLE = {"AXTextArea"}
GRANTED = config.DATA_DIR / ".accessibility-granted"  # setup waits for this
RECHECK = 600  # without Accessibility, restart this often to see a new grant

SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
SCRUB = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[email]"),
    (re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE), "[link]"),
    (re.compile(r"(?<![\w-])(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{20,}"), "[key]"),
    (re.compile(r"\+?\d[\d\s-]{4,}\d"), "[number]"),
]


def folder() -> Path:
    return config.DATA_DIR / "typed"


def scrub(text: str) -> str:
    for pattern, placeholder in SCRUB:
        text = pattern.sub(placeholder, text)
    return text


def inserted(before: str, after: str) -> str:
    """What one poll added: trim the common prefix and suffix, keep the middle."""
    start = 0
    limit = min(len(before), len(after))
    while start < limit and before[start] == after[start]:
        start += 1
    end = 0
    while end < limit - start and before[-1 - end] == after[-1 - end]:
        end += 1
    return after[start:len(after) - end]


def added_sentences(baseline: str, final: str, pasted: list[str]) -> list[str]:
    """Whole sentences of `final` that contain text not in `baseline`.

    Whole sentences, not the inserted fragments: a word fixed mid-sentence is
    grammar only in the context of the sentence around it.
    """
    spans = [(j1, j2) for op, _, _, j1, j2 in
             difflib.SequenceMatcher(None, baseline, final, autojunk=False).get_opcodes()
             if op in ("insert", "replace")]
    if not spans:
        return []
    out = []
    position = 0
    for piece in SENTENCE.split(final):
        start = final.find(piece, position)
        position = start + len(piece)
        piece = piece.strip()
        if not piece or not any(j1 < position and j2 > start for j1, j2 in spans):
            continue
        if any(p.strip() and (p.strip() in piece or piece in p) for p in pasted):
            continue
        out.append(piece)
    return out


class Box:
    """One focused text box, from focus to commit."""

    def __init__(self, key, app: str, value: str):
        self.key, self.app = key, app
        self.baseline = self.last = value
        self.pasted: list[str] = []
        self.changed = time.monotonic()

    def see(self, value: str) -> list[str]:
        """Feed the box's current text; returns sentences to commit, if any."""
        now = time.monotonic()
        if value == self.last:
            if now - self.changed > PAUSE and self.last != self.baseline:
                return self.commit(value)
            return []
        new = inserted(self.last, value)
        if len(new) > BURST:
            self.pasted.append(new)
        out = []
        if len(value) < len(self.last) // 2 and len(self.last) - len(value) > BURST:
            out = self.commit(value)  # sent or cleared: what was there is finished
        self.last, self.changed = value, now
        return out

    def commit(self, value: str) -> list[str]:
        out = added_sentences(self.baseline, self.last, self.pasted)
        self.baseline = self.last = value
        self.pasted = []
        return out


def write(app: str, sentences: list[str], day: date | None = None) -> None:
    sentences = [s for s in (scrub(s) for s in sentences) if len(s.split()) >= 4]
    if not sentences:
        return
    target = folder() / f"{(day or date.today()).isoformat()}.jsonl"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as handle:
        stamp = datetime.now().isoformat(timespec="seconds")
        for sentence in sentences:
            handle.write(json.dumps({"t": stamp, "app": app, "text": sentence}) + "\n")


def for_day(day: date) -> list[tuple[str, str]]:
    """[(app, sentence)] captured on `day`, without repeats."""
    try:
        rows = [json.loads(line) for line in
                (folder() / f"{day.isoformat()}.jsonl").read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    out, seen = [], set()
    for row in rows:
        if row["text"] not in seen:
            seen.add(row["text"])
            out.append((row["app"], row["text"]))
    return out


# ---- the macOS side -------------------------------------------------------

def _secure_input() -> bool:
    try:
        carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
        return bool(carbon.IsSecureEventInputEnabled())
    except OSError:
        return True  # cannot tell, so assume a password is being typed


def _attribute(element, name: str):
    import ApplicationServices as AS

    error, value = AS.AXUIElementCopyAttributeValue(element, name, None)
    return value if error == 0 else None


def trusted(prompt: bool = False) -> bool:
    import ApplicationServices as AS

    if prompt:
        return bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
    return bool(AS.AXIsProcessTrusted())


_skipped: set[tuple[str, str]] = set()


def _skip(bundle: str, reason: str) -> None:
    """Remember why a box was not read, once per app and reason. Never the text."""
    _skipped.add((bundle, reason))


def frontmost_app() -> tuple[int, str] | None:
    """(pid, bundle id) of the app you are using, from LaunchServices.

    Two methods that look right and are not, both measured on this Mac:
    NSWorkspace.frontmostApplication is refreshed by an event loop this
    process does not run, so it answered with whichever app was in front
    when it started -- all day. The window list puts Stage Manager's own
    windows on top, so it answered "WindowManager". lsappinfo asks
    LaunchServices, which is the authority, in ~30 ms.
    """
    import subprocess

    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True,
                             timeout=2).stdout.strip()
        info = subprocess.run(["lsappinfo", "info", "-only", "bundleid", "-only", "pid", asn],
                              capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    pid = re.search(r'"pid"=(\d+)', info)
    bundle = re.search(r'"CFBundleIdentifier"="([^"]*)"', info)
    return (int(pid.group(1)), bundle.group(1) if bundle else "") if pid else None


def focused() -> tuple[object, str, str] | None:
    """(element, app bundle id, text) of the box you are typing in, or None
    whenever reading it would be unsafe or pointless."""
    import ApplicationServices as AS

    # Asked of the front app, not the system-wide element: the system-wide
    # focus query answers -25204 to a background process even when trusted.
    front = frontmost_app()
    if front is None:
        return None
    pid, bundle = front
    if not bundle or bundle in config.TYPING_BLOCKED or _secure_input():
        return None
    root = AS.AXUIElementCreateApplication(pid)
    element = _attribute(root, "AXFocusedUIElement")
    if element is None:
        # Electron apps (Slack, Notion, Discord) build their tree only when
        # an assistive app asks for it, through this documented flag.
        AS.AXUIElementSetAttributeValue(root, "AXManualAccessibility", True)
        _skip(bundle, "no focused element")
        return None
    role, subrole = _attribute(element, "AXRole"), _attribute(element, "AXSubrole")
    if role not in READABLE or "AXSecureTextField" in (role, subrole):
        _skip(bundle, f"role {role}/{subrole}")
        return None
    value = _attribute(element, "AXValue")
    if not isinstance(value, str) or len(value) > MAX_FIELD:
        _skip(bundle, f"value {type(value).__name__} {len(value) if isinstance(value, str) else ''}")
        return None
    return element, bundle, str(value)


def watch(stop: threading.Event, logger) -> None:
    """The loop `tharoor listen` runs on a side thread. Never raises."""
    import CoreFoundation as CF

    asked = config.DATA_DIR / ".asked-accessibility"
    try:
        if not trusted(prompt=not asked.exists()):
            asked.touch()
            GRANTED.unlink(missing_ok=True)
            logger.info("typing capture off until Accessibility is granted to Mr Tharoor "
                        f"(or {os.path.realpath(sys.executable)} without the app); waiting for it")
            # AXIsProcessTrusted never turns true inside a process started
            # before the grant (measured 10 Oct: granted, polled, stayed off;
            # a restart saw it at once). So re-check by restarting: setup
            # kickstarts us while it waits; on our own, every 10 minutes.
            if not stop.wait(RECHECK):
                os.kill(os.getpid(), signal.SIGTERM)
            return
        GRANTED.parent.mkdir(parents=True, exist_ok=True)
        GRANTED.touch()
        logger.info("typing capture on (Accessibility granted)")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"typing capture unavailable: {type(exc).__name__}: {exc}")
        return

    box: Box | None = None
    logged: set = set()
    while not stop.wait(POLL):
        try:
            now = focused()
            for bundle, reason in _skipped - logged:
                logger.info(f"typing capture skipped {bundle}: {reason}")
            logged |= _skipped
            if box and (now is None or not CF.CFEqual(now[0], box.key)):
                write(box.app, box.commit(""))
                box = None
            if now:
                element, bundle, value = now
                if box is None:
                    box = Box(element, bundle, value)
                else:
                    write(bundle, box.see(value))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"typing capture: {type(exc).__name__}: {exc}")
            box = None
    if box:
        write(box.app, box.commit(""))


def start(logger) -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=watch, args=(stop, logger), name="textboxes", daemon=True).start()
    return stop
