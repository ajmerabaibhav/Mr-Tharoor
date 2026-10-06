"""Turn a day's findings into the page that opens at 08:30.

The page is deliberately one self-contained file. Audio is embedded rather
than linked, so it keeps working after the clips are deleted,
and it can be sent to someone or kept forever without dragging a folder along.

HTML only. It is the one format that can play sound, and hearing your own
voice is the point. Old pages are deleted by streaks.purge_expired.
"""

from __future__ import annotations

import base64
import html
import json
import subprocess
from datetime import date, datetime

from . import config, daily

# How a sound going wrong actually looks in letters. IPA teaches nobody
# anything on a printed page; "you said WERSION, the word is VERSION" teaches
# in one second. The respelling is an approximation of what came out, and the
# report says so -- the recording is the ground truth.
AS_HEARD = {
    "v->w": ("v", "w"), "w->v": ("w", "v"), "th->t": ("th", "t"), "dh->d": ("th", "d"),
    "z->s": ("z", "s"), "s->z": ("s", "z"), "zh->j": ("si", "sh"), "f->ph": ("f", "p"),
    "final-d": ("d", "t"), "ae->e": ("a", "e"), "o->aw": ("o", "aw"),
}


def _as_heard(word: str, contrast: str) -> str | None:
    """The word spelled the way it came out, or None when letters cannot show it."""
    pair = AS_HEARD.get(contrast)
    if not pair or not word:
        return None
    wrong, letters = pair
    low = word.lower()
    if contrast == "final-d":
        return low[:-1] + letters if low.endswith(wrong) else None
    if wrong not in low:
        return None
    said = low.replace(wrong, letters, 1)
    return said if said != low else None


# The mascot, drawn rather than fetched: inline SVG keeps the report one
# self-contained file that works offline and prints in ink. He is a fictional
# professor -- round spectacles, swept hair, a band collar -- and deliberately
# not a likeness of any living person. See the tribute note at the foot.
# The mascot, drawn rather than fetched: inline SVG keeps the report one
# self-contained file that works offline and prints in ink. He is a fictional
# professor -- swept hair going grey, round spectacles, a band-collar
# waistcoat -- and deliberately not a likeness of any living person. See the
# tribute note at the foot of the page.
#
# The medallion is not decoration. The drawing is ink on nothing, so on a dark
# background it simply disappears; the filled disc gives it its own paper
# wherever it is put, including a README on GitHub at night.
# An old-school English teacher: swept-back hair going silver at the temples,
# a warm smile, a light purple kurta. Fixed colours, so it reads the same in
# light and dark mode.
PORTRAIT = """<svg class="portrait" viewBox="0 0 124 124" role="img" aria-label="Mr Tharoor">
<defs><clipPath id="tharoor-face"><circle cx="62" cy="62" r="58"/></clipPath></defs>
<circle cx="62" cy="62" r="58" fill="#F4EEE2"/>
<g clip-path="url(#tharoor-face)"><g transform="translate(8 6)" stroke="#1F1A17" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round">
    <path d="M-4 124C-2 94 14 82 36 77L54 82L72 77C94 82 110 94 112 124Z" fill="#C9B6E4"/>
  <path d="M47 64L47 76Q54 80 61 76L61 64Z" fill="#B07450"/>
  <path d="M45 74Q54 81 63 74L64 79Q54 86 44 79Z" fill="#C9B6E4"/>
  <path d="M51 83L51 112L57 112L57 83" fill="none" stroke-width="1"/>
  <circle cx="54" cy="89" r="1.2" fill="#5B4580" stroke="none"/><circle cx="54" cy="98" r="1.2" fill="#5B4580" stroke="none"/><circle cx="54" cy="107" r="1.2" fill="#5B4580" stroke="none"/>
  <path d="M26 112L30 98M82 112L78 98" fill="none" stroke-width="1"/>
    <ellipse cx="34.5" cy="46" rx="3.2" ry="5.5" fill="#B07450"/><ellipse cx="73.5" cy="46" rx="3.2" ry="5.5" fill="#B07450"/>
  <path d="M35 40C35 28 43 22 54 22C65 22 73 28 73 40C73 56 65 67 54 67C43 67 35 56 35 40Z" fill="#B07450"/>
    <path d="M34 44C31 29 34 15 44 10C54 5 69 7 75 15C80 22 78 34 74 44C73 36 71 30 65 27.5C61 26 57.5 27.5 54.5 29C51 27 47 26 43.5 27.5C39 29.5 36 36 34 44Z" fill="#1E1A18"/>
  <path d="M43.5 27C42 22 42.5 16 45 12M49 26C50 20 54 14 60 11M56 28C59 22 64 17 71 15M62 27C66 23 70 21 75 21" fill="none" stroke="#5E5853" stroke-width="1.1"/>
  <path d="M34.5 43C34 38 35 34 37 32M73.5 43C74 38 73 34 71 32" fill="none" stroke="#BDB6AE" stroke-width="2.4"/>
    <path d="M40 37Q45 33.5 50 36.5M58 36.5Q63 33.5 68 37" fill="none" stroke-width="2.2"/>
  <path d="M42 42Q45.5 39.5 49 42M59 42Q62.5 39.5 66 42" fill="none"/>
  <circle cx="45.5" cy="42" r="1.2" fill="#1F1A17" stroke="none"/><circle cx="62.5" cy="42" r="1.2" fill="#1F1A17" stroke="none"/>
  <path d="M54 43C54 48 53 50 50.5 52Q54 54.5 57.5 52" fill="none" stroke-width="1.2"/>
  <path d="M45 57Q54 63 63 57" fill="none" stroke-width="1.7"/>
  <path d="M43 52Q42 56 44.5 59M65 52Q66 56 63.5 59" fill="none" stroke-width="1"/>
</g></g>
<circle cx="62" cy="62" r="58" fill="none" stroke="#1F1A17" stroke-width="2.2"/>
</svg>"""


