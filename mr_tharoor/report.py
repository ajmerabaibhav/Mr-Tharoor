"""Turn a day's findings into the page that opens at 08:30.

The page is deliberately one self-contained file. Audio is embedded rather
than linked, so it keeps working when the clips are deleted three days later,
and it can be sent to someone or kept forever without dragging a folder along.

Three formats out of one template, all local:

    HTML   the real one, because it is the only one that can play sound
    PDF    headless Chromium, already on this machine
    DOCX   textutil, which ships with macOS

PDF and Word are for keeping and sharing. Neither can play a recording, which
is the whole product, so HTML is what actually opens in the morning.
"""

from __future__ import annotations

import base64
import html
import subprocess
from datetime import date
from pathlib import Path

from . import config, daily

CHROMIUM = (
    Path.home()
    / "Library/Caches/ms-playwright/chromium_headless_shell-1234"
    / "chrome-headless-shell-mac-arm64/chrome-headless-shell"
)

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


def _grammar_html(habits: list[dict]) -> str:
    if not habits:
        return ""
    from . import grammar as _g

    def one(h: dict) -> str:
        f = _g.GrammarFinding(**{k: v for k, v in h.items() if k != "times"})
        action = html.escape(f.instruction) if f.instruction else ""
        return (
            '<div class="ab"><div class="who">'
            f'<div class="word">transcript: &ldquo;{html.escape(h["said"])}&rdquo;</div>'
            + (f'<div class="action">{action}</div>' if action else "")
            + f'<div class="fix">&ldquo;<b>{html.escape(h["should_be"])}</b>&rdquo;'
            f'<span class="kind">{html.escape(h["kind"])} &middot; {h["times"]}x</span></div>'
            f'<div class="rule">{html.escape(f.rule)}</div>'
            f'<div class="ctx">&ldquo;{html.escape(h["context"][:120])}&rdquo;</div>'
            "</div></div>"
        )

    items = "".join(one(h) for h in habits)
    return (
        '<h2 class="sect">Phrasing</h2>'
        '<div class="sub2">Repeated suggestions from local rules or your own edits. Check the transcript against what you actually said before practising.</div>'
        f'<div class="card">{items}</div>'
    )


def build_html(findings: list, day: date, grammar: list[dict] | None = None) -> str:
    grouped = daily.group(findings, day)
    bounds = daily.trustworthy_contrasts(findings, day)
    total = sum(len(items) for items in grouped.values())
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

    body = "".join(rows) or (
        '<div class="card"><div class="card-head"><div class="words">'
        "No pronunciation pattern passed the evidence checks. This may mean clear speech, "
        "too little audio, or uncertain recognition.</div></div></div>"
    )
    best = max((bounds[c] for c in grouped), default=0.0)
    mood = "clear" if best >= 0.15 else ("likely" if best >= 0.08 else "watch")
    name = config.user_name()
    greeting = f"Good morning, {name}."
    remark = OPENERS[mood]
    return (
        TEMPLATE.replace("{{GREETING}}", html.escape(greeting))
        .replace("{{DATE}}", day.strftime("%A %d %B %Y"))
        .replace("{{TOTAL}}", str(total))
        .replace("{{SOUNDS}}", str(len(grouped)))
        .replace("{{CARDS}}", body)
        .replace("{{GRAMMAR}}", _grammar_html(grammar or []))
        .replace("{{REMARK}}", html.escape(remark))
    )


