# Mr Tharoor

A pronunciation and phrasing coach that listens to how you actually talk, and
each morning greets you with the words you got wrong, your own voice next to a
recording of them said properly, and the phrases you keep getting backwards.

Mr Tharoor is an old-school Indian professor of English: courteous, exacting,
fond of a long word where a long word is warranted, and entirely without
condescension. He corrects the way a good teacher does, by showing you the
thing and trusting your ear to do the rest.

> **A tribute, not an association.** The name and manner are an affectionate
> nod to Dr Shashi Tharoor, whose command of English is the standard many of
> us grew up measuring ourselves against. This project is **not affiliated
> with, endorsed by, or connected to him in any way**, and the character is
> a fictional mascot. Every word it speaks was written for this software.
> If any objection is ever raised, the name will be changed without argument.

You cannot learn a sound by reading a symbol. `/ˈvɜːʒn̩/` teaches nobody
anything. Hearing yourself say *wersion*, then hearing *version*, teaches it in
one second.

macOS only. Everything runs on your machine: no API keys, no accounts, no
audio leaves the laptop. The single network call is fetching a human recording
of a word the first time it gets flagged.

---

## Install

```bash
git clone https://github.com/ajmerabaibhav/Mr-Roy-.git mr-tharoor
cd mr-tharoor
pip install -e .
roy setup
```

`roy setup` does the rest: checks the machine, verifies every library, asks
macOS for microphone permission (say yes), downloads the two models, and
installs three launchd agents. It names the fix for anything that fails rather
than printing a traceback.

About 3 GB downloads once: a phoneme recogniser (2.4 GB) and Whisper small.en
(464 MB). After that it runs offline. Nothing needs sudo, nothing installs
outside your home directory.

Then talk normally. That is the whole thing.

## Use

```bash
roy listen           # start it, leave it running, forget it
```

That is the whole daily interaction. At 23:30 it analyses the day, at 08:30
the report opens itself.

| Command | What it does |
|---|---|
| `roy listen` | the all-day loop. Context-aware, sleeps when you are not talking |
| `roy gate` | should it be listening right now, and why |
| `roy mictest` | compare microphone setups by measuring, not guessing |
| `roy selftest` | false-alarm floor, measured on known-correct speech. No labelling |
| `roy check` | judge its findings, so accuracy becomes a number |
| `roy score` | what your answers add up to, with honest intervals |
| `roy drill` | hear it, say it, hear it again |
| `roy probe` | record 20 sentences that test whether it works on your voice |
| `roy analyse-day` | run tonight's job now |
| `roy logs` | what the scheduled jobs actually did |
| `roy install --remove` | stop all of it. Two files deleted. |

---

## Where the speech comes from

Two sources, best first.

