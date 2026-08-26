"""Observable rule-based planner used by the offline reproducibility path."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence


@dataclass(frozen=True)
class PlanStep:
    action: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


class DeterministicPlanner:
    """Select actions from visible request state, without accessing acceptance labels."""

    _AMBIGUOUS_MARKERS = (
        "anything",
        "something",
        "not sure",
        "surprise me",
        "随便",
        "不知道",
        "帮我挑",
        "都可以",
        "礼物",
        "送给",
        "gift",
    )

    def should_clarify(
        self,
        request: str,
        *,
        known_constraints: Sequence[Mapping[str, Any]] = (),
        known_preferences: Sequence[Mapping[str, Any]] = (),
    ) -> bool:
        text = request.lower().strip()
        if any(marker in text for marker in self._AMBIGUOUS_MARKERS):
            return True
        has_budget = bool(re.search(r"(?:[$¥￥]\s*\d|\d+\s*(?:元|rmb|usd|dollars?))", text))
        has_detail = bool(known_constraints or known_preferences)
        # A very short, unqualified request is observably underspecified.
        word_like = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text)
        return len(word_like) <= 4 and not has_budget and not has_detail

    def clarification_question(self, request: str, recipient: str) -> str:
        recipient_phrase = "收礼人的" if recipient != "self" else "你的"
        return f"为了缩小候选，请补充{recipient_phrase}预算上限、必须满足的条件，以及最看重或想避开的属性。"

    def initial_plan(self, *, use_memory: bool, clarify: bool) -> List[PlanStep]:
        plan = [PlanStep("observe_request", "establish recipient and currently stated constraints")]
        if use_memory:
            plan.append(PlanStep("retrieve_preferences", "retrieve only relevant, active evidence"))
        if clarify:
            plan.append(PlanStep("ask_clarifying_question", "resolve observable missing decision variables"))
        plan.extend(
            [
                PlanStep("search_products", "recall candidates from the local catalog"),
                PlanStep("filter_constraints", "enforce hard constraints before ranking"),
                PlanStep("rank_candidates", "score the fixed candidate pool using visible preferences"),
                PlanStep("compare_products", "ground the recommendation in catalog attributes"),
                PlanStep("recommend", "present a bounded ranked slate"),
            ]
        )
        return plan

    def recovery_plan(self) -> List[PlanStep]:
        return [
            PlanStep("reflect_on_feedback", "identify why the first slate was rejected"),
            PlanStep("update_memory", "record scoped feedback evidence"),
            PlanStep("search_products", "retrieve alternatives under revised state"),
            PlanStep("filter_constraints", "apply newly revealed hard constraints"),
            PlanStep("rank_candidates", "exclude rejected options and re-rank"),
            PlanStep("recommend", "issue a materially revised slate"),
        ]

