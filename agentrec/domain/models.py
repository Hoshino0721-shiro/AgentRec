"""Small, dependency-free domain models for AgentRec.

The experiment harness writes these objects to JSONL, so each model has an
explicit ``to_dict``/``from_dict`` contract.  The implementation deliberately
avoids pydantic (and Python 3.10-only syntax) so the deterministic environment
can run on Python 3.9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional


def _list(value: Optional[Iterable[Any]]) -> List[Any]:
    return list(value) if value is not None else []


@dataclass(frozen=True)
class Product:
    """A catalog item.  ``attributes`` holds category-specific facts."""

    product_id: str
    name: str
    category: str
    brand: str
    price: float
    currency: str = "USD"
    description: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    rating: float = 0.0
    review_count: int = 0
    review_snippets: List[str] = field(default_factory=list)
    available: bool = True
    controlled: bool = True
    source: str = "controlled_catalog"

    @property
    def id(self) -> str:
        """Compatibility alias used by simple recommenders."""
        return self.product_id

    def value_for(self, field_name: str, default: Any = None) -> Any:
        """Return an explicit or category-specific field without evaluation."""
        key = str(field_name or "")
        if key.startswith("attributes."):
            key = key.split(".", 1)[1]
        if key in self.attributes:
            return self.attributes[key]
        if hasattr(self, key) and key not in {"value_for", "to_dict"}:
            return getattr(self, key)
        return default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "category": self.category,
            "brand": self.brand,
            "price": float(self.price),
            "currency": self.currency,
            "description": self.description,
            "attributes": dict(self.attributes),
            "tags": list(self.tags),
            "rating": float(self.rating),
            "review_count": int(self.review_count),
            "review_snippets": list(self.review_snippets),
            "available": bool(self.available),
            "controlled": bool(self.controlled),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Product":
        return cls(
            product_id=str(data.get("product_id") or data.get("id") or ""),
            name=str(data.get("name") or ""),
            category=str(data.get("category") or ""),
            brand=str(data.get("brand") or ""),
            price=float(data.get("price", 0.0)),
            currency=str(data.get("currency") or "USD"),
            description=str(data.get("description") or ""),
            attributes=dict(data.get("attributes") or {}),
            tags=[str(item) for item in _list(data.get("tags"))],
            rating=float(data.get("rating", 0.0)),
            review_count=int(data.get("review_count", 0)),
            review_snippets=[str(item) for item in _list(data.get("review_snippets"))],
            available=bool(data.get("available", True)),
            controlled=bool(data.get("controlled", True)),
            source=str(data.get("source") or "controlled_catalog"),
        )


@dataclass(frozen=True)
class Constraint:
    """A machine-checkable task constraint.

    Supported operators are implemented by :mod:`agentrec.tools.catalog` and
    include eq/ne/lte/gte/in/not_in/contains/not_contains/exists.
    """

    field: str
    operator: str
    value: Any
    hard: bool = True
    source: str = "explicit_request"
    subject: str = "self"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
            "hard": bool(self.hard),
            "source": self.source,
            "subject": self.subject,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Constraint":
        return cls(
            field=str(data.get("field") or data.get("attribute") or ""),
            operator=str(data.get("operator") or data.get("op") or "eq"),
            value=data.get("value"),
            hard=bool(data.get("hard", True)),
            source=str(data.get("source") or "explicit_request"),
            subject=str(data.get("subject") or "self"),
        )


@dataclass(frozen=True)
class Preference:
    """A soft preference that can be scoped to a person and memory layer."""

    attribute: str
    value: Any
    weight: float = 1.0
    polarity: str = "prefer"
    subject: str = "self"
    scope: str = "session"
    confidence: float = 1.0
    source: str = "explicit"
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attribute": self.attribute,
            "value": self.value,
            "weight": float(self.weight),
            "polarity": self.polarity,
            "subject": self.subject,
            "scope": self.scope,
            "confidence": float(self.confidence),
            "source": self.source,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Preference":
        return cls(
            attribute=str(data.get("attribute") or data.get("field") or ""),
            value=data.get("value"),
            weight=float(data.get("weight", 1.0)),
            polarity=str(data.get("polarity") or "prefer"),
            subject=str(data.get("subject") or "self"),
            scope=str(data.get("scope") or data.get("layer") or "session"),
            confidence=float(data.get("confidence", 1.0)),
            source=str(data.get("source") or "explicit"),
            timestamp=(str(data["timestamp"]) if data.get("timestamp") is not None else None),
        )


@dataclass(frozen=True)
class AcceptanceCriteria:
    """Hidden deterministic oracle state owned by ``UserSimulator``."""

    acceptable_product_ids: List[str] = field(default_factory=list)
    target_product_id: Optional[str] = None
    require_all_constraints: bool = True
    notes: str = ""

    @property
    def relevant_product_ids(self) -> List[str]:
        result = list(self.acceptable_product_ids)
        if self.target_product_id and self.target_product_id not in result:
            result.append(self.target_product_id)
        return result

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "acceptable_product_ids": list(self.acceptable_product_ids),
            "target_product_id": self.target_product_id,
            "require_all_constraints": bool(self.require_all_constraints),
            "notes": self.notes,
            "hidden_from_agent": True,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AcceptanceCriteria":
        return cls(
            acceptable_product_ids=[str(item) for item in _list(
                data.get("acceptable_product_ids") or data.get("product_ids")
            )],
            target_product_id=(
                str(data["target_product_id"])
                if data.get("target_product_id") is not None
                else None
            ),
            require_all_constraints=bool(data.get("require_all_constraints", True)),
            notes=str(data.get("notes") or ""),
        )


@dataclass(frozen=True)
class Feedback:
    """A deterministic user response to a recommendation attempt."""

    accepted: bool
    reason: str
    product_ids: List[str] = field(default_factory=list)
    rejected_product_ids: List[str] = field(default_factory=list)
    new_constraints: List[Constraint] = field(default_factory=list)
    new_preferences: List[Preference] = field(default_factory=list)
    attempt: int = 1
    event_type: str = "recommendation_feedback"
    recipient: str = "self"
    timestamp: str = "2026-01-15T10:00:00Z"
    controlled: bool = True

    @property
    def message(self) -> str:
        return self.reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": bool(self.accepted),
            "reason": self.reason,
            "message": self.reason,
            "product_ids": list(self.product_ids),
            "rejected_product_ids": list(self.rejected_product_ids),
            "new_constraints": [item.to_dict() for item in self.new_constraints],
            "new_preferences": [item.to_dict() for item in self.new_preferences],
            "attempt": int(self.attempt),
            "event_type": self.event_type,
            "recipient": self.recipient,
            "timestamp": self.timestamp,
            "controlled": bool(self.controlled),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Feedback":
        return cls(
            accepted=bool(data.get("accepted", False)),
            reason=str(data.get("reason") or data.get("message") or ""),
            product_ids=[str(item) for item in _list(data.get("product_ids"))],
            rejected_product_ids=[str(item) for item in _list(data.get("rejected_product_ids"))],
            new_constraints=[
                item if isinstance(item, Constraint) else Constraint.from_dict(item)
                for item in _list(data.get("new_constraints"))
            ],
            new_preferences=[
                item if isinstance(item, Preference) else Preference.from_dict(item)
                for item in _list(data.get("new_preferences"))
            ],
            attempt=int(data.get("attempt", 1)),
            event_type=str(data.get("event_type") or "recommendation_feedback"),
            recipient=str(data.get("recipient") or "self"),
            timestamp=str(data.get("timestamp") or "2026-01-15T10:00:00Z"),
            controlled=bool(data.get("controlled", True)),
        )


@dataclass(frozen=True)
class Task:
    """A controlled shopping episode.

    ``acceptance`` and ``target_product_id`` are oracle fields.  They are
    serialized for auditability, but the Agent loop must pass recommendations
    to ``UserSimulator.evaluate`` rather than inspect them.
    """

    task_id: str
    scenario: str
    request: str
    recipient: str
    hard_constraints: List[Constraint]
    acceptance: AcceptanceCriteria
    feedback: Feedback
    target_product_id: str
    controlled: bool = True
    preferences: List[Preference] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def initial_memories(self) -> List[Dict[str, Any]]:
        return list(self.metadata.get("initial_memories") or [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "scenario": self.scenario,
            "request": self.request,
            "recipient": self.recipient,
            "hard_constraints": [item.to_dict() for item in self.hard_constraints],
            "preferences": [item.to_dict() for item in self.preferences],
            "acceptance": self.acceptance.to_dict(),
            "feedback": self.feedback.to_dict(),
            "target_product_id": self.target_product_id,
            "controlled": bool(self.controlled),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Task":
        acceptance = data.get("acceptance") or {}
        feedback = data.get("feedback") or {
            "accepted": False,
            "reason": "Recommendation did not meet the controlled criteria.",
        }
        target = data.get("target_product_id") or (
            acceptance.target_product_id
            if isinstance(acceptance, AcceptanceCriteria)
            else acceptance.get("target_product_id")
        )
        return cls(
            task_id=str(data.get("task_id") or ""),
            scenario=str(data.get("scenario") or ""),
            request=str(data.get("request") or data.get("user_request") or ""),
            recipient=str(data.get("recipient") or "self"),
            hard_constraints=[
                item if isinstance(item, Constraint) else Constraint.from_dict(item)
                for item in _list(data.get("hard_constraints"))
            ],
            preferences=[
                item if isinstance(item, Preference) else Preference.from_dict(item)
                for item in _list(data.get("preferences"))
            ],
            acceptance=(
                acceptance
                if isinstance(acceptance, AcceptanceCriteria)
                else AcceptanceCriteria.from_dict(acceptance)
            ),
            feedback=(
                feedback if isinstance(feedback, Feedback) else Feedback.from_dict(feedback)
            ),
            target_product_id=str(target or ""),
            controlled=bool(data.get("controlled", True)),
            metadata=dict(data.get("metadata") or {}),
        )
