import json
from pathlib import Path

from agentrec.reports.build import build_report, discover_records


def _record(run_id, success):
    return {
        "run_id": run_id,
        "stage": "full",
        "task_id": "t1",
        "scenario": "clear_single_turn",
        "controlled": True,
        "config_hash": "cfg",
        "git_commit": "rev",
        "code_hash": "code",
        "seed": 42,
        "system": "fixed_pipeline",
        "trajectory": [{"selected_action": "recommend"}],
        "final_product_ids": ["p1"],
        "metrics": {
            "task_success_rate": float(success),
            "hard_constraint_satisfaction_rate": 1.0,
            "profile_contamination_rate": 0.0,
            "recovery_success_rate": None,
            "hr_at_5": 1.0,
            "ndcg_at_5": 1.0,
        },
        "error": None,
        "bootstrap_samples": 20,
        "confidence_level": 0.95,
    }


def test_report_is_generated_only_from_saved_records(tmp_path):
    run = tmp_path / "full" / "run-a"
    run.mkdir(parents=True)
    (run / "trajectories.jsonl").write_text(
        json.dumps(_record("run-a", True)) + "\n", encoding="utf-8"
    )
    records = discover_records(tmp_path)
    output = tmp_path / "report.md"
    build_report(records, output)
    text = output.read_text(encoding="utf-8")
    assert "1 unfiltered per-task records" in text
    assert "all reported tasks are controlled" in text
    assert "fixed_pipeline" in text
    assert "Run ID: run-a" in text
    assert "Dirty-tree code fingerprint(s): code" in text
    assert "Stale-memory misuse" in text


def test_report_keeps_real_and_llm_extensions_separate(tmp_path):
    summaries = tmp_path / "results" / "summary"
    summaries.mkdir(parents=True)
    metric = {"n": 1, "mean": 0.5, "ci_low": 0.25, "ci_high": 0.75}
    systems = {
        name: {
            "n": 1,
            "metrics": {
                "task_success_rate": metric,
                "hr_at_3": metric,
                "hr_at_5": metric,
                "ndcg_at_5": metric,
            },
        }
        for name in ("candidate_order", "popularity", "full_history_lexical", "short_term_recency")
    }
    (summaries / "real_pilot_summary.json").write_text(
        json.dumps({"run_id": "real-run", "n_records": 4, "systems": systems}),
        encoding="utf-8",
    )
    (summaries / "llm_smoke_summary.json").write_text(
        json.dumps(
            {
                "run_id": "llm-run",
                "model": "gpt-5.6-terra",
                "stop_reason": "stopped_on_error",
                "saved_records": 1,
                "budget_after": {
                    "settled_cost_usd": 0,
                    "charged_or_reserved_usd": 0.02,
                    "remaining_usd": 9.98,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "reports" / "final_report.md"
    build_report([_record("run-a", True)], output)
    text = output.read_text(encoding="utf-8")
    assert "Independently scoped extensions" in text
    assert "real-run" in text
    assert "Exact target@1 is a static ranking label" in text
    assert "llm-run" in text
    assert "no inference-quality result is claimed" in text.lower()


def test_report_prefers_llm_pilot_and_keeps_negative_mechanism_signals(tmp_path):
    summaries = tmp_path / "results" / "summary"
    raw = tmp_path / "results" / "raw" / "llm_pilot" / "pilot-run"
    summaries.mkdir(parents=True)
    raw.mkdir(parents=True)
    metric = {"n": 1, "mean": 1.0, "ci_low": 1.0, "ci_high": 1.0}
    system = {
        "n": 1,
        "metrics": {
            "task_success_rate": metric,
            "hard_constraint_satisfaction_rate": metric,
            "profile_contamination_rate": {**metric, "mean": 0.0, "ci_low": 0.0, "ci_high": 0.0},
            "recovery_success_rate": metric,
            "useful_clarification_rate": metric,
            "mean_tool_calls": metric,
        },
    }
    trajectory = {
        "task_id": "pilot-task-1",
        "trajectory": [
            {"tool_result": {"ignored_function_calls": [{"name": "inspect_catalog"}]}}
        ],
        "metrics": {"useful_clarification_rate": 0.0},
        "token_usage": {"input": 10, "cached_input": 2, "output": 3},
        "estimated_cost_usd": 0.01,
    }
    (raw / "trajectories.jsonl").write_text(json.dumps(trajectory) + "\n", encoding="utf-8")
    (summaries / "llm_pilot_summary.json").write_text(
        json.dumps(
            {
                "run_id": "pilot-run",
                "model": "gpt-5.5",
                "stop_reason": "completed",
                "saved_records": 1,
                "systems": {"llm_full_agent": system},
                "budget_after": {"settled_cost_usd": 0.01},
                "overall_budget_after": {"charged_or_reserved_usd": 0.02, "remaining_usd": 9.98},
                "trajectories_file": "results/raw/llm_pilot/pilot-run/trajectories.jsonl",
                "cost_basis": "reference estimate",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "reports" / "final_report.md"
    build_report([_record("run-a", True)], output)
    text = output.read_text(encoding="utf-8")
    assert "Paid LLM controlled pilot" in text
    assert "pilot-run" in text
    assert "1 extra provider tool calls" in text
    assert "1 did not" in text
    assert "10 input, 2 cached-input, and 3 output tokens" in text
    assert "pilot-task-1" in text
    assert "trajectories.jsonl:1" in text
