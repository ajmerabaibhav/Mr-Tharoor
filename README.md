<div align="center">

<img src="docs/tharoor.svg" width="112" alt="Mr Tharoor">

# Mr Tharoor

**An English teacher who listens to how you actually talk, then hands you a lesson every morning.**

</div>

---

He reads what you dictate and what you type. He marks the grammar a teacher
would mark, hears the sounds you get wrong, and at 08:30 a PDF opens on your
desk: what you said, what to say instead, and the one word that tells you why.

macOS. Your audio never leaves the laptop.

> **AGREEMENT**
> You said ~~"the people that is actually building"~~
> Say **"the people that are actually building"**
> *plural noun requires plural verb*
> &nbsp;&nbsp;&nbsp;&nbsp;"...find the people that is actually building and in consumer AI startup..."

## Install

```bash
git clone https://github.com/ajmerabaibhav/Mr-Tharoor.git mr-tharoor
cd mr-tharoor && pip install -e . && tharoor setup
```

`tharoor setup` checks the machine, asks for the microphone, downloads the two
speech models (~3 GB, once), and installs three launch agents. Then talk and
type normally. That is the whole interaction.

## What he reads

| source | what it gives him |
|---|---|
| **Wispr Flow's database** | your dictation, in any app, with the audio already paired to the words you meant. Grammar *and* pronunciation. |
| **His own microphone** | reading aloud. Calls are never recorded: there is no speaker filter, and it is not your voice on the other end. |
| **Claude Code's transcripts** | what you typed. Grammar only. Pastes, commands and tool output excluded; deliberately not a keylogger. |

## What he does with it

```
the sounds you MADE   wav2vec2-espeak, on your machine, no language model
the words you MEANT   whisper small.en, or Wispr's own text
        ↓
pool by SOUND across every word carrying it, weighted by audio quality,
report only when the lower bound of the credible interval clears the floor

the grammar            one batched call to the claude CLI already installed here
        ↓
every correction must quote a span that is really in your transcript, or it
is dropped. Nothing else stands between you and an invented mistake.
```

## Commands

| | |
|---|---|
| `tharoor listen` | the all-day loop. Sleeps when you are not talking |
| `tharoor analyse-day` | run tonight's job now |
| `tharoor morning` | open the latest lesson |
| `tharoor check` | judge his findings, so accuracy becomes a number |
| `tharoor drill` | hear it, say it, hear it again |
| `tharoor logs` | what the scheduled jobs actually did |
| `tharoor install --status` | are the three agents really running |
| `tharoor install --remove` | stop all of it |

## What he will not claim

- **Meetings.** Dictation during a meeting is covered; live meeting speech is
  not. Measured: our share of a contended microphone is 4.5x quieter, and
  there is no speaker filter, so it was scoring the other person as you.
- **Your own microphone is the weak source.** 3.1 dB on an ordinary day against
  24.0 dB through Wispr. No algorithm closes that. Sit closer.
- **Progress needs a week and says so.** The seven-day strip divides by how
  much you actually produced and calls anything inside the noise band exactly
  that: nothing proved.
- **Pronunciation accuracy on your voice is unmeasured.** `tharoor check` is
  the only thing that turns it into a number. Nobody has run it yet.
- **Text leaves the machine once a night** for the grammar call.
  `MR_THAROOR_NO_LLM=1` turns that off and falls back to local rules.

## Privacy

Audio never leaves the laptop and raw recordings delete after three days. The
microphone never opens while another app holds it. `data/`, `cache/`,
`reports/` and `logs/` are gitignored; this repo contains no recordings.

## Tests

```bash
pip install -e '.[dev]' && python3 -m pytest tests -q
```

---

> **A tribute, not an association.** The name and manner are an affectionate
> nod to Dr Shashi Tharoor. This project is **not affiliated with, endorsed by,
> or connected to him in any way**, the character is a fictional mascot, and
> the drawing is nobody's likeness. If any objection is ever raised, the name
> will be changed without argument.

What changed and what was measured: [CHANGELOG.md](CHANGELOG.md).
What is still broken: [TODOS.md](TODOS.md). MIT.
