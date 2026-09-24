# What is not built, and what is known broken

## Three simulations against future data — 23 September 2026

Three isolated runs (own `MR_THAROOR_HOME`, the real data untouched) played
invented future days against the tool and checked what it said.

**What held.** The transcript-matching guard in `parse_llm` survived every
attack: spans not in the text, out-of-range and non-integer indices,
`said == should_be`, duplicates, fenced and prose-wrapped replies. Zero
findings of the only kind that really matters — a mistake shown to the user
that he never made. HTML escaping held everywhere transcript or model text
reaches the page. On 16 planted errors mixed with correct and mis-transcribed
sentences: **10/10 recall, 0 false alarms, 0 mis-transcriptions marked**, on
both Haiku and Sonnet, twice each. The weekly arithmetic refused every trap:
same rate from a bigger week is not improvement, a week of the old engine is
not zero corrections, and a fourfold rate gap on 50 words is still noise.

**Fixed as a result.**

| What | Where |
|---|---|
| A "nothing was proved" verdict still carried a percentage in the returned dict — a landmine for any caller that prints it | `progress.py` |
| `_analysed_days` trusted the engine name without checking the schema version | `progress.py` |
| The week footer claimed corrections under a verdict saying there was no material | `report.py` |
| One malformed grammar row raised through `build_html` and cost the whole night: no HTML, therefore no PDF | `report.py` |
| An unknown `mode` was counted in the total but rendered nowhere: 3 corrections, "1 said, 1 typed", 2 cards | `report.py` |
| The typed/spoken dedupe compared punctuated against unpunctuated text, so the same sentence dictated and typed counted twice | `typed.py` |
| A reply with two objects on one line, or wrapped in an array, parsed to nothing **and logged nothing** | `grammar.py` |
| `said`/`should_be` had no length cap, unlike `context` | `report.py` |
| One unescaped interpolation (not reachable, but inconsistent) | `report.py` |
| A mic test asked the live machine who owned the microphone and failed whenever the listener held it | `tests/test_micgate.py` |

**Open, and honest about it.**

- **Recall is not perfectly stable.** On a 25-item run one agent saw 13/15 and
  then 15/15 on identical input, missing "four email thread" once. My own
  16-item runs were 10/10 four times. The difference between the two is batch
  size, which is the next thing to settle.
- **`article` labels two different moves** — add "a", and drop "the" before a
  proper noun. One word for two actions weakens the point of the word.
- A day's typing is lost entirely if a message exceeds `MAX_CHARS` with an
  untagged paste in it. The typed words inside it go with it.


## Teaching, not reporting — 22 September 2026

- `label`: the checker returns one lowercase word naming the rule, verified the
  same way as everything else it returns, shown as the badge on each correction.
- `report._as_heard`: the flagged word respelled with the sound that came out,
  so the PDF can say WERSION against VERSION. Returns None for contrasts letters
  cannot show (both retroflex pairs), and the card falls back to IPA there.
- `progress.py`: corrections per thousand words, this week against last.
  Guards: engine-matched days only, rate not count, and a crude 2-sigma test
  that reports anything smaller as no difference. Word counts are computed from
  the sources on demand, so no new state is stored and past weeks work.
- Inline SVG portrait in the masthead.

Ceilings: with a few thousand words a week the noise band is wide, so early
weeks will honestly say nothing has been proved. The respelling is an
approximation of the produced sound, not a transcription — the recording
remains the ground truth, and the report says so.


## Report redesign and one name — 22 September 2026

- The report template is a light, serif lesson sheet, print first. Numbered
  corrections, struck-through original, the rule under each one, context
  quoted around the mistake rather than the first 150 characters of the
  utterance. `@page` margins set; cards and items do not break across pages.
- The lesson section is placed above pronunciation, and the greeting names the
  count. Both halves are capped separately so speech cannot crowd out typing.
- `tharoor` is the only command.


## Grammar rewritten to actually find things — 22 September 2026

Implemented:

- The seven local regexes found **zero** corrections across a month of real
  dictation. Every `*-grammar.json` on disk is `[]`. Grammar now goes through
  the Claude Code CLI already installed here, batched, once or twice a night.
  On 20 September: **20 corrections** where the old path found none.
- Every returned correction is checked against the transcript before it is
  shown. If the span it quotes is not in the text, it is dropped — that is the
  whole defence against an invented mistake, and it is cheap.
- The report no longer requires a correction to repeat before showing it.
  Requiring `times >= 2` is why the section was empty on days that had plenty
  in them. Yesterday's mistakes come first, repeated habits after.
- `typed.py`: what you typed into Claude Code, from its own transcripts, as a
  third source. Grammar only. Excluded: pastes, slash commands, tool output,
  interrupts, anything under a Mr Tharoor project folder (the checker is
  Claude Code, and without that filter its own prompt comes back as homework).
- Dictated text pasted into a text box is not counted as typing: the day's
  Wispr texts are passed as an exclusion list.

Known ceilings of this approach:

| What | Why it is acceptable |
|---|---|
| Transcript text now leaves the machine | Stated in the README and in the report footer. Audio still does not. `MR_THAROOR_NO_LLM=1` reverts to local rules. |
| Typing is Claude Code only | Everything else needs an Accessibility keylogger, which would put passwords in a grammar report. Revisit only if the typing section proves useful. |
| Text someone else wrote, pasted in and typed around, can be marked | Only when pasted without Claude Code's own `pasted_content` tags. Rare, low harm. |
| One or two subprocess calls a night, ~90s each | Nightly job, no interactive path. Capped at 8 batches a day. |


