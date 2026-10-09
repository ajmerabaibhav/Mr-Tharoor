"""Turn a day's corrections into the page that opens at 08:30.

The page is deliberately one self-contained file, so it works offline and can
be sent to someone without dragging a folder along. Old pages are deleted by
config.purge_expired.
"""

from __future__ import annotations

import html
import json
import subprocess
from datetime import date, datetime

from . import config

# Bumped when the saved layout changes, so older days are rebuilt rather than misread.
ANALYSIS_VERSION = 2

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


# Mr Tharoor is an old-school Indian professor of English: courteous, exacting,
# fond of a long word where a long word is warranted, and entirely without
# condescension. He corrects the way a good teacher does, by showing you the
# thing and trusting you to hear it.
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
         "From your Wispr Flow dictation, marked against the raw transcript. "
         "A recogniser can mishear, so trust your memory of the sentence over the transcript."),
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


def _provenance(analysis: dict) -> str:
    """Say in the report itself what left the machine. It is the honest place."""
    engine = analysis.get("grammar_engine", "")
    if not engine.endswith("-cli"):
        return ('<div class="tribute">Everything in this report was produced on this machine. '
                'Grammar came from local rules.</div>')
    return ('<div class="tribute">'
            f"Grammar was checked by the {'Codex' if engine == 'codex-cli' else 'Claude Code'} CLI "
            "already installed here, which means the day's "
            'transcript text was sent for that one call. Set MR_THAROOR_NO_LLM=1 to use local rules '
            'instead.</div>')


def build_html(day: date, grammar: list[dict] | None = None, analysis: dict | None = None) -> str:
    grammar = grammar or []
    name = config.user_name()
    greeting = f"Good morning, {name}."
    if grammar:
        remark = (f"Your phrasing gave me {len(grammar)} thing{'s' if len(grammar) != 1 else ''} to "
                  "set right, and phrasing is what a listener notices first. They are set out below, in order.")
    else:
        remark = ("Nothing in your phrasing today that I am willing to call a mistake. "
                  "Rest on it; I shall be reading again tomorrow.")
    typed_rows = sum(1 for row in grammar if row.get("mode") == "typed")
    spoken_rows = len(grammar) - typed_rows
    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="stat-label">CORRECTIONS</div><div class="stat-value">{len(grammar)}</div>'
        '<div class="stat-note">on this page</div></div>'
        f'<div class="stat"><div class="stat-label">FROM SPEECH</div><div class="stat-value">{spoken_rows}</div>'
        '<div class="stat-note">Wispr Flow dictation</div></div>'
        f'<div class="stat"><div class="stat-label">FROM TYPING</div><div class="stat-value">{typed_rows}</div>'
        '<div class="stat-note">chats and text boxes</div></div>'
        '</div>'
    )
    summary = ""
    if analysis is not None:
        sources = analysis.get("sources", {})
        wispr_count = int(sources.get("wispr", 0))
        typed_count = int(sources.get("typed", 0))
        completed = str(analysis.get("completed_at", ""))
        try:
            generated = datetime.fromisoformat(completed).strftime("%d %B %Y at %H:%M")
        except ValueError:
            generated = completed or "time unavailable"
        summary = (
            '<div class="card"><div class="card-head">'
            '<strong>Processing summary</strong><div class="words">'
            f'{wispr_count} dictation{"s" if wispr_count != 1 else ""} and '
            f'{typed_count} typed message{"s" if typed_count != 1 else ""} read.</div>'
            f'<div class="words">Generated {html.escape(generated)}'
            ' (local time).'
            + (' This is a partial-day report; analysis will run again after the day ends.'
               if completed[:10] == str(day) else '')
            + '</div></div></div>'
        )
    return (
        # Keep an explicit empty state: an absent section looks like a broken report.
        TEMPLATE.replace("{{GREETING}}", html.escape(greeting))
        .replace("{{DATE}}", day.strftime("%A %d %B %Y"))
        .replace("{{STATS}}", stats)
        .replace("{{SUMMARY}}", summary)
        .replace("{{GRAMMAR}}", _grammar_html(grammar, name) or (
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


def write(day: date | None = None, grammar: list[dict] | None = None,
          analysis: dict | None = None) -> dict[str, str]:
    """The day's page."""
    day = day or date.today()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = config.REPORTS_DIR / f"{day.isoformat()}.html"
    html_path.write_text(build_html(day, grammar, analysis), encoding="utf-8")
    return {"html": str(html_path)}


def repair_exports(day: date, analysis: dict) -> bool:
    """Rebuild a missing page from saved results without checking the day again."""
    html_path = config.REPORTS_DIR / f"{day}.html"
    if html_path.exists():
        return True
    grammar_path = config.REPORTS_DIR / f"{day}-grammar.json"
    if not grammar_path.exists():
        return False
    written = write(day, grammar=json.loads(grammar_path.read_text()), analysis=analysis)
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
    before = before or date.today()
    for marker in sorted(config.REPORTS_DIR.glob("*-analysis.json"), reverse=True):
        try:
            day = date.fromisoformat(marker.name[:10])
            version = json.loads(marker.read_text()).get("version", 0)
        except (ValueError, TypeError):
            continue
        if day < before and version >= ANALYSIS_VERSION and marker.with_name(f"{day}.html").exists():
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

/* the day in three numbers */
.stats{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--rule2);
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
.ctx{font-size:.84rem;color:var(--muted);margin-top:8px;padding-left:12px;
border-left:2px solid var(--rule);line-height:1.55}
.action{display:inline-block;font:600 .7rem/1 -apple-system,BlinkMacSystemFont,sans-serif;
color:var(--mark);background:var(--wash);padding:5px 9px;border-radius:2px;margin-left:10px;
letter-spacing:.03em;vertical-align:middle}

.card{background:var(--card);border:1px solid var(--rule);margin-bottom:14px;break-inside:avoid}
.card-head{padding:15px 18px;border-bottom:1px solid var(--rule);background:var(--wash)}
.words{font-size:.87rem;color:var(--ink2);margin-top:7px;line-height:1.5}
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
@media(max-width:620px){.item{grid-template-columns:28px 1fr;gap:10px}}
@page{margin:16mm 15mm}
@media print{*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{padding:0 0 12px;font-size:11.5pt}.wrap{max-width:none}
.sect{break-after:avoid}.card,.item{break-inside:avoid}}
</style></head><body><div class="wrap">
<div class="masthead">{{PORTRAIT}}<h1>Mr Tharoor</h1></div><div class="rule-thin"></div>
<div class="sub">{{DATE}} &middot; a lesson made from what you said and what you wrote</div>
<div class="greet">{{GREETING}}</div>
<div class="remark">{{REMARK}}</div>
{{STATS}}
{{WEEK}}
{{GRAMMAR}}
{{SUMMARY}}
{{PROVENANCE}}
<div class="tribute">Mr Tharoor is a fictional mascot, named in tribute to Dr Shashi Tharoor.
This software is not affiliated with, endorsed by, or connected to him. Every word it speaks
was written for this program.</div>
</div></body></html>"""
