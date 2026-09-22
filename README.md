# Mr Tharoor

## One word for the rule, the sound in letters, and a week's arithmetic — 22 September 2026

Four changes, all of them about the page teaching rather than reporting.

**A one-word reason on every correction.** *AGREEMENT*, *PARTICIPLE*, *ARTICLE*,
*COUNTABLE*. The full rule is still underneath in a line, but the word is the
thing to remember: it is what you should be able to say back when someone asks
why the correction is right.

**Pronunciation in letters, not symbols.** `/v/ → /w/` teaches nobody anything
on a printed page. It now reads *You said **WERSION** / The word is **VERSION***,
with the misspelling derived from the sound that actually came out. Where
letters cannot show the difference — a retroflex T is still a T — it says so
rather than inventing a spelling.

**Seven days, honestly.** A strip at the top compares corrections per thousand
words against the previous seven days. Three rules keep it from lying: only
days the current checker read are counted (the old rules found nothing, and
comparing against that would show a collapse that never happened), the count is
always divided by how much you actually produced, and a difference smaller than
twice the combined standard error is reported as no difference at all.

**A portrait.** Mr Tharoor is drawn in inline SVG — a fictional professor,
spectacles and a band collar, not a likeness of anyone living — so the page
stays one self-contained file that prints in ink.


## The report is a lesson now, and the name is one name — 22 September 2026

The morning page was a dark dashboard: four numbers, then cards. It is now a
light lesson sheet, typeset in serif, printed-page first, because that is what
a PDF is read as and because a teacher's page should look like one. Each
correction is numbered and laid out the way a marker would write it — what you
produced, struck through; what to produce instead; the rule underneath; the
sentence it came from. The lesson comes before the pronunciation section, since
that is where the material usually is, and the opening line says how many
corrections there are and which half of the day they came from.

`roy` is gone from every command, every table and every line of help: the
command is `tharoor`. The `roy` entry point still exists, undocumented, so
older habits and any script you wrote do not break.


## Grammar that finds things, and the typing half — 22 September 2026

The phrasing section had been empty every morning since it was written. Seven
regular expressions and a filtered diff, run over a month of real dictation,
produced an empty list every single night. The mistakes were plainly there in
the transcripts — *"the result which you have gave"*, *"I did not went"*,
*"write a email"*, *"the people that is building"* — and no rule caught one
of them. Writing the two-hundredth regex is not a plan.

The grammar half now calls the Claude Code CLI already installed on this
machine, once or twice a night, with the day's raw transcripts. On 20
September, where the old checker found **nothing**, it found **20** real
corrections. Every correction is verified against the transcript before it is
believed: if the span it claims you said is not in the text, it is dropped.

**What you type is marked too.** Claude Code already stores every message you
type, in `~/.claude/projects/*/*.jsonl`. That is read as the typing half of the
day — pasted blocks, slash commands, tool output and the checker's own
prompts excluded — and the morning PDF now has two grammar sections: what you
said, and what you typed.

**This is a change of posture and it is stated plainly.** Text now leaves the
laptop, for that one call. Audio still never does. Most of the text in question
was dictated or typed into Claude to begin with. `MR_THAROOR_NO_LLM=1` turns it
off and leaves the old local rules; without the Claude CLI on PATH, grammar
falls back to them automatically.

Meetings: a dictation made during a meeting is covered like any other, because
Wispr Flow records it. Live meeting speech that never goes through Wispr is
still not captured, for the three measured reasons below — it spoils the call,
the audio is 4.5x quieter, and there is no speaker filter.


## Automation and PDF recovery - 21 September 2026

`tharoor install` now targets the macOS desktop login session explicitly and
verifies each service after loading it. An unsuccessful installation exits
with an error. `tharoor install --status` reports each service's actual state,
PID when running, and any unsuccessful last exit. A plist on disk alone does
not mean the service is running.

Daily analysis prioritises yesterday, then catches up the other retained days.
It retries missing PDF exports from saved results without running the speech
models again. Failed exports preserve the previous PDF and are logged. PDFs
require a local Chrome/Chromium browser; HTML is always generated. Reports
include processing counts, the generation time, and a partial-day label when
run before the day ends. A manual daytime report does not suppress the nightly
analysis.

Downloaded speech models are loaded from the local cache first. The hub is
contacted only if required cache files are missing, so a network connection
stall cannot block loading an already downloaded model.

To investigate a missing report, use the Python environment where the project
is installed:

```bash
tharoor install --status
tharoor logs
tharoor analyse-pending --force
```

The morning job opens the PDF in Preview and the interactive HTML review in
your browser, where audio playback is available. The PDF is also stored in
`reports/YYYY-MM-DD.pdf`. No new
full-day PDF is expected at the start of that same day: the morning review
covers the preceding day.

