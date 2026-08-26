from agentrec.experiments.bootstrap import bootstrap_mean_ci, paired_bootstrap_difference
from agentrec.experiments.metrics import (
    aggregate_records,
    ndcg,
    paired_system_comparisons,
    recommendation_metrics,
)


def test_recommendation_metrics_are_deterministic():
    values = recommendation_metrics(["p2", "p1", "p3"], ["p1"])
    assert values["hr_at_1"] == 0.0
    assert values["hr_at_3"] == 1.0
    assert 0.0 < values["ndcg_at_3"] < 1.0
    assert ndcg([], ["p1"], 5) == 0.0


def test_bootstrap_fixed_seed_and_paired_difference():
    first = bootstrap_mean_ci([0, 1, 1, 0], samples=200, seed=7)
    second = bootstrap_mean_ci([0, 1, 1, 0], samples=200, seed=7)
    assert first == second
    assert first["mean"] == 0.5
    paired = paired_bootstrap_difference([1, 1, 0], [0, 1, 0], samples=100, seed=3)
    assert paired["mean"] == 1 / 3


def test_aggregate_keeps_failures_and_ignores_undefined_recovery():
    rows = [
        {
            "system": "x",
            "metrics": {
                "task_success_rate": 1.0,
                "hard_constraint_satisfaction_rate": 1.0,
                "profile_contamination_rate": 0.0,
                "recovery_success_rate": None,
            },
            "error": None,
        },
        {
            "system": "x",
            "metrics": {
                "task_success_rate": 0.0,
                "hard_constraint_satisfaction_rate": 0.0,
                "profile_contamination_rate": 0.0,
                "recovery_success_rate": 0.0,
            },
            "error": None,
        },
    ]
    summary = aggregate_records(rows, bootstrap_samples=100, confidence=0.95, seed=1)["systems"]["x"]
    assert summary["n"] == 2
    assert summary["metrics"]["task_success_rate"]["mean"] == 0.5
    assert summary["metrics"]["recovery_success_rate"]["n"] == 1
    assert summary["failure_counts"]["hard_constraint_violation"] == 1


def test_paired_comparison_matches_same_task_and_seed_only():
    rows = []
    for system, values in {"full_agent": [1.0, 1.0], "fixed_pipeline": [0.0, 1.0]}.items():
        for index, value in enumerate(values):
            rows.append(
                {
                    "system": system,
                    "seed": 42,
                    "task_id": f"t{index}",
                    "metrics": {"task_success_rate": value},
                }
            )
    result = paired_system_comparisons(
        rows,
        bootstrap_samples=100,
        confidence=0.95,
        seed=9,
        metrics=["task_success_rate"],
    )["fixed_pipeline"]
    assert result["common_episodes"] == 2
    assert result["metrics"]["task_success_rate"]["mean"] == 0.5
