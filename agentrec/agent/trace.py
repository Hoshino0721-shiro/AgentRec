"""Structured, JSON-safe trajectory recording."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "to_dict"):
        return jsonable(value.to_dict())
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return str(value)


@dataclass
class TrajectoryRecorder:
    steps: List[Dict[str, Any]] = field(default_factory=list)
    _started: float = field(default_factory=time.perf_counter)

    def add(
        self,
        action: str,
        *,
        observation: Any = None,
        arguments: Any = None,
        tool_result: Any = None,
        reason: str = "",
        memory_reads: Any = None,
        memory_writes: Any = None,
        constraint_check: Any = None,
        token_usage: Any = None,
        estimated_cost_usd: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        self.steps.append(
            {
                "step": len(self.steps) + 1,
                "latency_ms": round((time.perf_counter() - self._started) * 1000.0, 3),
                "observation": jsonable(observation),
                "selected_action": action,
                "reason": reason,
                "action_arguments": jsonable(arguments),
                "tool_result": jsonable(tool_result),
                "memory_reads": jsonable(memory_reads or []),
                "memory_writes": jsonable(memory_writes or []),
                "constraint_check": jsonable(constraint_check),
                "token_usage": jsonable(token_usage or {"input": 0, "output": 0}),
                "estimated_cost_usd": float(estimated_cost_usd),
                "error": error,
            }
        )

    @property
    def latency_ms(self) -> float:
        return round((time.perf_counter() - self._started) * 1000.0, 3)
