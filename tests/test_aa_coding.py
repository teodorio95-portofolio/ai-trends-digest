import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aa_coding import new_entries, normalize, rank, render  # noqa: E402


def model(model_id, coding=50, price=1.0, tps=100, slug=None):
    return {
        "id": model_id,
        "name": model_id.upper(),
        "slug": slug or model_id,
        "model_creator": {"name": "Acme"},
        "evaluations": {"artificial_analysis_coding_index": coding},
        "pricing": {"price_1m_blended_3_to_1": price, "price_1m_input_tokens": price, "price_1m_output_tokens": price},
        "median_output_tokens_per_second": tps,
    }


def test_normalize_drops_models_without_coding_index_and_keeps_missing_price():
    raw = [model("a"), model("b", price=None, tps=0)]
    raw.append({**model("c"), "evaluations": {}})
    models = normalize(raw)
    assert sorted(models) == ["a", "b"]
    assert models["b"]["price"] is None
    assert models["b"]["tps"] is None


def test_value_list_ignores_weak_cheap_and_unpriced_models():
    models = normalize(
        [
            model("best", coding=70, price=10),
            model("good", coding=60, price=2),
            model("weak", coding=30, price=0.01),
            model("free", coding=65, price=0),
        ]
    )
    ranks = rank(models, 5)
    assert ranks["top"] == ["best", "free", "good", "weak"]
    assert ranks["value"] == ["good", "best"]


def test_fast_list_only_strong_models_with_known_speed():
    models = normalize(
        [
            model("slow", coding=70, tps=40),
            model("quick", coding=60, tps=300),
            model("weak", coding=20, tps=900),
            model("unknown", coding=69, tps=None),
        ]
    )
    assert rank(models, 5)["fast"] == ["quick", "slow"]


def test_limit_and_empty_input():
    models = normalize([model(str(i), coding=50 + i) for i in range(10)])
    assert len(rank(models, 3)["top"]) == 3
    assert rank({}, 3) == {"top": [], "value": [], "fast": []}
    assert render({}, rank({}, 3), new_entries(rank({}, 3), {})) == "No models with a coding index."


def test_new_entries_against_previous_snapshot_only():
    ranks = {"top": ["a", "b"], "value": ["b"], "fast": []}
    assert new_entries(ranks, {}) == {"top": set(), "value": set(), "fast": set()}
    assert new_entries(ranks, {"top": ["a"], "value": ["b"]}) == {"top": {"b"}, "value": set(), "fast": set()}


def test_render_lines_link_and_markers():
    models = normalize([model("a", coding=60, price=2, tps=120.4, slug="model-a")])
    ranks = rank(models, 5)
    out = render(models, ranks, {"top": {"a"}, "value": set(), "fast": set()})
    assert "### Highest coding index" in out
    assert "- A (Acme): coding index 60; $2/1M blended (in $2, out $2); 120 tok/s" in out
    assert "https://artificialanalysis.ai/models/model-a; NEW in this list" in out
    assert "(30.0 points per $)" in out
