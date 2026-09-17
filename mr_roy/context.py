"""Should Mr Roy be listening right now?

The microphone gate answers "is someone on a call". That covers meetings and
dictation and costs nothing, because the operating system already knows. It
misses the case that matters most to you: sitting at the desk reading a page
out loud, with no app holding the microphone at all.

Catching that needs something to notice you started talking, and noticing
means sampling audio, which costs battery. So the job here is to sample as
rarely as possible while still being there when you read.

Three signals, cheapest first, and the order is the whole design:

  1. IS ANOTHER APP ON THE MIC?   Free. The OS knows. A call, a huddle,
     dictation. Listen, no questions.

  2. WHAT IS IN FRONT?            One microsecond. If you are looking at
     Claude, ChatGPT, a PDF or your notes, reading aloud is plausible, so it
     is worth spending a little battery to check. If you are in Excel, it
     is not.

  3. IS ANYTHING PLAYING?         Free, same CoreAudio call as the gate.
     This is the trick that makes YouTube solvable without ever reading a
     URL: a browser that is making sound is showing you a video, and a
     browser that is silent is showing you text. Same app, opposite answer,
     and we never learn which page you are on.

Only when 2 says maybe and 3 says silent does the microphone open at all,
and even then in short peeks rather than continuously. Everything else costs
nothing.

Deliberately NOT done: reading browser tab URLs. AppleScript can do it, and
it would let us say "youtube.com means no". It also means a tool that can
see every page you visit, for a signal the sound check already gives us. The
cheaper answer is also the more private one.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import micgate

# In front of these, reading aloud is plausible.
READING_APPS = frozenset(
    {
        "com.anthropic.claudefordesktop",
        "com.openai.chat",
        "com.openai.codex",
        "com.electron.wispr-flow",
        "com.apple.Safari",
        "com.google.Chrome",
        "com.microsoft.edgemac",
        "com.brave.Browser",
        "company.thebrowser.Browser",
        "com.apple.Notes",
        "com.apple.Preview",
        "com.apple.iBooksX",
        "md.obsidian",
        "notion.id",
        "com.apple.TextEdit",
        "com.microsoft.Word",
        "com.apple.dt.Xcode",
        "com.apple.Terminal",
        "com.googlecode.iterm2",
    }
)

# In front of these, you are talking to someone. Listen without sampling.
CALL_APPS = frozenset(
    {
        "us.zoom.xos",
        "com.microsoft.teams",
        "com.microsoft.teams2",
        "com.tinyspeck.slackmacgap",
        "com.apple.FaceTime",
        "net.whatsapp.WhatsApp",
        "com.hnc.Discord",
        "com.cisco.webexmeetingsapp",
    }
)

# Making sound here means entertainment, never a conversation.
MEDIA_APPS = frozenset(
    {
        "com.spotify.client",
        "com.apple.Music",
        "com.apple.TV",
        "tv.plex.desktop",
        "com.netflix.Netflix",
        "com.colliderli.iina",
        "org.videolan.vlc",
        "com.apple.QuickTimePlayerX",
    }
)

# Holding the microphone without it necessarily meaning a conversation.
#
# com.apple.CoreSpeech is Apple's speech service. Wispr Flow, Siri and system
# dictation all capture through it, so none of them ever appears here under
# its own name -- you see CoreSpeech or you see nothing.
#
# MEASURED: it does NOT hold the microphone permanently. It appears while
# something is actively listening and releases afterwards. (An earlier note
# here claimed otherwise, from seeing the same long-lived pid twice hours
# apart; the daemon is long-lived, its grip on the microphone is not.)
#
# It still downgrades to SAMPLE rather than ALWAYS, for a different and
# smaller reason: we cannot tell dictation from a Siri prompt or a wake-word
# check, and recording a 30 second chunk because someone said "Hey Siri"
# wastes battery on silence. Peeking first costs one half-second and lets
# voice activity settle it.
AMBIGUOUS_HOLDERS = frozenset(
    {
        "com.apple.CoreSpeech",
        "com.apple.Siri",
        "com.apple.assistantd",
        "com.apple.SpeechRecognitionCore",
    }
)

LISTEN_NEVER = "never"  # nothing to hear, stay asleep
LISTEN_ALWAYS = "always"  # a conversation is happening, record it
LISTEN_SAMPLE = "sample"  # might be reading aloud, peek occasionally


@dataclass
class Decision:
    mode: str
    reason: str
    frontmost: str | None = None

    @property
    def listening(self) -> bool:
        return self.mode != LISTEN_NEVER


def frontmost() -> str | None:
    """Bundle id of the app in front. About a microsecond, no permissions."""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.bundleIdentifier() if app else None
    except Exception:
        return None


def playing_media(front: str | None = None) -> str | None:
    """Which app is making sound, if it is the sort that means 'watching'.

    A browser producing audio is a video, so the frontmost app counts as
    media when it is the one making the noise. No URL is ever read.
    """
    for app in micgate.audio_output_apps():
        bundle = app.bundle_id or ""
        if bundle in MEDIA_APPS:
            return bundle
        if front and bundle == front and bundle not in CALL_APPS:
            return bundle
    return None


def decide() -> Decision:
    """The whole policy, in the order that costs least."""
    holders = micgate.mic_users()
    real = [h for h in holders if (h.bundle_id or "") not in AMBIGUOUS_HOLDERS]
    if real:
        return Decision(
            LISTEN_ALWAYS,
            f"{real[0].bundle_id or 'an app'} is using the microphone",
            frontmost(),
        )

    front = frontmost()
    if holders:
        # Only a system speech service has it. That means dictation might be
        # happening, or nothing at all. Peek rather than assume.
        return Decision(
            LISTEN_SAMPLE,
            f"{holders[0].bundle_id} has the mic, which may just be standby",
            front,
        )
    if front in CALL_APPS:
        return Decision(LISTEN_ALWAYS, "a call app is in front", front)

    if front in READING_APPS:
        noisy = playing_media(front)
        if noisy:
            return Decision(LISTEN_NEVER, f"{noisy} is playing audio, so you are watching", front)
        return Decision(LISTEN_SAMPLE, "you might be reading aloud", front)

    return Decision(LISTEN_NEVER, f"{front or 'nothing'} is not a reading app", front)


def explain() -> str:
    decision = decide()
    return f"{decision.mode.upper():<7} {decision.reason}"
