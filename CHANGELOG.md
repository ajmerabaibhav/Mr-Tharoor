# Changelog

What changed, when, and what was measured. Newest first.
The current state of the project is in [README.md](README.md); what is still
broken or deferred is in [TODOS.md](TODOS.md).

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

