"""Rank closed frontier models by Artificial Analysis Intelligence Index against price and speed.

Uses the free Artificial Analysis API, /api/v2/language/models/free (attribution
to artificialanalysis.ai is required). AA no longer publishes a separate Coding
Index (the field is always null); coding is one of the four equally weighted
categories of Intelligence Index v5. The free tier has no blended price, so it is
computed here as (3 x input + output) / 4, USD per 1M tokens. Only closed
frontier models are ranked, newest version per model line, each model once per
list (best effort variant). Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
MODEL_URL = "https://artificialanalysis.ai/models/{slug}"
KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"
MAX_PAGES = 20  # 200 models per page; about 4 pages today
STRONG_RATIO = 0.8  # value/speed lists only consider models within 80% of the best index
LISTS = ("top", "value", "fast")
# The free tier has no open-weights/license field: frontier = closed labs, minus their open families.
FRONTIER_CREATORS = {"anthropic", "openai", "google", "xai", "meta"}
OPEN_FAMILIES = ("gpt-oss", "gemma", "llama")
EFFORT_SUFFIX = re.compile(r"(\s*\([^)]*\))+\s*$")  # "Claude Fable 5.1 (Max, Default Fallback)"
VERSION = re.compile(r"\d+(?:\.\d+)*")
PREVIEW = re.compile(r"\bpreview\b", re.IGNORECASE)


def fetch_models(api_key: str) -> tuple[list[dict], object]:
    """Every page of the free language-models list, plus the Intelligence Index version."""
    models: list[dict] = []
    index_version = None
    for page in range(1, MAX_PAGES + 1):
        url = f"{API_URL}?{urllib.parse.urlencode({'page': page})}"
        request = urllib.request.Request(url, headers={"User-Agent": "ai-trends-digest", "x-api-key": api_key})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
        models.extend(body.get("data") or [])
        index_version = body.get("intelligence_index_version", index_version)
        if not (body.get("pagination") or {}).get("has_more"):
            return models, index_version
    raise RuntimeError(f"more than {MAX_PAGES} pages")


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if number < 0 else number


def blended(price_in: float | None, price_out: float | None) -> float | None:
    """AA's 3:1 input:output blend, which the free tier no longer returns."""
    if price_in is None or price_out is None:
        return None
    return round((3 * price_in + price_out) / 4, 6)


