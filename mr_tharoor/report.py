"""Turn a day's findings into the page that opens at 08:30.

The page is deliberately one self-contained file. Audio is embedded rather
than linked, so it keeps working when the clips are deleted three days later,
and it can be sent to someone or kept forever without dragging a folder along.

Three formats out of one template, all local:

    HTML   the real one, because it is the only one that can play sound
    PDF    headless Chromium, already on this machine
    DOCX   textutil, which ships with macOS

PDF and Word are for keeping and sharing. Neither can play a recording, so the
morning job opens both the PDF in Preview and the interactive HTML review.
"""

from __future__ import annotations

import base64
import html
import json
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path

from . import config, daily

def _find_chromium() -> Path | None:
    """Find a local headless browser without pinning one Playwright revision."""
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    candidates = sorted(
        cache.glob("chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell"),
        reverse=True,
    )
    candidates += [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    return next((path for path in candidates if path.is_file() and path.stat().st_mode & 0o111), None)


CHROMIUM = _find_chromium()

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

    def one(h: dict, spoken: bool, number: int) -> str:
        f = _g.GrammarFinding(**{k: v for k, v in h.items() if k != "times"})
        action = html.escape(f.instruction) if f.instruction else ""
        times = int(h.get("times", 1))
        tag = html.escape(h["kind"])
        if times > 1:
            tag += f" &middot; {times} times this month"
        return (
            f'<div class="item"><div class="num">{number}</div><div class="body">'
            f'<div class="tagline">{tag}</div>'
            f'<div class="said">You {"said" if spoken else "wrote"} '
            f'&ldquo;<b>{html.escape(h["said"])}</b>&rdquo;</div>'
            f'<div class="say">Say &ldquo;<b>{html.escape(h["should_be"])}</b>&rdquo;'
            + (f'<span class="action">{action}</span>' if action else "")
            + f'</div><div class="why">{html.escape(f.rule)}</div>'
            f'<div class="ctx">&ldquo;{html.escape(h["context"][:190])}&rdquo;</div>'
            "</div></div>"
        )

    spoken_rows = [h for h in habits if (h.get("mode") or "spoken") == "spoken"]
    typed_rows = [h for h in habits if h.get("mode") == "typed"]
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
         "From what you typed into Claude Code. Pastes, commands and tool output are excluded."),
    ):
        if not rows:
            continue
        items = []
        for h in rows:
            number += 1
            items.append(one(h, title == "What you said", number))
        out.append(f'<h3 class="sect">{title}</h3><div class="sub2">{blurb}</div>'
                   f'<div class="lesson">{"".join(items)}</div>')
    return "".join(out)


