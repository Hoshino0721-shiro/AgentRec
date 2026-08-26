from agentrec.agent.orchestrator import ShoppingAgent
from agentrec.simulation.scenarios import build_tasks
from agentrec.tools.catalog import CatalogTool, load_catalog


def run(system, scenario):
    task = build_tasks(1, seed=42, scenarios=[scenario])[0]
    return ShoppingAgent(system=system, catalog=CatalogTool(load_catalog()), seed=42).run_task(task)


def actions(record):
    return [step["selected_action"] for step in record["trajectory"]]


def test_clarification_changes_visible_state_and_outcome():
    fixed = run("fixed_pipeline", "needs_clarification")
    full = run("full_agent", "needs_clarification")
    assert fixed["metrics"]["task_success_rate"] == 0.0
    assert fixed["metrics"]["hard_constraint_satisfaction_rate"] == 0.0
    assert CatalogTool(load_catalog()).get_product(fixed["final_product_ids"][0]).name in fixed["final_answer"]
    assert "ask_clarifying_question" not in actions(fixed)
    assert full["metrics"]["task_success_rate"] == 1.0
    assert "ask_clarifying_question" in actions(full)
    assert full["metrics"]["useful_clarification_rate"] == 1.0


def test_reflection_and_replanning_recover_rejection():
    ablated = run("ablation_no_replanning", "rejection_recovery")
    full = run("full_agent", "rejection_recovery")
    assert ablated["metrics"]["recovery_success_rate"] == 0.0
    assert "replan" not in actions(ablated)
    assert full["metrics"]["recovery_success_rate"] == 1.0
    assert "reflect_on_feedback" in actions(full)
    assert "replan" in actions(full)
    assert full["final_product_ids"][0] == "B004"


def test_recipient_isolation_prevents_profile_contamination():
    flat = run("agent_flat_memory", "recipient_shift")
    hierarchical = run("agent_hierarchical_memory", "recipient_shift")
    no_isolation = run("ablation_no_recipient_isolation", "recipient_shift")
    assert flat["metrics"]["profile_contamination_rate"] == 1.0
    assert no_isolation["metrics"]["profile_contamination_rate"] == 1.0
    assert hierarchical["metrics"]["profile_contamination_rate"] == 0.0
    assert hierarchical["metrics"]["task_success_rate"] == 1.0


def test_temporal_decay_blocks_stale_memory_use():
    full = run("full_agent", "preference_conflict")
    no_decay = run("ablation_no_temporal_decay", "preference_conflict")
    assert full["metrics"]["stale_memory_misuse_rate"] == 0.0
    assert no_decay["metrics"]["stale_memory_misuse_rate"] == 1.0
    # Replanning can mask the stale-memory error in final task success; the
    # extra rejection remains visible rather than being relabeled as uplift.
    assert no_decay["rejection_occurred"] is True


def test_each_trajectory_step_has_auditable_contract():
    record = run("full_agent", "recipient_shift")
    required = {
        "step",
        "observation",
        "selected_action",
        "action_arguments",
        "tool_result",
        "memory_reads",
        "memory_writes",
        "constraint_check",
        "latency_ms",
        "token_usage",
        "estimated_cost_usd",
        "error",
    }
    assert record["trajectory"]
    assert all(required.issubset(step) for step in record["trajectory"])
    assert record["token_usage"] == {"input": 0, "output": 0}
    assert record["estimated_cost_usd"] == 0.0


def test_session_constraints_do_not_leak_into_later_tasks():
    tasks = build_tasks(20, seed=42)
    for system in ("full_agent", "agent_flat_memory"):
        agent = ShoppingAgent(
            system=system, catalog=CatalogTool(load_catalog()), seed=42
        )
        records = [agent.run_task(task) for task in tasks]
        deterministic_constraint_rows = [
            row
            for row in records
            if row["scenario"] in {"hard_constraints", "cold_start", "clear_single_turn"}
        ]
        assert deterministic_constraint_rows
        assert all(
            row["metrics"]["hard_constraint_satisfaction_rate"] == 1.0
            for row in deterministic_constraint_rows
        )
