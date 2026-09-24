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
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_URL = "https://openrouter.ai/api/v1/models"
PER_MILLION = 1_000_000
DROP_THRESHOLD = 0.05  # ignore price moves under 5%
NEW_MODEL_WINDOW = timedelta(hours=48)  # first run: "new" means created recently
EXPIRY_WINDOW = timedelta(days=7)


def fetch_models(api_key: str | None) -> list[dict]:
    request = urllib.request.Request(API_URL, headers={"User-Agent": "ai-trends-digest"})
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["data"]


def per_million(value: object) -> float | None:
    """USD per token -> USD per 1M tokens. Router models report -1: treat as unknown."""
    try:
        price = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if price < 0 else round(price * PER_MILLION, 6)


def normalize(models: list[dict]) -> dict[str, dict]:
    snapshot = {}
    for model in models:
        pricing = model.get("pricing") or {}
        snapshot[model["id"]] = {
            "name": model.get("name", model["id"]),
            "in": per_million(pricing.get("prompt")),
            "out": per_million(pricing.get("completion")),
            "discount": float(pricing.get("discount") or 0),
            "created": model.get("created"),
            "expires": model.get("expiration_date"),
        }
    return snapshot


def is_free(entry: dict) -> bool:
    return entry["in"] == 0 and entry["out"] == 0


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

    expiring = []
    for model_id, cur in current.items():
        expires = _parse_date(cur["expires"])
        if expires and now <= expires <= now + EXPIRY_WINDOW:
            expiring.append({"id": model_id, "name": cur["name"], "expires": expires.date().isoformat()})

    return {
        "new": [{"id": i, **current[i]} for i in new_ids],
        "drops": drops,
        # same order as openrouter.ai/models?order=discount-high-to-low
        "discounted": sorted(
            ({"id": i, **m} for i, m in current.items() if m["discount"] > 0),
            key=lambda m: m["discount"],
            reverse=True,
        ),
        "expiring": expiring,
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
    if report["expiring"]:
        lines.append("### Expiring within 7 days")
        for m in report["expiring"][:limit]:
            lines.append(f"- {m['id']} ({m['name']}): expires {m['expires']}")
    return "\n".join(lines) if lines else "No price changes, discounts or new models."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="previous snapshot; overwritten")
    parser.add_argument("--limit", type=int, default=10, help="max items per section")
    args = parser.parse_args()

    try:
        models = fetch_models(os.environ.get("OPENROUTER_API_KEY"))
    except Exception as exc:  # noqa: BLE001 - report any fetch failure to the caller
        print(f"OpenRouter fetch failed: {exc}", file=sys.stderr)
        return 1

    previous = {}
    if args.snapshot.exists():
        previous = json.loads(args.snapshot.read_text())["models"]
    now = datetime.now(timezone.utc)
    current = normalize(models)

    print(f"OpenRouter: {len(current)} models, previous snapshot: {len(previous) or 'none'}")
    print(render(diff(previous, current, now), args.limit))

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    args.snapshot.write_text(json.dumps({"fetched_at": now.isoformat(), "models": current}, indent=0) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
