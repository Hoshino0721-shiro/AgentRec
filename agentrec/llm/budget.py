"""Fail-closed persistent API budget ledger."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from agentrec.llm.security import redact_api_secrets


MODEL_PRICING_USD_PER_MILLION = {
    "gpt-5.5": {
        "input": 5.0,
        "cached_input": 0.5,
        "output": 30.0,
        "long_context_input_threshold": 272000,
        "long_context_input_multiplier": 2.0,
        "long_context_output_multiplier": 1.5,
        "source": "https://developers.openai.com/api/docs/models/gpt-5.5",
        "verified_date": "2026-08-25",
    },
    "gpt-5.6-terra": {
        "input": 2.0,
        "cached_input": 0.2,
        "output": 12.0,
        "long_context_input_threshold": 272000,
        "long_context_input_multiplier": 2.0,
        "long_context_output_multiplier": 1.5,
        "source": "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        "verified_date": "2026-08-25",
    }
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BudgetExceeded(RuntimeError):
    """Raised before an API request when the local hard cap cannot cover it."""


def charged_or_reserved_usd(path: Union[str, Path]) -> float:
    """Read another model ledger so a model migration cannot reset the overall cap."""

    ledger_path = Path(path)
    value = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise ValueError("invalid budget ledger: %s" % ledger_path)
    total = 0.0
    for event in value["events"]:
        if not isinstance(event, dict):
            raise ValueError("invalid budget event: %s" % ledger_path)
        if event.get("status") == "settled":
            total += float(event.get("actual_cost_usd", 0.0))
        elif event.get("status") in {"pending", "failed_reserved"}:
            total += float(event.get("reserved_cost_usd", 0.0))
    return round(total, 8)


class CostLedger:
    def __init__(
        self,
        path: Union[str, Path],
        *,
        model: str,
        max_cost_usd: float,
        pricing: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.path = Path(path)
        self.model = str(model)
        self.max_cost_usd = float(max_cost_usd)
        if self.max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be greater than zero")
        selected = dict(pricing or MODEL_PRICING_USD_PER_MILLION.get(self.model) or {})
        if not all(name in selected for name in ("input", "cached_input", "output")):
            raise ValueError("no verified pricing configured for model %s" % self.model)
        self.pricing = selected
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(
                {
                    "schema_version": 1,
                    "model": self.model,
                    "max_cost_usd": self.max_cost_usd,
                    "pricing_usd_per_million_tokens": self.pricing,
                    "created_at": _utc_now(),
                    "updated_at": _utc_now(),
                    "events": [],
                }
            )
        self._validate(self._read())

    def _read(self) -> Dict[str, Any]:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("budget ledger must be a JSON object")
        return value

    def _write(self, value: Mapping[str, Any]) -> None:
        payload = dict(value)
        payload["updated_at"] = _utc_now()
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        last_error: Optional[BaseException] = None
        for retry in range(12):
            try:
                temporary.replace(self.path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.05 * (retry + 1))
        if last_error is not None:
            raise last_error

    def _validate(self, value: Mapping[str, Any]) -> None:
        if value.get("model") != self.model:
            raise ValueError("budget ledger model mismatch")
        if abs(float(value.get("max_cost_usd", 0.0)) - self.max_cost_usd) > 1e-9:
            raise ValueError("budget ledger cap mismatch")

    @staticmethod
    def _charged(event: Mapping[str, Any]) -> float:
        status = event.get("status")
        if status == "settled":
            return float(event.get("actual_cost_usd", 0.0))
        if status in {"pending", "failed_reserved"}:
            return float(event.get("reserved_cost_usd", 0.0))
        return 0.0

    def _rates(self, input_tokens: int) -> Dict[str, float]:
        rates = {
            "input": float(self.pricing["input"]),
            "cached_input": float(self.pricing["cached_input"]),
            "output": float(self.pricing["output"]),
        }
        threshold = int(self.pricing.get("long_context_input_threshold") or 0)
        if threshold and int(input_tokens) > threshold:
            input_multiplier = float(self.pricing.get("long_context_input_multiplier") or 1.0)
            output_multiplier = float(self.pricing.get("long_context_output_multiplier") or 1.0)
            rates["input"] *= input_multiplier
            rates["cached_input"] *= input_multiplier
            rates["output"] *= output_multiplier
        return rates

    def snapshot(self) -> Dict[str, Any]:
        value = self._read()
        self._validate(value)
        charged = sum(self._charged(event) for event in value.get("events") or [])
        settled = sum(
            float(event.get("actual_cost_usd", 0.0))
            for event in value.get("events") or []
            if event.get("status") == "settled"
        )
        return {
            "model": self.model,
            "max_cost_usd": self.max_cost_usd,
            "charged_or_reserved_usd": round(charged, 8),
            "settled_cost_usd": round(settled, 8),
            "remaining_usd": round(max(0.0, self.max_cost_usd - charged), 8),
            "event_count": len(value.get("events") or []),
        }

    def reserve(
        self,
        *,
        estimated_input_tokens: int,
        max_output_tokens: int,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> str:
        safe_input = max(0, int(estimated_input_tokens))
        rates = self._rates(safe_input)
        estimated = (
            safe_input * rates["input"] / 1_000_000.0
            + max(0, int(max_output_tokens)) * rates["output"] / 1_000_000.0
        )
        reservation = max(0.02, estimated * 1.25 + 0.002)
        value = self._read()
        self._validate(value)
        charged = sum(self._charged(event) for event in value.get("events") or [])
        if charged + reservation > self.max_cost_usd + 1e-12:
            raise BudgetExceeded(
                "local API cost cap reached: charged/reserved %.6f + next reservation %.6f > %.6f"
                % (charged, reservation, self.max_cost_usd)
            )
        reservation_id = uuid.uuid4().hex
        value.setdefault("events", []).append(
            {
                "reservation_id": reservation_id,
                "status": "pending",
                "created_at": _utc_now(),
                "reserved_cost_usd": round(reservation, 8),
                "estimated_input_tokens": int(estimated_input_tokens),
                "max_output_tokens": int(max_output_tokens),
                "metadata": dict(metadata or {}),
            }
        )
        self._write(value)
        return reservation_id

    def settle(
        self,
        reservation_id: str,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        response_id: str,
    ) -> float:
        cached = max(0, min(int(cached_input_tokens), int(input_tokens)))
        uncached = max(0, int(input_tokens) - cached)
        rates = self._rates(int(input_tokens))
        actual = (
            uncached * rates["input"] / 1_000_000.0
            + cached * rates["cached_input"] / 1_000_000.0
            + max(0, int(output_tokens)) * rates["output"] / 1_000_000.0
        )
        value = self._read()
        event = self._event(value, reservation_id)
        if event.get("status") != "pending":
            raise ValueError("reservation is not pending")
        event.update(
            {
                "status": "settled",
                "settled_at": _utc_now(),
                "response_id": str(response_id),
                "input_tokens": int(input_tokens),
                "cached_input_tokens": cached,
                "output_tokens": int(output_tokens),
                "actual_cost_usd": round(actual, 8),
            }
        )
        self._write(value)
        return round(actual, 8)

    def fail(self, reservation_id: str, error: BaseException) -> None:
        value = self._read()
        event = self._event(value, reservation_id)
        if event.get("status") == "pending":
            event.update(
                {
                    "status": "failed_reserved",
                    "failed_at": _utc_now(),
                    "error": "%s: %s" % (type(error).__name__, redact_api_secrets(error)),
                }
            )
            self._write(value)

    @staticmethod
    def _event(value: Mapping[str, Any], reservation_id: str) -> Dict[str, Any]:
        for event in value.get("events") or []:
            if event.get("reservation_id") == reservation_id:
                return event
        raise KeyError("unknown reservation: %s" % reservation_id)
