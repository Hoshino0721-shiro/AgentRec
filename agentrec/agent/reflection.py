"""Feedback reflection that converts visible feedback into replanning state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping


@dataclass
class Reflection:
    reason: str
    constraints: List[Dict[str, Any]]
    preferences: List[Dict[str, Any]]
    rejected_product_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        result = value.to_dict()
        return dict(result) if isinstance(result, dict) else {}
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key, None))
    }


def reflect_on_feedback(feedback: Any, recommended_ids: List[str]) -> Reflection:
    raw = _mapping(feedback)
    details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
    constraints = raw.get("new_constraints") or details.get("constraints") or []
    preferences = raw.get("new_preferences") or details.get("preferences") or []
    rejected = raw.get("rejected_product_ids") or details.get("rejected_product_ids") or recommended_ids
    reason = str(raw.get("reason") or raw.get("message") or details.get("reason") or "recommendation rejected")
    return Reflection(
        reason=reason,
        constraints=[_mapping(value) for value in constraints],
        preferences=[_mapping(value) for value in preferences],
        rejected_product_ids=[str(value) for value in rejected],
    )

