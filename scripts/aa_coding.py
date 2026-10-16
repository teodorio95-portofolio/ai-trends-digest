"""Rank models by Artificial Analysis Coding Index against price and speed.

Uses the free Artificial Analysis API (attribution to artificialanalysis.ai is
required). The coding index is per model; prices are USD per 1M tokens, not
per task: the coding-agents page (cost per task) has no API. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
MODEL_URL = "https://artificialanalysis.ai/models/{slug}"
KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"
STRONG_RATIO = 0.8  # value/speed lists only consider models within 80% of the best coding index
LISTS = ("top", "value", "fast")


def fetch_models(api_key: str) -> list[dict]:
    request = urllib.request.Request(API_URL, headers={"User-Agent": "ai-trends-digest", "x-api-key": api_key})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["data"]


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if number < 0 else number


def normalize(models: list[dict]) -> dict[str, dict]:
    """Keep only models with a coding index; missing prices or speeds become None."""
    snapshot = {}
    for model in models:
        coding = _number((model.get("evaluations") or {}).get("artificial_analysis_coding_index"))
        if coding is None:
            continue
        pricing = model.get("pricing") or {}
        snapshot[model["id"]] = {
            "name": model.get("name", model["id"]),
            "creator": (model.get("model_creator") or {}).get("name", "?"),
            "slug": model.get("slug", ""),
            "coding": coding,
            "price": _number(pricing.get("price_1m_blended_3_to_1")),
            "in": _number(pricing.get("price_1m_input_tokens")),
            "out": _number(pricing.get("price_1m_output_tokens")),
            "tps": _number(model.get("median_output_tokens_per_second")) or None,
        }
    return snapshot


def value(entry: dict) -> float:
    return entry["coding"] / entry["price"]


def rank(models: dict[str, dict], limit: int) -> dict[str, list[str]]:
    if not models:
        return {name: [] for name in LISTS}
    floor = STRONG_RATIO * max(m["coding"] for m in models.values())
    strong = {i: m for i, m in models.items() if m["coding"] >= floor}
    priced = [i for i, m in strong.items() if m["price"]]  # free/unknown price has no meaningful ratio
    timed = [i for i, m in strong.items() if m["tps"]]
    return {
        "top": sorted(models, key=lambda i: models[i]["coding"], reverse=True)[:limit],
        "value": sorted(priced, key=lambda i: value(models[i]), reverse=True)[:limit],
        "fast": sorted(timed, key=lambda i: models[i]["tps"], reverse=True)[:limit],
    }


def new_entries(ranks: dict[str, list[str]], previous: dict[str, list[str]]) -> dict[str, set[str]]:
    """Ids that entered a list since the last snapshot. First run: nothing is new."""
    if not previous:
        return {name: set() for name in LISTS}
    return {name: set(ranks[name]) - set(previous.get(name, [])) for name in LISTS}


def _usd(value: float | None) -> str:
    return "?" if value is None else f"${value:g}"


def _line(model_id: str, m: dict, extra: str, new: bool) -> str:
    tps = "? tok/s" if m["tps"] is None else f"{m['tps']:.0f} tok/s"
    line = (
        f"- {m['name']} ({m['creator']}): coding index {m['coding']:g}{extra}; "
        f"{_usd(m['price'])}/1M blended (in {_usd(m['in'])}, out {_usd(m['out'])}); {tps}; "
        f"{MODEL_URL.format(slug=m['slug'] or model_id)}"
    )
    return line + ("; NEW in this list" if new else "")


def render(models: dict[str, dict], ranks: dict[str, list[str]], new: dict[str, set[str]]) -> str:
    titles = {
        "top": "### Highest coding index",
        "value": f"### Best coding index per $ (blended 1M tokens, models >= {STRONG_RATIO:.0%} of the best)",
        "fast": f"### Fastest output (models >= {STRONG_RATIO:.0%} of the best coding index)",
    }
    lines = []
    for name in LISTS:
        if not ranks[name]:
            continue
        lines.append(titles[name])
        for i in ranks[name]:
            extra = f" ({value(models[i]):.1f} points per $)" if name == "value" else ""
            lines.append(_line(i, models[i], extra, i in new[name]))
    return "\n".join(lines) if lines else "No models with a coding index."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="previous snapshot; overwritten")
    parser.add_argument("--limit", type=int, default=5, help="max items per list")
    args = parser.parse_args()

    api_key = os.environ.get(KEY_ENV, "").strip()
    if not api_key:
        print(f"Artificial Analysis: skipped (no {KEY_ENV})")
        return 0
    try:
        models = normalize(fetch_models(api_key))
    except Exception as exc:  # noqa: BLE001 - report any fetch failure to the caller
        print(f"Artificial Analysis fetch failed: {exc}", file=sys.stderr)
        return 1

    previous = {}
    if args.snapshot.exists():
        previous = json.loads(args.snapshot.read_text()).get("ranks", {})
    ranks = rank(models, args.limit)

    print(f"Artificial Analysis: {len(models)} models with a coding index, previous snapshot: {bool(previous)}")
    print(render(models, ranks, new_entries(ranks, previous)))

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    kept = {i: models[i] for i in sorted({i for ids in ranks.values() for i in ids})}
    args.snapshot.write_text(json.dumps({"fetched_at": now, "ranks": ranks, "models": kept}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
