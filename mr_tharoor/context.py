"""Should Mr Tharoor be listening right now?

The microphone gate answers "is someone on a call". That covers meetings and
dictation and costs nothing, because the operating system already knows. It
misses the case that matters most to you: sitting at the desk reading a page
out loud, with no app holding the microphone at all.

Catching that needs something to notice you started talking, and noticing
means sampling audio, which costs battery. So the job here is to sample as
rarely as possible while still being there when you read.

Three signals, cheapest first, and the order is the whole design:

  1. IS ANOTHER APP ON THE MIC?   Free. The OS knows. A call, a huddle,
     dictation. Stay out of it -- see decide() for why this used to be the
     opposite.

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

# Dictation apps. Two ways one of these shows up on the microphone: it holds
# the device itself (Wispr Flow does, as com.electron.wispr-flow.helper -- see
# dictation_app below), or CoreSpeech holds it while the app is running, which
# means that app dictating rather than a Siri wake-word check. Either way it is
# the cleanest speech this tool ever gets -- one speaker, close to the mic,
# talking deliberately -- and Wispr has already stored it, so we skip.
DICTATION_APPS = frozenset(
    {
        "com.electron.wispr-flow",
        "com.superwhisper",
        "com.openai.chat",
        "app.flowvoice",
        "com.aqua.voice",
        "com.goodsnooze.macwhisper",
    }
)

LISTEN_NEVER = "never"  # nothing to hear, stay asleep
LISTEN_ALWAYS = "always"  # record without asking. Nothing returns this now:
# every conversation has someone else in it and there is no speaker filter.
# The listener still honours it, so a speaker filter is the only thing
# standing between here and meetings working again.
LISTEN_SAMPLE = "sample"  # might be reading aloud, peek occasionally
LISTEN_SKIP = "skip"  # someone else is already recording this for us


@dataclass
class Decision:
    mode: str
    reason: str
    frontmost: str | None = None

    @property
    def listening(self) -> bool:
        return self.mode in (LISTEN_ALWAYS, LISTEN_SAMPLE)


def running_apps() -> set[str]:
    """Bundle ids of everything with a UI. About a third of a millisecond."""
    try:
        from AppKit import NSWorkspace

        return {
            app.bundleIdentifier()
            for app in NSWorkspace.sharedWorkspace().runningApplications()
            if app.bundleIdentifier()
        }
    except Exception:
        return set()


def dictation_app(bundle: str) -> str | None:
    """Which dictation app a microphone holder belongs to, if any.

    MEASURED: the claim below that these apps never hold the microphone under
    their own name is wrong. Wispr Flow captures through CoreSpeech sometimes
    and through its own Electron audio service the rest of the time, and that
    service holds the device as com.electron.wispr-flow.helper. An exact-match
    test saw an unknown app on the mic, took the ALWAYS branch, and recorded 30
    seconds of the dictation Wispr had already stored -- through the voice path,
    which ducks every other sound the Mac is making. Match a helper to its
    parent so the SKIP branch gets its chance.
    """
    for app in DICTATION_APPS:
        if bundle == app or bundle.startswith(app + "."):
            return app
    return None


def dictating() -> str | None:
    """Is a dictation app the reason the microphone is open?

    Wispr Flow shows an orange mic while it listens, and that is exactly the
    moment worth recording. Two ways to see it: the app (or a helper of it)
    holds the device itself, or a system speech service holds it while the app
    is running. Siri alone satisfies neither.
    """
    holders = {h.bundle_id or "" for h in micgate.mic_users()}
    direct = sorted(app for h in holders if (app := dictation_app(h)))
    if direct:
        return direct[0]
    if not holders & AMBIGUOUS_HOLDERS:
        return None
    present = running_apps() & DICTATION_APPS
    return sorted(present)[0] if present else None


def frontmost() -> str | None:
    """Bundle id of the app in front. About a microsecond, no permissions."""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.bundleIdentifier() if app else None
    except Exception:
        return None


def playing_media(front: str | None = None) -> str | None:
    """Which app is making sound, if it means now is not a moment to listen.

    ANY sound counts, from any app that is not a call. Two earlier versions
    were narrower and both let a video through: the first only looked at the
    frontmost app; the second matched bundle ids, but a browser plays audio
    from a helper process with a different id (com.google.Chrome.helper,
    com.apple.WebKit.GPU), so YouTube never matched. The mic then peeked,
    heard the video's voice through the speakers, mistook it for you, and
    recorded thirty seconds of it through the voice path -- which ducks the
    very audio you were trying to hear.

    The reasoning is simple: if the Mac is making sound, you are either
    listening to it (so not reading aloud) or on a call (caught earlier by
    the microphone check). Either way, peeking is wrong. No URL is ever read.
    """
    for app in micgate.audio_output_apps():
        bundle = app.bundle_id or ""
        if bundle in CALL_APPS:
            continue
        return bundle or "an unnamed app"
    return None


def decide() -> Decision:
    """The whole policy, in the order that costs least."""
    holders = micgate.mic_users()
    if not holders and micgate.is_mic_in_use():
        # Older CoreAudio and some Bluetooth devices only expose a boolean.
        # An empty process list in that case does not mean the device is free.
        return Decision(LISTEN_NEVER, "microphone activity detected without a known owner", frontmost())
    real = [
        h
        for h in holders
        if (h.bundle_id or "") not in AMBIGUOUS_HOLDERS
        and not dictation_app(h.bundle_id or "")
    ]
    if real:
        # Another app is capturing, which almost always means a call. This
        # used to be LISTEN_ALWAYS -- open the microphone too and record 30
        # second chunks through Apple's voice path. That was three bad things
        # at once, and only the first is obvious:
        #
        #   it spoils their call    voice processing reconfigures the shared
        #                           input device and ducks other audio, and
        #                           Apple gives no true off switch, only a
        #                           minimum level. Reported from a real call.
        #   the audio is poor       our share comes back about 4.5x quieter
        #                           while another app holds the device.
        #                           Measured 3-6 dB median against 24 dB
        #                           through Wispr; most of it under the
        #                           analyser's own floor, recorded and then
        #                           deleted at 23:30.
        #   it is not your voice    a call has someone else in it, there is
        #                           no speaker filter, and their pronunciation
        #                           scored as yours.
        #
        # None of the three is fixable from this side. Dictation is covered by
        # Wispr's own database and reading aloud by the sampling path, so what
        # this gives up is meetings -- the one case with no other source. Put
        # LISTEN_ALWAYS back here when there is a speaker filter to make it
        # honest; until then it would be recording your mother.
        return Decision(
            LISTEN_NEVER,
            f"{real[0].bundle_id or 'an app'} has the microphone; staying out of it",
            frontmost(),
        )

    front = frontmost()
    if holders:
        app = dictating()
        if app:
            # The orange mic is on. Wispr Flow is recording you, storing the
            # audio and working out the words -- better than we can, and it is
            # what the nightly job reads first. Recording alongside it would
            # duplicate the data and, through the voice path, duck whatever
            # else the Mac is playing. So: do nothing, deliberately.
            return Decision(LISTEN_SKIP, f"{app} is recording this for us", front)
        return Decision(
            LISTEN_NEVER,
            f"{holders[0].bundle_id} has the microphone; waiting until it is free",
            front,
        )
    if front in READING_APPS:
        noisy = playing_media(front)
        if noisy:
            return Decision(LISTEN_NEVER, f"{noisy} is playing audio, so you are watching", front)
        return Decision(LISTEN_SAMPLE, "you might be reading aloud", front)

    return Decision(LISTEN_NEVER, f"{front or 'nothing'} is not a reading app", front)


def explain() -> str:
    decision = decide()
    return f"{decision.mode.upper():<7} {decision.reason}"
