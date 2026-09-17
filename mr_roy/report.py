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

TIPS = {
    "v->w": "Top teeth on the bottom lip, then switch your voice on.",
    "w->v": "Round the lips and keep the teeth away.",
    "th->t": "Tongue between the teeth and blow.",
    "dh->d": "Tongue between the teeth, and voice it.",
    "z->s": "Same mouth as s, voice on. Your throat should buzz.",
    "zh->j": "Soft, like the middle of treasure. Do not stop it short.",
    "final-d": "Do not harden the ending. Keep the voice on.",
    "f->ph": "Teeth on lip and blow steadily. No puff of air.",
    "ae->e": "Open the jaw wider than feels right.",
}


def _audio_tag(path: str | None, label: str, css: str) -> str:
    data = daily.embed(path)
    if not data:
        return f'<button class="pb {css}" disabled>{label}</button>'
    return (
        f'<button class="pb {css}" data-src="{data}">{label}</button>'
    )


def build_html(findings: list, day: date) -> str:
    grouped = daily.group(findings)
    total = len(findings)
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
            + f'</div><div class="ctx">{html.escape(f.sentence[:110])}</div></div>'
            + '<div class="buttons">'
            + _audio_tag(f.clip_path, "▶ You", "you")
            + _audio_tag(f.correct_path, "▶ Correct", "right")
            + "</div></div>"
            for f in examples
        )
        rows.append(
            f'<div class="card"><div class="card-head"><div class="swap">'
            f'<span class="bad">/{html.escape(first.said)}/</span>'
            f'<span class="arrow">you said, should be</span>'
            f'<span class="good">/{html.escape(first.should_be)}/</span>'
            f'<span class="n">{len(items)}x</span></div>'
            f'<div class="words">{CONTRAST_NAMES.get(contrast, contrast)}'
            f' &middot; {html.escape(TIPS.get(contrast, ""))}</div></div>'
            f"{blocks}</div>"
        )

    body = "".join(rows) or (
        '<div class="card"><div class="card-head"><div class="words">'
        "Nothing flagged. Either a clean day or a quiet one.</div></div></div>"
    )
    return TEMPLATE.replace("{{DATE}}", day.strftime("%A %d %B %Y")).replace(
        "{{TOTAL}}", str(total)
    ).replace("{{SOUNDS}}", str(len(grouped))).replace("{{CARDS}}", body)


def write(findings: list, day: date | None = None) -> dict[str, str]:
    """HTML always; PDF and Word when their tools are present."""
    day = day or date.today()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = config.REPORTS_DIR / f"{day.isoformat()}.html"
    html_path.write_text(build_html(findings, day), encoding="utf-8")
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
    subprocess.run(["open", str(path)], capture_output=True)
    return str(path)


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<title>Mr Roy - {{DATE}}</title><style>
:root{--ground:#F2F4F4;--surface:#fff;--ink:#101C1B;--ink2:#3A4A48;--muted:#697A78;
--rule:#D3DAD9;--accent:#0F6E68;--accentsoft:#D9EAE8;--crit:#A8261C}
@media(prefers-color-scheme:dark){:root{--ground:#0C1312;--surface:#141D1C;--ink:#E7EDEC;
--ink2:#BCC9C7;--muted:#879896;--rule:#26332F;--accent:#56BEB4;--accentsoft:#12302E;--crit:#F08074}}
*{box-sizing:border-box}body{background:var(--ground);color:var(--ink);margin:0;padding:28px 18px 70px;
font:16px/1.55 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif}
.wrap{max-width:760px;margin:0 auto}h1{font-size:2rem;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:.88rem;margin-bottom:24px}
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
<h1>What I heard you say</h1>
<div class="sub">{{DATE}} &middot; {{TOTAL}} mistakes across {{SOUNDS}} sounds &middot; press a button to hear it</div>
{{CARDS}}
</div><script>
var playing=null;
document.addEventListener('click',function(e){
  var b=e.target.closest('.pb[data-src]'); if(!b)return;
  if(playing){playing.pause();playing=null;}
  playing=new Audio(b.getAttribute('data-src')); playing.play();
});
</script></body></html>"""