CONTRAST_NAMES = {
    "v->w": "V becomes W", "w->v": "W becomes V", "th->t": "TH becomes T",
    "dh->d": "TH becomes D", "z->s": "Z becomes S", "zh->j": "ZH becomes SH",
    "final-d": "Final D becomes T", "f->ph": "F becomes P", "ae->e": "A becomes E",
    "o->aw": "O becomes AW", "t->retroflex": "T is retroflex",
    "d->retroflex": "D is retroflex",
}

# Mr Tharoor is an old-school Indian professor of English: courteous, exacting,
# fond of a long word where a long word is warranted, and entirely without
# condescension. He corrects the way a good teacher does, by showing you the
# thing and trusting you to hear it.
TIPS = {
    "v->w": "The upper teeth must meet the lower lip, and the voice must follow. "
            "A rounded lip gives you a W, and W is not what the word asks for.",
    "w->v": "Round the lips and keep the teeth well clear. A W never touches a tooth.",
    "th->t": "The tongue ventures between the teeth and the breath passes over it. "
             "It feels absurd. It is nonetheless correct.",
    "dh->d": "Tongue between the teeth once more, but this time with voice behind it. "
             "The TH of THIS, not the D of DIS.",
    "z->s": "The identical mouth as an S, with the voice switched on. "
            "Place a finger at the throat: you should feel it hum.",
    "zh->j": "Soft and sustained, as in the middle of TREASURE. "
             "Do not stop it short with a D in front.",
    "final-d": "Do not harden the ending into a T. Let the voice carry through to the close.",
    "f->ph": "Teeth upon the lip, and a steady stream of breath. No puff of air, which is a P.",
    "ae->e": "Open the jaw rather wider than feels dignified. CAT, not KET.",
    "o->aw": "Two vowels in one, gliding: OH-oo. Not a single flat note.",
    "t->retroflex": "The tongue tip meets the ridge behind the upper teeth, not the roof.",
    "d->retroflex": "Forward, at the ridge behind the teeth. The retroflex belongs to Hindi.",
}

OPENERS = {
    "clear": "Good morning. I have listened, and I must tell you plainly: "
             "there is a habit here, and habits are the only things worth correcting.",
    "likely": "Good morning. A pattern is emerging. Not yet a certainty, but "
              "emerging, and better attended to now than later.",
    "watch": "Good morning. Little of consequence today, which is itself a "
             "respectable result. One or two things merit an ear.",
}


def _audio_tag(path: str | None, label: str, css: str) -> str:
    data = daily.embed(path)
    if not data:
        return f'<button class="pb {css}" disabled>{label}</button>'
    return (
        f'<button class="pb {css}" data-src="{data}">{label}</button>'
    )


def _listen(day: date, anchor: str) -> str:
    """The PDF cannot play audio, so it links to the page that can."""
    page = (config.REPORTS_DIR / f"{day.isoformat()}.html").resolve().as_uri()
    # `?listen` keeps Chrome's print from turning this into a jump inside the PDF.
    return (f'<a class="listen" href="{page}?listen#{anchor}">'
            '▶ Listen: you against the correct version (opens the interactive report)</a>')


