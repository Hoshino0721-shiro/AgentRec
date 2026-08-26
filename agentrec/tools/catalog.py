"""Local, deterministic catalog search, filtering, ranking, and comparison."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from agentrec.domain.models import Constraint, Preference, Product


CATEGORY_ALIASES = {
    "headphones": ("headphone", "headphones", "earbuds", "耳机"),
    "shoes": ("shoe", "shoes", "sneaker", "sneakers", "鞋", "跑步"),
    "backpacks": ("backpack", "bag", "背包", "书包"),
    "coffee_makers": ("coffee", "coffee maker", "咖啡", "咖啡机"),
}


def _default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "processed" / "catalog.json"


def load_catalog(path: Optional[Union[str, Path]] = None) -> List[Product]:
    source = Path(path) if path is not None else _default_catalog_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    rows = payload.get("products") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("catalog JSON must contain a products list")
    products = [Product.from_dict(row) for row in rows]
    if not products or len({product.product_id for product in products}) != len(products):
        raise ValueError("catalog must contain non-empty, unique product IDs")
    if any(not product.controlled for product in products):
        raise ValueError("the bundled catalog may only contain controlled products")
    return products


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(text).lower())


def _category_from_query(query: str) -> Optional[str]:
    lowered = str(query).lower()
    for category, aliases in CATEGORY_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return category
    return None


def _product_text(product: Product) -> str:
    return " ".join(
        [
            product.product_id,
            product.name,
            product.category,
            product.brand,
            product.description,
            " ".join(product.tags),
            json.dumps(product.attributes, ensure_ascii=False, sort_keys=True),
        ]
    ).lower()


def _coerce_constraint(value: Union[Constraint, Mapping[str, Any]]) -> Constraint:
    return value if isinstance(value, Constraint) else Constraint.from_dict(value)


def _coerce_preference(value: Union[Preference, Mapping[str, Any]]) -> Preference:
    return value if isinstance(value, Preference) else Preference.from_dict(value)


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (list, tuple, set)):
        return expected in actual
    return str(expected).lower() in str(actual).lower()


def constraint_satisfied(product: Product, constraint: Union[Constraint, Mapping[str, Any]]) -> bool:
    item = _coerce_constraint(constraint)
    actual = product.value_for(item.field)
    expected = item.value
    operator = item.operator.lower()
    if operator == "exists":
        return (actual is not None) is bool(expected)
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "lte":
        return actual is not None and actual <= expected
    if operator == "lt":
        return actual is not None and actual < expected
    if operator == "gte":
        return actual is not None and actual >= expected
    if operator == "gt":
        return actual is not None and actual > expected
    if operator == "in":
        return actual in expected
    if operator == "not_in":
        return actual not in expected
    if operator == "contains":
        return actual is not None and _contains(actual, expected)
    if operator == "not_contains":
        return actual is None or not _contains(actual, expected)
    raise ValueError(f"unsupported constraint operator: {item.operator}")


class CatalogTool:
    def __init__(
        self,
        products: Optional[Sequence[Product]] = None,
        profile_reader: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.products = list(products) if products is not None else load_catalog()
        self._by_id = {product.product_id: product for product in self.products}
        self.profile_reader = profile_reader

    def get_product(self, product_id: Optional[str]) -> Optional[Product]:
        return self._by_id.get(str(product_id)) if product_id is not None else None

    def _lexical_score(self, product: Product, query: str) -> float:
        if not query:
            return 0.0
        text = _product_text(product)
        score = 0.0
        for token in _tokens(query):
            if token in text:
                score += 1.0
        category = _category_from_query(query)
        if category == product.category:
            score += 4.0
        if product.brand.lower() in query.lower() or product.name.lower() in query.lower():
            score += 4.0
        return score

    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[Product]:
        inferred = category or _category_from_query(query)
        candidates = [
            product
            for product in self.products
            if product.available and (inferred is None or product.category == inferred)
        ]
        scored = [(self._lexical_score(product, query), product) for product in candidates]
        if query and inferred is None:
            positive = [pair for pair in scored if pair[0] > 0]
            if positive:
                scored = positive
        scored.sort(key=lambda pair: (-pair[0], pair[1].product_id))
        return [product for _, product in scored[: max(0, int(limit))]]

    def filter_constraints(
        self,
        candidates: Sequence[Union[Product, str]],
        constraints: Sequence[Union[Constraint, Mapping[str, Any]]],
    ) -> List[Product]:
        products = [
            value if isinstance(value, Product) else self._by_id.get(str(value))
            for value in candidates
        ]
        hard = []
        for value in constraints:
            item = _coerce_constraint(value)
            if item.hard:
                hard.append(item)
        return [
            product
            for product in products
            if product is not None and all(constraint_satisfied(product, item) for item in hard)
        ]

    @staticmethod
    def _preference_match(product: Product, preference: Preference) -> float:
        actual = product.value_for(preference.attribute)
        expected = preference.value
        if isinstance(expected, dict) and "operator" in expected:
            item = Constraint(
                field=preference.attribute,
                operator=str(expected["operator"]),
                value=expected.get("value"),
            )
            matched = constraint_satisfied(product, item)
        elif isinstance(actual, (list, tuple, set)):
            matched = expected in actual
        elif isinstance(actual, str) and isinstance(expected, str):
            matched = actual.lower() == expected.lower()
        else:
            matched = actual == expected
        direction = -1.0 if preference.polarity == "avoid" else 1.0
        return direction * float(preference.weight) * float(preference.confidence) * (3.0 if matched else -0.25)

    def rank(
        self,
        candidates: Sequence[Union[Product, str]],
        preferences: Sequence[Union[Preference, Mapping[str, Any]]] = (),
        query: str = "",
        limit: int = 10,
    ) -> List[Product]:
        products = [
            value if isinstance(value, Product) else self._by_id.get(str(value))
            for value in candidates
        ]
        prefs = [_coerce_preference(value) for value in preferences]
        scored = []
        for product in products:
            if product is None:
                continue
            score = self._lexical_score(product, query)
            score += product.rating * 0.20
            score += math.log1p(product.review_count) * 0.02
            score += sum(self._preference_match(product, preference) for preference in prefs)
            scored.append((score, product))
        scored.sort(key=lambda pair: (-pair[0], pair[1].price, pair[1].product_id))
        return [product for _, product in scored[: max(0, int(limit))]]

    def compare(self, product_ids: Sequence[str]) -> Dict[str, Any]:
        products = [self._by_id[value] for value in product_ids if value in self._by_id]
        return {
            "product_ids": [product.product_id for product in products],
            "products": [
                {
                    "product_id": product.product_id,
                    "name": product.name,
                    "brand": product.brand,
                    "price": product.price,
                    "currency": product.currency,
                    "rating": product.rating,
                    "attributes": dict(product.attributes),
                }
                for product in products
            ],
            "controlled": True,
        }

    def review_summary(self, product_id: str) -> Dict[str, Any]:
        product = self._by_id.get(str(product_id))
        if product is None:
            return {"product_id": product_id, "error": "unknown product", "controlled": True}
        return {
            "product_id": product.product_id,
            "rating": product.rating,
            "review_count": product.review_count,
            "summary": " ".join(product.review_snippets[:2]),
            "controlled": True,
            "source": product.source,
        }

    def read_profile(self, subject: str = "self") -> Any:
        if self.profile_reader is None:
            return []
        return self.profile_reader(subject)


__all__ = ["CatalogTool", "constraint_satisfied", "load_catalog"]

