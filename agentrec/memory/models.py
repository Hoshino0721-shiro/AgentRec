"""Data contracts for the deterministic shopping-memory subsystem.

The public models deliberately contain only standard-library and JSON-friendly
types.  Stored entries are immutable; every change creates a new version so a
trajectory can always explain which evidence produced the currently active
profile.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


VALID_LAYERS = frozenset(
    {"stable", "stage", "session", "recipient", "constraint", "event"}
)
VALID_POLARITIES = frozenset({"prefer", "avoid", "required"})
VALID_STATUSES = frozenset({"active", "candidate", "superseded", "expired"})
TEMPORAL_LAYERS = frozenset({"stage", "session", "recipient", "event"})


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def parse_datetime(value: Any, *, field_name: str = "timestamp") -> datetime:
    """Parse a datetime/ISO-8601 value and normalize it to UTC.

    Naive datetimes are interpreted as UTC.  Supporting both ``Z`` and offset
    forms keeps snapshots portable between Python 3.9 and newer runtimes.
    """

    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("%s must be an ISO-8601 timestamp" % field_name) from exc
    else:
        raise ValueError("%s must be a datetime or ISO-8601 string" % field_name)

    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def format_datetime(value: Any, *, field_name: str = "timestamp") -> str:
    """Return a canonical UTC ISO-8601 string ending in ``Z``."""

    return parse_datetime(value, field_name=field_name).isoformat().replace(
        "+00:00", "Z"
    )


def canonical_value(value: Any) -> str:
    """Create a stable comparison key for scalar or structured memory values."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return repr(value)


def _normalize_evidence(values: Optional[Iterable[Any]]) -> Tuple[str, ...]:
    seen = set()
    result = []
    for raw in values or ():
        value = str(raw).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _validate_subject(subject: str) -> None:
    if subject == "self":
        return
    if subject.startswith("recipient:") and subject.split(":", 1)[1].strip():
        return
    raise ValueError("subject must be 'self' or 'recipient:<id>'")


