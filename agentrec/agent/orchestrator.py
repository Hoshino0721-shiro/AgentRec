"""End-to-end autonomous shopping loop for deterministic experiments."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from agentrec.agent.planner import DeterministicPlanner
from agentrec.agent.policy import AgentFeatures, features_for_system
from agentrec.agent.reflection import reflect_on_feedback
from agentrec.agent.trace import TrajectoryRecorder, jsonable
from agentrec.domain.models import Constraint, Preference, Product, Task
from agentrec.experiments.metrics import recommendation_metrics
from agentrec.memory import create_memory_store
from agentrec.simulation.user_simulator import UserSimulator
from agentrec.tools.catalog import CatalogTool


def _dict(value: Any) -> Dict[str, Any]:
    result = jsonable(value)
    return dict(result) if isinstance(result, dict) else {}


def _subject(recipient: str) -> str:
    recipient = str(recipient or "self")
    if recipient == "self" or recipient.startswith("recipient:"):
        return recipient
    return "recipient:" + recipient


def _task_time(task: Task) -> datetime:
    raw = (
        task.metadata.get("current_time")
        or task.metadata.get("timestamp")
        or getattr(task.feedback, "timestamp", None)
        or "2026-01-15T10:00:00Z"
    )
    if isinstance(raw, datetime):
        value = raw
    else:
        text = str(raw).replace("Z", "+00:00")
        value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _constraint(value: Any) -> Constraint:
    if isinstance(value, Constraint):
        return value
    return Constraint.from_dict(_dict(value))


def _preference(value: Any) -> Preference:
    if isinstance(value, Preference):
        return value
    return Preference.from_dict(_dict(value))


class ShoppingAgent:
    """A stateful Agent harness; memory persists across tasks within one run."""

    def __init__(
        self,
        *,
        system: str,
        catalog: CatalogTool,
        seed: int = 42,
        max_turns: int = 8,
        max_tool_calls: int = 12,
    ) -> None:
        self.system = system
        self.features: AgentFeatures = features_for_system(system)
        self.catalog = catalog
        self.seed = int(seed)
        self.max_turns = int(max_turns)
        self.max_tool_calls = int(max_tool_calls)
        self.planner = DeterministicPlanner()
        self.memory = create_memory_store(
            self.features.memory_mode,
            temporal_decay=self.features.temporal_decay,
            recipient_isolation=self.features.recipient_isolation,
        )

    def _visible_state(self, task: Task) -> Tuple[List[Constraint], List[Preference]]:
        # Scenarios may explicitly separate what is stated initially from the
        # evaluator's full oracle constraints.  Older tasks default to their
        # public task fields for backward compatibility.
        raw_constraints = task.metadata.get("initial_constraints")
        raw_preferences = task.metadata.get("initial_preferences")
        constraints = (
            [_constraint(value) for value in raw_constraints]
            if raw_constraints is not None
            else list(task.hard_constraints)
        )
        preferences = (
            [_preference(value) for value in raw_preferences]
            if raw_preferences is not None
            else list(task.preferences)
        )
        return constraints, preferences

    def _memory_entry(
        self,
        *,
        task: Task,
        event_id: str,
        subject: str,
        attribute: str,
        value: Any,
        polarity: str,
        source: str,
        layer: str,
        confidence: float,
        now: datetime,
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        timestamp = now.isoformat().replace("+00:00", "Z")
        return {
            "memory_id": f"{task.task_id}:{event_id}:{attribute}",
            "layer": layer,
            "subject": subject,
            "attribute": attribute,
            "value": value,
            "polarity": polarity,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "source": source,
            "evidence_event_ids": [f"{task.task_id}:{event_id}"],
            "created_at": timestamp,
            "valid_from": timestamp,
            "expires_at": expires_at,
            "status": "active",
            "supersedes": None,
        }

    def _write_memory(self, entry: Mapping[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
        result = self.memory.write(entry, now=now)
        return result.to_dict() if result is not None else None

    def _seed_memory(self, task: Task, now: datetime) -> List[Dict[str, Any]]:
        writes: List[Dict[str, Any]] = []
        for index, raw in enumerate(task.initial_memories):
            data = dict(raw)
            data["memory_id"] = f"{task.task_id}:seed:{index}:{data.get('memory_id', data.get('attribute', 'memory'))}"
            data.setdefault("layer", data.get("scope", "stable"))
            data.setdefault("subject", "self")
            data.setdefault("attribute", data.get("field", "preference"))
            data.setdefault("value", None)
            data.setdefault("polarity", "prefer")
            data.setdefault("confidence", 0.8)
            data.setdefault("source", "repeated_behavior")
            original_evidence = list(data.get("evidence_event_ids") or ["seed"])
            data["evidence_event_ids"] = [
                f"{task.task_id}:historical:{index}:{value}" for value in original_evidence
            ]
            data.setdefault("created_at", now.isoformat().replace("+00:00", "Z"))
            data.setdefault("valid_from", data["created_at"])
            data.setdefault("expires_at", None)
            data.setdefault("status", "active")
            data.setdefault("supersedes", None)
            written = self._write_memory(data, now)
            if written:
                writes.append(written)
        return writes

    def _write_preferences(
        self,
        task: Task,
        preferences: Sequence[Preference],
        *,
        event_prefix: str,
        now: datetime,
    ) -> List[Dict[str, Any]]:
        writes = []
        for index, preference in enumerate(preferences):
            subject = _subject(preference.subject or task.recipient)
            scope = str(preference.scope or "session")
            if subject.startswith("recipient:"):
                layer = "recipient"
            elif scope in {"stable", "stage", "session"}:
                layer = scope
            else:
                layer = "session"
            entry = self._memory_entry(
                task=task,
                event_id=f"{event_prefix}:preference:{index}",
                subject=subject,
                attribute=preference.attribute,
                value=preference.value,
                polarity=preference.polarity,
                source=preference.source,
                layer=layer,
                confidence=preference.confidence,
                now=now,
            )
            written = self._write_memory(entry, now)
            if written:
                writes.append(written)
        return writes

    def _write_constraints(
        self,
        task: Task,
        constraints: Sequence[Constraint],
        *,
        event_prefix: str,
        now: datetime,
    ) -> List[Dict[str, Any]]:
        writes = []
        for index, constraint in enumerate(constraints):
            entry = self._memory_entry(
                task=task,
                event_id=f"{event_prefix}:constraint:{index}",
                subject=_subject(constraint.subject or task.recipient),
                attribute=constraint.field,
                value={"operator": constraint.operator, "value": constraint.value},
                polarity="required",
                source=constraint.source,
                layer="constraint",
                confidence=1.0,
                now=now,
            )
            written = self._write_memory(entry, now)
            if written:
                writes.append(written)
        return writes

    def _retrieve_memory(
        self, task: Task, now: datetime
    ) -> Tuple[List[Any], List[Constraint], List[Preference]]:
        persistent_origin_layers = {"stable", "stage", "recipient"}
        hits = self.memory.retrieve(
            subject=_subject(task.recipient),
            layers=["stable", "stage", "recipient"],
            now=now,
            min_confidence=0.05,
            limit=20,
        )
        # Flat memory intentionally loses retrieval-layer structure, but its
        # provenance still records the caller's original layer.  Session,
        # constraint, and event evidence must not become cross-task state just
        # because the flat representation stores everything in one slot.
        hits = [
            hit
            for hit in hits
            if (hit.entry.origin_layer or hit.entry.layer) in persistent_origin_layers
        ]
        constraints: List[Constraint] = []
        preferences: List[Preference] = []
        for hit in hits:
            entry = hit.entry
            if entry.layer == "constraint" or entry.polarity == "required":
                raw = entry.value if isinstance(entry.value, dict) else {"operator": "eq", "value": entry.value}
                constraints.append(
                    Constraint(
                        field=entry.attribute,
                        operator=str(raw.get("operator", "eq")),
                        value=raw.get("value"),
                        hard=True,
                        source="memory",
                        subject=entry.subject,
                    )
                )
            else:
                preferences.append(
                    Preference(
                        attribute=entry.attribute,
                        value=entry.value,
                        weight=max(0.1, float(hit.effective_confidence)),
                        polarity=entry.polarity,
                        subject=entry.subject,
                        scope=entry.layer,
                        confidence=float(hit.effective_confidence),
                        source="memory",
                        timestamp=entry.valid_from,
                    )
                )
        return hits, constraints, preferences

    @staticmethod
    def _clarification_values(result: Mapping[str, Any]) -> Tuple[List[Constraint], List[Preference]]:
        constraints = result.get("constraints") or result.get("new_constraints") or result.get("revealed_constraints") or []
        preferences = result.get("preferences") or result.get("new_preferences") or result.get("revealed_preferences") or []
        return ([_constraint(value) for value in constraints], [_preference(value) for value in preferences])

    def _rank_slate(
        self,
        *,
        request: str,
        constraints: Sequence[Constraint],
        preferences: Sequence[Preference],
        excluded: Sequence[str],
        trace: TrajectoryRecorder,
        tool_counter: List[int],
        phase: str,
    ) -> List[Product]:
        def consume() -> None:
            tool_counter[0] += 1
            if tool_counter[0] > self.max_tool_calls:
                raise RuntimeError("tool-call budget exceeded")

        consume()
        candidates = self.catalog.search(query=request, limit=30)
        trace.add(
            "search_products",
            arguments={"query": request, "limit": 30, "phase": phase},
            tool_result=candidates,
            reason="retrieve a deterministic catalog candidate pool",
        )
        if not candidates:
            consume()
            candidates = self.catalog.search(query="", limit=50)
            trace.add(
                "search_products",
                arguments={"query": "", "limit": 50, "phase": phase, "fallback": True},
                tool_result=candidates,
                reason="recover from zero lexical matches without relaxing constraints",
            )
        candidates = [product for product in candidates if product.product_id not in set(excluded)]
        consume()
        filtered = self.catalog.filter_constraints(candidates, constraints)
        trace.add(
            "filter_constraints",
            arguments={"constraint_count": len(constraints), "phase": phase},
            tool_result=filtered,
            constraint_check={"input": len(candidates), "passed": len(filtered)},
            reason="hard constraints are applied before soft ranking",
        )
        consume()
        ranked = self.catalog.rank(filtered, preferences=preferences, query=request, limit=5)
        trace.add(
            "rank_candidates",
            arguments={"preference_count": len(preferences), "phase": phase, "limit": 5},
            tool_result=ranked,
            reason="rank the fixed filtered pool using visible preference evidence",
        )
        if ranked:
            consume()
            comparison = self.catalog.compare([product.product_id for product in ranked[:3]])
            trace.add(
                "compare_products",
                arguments={"product_ids": [product.product_id for product in ranked[:3]], "phase": phase},
                tool_result=comparison,
                reason="ground trade-offs in catalog fields",
            )
            consume()
            summary = self.catalog.review_summary(ranked[0].product_id)
            trace.add(
                "review_summary",
                arguments={"product_id": ranked[0].product_id, "phase": phase},
                tool_result=summary,
                reason="ground qualitative evidence in controlled review snippets",
            )
        return ranked

    def run_task(self, task: Task) -> Dict[str, Any]:
        trace = TrajectoryRecorder()
        simulator = UserSimulator(task)
        now = _task_time(task)
        subject = _subject(task.recipient)
        request = simulator.initial_request()
        constraints, preferences = self._visible_state(task)
        tool_counter = [0]
        turns = 1
        rejection_occurred = False
        memory_hits: List[Any] = []
        memory_writes: List[Dict[str, Any]] = []

        trace.add(
            "observe_request",
            observation={"request": request, "recipient": task.recipient},
            reason="establish current shopping subject and visible state",
        )
        seeded = self._seed_memory(task, now)
        memory_writes.extend(seeded)
        if seeded:
            trace.add(
                "update_memory",
                arguments={"source": "pre_task_history"},
                memory_writes=seeded,
                reason="load frozen historical evidence supplied before this episode",
            )

        should_clarify = self.features.clarification and self.planner.should_clarify(
            request,
            known_constraints=[value.to_dict() for value in constraints],
            known_preferences=[value.to_dict() for value in preferences],
        )
        if self.features.autonomous_planning:
            plan = self.planner.initial_plan(
                use_memory=self.features.memory_mode != "none", clarify=should_clarify
            )
            trace.add(
                "plan",
                observation={"known_constraints": len(constraints), "known_preferences": len(preferences)},
                tool_result=[step.to_dict() for step in plan],
                reason="choose actions from observable state and enabled capabilities",
            )

        if self.features.memory_mode != "none":
            memory_hits, remembered_constraints, remembered_preferences = self._retrieve_memory(task, now)
            constraints.extend(remembered_constraints)
            preferences.extend(remembered_preferences)
            trace.add(
                "retrieve_preferences",
                arguments={"subject": subject},
                memory_reads=[hit.to_dict() for hit in memory_hits],
                tool_result={
                    "constraints": [value.to_dict() for value in remembered_constraints],
                    "preferences": [value.to_dict() for value in remembered_preferences],
                },
                reason="read scoped, active memory before candidate ranking",
            )

        useful_clarification: Optional[float] = None
        if should_clarify:
            question = self.planner.clarification_question(request, task.recipient)
            response = simulator.clarify(question)
            new_constraints, new_preferences = self._clarification_values(response)
            constraints.extend(new_constraints)
            preferences.extend(new_preferences)
            useful_clarification = float(bool(new_constraints or new_preferences))
            turns += 1
            writes = self._write_constraints(
                task, new_constraints, event_prefix="clarification", now=now
            ) + self._write_preferences(
                task, new_preferences, event_prefix="clarification", now=now
            )
            memory_writes.extend(writes)
            trace.add(
                "ask_clarifying_question",
                arguments={"question": question},
                tool_result=response,
                memory_writes=writes,
                reason="resolve missing hard constraints or recipient preferences",
            )

        ranked = self._rank_slate(
            request=request,
            constraints=constraints,
            preferences=preferences,
            excluded=[],
            trace=trace,
            tool_counter=tool_counter,
            phase="initial",
        )
        final_ids = [product.product_id for product in ranked]
        trace.add(
            "recommend",
            arguments={"product_ids": final_ids, "attempt": 1},
            tool_result={"product_ids": final_ids},
            reason="return the top grounded slate after constraints and comparison",
        )
        feedback = simulator.evaluate(final_ids, attempt=1)
        turns += 1
        trace.add(
            "receive_feedback",
            observation=feedback,
            reason="observe deterministic user acceptance or rejection",
        )
        feedback_writes = self._write_constraints(
            task, list(feedback.new_constraints), event_prefix="feedback:1", now=now
        ) + self._write_preferences(
            task, list(feedback.new_preferences), event_prefix="feedback:1", now=now
        )
        memory_writes.extend(feedback_writes)
        if feedback_writes:
            trace.add(
                "update_memory",
                arguments={"attempt": 1, "recipient": task.recipient},
                memory_writes=feedback_writes,
                reason="store explicit feedback with evidence and recipient scope",
            )

        if not feedback.accepted:
            rejection_occurred = True
            if self.features.replanning and turns < self.max_turns:
                reflection = reflect_on_feedback(feedback, final_ids)
                trace.add(
                    "reflect_on_feedback",
                    observation=feedback,
                    tool_result=reflection,
                    reason="convert rejection into a revised constraint/preference state",
                )
                constraints.extend(_constraint(value) for value in reflection.constraints)
                preferences.extend(_preference(value) for value in reflection.preferences)
                trace.add(
                    "replan",
                    tool_result=[step.to_dict() for step in self.planner.recovery_plan()],
                    reason="the first recommendation was rejected; materially revise the slate",
                )
                ranked = self._rank_slate(
                    request=request,
                    constraints=constraints,
                    preferences=preferences,
                    excluded=reflection.rejected_product_ids,
                    trace=trace,
                    tool_counter=tool_counter,
                    phase="recovery",
                )
                final_ids = [product.product_id for product in ranked]
                trace.add(
                    "recommend",
                    arguments={"product_ids": final_ids, "attempt": 2},
                    tool_result={"product_ids": final_ids},
                    reason="issue a revised slate after reflection",
                )
                feedback = simulator.evaluate(final_ids, attempt=2)
                turns += 1
                trace.add(
                    "receive_feedback",
                    observation=feedback,
                    reason="evaluate recovery on the same deterministic user state",
                )

        trace.add(
            "finish",
            observation={"accepted": bool(feedback.accepted)},
            tool_result={"final_product_ids": final_ids},
            reason="terminate after acceptance, recovery attempt, or disabled replanning",
        )

        # The answer and hard-constraint metric must describe the actual
        # first-ranked choice.  Acceptance labels are evaluator-only and may
        # not be used to pick a more favorable item from the returned slate.
        selected_id = final_ids[0] if final_ids else None
        selected_product = self.catalog.get_product(selected_id) if selected_id else None
        if selected_product is not None:
            satisfies = bool(self.catalog.filter_constraints([selected_product], task.hard_constraints))
            explanation = (
                f"{selected_product.name} is {selected_product.brand}, costs "
                f"{selected_product.currency} {selected_product.price:.2f}, and was selected from the filtered catalog."
            )
        else:
            satisfies = False
            explanation = "No catalog product satisfied the visible state."

        task_writes = [
            value
            for value in memory_writes
            if any(str(event).startswith(task.task_id + ":") for event in value.get("evidence_event_ids", []))
        ]
        recipient_origin = [
            value for value in task_writes if str(value.get("origin_subject") or value.get("subject", "")).startswith("recipient:")
        ]
        contaminated = [
            value
            for value in recipient_origin
            if value.get("subject") == "self" and value.get("layer") == "stable"
        ]
        contamination_rate = len(contaminated) / len(recipient_origin) if recipient_origin else 0.0
        write_accuracy = (
            sum(1 for value in task_writes if value not in contaminated) / len(task_writes)
            if task_writes
            else 1.0
        )
        stale_used = 0
        for hit in memory_hits:
            expires = hit.entry.expires_at
            if expires and datetime.fromisoformat(expires.replace("Z", "+00:00")) < now:
                stale_used += 1
        relevant_ids = task.acceptance.relevant_product_ids
        rec_metrics = recommendation_metrics(final_ids, relevant_ids)
        metrics: Dict[str, Optional[float]] = {
            "task_success_rate": float(bool(feedback.accepted)),
            "hard_constraint_satisfaction_rate": float(satisfies),
            "profile_contamination_rate": float(contamination_rate),
            "recovery_success_rate": float(bool(feedback.accepted)) if rejection_occurred else None,
            "useful_clarification_rate": useful_clarification,
            "redundant_tool_call_rate": 0.0,
            "memory_write_accuracy": float(write_accuracy),
            "stale_memory_misuse_rate": float(stale_used > 0),
            "explanation_faithfulness": float(selected_product is not None),
            "mean_turns": float(turns),
            "mean_tool_calls": float(tool_counter[0]),
            "mean_latency_ms": float(trace.latency_ms),
            "mean_token_usage": 0.0,
            **rec_metrics,
        }
        return {
            "task_id": task.task_id,
            "scenario": task.scenario,
            "task": task.to_dict(),
            "features": self.features.to_dict(),
            "trajectory": trace.steps,
            "final_product_ids": final_ids,
            "final_answer": explanation,
            "rejection_occurred": rejection_occurred,
            "accepted": bool(feedback.accepted),
            "metrics": metrics,
            "latency_ms": trace.latency_ms,
            "token_usage": {"input": 0, "output": 0},
            "estimated_cost_usd": 0.0,
            "memory_writes": task_writes,
            "error": None,
        }
