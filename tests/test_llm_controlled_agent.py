from agentrec.llm.controlled_agent import LLMControlledShoppingAgent
from agentrec.llm.openai_responses import FunctionCall, OpenAIResponseTurn
from agentrec.simulation.scenarios import build_tasks
from agentrec.tools.catalog import CatalogTool, load_catalog


class _SequencePolicy:
    model = "codex.gpt-5.5"

    def __init__(self, target_id, candidate_ids):
        self.target_id = target_id
        self.inputs = []
        self.previous_response_ids = []
        self.calls = [
            ("record_plan", {"steps": ["retrieve memory", "inspect", "evaluate", "recommend"]}),
            ("retrieve_memory", {"subject": "self"}),
            ("inspect_catalog", {"query": "shopping request", "limit": 30}),
            ("evaluate_slate", {"product_ids": list(candidate_ids), "phase": "initial"}),
            ("recommend", {"product_ids": [target_id], "attempt": 1}),
            ("finish", {"product_ids": [target_id], "explanation": "Selected from grounded catalog evidence."}),
        ]

    def create_turn(self, **kwargs):
        self.inputs.append(kwargs["input_value"])
        self.previous_response_ids.append(kwargs.get("previous_response_id"))
        name, arguments = self.calls[len(self.inputs) - 1]
        return OpenAIResponseTurn(
            response_id="resp_%d" % len(self.inputs),
            status="completed",
            output_text="",
            function_calls=[FunctionCall("call_%d" % len(self.inputs), name, arguments)],
            token_usage={"input": 10, "cached_input": 0, "output": 2},
            estimated_cost_usd=0.001,
            context_token_estimate=12 * len(self.inputs),
        )


def test_llm_agent_executes_tool_loop_without_exposing_hidden_target():
    task = build_tasks(1, seed=42, scenarios=["clear_single_turn"])[0]
    catalog = CatalogTool(load_catalog())
    candidate_ids = [item.product_id for item in catalog.search(task.request, limit=30)]
    policy = _SequencePolicy(task.target_product_id, candidate_ids)
    agent = LLMControlledShoppingAgent(
        catalog=catalog,
        policy=policy,
        max_tool_calls=12,
        max_model_turns=12,
    )
    row = agent.run_task(task)
    assert row["accepted"] is True
    assert row["final_product_ids"][0] == task.target_product_id
    assert row["token_usage"] == {"input": 60, "cached_input": 0, "output": 12}
    assert row["estimated_cost_usd"] == 0.006
    actions = [step["selected_action"] for step in row["trajectory"]]
    assert "plan" in actions
    assert "retrieve_preferences" in actions
    assert "search_products" in actions
    assert "evaluate_slate" in actions
    assert "recommend" in actions
    assert actions[-1] == "finish"
    first_input = policy.inputs[0]
    assert task.target_product_id not in first_input
    assert "acceptance" not in first_input
    assert all(value is None for value in policy.previous_response_ids)
    second_input = policy.inputs[1]
    assert any(
        item.get("type") == "function_call" and item.get("call_id") == "call_1"
        for item in second_input
    )
    assert any(
        item.get("type") == "function_call_output" and item.get("call_id") == "call_1"
        for item in second_input
    )