def write(findings: list, day: date | None = None, grammar: list[dict] | None = None) -> dict[str, str]:
    """HTML always; PDF and Word when their tools are present."""
    day = day or date.today()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = config.REPORTS_DIR / f"{day.isoformat()}.html"
    html_path.write_text(build_html(findings, day, grammar), encoding="utf-8")
    out = {"html": str(html_path)}

    if CHROMIUM.exists():
        pdf = html_path.with_suffix(".pdf")
        result = subprocess.run(
            [str(CHROMIUM), "--headless", "--no-sandbox", "--disable-gpu",
             f"--print-to-pdf={pdf}", f"file://{html_path}"],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0 and pdf.exists():
            out["pdf"] = str(pdf)

    docx = html_path.with_suffix(".docx")
    result = subprocess.run(
        ["textutil", "-convert", "docx", str(html_path), "-output", str(docx)],
        capture_output=True,
    )
    if result.returncode == 0 and docx.exists():
        out["docx"] = str(docx)
    return out


def open_report(day: date | None = None) -> str | None:
    day = day or date.today()
    path = config.REPORTS_DIR / f"{day.isoformat()}.html"
    if not path.exists():
        return None
    result = subprocess.run(["open", str(path)], capture_output=True)
    return str(path) if result.returncode == 0 else None


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
:root{--ground:#F2F4F4;--surface:#fff;--ink:#101C1B;--ink2:#3A4A48;--muted:#697A78;
--rule:#D3DAD9;--accent:#0F6E68;--accentsoft:#D9EAE8;--crit:#A8261C}
@media(prefers-color-scheme:dark){:root{--ground:#0C1312;--surface:#141D1C;--ink:#E7EDEC;
--ink2:#BCC9C7;--muted:#879896;--rule:#26332F;--accent:#56BEB4;--accentsoft:#12302E;--crit:#F08074}}
*{box-sizing:border-box}body{background:var(--ground);color:var(--ink);margin:0;padding:28px 18px 70px;
font:16px/1.55 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif}
.wrap{max-width:760px;margin:0 auto}h1{font-size:2rem;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:.88rem;margin-bottom:24px}
.greet{font-family:-apple-system,"Helvetica Neue",sans-serif;font-size:1.05rem;color:var(--accent);font-weight:600;margin-bottom:6px}
.remark{font-style:italic;color:var(--ink2);font-size:.95rem;line-height:1.5;margin:10px 0 18px;padding-left:14px;border-left:3px solid var(--accentsoft);max-width:60ch}
.sect{font-size:1.15rem;margin:26px 0 10px;letter-spacing:-.01em}
.sub2{color:var(--muted);font-size:.84rem;margin:-6px 0 12px}
.fix{font-size:.95rem;color:var(--ink2);margin-top:2px}.fix b{color:var(--accent)}
.action{display:inline-block;font-size:.8rem;font-weight:600;color:var(--accent);
  background:var(--accentsoft);padding:2px 8px;border-radius:2px;margin:5px 0 3px}
.rule{font-size:.78rem;color:var(--muted);font-style:italic;margin-top:4px}
.kind{font-size:.7rem;color:var(--muted);margin-left:10px;text-transform:uppercase;letter-spacing:.06em}
.card{background:var(--surface);border:1px solid var(--rule);margin-bottom:12px;overflow:hidden}
.card-head{padding:14px 16px;border-bottom:1px solid var(--rule)}
.swap{font-size:1.25rem;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.bad{color:var(--crit);font-weight:700}.good{color:var(--accent);font-weight:700}
.arrow{color:var(--muted);font-size:.78rem}.n{margin-left:auto;color:var(--muted);font-size:.75rem}
.words{font-size:.83rem;color:var(--muted);margin-top:5px}
.ab{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;padding:11px 16px;
border-bottom:1px solid var(--rule)}.ab:last-child{border-bottom:0}
.word{font-size:1.05rem;font-weight:600}.ipa{color:var(--muted);font-size:.85rem;font-weight:400}
.ctx{font-size:.77rem;color:var(--muted);margin-top:2px}
.buttons{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.pb{border:1px solid var(--rule);background:transparent;border-radius:999px;padding:7px 13px;
font:inherit;font-size:.8rem;cursor:pointer;color:var(--ink2)}
.pb.you{border-color:var(--crit);color:var(--crit)}
.pb.right{border-color:var(--accent);color:var(--accent)}
.pb[disabled]{opacity:.4;cursor:not-allowed}
@media(max-width:620px){.ab{grid-template-columns:1fr}.buttons{justify-content:flex-start}}
@media print{.pb{display:none}.card{break-inside:avoid}}
</style></head><body><div class="wrap">
<div class="greet">{{GREETING}}</div>
<h1>What I heard you say</h1>
<div class="remark">{{REMARK}}</div>
<div class="sub">{{DATE}} &middot; {{TOTAL}} examples across {{SOUNDS}} sound patterns &middot; compare your voice with the reference</div>
<h2 class="sect">Pronunciation</h2>
{{CARDS}}
{{GRAMMAR}}
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