def _sureness(lower: float) -> str:
    """Plain words for a credible bound. A number nobody trusts teaches nothing."""
    if lower >= 0.15:
        return "a clear habit"
    if lower >= 0.08:
        return "likely a habit"
    return "worth watching"


def _grammar_html(habits: list[dict], name: str = "") -> str:
    """The lesson: numbered corrections, what to say instead, and why."""
    if not habits:
        return ""
    from . import grammar as _g

    def one(h: dict, spoken: bool, number: int) -> str | None:
        try:
            f = _g.GrammarFinding(**{k: v for k, v in h.items() if k != "times"})
        except TypeError:
            # One partial row used to raise straight through build_html, so a
            # single bad record cost the whole night: no HTML, therefore no PDF.
            return None
        action = html.escape(f.instruction) if f.instruction else ""
        times = int(h.get("times", 1))
        # The one word he should be able to say back when asked why it is wrong.
        label = html.escape((h.get("label") or h["kind"]).upper())
        tag = "" if (h.get("label") or h["kind"]).lower() == h["kind"].lower() else html.escape(h["kind"])
        if times > 1:
            tag += (" &middot; " if tag else "") + f"{times} times this month"
        return (
            f'<div class="item"><div class="num">{number}</div><div class="body">'
            f'<div class="tagline"><span class="label">{label}</span>{tag}</div>'
            f'<div class="said">You {"said" if spoken else "wrote"} '
            f'&ldquo;<b>{html.escape(h["said"][:120])}</b>&rdquo;</div>'
            f'<div class="say">Say &ldquo;<b>{html.escape(h["should_be"][:120])}</b>&rdquo;'
            + (f'<span class="action">{action}</span>' if action else "")
            + f'</div><div class="why">{html.escape(f.rule)}</div>'
            f'<div class="ctx">&ldquo;{html.escape(h["context"][:190])}&rdquo;</div>'
            "</div></div>"
        )

    typed_rows = [h for h in habits if h.get("mode") == "typed"]
    spoken_rows = [h for h in habits if h.get("mode") != "typed"]  # unknown modes are speech
    lead = (f'<h2 class="sect">Your lesson</h2><div class="sub2">'
            f'{html.escape(name) + ", t" if name else "T"}here '
            f'{"is one correction" if len(habits) == 1 else f"are {len(habits)} corrections"} below: '
            f'{len(spoken_rows)} from your speech, {len(typed_rows)} from your typing. '
            'Each one shows what you produced, what to produce instead, and the rule behind it.'
            "</div>")
    out = [lead]
    number = 0
    for rows, title, blurb in (
        (spoken_rows, "What you said",
         "From your dictation and reading audio, marked against the raw transcript. "
         "Listen to the recording before you accept a correction: a recogniser can mishear."),
        (typed_rows, "What you typed",
         "From what you typed into Claude Code, Codex and other apps' text boxes. Pastes, commands and tool output are excluded."),
    ):
        if not rows:
            continue
        items = []
        for h in rows:
            card = one(h, title == "What you said", number + 1)
            if card is None:
                continue
            number += 1
            items.append(card)
        if not items:
            continue
        out.append(f'<h3 class="sect">{title}</h3><div class="sub2">{blurb}</div>'
                   f'<div class="lesson">{"".join(items)}</div>')
    return "".join(out)


def _week_html(day: date) -> str:
    """Seven days against the seven before. Silent when there is nothing to say."""
    from . import progress

    try:
        summary = progress.week(day)
    except Exception:  # noqa: BLE001  a progress strip must never cost a report
        return ""
    if not summary or not summary.get("verdict"):
        return ""
    now = summary["this_week"]
    extra = []
    if summary.get("fixed"):
        extra.append("Gone since last week: <b>" + ", ".join(
            html.escape(w) for w in summary["fixed"]) + "</b>.")
    if summary.get("persisting"):
        extra.append("Still with you: <b>" + ", ".join(
            html.escape(w) for w in summary["persisting"]) + "</b>.")
    note = f'<div class="week-note">{" ".join(extra)}</div>' if extra else ""
    return (
        '<div class="week"><div class="week-head">Seven days</div>'
        f'<div class="week-body">{html.escape(summary["verdict"])}</div>'
        f'{note}'
        # Without the word count the footer reads as a contradiction under the
        # "not enough material" verdict: no material, five corrections.
        + (f'<div class="week-foot">{now["found"]} corrections across {now["days"]} '
           f'analysed day{"s" if now["days"] != 1 else ""}, {now["words"]:,} words of your own. '
           'Only days this checker read are counted.</div>' if now["words"] else "")
        + '</div>'
    )


