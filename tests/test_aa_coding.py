import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aa_coding import family, frontier, latest, line, new_entries, normalize, rank, render, unscored_newer  # noqa: E402


def model(model_id, coding=50, price=1.0, tps=100, slug=None, name=None, creator="Acme"):
    return {
        "id": model_id,
        "name": name or model_id.upper(),
        "slug": slug or model_id,
        "model_creator": {"name": creator},
        "evaluations": {"artificial_analysis_coding_index": coding},
        "pricing": {"price_1m_blended_3_to_1": price, "price_1m_input_tokens": price, "price_1m_output_tokens": price},
        "median_output_tokens_per_second": tps,
    }


def test_normalize_keeps_missing_coding_index_price_and_speed_as_none():
    raw = [model("a"), model("b", price=None, tps=0)]
    raw.append({**model("c"), "evaluations": {}})
    models = normalize(raw)
    assert sorted(models) == ["a", "b", "c"]
    assert models["b"]["price"] is None
    assert models["b"]["tps"] is None
    assert models["c"]["coding"] is None


def test_line_ignores_version_numbers_effort_and_preview():
    assert line("Gemini 3.8 Flash (High)") == line("Gemini 3.7 Flash") == "gemini flash"
    assert line("Gemini 3.1 Pro Preview") == line("Gemini 3 Pro") == "gemini pro"
    assert line("Claude Opus 5 (Max)") == line("Claude Opus 5.5") == "claude opus"
    assert line("GPT-5.6 Sol (Xhigh)") != line("GPT-6 Astra (High)")
    assert line("Gemini 3.8 Flash") != line("Gemini 3.8 Flash-Lite")


def test_latest_keeps_only_newest_version_with_all_its_effort_variants():
    models = normalize(
        [
            model("f38h", name="Gemini 3.8 Flash (High)"),
            model("f38m", name="Gemini 3.8 Flash (Medium)"),
            model("f37", name="Gemini 3.7 Flash (High)"),
            model("o5", name="Claude Opus 5 (Max)"),
            model("o48", name="Claude Opus 4.8"),
            model("sol", name="GPT-5.6 Sol"),
        ]
    )
    assert sorted(latest(models)) == ["f38h", "f38m", "o5", "sol"]


def test_unscored_newer_version_is_reported_and_older_one_stays_ranked():
    raw = [model("o5", name="Claude Opus 5 (Max)", coding=78), model("o55", name="Claude Opus 5.5 (Max)")]
    raw[1]["evaluations"] = {}
    raw.append({**model("new-line", name="Brand New 1"), "evaluations": {}})
    models = normalize(raw)
    ranked = latest({i: m for i, m in models.items() if m["coding"] is not None})
    assert sorted(ranked) == ["o5"]
    assert unscored_newer(models, ranked) == ["Claude Opus 5.5"]
    out = render(ranked, rank(ranked, 5), {"top": set(), "value": set(), "fast": set()}, ["Claude Opus 5.5"])
    assert "### Newer versions without a coding index yet" in out
    assert out.endswith("\n- Claude Opus 5.5")


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
    assert render({}, rank({}, 3), new_entries(rank({}, 3), {}, {})) == "No models with a coding index."


def test_new_entries_compare_families_against_previous_snapshot_only():
    models = normalize([model("a", name="Fable 5.1 (High)"), model("b", name="Luna")])
    ranks = {"top": ["a", "b"], "value": ["b"], "fast": []}
    assert new_entries(ranks, models, {}) == {"top": set(), "value": set(), "fast": set()}
    # a different effort variant of a family already listed is not new
    previous = {"top": ["Fable 5.1"], "value": ["Luna"]}
    assert new_entries(ranks, models, previous) == {"top": {"b"}, "value": set(), "fast": set()}


def test_snapshot_with_only_empty_lists_is_not_a_baseline():
    models = normalize([model("a", name="Fable 5.1 (High)"), model("b", name="Luna")])
    ranks = {"top": ["a", "b"], "value": ["b"], "fast": []}
    empty = {"top": [], "value": [], "fast": []}
    assert new_entries(ranks, models, empty) == {"top": set(), "value": set(), "fast": set()}


def test_family_strips_effort_suffix():
    assert family("Claude Fable 5.1 (Max, Default Fallback)") == "Claude Fable 5.1"
    assert family("GPT-5.6 Luna (Xhigh)") == "GPT-5.6 Luna"
    assert family("Gemini 3.1 Pro Preview") == "Gemini 3.1 Pro Preview"


def test_each_family_appears_once_with_its_best_variant():
    models = normalize(
        [
            model("max", coding=81, name="Fable 5.1 (Max)", tps=60),
            model("xhigh", coding=80, name="Fable 5.1 (Xhigh)", tps=90),
            model("other", coding=70, name="Sol (High)", tps=50),
        ]
    )
    ranks = rank(models, 5)
    assert ranks["top"] == ["max", "other"]
    assert ranks["fast"] == ["xhigh", "other"]  # per list: the fastest Fable variant wins here


def test_frontier_keeps_closed_labs_and_drops_open_families():
    models = normalize(
        [
            model("fable", creator="Anthropic"),
            model("muse", creator="Meta", name="Muse Spark 1.3"),
            model("llama", creator="Meta", name="Llama 5 70B"),
            model("oss", creator="OpenAI", name="gpt-oss-240B (high)"),
            model("gemma", creator="Google", name="Gemma 4 27B"),
            model("grok", creator="xAI"),
            model("qwen", creator="Alibaba"),
        ]
    )
    assert sorted(frontier(models)) == ["fable", "grok", "muse"]


def test_render_lines_link_and_markers():
    models = normalize([model("a", coding=60, price=2, tps=120.4, slug="model-a")])
    ranks = rank(models, 5)
    out = render(models, ranks, {"top": {"a"}, "value": set(), "fast": set()})
    assert "### Highest coding index" in out
    assert "- A (Acme): coding index 60; $2/1M blended (in $2, out $2); 120 tok/s" in out
    assert "https://artificialanalysis.ai/models/model-a; NEW in this list" in out
    assert "(30.0 points per $)" in out
