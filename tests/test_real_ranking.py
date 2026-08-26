from agentrec.data.agentrecbench import RealRecommendationTask
from agentrec.domain.models import Product
from agentrec.real.ranking import rank_real_task


def _product(product_id, name, rating=4.0, count=10):
    return Product(
        product_id=product_id,
        name=name,
        category="test",
        brand="brand",
        price=10,
        rating=rating,
        review_count=count,
        controlled=False,
        source="agentrecbench_amazon_short_v1",
    )


def test_real_ranker_is_deterministic_target_blind_and_profile_aware():
    products = {
        "A": _product("A", "durable red cable", 4.0, 10),
        "B": _product("B", "fragile blue cable", 4.9, 1000),
        "H": _product("H", "durable red adapter", 4.5, 50),
    }
    task = RealRecommendationTask(
        task_id="t0",
        scenario="agentrecbench_short_term",
        user_id="u0",
        candidate_ids=["A", "B"],
        target_product_id="B",
        review_ids=["r0"],
    )
    reviews = [
        {
            "review_id": "r0",
            "user_id": "u0",
            "item_id": "H",
            "stars": 5,
            "text": "Durable red hardware is exactly what I value.",
            "timestamp": 1,
        }
    ]
    ranked, audit = rank_real_task(
        system="short_term_recency",
        task=task,
        products_by_id=products,
        reviews=reviews,
    )
    assert ranked == ["A", "B"]
    assert audit["target_blind"] is True
    changed_target = RealRecommendationTask(
        task_id=task.task_id,
        scenario=task.scenario,
        user_id=task.user_id,
        candidate_ids=task.candidate_ids,
        target_product_id="A",
        review_ids=task.review_ids,
    )
    repeated, _ = rank_real_task(
        system="short_term_recency",
        task=changed_target,
        products_by_id=products,
        reviews=reviews,
    )
    assert repeated == ranked
