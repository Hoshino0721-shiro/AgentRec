"""Run smoke, pilot, or full AgentRec experiments with per-task persistence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from agentrec.agent.policy import features_for_system
from agentrec.experiments.config import code_fingerprint, git_commit, load_config
from agentrec.experiments.metrics import aggregate_records, paired_system_comparisons


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_record(
    *,
    run_id: str,
    config_hash: str,
    revision: str,
    code_hash: str,
    stage: str,
    seed: int,
    system: str,
    task: Any,
    error: BaseException,
    bootstrap_samples: int,
    confidence: float,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "config_hash": config_hash,
        "git_commit": revision,
        "code_hash": code_hash,
        "stage": stage,
        "task_id": str(getattr(task, "task_id", "unknown")),
        "scenario": str(getattr(task, "scenario", "unknown")),
        "controlled": bool(getattr(task, "controlled", True)),
        "seed": seed,
        "system": system,
        "features": features_for_system(system).to_dict(),
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
                "error": f"{type(error).__name__}: {error}",
            }
        ],
        "final_product_ids": [],
        "metrics": {
            "task_success_rate": 0.0,
            "hard_constraint_satisfaction_rate": 0.0,
            "profile_contamination_rate": 0.0,
            "recovery_success_rate": None,
            "mean_turns": 0.0,
            "mean_tool_calls": 0.0,
            "mean_latency_ms": 0.0,
            "mean_token_usage": 0.0,
        },
        "latency_ms": 0.0,
        "token_usage": {"input": 0, "output": 0},
        "estimated_cost_usd": 0.0,
        "error": f"{type(error).__name__}: {error}",
        "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))[-8000:],
        "bootstrap_samples": bootstrap_samples,
        "confidence_level": confidence,
    }


def _pilot_gate(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    actions = {
        str(step.get("selected_action"))
        for row in records
        for step in row.get("trajectory", [])
        if isinstance(step, dict) and step.get("selected_action")
    }
    has_tool_results = any(
        step.get("tool_result") not in (None, "", [], {})
        for row in records
        for step in row.get("trajectory", [])
        if isinstance(step, dict)
    )
    memory_rows = [row for row in records if row.get("system") in {"agent_flat_memory", "agent_hierarchical_memory"}]
    has_memory_activity = any(
        bool(step.get("memory_reads") or step.get("memory_writes"))
        for row in memory_rows
        for step in row.get("trajectory", [])
        if isinstance(step, dict)
    )
    by_system: Dict[str, Dict[str, float]] = {}
    for system in {str(row.get("system")) for row in records}:
        rows = [row for row in records if row.get("system") == system]
        by_system[system] = {}
        for metric in ("task_success_rate", "hard_constraint_satisfaction_rate", "profile_contamination_rate"):
            values = [row.get("metrics", {}).get(metric) for row in rows]
            values = [float(value) for value in values if value is not None]
            if values:
                by_system[system][metric] = sum(values) / len(values)
    flat = by_system.get("agent_flat_memory", {})
    hierarchical = by_system.get("agent_hierarchical_memory", {})
    contamination_signal = (
        "profile_contamination_rate" in flat
        and "profile_contamination_rate" in hierarchical
        and hierarchical["profile_contamination_rate"] < flat["profile_contamination_rate"]
    )
    reliability_signal = (
        hierarchical.get("task_success_rate", 0.0) > by_system.get("fixed_pipeline", {}).get("task_success_rate", 0.0)
        or hierarchical.get("hard_constraint_satisfaction_rate", 0.0)
        > by_system.get("fixed_pipeline", {}).get("hard_constraint_satisfaction_rate", 0.0)
    )
    error_rate = sum(bool(row.get("error")) for row in records) / max(1, len(records))
    checks = {
        "closed_loop": bool(records) and error_rate == 0.0 and all(row.get("trajectory") for row in records),
        "action_diversity": len(actions) >= 5,
        "tools_used": has_tool_results,
        "memory_used": has_memory_activity,
        "mechanism_signal": contamination_signal or reliability_signal,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "action_types": sorted(actions),
        "error_rate": error_rate,
        "system_point_estimates": by_system,
        "note": "Gate checks execution integrity and at least one preregistered mechanism signal; it does not select the best-looking system.",
    }


def _latest_passed_pilot(project_root: Path) -> Optional[Path]:
    gates = sorted(
        (project_root / "results" / "raw" / "pilot").rglob("pilot_gate.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if (project_root / "results" / "raw" / "pilot").exists() else []
    for path in gates:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("passed"):
                return path
        except Exception:
            continue
    return None


def run_experiment(config_path: str, *, max_tasks_override: Optional[int] = None) -> Path:
    config, config_hash = load_config(config_path)
    project_root = Path(config_path).resolve().parents[2]
    experiment = config["experiment"]
    stage = str(experiment["stage"])
    passed_pilot = _latest_passed_pilot(project_root) if stage == "full" else None
    if stage == "full" and passed_pilot is None:
        raise RuntimeError("full experiment is blocked until a saved pilot_gate.json passes; run pilot.yaml first")

    from agentrec.agent.orchestrator import ShoppingAgent
    from agentrec.simulation.scenarios import build_tasks
    from agentrec.tools.catalog import CatalogTool, load_catalog

    seeds = [int(seed) for seed in experiment.get("seeds", [42])]
    max_tasks = int(max_tasks_override or experiment.get("max_tasks", 20))
    systems = [str(system) for system in config.get("systems", [])]
    scenarios = list(config.get("data", {}).get("scenarios") or [])
    evaluation = config.get("evaluation", {})
    bootstrap_samples = int(evaluation.get("bootstrap_samples", 2000))
    confidence = float(evaluation.get("confidence_level", 0.95))
    revision = git_commit(Path.cwd())
    code_hash = code_fingerprint(project_root)
    if passed_pilot is not None:
        pilot_data = json.loads(passed_pilot.read_text(encoding="utf-8"))
        if pilot_data.get("code_hash") != code_hash:
            raise RuntimeError(
                "full experiment code hash does not match the latest passed pilot; rerun pilot.yaml after code changes"
            )
    started_at = _utc_now()
    run_id = (
        f"{experiment.get('name', 'agentrec')}-{config_hash}-"
        f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    )
    configured_output = Path(str(experiment.get("output_dir", f"results/raw/{stage}")))
    output_root = configured_output if configured_output.is_absolute() else project_root / configured_output
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "run_id": run_id,
        "name": experiment.get("name"),
        "stage": stage,
        "started_at": started_at,
        "config_path": str(Path(config_path).resolve()),
        "config_hash": config_hash,
        "git_commit": revision,
        "code_hash": code_hash,
        "python": sys.version,
        "platform": sys.platform,
        "controlled": bool(config.get("data", {}).get("controlled", True)),
        "data_source": config.get("data", {}).get("source"),
        "seeds": seeds,
        "systems": systems,
        "max_tasks_per_system_seed": max_tasks,
        "bootstrap_samples": bootstrap_samples,
        "confidence_level": confidence,
        "config": config,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    products = load_catalog()
    records: List[Dict[str, Any]] = []
    trajectory_path = run_dir / "trajectories.jsonl"
    with trajectory_path.open("w", encoding="utf-8", buffering=1) as stream:
        for seed in seeds:
            tasks = build_tasks(count=max_tasks, seed=seed, scenarios=scenarios)
            for system in systems:
                for task in tasks:
                    try:
                        # Each controlled row is an independent user episode.
                        # Its frozen longitudinal history arrives through
                        # task.initial_memories; sharing a store here would let
                        # one evaluation sample alter the next sample.
                        agent = ShoppingAgent(
                            system=system,
                            catalog=CatalogTool(products),
                            seed=seed,
                            max_turns=int(config.get("agent", {}).get("max_turns", 8)),
                            max_tool_calls=int(config.get("agent", {}).get("max_tool_calls", 12)),
                        )
                        row = agent.run_task(task)
                        row.update(
                            {
                                "run_id": run_id,
                                "config_hash": config_hash,
                                "git_commit": revision,
                                "code_hash": code_hash,
                                "stage": stage,
                                "seed": seed,
                                "system": system,
                                "controlled": bool(getattr(task, "controlled", True)),
                                "bootstrap_samples": bootstrap_samples,
                                "confidence_level": confidence,
                            }
                        )
                    except Exception as exc:  # persist every failed sample before continuing
                        row = _safe_record(
                            run_id=run_id,
                            config_hash=config_hash,
                            revision=revision,
                            code_hash=code_hash,
                            stage=stage,
                            seed=seed,
                            system=system,
                            task=task,
                            error=exc,
                            bootstrap_samples=bootstrap_samples,
                            confidence=confidence,
                        )
                    records.append(row)
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    stream.flush()

    summary = aggregate_records(
        records,
        bootstrap_samples=bootstrap_samples,
        confidence=confidence,
        seed=seeds[0] if seeds else 0,
    )
    if "full_agent" in systems:
        summary["paired_comparisons"] = paired_system_comparisons(
            records,
            reference="full_agent",
            bootstrap_samples=bootstrap_samples,
            confidence=confidence,
            seed=seeds[0] if seeds else 0,
        )
    summary.update(
        {
            "run_id": run_id,
            "stage": stage,
            "config_hash": config_hash,
            "git_commit": revision,
            "code_hash": code_hash,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "raw_run_dir": run_dir.relative_to(project_root).as_posix(),
            "trajectories_file": trajectory_path.relative_to(project_root).as_posix(),
        }
    )
    serialized_summary = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    (run_dir / "summary.json").write_text(serialized_summary, encoding="utf-8")
    summary_dir = project_root / "results" / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / f"{stage}_summary.json").write_text(serialized_summary, encoding="utf-8")
    if stage == "pilot":
        gate = _pilot_gate(records)
        gate.update({"run_id": run_id, "config_hash": config_hash, "code_hash": code_hash})
        serialized_gate = json.dumps(gate, ensure_ascii=False, indent=2) + "\n"
        (run_dir / "pilot_gate.json").write_text(serialized_gate, encoding="utf-8")
        (summary_dir / "pilot_gate.json").write_text(serialized_gate, encoding="utf-8")
    print(f"completed {stage}: {len(records)} records -> {run_dir}")
    return run_dir


def parse_args(argv: Iterable[str] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="experiment YAML")
    parser.add_argument("--max-tasks", type=int, default=None, help="debug-only task cap")
    return parser.parse_args(argv)


def main(argv: Iterable[str] = None) -> int:
    args = parse_args(argv)
    run_experiment(args.config, max_tasks_override=args.max_tasks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
