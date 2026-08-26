from collections import Counter

from agentrec.simulation.scenarios import SCENARIOS, build_tasks
from agentrec.simulation.user_simulator import UserSimulator


def test_task_generation_is_seeded_balanced_and_controlled():
    first = build_tasks(300, seed=42)
    second = build_tasks(300, seed=42)
    assert [task.to_dict() for task in first] == [task.to_dict() for task in second]
    assert len(first) == 300
    assert len({task.task_id for task in first}) == 300
    assert all(task.controlled and task.metadata["source"] == "controlled_catalog_v1" for task in first)
    counts = Counter(task.scenario for task in first)
    assert set(counts) == set(SCENARIOS)
    assert max(counts.values()) - min(counts.values()) <= 1


def test_clarification_reveals_hidden_state_only_when_called():
    task = build_tasks(1, seed=42, scenarios=["needs_clarification"])[0]
    simulator = UserSimulator(task)
    assert simulator.initial_request() == task.request
    response = simulator.clarify("What is the budget?")
    assert response["useful"] is True
    assert response["constraints"]
    assert response["controlled"] is True


def test_rejection_feedback_enables_deterministic_recovery():
    task = build_tasks(1, seed=42, scenarios=["rejection_recovery"])[0]
    simulator = UserSimulator(task)
    first = simulator.evaluate(["B006", "B001"], attempt=1)
    assert first.accepted is False
    assert first.new_constraints
    second = simulator.evaluate(["B004"], attempt=2)
    assert second.accepted is True
    assert simulator.is_accepted is True


def test_evaluation_uses_first_ranked_selection_not_hr_at_five():
    task = build_tasks(1, seed=42, scenarios=["recipient_shift"])[0]
    simulator = UserSimulator(task)
    assert simulator.evaluate(["H001", "H004"], attempt=1).accepted is False
    assert simulator.evaluate(["H004", "H001"], attempt=2).accepted is True

