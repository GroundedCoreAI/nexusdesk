import asyncio
import importlib
import json
from uuid import UUID

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent_platform.core_platform.agent_execution.contracts.config import EngineIdentity
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway

pytestmark = pytest.mark.asyncio

AGENT_ID = UUID("60000000-0000-4000-8000-000000000006")


def _instructions_contract():
    return importlib.import_module(
        "agent_platform.core_platform.agent_execution.contracts.instructions"
    )


def _react_instruction_provider():
    return importlib.import_module(
        "agent_platform.core_platform.agent_execution.instructions.react_provider"
    ).ReactInstructionProvider()


def _engine_identity():
    return EngineIdentity(engine_id="react", protocol_id="native", adapter_version="v1")


def spec(name="lookup"):
    return HttpTool(
        name=name,
        description="Query demo",
        url="https://business.test/orders",
        parameters={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    )


def call(value="A", name="lookup", call_id="call_1"):
    return AIMessage(
        content="", tool_calls=[{"id": call_id, "name": name, "args": {"order_id": value}}]
    )


class SequenceModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    async def ainvoke(self, messages):
        self.seen.append(messages)
        return self.responses.pop(0)


async def ignore_event(kind, data):
    pass


async def test_reasoning_survives_history_without_becoming_visible_output():
    model = SequenceModel(
        AIMessage(content="first answer", additional_kwargs={"reasoning_content": "first trace"}),
        AIMessage(content="second answer", additional_kwargs={"reasoning_content": "second trace"}),
    )
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    async with httpx.AsyncClient() as client:
        engine = RuntimeEngine(model, ToolGateway(client, []), Settings())
        first, history, dropped = await engine.run("first question", [], emit)
        assert first == "first answer" and history[-1]["reasoning_content"] == "first trace"
        assert dropped == []
        second, history, _ = await engine.run("second question", history, emit)
    assert model.seen[1][2].additional_kwargs["reasoning_content"] == "first trace"
    assert second == "second answer" and history[-1]["reasoning_content"] == "second trace"
    assert "first trace" not in json.dumps(events) and "second trace" not in json.dumps(events)


async def test_model_tool_observe_reply_and_history():
    requests = []

    async def http(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "shipped"})

    model = SequenceModel(call(), AIMessage(content="订单已发货"))
    events = []

    async def emit(kind, data):
        events.append(kind)

    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        engine = RuntimeEngine(model, ToolGateway(client, [spec()]), Settings())
        answer, history, _ = await engine.run("查订单", [], emit)
    assert answer == "订单已发货"
    assert history[-1] == {"role": "assistant", "content": answer}
    assert requests[0].url.params["order_id"] == "A"
    assert isinstance(model.seen[1][-1], ToolMessage)
    assert json.loads(model.seen[1][-1].content)["data"]["status"] == "shipped"
    assert events == [
        "model.started",
        "model.completed",
        "tool.started",
        "tool.completed",
        "model.started",
        "model.completed",
    ]


