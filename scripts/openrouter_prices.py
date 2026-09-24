"""Snapshot OpenRouter model prices and report what changed since the last run.

OpenRouter keeps no price history, so each run stores a compact snapshot and
diffs it against the previous one. Stdlib only: the cloud routine runs it with
plain `python3`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_URL = "https://openrouter.ai/api/v1/models"
PER_MILLION = 1_000_000
DROP_THRESHOLD = 0.05  # ignore price moves under 5%
NEW_MODEL_WINDOW = timedelta(hours=48)  # first run: "new" means created recently
EXPIRY_WINDOW = timedelta(days=7)
ENDPOINT_WORKERS = 8


def _get_json(url: str, api_key: str | None, timeout: int) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "ai-trends-digest"})
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fetch_models(api_key: str | None) -> list[dict]:
    return _get_json(API_URL, api_key, timeout=30)["data"]


def fetch_endpoint_discounts(model_ids: list[str], api_key: str | None) -> tuple[dict[str, float], int]:
    """Discounts live per provider endpoint; /models always reports 0.

    Returns the best discount per model and how many lookups failed.
    """

    def lookup(model_id: str) -> tuple[str, float | None]:
        try:
            data = _get_json(f"{API_URL}/{model_id}/endpoints", api_key, timeout=15)["data"]
        except Exception:  # noqa: BLE001 - one bad model must not sink the digest
            return model_id, None
        discounts = [float((e.get("pricing") or {}).get("discount") or 0) for e in data.get("endpoints", [])]
        return model_id, max(discounts, default=0.0)

    with ThreadPoolExecutor(max_workers=ENDPOINT_WORKERS) as pool:
        results = list(pool.map(lookup, model_ids))
    failed = sum(1 for _, d in results if d is None)
    return {i: d for i, d in results if d}, failed


def per_million(value: object) -> float | None:
    """USD per token -> USD per 1M tokens. Router models report -1: treat as unknown."""
    try:
        price = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if price < 0 else round(price * PER_MILLION, 6)


def normalize(models: list[dict], discounts: dict[str, float] | None = None) -> dict[str, dict]:
    discounts = discounts or {}
    snapshot = {}
    for model in models:
        pricing = model.get("pricing") or {}
        snapshot[model["id"]] = {
            "name": model.get("name", model["id"]),
            "in": per_million(pricing.get("prompt")),
            "out": per_million(pricing.get("completion")),
            "discount": max(float(pricing.get("discount") or 0), discounts.get(model["id"], 0.0)),
            "created": model.get("created"),
            "expires": model.get("expiration_date"),
        }
    return snapshot


def is_free(entry: dict) -> bool:
    return entry["in"] == 0 and entry["out"] == 0


def needs_endpoint_lookup(model_id: str, entry: dict) -> bool:
    """Free variants and routers (price unknown) cannot be discounted further."""
    return not model_id.endswith(":free") and not is_free(entry) and entry["in"] is not None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def diff(previous: dict[str, dict], current: dict[str, dict], now: datetime) -> dict[str, list]:
    if previous:
        new_ids = [i for i in current if i not in previous]
    else:
        cutoff = (now - NEW_MODEL_WINDOW).timestamp()
        new_ids = [i for i, m in current.items() if (m["created"] or 0) >= cutoff]

    drops = []
    for model_id, cur in current.items():
        old = previous.get(model_id)
        if not old:
            continue
        changes = {}
        for side in ("in", "out"):
            before, after = old[side], cur[side]
            if before and after is not None and after < before * (1 - DROP_THRESHOLD):
                changes[side] = (before, after)
        if changes:
            biggest = max(1 - after / before for before, after in changes.values())
            drops.append({"id": model_id, "name": cur["name"], "changes": changes, "pct": biggest})
    drops.sort(key=lambda d: d["pct"], reverse=True)

    # expiration_date on a free variant ends the free offer; on a paid model it retires the model
    free_ending, retiring = [], []
    for model_id, cur in current.items():
        expires = _parse_date(cur["expires"])
        if expires and now <= expires <= now + EXPIRY_WINDOW:
            item = {"id": model_id, "name": cur["name"], "expires": expires.date().isoformat()}
            (free_ending if model_id.endswith(":free") or is_free(cur) else retiring).append(item)

    return {
        "new": [{"id": i, **current[i]} for i in new_ids],
        "drops": drops,
        # same order as openrouter.ai/models?order=discount-high-to-low
        "discounted": sorted(
            ({"id": i, **m} for i, m in current.items() if m["discount"] > 0),
            key=lambda m: m["discount"],
            reverse=True,
        ),
        "free_ending": free_ending,
        "retiring": retiring,
    }


def _usd(value: float | None) -> str:
    return "?" if value is None else f"${value:g}"


def render(report: dict[str, list], limit: int) -> str:
    lines = []
    if report["drops"]:
        lines.append("### Price drops since last snapshot")
        for d in report["drops"][:limit]:
            parts = [f"{side} {_usd(b)} -> {_usd(a)}" for side, (b, a) in d["changes"].items()]
            lines.append(f"- {d['id']} ({d['name']}): -{d['pct']:.0%}; {', '.join(parts)} per 1M tokens")
    if report["discounted"]:
        lines.append("### Active discounts")
        for m in report["discounted"][:limit]:
            lines.append(
                f"- {m['id']} ({m['name']}): {m['discount']:.0%} off; in {_usd(m['in'])}, out {_usd(m['out'])} per 1M"
            )
    if report["new"]:
        lines.append("### New models")
        for m in report["new"][:limit]:
            price = "FREE" if is_free(m) else f"in {_usd(m['in'])}, out {_usd(m['out'])} per 1M"
            lines.append(f"- {m['id']} ({m['name']}): {price}")
    if report["free_ending"]:
        lines.append("### Free offers ending within 7 days")
        for m in report["free_ending"][:limit]:
            lines.append(f"- {m['id']} ({m['name']}): free until {m['expires']}")
    if report["retiring"]:
        lines.append("### Models retired within 7 days (not a discount)")
        for m in report["retiring"][:limit]:
            lines.append(f"- {m['id']} ({m['name']}): removed from OpenRouter on {m['expires']}")
    return "\n".join(lines) if lines else "No price changes, discounts or new models."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="previous snapshot; overwritten")
    parser.add_argument("--limit", type=int, default=10, help="max items per section")
    parser.add_argument("--no-endpoints", action="store_true", help="skip per-endpoint discount lookups")
    args = parser.parse_args()
    api_key = os.environ.get("OPENROUTER_API_KEY")

    try:
        models = fetch_models(api_key)
    except Exception as exc:  # noqa: BLE001 - report any fetch failure to the caller
        print(f"OpenRouter fetch failed: {exc}", file=sys.stderr)
        return 1

    discounts, failed = {}, 0
    if not args.no_endpoints:
        lookup_ids = [i for i, m in normalize(models).items() if needs_endpoint_lookup(i, m)]
        discounts, failed = fetch_endpoint_discounts(lookup_ids, api_key)

    previous = {}
    if args.snapshot.exists():
        previous = json.loads(args.snapshot.read_text())["models"]
    now = datetime.now(timezone.utc)
    current = normalize(models, discounts)

    print(
        f"OpenRouter: {len(current)} models, previous snapshot: {len(previous) or 'none'}, "
        f"endpoint discount lookups failed: {failed}"
    )
    print(render(diff(previous, current, now), args.limit))

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    rows = ",\n".join(f"{json.dumps(i)}: {json.dumps(m, ensure_ascii=False)}" for i, m in sorted(current.items()))
    args.snapshot.write_text(f'{{"fetched_at": "{now.isoformat()}", "models": {{\n{rows}\n}}}}\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())