CANDIDATE_LIMIT = 8  # how many unconfirmed sounds the page will show


def _provenance(analysis: dict) -> str:
    """Say in the report itself what left the machine. It is the honest place."""
    engine = analysis.get("grammar_engine", "")
    if not engine.endswith("-cli"):
        return ('<div class="tribute">Everything in this report was produced on this machine. '
                'Grammar came from local rules.</div>')
    return ('<div class="tribute">Pronunciation was measured on this machine and no audio left it. '
            f"Grammar was checked by the {'Codex' if engine == 'codex-cli' else 'Claude Code'} CLI "
            "already installed here, which means the day's "
            'transcript text was sent for that one call. Set MR_THAROOR_NO_LLM=1 to use local rules '
            'instead.</div>')


def build_html(findings: list, day: date, grammar: list[dict] | None = None,
               analysis: dict | None = None) -> str:
    grouped = daily.group(findings, day)
    bounds = daily.trustworthy_contrasts(findings, day)
    total = sum(len(items) for items in grouped.values())
    confirmed_ids = {id(item) for items in grouped.values() for item in items}
    candidates = [item for item in findings if id(item) not in confirmed_ids]
    rows = []
    for contrast, items in grouped.items():
        seen: set[str] = set()
        examples = []
        for finding in items:
            if finding.word in seen:
                continue
            seen.add(finding.word)
            examples.append(finding)
            if len(examples) >= 3:
                break
        if not examples:
            continue
        first = examples[0]
        blocks = "".join(
            '<div class="ab"><div class="who">'
            + (f'<div class="heard">You said <b>{html.escape((_as_heard(f.word, f.contrast) or "").upper())}</b></div>'
               f'<div class="word">The word is <b>{html.escape(f.word.upper())}</b>'
               if _as_heard(f.word, f.contrast)
               else f'<div class="word">{html.escape(f.word)}')
            + (f' <span class="ipa">{html.escape(f.ipa)}</span>' if f.ipa else "")
            + f'</div><div class="ctx">Transcript: {html.escape(f.sentence[:110])}</div>'
            + f'<div class="ctx">{"Wispr dictation" if "wispr-" in f.source else "Reading audio"} · phoneme model score {f.confidence:.0%} (not measured accuracy)</div></div>'
            + '<div class="buttons">'
            + _audio_tag(f.clip_path, "▶ You", "you")
            + _audio_tag(f.correct_path, "▶ Reference", "right")
            + "</div></div>"
            for f in examples
        )
        rows.append(
            f'<div class="card" id="s-{html.escape(contrast)}"><div class="card-head"><div class="swap">'
            f'<span class="sound-name">{html.escape(CONTRAST_NAMES.get(contrast, contrast))}</span>'
            f'<span class="arrow">/{html.escape(first.said)}/ where the word wants '
            f'/{html.escape(first.should_be)}/</span>'
            f'<span class="n">{len(items)}x &middot; {_sureness(bounds.get(contrast, 0.0))}</span></div>'
            f'<div class="words">{html.escape(TIPS.get(contrast, ""))}</div></div>'
            f"{blocks}{_listen(day, f's-{contrast}')}</div>"
        )

    body = "".join(rows)
    if not body:
        opportunities = int((analysis or {}).get("opportunities", 0))
        explanation = (
            f"The system checked {opportunities} sound opportunities, but none formed a "
            "repeatable pattern strong enough to call a mistake. This does not prove the "
            "speech was error-free; it means there is no correction the evidence can "
            "support today."
            if opportunities
            else "This may mean clear speech, too little audio, or uncertain recognition."
        )
        body = (
            '<div class="card"><div class="card-head"><div class="words">'
            f"No pronunciation pattern passed the evidence checks. {explanation}"
            "</div></div></div>"
        )
    candidate_cards = []
    for number, finding in enumerate(candidates[:CANDIDATE_LIMIT]):
        sentence = html.escape(finding.sentence[:360])
        if len(finding.sentence) > 360:
            sentence += "…"
        source = "Wispr dictation" if "wispr-" in finding.source else "Reading audio"
        ipa = f' <span class="ipa">{html.escape(finding.ipa)}</span>' if finding.ipa else ""
        heard = _as_heard(finding.word, finding.contrast)
        headline = (f'<span class="bad">{html.escape(heard.upper())}</span>'
                    '<span class="arrow"> heard; the word is </span>'
                    f'<span class="good">{html.escape(finding.word.upper())}</span>'
                    if heard else
                    f'<span class="bad">/{html.escape(finding.said)}/</span>'
                    '<span class="arrow"> heard; expected </span>'
                    f'<span class="good">/{html.escape(finding.should_be)}/</span>')
        candidate_cards.append(
            f'<div class="candidate-card" id="c-{number}">'
            '<div class="candidate-head"><div>'
            + headline
            + f'<div class="candidate-word">{html.escape(finding.word)}{ipa}</div>'
            '</div><span class="candidate-tag">candidate · not confirmed</span></div>'
            f'<div class="words">{html.escape(CONTRAST_NAMES.get(finding.contrast, finding.contrast))}'
            f' · confidence {finding.confidence:.0%} · audio quality {finding.quality:.0%} · {source}</div>'
            f'<div class="candidate-transcript">“{sentence}”</div>'
            + '<div class="buttons">'
            + _audio_tag(finding.clip_path, "▶ You", "you")
            + _audio_tag(finding.correct_path, "▶ Said properly", "right")
            + '</div>' + _listen(day, f"c-{number}")
            + '<div class="candidate-foot">Your own voice against a human recording. '
            'The evidence does not yet call this a habit, so listen and judge it yourself.</div>'
            '</div>'
        )
    candidate_html = (
        '<div class="candidate-group"><h2 class="sect">Worth another listen</h2>'
        '<div class="sub2">Possible pronunciation signals that did not yet meet the evidence threshold. '
        'They are deliberately not labelled as mistakes.</div>'
        + "".join(candidate_cards)
        + '</div>'
        if candidate_cards else ""
    )
    best = max((bounds[c] for c in grouped), default=0.0)
    mood = "clear" if best >= 0.15 else ("likely" if best >= 0.08 else "watch")
    name = config.user_name()
    greeting = f"Good morning, {name}."
    lesson_count = len(grammar or [])
    if grouped:
        remark = OPENERS[mood]
    elif lesson_count:
        remark = (
            f"Your sounds gave me nothing I can prove today, which is not at all the same as "
            f"nothing to say. Your phrasing gave me {lesson_count}, and phrasing is the half a "
            "listener notices first. They are set out below, in order."
        )
    else:
        remark = ("Neither your sounds nor your phrasing produced anything I am willing to call "
                  "a mistake today. Rest on it; I shall be listening again tomorrow.")
    clips = sum(bool(item.clip_path) for item in findings)
    quality_values = [item.quality for item in findings if item.quality is not None]
    quality = (sum(quality_values) / len(quality_values)) if quality_values else None
    quality_value = f"{quality:.0%}" if quality is not None else "&mdash;"
    quality_note = "average signal quality" if quality is not None else "no qualifying examples"
    typed_rows = sum(1 for row in (grammar or []) if row.get("mode") == "typed")
    spoken_rows = len(grammar or []) - typed_rows
    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="stat-label">SOUNDS TO FIX</div><div class="stat-value">{len(grouped)}</div>'
        '<div class="stat-note">confirmed patterns</div></div>'
        f'<div class="stat"><div class="stat-label">GRAMMAR TO FIX</div><div class="stat-value">{len(grammar or [])}</div>'
        f'<div class="stat-note">{spoken_rows} said &middot; {typed_rows} typed</div></div>'
        f'<div class="stat"><div class="stat-label">CLIPS TO HEAR</div><div class="stat-value">{clips}</div>'
        '<div class="stat-note">voice clips available</div></div>'
        f'<div class="stat"><div class="stat-label">EVIDENCE QUALITY</div><div class="stat-value">{quality_value}</div>'
        f'<div class="stat-note">{quality_note}</div></div>'
        '</div>'
    )
    summary = ""
    if analysis is not None:
        sources = analysis.get("sources", {})
        wispr_count = int(sources.get("wispr", 0))
        own_count = int(sources.get("own", 0))
        candidate_count = int(analysis.get("candidates", 0))
        completed = str(analysis.get("completed_at", ""))
        try:
            generated = datetime.fromisoformat(completed).strftime("%d %B %Y at %H:%M")
        except ValueError:
            generated = completed or "time unavailable"
        summary = (
            '<div class="card"><div class="card-head">'
            '<strong>Processing summary</strong><div class="words">'
            f'{wispr_count} Wispr recording{"s" if wispr_count != 1 else ""}, '
            f'{own_count} reading recording{"s" if own_count != 1 else ""} and '
            f'{int(sources.get("typed", 0))} typed message{"s" if int(sources.get("typed", 0)) != 1 else ""} '
            f'read; {int(analysis.get("opportunities", 0))} sound opportunities checked. '
            f'{candidate_count} tentative candidate{"s" if candidate_count != 1 else ""}; '
            f'{total} examples passed the evidence checks.</div>'
            f'<div class="words">Generated {html.escape(generated)}'
            ' (local time).'
            + (' This is a partial-day report; analysis will run again after the day ends.'
               if str(analysis.get("completed_at", ""))[:10] == str(day) else '')
            + '</div></div></div>'
        )
    return (
        # Keep an explicit empty state: an absent section looks like a broken
        # report, whereas this makes clear that grammar was checked too.
        TEMPLATE.replace("{{GREETING}}", html.escape(greeting))
        .replace("{{DATE}}", day.strftime("%A %d %B %Y"))
        .replace("{{TOTAL}}", str(total))
        .replace("{{SOUNDS}}", str(len(grouped)))
        .replace("{{STATS}}", stats)
        .replace("{{CARDS}}", body)
        .replace("{{CANDIDATES}}", candidate_html)
        .replace("{{SUMMARY}}", summary)
        .replace("{{GRAMMAR}}", _grammar_html(grammar or [], name) or (
            '<h2 class="sect">Your lesson</h2>'
            '<div class="card"><div class="card-head"><div class="words">'
            'Nothing was marked in what you said or typed. '
            'Either the day was clean, or there was too little of it to read.'
            '</div></div></div>'
        ))
        .replace("{{PORTRAIT}}", PORTRAIT)
        .replace("{{WEEK}}", _week_html(day))
        .replace("{{PROVENANCE}}", _provenance(analysis or {}))
        .replace("{{REMARK}}", html.escape(remark))
    )


