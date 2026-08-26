"""Frozen controlled-task generator covering the preregistered scenarios."""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional, Sequence

from agentrec.domain.models import (
    AcceptanceCriteria,
    Constraint,
    Feedback,
    Preference,
    Task,
)


SCENARIOS = (
    "clear_single_turn",
    "needs_clarification",
    "preference_alignment",
    "preference_conflict",
    "recipient_shift",
    "hard_constraints",
    "rejection_recovery",
    "cold_start",
)

CURRENT_TIME = "2026-01-15T10:00:00Z"


def _c(field: str, operator: str, value: Any, *, subject: str = "self", source: str = "explicit_request") -> Constraint:
    return Constraint(field=field, operator=operator, value=value, subject=subject, source=source)


def _p(
    attribute: str,
    value: Any,
    *,
    subject: str = "self",
    scope: str = "session",
    polarity: str = "prefer",
    confidence: float = 1.0,
    source: str = "explicit",
) -> Preference:
    return Preference(
        attribute=attribute,
        value=value,
        subject=subject,
        scope=scope,
        polarity=polarity,
        confidence=confidence,
        source=source,
    )


def _memory(
    memory_id: str,
    *,
    layer: str,
    subject: str,
    attribute: str,
    value: Any,
    confidence: float = 0.9,
    valid_from: str = "2025-12-01T10:00:00Z",
    expires_at: Optional[str] = None,
    source: str = "repeated_behavior",
) -> Dict[str, Any]:
    return {
        "memory_id": memory_id,
        "layer": layer,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "polarity": "prefer",
        "confidence": confidence,
        "source": source,
        "evidence_event_ids": [memory_id + ":e1", memory_id + ":e2"],
        "created_at": valid_from,
        "valid_from": valid_from,
        "expires_at": expires_at,
        "status": "active",
        "supersedes": None,
    }


