"""GPT-5.5-driven tool loop over the controlled shopping environment."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from agentrec.agent.orchestrator import ShoppingAgent, _constraint, _preference, _subject, _task_time
from agentrec.agent.reflection import reflect_on_feedback
from agentrec.agent.trace import TrajectoryRecorder, jsonable
from agentrec.domain.models import Constraint, Preference, Product, Task
from agentrec.experiments.metrics import recommendation_metrics
from agentrec.llm.openai_responses import FunctionCall, OpenAIResponsesPolicy
from agentrec.simulation.user_simulator import UserSimulator
from agentrec.tools.catalog import CatalogTool


def _tool(
    name: str,
    description: str,
    properties: Mapping[str, Any],
    required: Sequence[str],
) -> Dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": dict(properties),
            "required": list(required),
            "additionalProperties": False,
        },
        "strict": True,
    }


CONTROLLED_TOOLS = [
    _tool(
        "record_plan",
        "Record an outcome-oriented plan before using shopping tools.",
        {"steps": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 8}},
        ["steps"],
    ),
    _tool(
        "retrieve_memory",
        "Retrieve active, recipient-scoped preference evidence. Use once before catalog ranking.",
        {"subject": {"type": "string"}},
        ["subject"],
    ),
    _tool(
        "ask_clarifying_question",
        "Ask one focused question when budget, hard constraints, or recipient preferences are missing.",
        {"question": {"type": "string"}},
        ["question"],
    ),
    _tool(
        "inspect_catalog",
        "Search the local catalog. This is retrieval only and does not enforce hard constraints.",
        {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        ["query", "limit"],
    ),
    _tool(
        "evaluate_slate",
        "Apply current hard constraints, rank by visible preferences, and return grounded comparisons.",
        {
            "product_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 30},
            "phase": {"type": "string", "enum": ["initial", "recovery"]},
        },
        ["product_ids", "phase"],
    ),
    _tool(
        "recommend",
        "Recommend the evaluated ranked slate to the user and receive acceptance/rejection feedback.",
        {
            "product_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
            "attempt": {"type": "integer", "minimum": 1, "maximum": 2},
        },
        ["product_ids", "attempt"],
    ),
    _tool(
        "reflect_and_replan",
        "After rejection, state the cause and revised search intent before a recovery slate.",
        {"analysis": {"type": "string"}, "revised_query": {"type": "string"}},
        ["analysis", "revised_query"],
    ),
    _tool(
        "finish",
        "Finish only after a recommendation. Product IDs must match the last recommended slate.",
        {
            "product_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
            "explanation": {"type": "string"},
        },
        ["product_ids", "explanation"],
    ),
]


INSTRUCTIONS = """You are the planning policy for an auditable shopping agent.
The user request, current recipient, and visible state are supplied separately. Hidden evaluator
targets are never available. Use only the provided local tools and their results.

Operating contract:
1. Your first function call must be record_plan.
2. Retrieve recipient-scoped memory before ranking. Ask one concise clarification only when the
   visible request lacks decision-critical information.
3. Search with inspect_catalog, then pass only returned IDs to evaluate_slate. Hard constraints
   are enforced by evaluate_slate and must never be relaxed for preference scoring.
4. Recommend only IDs returned by the latest evaluate_slate, preserving its ranking.
5. If rejected, call reflect_and_replan before a recovery search. Make at most two recommendations.
6. Call finish after acceptance or after the permitted recovery attempt. Do not invent products,
   prices, reviews, preferences, tool results, or acceptance labels.