## Reliability update — 20 September 2026

The speech-to-report pipeline now abstains when recognition is uncertain:

- Each Whisper segment is compared only with its own timed audio. Previously,
  every segment was aligned to the entire recording.
- Wispr pronunciation analysis uses its raw transcript. Rewritten words and
  their neighbours are excluded; formatted text is not proof of what was said.
- A pronunciation candidate needs a phoneme score of at least 0.80, overall
  alignment agreement of at least 0.60, and matching neighbouring sounds.
  Weak vowels in common function words are not treated as mistakes.
- Counts include correctly pronounced words and recordings, once each.
  The report and reminders use the same evidence filter. If nothing qualifies,
  neither invents a correction. Older findings remain on disk but cannot
  automatically create new reminders under the revised policy.
- Grammar uses a small set of explicit local rules, plus isolated changes you
  made by hand. Model rewrites such as `kindly → please`, `prepone → bring
  forward`, and `the same → it` are not grammar judgements.
- `tharoor check` plays your own clip and the reference. Answering `n` excludes
  that day's word/sound from future evidence, reports, and reminders.

The latest reference test produced **0 flags in 118 usable sound opportunities
across 86 cached reference recordings**. This does not measure recall or
accuracy on your connected speech. Model scores are not calibrated probabilities
that you made a mistake. The historical experiments below predate this update.

`tharoor install` updates the three existing launch agents. Analysis checks
every 15 minutes while awake and at login, catches up the last three days,
and processes the current day after 23:30. Scheduled analysis also runs on
battery; it does not request a wake lock. The morning job retries until a
completed local report exists and opens it once per report/day between 08:00
and 21:00, outside calls. A day analysed before midnight is finalised again
the next day to include late speech. Raw audio still expires after three days.

The HTML report remains the interactive review because it can play your voice
and the dictionary reference. The morning job also opens the PDF in Preview;
PDF and Word exports are optional local outputs when their converters are
installed. Grammar calls the local Claude Code CLI; see 22 September above.
The existing local speech models are still required to interpret microphone audio.

Meetings remain disabled: the current code cannot reliably distinguish your
voice from other speakers, and its previous shared voice-processing path
degraded calls. Reading detection is a heuristic based on the foreground app,
output audio, and sampled speech; it cannot know which text you are reading.

From the same Python environment that installed Mr Tharoor, install the dev
extras once with `python -m pip install -e '.[dev]'`, then run the automated
checks with `python -m pytest tests -q`. The tests isolate the user's data and
mock capture. The explicit hardware check is separate:
`python tests/test_micgate.py` (opens a test microphone stream).

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

macOS only. No audio ever leaves the laptop and no API key is needed. Two
things do go out: a human recording of a word, fetched the first time it is
flagged, and the day's transcripts, sent to the Claude Code CLI for the grammar
pass — which `MR_THAROOR_NO_LLM=1` switches off.

---

## Install

```bash
git clone https://github.com/ajmerabaibhav/Mr-Tharoor.git mr-tharoor
cd mr-tharoor
pip install -e .
tharoor setup
```

`tharoor setup` does the rest: checks the machine, verifies every library, asks
macOS for microphone permission (say yes), downloads the two models, and
installs three launchd agents. It names the fix for anything that fails rather
than printing a traceback.

About 3 GB downloads once: a phoneme recogniser (2.4 GB) and Whisper small.en
(464 MB). After that it runs offline. Nothing needs sudo, nothing installs
outside your home directory.

Then talk normally. That is the whole thing.

## Use

```bash
tharoor listen           # start it, leave it running, forget it
```

That is the whole daily interaction. At 23:30 it analyses the day; the morning
report opens after 08:00, with retries after sleep or login.

| Command | What it does |
|---|---|
| `tharoor listen` | the all-day loop. Context-aware, sleeps when you are not talking |
| `tharoor gate` | should it be listening right now, and why |
| `tharoor mictest` | compare microphone setups by measuring, not guessing |
| `tharoor selftest` | false-alarm floor, measured on known-correct speech. No labelling |
| `tharoor check` | judge its findings, so accuracy becomes a number |
| `tharoor score` | what your answers add up to, with honest intervals |
| `tharoor drill` | hear it, say it, hear it again |
| `tharoor probe` | record 20 sentences that test whether it works on your voice |
| `tharoor analyse-day` | run tonight's job now |
| `tharoor logs` | what the scheduled jobs actually did |
| `tharoor install --remove` | stop all of it. Three launch-agent files deleted. |
| `tharoor analyse-pending --force` | catch up retained days, including on battery |

---

## Where the speech comes from

Three sources, best first.

