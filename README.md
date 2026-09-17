# mr-roy

Hear how the word is actually said.

You cannot learn a sound by reading a symbol. `/ˈvɜːʒn̩/` teaches nobody
anything. A recording of a person saying **version** teaches it in one second.
So every word this tool flags comes with real human audio, pulled once from
Wiktionary and kept on disk forever.

Runs on macOS. Local by default. Nothing leaves the machine except the word
being looked up.

## Working now

```bash
pl say version three          # play the correct pronunciation out loud
pl look comfortable           # IPA, accent, and where the audio came from
pl gate                       # is the battery gate healthy on this Mac
pl cache                      # what is already offline
```

```
$ roy look measure
  measure  /ˈmɛʒ.ə/  [en-us, human]
    File:en-us-measure.ogg via Wikimedia Commons
    ~/mr-roy/cache/audio/measure.mp3
```

First lookup takes about 2 seconds. Every lookup after that is 0.1ms and needs
no network at all.

## How it works

**Audio comes from Wiktionary.** The recordings live on Wikimedia Commons under
free licences. Commons stores originals as `.ogg`, which macOS cannot play, but
Wikimedia also publishes an `.mp3` transcode of every audio file and `afplay`
handles mp3 natively. So there is no ffmpeg, no codec, no dependency.

The file URL is derived from the MD5 of the filename rather than requested from
the API, which removes a network round trip and a failure mode. Note that
MediaWiki capitalises the first letter of a filename before hashing it.

**When no human has recorded a word**, the macOS speech synth fills in. Fully
offline, and labelled `[synthetic]` everywhere so you always know whether you
are hearing a person or a robot. About 1 word in 10 lands here.

**The microphone gate is the battery story.** Holding a capture stream open all
day costs real power. Asking CoreAudio a question costs microseconds. So the
listener sleeps until another app actually takes the microphone, which is the
only time you are in a call or a meeting worth recording.

macOS 14.2+ exposes a per-process audio list, so the gate can name which app
holds the mic and skip our own stream. Older Macs fall back to a blunter
device-level check.

```
$ roy gate
{ "process_api": true, "method": "process-object list", ... }
mic in use right now: True
  us.zoom.xos (pid 4821)
```

## Known limits

- **Bluetooth microphones report nothing to CoreAudio.** A call taken on AirPods
  reads as idle and will not be recorded. Use the built-in mic or a wired
  headset. `pl gate` says so out loud.
- **A transient failure is never cached.** A rate limit or a dead network
  returns `error` and is deliberately not written to the index, so a bad
  afternoon cannot permanently convince the tool that a word has no sound.
- **IPv6.** This machine's network advertises AAAA records and drops the
  traffic. Python waits the full connect timeout on each address in turn, so
  every request stalled about 20 seconds. `net.prefer_ipv4()` sorts IPv4 first
  and takes it to 0.5s.

## Layout

```
mr_roy/
  config.py       paths and knobs, one place
  net.py          IPv4-first HTTP, throttling, Commons URL derivation
  dictionary.py   word -> IPA + human audio, cached forever
  micgate.py      is another app using the mic right now
  cli.py          the pl command
tests/
  test_dictionary.py
  test_micgate.py
cache/audio/      downloaded recordings, safe to delete, refetches on demand
```

## Tests

```bash
python3 tests/test_dictionary.py   # parsing, URL derivation, cache behaviour
python3 tests/test_micgate.py      # opens the mic from another process
```

The mic test needs microphone permission for your terminal. macOS asks once.

## Next

1. Capture. Record only while the gate is open, 16kHz mono, voice-activity
   trimmed.
2. Nightly analysis. Two passes over the day: one for the words you meant, one
   for the sounds you actually made, aligned against the dictionary.
3. The report, with a play button on every flagged word.
4. Daily delivery to WhatsApp.

Full plan: https://claude.ai/artifact/Fb2Ke36sK4xL1t6XhT4P2V
