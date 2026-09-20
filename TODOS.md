# What is not built, and what is known broken

Everything deferred is written down here. A vague intention is a lie.

## The honest state

Mr Tharoor runs. Three launchd agents: a context-aware listener at login, analysis
at 23:30, the report and greeting at 08:30. For dictation it reads Wispr Flow's
own database (audio already paired with the words you meant); its own
microphone covers meetings, calls and reading aloud. The report has a
pronunciation section with your voice next to a human recording, and a
phrasing section with the corrections you keep needing.

```
built     wispr reader · grammar · listener · nightly · morning · report
          reminders · dictionary · evidence model · 4 test suites
unproven  accuracy of the findings (nobody has labelled any yet)
missing   speaker filter · Windows
```

## The one thing that should happen next

**`roy check`.** Twenty minutes of judging findings. Every threshold in
`evidence.py` and every filter in `grammar.py` is a judgement call until this
is done. The 24 dictations you hand-corrected in Wispr are a free labelled set
for the phrasing side; the pronunciation side has nothing yet.

## Known defects

| # | What | Severity | Where |
|---|------|----------|-------|
| 1 | **No speaker filter.** In a meeting the microphone hears everyone, and a colleague's pronunciation scores as yours. Also the consent story. ~150 lines with voice enrolment. | High | `listener.py` |
| 2 | **Grammar "correct" side is an LLM's opinion.** Wispr's cleaned text is a model's rewrite, not ground truth, except where you edited it by hand. A style preference can read as a correction. The filter is strict, but not perfect. | Medium | `grammar.py` |
| 3 | **Reading-aloud detection is energy plus zero-crossing.** A radio in the next room can pass it. The SNR gate and the nightly analysis catch most of that downstream, at the cost of a wasted 30s recording. | Medium | `listener.py` |
| 4 | **Wispr schema dependency.** Another company's private database. The reader checks the schema and fails loudly, but a Wispr release can still break the primary source overnight. Fallback is the listener. | Medium | `wispr.py` |
| 5 | **Whisper cannot recover badly-said words** on our own recordings (not Wispr's). *version* became *mission*. Only Wispr's text, or `roy check`, tells those apart. | Medium | `listen.py` |
| 6 | **Voice path still ducks other audio on calls.** Apple's echo cancellation has no true off switch, only a minimum level. Acceptable on a call (the call app ducks anyway); the design now keeps the voice path out of every other situation. | Low | `capture.py` |
| 7 | **Windows.** ~49% of the code is portable. The missing half is CoreAudio process enumeration and voice processing, with no clean equivalent. Not until the Mac version is validated. | Low | – |

### Fixed

- Recording over every Wispr dictation: Wispr Flow does not only capture
  through CoreSpeech. Its Electron audio service holds the device as
  `com.electron.wispr-flow.helper`, which matched nothing, read as a stranger
  on the mic, and took the ALWAYS branch -- 30 seconds through the voice path,
  duplicating audio Wispr had already stored, holding the mic ~30s past the
  end of each dictation and ducking everything else the Mac was playing.
  Holders are now matched to their parent app. `2026-09-20`
- Video audio going quiet: the listener peeked, heard the video through the
  speakers, and recorded via the voice path. Any non-call sound now blocks
  peeking; reading-aloud capture is raw; dictation is skipped because Wispr
  already has it. `2026-09-19`
- Nightly job never finishing: pure-Python O(n·m) aligner on 500-word
  dictations (now numpy, 0.07s), a network fetch per new word inside the
  loop (now budgeted, 90s), and a Python for-loop filter per finding (now
  scipy, 4.6ms). `2026-09-18/19`
- Listener could not come back from a clean shutdown (`KeepAlive` semantics).
- Retention cleanup unreachable on battery; disk ceiling added.
- Scratch WAV leaking into the session folder; empty-audio `KeyError`.
- SNR gate rejecting every real recording; quality is now a weight.
- Homographs: every valid pronunciation is kept; you are wrong only if you
  match none.
- Playing a different word than asked for; rate limits cached as "no
  pronunciation"; IPv6 stall; Commons URL capitalisation; corrupt-JSON
  cache wipe; path traversal via word; test that SIGTERMed any mic holder.

## Deliberately not doing

- Live in-ear correction during calls.
- Reading browser tab URLs to detect YouTube. The sound check answers the
  same question without a tool that can see every page you visit.
- Publishing the daily report to a shared URL. The report is a local file;
  the claude.ai artifacts are snapshots published by hand.