**Wispr Flow's own database.** If you dictate with Wispr Flow, every
dictation is already stored on your Mac: the audio, what the recogniser heard,
what the model decided you meant, and what you corrected by hand. That is the
exact pair this tool needs, produced by a model that saw the whole sentence.
Mr Tharoor reads it through SQLite's read-only backup API. Pronunciation is
aligned to the raw transcript, with rewritten regions excluded. The
**phrasing** section applies explicit grammar rules to that transcript and
can include isolated changes you made by hand. A transcript can still be wrong;
listen to the recording before accepting a suggestion.

The reader checks Wispr's schema before trusting anything and fails loudly
if a release changes it.

**Its own microphone**, for reading aloud: a page in Claude, a PDF, your
notes. Words come from Whisper here, which is weaker than Wispr's text, so
these findings count for a little less. Calls and meetings are deliberately
not recorded — see below.

**What you typed**, from Claude Code's own transcripts. Grammar only: there is
no audio, so there is nothing to say about pronunciation. It is deliberately
limited to Claude Code, because reading every keystroke on this machine would
mean an Accessibility keylogger and a morning report that could contain a
password.

## How it decides to listen

Holding the microphone open all day costs real battery. Asking the operating
system a question costs microseconds. So three signals, cheapest first:

```
1. is another app on the mic?   free, the OS knows. A call, a huddle.
                                Stay out of it. See below.
2. what is in front of you?     1 microsecond. Claude, a PDF, your notes.
3. is anything playing sound?   free. A browser making noise is a video.
```

The microphone opens only when 2 says *maybe* and 3 says *silent*, and then in
half-second peeks rather than continuously.

**It never opens while another app has the microphone.** That reads as an odd
choice — a call is a conversation, and conversation is what this listens for —
so here is the reasoning, which is three separate problems rather than one:

- **It spoils the call.** Apple's voice processing reconfigures the shared
  input device and ducks other audio, and there is no true off switch, only a
  minimum level. Reported from a real call, which is what changed this.
- **The audio is poor anyway.** Our share comes back about 4.5x quieter while
  another app holds the device: 3–6 dB median against 24 dB through Wispr,
  most of it below the analyser's own floor. It was recorded, stored, decoded
  at 23:30, and deleted.
- **It is not your voice.** A call has someone else in it, there is no speaker
  filter, and their pronunciation was being scored as yours.

What that gives up is meetings, the one case with no other source. Dictation
comes from Wispr's own database and reading aloud from the sampling path, both
untouched. A speaker filter is the only thing standing between here and
meetings working again.

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
   report only when the model's lower bound clears the reporting threshold
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

- Transcript text leaves the machine once a night, for the grammar pass.
  `MR_THAROOR_NO_LLM=1` stops that and the local rules take over.
- Audio never leaves the machine. Raw recordings delete after 3 days; the
  tallies they produced are kept forever, because counts are free and audio
  is not.
- Silence is never written to disk.
- `data/`, `cache/`, `reports/` and `logs/` are gitignored. This repo contains
  no recordings.
- **The microphone never opens while another app has it**, so a call is not
  recorded and the person on the other end is not analysed. There is still no
  speaker filter; this is what stands in for one.

---

## Honest limits

**Accuracy has a floor now, measured without asking anyone anything.**
`tharoor selftest` runs the detector over the human recordings already cached
for the report. Those are native speakers saying the word properly, so every
finding it produces is a false alarm by construction. No labelling, no
opinion, 25 seconds. On 86 words: **1 false alarm in 127 chances (0.8%, at
most 3.0%)**, and the one was `æ -> ɛ` in unstressed *than*, which is
reduction rather than error. Consonants: **0 in 113**.

That is a floor, not the rate you would see in a meeting: single words, read
carefully, by a speaker who does not have the habit being hunted. It bounds
false alarms and says nothing at all about recall. Per contrast the sample
is still thin — zero out of eight chances for /v/ means "at most 21%", not
"never" — so the aggregate is the number worth quoting. `tharoor check` remains
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
the day measured, 82% of what its own microphone collected — and `tharoor logs`
and the morning notification tell you how many went in the bin, while you
can still move. Wispr's path needs none of it: close microphone, and it
already knows the words.

**macOS only.** About half the code is portable Python; the other half is
CoreAudio session enumeration and Apple's voice processing, neither of which
has a clean Windows equivalent.

## Tests

```bash
pip install -e '.[dev]'
python3 -m pytest tests -q
```

The checks cover segment/audio correspondence, abstention, homographs,
complete evidence counts, grammar rewrites, reminders, scheduler retries,
dictionary lookups, and microphone policy. They do not measure personalised
recognition accuracy; use `tharoor check` for that.

## Licence

MIT.