**Wispr Flow's own database.** If you dictate with Wispr Flow, every
dictation is already stored on your Mac: the audio, what the recogniser heard,
what the model decided you meant, and what you corrected by hand. That is the
exact pair this tool needs, produced by a model that saw the whole sentence.
Mr Tharoor reads it (read-only, through SQLite's backup API, never writing to it)
and gets clean close-mic audio with reliable text for free. It is also where
the **phrasing** section comes from: what you said against what you meant,
filtered to the kinds of change a grammar teacher would mark, articles,
prepositions, number, verb form, and Indian English fixed phrases like
"revert back" and "discuss about". Fillers and style rewrites are discarded.

The reader checks Wispr's schema before trusting anything and fails loudly
if a release changes it.

**Its own microphone**, for everything Wispr does not hear: a Google Meet, a
WhatsApp call, reading aloud in Claude or ChatGPT. Words come from Whisper
here, which is weaker than Wispr's text, so these findings count for a little
less.

## How it decides to listen

Holding the microphone open all day costs real battery. Asking the operating
system a question costs microseconds. So three signals, cheapest first:

```
1. is another app on the mic?   free, the OS knows. A call, a huddle.
2. what is in front of you?     1 microsecond. Claude, a PDF, your notes.
3. is anything playing sound?   free. A browser making noise is a video.
```

The microphone opens only when 2 says *maybe* and 3 says *silent*, and then in
half-second peeks rather than continuously. A dictation app running while a
speech service holds the mic means you are talking deliberately into a close
microphone, so that records straight away.

Measured: **8.3 seconds of CPU across a 14 hour day**, 29 MB resident.

Notably absent: reading your browser tab URLs. AppleScript could, and it would
make "youtube.com means no" trivial. The sound check gives the same answer
without a tool that can see every page you visit.

## How it decides you got something wrong

```
whisper small.en    ──►  the words you MEANT
wav2vec2-espeak     ──►  the sounds you MADE
                         (no language model, so it will not correct you)
        │
        ▼
   align against CMUdict, keeping every valid pronunciation of each word
        │
        ▼
   pool by SOUND across every word containing it, weighted by detector
   confidence and audio quality, decayed by age
        │
        ▼
   report only when the 95% lower bound says the error rate is real
```

A sound reaches the page when the pooled rate across every word carrying it
clears a credible lower bound, not when one detection happened to be
confident. Measured on a real day: /th/ went wrong on 22% of its chances, a
genuine habit; /d/, /z/, /v/ and the trap vowel all sat between 0.5% and 2%,
which is a detector's noise floor. Confidence answers "did the model hear
this clearly" and says nothing at all about whether it is a habit.

Evidence about a sound compounds across every word that contains it. If you
produce `/w/` for `/v/` 140 times out of 200 across forty words, then saying
*vulnerable* once and getting it wrong is not one weak data point. That is a
hierarchical Beta-Binomial model, and it is why a word said once can be
reported while the same observation on a clean sound stays silent.

Reporting uses the lower bound of the credible interval, not the mean, so
small samples disqualify themselves without a rule: 1 wrong out of 1 scores
0.04, but 30 out of 30 scores 0.80.

## Privacy

- Audio never leaves the machine. Raw recordings delete after 3 days; the
  tallies they produced are kept forever, because counts are free and audio
  is not.
- Silence is never written to disk.
- `data/`, `cache/`, `reports/` and `logs/` are gitignored. This repo contains
  no recordings.
- In a meeting the microphone hears everyone. **There is no speaker filter
  yet**, so other people's speech is analysed too. See TODOS.md.

---

## Honest limits

**Accuracy has a floor now, measured without asking anyone anything.**
`roy selftest` runs the detector over the human recordings already cached
for the report. Those are native speakers saying the word properly, so every
finding it produces is a false alarm by construction. No labelling, no
opinion, 25 seconds. On 86 words: **1 false alarm in 127 chances (0.8%, at
most 3.0%)**, and the one was `æ -> ɛ` in unstressed *than*, which is
reduction rather than error. Consonants: **0 in 113**.

That is a floor, not the rate you would see in a meeting: single words, read
carefully, by a speaker who does not have the habit being hunted. It bounds
false alarms and says nothing at all about recall. Per contrast the sample
is still thin — zero out of eight chances for /v/ means "at most 21%", not
"never" — so the aggregate is the number worth quoting. `roy check` remains
the only thing that measures findings from your own speech, and nobody has
run it yet.

**Two things decide whether a recording is worth anything, not one.**
Signal-to-noise asks whether the microphone heard the room. Phoneme
agreement — how much of the expected sequence the model actually matched —
asks whether it followed the words at all. Measured on 14 dictations:

| agreement | recordings | findings | chances | rate |
|---|---|---|---|---|
| below 0.50 | 3 | 33 | 213 | **15.5%** |
| 0.50 and above | 11 | 57 | 2,356 | **2.4%** |

Six times the finding rate from audio the model was not following, and SNR
does not predict which is which: the worst of the three had the second-best
signal in the set (32.9 dB), and the cleanest recording of all (43.7 dB) sat
at 0.53. When the model is not tracking the words the aligner pairs sounds
that have nothing to do with each other, and the debris looks exactly like a
finding. Both axes now weight the evidence. For scale, the 86 reference
recordings score 0.87.

**Badly mispronounced words still cannot be recovered — now tested, not
assumed.** Whisper heard *version* as *mission* and *vulnerable* as
*wondering*, both /v/ words from a speaker who produces /w/. It was
transcribing what was actually said. Two ways out, both measured, both empty:

- *Confusion-aware dictionary lookup.* Collapse every sound you confuse into
  one symbol, index CMUdict by the result, look up what was actually
  produced. 82% of keys map to exactly one word, so the idea is sound. On
  the 20 probe recordings it recovered **0 of 57** substituted words: at this
  audio quality the produced phonemes are not merely confused but truncated
  and garbled — *grew* came out `nkdeɪ`, *vet* came out `wɛ` — and no lookup
  repairs that.
- *Wispr's own record.* Wispr stores what its recogniser heard beside what
  you meant, which should expose any word a mispronunciation turned into a
  different real word. Across **201 dictations: zero** such pairs.

So the circularity stands. What changed is what follows from it: recovery
only matters on the own-microphone path, and that path has a larger problem.

**Audio quality is the binding constraint, and the two sources are nowhere
near each other.** Measured on this machine:

| source | median SNR | usable | full weight |
|---|---|---|---|
| Wispr Flow's own audio | **24.0 dB** | 100% | 36% |
| own microphone, scripted probe | 11.9 dB | 100% | 0% |
| own microphone, an ordinary day | **3.1 dB** | 18% | 8% |

Eighteen decibels apart, and no algorithm closes that: gain normalisation
changes nothing (the model already normalises) and spectral subtraction
raises SNR 15 dB while improving recognition by zero. Recording a hand-span
from the microphone is worth about 12 dB. Distance is the only lever and you
are the only one who can pull it.

So the listener no longer keeps what the analyser is going to refuse — on
the day measured, 82% of what its own microphone collected — and `roy logs`
and the morning notification tell you how many went in the bin, while you
can still move. Wispr's path needs none of it: close microphone, and it
already knows the words.

**macOS only.** About half the code is portable Python; the other half is
CoreAudio session enumeration and Apple's voice processing, neither of which
has a clean Windows equivalent.

## Tests

```bash
for t in tests/test_*.py; do python3 "$t"; done
```

Four suites. They cover the things that fail silently: never playing a
different word than the one asked for, never caching a rate limit as "this
word has no pronunciation", never letting a holiday read as improvement.

## Licence

MIT.