def write(findings: list, day: date | None = None, grammar: list[dict] | None = None,
          analysis: dict | None = None) -> dict[str, str]:
    """The day's page."""
    day = day or date.today()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = config.REPORTS_DIR / f"{day.isoformat()}.html"
    html_path.write_text(build_html(findings, day, grammar, analysis), encoding="utf-8")
    return {"html": str(html_path)}


def repair_exports(day: date, analysis: dict) -> bool:
    """Rebuild a missing page from saved results without decoding audio again."""
    html_path = config.REPORTS_DIR / f"{day}.html"
    if html_path.exists():
        return True
    if not (config.REPORTS_DIR / f"{day}.json").exists():
        return False
    grammar_path = config.REPORTS_DIR / f"{day}-grammar.json"
    grammar = json.loads(grammar_path.read_text()) if grammar_path.exists() else []
    written = write(daily.load(day), day, grammar=grammar, analysis=analysis)
    analysis["outputs"] = sorted(written)
    config.write_json_atomically(config.REPORTS_DIR / f"{day}-analysis.json", analysis)
    return html_path.exists()


def open_report(day: date | None = None) -> str | None:
    """Open the day's page in the browser."""
    day = day or date.today()
    html_path = config.REPORTS_DIR / f"{day.isoformat()}.html"
    if not html_path.exists():
        return None
    try:
        if subprocess.run(["open", str(html_path)], capture_output=True).returncode == 0:
            return str(html_path)
    except OSError:
        pass
    return None


