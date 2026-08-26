"""Run GPT-5.5 controlled Agent experiments with cost and transport gates."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agentrec.agent.policy import features_for_system
from agentrec.experiments.config import code_fingerprint, git_commit, load_config
from agentrec.experiments.metrics import aggregate_records
from agentrec.llm.budget import (
    BudgetExceeded,
    CostLedger,
    MODEL_PRICING_USD_PER_MILLION,
    charged_or_reserved_usd,
)
from agentrec.llm.controlled_agent import LLMControlledShoppingAgent
from agentrec.llm.openai_responses import OpenAIResponsesPolicy
from agentrec.llm.security import redact_api_secrets
from agentrec.simulation.scenarios import build_tasks
from agentrec.tools.catalog import CatalogTool, load_catalog


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _error_row(task, agent, error: BaseException) -> Dict[str, Any]:
    safe_error = "%s: %s" % (type(error).__name__, redact_api_secrets(error))
    trajectory = list(getattr(agent, "last_trace", None) or [])
    trajectory.append(
        {
            "step": len(trajectory) + 1,
            "selected_action": "runtime_error",
            "observation": None,
            "action_arguments": None,
            "tool_result": None,
            "memory_reads": [],
            "memory_writes": [],
            "constraint_check": None,
            "latency_ms": float(trajectory[-1].get("latency_ms", 0.0)) if trajectory else 0.0,
            "token_usage": {"input": 0, "cached_input": 0, "output": 0},
            "estimated_cost_usd": 0.0,
            "error": safe_error,
        }
    )
    return {
        "task_id": task.task_id,
        "scenario": task.scenario,
        "task": task.to_dict(),
        "system": "llm_full_agent",
        "model": getattr(getattr(agent, "policy", None), "model", "unknown"),
        "features": features_for_system("full_agent").to_dict(),
        "controlled": True,
        "trajectory": trajectory,
        "final_product_ids": [],
        "final_answer": "",
        "rejection_occurred": False,
        "accepted": False,
        "metrics": {
            "task_success_rate": 0.0,
            "hard_constraint_satisfaction_rate": 0.0,
            "profile_contamination_rate": 0.0,
            "recovery_success_rate": None,
            "mean_turns": 0.0,
            "mean_tool_calls": 0.0,
            "mean_latency_ms": 0.0,
            "mean_token_usage": float(
                sum((getattr(agent, "last_token_usage", None) or {}).values())
            ),
        },
        "latency_ms": 0.0,
        "token_usage": dict(
            getattr(agent, "last_token_usage", None)
            or {"input": 0, "cached_input": 0, "output": 0}
        ),
        "estimated_cost_usd": float(getattr(agent, "last_estimated_cost_usd", 0.0)),
        "memory_writes": [],
        "error": safe_error,
        "traceback": redact_api_secrets(
            "".join(traceback.format_exception(type(error), error, error.__traceback__))[-8000:]
        ),
    }


def run_llm_experiment(config_path: str, max_tasks_override: Optional[int] = None) -> Path:
    config, config_hash = load_config(config_path)
    project_root = Path(config_path).resolve().parents[2]
    experiment = dict(config.get("experiment") or {})
    data = dict(config.get("data") or {})
    agent_config = dict(config.get("agent") or {})
    api_config = dict(config.get("api") or {})
    if data.get("controlled") is not True or data.get("source") != "controlled_catalog":
        raise ValueError("LLM controlled runner requires controlled_catalog with controlled=true")
    model = str(agent_config.get("model") or "")
    provider = str(api_config.get("provider") or "")
    base_url = str(api_config.get("base_url") or "").rstrip("/")
    api_key_env = str(api_config.get("api_key_env") or "")
    insecure_http_ack_env = str(api_config.get("insecure_http_ack_env") or "")
    pricing_reference_model = str(api_config.get("pricing_reference_model") or "")
    if (
        provider != "agentrec_gateway"
        or model != "gpt-5.5"
        or not base_url
        or "${" in base_url
        or api_key_env != "AGENTREC_API_KEY"
        or insecure_http_ack_env != "AGENTREC_ALLOW_INSECURE_HTTP"
        or pricing_reference_model != "gpt-5.5"
    ):
        raise ValueError(
            "the paid API protocol requires agentrec_gateway/gpt-5.5 and "
            "an AGENTREC_BASE_URL value"
        )
    insecure_http_acknowledged = (
        os.environ.get(insecure_http_ack_env) == "I_ACCEPT_PLAINTEXT_HTTP"
    )
    if base_url.startswith("http://") and not insecure_http_acknowledged:
        raise RuntimeError(
            "plaintext HTTP endpoint is blocked; set %s only after accepting the risk"
            % insecure_http_ack_env
        )
    if not os.environ.get(api_key_env):
        raise RuntimeError("%s is not configured" % api_key_env)
    max_cost_usd = float(api_config.get("max_cost_usd") or os.environ.get("AGENTREC_MAX_COST_USD") or 10)
    ledger_path = project_root / "results" / "api_usage" / "agentrec_gateway_gpt-5.5_ledger.json"
    prior_model_reservations = round(
        sum(
            charged_or_reserved_usd(path)
            for path in sorted(ledger_path.parent.glob("*_ledger.json"))
            if path.resolve() != ledger_path.resolve()
        ),
        8,
    )
    model_cost_cap = round(max_cost_usd - prior_model_reservations, 8)
    if model_cost_cap <= 0:
        raise BudgetExceeded(
            "overall API cost cap is already exhausted by prior model ledgers"
        )
    reference_pricing = dict(MODEL_PRICING_USD_PER_MILLION[pricing_reference_model])
    reference_pricing.update(
        {
            "provider": provider,
            "provider_pricing_verified": False,
            "billing_basis": "OpenAI public GPT-5.5 reference estimate; not an AgentRec gateway invoice",
        }
    )
    ledger = CostLedger(
        ledger_path,
        model=model,
        max_cost_usd=model_cost_cap,
        pricing=reference_pricing,
    )
    policy = OpenAIResponsesPolicy(
        model=model,
        ledger=ledger,
        reasoning_effort=str(agent_config.get("reasoning_effort") or "low"),
        verbosity=str(agent_config.get("verbosity") or "low"),
        max_output_tokens=int(agent_config.get("max_output_tokens") or 500),
        api_key_env=api_key_env,
        base_url=base_url,
        allow_insecure_http=insecure_http_acknowledged,
    )

    seed = int(experiment.get("seed", 42))
    max_tasks = int(max_tasks_override or experiment.get("max_tasks", 20))
    scenarios = [str(value) for value in data.get("scenarios") or []]
    tasks = build_tasks(count=max_tasks, seed=seed, scenarios=scenarios)
    products = load_catalog()
    stage = str(experiment.get("stage") or "llm_smoke")
    started_at = _utc_now()
    run_id = "%s-%s-%s-%s" % (
        experiment.get("name", "agentrec_llm"),
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
        "controlled": True,
        "data_source": "controlled_catalog_v1",
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "transport_security": "plaintext_http_user_acknowledged",
        "provider_pricing_verified": False,
        "cost_basis": reference_pricing["billing_basis"],
        "api_key_configured": True,
        "api_state_storage": True,
        "budget_ledger": str(ledger_path),
        "overall_budget_cap_usd": max_cost_usd,
        "prior_model_charged_or_reserved_usd": prior_model_reservations,
        "budget_before": ledger.snapshot(),
        "requested_tasks": len(tasks),
        "seed": seed,
        "config": config,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    records: List[Dict[str, Any]] = []
    trajectory_path = run_dir / "trajectories.jsonl"
    stop_reason = "completed"
    stop_error: Optional[str] = None
    with trajectory_path.open("w", encoding="utf-8", buffering=1) as stream:
        for task in tasks:
            agent = LLMControlledShoppingAgent(
                catalog=CatalogTool(products),
                policy=policy,
                seed=seed,
                max_turns=int(agent_config.get("max_turns") or 8),
                max_tool_calls=int(agent_config.get("max_tool_calls") or 12),
                max_model_turns=int(agent_config.get("max_model_turns") or 12),
            )
            try:
                row = agent.run_task(task)
            except Exception as exc:
                row = _error_row(task, agent, exc)
                stop_reason = "budget_exhausted" if isinstance(exc, BudgetExceeded) else "stopped_on_error"
                stop_error = "%s: %s" % (type(exc).__name__, redact_api_secrets(exc))
            row.update(
                {
                    "run_id": run_id,
                    "stage": stage,
                    "config_hash": config_hash,
                    "git_commit": revision,
                    "code_hash": code_hash,
                    "seed": seed,
                    "controlled": True,
                }
            )
            records.append(row)
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            if row.get("error") and bool(experiment.get("stop_on_error", True)):
                break

    evaluation = dict(config.get("evaluation") or {})
    summary = aggregate_records(
        records,
        bootstrap_samples=int(evaluation.get("bootstrap_samples") or 500),
        confidence=float(evaluation.get("confidence_level") or 0.95),
        seed=seed,
    )
    budget_after = ledger.snapshot()
    overall_charged = round(
        prior_model_reservations + float(budget_after["charged_or_reserved_usd"]), 8
    )
    overall_budget_after = {
        "max_cost_usd": max_cost_usd,
        "charged_or_reserved_usd": overall_charged,
        "remaining_usd": round(max(0.0, max_cost_usd - overall_charged), 8),
        "prior_model_charged_or_reserved_usd": prior_model_reservations,
        "current_model": model,
    }
    summary.update(
        {
            "run_id": run_id,
            "stage": stage,
            "config_hash": config_hash,
            "git_commit": revision,
            "code_hash": code_hash,
            "controlled": True,
            "model": model,
            "provider": provider,
            "base_url": base_url,
            "provider_pricing_verified": False,
            "cost_basis": reference_pricing["billing_basis"],
            "requested_tasks": len(tasks),
            "saved_records": len(records),
            "stop_reason": stop_reason,
            "stop_error": stop_error,
            "budget_after": budget_after,
            "overall_budget_after": overall_budget_after,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "raw_run_dir": run_dir.relative_to(project_root).as_posix(),
            "trajectories_file": trajectory_path.relative_to(project_root).as_posix(),
        }
    )
    serialised = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    (run_dir / "summary.json").write_text(serialised, encoding="utf-8")
    (run_dir / "termination.json").write_text(
        json.dumps(
            {
                "stop_reason": stop_reason,
                "stop_error": stop_error,
                "requested_tasks": len(tasks),
                "saved_records": len(records),
                "budget": budget_after,
                "overall_budget": overall_budget_after,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    summary_dir = project_root / "results" / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / (stage + "_summary.json")).write_text(serialised, encoding="utf-8")
    print(
        "completed %s: %d/%d records, stop=%s, budget=%s -> %s"
        % (stage, len(records), len(tasks), stop_reason, overall_budget_after, run_dir)
    )
    return run_dir


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-tasks", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    run_llm_experiment(args.config, args.max_tasks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