Keep plans, questions, and explanations concise."""


class LLMControlledShoppingAgent(ShoppingAgent):
    def __init__(
        self,
        *,
        catalog: CatalogTool,
        policy: OpenAIResponsesPolicy,
        seed: int = 42,
        max_turns: int = 8,
        max_tool_calls: int = 12,
        max_model_turns: int = 12,
    ) -> None:
        super().__init__(
            system="full_agent",
            catalog=catalog,
            seed=seed,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
        )
        self.policy = policy
        self.max_model_turns = int(max_model_turns)
        self.last_trace: List[Dict[str, Any]] = []
        self.last_token_usage: Dict[str, int] = {"input": 0, "cached_input": 0, "output": 0}
        self.last_estimated_cost_usd = 0.0

    @staticmethod
    def _product_summary(product: Product) -> Dict[str, Any]:
        return {
            "product_id": product.product_id,
            "name": product.name,
            "category": product.category,
            "brand": product.brand,
            "price": product.price,
            "currency": product.currency,
            "rating": product.rating,
            "review_count": product.review_count,
            "attributes": product.attributes,
            "tags": product.tags,
        }

    def run_task(self, task: Task) -> Dict[str, Any]:
        trace = TrajectoryRecorder()
        self.last_trace = trace.steps
        simulator = UserSimulator(task)
        now = _task_time(task)
        request = simulator.initial_request()
        constraints, preferences = self._visible_state(task)
        memory_hits: List[Any] = []
        memory_writes: List[Dict[str, Any]] = []
        seeded = self._seed_memory(task, now)
        memory_writes.extend(seeded)
        if seeded:
            trace.add(
                "update_memory",
                arguments={"source": "pre_task_history"},
                memory_writes=seeded,
                reason="load frozen historical evidence before the LLM policy starts",
            )

        visible_input = {
            "request": request,
            "recipient": task.recipient,
            "visible_constraints": [value.to_dict() for value in constraints],
            "visible_preferences": [value.to_dict() for value in preferences],
            "capabilities": self.features.to_dict(),
            "budgets": {
                "max_user_turns": self.max_turns,
                "max_tool_calls": self.max_tool_calls,
                "max_recommendations": 2,
            },
        }
        trace.add(
            "observe_request",
            observation=visible_input,
            reason="provide only observable task state to the LLM policy",
        )

        initial_input = json.dumps(visible_input, ensure_ascii=False, sort_keys=True)
        input_value: Any = initial_input
        conversation_items: List[Dict[str, Any]] = [
            {"role": "user", "content": initial_input}
        ]
        total_usage = {"input": 0, "cached_input": 0, "output": 0}
        total_cost = 0.0
        tool_calls = 0
        user_turns = 1
        plan_recorded = False
        memory_retrieved = False
        clarification_called = False
        candidate_pool: List[str] = []
        evaluated_ids: List[str] = []
        excluded_ids: List[str] = []
        recommendation_attempts = 0
        last_recommendation: List[str] = []
        last_feedback = None
        rejection_occurred = False
        reflected_after_rejection = False
        useful_clarification: Optional[float] = None
        final_ids: List[str] = []
        final_answer = ""
        finished = False
        invalid_tool_calls = 0

        for model_turn in range(1, self.max_model_turns + 1):
            turn = self.policy.create_turn(
                instructions=INSTRUCTIONS,
                input_value=input_value,
                tools=CONTROLLED_TOOLS,
                task_id=task.task_id,
                turn_index=model_turn,
            )
            for name in total_usage:
                total_usage[name] += int(turn.token_usage.get(name, 0))
            total_cost += float(turn.estimated_cost_usd)
            self.last_token_usage = dict(total_usage)
            self.last_estimated_cost_usd = round(total_cost, 8)
            trace.add(
                "llm_decide",
                observation={"output_text": turn.output_text, "status": turn.status},
                tool_result={
                    "response_id": turn.response_id,
                    "function_calls": [
                        {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
                        for call in turn.function_calls
                    ],
                    "ignored_function_calls": [
                        {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
                        for call in turn.ignored_function_calls
                    ],
                },
                reason="select the next Agent action through the Responses API",
                token_usage=turn.token_usage,
                estimated_cost_usd=turn.estimated_cost_usd,
            )
            if len(turn.function_calls) != 1:
                raise RuntimeError(
                    "LLM policy must return exactly one function call; got %d" % len(turn.function_calls)
                )
            invalid_tool_calls += len(turn.ignored_function_calls)
            call = turn.function_calls[0]
            response_items = list(turn.output_items)
            if not any(
                item.get("type") == "function_call" and item.get("call_id") == call.call_id
                for item in response_items
            ):
                response_items.append(
                    {
                        "type": "function_call",
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False, sort_keys=True),
                    }
                )
            conversation_items.extend(response_items)
            tool_calls += 1
            if tool_calls > self.max_tool_calls:
                raise RuntimeError("LLM tool-call budget exceeded")
            if tool_calls == 1 and call.name != "record_plan":
                raise RuntimeError("LLM policy violated first-action planning contract")

            result: Dict[str, Any]
            if call.name == "record_plan":
                if plan_recorded:
                    invalid_tool_calls += 1
                    result = {"ok": False, "error": "plan already recorded"}
                else:
                    steps = [str(value) for value in call.arguments.get("steps") or []]
                    if len(steps) < 2:
                        raise RuntimeError("record_plan requires at least two steps")
                    plan_recorded = True
                    result = {"ok": True, "steps": steps}
                    trace.add(
                        "plan",
                        arguments=call.arguments,
                        tool_result=result,
                        reason="persist the LLM's outcome-oriented plan",
                    )
            elif call.name == "retrieve_memory":
                if memory_retrieved:
                    invalid_tool_calls += 1
                    result = {"ok": False, "error": "memory already retrieved"}
                else:
                    memory_retrieved = True
                    memory_hits, remembered_constraints, remembered_preferences = self._retrieve_memory(task, now)
                    constraints.extend(remembered_constraints)
                    preferences.extend(remembered_preferences)
                    result = {
                        "ok": True,
                        "constraints": [value.to_dict() for value in remembered_constraints],
                        "preferences": [value.to_dict() for value in remembered_preferences],
                    }
                    trace.add(
                        "retrieve_preferences",
                        arguments={"subject": _subject(task.recipient)},
                        memory_reads=[hit.to_dict() for hit in memory_hits],
                        tool_result=result,
                        reason="retrieve active recipient-scoped evidence",
                    )
            elif call.name == "ask_clarifying_question":
                if clarification_called or recommendation_attempts:
                    invalid_tool_calls += 1
                    result = {"ok": False, "error": "clarification unavailable at this stage"}
                else:
                    clarification_called = True
                    response = simulator.clarify(str(call.arguments.get("question") or ""))
                    new_constraints, new_preferences = self._clarification_values(response)
                    constraints.extend(new_constraints)
                    preferences.extend(new_preferences)
                    useful_clarification = float(bool(new_constraints or new_preferences))
                    user_turns += 1
                    writes = self._write_constraints(
                        task, new_constraints, event_prefix="clarification", now=now
                    ) + self._write_preferences(
                        task, new_preferences, event_prefix="clarification", now=now
                    )
                    memory_writes.extend(writes)
                    result = dict(response)
                    result["ok"] = True
                    trace.add(
                        "ask_clarifying_question",
                        arguments=call.arguments,
                        tool_result=result,
                        memory_writes=writes,
                        reason="resolve missing decision-critical state",
                    )
            elif call.name == "inspect_catalog":
                query = str(call.arguments.get("query") or request)
                limit = max(1, min(30, int(call.arguments.get("limit") or 20)))
                products = self.catalog.search(query=query, limit=limit)
                candidate_pool = [item.product_id for item in products if item.product_id not in excluded_ids]
                result = {
                    "ok": True,
                    "query": query,
                    "products": [self._product_summary(item) for item in products if item.product_id in candidate_pool],
                }
                trace.add(
                    "search_products",
                    arguments={"query": query, "limit": limit},
                    tool_result=result,
                    reason="retrieve a local catalog pool without hidden evaluator state",
                )
            elif call.name == "evaluate_slate":
                requested = [str(value) for value in call.arguments.get("product_ids") or []]
                if not requested or not set(requested).issubset(set(candidate_pool)):
                    invalid_tool_calls += 1
                    result = {"ok": False, "error": "product_ids must come from latest inspect_catalog"}
                else:
                    available = [item_id for item_id in requested if item_id not in excluded_ids]
                    filtered = self.catalog.filter_constraints(available, constraints)
                    ranked = self.catalog.rank(filtered, preferences=preferences, query=request, limit=5)
                    evaluated_ids = [item.product_id for item in ranked]
                    comparison = self.catalog.compare(evaluated_ids[:3]) if evaluated_ids else {"products": []}
                    review = self.catalog.review_summary(evaluated_ids[0]) if evaluated_ids else None
                    result = {
                        "ok": True,
                        "ranked_ids": evaluated_ids,
                        "products": [self._product_summary(item) for item in ranked],
                        "comparison": comparison,
                        "top_review_summary": review,
                    }
                    trace.add(
                        "evaluate_slate",
                        arguments=call.arguments,
                        tool_result=result,
                        constraint_check={"input": len(available), "passed": len(filtered)},
                        reason="enforce hard constraints before preference ranking and comparison",
                    )
            elif call.name == "recommend":
                requested = [str(value) for value in call.arguments.get("product_ids") or []]
                if (
                    not requested
                    or requested != evaluated_ids[: len(requested)]
                    or recommendation_attempts >= 2
                    or (recommendation_attempts == 1 and rejection_occurred and not reflected_after_rejection)
                ):
                    invalid_tool_calls += 1
                    result = {"ok": False, "error": "recommendation must preserve the latest evaluated ranking and protocol"}
                else:
                    recommendation_attempts += 1
                    last_recommendation = requested
                    last_feedback = simulator.evaluate(requested, attempt=recommendation_attempts)
                    user_turns += 1
                    if not last_feedback.accepted:
                        rejection_occurred = True
                    writes = self._write_constraints(
                        task,
                        list(last_feedback.new_constraints),
                        event_prefix="feedback:%d" % recommendation_attempts,
                        now=now,
                    ) + self._write_preferences(
                        task,
                        list(last_feedback.new_preferences),
                        event_prefix="feedback:%d" % recommendation_attempts,
                        now=now,
                    )
                    memory_writes.extend(writes)
                    result = {"ok": True, "feedback": last_feedback.to_dict()}
                    trace.add(
                        "recommend",
                        arguments={"product_ids": requested, "attempt": recommendation_attempts},
                        tool_result=result,
                        memory_writes=writes,
                        reason="present the grounded slate and observe controlled feedback",
                    )
            elif call.name == "reflect_and_replan":
                if last_feedback is None or last_feedback.accepted or reflected_after_rejection:
                    invalid_tool_calls += 1
                    result = {"ok": False, "error": "reflection requires one unresolved rejection"}
                else:
                    reflected_after_rejection = True
                    reflection = reflect_on_feedback(last_feedback, last_recommendation)
                    constraints.extend(_constraint(value) for value in reflection.constraints)
                    preferences.extend(_preference(value) for value in reflection.preferences)
                    excluded_ids.extend(reflection.rejected_product_ids)
                    result = {
                        "ok": True,
                        "analysis": str(call.arguments.get("analysis") or ""),
                        "revised_query": str(call.arguments.get("revised_query") or request),
                        "constraints": list(reflection.constraints),
                        "preferences": list(reflection.preferences),
                        "excluded_product_ids": list(reflection.rejected_product_ids),
                    }
                    trace.add(
                        "reflect_and_replan",
                        arguments=call.arguments,
                        tool_result=result,
                        reason="translate rejection into revised observable state",
                    )
            elif call.name == "finish":
                requested = [str(value) for value in call.arguments.get("product_ids") or []]
                explanation = str(call.arguments.get("explanation") or "").strip()
                if not last_recommendation or requested != last_recommendation or not explanation:
                    invalid_tool_calls += 1
                    result = {"ok": False, "error": "finish must match the latest recommendation and include an explanation"}
                else:
                    final_ids = list(last_recommendation)
                    final_answer = explanation
                    finished = True
                    result = {"ok": True, "final_product_ids": final_ids}
                    trace.add(
                        "finish",
                        arguments=call.arguments,
                        tool_result=result,
                        reason="terminate after the auditable recommendation loop",
                    )
            else:
                invalid_tool_calls += 1
                result = {"ok": False, "error": "unknown function: %s" % call.name}

            conversation_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(jsonable(result), ensure_ascii=False, sort_keys=True),
                }
            )
            input_value = list(conversation_items)
            if finished:
                break

        if not finished:
            raise RuntimeError("LLM policy did not call finish within the model-turn budget")

        selected_id = final_ids[0] if final_ids else None
        selected_product = self.catalog.get_product(selected_id) if selected_id else None
        satisfies = bool(
            selected_product is not None
            and self.catalog.filter_constraints([selected_product], task.hard_constraints)
        )
        task_writes = [
            value
            for value in memory_writes
            if any(str(event).startswith(task.task_id + ":") for event in value.get("evidence_event_ids", []))
        ]
        recipient_origin = [
            value
            for value in task_writes
            if str(value.get("origin_subject") or value.get("subject", "")).startswith("recipient:")
        ]
        contaminated = [
            value
            for value in recipient_origin
            if value.get("subject") == "self" and value.get("layer") == "stable"
        ]
        contamination_rate = len(contaminated) / len(recipient_origin) if recipient_origin else 0.0
        stale_used = 0
        for hit in memory_hits:
            expires = hit.entry.expires_at
            if expires and datetime.fromisoformat(expires.replace("Z", "+00:00")) < now:
                stale_used += 1
        rec_metrics = recommendation_metrics(final_ids, task.acceptance.relevant_product_ids)
        accepted = bool(last_feedback and last_feedback.accepted)
        metrics: Dict[str, Optional[float]] = {
            "task_success_rate": float(accepted),
            "hard_constraint_satisfaction_rate": float(satisfies),
            "profile_contamination_rate": float(contamination_rate),
            "recovery_success_rate": float(accepted) if rejection_occurred else None,
            "useful_clarification_rate": useful_clarification,
            "redundant_tool_call_rate": float(invalid_tool_calls / max(1, tool_calls)),
            "memory_write_accuracy": float(
                sum(1 for value in task_writes if value not in contaminated) / len(task_writes)
                if task_writes
                else 1.0
            ),
            "stale_memory_misuse_rate": float(stale_used > 0),
            "explanation_faithfulness": float(selected_product is not None),
            "mean_turns": float(user_turns),
            "mean_tool_calls": float(tool_calls),
            "mean_latency_ms": float(trace.latency_ms),
            "mean_token_usage": float(total_usage["input"] + total_usage["output"]),
            **rec_metrics,
        }
        return {
            "task_id": task.task_id,
            "scenario": task.scenario,
            "task": task.to_dict(),
            "system": "llm_full_agent",
            "model": self.policy.model,
            "features": self.features.to_dict(),
            "trajectory": trace.steps,
            "final_product_ids": final_ids,
            "final_answer": final_answer,
            "rejection_occurred": rejection_occurred,
            "accepted": accepted,
            "metrics": metrics,
            "latency_ms": trace.latency_ms,
            "token_usage": total_usage,
            "estimated_cost_usd": round(total_cost, 8),
            "memory_writes": task_writes,
            "error": None,
        }