@dataclass(frozen=True)
class MemoryEntry:
    """One evidence-backed, versioned shopping memory.

    ``origin_subject`` and ``origin_layer`` are provenance fields used by the
    recipient-isolation ablation.  They record the caller's original scope even
    when a flat/no-isolation store intentionally collapses it into ``self`` and
    ``stable``.  They do not replace any field in the experiment contract.
    """

    memory_id: str
    layer: str
    subject: str
    attribute: str
    value: Any
    polarity: str
    confidence: float
    source: str
    evidence_event_ids: Tuple[str, ...]
    created_at: str
    valid_from: str
    expires_at: Optional[str]
    status: str
    supersedes: Optional[str]
    origin_subject: Optional[str] = None
    origin_layer: Optional[str] = None

    def __post_init__(self) -> None:
        memory_id = str(self.memory_id).strip()
        if not memory_id:
            raise ValueError("memory_id must not be empty")
        object.__setattr__(self, "memory_id", memory_id)

        layer = str(self.layer).strip().lower()
        if layer not in VALID_LAYERS:
            raise ValueError("invalid memory layer: %s" % self.layer)
        object.__setattr__(self, "layer", layer)

        subject = str(self.subject).strip()
        _validate_subject(subject)
        object.__setattr__(self, "subject", subject)

        attribute = str(self.attribute).strip()
        if not attribute:
            raise ValueError("attribute must not be empty")
        object.__setattr__(self, "attribute", attribute)

        polarity = str(self.polarity).strip().lower()
        if polarity not in VALID_POLARITIES:
            raise ValueError("invalid memory polarity: %s" % self.polarity)
        object.__setattr__(self, "polarity", polarity)

        confidence = float(self.confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be a finite number in [0, 1]")
        object.__setattr__(self, "confidence", confidence)

        source = str(self.source).strip()
        if not source:
            raise ValueError("source must not be empty")
        object.__setattr__(self, "source", source)

        object.__setattr__(
            self, "evidence_event_ids", _normalize_evidence(self.evidence_event_ids)
        )
        object.__setattr__(
            self,
            "created_at",
            format_datetime(self.created_at, field_name="created_at"),
        )
        object.__setattr__(
            self,
            "valid_from",
            format_datetime(self.valid_from, field_name="valid_from"),
        )
        if self.expires_at is not None:
            object.__setattr__(
                self,
                "expires_at",
                format_datetime(self.expires_at, field_name="expires_at"),
            )

        status = str(self.status).strip().lower()
        if status not in VALID_STATUSES:
            raise ValueError("invalid memory status: %s" % self.status)
        object.__setattr__(self, "status", status)

        if self.supersedes is not None:
            supersedes = str(self.supersedes).strip()
            object.__setattr__(self, "supersedes", supersedes or None)

        origin_subject = self.origin_subject or subject
        origin_subject = str(origin_subject).strip()
        _validate_subject(origin_subject)
        object.__setattr__(self, "origin_subject", origin_subject)

        origin_layer = str(self.origin_layer or layer).strip().lower()
        if origin_layer not in VALID_LAYERS:
            raise ValueError("invalid origin_layer: %s" % self.origin_layer)
        object.__setattr__(self, "origin_layer", origin_layer)

        # Prevent callers from changing a stored structured value through a
        # reference retained outside this frozen dataclass.
        object.__setattr__(self, "value", copy.deepcopy(self.value))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MemoryEntry":
        """Build an entry from a complete mapping."""

        return cls(
            memory_id=data["memory_id"],
            layer=data["layer"],
            subject=data["subject"],
            attribute=data["attribute"],
            value=data.get("value"),
            polarity=data["polarity"],
            confidence=data["confidence"],
            source=data["source"],
            evidence_event_ids=data.get("evidence_event_ids") or (),
            created_at=data["created_at"],
            valid_from=data["valid_from"],
            expires_at=data.get("expires_at"),
            status=data["status"],
            supersedes=data.get("supersedes"),
            origin_subject=data.get("origin_subject"),
            origin_layer=data.get("origin_layer"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a detached, JSON-serializable representation."""

        return {
            "memory_id": self.memory_id,
            "layer": self.layer,
            "subject": self.subject,
            "attribute": self.attribute,
            "value": copy.deepcopy(self.value),
            "polarity": self.polarity,
            "confidence": self.confidence,
            "source": self.source,
            "evidence_event_ids": list(self.evidence_event_ids),
            "created_at": self.created_at,
            "valid_from": self.valid_from,
            "expires_at": self.expires_at,
            "status": self.status,
            "supersedes": self.supersedes,
            "origin_subject": self.origin_subject,
            "origin_layer": self.origin_layer,
        }

    def clone(self) -> "MemoryEntry":
        """Return a detached copy safe for a caller to retain."""

        return MemoryEntry.from_mapping(self.to_dict())

    @property
    def is_recipient_origin(self) -> bool:
        return bool(
            self.origin_subject and self.origin_subject.startswith("recipient:")
        )

    @property
    def is_profile_contamination(self) -> bool:
        """Whether recipient evidence currently occupies the self/stable slot."""

        return (
            self.subject == "self"
            and self.layer == "stable"
            and self.is_recipient_origin
            and self.status == "active"
        )


@dataclass(frozen=True)
class MemoryHit:
    """A retrieved entry plus non-destructive temporal scoring metadata."""

    entry: MemoryEntry
    effective_confidence: float
    score: float
    age_days: float
    decayed: bool

    def to_dict(self) -> Dict[str, Any]:
        result = self.entry.to_dict()
        result.update(
            {
                "effective_confidence": self.effective_confidence,
                "retrieval_score": self.score,
                "age_days": self.age_days,
                "decayed": self.decayed,
            }
        )
        return result


def merge_evidence(*groups: Iterable[str]) -> Tuple[str, ...]:
    """Combine evidence IDs while retaining deterministic first-seen order."""

    values = []
    for group in groups:
        values.extend(group)
    return _normalize_evidence(values)


__all__ = [
    "MemoryEntry",
    "MemoryHit",
    "TEMPORAL_LAYERS",
    "VALID_LAYERS",
    "VALID_POLARITIES",
    "VALID_STATUSES",
    "canonical_value",
    "format_datetime",
    "merge_evidence",
    "parse_datetime",
    "utc_now",
]
