from agentrec.domain.models import Constraint, Preference
from agentrec.tools.catalog import CatalogTool, load_catalog


def test_catalog_is_controlled_unique_and_deterministic():
    first = load_catalog()
    second = load_catalog()
    assert len(first) == 32
    assert [item.product_id for item in first] == [item.product_id for item in second]
    assert len({item.product_id for item in first}) == 32
    assert all(item.controlled and item.source == "controlled_catalog_v1" for item in first)


def test_search_filter_rank_compare_and_reviews():
    tool = CatalogTool(load_catalog())
    candidates = tool.search("waterproof walking shoes", limit=20)
    assert candidates and all(item.category == "shoes" for item in candidates)
    constraints = [
        Constraint("price", "lte", 100),
        Constraint("size", "eq", 9),
        Constraint("waterproof", "eq", True),
        Constraint("vegan", "eq", True),
    ]
    filtered = tool.filter_constraints(candidates, constraints)
    assert [item.product_id for item in filtered] == ["S003"]
    ranked = tool.rank(
        tool.search("wireless headphones", limit=20),
        preferences=[Preference("brand", "Grove", confidence=1.0)],
        query="wireless headphones",
    )
    assert ranked[0].product_id == "H007"
    comparison = tool.compare(["H007", "H001"])
    assert comparison["product_ids"] == ["H007", "H001"]
    assert tool.review_summary("H007")["controlled"] is True


def test_hard_constraints_are_never_relaxed_by_ranker():
    tool = CatalogTool(load_catalog())
    products = tool.filter_constraints(
        tool.search("coffee maker", limit=20),
        [
            Constraint("price", "lte", 60),
            Constraint("programmable", "eq", True),
            Constraint("capacity_cups", "lte", 4),
        ],
    )
    assert [item.product_id for item in products] == ["C002"]
    assert tool.rank(products, query="coffee maker")[0].product_id == "C002"

