import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from openrouter_prices import diff, normalize, per_million, render  # noqa: E402

NOW = datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc)


def model(model_id, prompt="0.000001", completion="0.000002", discount=0, created=0, expires=None):
    return {
        "id": model_id,
        "name": model_id.upper(),
        "created": created,
        "expiration_date": expires,
        "pricing": {"prompt": prompt, "completion": completion, "discount": discount},
    }


def test_per_million_handles_router_and_garbage():
    assert per_million("0.000003") == 3
    assert per_million("-1") is None
    assert per_million(None) is None


def test_drop_over_threshold_is_reported_small_move_is_not():
    prev = normalize([model("a"), model("b")])
    cur = normalize([model("a", prompt="0.0000005"), model("b", prompt="0.00000098")])
    report = diff(prev, cur, NOW)
    assert [d["id"] for d in report["drops"]] == ["a"]
    assert report["drops"][0]["pct"] == 0.5


def test_new_model_against_previous_snapshot():
    prev = normalize([model("a")])
    cur = normalize([model("a"), model("b:free", prompt="0", completion="0")])
    report = diff(prev, cur, NOW)
    assert [m["id"] for m in report["new"]] == ["b:free"]
    assert "FREE" in render(report, 10)


def test_first_run_uses_created_window():
    recent = int((NOW - timedelta(hours=3)).timestamp())
    old = int((NOW - timedelta(days=30)).timestamp())
    cur = normalize([model("fresh", created=recent), model("stale", created=old)])
    assert [m["id"] for m in diff({}, cur, NOW)["new"]] == ["fresh"]


def test_discount_and_expiry():
    cur = normalize(
        [
            model("promo", discount=0.25, expires="2026-09-28T00:00:00Z"),
            model("later", expires="2026-12-01"),
        ]
    )
    report = diff(cur, cur, NOW)
    assert [m["id"] for m in report["discounted"]] == ["promo"]
    assert [m["id"] for m in report["expiring"]] == ["promo"]


def test_discounts_sorted_high_to_low():
    cur = normalize([model("small", discount=0.1), model("big", discount=0.5), model("none")])
    assert [m["id"] for m in diff(cur, cur, NOW)["discounted"]] == ["big", "small"]


def test_render_when_nothing_changed():
    cur = normalize([model("a")])
    assert render(diff(cur, cur, NOW), 10) == "No price changes, discounts or new models."