## Reliability repairs — 20 September 2026

Implemented and regression tested:

- Sentence transcripts previously aligned to the whole recording. They now
  use timestamped slices and retain their absolute source time.
- Wispr's formatted text previously supplied the pronunciation reference.
  Raw ASR now supplies it, and words near rewrites are excluded.
- A best-effort fallback showed a finding when no sound passed the report
  threshold. Removed; reminders now share the report's filter.
- Opportunity counts previously omitted clean words and duplicated totals
  for repeated errors. Nightly analysis now writes complete, idempotent tallies.
- Grammar diffs previously promoted model style rewrites to mistakes. Default
  grammar analysis now uses explicit rules; only hand edits enter the diff path.
- Homographs were chosen per spelling, forcing repeated `read` to have one
  pronunciation. Choices are now per occurrence, with abstention beyond the
  search budget.
- Review never played the user's clip and could not see nightly evidence.
  It now reviews actual report examples and honours false-alarm judgements.
- Reading budgets double-counted saved chunks and did not reset at midnight.
  Both are fixed. Unknown microphone ownership now prevents speculative capture.
- Nightly battery skips had no retry; morning searched only yesterday/today.
  Catch-up analysis, completion markers, login/interval retries, and once-daily
  opening of the latest completed report are implemented. Scheduled analysis
  now permits battery operation while the laptop is awake.
- Reminders did not enforce their daily cap across invocations and reanalysis
  reset learning progress. Delivery counts and last-seen dates now persist.

Still unresolved: recognition accuracy on this user's connected speech;
speaker attribution for meetings; identifying the exact text being read;
support for a selectable accent beyond the CMUdict reference. The limited
local grammar rules intentionally miss many constructions. Historical results
and notes below describe the earlier pipeline and are not current guarantees.

Everything deferred is written down here. A vague intention is a lie.

## The honest state

Mr Tharoor runs. Three launchd agents: a context-aware listener at login, analysis
at 23:30, the report and greeting at 08:30. For dictation it reads Wispr Flow's
own database (audio already paired with the words you meant); its own
microphone covers reading aloud. Meetings and calls remain disabled. The report has a
pronunciation section with your voice next to a human recording, and a
phrasing section with the corrections you keep needing.

```
built     wispr reader · grammar · listener · nightly · morning · report
          reminders · dictionary · evidence model · selftest · 4 test suites
measured  false-alarm floor 1 in 127 chances on known-correct speech (0.8%,
          at most 3.0%); consonants 0 in 113
unproven  recall, and precision on your own connected speech. Needs `tharoor check`
missing   speaker filter · Windows
```

## The one thing that should happen next

**`tharoor check`.** Twenty minutes of judging findings. `tharoor selftest` now bounds
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
| 1 | **No speaker filter**, so meetings are simply not recorded any more: the microphone stays shut while another app holds it. That removes the consent problem and the wrong-speaker data, and gives up the only source for meetings. ~150 lines with voice enrolment would buy it back. | Medium | `context.py` |
| 2 | ~~Grammar coverage is deliberately limited.~~ Replaced 22 Sep: the rules found zero in a month, so the checker is now the Claude Code CLI with a verify-against-transcript guard. Still depends on transcript accuracy — a mishearing can read as a grammar slip, and the prompt says to skip those. | — | `grammar.py` |
| 3 | **Reading-aloud detection is energy plus zero-crossing.** A radio in the next room can pass it. The SNR gate and the nightly analysis catch most of that downstream, at the cost of a wasted 30s recording. | Medium | `listener.py` |
| 4 | **Wispr schema dependency.** Another company's private database. The reader checks the schema and fails loudly, but a Wispr release can still break the primary source overnight. Fallback is the listener. | Medium | `wispr.py` |
| 5 | **Whisper cannot recover badly-said words** on our own recordings (not Wispr's). *version* became *mission*. Two recovery routes have now been tried and measured empty — see below. Only Wispr's text, or `tharoor check`, tells those apart. | Medium | `listen.py` |
| 8 | **The own-microphone path barely earns its keep.** 3.1 dB median on a real day against 24.0 dB through Wispr; 82% of a day's chunks are now dropped at capture for being under the analyser's floor. It still covers meetings and reading aloud, which Wispr never hears, but it is a weak second source and the report should probably say which source a finding came from. | Medium | `listener.py` |
| 6 | ~~Voice path ducks other audio on calls.~~ Fixed by not recording during calls at all. Apple's echo cancellation still has no true off switch, so if `LISTEN_ALWAYS` is ever restored this comes back with it. | – | `capture.py` |
| 7 | **Windows.** ~49% of the code is portable. The missing half is CoreAudio process enumeration and voice processing, with no clean equivalent. Not until the Mac version is validated. | Low | – |

### Fixed today, after a call went wrong

- The listener opened the microphone alongside a WhatsApp call, recorded 30
  second chunks through Apple's voice path, and audibly degraded the call.
  It no longer opens the microphone while any other app holds it. Three
  reasons, only one of them the noise: see `context.decide`. `2026-09-20`

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
  so `tharoor logs` and the morning notification can say the microphone is too
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
