from datetime import datetime, timezone

from agentrec.memory import create_memory_store


NOW = datetime(2026, 1, 15, tzinfo=timezone.utc)


def entry(
    memory_id="m1",
    *,
    subject="self",
    layer="stable",
    attribute="brand",
    value="Aster",
    confidence=0.9,
    source="explicit",
    expires_at=None,
    valid_from="2026-01-01T00:00:00Z",
):
    return {
        "memory_id": memory_id,
        "layer": layer,
        "subject": subject,
        "attribute": attribute,
        "value": value,
        "polarity": "prefer",
        "confidence": confidence,
        "source": source,
        "evidence_event_ids": ["event-1"],
        "created_at": valid_from,
        "valid_from": valid_from,
        "expires_at": expires_at,
        "status": "active",
        "supersedes": None,
    }


def test_hierarchical_memory_isolates_recipient_from_self():
    store = create_memory_store("hierarchical", recipient_isolation=True)
    stored = store.write(
        entry(subject="recipient:mother", layer="recipient", value="Cedar"), now=NOW
    )
    assert stored.subject == "recipient:mother"
    assert store.retrieve(subject="self", now=NOW) == []
    hits = store.retrieve(subject="recipient:mother", now=NOW)
    assert [hit.entry.value for hit in hits] == ["Cedar"]
    assert not hits[0].entry.is_profile_contamination


def test_flat_and_no_isolation_make_contamination_auditable():
    for mode, isolation in (("flat", False), ("hierarchical", False)):
        store = create_memory_store(mode, recipient_isolation=isolation)
        stored = store.write(
            entry(subject="recipient:friend", layer="recipient", value="Dune"), now=NOW
        )
        assert stored.subject == "self"
        assert stored.layer == "stable"
        assert stored.origin_subject == "recipient:friend"
        assert stored.is_profile_contamination
        assert store.retrieve(subject="recipient:friend", now=NOW)[0].entry.value == "Dune"


def test_expiry_and_temporal_decay_toggle():
    expiring = entry(
        layer="session",
        valid_from="2025-12-01T00:00:00Z",
        expires_at="2026-01-10T00:00:00Z",
    )
    decayed = create_memory_store("hierarchical", temporal_decay=True)
    decayed.write(expiring, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert decayed.retrieve(subject="self", now=NOW) == []
    assert decayed.snapshot(now=NOW)["memories"][0]["status"] == "expired"

    no_decay = create_memory_store("hierarchical", temporal_decay=False)
    no_decay.write(expiring, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    hits = no_decay.retrieve(subject="self", now=NOW)
    assert len(hits) == 1
    assert hits[0].effective_confidence == 0.9


def test_conflict_is_versioned_and_lower_confidence_becomes_candidate():
    store = create_memory_store("hierarchical")
    first = store.write(entry(memory_id="old", value="Aster", confidence=0.9), now=NOW)
    second = store.write(
        entry(
            memory_id="weak",
            value="Boreal",
            confidence=0.2,
            source="single_behavior",
        ),
        now=NOW,
    )
    assert first.status == "active"
    assert second.status == "candidate"
    assert store.read("old", now=NOW).value == "Aster"

    replacement = store.write(
        entry(memory_id="explicit-new", value="Boreal", confidence=1.0), now=NOW
    )
    assert replacement.supersedes == "old"
    assert store.read("old", now=NOW) is None
    assert store.read("old", now=NOW, include_inactive=True).status == "superseded"


def test_update_is_versioned_and_no_memory_is_noop():
    store = create_memory_store("hierarchical")
    store.write(entry(memory_id="m"), now=NOW)
    updated = store.update("m", {"confidence": 1.0}, now=NOW)
    assert updated.supersedes == "m"
    assert updated.confidence == 1.0
    assert store.audit(action="update")

    empty = create_memory_store("no_memory")
    assert empty.write(entry(), now=NOW) is None
    assert empty.retrieve(subject="self", now=NOW) == []
    assert empty.snapshot(now=NOW)["memories"] == []

