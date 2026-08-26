"""Strict AgentRecBench Amazon adapter.

The upstream dataset mixes Yelp, Amazon, and Goodreads JSONL rows in large
files.  This module accepts a byte-range envelope that starts before Amazon
and ends after Amazon, filters only explicitly labelled Amazon rows, and
refuses to emit a processed artifact unless every benchmark candidate has
real item metadata.  Controlled fixtures never pass through this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

from agentrec.domain.models import Product


AGENTRECBENCH_DATASET_ID = "SGJQovo/AgentRecBench"
AGENTRECBENCH_REVISION = "288f7f09ca0387e5169a61b219047aea397e4b06"
AGENTRECBENCH_SOURCE = "agentrecbench_amazon_short_v1"


def sha256_file(path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _numeric_suffix(path: Path) -> int:
    match = re.search(r"_(\d+)\.json$", path.name)
    if match is None:
        raise ValueError("unexpected benchmark filename: %s" % path.name)
    return int(match.group(1))


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object: %s" % path)
    return value


def _iter_jsonl(path: Path) -> Iterator[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid JSONL at %s:%d" % (path, line_number)) from exc
            if not isinstance(value, dict):
                raise ValueError("non-object JSONL row at %s:%d" % (path, line_number))
            yield value


def _iter_jsonl_chunks(paths: Sequence[Path]) -> Iterator[Mapping[str, Any]]:
    """Read exact adjacent byte chunks while dropping envelope edge fragments.

    The first range begins inside a Yelp row and the last range ends inside a
    Goodreads row.  Internal chunk boundaries are reassembled byte-for-byte.
    """

    if not paths:
        raise ValueError("at least one item range chunk is required")
    carry = b""
    skipped_first_fragment = False
    for path in paths:
        with path.open("rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                carry += block
                rows = carry.split(b"\n")
                carry = rows.pop()
                for raw in rows:
                    if not skipped_first_fragment:
                        skipped_first_fragment = True
                        continue
                    if not raw.strip():
                        continue
                    try:
                        value = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ValueError("invalid full JSONL row in item range %s" % path) from exc
                    if not isinstance(value, dict):
                        raise ValueError("non-object JSONL row in item range %s" % path)
                    yield value
    # ``carry`` is the intentionally incomplete final Goodreads row.


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else float(default)


def _text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalise_product(row: Mapping[str, Any]) -> Product:
    details = dict(row.get("details") or {})
    features = _text_list(row.get("features"))
    categories = _text_list(row.get("categories"))
    descriptions = _text_list(row.get("description"))
    category = str(row.get("main_category") or (categories[0] if categories else "unknown"))
    brand = str(row.get("store") or details.get("Brand") or "unknown")
    attributes: Dict[str, Any] = {
        "main_category": category,
        "details": details,
        "features": features[:30],
        "price_missing": row.get("price") is None,
    }
    tags = categories[:10] + features[:10]
    return Product(
        product_id=str(row.get("item_id") or ""),
        name=str(row.get("title") or ""),
        category=category,
        brand=brand,
        price=_as_float(row.get("price"), 0.0),
        currency="USD",
        description=" ".join(descriptions)[:4000],
        attributes=attributes,
        tags=tags,
        rating=_as_float(row.get("average_rating"), 0.0),
        review_count=int(_as_float(row.get("rating_number"), 0.0)),
        review_snippets=[],
        available=True,
        controlled=False,
        source=AGENTRECBENCH_SOURCE,
    )


def _normalise_review(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "review_id": str(row.get("review_id") or ""),
        "user_id": str(row.get("user_id") or ""),
        "item_id": str(row.get("item_id") or ""),
        "stars": _as_float(row.get("stars"), 0.0),
        "title": str(row.get("title") or ""),
        "text": str(row.get("text") or ""),
        "timestamp": row.get("timestamp"),
        "verified_purchase": row.get("verified_purchase"),
        "source": AGENTRECBENCH_SOURCE,
        "controlled": False,
    }


@dataclass(frozen=True)
class RealRecommendationTask:
    task_id: str
    scenario: str
    user_id: str
    candidate_ids: List[str]
    target_product_id: str
    review_ids: List[str]
    source: str = AGENTRECBENCH_SOURCE
    controlled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "scenario": self.scenario,
            "user_id": self.user_id,
            "candidate_ids": list(self.candidate_ids),
            "target_product_id": self.target_product_id,
            "review_ids": list(self.review_ids),
            "source": self.source,
            "controlled": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RealRecommendationTask":
        return cls(
            task_id=str(value.get("task_id") or ""),
            scenario=str(value.get("scenario") or ""),
            user_id=str(value.get("user_id") or ""),
            candidate_ids=[str(item) for item in value.get("candidate_ids") or []],
            target_product_id=str(value.get("target_product_id") or ""),
            review_ids=[str(item) for item in value.get("review_ids") or []],
            source=str(value.get("source") or AGENTRECBENCH_SOURCE),
            controlled=False,
        )


@dataclass(frozen=True)
class AgentRecBenchSubset:
    manifest: Dict[str, Any]
    products: List[Product]
    reviews: List[Dict[str, Any]]
    tasks: List[RealRecommendationTask]

    @property
    def products_by_id(self) -> Dict[str, Product]:
        return {item.product_id: item for item in self.products}

    @property
    def reviews_by_user(self) -> Dict[str, List[Dict[str, Any]]]:
        result: Dict[str, List[Dict[str, Any]]] = {}
        for review in self.reviews:
            result.setdefault(str(review["user_id"]), []).append(review)
        return result

    @property
    def reviews_by_id(self) -> Dict[str, Dict[str, Any]]:
        return {str(review["review_id"]): review for review in self.reviews}


def _load_task_rows(task_root: Path, scenario: str, max_tasks: int) -> List[Dict[str, Any]]:
    task_paths = sorted((task_root / "tasks").glob("task_*.json"), key=_numeric_suffix)
    if len(task_paths) < max_tasks:
        raise ValueError("requested %d tasks but found %d" % (max_tasks, len(task_paths)))
    rows: List[Dict[str, Any]] = []
    for task_path in task_paths[:max_tasks]:
        index = _numeric_suffix(task_path)
        truth_path = task_root / "groundtruth" / ("groundtruth_%d.json" % index)
        if not truth_path.exists():
            raise ValueError("missing ground truth: %s" % truth_path)
        task = _read_json(task_path)
        truth = _read_json(truth_path)
        if str(task.get("data type") or "").lower() != "real":
            raise ValueError("benchmark task is not marked real: %s" % task_path)
        candidates = [str(item) for item in task.get("candidate_list") or []]
        target = str(truth.get("ground truth") or "")
        if not candidates or len(candidates) != len(set(candidates)):
            raise ValueError("candidate list must be non-empty and unique: %s" % task_path)
        if target not in candidates:
            raise ValueError("ground truth is outside candidate list: %s" % task_path)
        rows.append(
            {
                "task_id": "%s_amazon_%d" % (scenario, index),
                "scenario": "agentrecbench_%s" % scenario,
                "user_id": str(task.get("user_id") or ""),
                "candidate_ids": candidates,
                "target_product_id": target,
            }
        )
    return rows


def build_processed_subset(
    *,
    task_root: Union[str, Path],
    item_chunks: Sequence[Union[str, Path]],
    review_path: Union[str, Path],
    output_path: Union[str, Path],
    scenario: str = "short_term",
    max_tasks: int = 100,
    provenance: Optional[Mapping[str, Any]] = None,
) -> Path:
    """Build one auditable real-log subset and fail closed on missing rows."""

    root = Path(task_root)
    chunks = [Path(path) for path in item_chunks]
    reviews_file = Path(review_path)
    destination = Path(output_path)
    task_rows = _load_task_rows(root, scenario, int(max_tasks))
    candidate_ids = {
        item for task in task_rows for item in task["candidate_ids"]
    }
    user_ids = {str(task["user_id"]) for task in task_rows}

    reviews: List[Dict[str, Any]] = []
    review_source_counts: Dict[str, int] = {}
    for row in _iter_jsonl(reviews_file):
        source = str(row.get("source") or "unknown")
        review_source_counts[source] = review_source_counts.get(source, 0) + 1
        if source == "amazon" and str(row.get("user_id") or "") in user_ids:
            reviews.append(_normalise_review(row))
    reviews.sort(
        key=lambda row: (
            str(row.get("user_id") or ""),
            str(row.get("timestamp") or ""),
            str(row.get("review_id") or ""),
        )
    )
    history_item_ids = {
        str(review.get("item_id") or "") for review in reviews if review.get("item_id")
    }
    selected_item_ids = candidate_ids.union(history_item_ids)

    products: Dict[str, Product] = {}
    source_counts: Dict[str, int] = {}
    for row in _iter_jsonl_chunks(chunks):
        source = str(row.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        item_id = str(row.get("item_id") or "")
        if source == "amazon" and item_id in selected_item_ids:
            if item_id in products:
                raise ValueError("duplicate selected item metadata: %s" % item_id)
            product = _normalise_product(row)
            if not product.product_id or not product.name:
                raise ValueError("selected item metadata lacks item_id/title: %s" % item_id)
            products[item_id] = product
    missing = sorted(candidate_ids - set(products))
    if missing:
        raise ValueError(
            "missing real metadata for %d candidate IDs (first: %s)"
            % (len(missing), ", ".join(missing[:10]))
        )
    if "amazon" not in source_counts or len(source_counts) < 2:
        raise ValueError("item byte envelope did not demonstrate an external source boundary")
    missing_history_items = sorted(history_item_ids - set(products))
    reviews_by_user: Dict[str, List[Dict[str, Any]]] = {}
    for review in reviews:
        reviews_by_user.setdefault(str(review["user_id"]), []).append(review)

    tasks = [
        RealRecommendationTask(
            task_id=str(row["task_id"]),
            scenario=str(row["scenario"]),
            user_id=str(row["user_id"]),
            candidate_ids=list(row["candidate_ids"]),
            target_product_id=str(row["target_product_id"]),
            review_ids=[
                str(review["review_id"])
                for review in reviews_by_user.get(str(row["user_id"]), [])
                if str(review.get("item_id") or "") not in set(row["candidate_ids"])
            ],
        )
        for row in task_rows
    ]
    excluded_candidate_reviews = sum(
        len(reviews_by_user.get(task.user_id, [])) - len(task.review_ids) for task in tasks
    )
    manifest: Dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": AGENTRECBENCH_DATASET_ID,
        "dataset_revision": AGENTRECBENCH_REVISION,
        "source": AGENTRECBENCH_SOURCE,
        "domain": "amazon",
        "scenario": scenario,
        "controlled": False,
        "data_type": "real_log",
        "task_count": len(tasks),
        "candidate_product_count": len(candidate_ids),
        "selected_product_count": len(products),
        "selected_review_count": len(reviews),
        "users_with_history": len({row["user_id"] for row in reviews}),
        "task_visible_review_count": sum(len(task.review_ids) for task in tasks),
        "candidate_history_reviews_excluded": excluded_candidate_reviews,
        "history_item_count": len(history_item_ids),
        "resolved_history_product_count": len(history_item_ids.intersection(products)),
        "missing_history_product_count": len(missing_history_items),
        "missing_history_product_ids": missing_history_items,
        "item_envelope_source_counts": source_counts,
        "review_source_counts": review_source_counts,
        "raw_inputs": {
            "tasks_root": str(root),
            "item_chunks": [
                {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
                for path in chunks
            ],
            "review": {
                "path": str(reviews_file),
                "bytes": reviews_file.stat().st_size,
                "sha256": sha256_file(reviews_file),
            },
        },
    }
    manifest.update(dict(provenance or {}))
    payload = {
        "manifest": manifest,
        "products": [products[item_id].to_dict() for item_id in sorted(products)],
        "reviews": reviews,
        "tasks": [task.to_dict() for task in tasks],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def load_processed_subset(path: Union[str, Path]) -> AgentRecBenchSubset:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("processed AgentRecBench subset must be a JSON object")
    manifest = dict(payload.get("manifest") or {})
    if manifest.get("controlled") is not False or manifest.get("data_type") != "real_log":
        raise ValueError("real-data artifact must be explicitly marked controlled=false/data_type=real_log")
    if manifest.get("dataset_revision") != AGENTRECBENCH_REVISION:
        raise ValueError("unexpected AgentRecBench dataset revision")
    products = [Product.from_dict(row) for row in payload.get("products") or []]
    if not products or any(item.controlled for item in products):
        raise ValueError("real-data products must be non-empty and controlled=false")
    if len({item.product_id for item in products}) != len(products):
        raise ValueError("real-data product IDs must be unique")
    tasks = [RealRecommendationTask.from_dict(row) for row in payload.get("tasks") or []]
    product_ids = {item.product_id for item in products}
    for task in tasks:
        if task.controlled or task.source != AGENTRECBENCH_SOURCE:
            raise ValueError("real benchmark task has an invalid source boundary")
        if task.target_product_id not in task.candidate_ids:
            raise ValueError("task target is outside candidates: %s" % task.task_id)
        if not set(task.candidate_ids).issubset(product_ids):
            raise ValueError("task candidates lack processed product rows: %s" % task.task_id)
    reviews = [dict(row) for row in payload.get("reviews") or []]
    if any(row.get("controlled") is not False for row in reviews):
        raise ValueError("real reviews must be explicitly marked controlled=false")
    return AgentRecBenchSubset(
        manifest=manifest,
        products=products,
        reviews=reviews,
        tasks=tasks,
    )
