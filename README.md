# Mr Roy

A pronunciation coach that listens to how you actually talk, and each morning
plays you the words you got wrong next to a recording of them said properly.

You cannot learn a sound by reading a symbol. `/ˈvɜːʒn̩/` teaches nobody
anything. Hearing yourself say *wersion*, then hearing *version*, teaches it in
one second.

macOS only. Everything runs on your machine: no API keys, no accounts, no
audio leaves the laptop. The single network call is fetching a human recording
of a word the first time it gets flagged.

---

## Install

```bash
git clone https://github.com/ajmerabaibhav/Mr-Roy-.git mr-roy
cd mr-roy
pip install -e .
pip install torch transformers faster-whisper cmudict pyobjc-framework-AVFoundation
roy install          # two launchd agents. no sudo.
```

About 3 GB of models download on first use: a phoneme recogniser (2.4 GB) and
Whisper small.en (464 MB). macOS will ask for microphone permission once.

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
| `roy check` | judge its findings, so accuracy becomes a number |
| `roy score` | what your answers add up to, with honest intervals |
| `roy drill` | hear it, say it, hear it again |
| `roy probe` | record 20 sentences that test whether it works on your voice |
| `roy analyse-day` | run tonight's job now |
| `roy logs` | what the scheduled jobs actually did |
| `roy install --remove` | stop all of it. Two files deleted. |

---

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

**Accuracy is unmeasured.** Every threshold in `evidence.py` is a judgement
call. `roy check` is the only thing that turns them into settings.

**Badly mispronounced words cannot be recovered.** Whisper heard *version* as
*mission* and *vulnerable* as *wondering* — both /v/ words from a speaker who
produces /w/. It was transcribing what was actually said. To judge how a word
was pronounced we need to know which word was meant, and the only evidence is
a pronunciation wrong enough to change the word. Live audio produced 3 findings
where a scripted probe produced 32.

**Audio quality is the binding constraint.** A first real session measured
12 dB signal-to-noise against 37 dB on reference recordings. Findings from it
are weighted down to 36%. Recording a hand-span from the microphone does more
than any algorithm: measured, gain normalisation changes nothing (the model
already normalises) and spectral subtraction raises SNR 15 dB while improving
recognition by zero.

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
