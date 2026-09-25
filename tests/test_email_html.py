import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from email_html import headline, inline, render, render_text, sections, strip_emoji  # noqa: E402

DIGEST = """# AI digest — 2026-09-25

## TL;DR
- **Opus 5.5** e mai ieftin

## 🆕 Nou: agents
- [a/b](https://github.com/a/b) — ⭐ 10 (+2) — un repo <script>

## 💸 Reduceri
- Kimi — in $3 → $0.88

## Surse
- GitHub OK
"""


def test_strip_emoji_keeps_arrows_and_dashes():
    assert strip_emoji("🆕 Nou — $3 → $1 ⭐ 10") == " Nou — $3 → $1 10"


def test_inline_escapes_html_and_renders_links_bold_code():
    out = inline("[x](https://e.test/?a=1&b=2) **b** `c` <i>")
    assert 'href="https://e.test/?a=1&amp;b=2"' in out
    assert "<strong>b</strong>" in out
    assert ">c</code>" in out
    assert "&lt;i&gt;" in out


def test_sections_drop_emoji_from_headings():
    title, parts = sections(DIGEST)
    assert title == "AI digest — 2026-09-25"
    assert [h for h, _ in parts] == ["TL;DR", "Nou: agents", "Reduceri", "Surse"]


def test_render_has_button_tldr_box_and_no_emoji():
    out = render(DIGEST, "https://github.com/o/r/blob/digests/digests/2026-09-25.md")
    assert "Deschide pe GitHub" in out
    assert "Pe scurt" in out
    assert "&lt;script&gt;" in out
    assert "→" in out
    assert not any(ch in out for ch in "🆕💸⭐")


def test_headline_spells_the_date_in_romanian():
    assert headline("AI digest — 2026-09-25") == "Vineri, 25 septembrie 2026"
    assert headline("fara data") == "fara data"


def test_render_text_puts_link_first_without_emoji():
    text = render_text(DIGEST, "L")
    assert text.startswith("Deschide pe GitHub: L")
    assert "⭐" not in text and "🆕" not in text