def latest_day(before: date | None = None) -> date | None:
    """Most recent completed report before today, even after a weekend away."""
    import json

    before = before or date.today()
    for marker in sorted(config.REPORTS_DIR.glob("*-analysis.json"), reverse=True):
        try:
            day = date.fromisoformat(marker.name[:10])
            version = json.loads(marker.read_text()).get("version", 0)
        except (ValueError, TypeError):
            continue
        if day < before and version >= daily.ANALYSIS_VERSION and marker.with_name(f"{day}.html").exists():
            return day
    return None


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<title>Mr Tharoor - {{DATE}}</title><style>
/* A lesson sheet, not a dashboard. Light paper because this is printed and
   read; serif because it is a teacher's page. Fonts are the ones macOS
   already has, so the file stays offline and self-contained. */
:root{--paper:#FBFAF6;--card:#FFFFFF;--ink:#191917;--ink2:#46463F;--muted:#7C7A70;
--rule:#E3DED1;--rule2:#CFC8B6;--wrong:#A33227;--right:#1F5C46;--mark:#1F3A5F;
--wash:#F3EFE4;--gold:#8A6A1F;--goldwash:#FBF4E2}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);margin:0;padding:34px 20px 72px;
font:16.5px/1.62 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
.wrap{max-width:720px;margin:0 auto}
.masthead{border-bottom:2px solid var(--ink);padding-bottom:10px;margin-bottom:3px;
display:flex;align-items:center;gap:18px}
.portrait{width:76px;height:76px;color:var(--ink);flex:none;margin-bottom:2px}
h1{font-size:2.15rem;margin:0;letter-spacing:.005em;font-weight:600}
.rule-thin{border-bottom:1px solid var(--rule2);margin-bottom:20px;height:3px}
.greet{font-size:1.06rem;color:var(--mark);margin:16px 0 2px;font-weight:600}
.sub{color:var(--muted);font-size:.84rem;font-family:-apple-system,BlinkMacSystemFont,sans-serif;
letter-spacing:.02em;margin-bottom:18px}
.remark{font-style:italic;color:var(--ink2);font-size:1rem;line-height:1.6;margin:8px 0 20px;
padding-left:16px;border-left:3px solid var(--rule2);max-width:62ch}
.sect{font-size:1.3rem;margin:34px 0 4px;font-weight:600;letter-spacing:.005em}
.sect:after{content:"";display:block;width:56px;border-bottom:2px solid var(--ink);margin-top:7px}
.sub2{color:var(--muted);font-size:.85rem;margin:10px 0 16px;max-width:62ch;font-style:italic}

/* the day in four numbers */
.stats{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--rule2);
border-bottom:1px solid var(--rule2);margin:18px 0 26px}
.stat{padding:14px 16px 13px;border-right:1px solid var(--rule)}.stat:last-child{border-right:0}
.stat-label{font:600 .62rem/1.2 -apple-system,BlinkMacSystemFont,sans-serif;color:var(--muted);
letter-spacing:.12em;text-transform:uppercase}
.stat-value{font-size:1.9rem;line-height:1.15;margin-top:5px}
.stat-note{font:.7rem/1.4 -apple-system,BlinkMacSystemFont,sans-serif;color:var(--muted);margin-top:4px}

