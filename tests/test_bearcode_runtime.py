from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace


BEARCODE_ROOT = Path(__file__).resolve().parents[1] / "upstream" / "bearcode"
sys.path.insert(0, str(BEARCODE_ROOT))


def _stub_missing_sdk(module_name):
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError:
        sys.modules[module_name] = types.ModuleType(module_name)


# The upstream SDKs are optional for these offline runtime tests.  The tests
# replace every model response and must never open a network connection.
_stub_missing_sdk("anthropic")
_stub_missing_sdk("openai")

from agents import agent as agent_module  # noqa: E402
from agents.agent import Agent  # noqa: E402
from agents.tools import execute_tool  # noqa: E402


def _tool_call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _model_response(tool_calls=None, content=None):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _offline_openai_agent(responses, executed):
    runtime = Agent.__new__(Agent)
    runtime._openai_messages = []
    runtime.is_sub_agent = True
    runtime._aborted = False
    runtime._context_cleared = False
    runtime.permission_mode = "bypassPermissions"
    runtime._plan_file_path = None
    runtime._confirmed_paths = set()
    runtime.total_input_tokens = 0
    runtime.total_output_tokens = 0
    runtime.last_input_token_count = 0
    runtime.last_api_call_time = 0
    runtime.current_turns = 0
    runtime.max_cost_usd = None
    runtime.max_turns = None
    runtime._last_tool_name = ""
    runtime._same_tool_repeat_count = 0
    runtime._tool_error_streak = 0

    pending = list(responses)

    async def fake_model_response():
        return pending.pop(0)

    async def fake_execute(name, inp):
        executed.append((name, dict(inp)))
        return "result for {0}".format(name)

    async def no_compaction():
        return None

    runtime._call_openai_stream = fake_model_response
    runtime._execute_tool_call = fake_execute
    runtime._run_compression_pipeline = lambda: None
    runtime._refresh_runtime_system_prompt = lambda: None
    runtime._check_and_compact = no_compaction
    return runtime


def _silence_runtime_ui(monkeypatch):
    monkeypatch.setattr(agent_module, "print_tool_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent_module, "print_tool_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent_module, "print_info", lambda *args, **kwargs: None)


def test_builtin_tool_runtime_smoke_is_offline(tmp_path):
    catalog = tmp_path / "catalog.txt"
    catalog.write_text("p1 red shoes\np2 blue coat\n", encoding="utf-8")
    read_state = {}

    read_result = asyncio.run(
        execute_tool("read_file", {"file_path": str(catalog)}, read_state)
    )
    grep_result = asyncio.run(
        execute_tool(
            "grep_search",
            {"pattern": "blue", "path": str(tmp_path), "include": "*.txt"},
            read_state,
        )
    )
    list_result = asyncio.run(
        execute_tool(
            "list_files", {"pattern": "*.txt", "path": str(tmp_path)}, read_state
        )
    )

    assert "p1 red shoes" in read_result
    assert "blue coat" in grep_result
    assert "catalog.txt" in list_result


def test_openai_stream_assembles_multiple_tool_calls_without_network():
    chunks = [
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-search",
                                function=SimpleNamespace(
                                    name="read_file", arguments='{"file_'
                                ),
                            )
                        ],
                    ),
                    finish_reason=None,
                )
            ],
        ),
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(
                                    name=None, arguments='path":"catalog.json"}'
                                ),
                            ),
                            SimpleNamespace(
                                index=1,
                                id="call-rank",
                                function=SimpleNamespace(
                                    name="grep_search", arguments='{"pattern":"red"}'
                                ),
                            ),
                        ],
                    ),
                    finish_reason=None,
                )
            ],
        ),
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=None),
                    finish_reason="tool_calls",
                )
            ],
        ),
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3), choices=[]
        ),
    ]

    class FakeStream:
        def __aiter__(self):
            self._chunks = iter(chunks)
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration:
                raise StopAsyncIteration

    class FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs["stream"] is True
            return FakeStream()

    runtime = Agent.__new__(Agent)
    runtime._openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    runtime.model = "offline-test-model"
    runtime.tools = []
    runtime._openai_messages = [{"role": "user", "content": "find products"}]

    response = asyncio.run(runtime._call_openai_stream())
    calls = response["choices"][0]["message"]["tool_calls"]

    assert [call["id"] for call in calls] == ["call-search", "call-rank"]
    assert calls[0]["function"]["arguments"] == '{"file_path":"catalog.json"}'
    assert response["usage"] == {"prompt_tokens": 7, "completion_tokens": 3}


def test_openai_multiple_tool_calls_execute_each_once(monkeypatch):
    _silence_runtime_ui(monkeypatch)
    executed = []
    first = _model_response(
        [
            _tool_call("call-search", "read_file", '{"file_path":"catalog.json"}'),
            _tool_call("call-rank", "grep_search", '{"pattern":"red"}'),
        ]
    )
    runtime = _offline_openai_agent([first, _model_response(content="done")], executed)

    asyncio.run(runtime._chat_openai("find a red product"))

    assert executed == [
        ("read_file", {"file_path": "catalog.json"}),
        ("grep_search", {"pattern": "red"}),
    ]
    tool_messages = [
        message for message in runtime._openai_messages if message.get("role") == "tool"
    ]
    assert [message["tool_call_id"] for message in tool_messages] == [
        "call-search",
        "call-rank",
    ]


def test_openai_denied_tool_call_gets_exactly_one_result(monkeypatch):
    _silence_runtime_ui(monkeypatch)

    def permission(name, inp, mode, plan_file_path):
        if name == "write_file":
            return {"action": "deny", "message": "offline policy"}
        return {"action": "allow"}

    monkeypatch.setattr(agent_module, "check_permission", permission)
    executed = []
    first = _model_response(
        [
            _tool_call("call-read", "read_file", '{"file_path":"catalog.json"}'),
            _tool_call(
                "call-denied",
                "write_file",
                '{"file_path":"out.txt","content":"no"}',
            ),
        ]
    )
    runtime = _offline_openai_agent([first, _model_response(content="done")], executed)
    runtime.permission_mode = "dontAsk"

    asyncio.run(runtime._chat_openai("write and read"))

    assert executed == [("read_file", {"file_path": "catalog.json"})]
    tool_messages = [
        message for message in runtime._openai_messages if message.get("role") == "tool"
    ]
    assert [message["tool_call_id"] for message in tool_messages] == [
        "call-read",
        "call-denied",
    ]
    assert tool_messages[1]["content"] == "Action denied: offline policy"
