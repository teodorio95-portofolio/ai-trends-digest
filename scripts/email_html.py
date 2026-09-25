"""Render a digest (a small, known Markdown subset) as an email.

Email clients drop <style> blocks and external CSS unpredictably, so every
element carries inline styles and the layout is table-based. Stdlib only.

    python3 scripts/email_html.py digests/2026-09-25.md <link>          # HTML
    python3 scripts/email_html.py digests/2026-09-25.md <link> --text   # plain text
"""

from __future__ import annotations

import html
import re
import sys
from datetime import date
from pathlib import Path

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
INK = "#1f2328"
MUTED = "#656d76"
ACCENT = "#0969da"
RULE = "#d8dee4"

# Pictographs and their joiners; arrows (U+2190..21FF) and dashes are kept.
EMOJI = re.compile("[\U0001f000-\U0001faff\U00002600-\U000027bf\U00002b00-\U00002bff\U0000fe0f\U0000200d\U000020e3]")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
CODE = re.compile(r"`([^`]+)`")
ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
WEEKDAYS = ["Luni", "Marti", "Miercuri", "Joi", "Vineri", "Sambata", "Duminica"]
MONTHS = [
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
]  # fmt: skip


def strip_emoji(text: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", EMOJI.sub("", text))


def headline(title: str) -> str:
    """'AI digest — 2026-09-25' -> 'Vineri, 25 septembrie 2026'; anything else unchanged."""
    match = ISO_DATE.search(title)
    if not match:
        return title
    day = date(*map(int, match.groups()))
    return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]} {day.year}"


def inline(text: str) -> str:
    """Escape, then apply links, bold and code. Link URLs are escaped as attributes."""
    out = html.escape(strip_emoji(text).strip(), quote=False)
    out = LINK.sub(
        lambda m: (
            f'<a href="{html.escape(html.unescape(m.group(2)), quote=True)}" '
            f'style="color:{ACCENT};text-decoration:none;font-weight:600;">{m.group(1)}</a>'
        ),
        out,
    )
    out = BOLD.sub(r"<strong>\1</strong>", out)
    return CODE.sub(
        r'<code style="font-family:SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;'
        r'background:#f6f8fa;border-radius:4px;padding:1px 4px;">\1</code>',
        out,
    )


def sections(markdown: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Split into the `#` title and `##` sections (heading, raw lines)."""
    title, parts = "", []
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = strip_emoji(line[2:]).strip()
        elif line.startswith("## "):
            parts.append((strip_emoji(line[3:]).strip(), []))
        elif parts:
            parts[-1][1].append(line)
    return title, parts


def body_html(lines: list[str], small: bool = False) -> str:
    size, color = ("13px", MUTED) if small else ("15px", INK)
    blocks, items = [], []

    def flush() -> None:
        if items:
            lis = "".join(f'<li style="margin:0 0 10px 0;">{i}</li>' for i in items)
            blocks.append(f'<ul style="margin:0;padding:0 0 0 20px;">{lis}</ul>')
            items.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith(("- ", "* ")):
            items.append(inline(line[2:]))
        else:
            flush()
            blocks.append(f'<p style="margin:0 0 10px 0;">{inline(line)}</p>')
    flush()
    return f'<div style="font-size:{size};line-height:1.55;color:{color};">{"".join(blocks)}</div>'


def section_html(heading: str, lines: list[str]) -> str:
    key = heading.lower()
    if key.startswith("tl;dr"):
        return (
            '<tr><td style="padding:0 32px 8px 32px;">'
            f'<div style="background:#f6f8fa;border-left:4px solid {ACCENT};border-radius:6px;padding:16px 18px;">'
            f'<div style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;'
            f'color:{ACCENT};margin:0 0 10px 0;">Pe scurt</div>{body_html(lines)}</div></td></tr>'
        )
    small = key.startswith("surse")
    return (
        '<tr><td style="padding:22px 32px 4px 32px;">'
        f'<div style="border-top:1px solid {RULE};padding-top:18px;font-size:12px;font-weight:700;'
        f'letter-spacing:.08em;text-transform:uppercase;color:{MUTED};margin:0 0 12px 0;">'
        f"{html.escape(heading)}</div>{body_html(lines, small)}</td></tr>"
    )


def render(markdown: str, link: str) -> str:
    title, parts = sections(markdown)
    href = html.escape(link, quote=True)
    rows = "".join(section_html(h, lines) for h, lines in parts)
    return f"""<!DOCTYPE html>
<html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title></head>
<body style="margin:0;padding:0;background:#f4f5f7;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="max-width:640px;background:#ffffff;border-radius:10px;border:1px solid {RULE};font-family:{FONT};">
<tr><td style="padding:28px 32px 18px 32px;">
<div style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{MUTED};">AI digest</div>
<div style="font-size:22px;font-weight:700;color:{INK};margin:6px 0 16px 0;">{html.escape(headline(title))}</div>
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="background:{ACCENT};border-radius:6px;">
<a href="{href}" style="display:inline-block;padding:10px 18px;font-size:14px;font-weight:600;color:#ffffff;
text-decoration:none;">Deschide pe GitHub</a></td></tr></table>
</td></tr>
{rows}
<tr><td style="padding:22px 32px 26px 32px;font-size:12px;color:{MUTED};border-top:1px solid {RULE};">
Generat automat de <a href="{href}" style="color:{MUTED};">ai-trends-digest</a>.
</td></tr>
</table></td></tr></table></body></html>
"""


def render_text(markdown: str, link: str) -> str:
    return f"Deschide pe GitHub: {link}\n\n{strip_emoji(markdown)}"


def main() -> int:
    markdown = Path(sys.argv[1]).read_text()
    link = sys.argv[2]
    print(render_text(markdown, link) if "--text" in sys.argv[3:] else render(markdown, link))
    return 0


if __name__ == "__main__":
    sys.exit(main())