/* the lesson: one numbered correction at a time */
.lesson{counter-reset:item}
.item{display:grid;grid-template-columns:36px 1fr;gap:14px;padding:16px 0;
border-bottom:1px solid var(--rule);break-inside:avoid}
.item:last-child{border-bottom:0}
.num{font:600 .9rem/28px -apple-system,BlinkMacSystemFont,sans-serif;text-align:center;
width:28px;height:28px;border:1px solid var(--rule2);border-radius:50%;color:var(--muted);
background:var(--card)}
.said{font-size:1.06rem;color:var(--wrong)}
.said b{font-weight:600;text-decoration:line-through;text-decoration-thickness:1px;
text-decoration-color:rgba(163,50,39,.55)}
.say{font-size:1.14rem;color:var(--right);margin-top:4px}.say b{font-weight:700}
.why{font-size:.9rem;color:var(--ink2);font-style:italic;margin-top:6px}
.tagline{font:.64rem/1 -apple-system,BlinkMacSystemFont,sans-serif;color:var(--muted);
letter-spacing:.11em;text-transform:uppercase;margin:4px 0 8px}
.label{font:700 .68rem/1 -apple-system,BlinkMacSystemFont,sans-serif;color:var(--mark);
background:var(--wash);border:1px solid #DCD5C2;padding:4px 8px;border-radius:2px;
letter-spacing:.09em;margin-right:9px}
.heard{font-size:1.06rem;color:var(--wrong);margin-bottom:2px}
.heard b{font-weight:700;letter-spacing:.03em}
.word b{color:var(--right);letter-spacing:.03em}
.sound-name{font-size:1.15rem;font-weight:600}
.ctx{font-size:.84rem;color:var(--muted);margin-top:8px;padding-left:12px;
border-left:2px solid var(--rule);line-height:1.55}
.action{display:inline-block;font:600 .7rem/1 -apple-system,BlinkMacSystemFont,sans-serif;
color:var(--mark);background:var(--wash);padding:5px 9px;border-radius:2px;margin-left:10px;
letter-spacing:.03em;vertical-align:middle}

