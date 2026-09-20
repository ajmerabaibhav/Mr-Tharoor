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
          reminders · dictionary · evidence model · selftest · 4 test suites
measured  false-alarm floor 1 in 127 chances on known-correct speech (0.8%,
          at most 3.0%); consonants 0 in 113
unproven  recall, and precision on your own connected speech. Needs `roy check`
missing   speaker filter · Windows
```

## The one thing that should happen next

**`roy check`.** Twenty minutes of judging findings. `roy selftest` now bounds
the false alarms from above — the detector does not flag correct speech — but
a floor measured on single words read in a quiet room says nothing about
recall, and nothing about connected speech, where sounds legitimately reduce
and drop. Every threshold in `evidence.py` and every filter in `grammar.py`
stays a judgement call until real findings are labelled. The 24 dictations you
hand-corrected in Wispr are a free labelled set for the phrasing side; the
pronunciation side has nothing yet.

**Second: sit closer.** Measured, the own microphone gets 3.1 dB on an
ordinary day against 24.0 dB through Wispr. No code fixes that.

## Known defects

| # | What | Severity | Where |
|---|------|----------|-------|
| 1 | **No speaker filter.** In a meeting the microphone hears everyone, and a colleague's pronunciation scores as yours. Also the consent story. ~150 lines with voice enrolment. | High | `listener.py` |
| 2 | **Grammar "correct" side is an LLM's opinion.** Wispr's cleaned text is a model's rewrite, not ground truth, except where you edited it by hand. A style preference can read as a correction. The filter is strict, but not perfect. | Medium | `grammar.py` |
| 3 | **Reading-aloud detection is energy plus zero-crossing.** A radio in the next room can pass it. The SNR gate and the nightly analysis catch most of that downstream, at the cost of a wasted 30s recording. | Medium | `listener.py` |
| 4 | **Wispr schema dependency.** Another company's private database. The reader checks the schema and fails loudly, but a Wispr release can still break the primary source overnight. Fallback is the listener. | Medium | `wispr.py` |
| 5 | **Whisper cannot recover badly-said words** on our own recordings (not Wispr's). *version* became *mission*. Two recovery routes have now been tried and measured empty — see below. Only Wispr's text, or `roy check`, tells those apart. | Medium | `listen.py` |
| 8 | **The own-microphone path barely earns its keep.** 3.1 dB median on a real day against 24.0 dB through Wispr; 82% of a day's chunks are now dropped at capture for being under the analyser's floor. It still covers meetings and reading aloud, which Wispr never hears, but it is a weak second source and the report should probably say which source a finding came from. | Medium | `listener.py` |
| 6 | **Voice path still ducks other audio on calls.** Apple's echo cancellation has no true off switch, only a minimum level. Acceptable on a call (the call app ducks anyway); the design now keeps the voice path out of every other situation. | Low | `capture.py` |
| 7 | **Windows.** ~49% of the code is portable. The missing half is CoreAudio process enumeration and voice processing, with no clean equivalent. Not until the Mac version is validated. | Low | – |

### Tried, measured, dead

Written down so nobody spends another evening on them.

- **Recovering the intended word from the sounds produced.** Collapse every
  confusable sound into one symbol, index CMUdict by the collapsed key, look
  up what was actually said. 82% of keys map to exactly one word, so the idea
  is sound. It recovered **0 of 57** substituted words on the probe: at 12 dB
  the phoneme stream is not merely confused but truncated and garbled (*vet*
  came out `wɛ`, *grew* came out `nkdeɪ`). Worth revisiting only if the
  own-microphone audio ever reaches Wispr's quality. `2026-09-20`
- **Mining Wispr's heard-vs-meant pairs for mispronunciations.** Wispr stores
  its raw recogniser output beside the cleaned text, so a word a
  mispronunciation turned into a different real word should show up there.
  Across **201 dictations: zero** tracked-contrast pairs. What the pair
  actually contains is the cleaning model's grammar edits, which is what
  `grammar.py` already reads it for. `2026-09-20`

### Fixed

- Findings weighted on one axis when there are two: a recording can have a
  clean signal and still be one the phoneme model never followed. Measured,
  those produce findings 6x faster per chance (15.5% against 2.4%) at better
  SNR, and they entered the tally at full weight. `listen.agreement_weight`
  now discounts them. `2026-09-20`
- Collecting audio the analyser was always going to refuse: 82% of one day's
  own-microphone chunks sat under the SNR floor, costing disk, a decode at
  23:30 and a deletion. Dropped at capture now, same threshold, and counted
  so `roy logs` and the morning notification can say the microphone is too
  far while you can still move it. `2026-09-20`
- Renaming the checkout orphaned 94 of 95 cached pronunciations: the index
  stores absolute paths, and each orphan would have been re-downloaded one a
  second inside a 90 second budget. Audio is now found by name in the audio
  folder before anything is fetched. `2026-09-20`
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
