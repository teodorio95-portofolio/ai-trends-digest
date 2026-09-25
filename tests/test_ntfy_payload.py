import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ntfy_payload import payload, tldr  # noqa: E402

DIGEST = """# AI digest — 2026-09-25

## TL;DR
- first
- second

## 🆕 Nou
- repo
"""


def test_tldr_stops_at_next_section():
    assert tldr(DIGEST) == "- first\n- second"


def test_payload_strips_topic_and_links_everywhere():
    p = payload(DIGEST, "topic\n", "2026-09-25", "https://example.test/d.md")
    assert p["topic"] == "topic"
    assert p["click"] == p["actions"][0]["url"] == "https://example.test/d.md"
    assert p["message"] == "- first\n- second"


def test_empty_digest_falls_back():
    assert payload("", "t", "d", "l")["message"] == "Digest nou."