async def test_independent_tools_are_parallel_with_bounded_gateway():
    both_started = asyncio.Event()
    active = 0

    async def http(request):
        nonlocal active
        active += 1
        if active == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=2)
        return httpx.Response(200, json={"ok": True})

    reply = call()
    reply.tool_calls.append({"id": "call_2", "name": "lookup", "args": {"order_id": "B"}})
    model = SequenceModel(reply, AIMessage(content="done"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        engine = RuntimeEngine(model, ToolGateway(client, [spec()], concurrency=2), Settings())
        await engine.run("parallel", [], ignore_event)
    assert active == 2


@pytest.mark.parametrize(
    "args,expected",
    [
        ({"order_id": "A", "url": "http://other"}, "invalid_arguments"),
        ({}, "invalid_arguments"),
        ({"order_id": 1}, "invalid_arguments"),
    ],
)
async def test_invalid_parameters_never_reach_http(args, expected):
    async def http(request):
        pytest.fail("invalid tool arguments reached HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        gateway = ToolGateway(client, [spec()])
        assert (await gateway.execute("lookup", args))["error"] == expected
        assert (await gateway.execute("unknown", {}))["error"] == "tool_not_allowed"


@pytest.mark.parametrize(
    "status,body,error",
    [
        (302, b"", "upstream_http_error"),
        (500, b"secret server details", "upstream_http_error"),
        (200, b"not json", "invalid_json_response"),
        (200, b"x" * 200, "response_too_large"),
    ],
)
async def test_http_failures_are_sanitized(status, body, error):
    async def http(request):
        return httpx.Response(status, content=body, headers={"location": "https://other.test"})

    tool = spec().model_copy(update={"max_response_bytes": 128})
    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        result = await ToolGateway(client, [tool]).execute("lookup", {"order_id": "A"})
    assert result["error"] == error
    assert "secret" not in str(result)


async def test_tool_timeout_and_cancellation():
    async def http(request):
        await asyncio.sleep(10)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        short = spec().model_copy(update={"timeout_seconds": 0.02})
        assert (await ToolGateway(client, [short]).execute("lookup", {"order_id": "A"}))[
            "error"
        ] == "tool_timeout"
        task = asyncio.create_task(
            ToolGateway(client, [spec()]).execute("lookup", {"order_id": "A"})
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.parametrize(
    "settings,replies,error",
    [
        ({"max_model_rounds": 1}, [call()], "model_round_limit"),
        ({}, [call(), call()], "repeated_tool_call"),
        ({}, [AIMessage(content="")], "empty_model_response"),
    ],
)
async def test_execution_guards(settings, replies, error):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    ) as client:
        engine = RuntimeEngine(
            SequenceModel(*replies), ToolGateway(client, [spec()]), Settings(**settings)
        )
        with pytest.raises(RuntimeFault, match=error):
            await engine.run("query", [], ignore_event)


async def test_tool_budget_rejected_before_execution():
    reply = call()
    reply.tool_calls.append({"id": "call_2", "name": "lookup", "args": {"order_id": "B"}})

    async def http(request):
        pytest.fail("tool budget exceeded but executed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        engine = RuntimeEngine(
            SequenceModel(reply), ToolGateway(client, [spec()]), Settings(max_tool_calls=1)
        )
        with pytest.raises(RuntimeFault, match="tool_call_limit"):
            await engine.run("query", [], ignore_event)


async def test_model_timeout():
    class SlowModel:
        async def ainvoke(self, messages):
            await asyncio.sleep(10)

    async with httpx.AsyncClient() as client:
        engine = RuntimeEngine(
            SlowModel(), ToolGateway(client, []), Settings(model_timeout_seconds=0.02)
        )
        with pytest.raises(RuntimeFault, match="model_timeout"):
            await engine.run("query", [], ignore_event)


async def test_graph_run_states_do_not_leak_between_conversations():
    class EchoModel:
        async def ainvoke(self, messages):
            await asyncio.sleep(0)
            return AIMessage(content=str(messages[-1].content))

    async with httpx.AsyncClient() as client:
        engine = RuntimeEngine(EchoModel(), ToolGateway(client, []), Settings())
        results = await asyncio.gather(*(engine.run(str(i), [], ignore_event) for i in range(20)))
    assert [answer for answer, _, _ in results] == [str(i) for i in range(20)]


async def test_prepared_react_instructions_are_an_equivalent_input_not_a_second_assembly():
    """AC-7: the Phase 3 React provider feeds this Engine, it does not re-assemble.

    The first run below is the untouched Phase 2 path; the second passes the
    prepared instructions through ``run`` while still supplying the same history,
    summary, and memory arguments. Model input, output, kept history, and dropped
    messages must be identical, and the payload must be the only message source.
    """
    contract = _instructions_contract()
    provider = _react_instruction_provider()
    history = [
        {"role": "user", "content": "h1"},
        {"role": "assistant", "content": "a1", "reasoning_content": "r1"},
        {"role": "assistant", "content": "a2", "reasoning_content": None},
    ]
    settings = Settings(_env_file=None, system_prompt="PLATFORM PROMPT", history_turns=2)
    instructions = contract.InstructionInput(
        engine=_engine_identity(),
        agent_id=AGENT_ID,
        agent_version=3,
        system_prompt=settings.system_prompt,
        history=tuple(dict(item) for item in history),
        current_user_input="current question",
        summary_message="SUMMARY: rolled up",
        customer_memory="CUSTOMER: preference-a",
    )
    prepared = provider.prepare(instructions)

    async with httpx.AsyncClient() as client:
        baseline = RuntimeEngine(
            SequenceModel(AIMessage(content="answer")), ToolGateway(client, []), settings
        )
        baseline_result = await baseline.run(
            "current question",
            list(history),
            ignore_event,
            summary_message="SUMMARY: rolled up",
            customer_memory="CUSTOMER: preference-a",
        )
        prepared_engine = RuntimeEngine(
            SequenceModel(AIMessage(content="answer")), ToolGateway(client, []), settings
        )
        # The prepared branch replaces the whole assembly, and the Engine refuses
        # business arguments it would have to ignore (H-2): the rendered Summary
        # and Memory text already sits inside the payload.
        prepared_result = await prepared_engine.run(
            "current question",
            list(history),
            ignore_event,
            prepared_instructions=prepared,
        )

    def captured(engine):
        return [
            {
                "type": message.type,
                "content": message.content,
                "additional_kwargs": dict(message.additional_kwargs),
            }
            for message in engine.model.seen[0]
        ]

    assert captured(baseline) == captured(prepared_engine)
    assert [item["type"] for item in captured(prepared_engine)] == [
        "system",
        "system",
        "system",
        "human",
        "ai",
        "ai",
        "human",
    ]
    assert captured(baseline)[1]["content"] == "SUMMARY: rolled up"
    assert captured(baseline)[2]["content"] == "CUSTOMER: preference-a"
    assert captured(baseline)[4]["additional_kwargs"] == {"reasoning_content": "r1"}
    assert captured(baseline)[5]["additional_kwargs"] == {}
    assert baseline_result == prepared_result
