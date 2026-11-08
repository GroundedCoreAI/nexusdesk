import asyncio
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage
from test_runtime_engine import SequenceModel, call, spec

from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.service import ToolGateway

pytestmark = pytest.mark.asyncio


class RecordingRepository:
    def __init__(self):
        self.appended = []
        self.finished = []

    async def append(self, run_id, owner, kind, data):
        self.appended.append((run_id, owner, kind, data))

    async def finish(self, run_id, owner, status, **details):
        self.finished.append((run_id, owner, status, details))


class RecordingNotifier:
    def __init__(self):
        self.sent = []

    async def send(self, run_id, data):
        self.sent.append((run_id, data))


class WorkerRuntime:
    def __init__(self, *, events=(), result=None, error=None):
        self.events = events
        self.result = result or ("answer", [], [])
        self.error = error

    async def run(self, message, history, emit, **kwargs):
        for kind, data in self.events:
            await emit(kind, data)
        if self.error is not None:
            raise self.error
        return self.result


def worker_row():
    return {
        "id": uuid4(),
        "tenant_id": "synthetic-baseline-tenant",
        "business_id": "synthetic-baseline-business",
        "workspace_id": "synthetic-baseline-workspace",
        "config": {"fingerprint": "baseline-fingerprint"},
        "input": "synthetic input",
        "history": [],
        "summary": None,
    }


async def execute_worker(runtime, *, notifier=None):
    repository = RecordingRepository()
    row = worker_row()
    worker = RuntimeWorker(
        repository,
        runtime,
        Settings(_env_file=None),
        "baseline-fingerprint",
        notifier=notifier,
    )
    await worker._execute(row)
    return repository, notifier, row


async def test_engine_emits_streaming_model_event_payload_essentials():
    class StreamingModel:
        async def ainvoke_stream(self, messages, on_delta):
            await on_delta({"content": "synthetic "})
            await on_delta({"reasoning_content": "hidden reasoning"})
            await on_delta({"content": "answer"})
            return AIMessage(
                content="synthetic answer",
                usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                response_metadata={"gateway_call_id": "synthetic-gateway-call"},
            )

    events = []

    async def emit(kind, data):
        events.append((kind, data))

    async with httpx.AsyncClient() as client:
        engine = RuntimeEngine(StreamingModel(), ToolGateway(client, []), Settings(_env_file=None))
        output, history, dropped = await engine.run("synthetic question", [], emit)

    assert output == "synthetic answer"
    assert history == [
        {"role": "user", "content": "synthetic question"},
        {"role": "assistant", "content": output},
    ]
    assert dropped == []
    assert [kind for kind, _ in events] == [
        "model.started",
        "model.delta",
        "model.delta",
        "model.delta",
        "model.completed",
    ]
    assert events[0][1] == {"round": 1}
    assert events[1][1] == {"round": 1, "text": "synthetic "}
    assert events[2][1] == {"round": 1, "reasoning": "hidden reasoning"}
    assert events[3][1] == {"round": 1, "text": "answer"}
    completed = events[4][1]
    assert completed["round"] == 1
    assert completed["tool_calls"] == 0
    assert completed["usage"] == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    assert completed["gateway_call_id"] == "synthetic-gateway-call"
    assert isinstance(completed["first_token_ms"], int)
    assert isinstance(completed["duration_ms"], int)


async def test_engine_emits_tool_event_payload_essentials():
    async def http(request):
        return httpx.Response(200, json={"result": "synthetic"})

    model = SequenceModel(call(), AIMessage(content="finished"))
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    async with httpx.AsyncClient(transport=httpx.MockTransport(http)) as client:
        engine = RuntimeEngine(model, ToolGateway(client, [spec()]), Settings(_env_file=None))
        await engine.run("synthetic tool request", [], emit)

    tool_events = [(kind, data) for kind, data in events if kind.startswith("tool.")]
    assert [kind for kind, _ in tool_events] == ["tool.started", "tool.completed"]
    assert tool_events[0][1] == {"name": "lookup", "call_id": "call_1"}
    completed = tool_events[1][1]
    assert completed["name"] == "lookup"
    assert completed["call_id"] == "call_1"
    assert completed["ok"] is True
    assert completed["error"] is None
    assert "execution_status" in completed
    assert "tool_version" in completed
    assert isinstance(completed["duration_ms"], int)


async def test_engine_returns_trimmed_history_and_only_dropped_old_messages():
    old_history = [
        {"role": "user", "content": "old user zero"},
        {"role": "assistant", "content": "old assistant zero"},
        {"role": "user", "content": "old user one"},
        {"role": "assistant", "content": "old assistant one"},
    ]
    model = SequenceModel(AIMessage(content="new assistant"))

    settings = Settings(_env_file=None, history_turns=1, system_prompt="synthetic system")
    async with httpx.AsyncClient() as client:
        engine = RuntimeEngine(
            model,
            ToolGateway(client, []),
            settings,
        )
        output, history, dropped = await engine.run(
            "new user", old_history, lambda kind, data: asyncio.sleep(0)
        )

    assert output == "new assistant"
    assert history == [
        {"role": "user", "content": "new user"},
        {"role": "assistant", "content": "new assistant"},
    ]
    assert dropped == old_history[-2:]
    assert [message.content for message in model.seen[0]] == [
        "synthetic system",
        "old user one",
        "old assistant one",
        "new user",
    ]


async def test_worker_model_delta_is_transient_and_ordinary_event_is_appended():
    repository, notifier, row = await execute_worker(
        WorkerRuntime(
            events=(
                ("model.delta", {"round": 1, "text": "partial"}),
                ("model.completed", {"round": 1, "tool_calls": 0}),
            )
        ),
        notifier=RecordingNotifier(),
    )

    assert notifier.sent == [(row["id"], {"k": "delta", "round": 1, "text": "partial"})]
    assert [(kind, data) for _, _, kind, data in repository.appended] == [
        ("model.completed", {"round": 1, "tool_calls": 0})
    ]
    assert repository.finished[0][2:] == (
        "completed",
        {"output": "answer", "history": [], "completion": None},
    )


async def test_worker_sanitizes_ordinary_exception_to_execution_error():
    marker = "SYNTHETIC_PROVIDER_SECRET_DO_NOT_PERSIST"
    repository, _, _ = await execute_worker(WorkerRuntime(error=ValueError(marker)))

    assert len(repository.finished) == 1
    _, _, status, details = repository.finished[0]
    assert status == "failed"
    assert details == {"error": "execution_error"}
    assert marker not in repr(repository.finished)


@pytest.mark.parametrize("code", ["model_timeout", "provider_unavailable"])
async def test_worker_preserves_runtime_fault_code(code):
    repository, _, _ = await execute_worker(WorkerRuntime(error=RuntimeFault(code)))

    assert repository.finished[0][2:] == ("failed", {"error": code})


async def test_worker_maps_outer_timeout_to_run_timeout():
    repository, _, _ = await execute_worker(WorkerRuntime(error=TimeoutError("synthetic timeout")))

    assert repository.finished[0][2:] == ("failed", {"error": "run_timeout"})
