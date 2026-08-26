"""Auditable no-memory, flat, and hierarchical memory stores."""

from __future__ import annotations

import itertools
import math
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from .models import (
    MemoryEntry,
    MemoryHit,
    TEMPORAL_LAYERS,
    canonical_value,
    merge_evidence,
    parse_datetime,
    utc_now,
)


Clock = Callable[[], datetime]


def _now(value: Any, clock: Clock) -> datetime:
    if value is None:
        return clock()
    return parse_datetime(value, field_name="now")


def _replace(entry: MemoryEntry, **changes: Any) -> MemoryEntry:
    data = entry.to_dict()
    data.update(changes)
    return MemoryEntry.from_mapping(data)


class BaseMemoryStore:
    strategy = "base"

    def __init__(
        self,
        *,
        temporal_decay: bool = True,
        recipient_isolation: bool = True,
        decay_half_life_days: float = 30.0,
        clock: Optional[Clock] = None,
    ) -> None:
        if decay_half_life_days <= 0:
            raise ValueError("decay_half_life_days must be positive")
        self.temporal_decay = bool(temporal_decay)
        self.recipient_isolation = bool(recipient_isolation)
        self.decay_half_life_days = float(decay_half_life_days)
        self.clock = clock or utc_now
        self._entries: Dict[str, MemoryEntry] = {}
        self._audit: List[Dict[str, Any]] = []
        self._sequence = itertools.count(1)

    def _record(self, action: str, entry: Optional[MemoryEntry], **details: Any) -> None:
        self._audit.append(
            {
                "sequence": next(self._sequence),
                "action": action,
                "memory_id": entry.memory_id if entry else None,
                "details": details,
            }
        )

    def _scope(self, entry: MemoryEntry) -> MemoryEntry:
        return entry

    def _unique_id(self, requested: str) -> str:
        if requested not in self._entries:
            return requested
        version = 2
        while f"{requested}:v{version}" in self._entries:
            version += 1
        return f"{requested}:v{version}"

    @staticmethod
    def _conflict_key(entry: MemoryEntry) -> Any:
        return (entry.subject, entry.layer, entry.attribute, entry.polarity)

    def _active_conflict(self, entry: MemoryEntry) -> Optional[MemoryEntry]:
        candidates = [
            value
            for value in self._entries.values()
            if value.status == "active" and self._conflict_key(value) == self._conflict_key(entry)
        ]
        return max(candidates, key=lambda value: value.created_at) if candidates else None

    def write(
        self,
        entry: Union[MemoryEntry, Mapping[str, Any]],
        *,
        now: Any = None,
    ) -> Optional[MemoryEntry]:
        current = _now(now, self.clock)
        incoming = entry.clone() if isinstance(entry, MemoryEntry) else MemoryEntry.from_mapping(entry)
        incoming = self._scope(incoming)
        if parse_datetime(incoming.valid_from, field_name="valid_from") > current:
            incoming = _replace(incoming, status="candidate")
        previous = self._active_conflict(incoming)
        if previous is not None:
            same_value = canonical_value(previous.value) == canonical_value(incoming.value)
            if same_value:
                reinforced = 1.0 - (1.0 - previous.confidence) * (1.0 - incoming.confidence * 0.5)
                incoming = _replace(
                    incoming,
                    confidence=min(1.0, reinforced),
                    evidence_event_ids=merge_evidence(
                        previous.evidence_event_ids, incoming.evidence_event_ids
                    ),
                    supersedes=previous.memory_id,
                    status="active",
                )
            elif incoming.source in {"explicit", "explicit_request"} or incoming.confidence >= previous.confidence:
                incoming = _replace(incoming, supersedes=previous.memory_id, status="active")
            else:
                incoming = _replace(incoming, status="candidate", supersedes=None)

            if incoming.status == "active":
                self._entries[previous.memory_id] = _replace(previous, status="superseded")
                self._record(
                    "supersede",
                    previous,
                    replacement_requested_id=incoming.memory_id,
                    same_value=same_value,
                )

        unique_id = self._unique_id(incoming.memory_id)
        if unique_id != incoming.memory_id:
            incoming = _replace(incoming, memory_id=unique_id)
        self._entries[incoming.memory_id] = incoming
        self._record(
            "write",
            incoming,
            origin_subject=incoming.origin_subject,
            stored_subject=incoming.subject,
            origin_layer=incoming.origin_layer,
            stored_layer=incoming.layer,
        )
        return incoming.clone()

    def _expire(self, current: datetime) -> None:
        if not self.temporal_decay:
            return
        for memory_id, entry in list(self._entries.items()):
            if entry.status != "active" or not entry.expires_at:
                continue
            if parse_datetime(entry.expires_at, field_name="expires_at") <= current:
                expired = _replace(entry, status="expired")
                self._entries[memory_id] = expired
                self._record("expire", expired)

    def read(
        self,
        memory_id: str,
        *,
        now: Any = None,
        include_inactive: bool = False,
    ) -> Optional[MemoryEntry]:
        self._expire(_now(now, self.clock))
        entry = self._entries.get(str(memory_id))
        if entry is None or (not include_inactive and entry.status != "active"):
            return None
        self._record("read", entry)
        return entry.clone()

    def update(
        self,
        memory_id: str,
        changes: Mapping[str, Any],
        *,
        now: Any = None,
    ) -> Optional[MemoryEntry]:
        existing = self._entries.get(str(memory_id))
        if existing is None:
            return None
        data = existing.to_dict()
        data.update(dict(changes))
        data["memory_id"] = self._unique_id(f"{existing.memory_id}:update")
        data["supersedes"] = existing.memory_id
        data["status"] = "active"
        replacement = self._scope(MemoryEntry.from_mapping(data))
        self._entries[existing.memory_id] = _replace(existing, status="superseded")
        self._entries[replacement.memory_id] = replacement
        self._record("supersede", existing, replacement_requested_id=replacement.memory_id)
        self._record("update", replacement, previous_id=existing.memory_id)
        return replacement.clone()

    def _query_subject(self, subject: str) -> str:
        return subject

    def retrieve(
        self,
        *,
        subject: str = "self",
        attribute: Optional[str] = None,
        layers: Optional[Iterable[str]] = None,
        now: Any = None,
        include_candidates: bool = False,
        min_confidence: float = 0.0,
        limit: Optional[int] = None,
    ) -> List[MemoryHit]:
        current = _now(now, self.clock)
        self._expire(current)
        query_subject = self._query_subject(subject)
        allowed_layers = set(layers) if layers is not None else None
        hits: List[MemoryHit] = []
        layer_weight = {
            "constraint": 1.30,
            "session": 1.20,
            "recipient": 1.15,
            "stage": 1.05,
            "stable": 1.00,
            "event": 0.80,
        }
        for entry in self._entries.values():
            if entry.status != "active" and not (include_candidates and entry.status == "candidate"):
                continue
            if entry.subject != query_subject:
                continue
            if attribute is not None and entry.attribute != attribute:
                continue
            if allowed_layers is not None and entry.layer not in allowed_layers:
                continue
            valid_from = parse_datetime(entry.valid_from, field_name="valid_from")
            if valid_from > current:
                continue
            age_days = max(0.0, (current - valid_from).total_seconds() / 86400.0)
            decayed = bool(self.temporal_decay and entry.layer in TEMPORAL_LAYERS)
            effective = entry.confidence
            if decayed:
                effective *= math.pow(0.5, age_days / self.decay_half_life_days)
            if effective < float(min_confidence):
                continue
            score = effective * layer_weight.get(entry.layer, 1.0)
            hits.append(
                MemoryHit(
                    entry=entry.clone(),
                    effective_confidence=effective,
                    score=score,
                    age_days=age_days,
                    decayed=decayed,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.entry.attribute, hit.entry.memory_id))
        if limit is not None:
            hits = hits[: max(0, int(limit))]
        for hit in hits:
            self._record("retrieve", hit.entry, score=hit.score, effective_confidence=hit.effective_confidence)
        return hits

    def snapshot(self, *, now: Any = None, include_inactive: bool = True) -> Dict[str, Any]:
        self._expire(_now(now, self.clock))
        entries = [
            entry.to_dict()
            for entry in self._entries.values()
            if include_inactive or entry.status == "active"
        ]
        entries.sort(key=lambda value: (value["created_at"], value["memory_id"]))
        return {
            "strategy": self.strategy,
            "config": {
                "temporal_decay": self.temporal_decay,
                "recipient_isolation": self.recipient_isolation,
                "decay_half_life_days": self.decay_half_life_days,
            },
            "memories": entries,
            "audit_event_count": len(self._audit),
        }

    def audit(
        self, *, action: Optional[str] = None, memory_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return [
            dict(event)
            for event in self._audit
            if (action is None or event["action"] == action)
            and (memory_id is None or event["memory_id"] == memory_id)
        ]


class NoMemoryStore(BaseMemoryStore):
    strategy = "none"

    def write(self, entry: Union[MemoryEntry, Mapping[str, Any]], *, now: Any = None) -> None:
        return None

    def read(self, memory_id: str, *, now: Any = None, include_inactive: bool = False) -> None:
        return None

    def update(self, memory_id: str, changes: Mapping[str, Any], *, now: Any = None) -> None:
        return None

    def retrieve(self, **kwargs: Any) -> List[MemoryHit]:
        return []


class FlatMemoryStore(BaseMemoryStore):
    strategy = "flat"

    def _scope(self, entry: MemoryEntry) -> MemoryEntry:
        return _replace(
            entry,
            subject="self",
            layer="stable",
            origin_subject=entry.origin_subject or entry.subject,
            origin_layer=entry.origin_layer or entry.layer,
        )

    def _query_subject(self, subject: str) -> str:
        return "self"


class HierarchicalMemoryStore(BaseMemoryStore):
    strategy = "hierarchical"

    def _scope(self, entry: MemoryEntry) -> MemoryEntry:
        if self.recipient_isolation or not entry.subject.startswith("recipient:"):
            return entry
        return _replace(
            entry,
            subject="self",
            layer="stable",
            origin_subject=entry.origin_subject or entry.subject,
            origin_layer=entry.origin_layer or entry.layer,
        )

    def _query_subject(self, subject: str) -> str:
        if not self.recipient_isolation and subject.startswith("recipient:"):
            return "self"
        return subject


def create_memory_store(
    mode: str,
    *,
    temporal_decay: bool = True,
    recipient_isolation: bool = True,
    decay_half_life_days: float = 30.0,
    clock: Optional[Clock] = None,
) -> BaseMemoryStore:
    normalized = str(mode).strip().lower()
    cls = {
        "none": NoMemoryStore,
        "no_memory": NoMemoryStore,
        "flat": FlatMemoryStore,
        "hierarchical": HierarchicalMemoryStore,
    }.get(normalized)
    if cls is None:
        raise ValueError("unknown memory mode: %s" % mode)
    return cls(
        temporal_decay=temporal_decay,
        recipient_isolation=recipient_isolation,
        decay_half_life_days=decay_half_life_days,
        clock=clock,
    )


__all__ = [
    "BaseMemoryStore",
    "NoMemoryStore",
    "FlatMemoryStore",
    "HierarchicalMemoryStore",
    "create_memory_store",
]
