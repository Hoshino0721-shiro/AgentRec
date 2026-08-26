"""Deterministic user simulator with hidden acceptance state."""

from __future__ import annotations

from typing import Any, Dict, Sequence

from agentrec.domain.models import Feedback, Task


class UserSimulator:
    def __init__(self, task: Task) -> None:
        self.task = task
        self._accepted = False
        self._clarified = False

    def initial_request(self) -> str:
        return self.task.request

    @property
    def is_accepted(self) -> bool:
        return self._accepted

    def clarify(self, question: str) -> Dict[str, Any]:
        self._clarified = True
        constraints = list(self.task.metadata.get("clarification_constraints") or [])
        preferences = list(self.task.metadata.get("clarification_preferences") or [])
        return {
            "question": question,
            "constraints": constraints,
            "preferences": preferences,
            "recipient": self.task.recipient,
            "useful": bool(constraints or preferences),
            "controlled": True,
        }

    def evaluate(self, product_ids: Sequence[str], attempt: int = 1) -> Feedback:
        ranked = [str(value) for value in product_ids]
        if self.task.scenario == "rejection_recovery" and int(attempt) == 1:
            base = self.task.feedback
            rejected = list(base.rejected_product_ids) or ranked[:1]
            return Feedback(
                accepted=False,
                reason=base.reason,
                product_ids=ranked,
                rejected_product_ids=rejected,
                new_constraints=list(base.new_constraints),
                new_preferences=list(base.new_preferences),
                attempt=1,
                recipient=self.task.recipient,
                timestamp=base.timestamp,
                controlled=True,
            )

        selected = ranked[0] if ranked else None
        accepted = selected in set(self.task.acceptance.relevant_product_ids)
        self._accepted = accepted
        reason = (
            "The first-ranked product satisfies the controlled acceptance criteria."
            if accepted
            else "The first-ranked product does not satisfy the controlled acceptance criteria."
        )
        return Feedback(
            accepted=accepted,
            reason=reason,
            product_ids=ranked,
            rejected_product_ids=[] if accepted or selected is None else [selected],
            attempt=int(attempt),
            recipient=self.task.recipient,
            timestamp=self.task.feedback.timestamp,
            controlled=True,
        )


__all__ = ["UserSimulator"]

