"""Thin, testable OpenAI Responses API policy wrapper."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

from agentrec.llm.budget import CostLedger


def _dump(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        result = value.model_dump(exclude_none=True)
        return dict(result) if isinstance(result, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    result = getattr(value, "__dict__", {})
    return {key: item for key, item in result.items() if not key.startswith("_")}


@dataclass(frozen=True)
class FunctionCall:
    call_id: str
    name: str
    arguments: Dict[str, Any]


@dataclass(frozen=True)
class OpenAIResponseTurn:
    response_id: str
    status: str
    output_text: str
    function_calls: List[FunctionCall]
    token_usage: Dict[str, int]
    estimated_cost_usd: float
    context_token_estimate: int
    output_items: List[Dict[str, Any]] = field(default_factory=list)
    ignored_function_calls: List[FunctionCall] = field(default_factory=list)


class OpenAIResponsesPolicy:
    def __init__(
        self,
        *,
        model: str,
        ledger: CostLedger,
        client: Any = None,
        reasoning_effort: str = "low",
        verbosity: str = "low",
        max_output_tokens: int = 500,
        api_key_env: str = "OPENAI_API_KEY",
        base_url: Optional[str] = None,
        allow_insecure_http: bool = False,
    ) -> None:
        self.model = str(model)
        self.ledger = ledger
        self.reasoning_effort = str(reasoning_effort)
        self.verbosity = str(verbosity)
        self.max_output_tokens = int(max_output_tokens)
        self.api_key_env = str(api_key_env)
        self.base_url = str(base_url).rstrip("/") if base_url else None
        if self.base_url:
            scheme = urlparse(self.base_url).scheme.lower()
            if scheme not in {"http", "https"}:
                raise ValueError("base_url must use http or https")
            if scheme == "http" and not allow_insecure_http:
                raise ValueError(
                    "refusing plaintext HTTP API transport without explicit acknowledgement"
                )
        if self.model != ledger.model:
            raise ValueError("policy and ledger model mismatch")
        if client is None:
            api_key = os.environ.get(self.api_key_env)
            if not api_key:
                raise RuntimeError("%s is not configured" % self.api_key_env)
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=self.base_url)
        self.client = client

    def create_turn(
        self,
        *,
        instructions: str,
        input_value: Any,
        tools: Sequence[Mapping[str, Any]],
        task_id: str,
        turn_index: int,
        previous_response_id: Optional[str] = None,
        prior_context_tokens: int = 0,
    ) -> OpenAIResponseTurn:
        serialized = json.dumps(
            {"instructions": instructions, "input": input_value, "tools": list(tools)},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        new_tokens = max(1, (len(serialized) + 2) // 3)
        estimated_input = max(new_tokens, int(prior_context_tokens) + new_tokens)
        reservation_id = self.ledger.reserve(
            estimated_input_tokens=estimated_input,
            max_output_tokens=self.max_output_tokens,
            metadata={"task_id": task_id, "turn_index": int(turn_index)},
        )
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_value,
            "tools": list(tools),
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "max_output_tokens": self.max_output_tokens,
            "reasoning": {"effort": self.reasoning_effort},
            "text": {"verbosity": self.verbosity},
            "store": True,
            "prompt_cache_key": "agentrec-controlled-tools-v1",
            "safety_identifier": hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:32],
        }
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        try:
            response = self.client.responses.create(**kwargs)
        except Exception as exc:
            self.ledger.fail(reservation_id, exc)
            raise
        usage = _dump(getattr(response, "usage", None))
        input_details = dict(usage.get("input_tokens_details") or {})
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cached_tokens = int(input_details.get("cached_tokens") or 0)
        response_id = str(getattr(response, "id", ""))
        cost = self.ledger.settle(
            reservation_id,
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            response_id=response_id,
        )
        raw_output = list(getattr(response, "output", None) or [])
        output_items = [_dump(item) for item in raw_output]
        calls: List[FunctionCall] = []
        for item in raw_output:
            if str(getattr(item, "type", "")) != "function_call":
                continue
            raw_arguments = getattr(item, "arguments", "{}") or "{}"
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
            except (TypeError, ValueError) as exc:
                raise ValueError("model returned invalid function arguments") from exc
            if not isinstance(arguments, dict):
                raise ValueError("function arguments must be a JSON object")
            calls.append(
                FunctionCall(
                    call_id=str(getattr(item, "call_id", "")),
                    name=str(getattr(item, "name", "")),
                    arguments=arguments,
                )
            )
        ignored_calls = calls[1:]
        selected_calls = calls[:1]
        if ignored_calls:
            selected_call_ids = {call.call_id for call in selected_calls}
            output_items = [
                item
                for item in output_items
                if item.get("type") != "function_call"
                or item.get("call_id") in selected_call_ids
            ]
        return OpenAIResponseTurn(
            response_id=response_id,
            status=str(getattr(response, "status", "unknown")),
            output_text=str(getattr(response, "output_text", "") or ""),
            function_calls=selected_calls,
            token_usage={
                "input": input_tokens,
                "cached_input": cached_tokens,
                "output": output_tokens,
            },
            estimated_cost_usd=cost,
            context_token_estimate=input_tokens + output_tokens,
            output_items=output_items,
            ignored_function_calls=ignored_calls,
        )
