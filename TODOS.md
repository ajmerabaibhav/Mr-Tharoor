# What is not built, and what is known broken

Everything deferred is written down here. A vague intention is a lie.

## The honest state

Mr Roy is currently **a dictionary with a battery gate**. He can tell you how any
word should sound and he knows when you are in a call. He cannot yet hear you.
The part that makes this *yours* rather than a lookup tool does not exist.

```
built        [####################        ]  the easy half
             dictionary  micgate  streaks  cli  tests
not built    [                    ########]  the half that carries the risk
             capture  ASR  phoneme model  alignment  report  launchd
```

## The one thing that should happen next

**Prove the signal.** Record yourself reading 20 sentences loaded with the
tracked contrasts, run the phoneme model over them by hand, and check whether it
catches errors you already know you make.

This was Phase 1 of the original plan and it has not been done. Everything built
so far was built because it was buildable, not because it was risky. If the
phoneme model cannot separate your /v/ from your /w/ in connected speech, none
of the rest matters and the project should stop. That check costs about two
hours and it is the only thing standing between "promising" and "known".

## Known defects

| # | What | Severity | Where |
|---|------|----------|-------|
| 1 | **Homographs return one pronunciation.** `record` gives the noun `/ˈɹɛk.ɔːd/`. Say "record this" (verb, `/ɹɪˈkɔːd/`) and Mr Roy teaches the wrong stress. Same for `read`, `present`, `object`, `address`. Stress is one of the tracked contrasts, so this actively misfires on the feature it should serve. | High | `dictionary.py:_extract_ipa` |
| 2 | **Initialisms are lowercased and mangled.** `AI` becomes `ai` and returns `/ˈɑ.i/`, which is a different word. You say AI constantly. | High | `dictionary.py:lookup` |
| 3 | ~~Bluetooth mics invisible to the gate~~ **Measured false.** CoreAudio reports input for AirPods Pro on macOS 26.6; the primary path works on Bluetooth. An inferred fallback (call-app audio output) is kept as insurance for hardware that does not report, and is itself unverified. | ~~High~~ Closed | `micgate.py` |
| 4 | **No logging anywhere.** When the 23:30 job fails, nothing tells you. Silent failure is the defect the whole design is supposed to avoid. | High | everywhere |
| 5 | **Indian proper nouns have no coverage.** `Bengaluru` returns nothing, not even synthetic. Place names and names of people are a real part of your speech. | Medium | `dictionary.py` |
| 6 | IPA extraction is a regex over wikitext. It works on every word tested but Wiktionary templates vary, and a miss is silent. | Medium | `dictionary.py:_extract_ipa` |
| 7 | `config.py` creates directories as a side effect of being imported. Importing a module should not touch the filesystem. | Low | `config.py` |
| 8 | Not committed to git. | Low | - |

### Fixed already

- **Playing a different word entirely.** Substring matching returned `threesome`
  for `three` and `already` for `read`. Silent and the worst failure this tool
  has, because the audio plays and simply teaches the wrong thing. Now requires
  an exact filename match, locked in by `test_never_plays_a_different_word`.
- Rate limits cached as "this word has no pronunciation", poisoning the cache
  permanently.
- Every HTTPS request stalling 20s on a dead IPv6 address.
- Derived Commons URLs 404ing on filename capitalisation.

## Not built

1. **Capture** — record while the gate is open, 16kHz mono, silence trimmed.
   Needs the gate polled on a loop, which is also not written.
2. **Speaker filter** — keep only your voice. This is the consent story, not a
   nice-to-have.
3. **The two-pass analysis** — ASR for the words you meant, phoneme model for
   the sounds you made, aligned against the dictionary. This is the product.
4. **Report generator** — turn `streaks.verdicts()` into the HTML that the
   dashboard mock shows. The mock is hand-written; nothing generates it yet.
5. **PDF and Word export** — both verified working by hand (`chrome-headless-shell
   --print-to-pdf`, `textutil -convert docx`), neither wired up.
6. **The two launchd jobs** — 23:30 analyse, 08:30 open.
7. **`roy drill`** — play a word, pause, play it again. The actual learning loop,
   and it only exists as buttons in a mock.
8. **WhatsApp delivery** — undecided, and the only step where the report leaves
   the machine.

## Deliberately not doing

- Live in-ear correction during calls. Being buzzed mid-sentence in front of a
  client is unpleasant, and it forces the models to run during the call, which
  is the exact battery cost the gate exists to avoid.
- iPhone microphone.
- Multi-user support, until this has been used solo for a month.
