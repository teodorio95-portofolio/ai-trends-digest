"""Build the ntfy JSON payload for a digest: TL;DR as the message, a tap opens GitHub.

Reads NTFY_TOPIC, TODAY and LINK from the environment. Published as JSON (not
headers) because the title may contain non-ASCII characters.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MAX_MESSAGE = 400


def tldr(markdown: str) -> str:
    """Bullets under `## TL;DR`, up to the next section."""
    section = markdown.split("## TL;DR", 1)[-1].split("\n## ", 1)[0]
    return "\n".join(line.strip() for line in section.strip().splitlines() if line.strip())


def payload(markdown: str, topic: str, today: str, link: str) -> dict:
    return {
        "topic": topic.strip(),
        "title": f"AI digest {today}",
        "message": tldr(markdown)[:MAX_MESSAGE] or "Digest nou.",
        "tags": ["robot"],
        "markdown": True,
        "click": link,
        "actions": [{"action": "view", "label": "Deschide pe GitHub", "url": link}],
    }


def main() -> int:
    markdown = Path(sys.argv[1]).read_text()
    env = os.environ
    print(json.dumps(payload(markdown, env["NTFY_TOPIC"], env["TODAY"], env["LINK"]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