def normalize(models: list[dict]) -> dict[str, dict]:
    """Missing index, prices or speeds become None."""
    snapshot = {}
    for model in models:
        score = _number((model.get("evaluations") or {}).get("artificial_analysis_intelligence_index"))
        pricing = model.get("pricing") or {}
        price_in = _number(pricing.get("price_1m_input_tokens"))
        price_out = _number(pricing.get("price_1m_output_tokens"))
        # performance_v3 replaces performance, which returns null from 2026-12-10
        tps = _number((model.get("performance_v3") or {}).get("mean_output_tokens_per_second"))
        if not tps:
            tps = _number((model.get("performance") or {}).get("median_output_tokens_per_second"))
        name = model.get("name") or model["id"]
        snapshot[model["id"]] = {
            "name": name,
            "family": family(name),
            "creator": (model.get("model_creator") or {}).get("name") or "?",
            "slug": model.get("slug") or "",
            "index": score,
            "price": blended(price_in, price_out),
            "in": price_in,
            "out": price_out,
            "tps": tps or None,
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
    """Families newer than every scored version of their line but without an index yet."""
    best: dict[str, tuple[int, ...]] = {}
    for m in ranked.values():
        best[line(m["name"])] = max(best.get(line(m["name"]), ()), version(m["name"]))
    return sorted(
        {
            m["family"]
            for m in models.values()
            if m["index"] is None and line(m["name"]) in best and version(m["name"]) > best[line(m["name"])]
        }
    )


def is_frontier(entry: dict) -> bool:
    name = entry["name"].lower()
    return entry["creator"].lower() in FRONTIER_CREATORS and not any(f in name for f in OPEN_FAMILIES)


def frontier(models: dict[str, dict]) -> dict[str, dict]:
    return {i: m for i, m in models.items() if is_frontier(m)}


def value(entry: dict) -> float:
    return entry["index"] / entry["price"]


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
    floor = STRONG_RATIO * max(m["index"] for m in models.values())
    strong = {i: m for i, m in models.items() if m["index"] >= floor}
    priced = [i for i, m in strong.items() if m["price"]]  # free/unknown price has no meaningful ratio
    timed = [i for i, m in strong.items() if m["tps"]]
    return {
        "top": _unique(sorted(models, key=lambda i: models[i]["index"], reverse=True), models, limit),
        "value": _unique(sorted(priced, key=lambda i: value(models[i]), reverse=True), models, limit),
        "fast": _unique(sorted(timed, key=lambda i: models[i]["tps"], reverse=True), models, limit),
    }


def new_entries(
    ranks: dict[str, list[str]], models: dict[str, dict], previous: dict[str, list[str]]
) -> dict[str, set[str]]:
    """Ids whose family entered a list since the last snapshot. First run: nothing is new."""
    # A snapshot whose lists are all empty carries no baseline either (a run that ranked
    # nothing wrote it); treat it like a first run instead of calling every entry new.
    if not any(previous.get(name) for name in LISTS):
        return {name: set() for name in LISTS}
    return {name: {i for i in ranks[name] if models[i]["family"] not in previous.get(name, [])} for name in LISTS}


def _usd(value: float | None) -> str:
    return "?" if value is None else f"${value:g}"


def _line(model_id: str, m: dict, extra: str, new: bool) -> str:
    tps = "? tok/s" if m["tps"] is None else f"{m['tps']:.0f} tok/s"
    text = (
        f"- {m['name']} ({m['creator']}): intelligence index {m['index']:g}{extra}; "
        f"{_usd(m['price'])}/1M blended 3:1 (in {_usd(m['in'])}, out {_usd(m['out'])}); {tps}; "
        f"{MODEL_URL.format(slug=m['slug'] or model_id)}"
    )
    return text + ("; NEW in this list" if new else "")


def render(
    models: dict[str, dict], ranks: dict[str, list[str]], new: dict[str, set[str]], pending: list[str] | None = None
) -> str:
    titles = {
        "top": "### Highest Intelligence Index",
        "value": f"### Best index per $ (blended 1M tokens, models >= {STRONG_RATIO:.0%} of the best)",
        "fast": f"### Fastest output (models >= {STRONG_RATIO:.0%} of the best index)",
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
        lines.append("No closed frontier models with an Intelligence Index.")
    if pending:
        lines.append("### Newer versions without an Intelligence Index yet (not ranked, older version shown above)")
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
        raw, index_version = fetch_models(api_key)
    except Exception as exc:  # noqa: BLE001 - report any fetch failure to the caller
        print(f"Artificial Analysis fetch failed: {exc}", file=sys.stderr)
        return 1
    everything = normalize(raw)
    scored = sum(1 for m in everything.values() if m["index"] is not None)
    if not scored:
        # An answer with no scores at all means the API changed shape, not that the market did:
        # fail loudly (the previous snapshot stays) instead of printing an empty section.
        print(
            f"Artificial Analysis fetch failed: {len(everything)} models but none with an Intelligence Index "
            "(API shape changed?)",
            file=sys.stderr,
        )
        return 1

    previous = {}
    if args.snapshot.exists():
        previous = json.loads(args.snapshot.read_text()).get("ranks", {})
    closed = frontier(everything)
    models = latest({i: m for i, m in closed.items() if m["index"] is not None})
    ranks = rank(models, args.limit)

    print(
        f"Artificial Analysis Intelligence Index v{index_version}: {scored} of {len(everything)} models scored, "
        f"{len(models)} closed frontier ({', '.join(sorted(FRONTIER_CREATORS))}; open families excluded), "
        f"newest version per model line, one variant per model, previous snapshot: {bool(previous)}"
    )
    print(render(models, ranks, new_entries(ranks, models, previous), unscored_newer(closed, models)))

    if not models:
        # The source answered but ranked nothing: keep the previous snapshot so the next run
        # still has a baseline and does not mark every entry as new.
        print("Artificial Analysis: nothing ranked, previous snapshot kept", file=sys.stderr)
        return 0

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    families = {name: [models[i]["family"] for i in ids] for name, ids in ranks.items()}
    kept = {i: models[i] for i in sorted({i for ids in ranks.values() for i in ids})}
    snapshot = {"fetched_at": now, "index_version": index_version, "ranks": families, "models": kept}
    args.snapshot.write_text(json.dumps(snapshot, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
