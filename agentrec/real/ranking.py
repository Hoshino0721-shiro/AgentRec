"""Deterministic, target-blind baselines for AgentRecBench real tasks."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from agentrec.data.agentrecbench import RealRecommendationTask
from agentrec.domain.models import Product


_STOP_WORDS = {
    "about", "after", "again", "also", "amazon", "because", "been", "before",
    "being", "bought", "could", "from", "good", "great", "have", "into", "item",
    "just", "like", "more", "much", "only", "other", "product", "really", "than",
    "that", "their", "them", "then", "there", "these", "they", "this", "very",
    "what", "when", "which", "with", "would", "your",
}


def _tokens(value: Any) -> List[str]:
    result = re.findall(r"[a-z0-9]+", str(value or "").lower())
    return [token for token in result if len(token) >= 3 and token not in _STOP_WORDS]


def _product_tokens(product: Product) -> List[str]:
    text = " ".join(
        [
            product.name,
            product.category,
            product.brand,
            product.description,
            " ".join(product.tags),
            json.dumps(product.attributes, ensure_ascii=False, sort_keys=True),
        ]
    )
    return _tokens(text)


def _popularity(product: Product) -> float:
    return float(product.rating) + 0.15 * math.log1p(max(0, int(product.review_count)))


def _history_weights(
    reviews: Sequence[Mapping[str, Any]],
    products_by_id: Mapping[str, Product],
    *,
    recency: bool,
    history_window: int,
) -> Dict[str, float]:
    ordered = sorted(
        reviews,
        key=lambda row: (str(row.get("timestamp") or ""), str(row.get("review_id") or "")),
    )
    if recency:
        ordered = ordered[-max(1, int(history_window)):]
    weights: Dict[str, float] = defaultdict(float)
    total = len(ordered)
    for index, review in enumerate(ordered):
        stars = float(review.get("stars") or 0.0)
        polarity = 1.0 if stars >= 4.0 else (-1.0 if stars <= 2.0 else 0.15)
        recency_weight = (index + 1) / max(1, total) if recency else 1.0
        weight = polarity * recency_weight
        for token in _tokens("%s %s" % (review.get("title") or "", review.get("text") or "")):
            weights[token] += weight
        reviewed = products_by_id.get(str(review.get("item_id") or ""))
        if reviewed is not None:
            for token in _product_tokens(reviewed):
                weights[token] += 0.35 * weight
    return dict(weights)


def _profile_score(product: Product, weights: Mapping[str, float]) -> float:
    unique = set(_product_tokens(product))
    lexical = sum(float(weights.get(token, 0.0)) for token in unique)
    normalizer = math.sqrt(max(1.0, float(len(unique))))
    return lexical / normalizer + 0.03 * _popularity(product)


def rank_real_task(
    *,
    system: str,
    task: RealRecommendationTask,
    products_by_id: Mapping[str, Product],
    reviews: Sequence[Mapping[str, Any]],
    limit: int = 5,
) -> Tuple[List[str], Dict[str, Any]]:
    """Rank without reading ``task.target_product_id``."""

    candidates = [products_by_id[item_id] for item_id in task.candidate_ids]
    if system == "candidate_order":
        scored = [(float(-index), product) for index, product in enumerate(candidates)]
        profile_terms: List[Tuple[str, float]] = []
    elif system == "popularity":
        scored = [(_popularity(product), product) for product in candidates]
        profile_terms = []
    elif system in {"full_history_lexical", "short_term_recency"}:
        weights = _history_weights(
            reviews,
            products_by_id,
            recency=system == "short_term_recency",
            history_window=10,
        )
        scored = [(_profile_score(product, weights), product) for product in candidates]
        profile_terms = sorted(weights.items(), key=lambda pair: (-abs(pair[1]), pair[0]))[:20]
    else:
        raise ValueError("unknown real-data system: %s" % system)
    scored.sort(key=lambda pair: (-pair[0], pair[1].product_id))
    ranked = [product.product_id for _, product in scored[: max(0, int(limit))]]
    audit = {
        "system": system,
        "history_count": len(reviews),
        "candidate_count": len(candidates),
        "profile_terms": [[term, round(value, 6)] for term, value in profile_terms],
        "top_scores": [
            {"product_id": product.product_id, "score": round(score, 8)}
            for score, product in scored[: max(0, int(limit))]
        ],
        "target_blind": True,
    }
    return ranked, audit
