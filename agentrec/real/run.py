"""Run separate AgentRecBench real-log smoke/pilot evaluations."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agentrec.agent.trace import TrajectoryRecorder
from agentrec.data import load_processed_subset
from agentrec.experiments.config import code_fingerprint, git_commit, load_config
from agentrec.experiments.metrics import aggregate_records, recommendation_metrics
from agentrec.real.ranking import rank_real_task


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _error_row(task: Any, system: str, error: BaseException) -> Dict[str, Any]:
    return {
        "task_id": str(getattr(task, "task_id", "unknown")),
        "scenario": str(getattr(task, "scenario", "unknown")),
        "system": system,
        "controlled": False,
        "data_type": "real_log",
        "source": "agentrecbench_amazon_short_v1",
        "trajectory": [
            {
                "step": 1,
                "selected_action": "runtime_error",
                "observation": None,
                "action_arguments": None,
                "tool_result": None,
                "memory_reads": [],
                "memory_writes": [],
                "constraint_check": None,
                "latency_ms": 0.0,
                "token_usage": {"input": 0, "output": 0},
                "estimated_cost_usd": 0.0,
                "error": "%s: %s" % (type(error).__name__, error),
            }
        ],
        "final_product_ids": [],
        "metrics": {"task_success_rate": 0.0},
        "token_usage": {"input": 0, "output": 0},
        "estimated_cost_usd": 0.0,
        "error": "%s: %s" % (type(error).__name__, error),
        "traceback": "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )[-8000:],
    }


def _run_one(task, system, products_by_id, reviews_by_id):
    trace = TrajectoryRecorder()
    history = [reviews_by_id[review_id] for review_id in task.review_ids]
    trace.add(
        "observe_real_task",
        observation={
            "task_id": task.task_id,
            "scenario": task.scenario,
            "candidate_count": len(task.candidate_ids),
            "controlled": False,
        },
        reason="establish the fixed real-log candidate set without exposing ground truth",
    )
    trace.add(
        "retrieve_profile_history",
        arguments={"history_scope": "same_user_short_term"},
        tool_result={
            "review_count": len(history),
            "review_ids": [str(row.get("review_id") or "") for row in history],
        },
        memory_reads=history,
        reason="read only this benchmark user's observed short-term history",
    )
    trace.add(
        "inspect_candidate_catalog",
        arguments={"candidate_ids": task.candidate_ids},
        tool_result={
            "products": [
                {
                    "product_id": products_by_id[item_id].product_id,
                    "name": products_by_id[item_id].name,
                    "category": products_by_id[item_id].category,
                    "brand": products_by_id[item_id].brand,
                    "rating": products_by_id[item_id].rating,
                    "review_count": products_by_id[item_id].review_count,
                }
                for item_id in task.candidate_ids
            ]
        },
        reason="ground ranking in the fixed candidate metadata",
    )
    ranked, audit = rank_real_task(
        system=system,
        task=task,
        products_by_id=products_by_id,
        reviews=history,
        limit=5,
    )
    trace.add(
        "rank_candidates",
        arguments={"system": system, "limit": 5},
        tool_result={"ranked_ids": ranked, "audit": audit},
        reason="apply the preregistered target-blind baseline",
    )
    trace.add(
        "finish",
        tool_result={"final_product_ids": ranked},
        reason="terminate the static one-shot benchmark episode",
    )
    metrics = recommendation_metrics(ranked, [task.target_product_id])
    metrics.update(
        {
            "task_success_rate": metrics["hr_at_1"],
            "mean_turns": 1.0,
            "mean_tool_calls": 3.0,
            "mean_latency_ms": trace.latency_ms,
            "mean_token_usage": 0.0,
        }
    )
    return {
        "task_id": task.task_id,
        "scenario": task.scenario,
        "task": task.to_dict(),
        "system": system,
        "controlled": False,
        "data_type": "real_log",
        "source": task.source,
        "metric_applicability": {
            "task_success_rate": "exact held-out target at rank 1; not controlled interactive success",
            "hard_constraint_satisfaction_rate": "not_applicable",
            "profile_contamination_rate": "not_applicable",
            "recovery_success_rate": "not_applicable",
        },
        "trajectory": trace.steps,
        "final_product_ids": ranked,
        "target_product_id": task.target_product_id,
        "metrics": metrics,
        "latency_ms": trace.latency_ms,
        "token_usage": {"input": 0, "output": 0},
        "estimated_cost_usd": 0.0,
        "error": None,
    }


def run_real_experiment(config_path: str, max_tasks_override: Optional[int] = None) -> Path:
    config, config_hash = load_config(config_path)
    project_root = Path(config_path).resolve().parents[2]
    experiment = dict(config.get("experiment") or {})
    data = dict(config.get("data") or {})
    if data.get("controlled") is not False or data.get("data_type") != "real_log":
        raise ValueError("real runner requires controlled=false and data_type=real_log")
    dataset_path = Path(str(data["path"]))
    if not dataset_path.is_absolute():
        dataset_path = project_root / dataset_path
    subset = load_processed_subset(dataset_path)
    max_tasks = int(max_tasks_override or experiment.get("max_tasks", 20))
    tasks = subset.tasks[:max_tasks]
    systems = [str(value) for value in config.get("systems") or []]
    if not tasks or not systems:
        raise ValueError("real experiment requires tasks and systems")
    stage = str(experiment.get("stage") or "real_smoke")
    started_at = _utc_now()
    run_id = "%s-%s-%s-%s" % (
        experiment.get("name", "agentrec_real"),
        config_hash,
        datetime.now().strftime("%Y%m%dT%H%M%S"),
        uuid.uuid4().hex[:6],
    )
    output_root = Path(str(experiment.get("output_dir") or ("results/raw/%s" % stage)))
    if not output_root.is_absolute():
        output_root = project_root / output_root
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    revision = git_commit(project_root)
    code_hash = code_fingerprint(project_root)
    manifest = {
        "run_id": run_id,
        "stage": stage,
        "started_at": started_at,
        "config_path": str(Path(config_path).resolve()),
        "config_hash": config_hash,
        "git_commit": revision,
        "code_hash": code_hash,
        "python": sys.version,
        "controlled": False,
        "data_type": "real_log",
        "data_source": subset.manifest,
        "systems": systems,
        "max_tasks_per_system": len(tasks),
        "config": config,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    records: List[Dict[str, Any]] = []
    trajectory_path = run_dir / "trajectories.jsonl"
    with trajectory_path.open("w", encoding="utf-8", buffering=1) as stream:
        for system in systems:
            for task in tasks:
                try:
                    row = _run_one(task, system, subset.products_by_id, subset.reviews_by_id)
                except Exception as exc:
                    row = _error_row(task, system, exc)
                row.update(
                    {
                        "run_id": run_id,
                        "stage": stage,
                        "config_hash": config_hash,
                        "git_commit": revision,
                        "code_hash": code_hash,
                    }
                )
                records.append(row)
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
    evaluation = dict(config.get("evaluation") or {})
    summary = aggregate_records(
        records,
        bootstrap_samples=int(evaluation.get("bootstrap_samples", 1000)),
        confidence=float(evaluation.get("confidence_level", 0.95)),
        seed=int(experiment.get("seed", 42)),
    )
    summary.update(
        {
            "run_id": run_id,
            "stage": stage,
            "config_hash": config_hash,
            "git_commit": revision,
            "code_hash": code_hash,
            "controlled": False,
            "data_type": "real_log",
            "started_at": started_at,
            "finished_at": _utc_now(),
            "metric_boundary": "Interactive hard-constraint, contamination, clarification, and recovery metrics are not applicable to this static benchmark.",
            "raw_run_dir": run_dir.relative_to(project_root).as_posix(),
            "trajectories_file": trajectory_path.relative_to(project_root).as_posix(),
        }
    )
    serialised = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    (run_dir / "summary.json").write_text(serialised, encoding="utf-8")
    summary_dir = project_root / "results" / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / (stage + "_summary.json")).write_text(serialised, encoding="utf-8")
    print("completed %s: %d records -> %s" % (stage, len(records), run_dir))
    return run_dir


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-tasks", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    run_real_experiment(args.config, args.max_tasks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
