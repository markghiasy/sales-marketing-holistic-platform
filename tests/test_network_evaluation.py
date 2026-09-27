from scripts.evaluate_network_demo import run_evaluation
from scripts.probe_graphiti import preflight


def test_evaluation_includes_executed_baselines_and_temporal_difference():
    report = run_evaluation()
    rows = report["results"]
    old = next(
        r
        for r in rows
        if r["scenario"] == "historical-employer" and r["policy"] == "temporal_context"
    )
    static = next(
        r for r in rows if r["scenario"] == "historical-employer" and r["policy"] == "filter_only"
    )
    assert old["returned_ids"] == ["person:alex"]
    assert static["returned_ids"] == []
    assert all(r["status"] == "executed" for r in rows)
    assert {r["policy"] for r in rows} == {"filter_only", "filter_recency", "temporal_context"}


def test_missing_graph_engine_is_unexecuted_not_a_score():
    result = preflight(package_available=False, store_configured=False)
    assert result["status"] == "unexecuted"
    assert "score" not in result and "latency" not in result
    assert result["missing"] == ["graphiti_core", "isolated graph store"]