def _base_metadata(
    *,
    seed: int,
    variant: int,
    initial_constraints: Sequence[Constraint] = (),
    initial_preferences: Sequence[Preference] = (),
    clarification_constraints: Sequence[Constraint] = (),
    clarification_preferences: Sequence[Preference] = (),
    initial_memories: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    return {
        "source": "controlled_catalog_v1",
        "controlled": True,
        "seed": seed,
        "variant": variant,
        "current_time": CURRENT_TIME,
        "temporal": True,
        "initial_constraints": [value.to_dict() for value in initial_constraints],
        "initial_preferences": [value.to_dict() for value in initial_preferences],
        "clarification_constraints": [value.to_dict() for value in clarification_constraints],
        "clarification_preferences": [value.to_dict() for value in clarification_preferences],
        "initial_memories": list(initial_memories),
    }


def _placeholder_feedback(recipient: str = "self") -> Feedback:
    return Feedback(
        accepted=False,
        reason="The initial slate is evaluated by the controlled user simulator.",
        recipient=recipient,
        timestamp=CURRENT_TIME,
    )


def _build_one(scenario: str, *, seed: int, variant: int) -> Task:
    task_id = f"ctrl-{seed}-{scenario}-{variant:03d}"
    if scenario == "clear_single_turn":
        constraints = [_c("price", "lte", 70), _c("waterproof", "eq", True)]
        metadata = _base_metadata(seed=seed, variant=variant, initial_constraints=constraints)
        request = [
            "I need waterproof sport headphones under $70.",
            "Find me waterproof running headphones for no more than 70 dollars.",
        ][variant % 2]
        return Task(task_id, scenario, request, "self", constraints,
                    AcceptanceCriteria(["H005"], "H005"), _placeholder_feedback(), "H005",
                    preferences=[], metadata=metadata)

    if scenario == "needs_clarification":
        constraints = [
            _c("price", "lte", 100),
            _c("wireless", "eq", True),
            _c("noise_cancelling", "eq", True),
        ]
        clarification_preferences = [_p("color", "black")]
        metadata = _base_metadata(
            seed=seed,
            variant=variant,
            clarification_constraints=constraints,
            clarification_preferences=clarification_preferences,
        )
        request = [
            "帮我挑一副通勤用的耳机，预算和功能我还没说。",
            "I am not sure which commute headphones to buy; help me choose.",
        ][variant % 2]
        return Task(task_id, scenario, request, "self", constraints,
                    AcceptanceCriteria(["H001"], "H001"), _placeholder_feedback(), "H001",
                    preferences=clarification_preferences, metadata=metadata)

    if scenario == "preference_alignment":
        constraints = [_c("price", "lte", 100), _c("wireless", "eq", True)]
        memories = [_memory("stable-grove", layer="stable", subject="self", attribute="brand", value="Grove")]
        metadata = _base_metadata(
            seed=seed, variant=variant, initial_constraints=constraints, initial_memories=memories
        )
        return Task(task_id, scenario, "Find wireless headphones under $100.", "self", constraints,
                    AcceptanceCriteria(["H007"], "H007"), _placeholder_feedback(), "H007",
                    preferences=[], metadata=metadata)

    if scenario == "preference_conflict":
        constraints = [_c("price", "lte", 100), _c("wireless", "eq", True)]
        stale = [_memory(
            "expired-boreal", layer="stage", subject="self", attribute="brand", value="Boreal",
            confidence=1.0, valid_from="2025-09-01T00:00:00Z", expires_at="2026-01-01T00:00:00Z"
        )]
        metadata = _base_metadata(
            seed=seed, variant=variant, initial_constraints=constraints, initial_memories=stale
        )
        return Task(task_id, scenario, "Find good wireless headphones under $100 for my current commute.",
                    "self", constraints, AcceptanceCriteria(["H001"], "H001"),
                    _placeholder_feedback(), "H001", preferences=[], metadata=metadata)

    if scenario == "recipient_shift":
        recipient = "recipient:child"
        memories = [
            _memory("self-aster", layer="stable", subject="self", attribute="brand", value="Aster"),
            _memory("child-pink", layer="recipient", subject=recipient, attribute="color", value="pink", valid_from=CURRENT_TIME),
            _memory("child-age", layer="recipient", subject=recipient, attribute="age_group", value="child", valid_from=CURRENT_TIME),
        ]
        metadata = _base_metadata(seed=seed, variant=variant, initial_memories=memories)
        return Task(task_id, scenario, "I need headphones for another person.", recipient, [],
                    AcceptanceCriteria(["H004"], "H004"), _placeholder_feedback(recipient), "H004",
                    preferences=[], metadata=metadata)

    if scenario == "hard_constraints":
        constraints = [
            _c("price", "lte", 100),
            _c("size", "eq", 9),
            _c("waterproof", "eq", True),
            _c("vegan", "eq", True),
        ]
        metadata = _base_metadata(seed=seed, variant=variant, initial_constraints=constraints)
        return Task(task_id, scenario,
                    "I need vegan waterproof walking shoes, size 9, under $100.", "self", constraints,
                    AcceptanceCriteria(["S003"], "S003"), _placeholder_feedback(), "S003",
                    preferences=[], metadata=metadata)

    if scenario == "rejection_recovery":
        new_constraints = [
            _c("price", "lte", 110, source="explicit_feedback"),
            _c("laptop_inches", "gte", 16, source="explicit_feedback"),
            _c("waterproof", "eq", True, source="explicit_feedback"),
        ]
        feedback = Feedback(
            accepted=False,
            reason="The first choice does not protect my 16-inch laptop from rain.",
            rejected_product_ids=["B006"],
            new_constraints=new_constraints,
            recipient="self",
            timestamp=CURRENT_TIME,
        )
        metadata = _base_metadata(seed=seed, variant=variant)
        return Task(task_id, scenario, "I need a backpack for commuting.", "self", new_constraints,
                    AcceptanceCriteria(["B004"], "B004"), feedback, "B004",
                    preferences=[], metadata=metadata)

    if scenario == "cold_start":
        constraints = [
            _c("price", "lte", 60),
            _c("programmable", "eq", True),
            _c("capacity_cups", "lte", 4),
        ]
        metadata = _base_metadata(seed=seed, variant=variant, initial_constraints=constraints)
        return Task(task_id, scenario,
                    "For a new user, find a programmable coffee maker under $60 for at most four cups.",
                    "self", constraints, AcceptanceCriteria(["C002"], "C002"),
                    _placeholder_feedback(), "C002", preferences=[], metadata=metadata)
    raise ValueError(f"unknown controlled scenario: {scenario}")


def build_tasks(
    count: int = 20,
    seed: int = 42,
    scenarios: Optional[Sequence[str]] = None,
) -> List[Task]:
    selected = list(scenarios or SCENARIOS)
    if not selected:
        raise ValueError("at least one scenario is required")
    unknown = [value for value in selected if value not in SCENARIOS]
    if unknown:
        raise ValueError("unknown scenarios: " + ", ".join(unknown))
    if count < 0:
        raise ValueError("count must be non-negative")
    # Seed controls the starting offset while preserving balanced coverage.
    rng = random.Random(int(seed))
    offset = rng.randrange(len(selected)) if len(selected) > 1 else 0
    tasks = []
    per_scenario_counts = {scenario: 0 for scenario in selected}
    for index in range(int(count)):
        scenario = selected[(index + offset) % len(selected)]
        variant = per_scenario_counts[scenario]
        per_scenario_counts[scenario] += 1
        tasks.append(_build_one(scenario, seed=int(seed), variant=variant))
    return tasks


def build_smoke_tasks(seed: int = 42) -> List[Task]:
    return build_tasks(20, seed, SCENARIOS)


def build_pilot_tasks(count: int = 100, seed: int = 42) -> List[Task]:
    return build_tasks(min(100, int(count)), seed, SCENARIOS)


def build_full_tasks(count: int = 300, seed: int = 42) -> List[Task]:
    return build_tasks(int(count), seed, SCENARIOS)


__all__ = [
    "SCENARIOS",
    "build_tasks",
    "build_smoke_tasks",
    "build_pilot_tasks",
    "build_full_tasks",
]

