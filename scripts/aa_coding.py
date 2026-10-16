"""Rank models by Artificial Analysis Coding Index against price and speed.

Uses the free Artificial Analysis API (attribution to artificialanalysis.ai is
required). The coding index is per model; prices are USD per 1M tokens, not
per task: the coding-agents page (cost per task) has no API. Only closed
frontier models are ranked, each model family once (best effort variant).
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
MODEL_URL = "https://artificialanalysis.ai/models/{slug}"
KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"
STRONG_RATIO = 0.8  # value/speed lists only consider models within 80% of the best coding index
LISTS = ("top", "value", "fast")
# The API has no open-weights/license field: frontier = closed labs, minus their open families.
FRONTIER_CREATORS = {"anthropic", "openai", "google", "xai", "meta"}
OPEN_FAMILIES = ("gpt-oss", "gemma", "llama")
EFFORT_SUFFIX = re.compile(r"(\s*\([^)]*\))+\s*$")  # "Claude Fable 5.1 (Max, Default Fallback)"
VERSION = re.compile(r"\d+(?:\.\d+)*")
PREVIEW = re.compile(r"\bpreview\b", re.IGNORECASE)


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
    """Missing coding index, prices or speeds become None."""
    snapshot = {}
    for model in models:
        coding = _number((model.get("evaluations") or {}).get("artificial_analysis_coding_index"))
        pricing = model.get("pricing") or {}
        name = model.get("name", model["id"])
        snapshot[model["id"]] = {
            "name": name,
            "family": family(name),
            "creator": (model.get("model_creator") or {}).get("name", "?"),
            "slug": model.get("slug", ""),
            "coding": coding,
            "price": _number(pricing.get("price_1m_blended_3_to_1")),
            "in": _number(pricing.get("price_1m_input_tokens")),
            "out": _number(pricing.get("price_1m_output_tokens")),
            "tps": _number(model.get("median_output_tokens_per_second")) or None,
        }
    return snapshot


def family(name: str) -> str:
    """Model name without the effort/variant suffix, so each model shows up once per list."""
    return EFFORT_SUFFIX.sub("", name).strip() or name


def line(name: str) -> str:
    """Model line without version numbers: 'Gemini 3.8 Flash' and 'Gemini 3.7 Flash' -> 'gemini flash'."""
    bare = VERSION.sub(" ", PREVIEW.sub(" ", family(name).lower()))
    return " ".join(part for part in re.split(r"[\s\-_.]+", bare) if part)


def version(name: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", family(name)))


def latest(models: dict[str, dict]) -> dict[str, dict]:
    """Drop models whose line has a newer version (all effort variants of the newest stay)."""
    newest: dict[str, tuple[int, ...]] = {}
    for m in models.values():
        newest[line(m["name"])] = max(newest.get(line(m["name"]), ()), version(m["name"]))
    return {i: m for i, m in models.items() if version(m["name"]) == newest[line(m["name"])]}


def unscored_newer(models: dict[str, dict], ranked: dict[str, dict]) -> list[str]:
    """Families newer than every scored version of their line but without a coding index yet."""
    best: dict[str, tuple[int, ...]] = {}
    for m in ranked.values():
        best[line(m["name"])] = max(best.get(line(m["name"]), ()), version(m["name"]))
    return sorted(
        {
            m["family"]
            for m in models.values()
            if m["coding"] is None and line(m["name"]) in best and version(m["name"]) > best[line(m["name"])]
        }
    )


def is_frontier(entry: dict) -> bool:
    name = entry["name"].lower()
    return entry["creator"].lower() in FRONTIER_CREATORS and not any(f in name for f in OPEN_FAMILIES)


def frontier(models: dict[str, dict]) -> dict[str, dict]:
    return {i: m for i, m in models.items() if is_frontier(m)}


def value(entry: dict) -> float:
    return entry["coding"] / entry["price"]


def _unique(ids: list[str], models: dict[str, dict], limit: int) -> list[str]:
    """Keep the first (best) variant of each family."""
    seen, kept = set(), []
    for i in ids:
        if models[i]["family"] not in seen:
            seen.add(models[i]["family"])
            kept.append(i)
    return kept[:limit]


def rank(models: dict[str, dict], limit: int) -> dict[str, list[str]]:
    if not models:
        return {name: [] for name in LISTS}
    floor = STRONG_RATIO * max(m["coding"] for m in models.values())
    strong = {i: m for i, m in models.items() if m["coding"] >= floor}
    priced = [i for i, m in strong.items() if m["price"]]  # free/unknown price has no meaningful ratio
    timed = [i for i, m in strong.items() if m["tps"]]
    return {
        "top": _unique(sorted(models, key=lambda i: models[i]["coding"], reverse=True), models, limit),
        "value": _unique(sorted(priced, key=lambda i: value(models[i]), reverse=True), models, limit),
        "fast": _unique(sorted(timed, key=lambda i: models[i]["tps"], reverse=True), models, limit),
    }


def new_entries(
    ranks: dict[str, list[str]], models: dict[str, dict], previous: dict[str, list[str]]
) -> dict[str, set[str]]:
    """Ids whose family entered a list since the last snapshot. First run: nothing is new."""
    if not previous:
        return {name: set() for name in LISTS}
    return {name: {i for i in ranks[name] if models[i]["family"] not in previous.get(name, [])} for name in LISTS}


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


def render(
    models: dict[str, dict], ranks: dict[str, list[str]], new: dict[str, set[str]], pending: list[str] | None = None
) -> str:
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
    if not lines:
        lines.append("No models with a coding index.")
    if pending:
        lines.append("### Newer versions without a coding index yet (not ranked, older version shown above)")
        lines.extend(f"- {name}" for name in pending)
    return "\n".join(lines)


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
        everything = normalize(fetch_models(api_key))
    except Exception as exc:  # noqa: BLE001 - report any fetch failure to the caller
        print(f"Artificial Analysis fetch failed: {exc}", file=sys.stderr)
        return 1

    previous = {}
    if args.snapshot.exists():
        previous = json.loads(args.snapshot.read_text()).get("ranks", {})
    closed = frontier(everything)
    models = latest({i: m for i, m in closed.items() if m["coding"] is not None})
    ranks = rank(models, args.limit)

    scored = sum(1 for m in everything.values() if m["coding"] is not None)
    print(
        f"Artificial Analysis: {scored} models with a coding index, {len(models)} closed frontier "
        f"({', '.join(sorted(FRONTIER_CREATORS))}; open families excluded), newest version per model line, "
        f"one variant per model, previous snapshot: {bool(previous)}"
    )
    print(render(models, ranks, new_entries(ranks, models, previous), unscored_newer(closed, models)))

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    families = {name: [models[i]["family"] for i in ids] for name, ids in ranks.items()}
    kept = {i: models[i] for i in sorted({i for ids in ranks.values() for i in ids})}
    args.snapshot.write_text(json.dumps({"fetched_at": now, "ranks": families, "models": kept}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