def _provenance(analysis: dict) -> str:
    """Say in the report itself what left the machine. It is the honest place."""
    if analysis.get("grammar_engine") != "claude-cli":
        return ('<div class="tribute">Everything in this report was produced on this machine. '
                'Grammar came from local rules.</div>')
    return ('<div class="tribute">Pronunciation was measured on this machine and no audio left it. '
            "Grammar was checked by the Claude Code CLI already installed here, which means the day's "
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
            f'<div class="ab"><div class="who"><div class="word">{html.escape(f.word)}'
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
            f'<div class="card"><div class="card-head"><div class="swap">'
            f'<span class="bad">/{html.escape(first.said)}/</span>'
            f'<span class="arrow">detected → reference</span>'
            f'<span class="good">/{html.escape(first.should_be)}/</span>'
            f'<span class="n">{len(items)}x &middot; {_sureness(bounds.get(contrast, 0.0))}</span></div>'
            f'<div class="words">{CONTRAST_NAMES.get(contrast, contrast)}'
            f' &middot; {html.escape(TIPS.get(contrast, ""))}</div></div>'
            f"{blocks}</div>"
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
    for finding in candidates[:8]:
        sentence = html.escape(finding.sentence[:360])
        if len(finding.sentence) > 360:
            sentence += "…"
        source = "Wispr dictation" if "wispr-" in finding.source else "Reading audio"
        ipa = f' <span class="ipa">{html.escape(finding.ipa)}</span>' if finding.ipa else ""
        candidate_cards.append(
            '<div class="candidate-card">'
            '<div class="candidate-head"><div>'
            f'<span class="bad">/{html.escape(finding.said)}/</span>'
            '<span class="arrow"> heard; expected </span>'
            f'<span class="good">/{html.escape(finding.should_be)}/</span>'
            f'<div class="candidate-word">{html.escape(finding.word)}{ipa}</div>'
            '</div><span class="candidate-tag">candidate · not confirmed</span></div>'
            f'<div class="words">{html.escape(CONTRAST_NAMES.get(finding.contrast, finding.contrast))}'
            f' · confidence {finding.confidence:.0%} · audio quality {finding.quality:.0%} · {source}</div>'
            f'<div class="candidate-transcript">“{sentence}”</div>'
            '<div class="candidate-foot">A single or low-frequency signal is shown for review; '
            'listen to the clip in the HTML report before practising.</div>'
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
    spoken_rows = sum(1 for row in (grammar or []) if (row.get("mode") or "spoken") == "spoken")
    typed_rows = sum(1 for row in (grammar or []) if row.get("mode") == "typed")
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
        .replace("{{PROVENANCE}}", _provenance(analysis or {}))
        .replace("{{REMARK}}", html.escape(remark))
    )


def valid_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return path.stat().st_size > 1000 and stream.read(5) == b"%PDF-"
    except OSError:
        return False


def write(findings: list, day: date | None = None, grammar: list[dict] | None = None,
          analysis: dict | None = None) -> dict[str, str]:
    """HTML always; PDF and Word when their tools are present."""
    day = day or date.today()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = config.REPORTS_DIR / f"{day.isoformat()}.html"
    from . import log

    logger = log.get("report")
    html_path.write_text(build_html(findings, day, grammar, analysis), encoding="utf-8")
    out = {"html": str(html_path)}

    if CHROMIUM is not None:
        pdf = html_path.with_suffix(".pdf")
        # Chromium's macOS headless helper can fail before startup when the
        # session cannot register its Mach rendezvous service. Single-process
        # mode avoids that crash and still renders this local, self-contained
        # page. Try the normal mode first, then the compatible fallback.
        with tempfile.TemporaryDirectory(prefix=".pdf-", dir=config.REPORTS_DIR) as scratch:
            temporary = Path(scratch) / pdf.name
            base = [str(CHROMIUM), "--headless", "--no-sandbox", "--disable-gpu",
                    "--disable-dev-shm-usage", "--no-pdf-header-footer",
                    f"--user-data-dir={Path(scratch) / 'profile'}",
                    f"--print-to-pdf={temporary}", html_path.resolve().as_uri()]
            for extra in ([], ["--single-process"]):
                temporary.unlink(missing_ok=True)
                try:
                    result = subprocess.run(base[:1] + extra + base[1:],
                                            capture_output=True, timeout=120)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    logger.warning("PDF export attempt failed: %s", type(exc).__name__)
                    continue
                if result.returncode == 0 and valid_pdf(temporary):
                    temporary.replace(pdf)
                    out["pdf"] = str(pdf)
                    break
        if "pdf" not in out:
            logger.warning("PDF export failed for %s; keeping any previous PDF and retrying later", day)
    else:
        logger.warning("PDF export unavailable: install Google Chrome or a Playwright Chromium browser")

    docx = html_path.with_suffix(".docx")
    if shutil.which("textutil"):
        try:
            result = subprocess.run(
                ["textutil", "-convert", "docx", str(html_path), "-output", str(docx)],
                capture_output=True, timeout=30,
            )
            if result.returncode == 0 and docx.exists():
                out["docx"] = str(docx)
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("Optional Word export failed for %s", day)
    return out


def repair_exports(day: date, analysis: dict) -> bool:
    """Retry a missing/failed export from saved results without decoding audio again."""
    html_path = config.REPORTS_DIR / f"{day}.html"
    if (html_path.exists() and valid_pdf(html_path.with_suffix(".pdf"))
            and "pdf" in analysis.get("outputs", ["pdf"])):
        return True
    if not (config.REPORTS_DIR / f"{day}.json").exists():
        return False
    grammar_path = config.REPORTS_DIR / f"{day}-grammar.json"
    grammar = json.loads(grammar_path.read_text()) if grammar_path.exists() else []
    written = write(daily.load(day), day, grammar=grammar, analysis=analysis)
    analysis["outputs"] = sorted(written)
    config.write_json_atomically(config.REPORTS_DIR / f"{day}-analysis.json", analysis)
    return "pdf" in written


def open_report(day: date | None = None) -> str | None:
    """Open the interactive review, then put its PDF visibly in front.

    `open` returning zero only means LaunchServices accepted the request.  An
    HTML tab can land behind an existing browser window and look as though the
    morning job did nothing.  Preview is a distinct, visible destination and
    is also the durable report the user expects to receive each morning.
    """
    day = day or date.today()
    html_path = config.REPORTS_DIR / f"{day.isoformat()}.html"
    if not html_path.exists():
        return None

    opened_html = False
    try:
        opened_html = subprocess.run(
            ["open", str(html_path)], capture_output=True
        ).returncode == 0
    except OSError:
        pass

    pdf_path = html_path.with_suffix(".pdf")
    if valid_pdf(pdf_path):
        try:
            result = subprocess.run(
                ["open", "-a", "Preview", str(pdf_path)], capture_output=True
            )
            if result.returncode == 0:
                return str(pdf_path)
        except OSError:
            pass
    return str(html_path) if opened_html else None


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
.masthead{border-bottom:2px solid var(--ink);padding-bottom:8px;margin-bottom:3px}
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
letter-spacing:.11em;text-transform:uppercase;margin:4px 0 7px}
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
.tribute{font-size:.76rem;color:var(--muted);line-height:1.6;margin-top:30px;padding-top:14px;
border-top:1px solid var(--rule)}
@media(max-width:620px){.ab{grid-template-columns:1fr}.buttons{justify-content:flex-start}
.stats{grid-template-columns:repeat(2,1fr)}.stat:nth-child(2){border-right:0}
.stat:nth-child(-n+2){border-bottom:1px solid var(--rule)}
.item{grid-template-columns:28px 1fr;gap:10px}}
@page{margin:16mm 15mm}
@media print{*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.pb{display:none}body{padding:0 0 12px;font-size:11.5pt}.wrap{max-width:none}
.sect{break-after:avoid}.card,.item{break-inside:avoid}}
</style></head><body><div class="wrap">
<div class="masthead"><h1>Mr Tharoor</h1></div><div class="rule-thin"></div>
<div class="sub">{{DATE}} &middot; a lesson made from what you said and what you wrote</div>
<div class="greet">{{GREETING}}</div>
<div class="remark">{{REMARK}}</div>
{{STATS}}
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
