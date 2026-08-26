import json
from types import SimpleNamespace

import pytest

from agentrec.llm.budget import (
    BudgetExceeded,
    CostLedger,
    MODEL_PRICING_USD_PER_MILLION,
    charged_or_reserved_usd,
)
from agentrec.llm.openai_responses import OpenAIResponsesPolicy
from agentrec.llm.security import redact_api_secrets


class _FakeResponses:
    def __init__(self):
        self.kwargs = []

    def create(self, **kwargs):
        self.kwargs.append(kwargs)
        return SimpleNamespace(
            id="resp_test",
            status="completed",
            output_text="",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call_1",
                    name="record_plan",
                    arguments='{"steps":["inspect","recommend"]}',
                )
            ],
            usage={
                "input_tokens": 1000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 200},
            },
        )


def test_provider_records_usage_cost_and_required_tool_call(tmp_path):
    ledger = CostLedger(tmp_path / "ledger.json", model="gpt-5.5", max_cost_usd=1.0)
    responses = _FakeResponses()
    policy = OpenAIResponsesPolicy(
        model="gpt-5.5",
        ledger=ledger,
        client=SimpleNamespace(responses=responses),
    )
    tools = [
        {
            "type": "function",
            "name": "record_plan",
            "description": "Record a plan.",
            "parameters": {
                "type": "object",
                "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
                "required": ["steps"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]
    result = policy.create_turn(
        instructions="Use the tool.",
        input_value="Start.",
        tools=tools,
        task_id="task_1",
        turn_index=1,
    )
    assert result.function_calls[0].name == "record_plan"
    assert result.function_calls[0].arguments["steps"] == ["inspect", "recommend"]
    assert result.token_usage == {"input": 1000, "cached_input": 200, "output": 100}
    assert result.estimated_cost_usd == pytest.approx(0.0071)
    assert responses.kwargs[0]["model"] == "gpt-5.5"
    assert responses.kwargs[0]["tool_choice"] == "required"
    assert responses.kwargs[0]["store"] is True
    assert "metadata" not in responses.kwargs[0]
    saved = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert saved["events"][0]["status"] == "settled"


def test_budget_blocks_before_request(tmp_path):
    ledger = CostLedger(tmp_path / "ledger.json", model="gpt-5.5", max_cost_usd=0.01)
    with pytest.raises(BudgetExceeded):
        ledger.reserve(estimated_input_tokens=1, max_output_tokens=1)


def test_provider_normalizes_multiple_calls_to_one_audited_action(tmp_path):
    responses = _FakeResponses()
    original_create = responses.create

    def create_with_extra_call(**kwargs):
        response = original_create(**kwargs)
        response.output.append(
            SimpleNamespace(
                type="function_call",
                call_id="call_2",
                name="inspect_catalog",
                arguments='{"query":"headphones","limit":10}',
            )
        )
        return response

    responses.create = create_with_extra_call
    ledger = CostLedger(tmp_path / "ledger.json", model="gpt-5.5", max_cost_usd=1.0)
    policy = OpenAIResponsesPolicy(
        model="gpt-5.5",
        ledger=ledger,
        client=SimpleNamespace(responses=responses),
    )
    result = policy.create_turn(
        instructions="Use one tool.",
        input_value="Start.",
        tools=[],
        task_id="task_1",
        turn_index=1,
    )
    assert [call.call_id for call in result.function_calls] == ["call_1"]
    assert [call.call_id for call in result.ignored_function_calls] == ["call_2"]
    assert not any(item.get("call_id") == "call_2" for item in result.output_items)


def test_gpt_5_5_pricing_is_pinned_to_official_rates():
    pricing = MODEL_PRICING_USD_PER_MILLION["gpt-5.5"]
    assert pricing["input"] == 5.0
    assert pricing["cached_input"] == 0.5
    assert pricing["output"] == 30.0
    assert pricing["source"] == "https://developers.openai.com/api/docs/models/gpt-5.5"


def test_prior_model_reservation_can_be_carried_into_new_model_cap(tmp_path):
    path = tmp_path / "gpt-5.6-terra_ledger.json"
    ledger = CostLedger(path, model="gpt-5.6-terra", max_cost_usd=10.0)
    reservation = ledger.reserve(estimated_input_tokens=10, max_output_tokens=10)
    ledger.fail(reservation, RuntimeError("authentication failed"))
    assert charged_or_reserved_usd(path) == 0.02


def test_gpt_5_5_long_context_multiplier_is_budgeted(tmp_path):
    ledger = CostLedger(tmp_path / "ledger.json", model="gpt-5.5", max_cost_usd=10.0)
    reservation = ledger.reserve(estimated_input_tokens=273000, max_output_tokens=100)
    actual = ledger.settle(
        reservation,
        input_tokens=273000,
        cached_input_tokens=0,
        output_tokens=100,
        response_id="resp_long",
    )
    assert actual == pytest.approx(2.7345)


def test_provider_client_uses_explicit_key_env_and_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTREC_API_KEY", "test-only-placeholder")
    pricing = dict(MODEL_PRICING_USD_PER_MILLION["gpt-5.5"])
    ledger = CostLedger(
        tmp_path / "ledger.json",
        model="gpt-5.5",
        max_cost_usd=1.0,
        pricing=pricing,
    )
    policy = OpenAIResponsesPolicy(
        model="gpt-5.5",
        ledger=ledger,
        api_key_env="AGENTREC_API_KEY",
        base_url="http://gateway.example.test/v1",
        allow_insecure_http=True,
    )
    assert policy.api_key_env == "AGENTREC_API_KEY"
    assert policy.base_url == "http://gateway.example.test/v1"
    assert str(policy.client.base_url) == "http://gateway.example.test/v1/"


def test_provider_rejects_plaintext_http_without_explicit_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTREC_API_KEY", "test-only-placeholder")
    ledger = CostLedger(tmp_path / "ledger.json", model="gpt-5.5", max_cost_usd=1.0)
    with pytest.raises(ValueError, match="plaintext HTTP"):
        OpenAIResponsesPolicy(
            model="gpt-5.5",
            ledger=ledger,
            api_key_env="AGENTREC_API_KEY",
            base_url="http://gateway.example.test/v1",
        )


def test_api_key_patterns_are_redacted():
    value = redact_api_secrets("Incorrect API key sk-Ab12********************************xyZ9")
    assert value == "Incorrect API key <redacted_api_key>"
