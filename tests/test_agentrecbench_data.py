import json
from pathlib import Path

import pytest

from agentrec.data.agentrecbench import (
    AGENTRECBENCH_REVISION,
    build_processed_subset,
    load_processed_subset,
)


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _fixture(tmp_path: Path):
    root = tmp_path / "task" / "short_term" / "amazon"
    _write_json(
        root / "tasks" / "task_0.json",
        {
            "type": "recommendation",
            "user_id": "U1",
            "candidate_list": ["A1", "A2"],
            "data type": "real",
        },
    )
    _write_json(root / "groundtruth" / "groundtruth_0.json", {"ground truth": "A2"})
    rows = [
        {"source": "yelp", "item_id": "Y1", "name": "Yelp row"},
        {
            "source": "amazon",
            "item_id": "A1",
            "title": "Product one",
            "main_category": "Industrial & Scientific",
            "store": "Brand One",
            "average_rating": 4.0,
            "rating_number": 10,
            "features": ["red"],
            "details": {"Brand": "Brand One"},
        },
        {
            "source": "amazon",
            "item_id": "A2",
            "title": "Product two",
            "main_category": "Musical Instruments",
            "store": "Brand Two",
            "price": "$19.99",
            "average_rating": 4.8,
            "rating_number": 50,
            "description": ["Target product"],
        },
        {"source": "goodreads", "item_id": "G1", "title": "Book row"},
    ]
    encoded = b"partial-yelp" + b"\n" + b"".join(
        json.dumps(row).encode("utf-8") + b"\n" for row in rows
    ) + b"partial-goodreads"
    split = len(encoded) // 2
    chunk_one = tmp_path / "item_0.bin"
    chunk_two = tmp_path / "item_1.bin"
    chunk_one.write_bytes(encoded[:split])
    chunk_two.write_bytes(encoded[split:])
    review_path = tmp_path / "review.json"
    _write_jsonl(
        review_path,
        [
            {"source": "yelp", "review_id": "Y", "user_id": "U1"},
            {
                "source": "amazon",
                "review_id": "R1",
                "user_id": "U1",
                "item_id": "OLD",
                "stars": 5,
                "text": "I value durable red products.",
                "timestamp": 100,
            },
            {
                "source": "amazon",
                "review_id": "LEAK",
                "user_id": "U1",
                "item_id": "A2",
                "stars": 5,
                "text": "This candidate is the held-out target.",
                "timestamp": 200,
            },
            {"source": "goodreads", "review_id": "G", "user_id": "U1"},
        ],
    )
    return root, [chunk_one, chunk_two], review_path


def test_build_and_load_real_subset_preserves_source_boundary(tmp_path):
    root, chunks, reviews = _fixture(tmp_path)
    output = tmp_path / "processed.json"
    build_processed_subset(
        task_root=root,
        item_chunks=chunks,
        review_path=reviews,
        output_path=output,
        max_tasks=1,
        provenance={"test_fixture": True},
    )
    subset = load_processed_subset(output)
    assert subset.manifest["dataset_revision"] == AGENTRECBENCH_REVISION
    assert subset.manifest["controlled"] is False
    assert subset.manifest["item_envelope_source_counts"] == {
        "yelp": 1,
        "amazon": 2,
        "goodreads": 1,
    }
    assert [item.product_id for item in subset.products] == ["A1", "A2"]
    assert all(item.controlled is False for item in subset.products)
    assert subset.tasks[0].target_product_id == "A2"
    assert subset.tasks[0].review_ids == ["R1"]
    assert subset.manifest["candidate_history_reviews_excluded"] == 1
    assert subset.reviews_by_user["U1"][0]["controlled"] is False


def test_build_fails_instead_of_fabricating_missing_candidate(tmp_path):
    root, chunks, reviews = _fixture(tmp_path)
    second = chunks[1].read_bytes().replace(b'"item_id": "A2"', b'"item_id": "ZZ"')
    chunks[1].write_bytes(second)
    with pytest.raises(ValueError, match="missing real metadata"):
        build_processed_subset(
            task_root=root,
            item_chunks=chunks,
            review_path=reviews,
            output_path=tmp_path / "processed.json",
            max_tasks=1,
        )
