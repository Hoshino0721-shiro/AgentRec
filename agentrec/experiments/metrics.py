"""Per-task deterministic evaluation and aggregate statistics."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .bootstrap import bootstrap_mean_ci, paired_bootstrap_difference


PRIMARY_METRICS = (
    "task_success_rate",
    "hard_constraint_satisfaction_rate",
    "profile_contamination_rate",
    "recovery_success_rate",
)

RECOMMENDATION_METRICS = (
    "hr_at_1",
    "hr_at_3",
    "hr_at_5",
    "ndcg_at_3",
    "ndcg_at_5",
    "recall_at_5",
)


def hit_rate(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant = set(relevant_ids)
    return float(any(product_id in relevant for product_id in ranked_ids[:k]))


def ndcg(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    dcg = 0.0
    for index, product_id in enumerate(ranked_ids[:k]):
        if product_id in relevant:
            dcg += 1.0 / math.log2(index + 2)
    ideal_count = min(k, len(relevant))
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return dcg / idcg if idcg else 0.0


def recall(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    return len(relevant.intersection(ranked_ids[:k])) / len(relevant)


def recommendation_metrics(ranked_ids: Sequence[str], relevant_ids: Iterable[str]) -> Dict[str, float]:
    relevant = list(relevant_ids)
    return {
        "hr_at_1": hit_rate(ranked_ids, relevant, 1),
        "hr_at_3": hit_rate(ranked_ids, relevant, 3),
        "hr_at_5": hit_rate(ranked_ids, relevant, 5),
        "ndcg_at_3": ndcg(ranked_ids, relevant, 3),
        "ndcg_at_5": ndcg(ranked_ids, relevant, 5),
        "recall_at_5": recall(ranked_ids, relevant, 5),
    }


def classify_failure(record: Mapping[str, Any]) -> str:
    if record.get("error"):
        return "runtime_error"
    metrics = record.get("metrics") or {}
    if metrics.get("hard_constraint_satisfaction_rate", 1.0) < 1.0:
        return "hard_constraint_violation"
    if metrics.get("profile_contamination_rate", 0.0) > 0.0:
        return "profile_contamination"
    if record.get("rejection_occurred") and metrics.get("recovery_success_rate", 0.0) < 1.0:
        return "failed_recovery"
    if metrics.get("task_success_rate", 0.0) < 1.0:
        return "irrelevant_or_unaccepted_recommendation"
    return "success"


def aggregate_records(
    records: Sequence[Mapping[str, Any]],
    *,
    bootstrap_samples: int,
    confidence: float,
    seed: int,
) -> Dict[str, Any]:
    """Aggregate records by system; every mean retains a sample count and CI."""
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("system", "unknown"))].append(record)

    systems: Dict[str, Any] = {}
    for system, rows in sorted(grouped.items()):
        metric_names = sorted({name for row in rows for name in (row.get("metrics") or {}).keys()})
        metric_summary: Dict[str, Any] = {}
        for offset, name in enumerate(metric_names):
            values = [row.get("metrics", {}).get(name) for row in rows]
            values = [float(value) for value in values if value is not None]
            if not values:
                continue
            metric_summary[name] = {
                "n": len(values),
                **bootstrap_mean_ci(
                    values,
                    samples=bootstrap_samples,
                    confidence=confidence,
                    seed=seed + offset,
                ),
            }
        failures = Counter(classify_failure(row) for row in rows)
        systems[system] = {
            "n": len(rows),
            "metrics": metric_summary,
            "failure_counts": dict(sorted(failures.items())),
            "error_count": sum(1 for row in rows if row.get("error")),
        }
    return {"n_records": len(records), "systems": systems}


def paired_system_comparisons(
    records: Sequence[Mapping[str, Any]],
    *,
    reference: str = "full_agent",
    metrics: Sequence[str] = PRIMARY_METRICS,
    bootstrap_samples: int,
    confidence: float,
    seed: int,
) -> Dict[str, Any]:
    """Compare systems on identical (seed, task_id) episodes."""
    indexed: Dict[str, Dict[Any, Mapping[str, Any]]] = defaultdict(dict)
    for row in records:
        key = (row.get("seed"), row.get("task_id"))
        indexed[str(row.get("system"))][key] = row
    reference_rows = indexed.get(reference, {})
    comparisons: Dict[str, Any] = {}
    for system, rows in sorted(indexed.items()):
        if system == reference:
            continue
        metric_results: Dict[str, Any] = {}
        common_keys = sorted(set(reference_rows).intersection(rows), key=str)
        for offset, metric in enumerate(metrics):
            left: List[float] = []
            right: List[float] = []
            for key in common_keys:
                left_value = (reference_rows[key].get("metrics") or {}).get(metric)
                right_value = (rows[key].get("metrics") or {}).get(metric)
                if left_value is None or right_value is None:
                    continue
                left.append(float(left_value))
                right.append(float(right_value))
            if left:
                metric_results[metric] = {
                    "n_pairs": len(left),
                    **paired_bootstrap_difference(
                        left,
                        right,
                        samples=bootstrap_samples,
                        confidence=confidence,
                        seed=seed + offset,
                    ),
                }
        comparisons[system] = {
            "reference": reference,
            "common_episodes": len(common_keys),
            "metrics": metric_results,
        }
    return comparisons