/* pronunciation: a sound, then your voice against a proper one */
.card{background:var(--card);border:1px solid var(--rule);margin-bottom:14px;break-inside:avoid}
.card-head{padding:15px 18px;border-bottom:1px solid var(--rule);background:var(--wash)}
.swap{font-size:1.3rem;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.bad{color:var(--wrong);font-weight:700}.good{color:var(--right);font-weight:700}
.arrow{color:var(--muted);font:.72rem/1 -apple-system,sans-serif;letter-spacing:.06em;text-transform:uppercase}
.n{margin-left:auto;color:var(--muted);font:.72rem/1 -apple-system,sans-serif}
.words{font-size:.87rem;color:var(--ink2);margin-top:7px;line-height:1.5}
.ab{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center;padding:13px 18px;
border-bottom:1px solid var(--rule)}.ab:last-child{border-bottom:0}
.word{font-size:1.1rem;font-weight:600}
.ipa{color:var(--muted);font-size:.86rem;font-weight:400}
.buttons{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.pb{border:1px solid var(--rule2);background:var(--card);border-radius:999px;padding:7px 14px;
font:.8rem -apple-system,BlinkMacSystemFont,sans-serif;cursor:pointer;color:var(--ink2)}
.pb.you{border-color:var(--wrong);color:var(--wrong)}
.pb.right{border-color:var(--right);color:var(--right)}
.pb[disabled]{opacity:.35;cursor:not-allowed}
.listen{display:none}
.candidate-card{background:var(--goldwash);border:1px solid #E2D2A8;border-left:3px solid var(--gold);
padding:16px 18px;margin-bottom:12px;break-inside:avoid}
.candidate-group{break-inside:avoid}
.candidate-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.candidate-word{font-size:1.14rem;font-weight:600;margin-top:5px}
.candidate-tag{font:.66rem/1 -apple-system,sans-serif;color:var(--gold);border:1px solid #E2D2A8;
border-radius:999px;padding:5px 9px;white-space:nowrap;text-transform:uppercase;letter-spacing:.08em}
.candidate-transcript{font-size:.86rem;color:var(--ink2);line-height:1.6;border-top:1px solid #E7DCBF;
border-bottom:1px solid #E7DCBF;padding:11px 0;margin-top:11px}
.candidate-foot{font:.74rem/1.5 -apple-system,sans-serif;color:var(--muted);margin-top:10px}
.candidate-card .buttons{justify-content:flex-start;margin-top:12px}
.week{border:1px solid var(--rule2);border-left:3px solid var(--mark);background:var(--card);
padding:15px 18px;margin:0 0 26px;break-inside:avoid}
.week-head{font:700 .64rem/1 -apple-system,BlinkMacSystemFont,sans-serif;color:var(--mark);
letter-spacing:.14em;text-transform:uppercase;margin-bottom:7px}
.week-body{font-size:1.02rem;line-height:1.55}
.week-note{font-size:.88rem;color:var(--ink2);margin-top:7px}
.week-note b{color:var(--mark);font-weight:600}
.week-foot{font:.72rem/1.5 -apple-system,BlinkMacSystemFont,sans-serif;color:var(--muted);margin-top:8px}
.tribute{font-size:.76rem;color:var(--muted);line-height:1.6;margin-top:30px;padding-top:14px;
border-top:1px solid var(--rule)}
@media(max-width:620px){.ab{grid-template-columns:1fr}.buttons{justify-content:flex-start}
.stats{grid-template-columns:repeat(2,1fr)}.stat:nth-child(2){border-right:0}
.stat:nth-child(-n+2){border-bottom:1px solid var(--rule)}
.item{grid-template-columns:28px 1fr;gap:10px}}
@page{margin:16mm 15mm}
@media print{*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.pb{display:none}.listen{display:inline-block;margin-top:8px;color:var(--right);font-weight:600}body{padding:0 0 12px;font-size:11.5pt}.wrap{max-width:none}
.sect{break-after:avoid}.card,.item{break-inside:avoid}}
</style></head><body><div class="wrap">
<div class="masthead">{{PORTRAIT}}<h1>Mr Tharoor</h1></div><div class="rule-thin"></div>
<div class="sub">{{DATE}} &middot; a lesson made from what you said and what you wrote</div>
<div class="greet">{{GREETING}}</div>
<div class="remark">{{REMARK}}</div>
{{STATS}}
{{WEEK}}
{{GRAMMAR}}
<h2 class="sect">Pronunciation</h2>
{{CARDS}}
{{CANDIDATES}}
{{SUMMARY}}
{{PROVENANCE}}
<div class="tribute">Mr Tharoor is a fictional mascot, named in tribute to Dr Shashi Tharoor.
This software is not affiliated with, endorsed by, or connected to him. Every word it speaks
was written for this program.</div>
</div><script>
var playing=null;
document.addEventListener('click',function(e){
  var b=e.target.closest('.pb[data-src]'); if(!b)return;
  if(playing){playing.pause();playing=null;}
  playing=new Audio(b.getAttribute('data-src')); playing.play();
});
</script></body></html>"""
