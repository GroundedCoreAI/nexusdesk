import asyncio
import inspect
import json
import logging
import math
import re
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from test_execution_orchestrator import (
    ASYNC_WATCHDOG_SECONDS,
    ParityMemory,
    ParityRepository,
    assert_real_worker_parity,
    canonicalize_parity_capture,
    parity_worker_row,
    run_real_worker_pair,
)
from test_runtime_engine import SequenceModel, call, spec

from agent_platform.applications.customer_service.runtime_routes import stream_events
from agent_platform.applications.platform_runtime.runtime_composition import (
    _build_execution_orchestrator,
)
from agent_platform.applications.platform_runtime.runtime_factory import RuntimeFactory
from agent_platform.core_platform.agent_execution.adapters.react import ReactAdapter
from agent_platform.core_platform.agent_execution.contracts import (
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
)
from agent_platform.core_platform.agent_execution.orchestration.execution_lifecycle import (
    ExecutionOutcome,
)
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault, RunView
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.service import ToolGateway

pytestmark = pytest.mark.asyncio


class RecordingRepository:
    def __init__(self, *, append_error=None, heartbeat_result="ok"):
        self.appended = []
        self.finished = []
        self.heartbeats = []
        self.append_error = append_error
        self.heartbeat_result = heartbeat_result

    async def append(self, run_id, owner, kind, data):
        self.appended.append((run_id, owner, kind, data))
        if self.append_error is not None:
            raise self.append_error

    async def finish(self, run_id, owner, status, **details):
        self.finished.append((run_id, owner, status, details))

    async def heartbeat(self, run_id, owner, lease_seconds):
        self.heartbeats.append((run_id, owner, lease_seconds))
        return self.heartbeat_result


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


class WorkerOrchestrator:
    def __init__(self, *, outcome=None, error=None, events=(), gate=None):
        self.outcome = outcome or ExecutionOutcome(
            status="completed",
            output="orchestrated answer",
            history=[],
            dropped=[],
        )
        self.error = error
        self.events = events
        self.gate = gate
        self.selector = ("react", "native", "v1")
        self.started = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.context = None
        self.worker_emit = None

    async def execute(self, context, worker_emit):
        self.context = context
        self.worker_emit = worker_emit
        self.started.set()
        try:
            for kind, data in self.events:
                await worker_emit(kind, data)
            if self.gate is not None:
                await self.gate.wait()
            if self.error is not None:
                raise self.error
            return self.outcome
        except asyncio.CancelledError:
            self.cleaned.set()
            raise


class ExplodingLegacy:
    async def for_run(self, row, emit):
        raise AssertionError("legacy factory must not be resolved")

    async def run(self, *args, **kwargs):
        raise AssertionError("legacy runtime must not run")


class ExplodingOrchestrator:
    async def execute(self, context, worker_emit):
        raise AssertionError("orchestrator must not execute while disabled")


class WorkerMemory:
    def __init__(self):
        self.summary_calls = []
        self.customer_calls = []
        self.context_calls = []

    def render_summary(self, summary):
        self.summary_calls.append(summary)
        return f"rendered summary: {summary}"

    async def customer_memory(self, row, settings):
        self.customer_calls.append((row, settings))
        row["_memory_reinforce"] = {"memory-item": 2}
        row["_memory_injected"] = {"items": 1}
        return "rendered customer memory"

    def memory_context(self, row, dropped, settings):
        self.context_calls.append((row, dropped, settings))
        return {
            "dropped": dropped,
            "reinforce": row["_memory_reinforce"],
            "injected": row["_memory_injected"],
        }


def orchestrated_worker(
    orchestrator,
    *,
    runtime=None,
    repository=None,
    notifier=None,
    memory=None,
    row=None,
):
    repository = repository or RecordingRepository()
    row = row or worker_row()
    settings = Settings(_env_file=None, execution_orchestrator_enabled=True)
    worker = RuntimeWorker(
        repository,
        ExplodingLegacy() if runtime is None else runtime,
        settings,
        "baseline-fingerprint",
        notifier=notifier,
        memory=memory,
        orchestrator=orchestrator,
    )
    return worker, repository, row


async def execute_orchestrated_worker(orchestrator, **kwargs):
    worker, repository, row = orchestrated_worker(orchestrator, **kwargs)
    await worker._execute(row)
    return repository, kwargs.get("notifier"), row


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


async def test_worker_legacy_positional_and_keyword_construction_stays_compatible():
    memory = WorkerMemory()
    repository = RecordingRepository()
    runtime = WorkerRuntime()
    settings = Settings(_env_file=None)

    positional = RuntimeWorker(repository, runtime, settings, "fp", None, None, memory)
    keyword = RuntimeWorker(repository, runtime, settings, "fp", memory=memory)
    with_orchestrator = RuntimeWorker(
        repository,
        runtime,
        settings,
        "fp",
        None,
        None,
        memory,
        WorkerOrchestrator(),
    )

    assert list(inspect.signature(RuntimeWorker).parameters)[-1] == "orchestrator"
    assert positional.memory is memory and positional.orchestrator is None
    assert keyword.memory is memory and keyword.orchestrator is None
    assert with_orchestrator.memory is memory
    assert with_orchestrator.orchestrator is not None


async def test_worker_off_with_injected_orchestrator_uses_only_legacy(caplog):
    repository = RecordingRepository()
    row = worker_row()
    worker = RuntimeWorker(
        repository,
        WorkerRuntime(),
        Settings(_env_file=None),
        "baseline-fingerprint",
        orchestrator=ExplodingOrchestrator(),
    )

    with caplog.at_level(logging.INFO, logger="agent_platform.core_platform.agent_runtime.worker"):
        await worker._execute(row)

    assert repository.finished[0][2] == "completed"
    assert repository.finished[0][3]["output"] == "answer"
    assert not any("path=orchestrator" in record.getMessage() for record in caplog.records)


async def test_worker_on_never_touches_legacy_factory_or_runtime():
    orchestrator = WorkerOrchestrator()
    repository, _, _ = await execute_orchestrated_worker(orchestrator)

    assert orchestrator.context.row["input"] == "synthetic input"
    assert repository.finished == [
        (
            repository.finished[0][0],
            repository.finished[0][1],
            "completed",
            {"output": "orchestrated answer", "history": [], "completion": None},
        )
    ]


async def test_worker_on_without_orchestrator_fails_safely_without_legacy_fallback():
    repository = RecordingRepository()
    worker = RuntimeWorker(
        repository,
        ExplodingLegacy(),
        Settings(_env_file=None, execution_orchestrator_enabled=True),
        "baseline-fingerprint",
    )

    await worker._execute(worker_row())

    assert repository.finished[0][2:] == ("failed", {"error": "execution_error"})
    assert len(repository.finished) == 1


@pytest.mark.parametrize("orchestrator_enabled", [False, True])
async def test_worker_fingerprint_check_precedes_both_execution_paths(orchestrator_enabled):
    repository = RecordingRepository()
    row = worker_row()
    row["config"]["fingerprint"] = "stale-fingerprint"
    orchestrator = ExplodingOrchestrator()
    worker = RuntimeWorker(
        repository,
        ExplodingLegacy(),
        Settings(
            _env_file=None,
            execution_orchestrator_enabled=orchestrator_enabled,
        ),
        "baseline-fingerprint",
        orchestrator=orchestrator,
    )

    await worker._execute(row)

    assert repository.finished[0][2:] == ("failed", {"error": "configuration_changed"})
    assert len(repository.finished) == 1


async def test_worker_on_passes_original_emit_with_identical_delta_and_durable_effects():
    notifier = RecordingNotifier()
    orchestrator = WorkerOrchestrator(
        events=(
            ("model.delta", {"round": 1, "text": "partial"}),
            ("model.completed", {"round": 1, "tool_calls": 0}),
        )
    )
    repository, _, row = await execute_orchestrated_worker(
        orchestrator,
        notifier=notifier,
    )

    assert orchestrator.worker_emit is not None
    assert "emit" not in orchestrator.context.__dataclass_fields__
    assert notifier.sent == [(row["id"], {"k": "delta", "round": 1, "text": "partial"})]
    assert [(kind, data) for _, _, kind, data in repository.appended] == [
        ("model.completed", {"round": 1, "tool_calls": 0})
    ]


async def test_worker_on_completed_outcome_preserves_memory_row_history_and_dropped_verbatim():
    memory = WorkerMemory()
    history = [{"role": "assistant", "content": "non-empty history"}]
    dropped = [{"role": "user", "content": "dropped history"}]
    outcome = ExecutionOutcome(
        status="completed",
        output="exact output",
        history=history,
        dropped=dropped,
        usage={"private": "not-for-repository"},
    )
    orchestrator = WorkerOrchestrator(outcome=outcome)
    row = worker_row()
    row.update(
        history=[{"role": "user", "content": "claimed history"}],
        summary="claimed summary",
        trace_id="trace-from-row",
    )
    worker, repository, row = orchestrated_worker(orchestrator, memory=memory, row=row)

    await worker._execute(row)

    context = orchestrator.context
    assert context.row is row
    assert context.history == [{"role": "user", "content": "claimed history"}]
    assert context.summary_message == "rendered summary: claimed summary"
    assert context.customer_memory == "rendered customer memory"
    assert context.trace_id == "trace-from-row"
    assert context.timeout_seconds == worker.settings.run_timeout_seconds
    assert memory.summary_calls == ["claimed summary"]
    assert memory.customer_calls == [(row, worker.settings)]
    assert memory.context_calls == [(row, dropped, worker.settings)]
    assert len(repository.finished) == 1
    assert repository.finished[0][2:] == (
        "completed",
        {
            "output": "exact output",
            "history": history,
            "completion": {
                "dropped": dropped,
                "reinforce": {"memory-item": 2},
                "injected": {"items": 1},
            },
        },
    )
    assert "usage" not in repository.finished[0][3]


def _assert_finite_duration_ms(message):
    match = re.search(r"(?:^| )duration_ms=([0-9]+\.[0-9]{3})(?: |$)", message)
    assert match is not None, message
    duration_ms = float(match.group(1))
    assert math.isfinite(duration_ms)
    assert duration_ms >= 0
    return duration_ms


@pytest.mark.parametrize(
    "outcome,expected",
    [
        (
            ExecutionOutcome(status="failed", legacy_error_code="future_provider_code"),
            ("failed", {"error": "future_provider_code"}),
        ),
        (
            ExecutionOutcome(status="cancelled"),
            ("cancelled", {"error": None}),
        ),
    ],
)
async def test_worker_on_non_completed_outcomes_have_no_memory_or_completion_values(
    outcome, expected
):
    memory = WorkerMemory()
    repository, _, _ = await execute_orchestrated_worker(
        WorkerOrchestrator(outcome=outcome),
        memory=memory,
    )

    assert repository.finished[0][2:] == expected
    assert len(repository.finished) == 1
    assert memory.context_calls == []


@pytest.mark.parametrize(
    "error,expected_code",
    [
        (ValueError("raw provider secret"), "execution_error"),
        (TimeoutError("outer timeout"), "run_timeout"),
        (RuntimeFault("model_timeout"), "model_timeout"),
    ],
)
async def test_worker_on_ordinary_execution_failures_are_safely_finished(
    error, expected_code, caplog
):
    memory = WorkerMemory()
    with caplog.at_level(logging.INFO, logger="agent_platform.core_platform.agent_runtime.worker"):
        repository, _, _ = await execute_orchestrated_worker(
            WorkerOrchestrator(error=error),
            memory=memory,
        )

    assert repository.finished[0][2:] == ("failed", {"error": expected_code})
    assert len(repository.finished) == 1
    assert memory.context_calls == []
    outcome_logs = [
        record.getMessage()
        for record in caplog.records
        if "path=orchestrator" in record.getMessage()
    ]
    assert len(outcome_logs) == 1
    _assert_finite_duration_ms(outcome_logs[0])


@pytest.mark.parametrize(
    "append_error,expected_status,expected_code",
    [
        (ValueError("private append failure"), "failed", "execution_error"),
        (asyncio.CancelledError(), "cancelled", None),
    ],
)
async def test_worker_on_worker_emit_failures_keep_ordinary_and_control_flow_semantics(
    append_error, expected_status, expected_code
):
    repository = RecordingRepository(append_error=append_error)
    orchestrator = WorkerOrchestrator(events=(("model.completed", {"round": 1}),))
    worker, repository, row = orchestrated_worker(
        orchestrator,
        repository=repository,
    )

    await worker._execute(row)

    assert repository.finished[0][2:] == (expected_status, {"error": expected_code})
    assert len(repository.finished) == 1


async def test_worker_on_external_cancellation_cleans_orchestrator_and_finishes_cancelled():
    gate = asyncio.Event()
    orchestrator = WorkerOrchestrator(gate=gate)
    worker, repository, row = orchestrated_worker(orchestrator)
    execution = asyncio.create_task(worker._execute(row))
    await orchestrator.started.wait()

    execution.cancel()
    await execution

    assert orchestrator.cleaned.is_set()
    assert repository.finished[0][2:] == ("cancelled", {"error": None})
    assert len(repository.finished) == 1


@pytest.mark.parametrize(
    "heartbeat_result,expected_status,expected_code",
    [
        ("cancel", "cancelled", None),
        ("lost", "failed", "worker_lost"),
    ],
)
async def test_worker_on_monitor_cancels_the_same_orchestrator_task(
    monkeypatch, caplog, heartbeat_result, expected_status, expected_code
):
    monitor_started = asyncio.Event()
    release_monitor = asyncio.Event()

    async def gated_sleep(_seconds):
        monitor_started.set()
        await release_monitor.wait()

    monkeypatch.setattr(asyncio, "sleep", gated_sleep)
    repository = RecordingRepository(heartbeat_result=heartbeat_result)
    orchestrator = WorkerOrchestrator(gate=asyncio.Event())
    worker, repository, row = orchestrated_worker(orchestrator, repository=repository)
    execution = asyncio.create_task(worker._execute(row))
    await orchestrator.started.wait()
    await monitor_started.wait()

    with caplog.at_level(logging.INFO, logger="agent_platform.core_platform.agent_runtime.worker"):
        release_monitor.set()
        await execution

    assert orchestrator.cleaned.is_set()
    assert repository.finished[0][2:] == (expected_status, {"error": expected_code})
    assert len(repository.finished) == 1
    assert len(repository.heartbeats) == 1
    outcome_logs = [
        record.getMessage()
        for record in caplog.records
        if "path=orchestrator" in record.getMessage()
    ]
    assert len(outcome_logs) == 1
    _assert_finite_duration_ms(outcome_logs[0])


async def test_worker_on_logs_only_low_cardinality_path_and_outcome(caplog):
    marker = "SYNTHETIC_PRIVATE_INPUT_DO_NOT_LOG"
    row = worker_row()
    row["input"] = marker
    orchestrator = WorkerOrchestrator(
        outcome=ExecutionOutcome(status="failed", legacy_error_code="execution_error")
    )
    worker, repository, row = orchestrated_worker(orchestrator, row=row)

    with caplog.at_level(logging.INFO, logger="agent_platform.core_platform.agent_runtime.worker"):
        await worker._execute(row)

    messages = [record.getMessage() for record in caplog.records]
    outcome_logs = [message for message in messages if "path=orchestrator" in message]
    assert len(outcome_logs) == 1
    _assert_finite_duration_ms(outcome_logs[0])
    assert str(row["id"]) in outcome_logs[0]
    assert "tuple=react/native/v1" in outcome_logs[0]
    assert "status=failed" in outcome_logs[0]
    assert "error=execution_failed" in outcome_logs[0]
    assert marker not in "\n".join(messages)
    assert "None" not in outcome_logs[0]
    assert repository.finished[0][2] == "failed"


async def test_worker_on_completed_finish_failure_logs_only_retry_failed(caplog):
    class FlakyFinishRepository(RecordingRepository):
        def __init__(self):
            super().__init__()
            self.finish_statuses = []

        async def finish(self, run_id, owner, status, **details):
            self.finish_statuses.append(status)
            if status == "completed":
                raise ValueError("synthetic completed finish failure")
            await super().finish(run_id, owner, status, **details)

    repository = FlakyFinishRepository()
    worker, _, row = orchestrated_worker(WorkerOrchestrator(), repository=repository)

    with caplog.at_level(logging.INFO, logger="agent_platform.core_platform.agent_runtime.worker"):
        await worker._execute(row)

    assert repository.finish_statuses == ["completed", "failed"]
    assert [finished_call[2:] for finished_call in repository.finished] == [
        ("failed", {"error": "execution_error"})
    ]
    outcome_logs = [
        record.getMessage()
        for record in caplog.records
        if "path=orchestrator" in record.getMessage()
    ]
    assert len(outcome_logs) == 1
    assert "status=failed" in outcome_logs[0]
    assert "status=completed" not in outcome_logs[0]
    _assert_finite_duration_ms(outcome_logs[0])


async def test_worker_on_logs_terminal_only_after_successful_finish(monkeypatch):
    events = []

    class OrderedFinishRepository(RecordingRepository):
        async def finish(self, run_id, owner, status, **details):
            events.append(("finish_started", status))
            await super().finish(run_id, owner, status, **details)
            events.append(("finish_succeeded", status))

    worker, _, row = orchestrated_worker(
        WorkerOrchestrator(),
        repository=OrderedFinishRepository(),
    )
    original_log = worker._log_orchestrator_terminal

    def ordered_log(row, status, started_at):
        events.append(("log", status))
        original_log(row, status, started_at)

    monkeypatch.setattr(worker, "_log_orchestrator_terminal", ordered_log)

    await worker._execute(row)

    assert events == [
        ("finish_started", "completed"),
        ("finish_succeeded", "completed"),
        ("log", "completed"),
    ]


@pytest.mark.parametrize(
    "outcome,expected_status",
    [
        (
            ExecutionOutcome(status="completed", output="done", history=[], dropped=[]),
            "completed",
        ),
        (ExecutionOutcome(status="failed", legacy_error_code="model_timeout"), "failed"),
        (ExecutionOutcome(status="cancelled"), "cancelled"),
    ],
)
async def test_worker_on_known_outcomes_keep_controlled_log_labels(
    caplog, outcome, expected_status
):
    worker, _, row = orchestrated_worker(WorkerOrchestrator(outcome=outcome))

    with caplog.at_level(logging.INFO, logger="agent_platform.core_platform.agent_runtime.worker"):
        await worker._execute(row)

    outcome_logs = [
        record.getMessage()
        for record in caplog.records
        if "path=orchestrator" in record.getMessage()
    ]
    assert len(outcome_logs) == 1
    _assert_finite_duration_ms(outcome_logs[0])
    assert "tuple=react/native/v1" in outcome_logs[0]
    assert f"status={expected_status}" in outcome_logs[0]
    if expected_status == "failed":
        assert "error=execution_failed" in outcome_logs[0]
        assert "model_timeout" not in outcome_logs[0]
    else:
        assert "error=" not in outcome_logs[0]


async def test_worker_on_terminal_log_uses_controlled_monotonic_duration(caplog, monkeypatch):
    readings = iter([100.0, 100.125])
    monkeypatch.setattr(
        "agent_platform.core_platform.agent_runtime.worker.monotonic",
        lambda: next(readings),
    )
    outcome = ExecutionOutcome(status="completed", output="done", history=[], dropped=[])
    worker, _, row = orchestrated_worker(WorkerOrchestrator(outcome=outcome))

    with caplog.at_level(logging.INFO, logger="agent_platform.core_platform.agent_runtime.worker"):
        await worker._execute(row)

    outcome_logs = [
        record.getMessage()
        for record in caplog.records
        if "path=orchestrator" in record.getMessage()
    ]
    assert len(outcome_logs) == 1
    assert _assert_finite_duration_ms(outcome_logs[0]) == 125.0
    assert "duration_ms=125.000" in outcome_logs[0]


async def test_real_react_orchestrator_worker_never_logs_unknown_legacy_code(caplog):
    secret_code = "SYNTHETIC_SECRET_IN_FUTURE_PROVIDER_CODE"

    class FaultRuntime:
        async def run(self, *args, **kwargs):
            raise RuntimeFault(secret_code)

    class FaultFactory:
        async def for_run(self, row, emit):
            return FaultRuntime()

    orchestrator = _build_execution_orchestrator(FaultFactory())
    worker, repository, row = orchestrated_worker(orchestrator)

    with caplog.at_level(logging.INFO):
        await worker._execute(row)

    assert repository.finished[0][2:] == ("failed", {"error": secret_code})
    messages = [record.getMessage() for record in caplog.records]
    assert secret_code not in "\n".join(messages)
    outcome_logs = [message for message in messages if "path=orchestrator" in message]
    assert len(outcome_logs) == 1
    _assert_finite_duration_ms(outcome_logs[0])
    assert "tuple=react/native/v1" in outcome_logs[0]
    assert "status=failed" in outcome_logs[0]
    assert "error=execution_failed" in outcome_logs[0]


def _spy_real_no_snapshot_runtime_factory(monkeypatch):
    calls = []
    worker_rows = []
    original_for_run = RuntimeFactory.for_run
    original_execute = RuntimeWorker._execute

    async def for_run(factory, row, emit):
        base_runtime = factory.base_runtime
        runtime = await original_for_run(factory, row, emit)
        calls.append(
            {
                "factory": factory,
                "base_runtime": base_runtime,
                "runtime": runtime,
                "row": row,
                "enabled": factory.settings.execution_orchestrator_enabled,
            }
        )
        return runtime

    async def execute(worker, row):
        worker_rows.append(row)
        return await original_execute(worker, row)

    monkeypatch.setattr(RuntimeFactory, "for_run", for_run)
    monkeypatch.setattr(RuntimeWorker, "_execute", execute)
    return calls, worker_rows


def _assert_real_no_snapshot_factory_calls(calls, worker_rows):
    assert len(calls) == len(worker_rows) == 2
    assert [factory_call["enabled"] for factory_call in calls] == [False, True]
    for factory_call, worker_row in zip(calls, worker_rows, strict=True):
        assert isinstance(factory_call["factory"], RuntimeFactory)
        assert factory_call["runtime"] is factory_call["base_runtime"]
        assert factory_call["runtime"] is factory_call["factory"].base_runtime
        assert factory_call["row"] is worker_row
    assert calls[0]["factory"] is not calls[1]["factory"]


async def test_p2_it01_no_snapshot_fixed_model_off_on_real_worker_parity(monkeypatch):
    """P2-IT01/CM02/CM07: anonymous React v1 preserves public/private semantics."""
    usage = {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    factory_calls, worker_rows = _spy_real_no_snapshot_runtime_factory(monkeypatch)
    model = SequenceModel(
        AIMessage(content="fixed answer", usage_metadata=usage),
        AIMessage(content="fixed answer", usage_metadata=usage),
    )

    off, on = await run_real_worker_pair(model=model)

    _assert_real_no_snapshot_factory_calls(factory_calls, worker_rows)
    assert_real_worker_parity(off, on)
    assert off["output"] == on["output"] == "fixed answer"
    assert off["usage"] == on["usage"] == [usage]
    assert off["aggregate_usage"] == on["aggregate_usage"] == {}
    assert off["history"] == [
        {"role": "user", "content": "current question"},
        {"role": "assistant", "content": "fixed answer"},
    ]
    assert on["terminal"]["type"] == "run.completed"
    assert all("agent_id" not in event["data"] for event in on["replay"])


async def test_p2_it03_truncation_summary_customer_memory_and_reasoning_match_legacy(monkeypatch):
    """P2-IT03: injection order, dropped input, successful memory and reasoning parity."""
    factory_calls, worker_rows = _spy_real_no_snapshot_runtime_factory(monkeypatch)
    old_history = [
        {"role": "user", "content": "old-zero"},
        {
            "role": "assistant",
            "content": "old-answer-zero",
            "reasoning_content": "old-hidden-zero",
        },
        {"role": "user", "content": "kept-question"},
        {
            "role": "assistant",
            "content": "kept-answer",
            "reasoning_content": "kept-hidden-reasoning",
        },
    ]
    model = SequenceModel(
        AIMessage(content="new answer", additional_kwargs={"reasoning_content": "new hidden"}),
        AIMessage(content="new answer", additional_kwargs={"reasoning_content": "new hidden"}),
    )
    row = parity_worker_row(history=old_history, summary="older conversation")

    off, on = await run_real_worker_pair(
        model=model,
        row=row,
        memory=ParityMemory(),
        settings_overrides={"history_turns": 1, "system_prompt": "synthetic system"},
    )

    _assert_real_no_snapshot_factory_calls(factory_calls, worker_rows)
    assert_real_worker_parity(off, on)
    assert [message["content"] for message in on["model_calls"][0]] == [
        "synthetic system",
        "SUMMARY: older conversation",
        "CUSTOMER: preference-a",
        "kept-question",
        "kept-answer",
        "current question",
    ]
    assert on["model_calls"][0][4]["additional_kwargs"] == {
        "reasoning_content": "kept-hidden-reasoning"
    }
    assert on["history"][-1]["reasoning_content"] == "new hidden"
    assert on["dropped"] == old_history[-2:]
    assert on["memory_context"]["reinforce"] == {"memory-item": 2}
    assert "new hidden" not in on["output"]
    assert all("reasoning" not in event["data"] for event in on["events"])


async def test_p2_it15_parallel_tools_and_business_events_keep_stable_payloads():
    """P2-IT15/CM08: only tool interleaving and raw timings are non-deterministic."""
    parallel_call = AIMessage(
        content="",
        tool_calls=[
            {"id": "call-a", "name": "lookup", "args": {"order_id": "A"}},
            {"id": "call-b", "name": "lookup", "args": {"order_id": "B"}},
        ],
        usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
    )
    final_usage = {"input_tokens": 8, "output_tokens": 1, "total_tokens": 9}
    model = SequenceModel(
        parallel_call,
        AIMessage(content="both done", usage_metadata=final_usage),
        deepcopy(parallel_call),
        AIMessage(content="both done", usage_metadata=final_usage),
    )

    async def http(request):
        await asyncio.sleep(0)
        return httpx.Response(200, json={"result": request.url.params["order_id"]})

    class BusinessRuntime:
        def __init__(self, engine):
            self.engine = engine

        async def run(self, message, history, emit, **kwargs):
            await emit(
                "business.progress",
                {"document_id": "business-document-a", "chunks": ["chunk-a", "chunk-b"]},
            )
            return await self.engine.run(message, history, emit, **kwargs)

    off, on = await run_real_worker_pair(
        model=model,
        specs=[spec()],
        transport=httpx.MockTransport(http),
        runtime_wrapper=BusinessRuntime,
    )
    off["raw_latency"] = {"pair": 1, "elapsed_ms": 11}
    on["raw_latency"] = {"pair": 1, "elapsed_ms": 13}

    assert_real_worker_parity(off, on, parallel=True)
    assert {
        event["data"]["call_id"] for event in on["events"] if event["type"] == "tool.started"
    } == {"call-a", "call-b"}
    assert on["usage"] == [
        {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
        final_usage,
    ]
    assert off["raw_latency"] != on["raw_latency"]


class _SSERepository:
    def __init__(self, events, *, transient_delta=False):
        self.all_events = events
        self.get_calls = 0
        self.transient_delta = transient_delta

    async def get(self, run_id, tenant, scope):
        self.get_calls += 1
        terminal = self.get_calls >= 3 if self.transient_delta else True
        return {
            "id": run_id,
            "status": "completed" if terminal else "running",
            "event_seq": self.all_events[-1]["seq"],
        }

    async def events(self, run_id, tenant, after, scope):
        visible = self.all_events
        if self.transient_delta and self.get_calls < 3:
            visible = visible[:-1]
        return [event for event in visible if event["seq"] > after][:200]


class _SSEListener:
    def __init__(self, delta=None):
        self.delta = delta
        self.unsubscribed = False

    async def subscribe(self, run_id):
        queue = asyncio.Queue()
        if self.delta is not None:
            await queue.put(json.dumps(self.delta))
        return queue

    async def unsubscribe(self, run_id, queue):
        self.unsubscribed = True


class _SSERequest:
    def __init__(self, repository, listener):
        runtime = SimpleNamespace(repository=repository, listener=listener)
        self.app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
        self.state = SimpleNamespace(business_scope="scope-a")

    async def is_disconnected(self):
        return False


async def _sse_frames(response):
    return "".join([chunk async for chunk in response.body_iterator])


async def test_p2_it05_internal_sse_replay_delta_cursor_and_hidden_replay_parity():
    """P2-IT05: durable IDs/order/terminal match; delta and tool.replay stay non-durable."""
    model = SequenceModel(AIMessage(content="SSE parity"), AIMessage(content="SSE parity"))
    off, on = await run_real_worker_pair(model=model)
    off_events = canonicalize_parity_capture(off)["replay"]
    on_events = canonicalize_parity_capture(on)["replay"]
    assert off_events == on_events

    async def render(events):
        response = await stream_events(
            off["run_id"],
            _SSERequest(_SSERepository(events), _SSEListener()),
            "tenant-a",
        )
        return await _sse_frames(response)

    assert await render(off_events) == await render(on_events)

    events = [
        {"seq": 1, "type": "model.started", "data": {"round": 1}},
        {"seq": 2, "type": "tool.replay", "data": {"private": "hidden"}},
        {"seq": 3, "type": "model.completed", "data": {"round": 1, "usage": {"input": 1}}},
        {"seq": 4, "type": "run.completed", "data": {"output": "done"}},
    ]
    repository = _SSERepository(events, transient_delta=True)
    listener = _SSEListener({"k": "delta", "round": 1, "text": "transient"})
    request = _SSERequest(repository, listener)

    response = await stream_events(events[0].get("run_id", uuid4()), request, "tenant-a")
    frames = await _sse_frames(response)

    assert [line for line in frames.splitlines() if line.startswith("event: ")] == [
        "event: model.started",
        "event: model.completed",
        "event: model.delta",
        "event: run.completed",
    ]
    assert [line for line in frames.splitlines() if line.startswith("id: ")] == [
        "id: 1",
        "id: 3",
        "id: 4",
    ]
    assert "tool.replay" not in frames
    assert '"text": "transient"' in frames
    delta_frame = next(frame for frame in frames.split("\n\n") if "model.delta" in frame)
    assert "id:" not in delta_frame
    assert frames.rstrip().endswith('event: run.completed\ndata: {"output": "done"}')
    assert listener.unsubscribed

    replay_repository = _SSERepository(events)
    replay = await stream_events(
        uuid4(), _SSERequest(replay_repository, _SSEListener()), "tenant-a", after=2
    )
    replay_frames = await _sse_frames(replay)
    assert "model.delta" not in replay_frames
    assert "tool.replay" not in replay_frames
    assert "id: 3" in replay_frames


async def test_p2_it05_internal_sse_last_event_id_drain_and_invalid_cursor():
    events = [
        {"seq": seq, "type": "business.progress", "data": {"seq": seq}} for seq in range(1, 202)
    ] + [{"seq": 202, "type": "run.completed", "data": {"output": "done"}}]
    request = _SSERequest(_SSERepository(events), _SSEListener())

    response = await stream_events(uuid4(), request, "tenant-a", after=2, last_event_id="3")
    frames = await _sse_frames(response)

    assert frames.count("event: business.progress") == 198
    assert "id: 3\n" not in frames
    assert "id: 4\n" in frames
    assert "id: 202\nevent: run.completed" in frames
    with pytest.raises(HTTPException) as caught:
        await stream_events(uuid4(), request, "tenant-a", last_event_id="invalid")
    assert caught.value.status_code == 400
    assert caught.value.detail == "invalid_last_event_id"


def _observe_react_public_result_and_private_outcome(monkeypatch):
    """Observe both terminal views without replacing the real Adapter or Orchestrator."""
    observations = []
    original_collect_outcome = ReactAdapter.collect_outcome
    original_collect_result = ReactAdapter.collect_result

    async def collect_outcome(adapter, handle):
        outcome, result = await asyncio.gather(
            original_collect_outcome(adapter, handle),
            original_collect_result(adapter, handle),
        )
        observations.append({"result": result, "outcome": outcome})
        return outcome

    monkeypatch.setattr(ReactAdapter, "collect_outcome", collect_outcome)
    return observations


def _assert_t9_run_view_and_terminal(capture, row, legacy_code, raw_marker=None):
    terminal = capture["terminal"]
    assert terminal["type"] == "run.failed"
    assert terminal["data"] == {"output": None, "error_code": legacy_code}
    now = datetime.now(UTC)
    view = RunView.model_validate(
        {
            "id": row["id"],
            "conversation_id": row.get("conversation_id", uuid4()),
            "status": capture["status"],
            "cancel_requested": False,
            "output": capture["output"],
            "error_code": capture["error_code"],
            "created_at": now,
            "started_at": now,
            "finished_at": terminal["timestamp"],
            "config": {"agent": {"id": "private-agent"}},
            "history": [{"content": "private-history"}],
            "execution_context": "private-context",
        }
    )
    assert view.status == "failed"
    assert view.output is None
    assert view.error_code == legacy_code
    serialized = view.model_dump_json()
    assert "private-agent" not in serialized
    assert "private-history" not in serialized
    assert "private-context" not in serialized
    if raw_marker is not None:
        assert raw_marker not in serialized


def _assert_t9_orchestrated_failure(
    on,
    observation,
    row,
    *,
    legacy_code,
    public_category,
    public_code,
    raw_marker=None,
):
    result = observation["result"]
    outcome = observation["outcome"]
    assert on["status"] == "failed"
    assert on["error_code"] == legacy_code
    assert result.status == "failed"
    assert result.output is None
    assert result.usage == {}
    assert result.engine_metadata == {}
    assert result.error is not None
    assert result.error.category is public_category
    assert result.error.code is public_code
    expected_error = ExecutionError(category=public_category, code=public_code)
    assert result.error.message == expected_error.message
    assert legacy_code not in result.model_dump_json()
    assert set(result.model_dump()).isdisjoint(
        {"history", "dropped", "legacy_error_code", "outcome", "context"}
    )
    assert outcome.status == "failed"
    assert outcome.legacy_error_code == legacy_code
    assert outcome.output is None
    assert outcome.history is None
    assert outcome.dropped is None
    assert outcome.usage == {}
    _assert_t9_run_view_and_terminal(on, row, legacy_code, raw_marker)


def _assert_t9_real_chain_failure(
    off,
    on,
    observation,
    row,
    *,
    legacy_code,
    public_category,
    public_code,
):
    assert_real_worker_parity(off, on)
    assert off["status"] == on["status"] == "failed"
    assert off["error_code"] == on["error_code"] == legacy_code
    _assert_t9_orchestrated_failure(
        on,
        observation,
        row,
        legacy_code=legacy_code,
        public_category=public_category,
        public_code=public_code,
    )
    _assert_t9_run_view_and_terminal(off, row, legacy_code)


async def _execute_t9_orchestrated_runtime(runtime_factory, monkeypatch):
    observations = _observe_react_public_result_and_private_outcome(monkeypatch)

    class RuntimeFactory:
        async def for_run(self, row, emit):
            return runtime_factory()

    on_repository, _, on_row = await execute_orchestrated_worker(
        _build_execution_orchestrator(RuntimeFactory()), repository=ParityRepository()
    )
    assert len(observations) == 1
    observation = observations[0]
    on = on_repository.capture(outcome=observation["outcome"])
    return on, observation, on_row, on_repository


async def _execute_t9_failure_pair(error_factory, monkeypatch):
    off_repository = ParityRepository()
    off_row = worker_row()
    off_worker = RuntimeWorker(
        off_repository,
        WorkerRuntime(error=error_factory()),
        Settings(_env_file=None, execution_orchestrator_enabled=False),
        "baseline-fingerprint",
    )
    await off_worker._execute(off_row)
    off = off_repository.capture()
    on, observation, on_row, _ = await _execute_t9_orchestrated_runtime(
        lambda: WorkerRuntime(error=error_factory()), monkeypatch
    )
    return off, on, observation, off_row, on_row


class _T9NoCompletionMemory(ParityMemory):
    def __init__(self):
        self.completion_calls = 0

    def memory_context(self, row, dropped, settings):
        self.completion_calls += 1
        raise AssertionError("failed budget executions must not write Memory completion state")


@pytest.mark.parametrize(
    "legacy_code", ["model_round_limit", "tool_call_limit", "model_output_too_large"]
)
async def test_p2_t9_a2_real_engine_budget_fault_off_on_parity(legacy_code, monkeypatch):
    """T9 A2: real RuntimeEngine guards trigger identical off/on budget failures."""
    settings_overrides = {}
    specs = []
    transport = None
    if legacy_code == "model_round_limit":
        settings_overrides = {"max_model_rounds": 1}
        replies = [call("budget"), call("budget")]
        specs = [spec()]
    elif legacy_code == "tool_call_limit":
        settings_overrides = {"max_tool_calls": 1}
        reply = call("budget")
        reply.tool_calls.append(
            {"id": "call_2", "name": "lookup", "args": {"order_id": "budget-2"}}
        )
        replies = [deepcopy(reply), deepcopy(reply)]
        specs = [spec()]
    else:
        replies = [AIMessage(content="x" * 64001) for _ in range(2)]

    if specs:

        async def http(request):
            if legacy_code == "tool_call_limit":
                pytest.fail("tool-call budget was exceeded before gateway execution")
            return httpx.Response(200, json={"result": "budget-controlled"})

        transport = httpx.MockTransport(http)

    model = SequenceModel(*replies)
    memory = _T9NoCompletionMemory()
    row = parity_worker_row()
    observations = _observe_react_public_result_and_private_outcome(monkeypatch)
    off, on = await run_real_worker_pair(
        model=model,
        specs=specs,
        transport=transport,
        row=row,
        memory=memory,
        settings_overrides=settings_overrides,
    )

    assert len(observations) == 1
    _assert_t9_real_chain_failure(
        off,
        on,
        observations[0],
        row,
        legacy_code=legacy_code,
        public_category=ExecutionErrorCategory.RESOURCE_EXHAUSTED,
        public_code=ExecutionErrorCode.RESOURCE_EXHAUSTED,
    )
    assert memory.completion_calls == 0
    assert on["memory_context"] is None


def _t9_fault_cases(codes, category, public_code):
    return [pytest.param(code, category, public_code, id=code) for code in codes.split()]


@pytest.mark.parametrize(
    "legacy_code,public_category,public_code",
    [
        *_t9_fault_cases(
            "agent_model_required configuration_changed model_resource_not_found "
            "model_resource_disabled model_profile_version_not_found model_tools_not_supported",
            ExecutionErrorCategory.CONFIGURATION_ERROR,
            ExecutionErrorCode.INVALID_REQUEST,
        ),
        *_t9_fault_cases(
            "model_input_too_large model_round_limit tool_call_limit model_output_too_large "
            "gateway_concurrency_exceeded gateway_request_quota_exceeded model_response_too_large",
            ExecutionErrorCategory.RESOURCE_EXHAUSTED,
            ExecutionErrorCode.RESOURCE_EXHAUSTED,
        ),
        *_t9_fault_cases(
            "invalid_model_response empty_model_response duplicate_tool_call_id repeated_tool_call",
            ExecutionErrorCategory.PROTOCOL_ERROR,
            ExecutionErrorCode.PROTOCOL_ERROR,
        ),
        *_t9_fault_cases(
            "model_provider_unavailable model_rate_limited model_provider_rejected "
            "model_transport_error model_stream_interrupted",
            ExecutionErrorCategory.ENGINE_UNAVAILABLE,
            ExecutionErrorCode.ENGINE_UNAVAILABLE,
        ),
        *_t9_fault_cases(
            "content_blocked_input content_blocked_output",
            ExecutionErrorCategory.PERMISSION_DENIED,
            ExecutionErrorCode.PERMISSION_DENIED,
        ),
        *_t9_fault_cases(
            "model_credential_unavailable",
            ExecutionErrorCategory.AUTHENTICATION_ERROR,
            ExecutionErrorCode.AUTHENTICATION_FAILED,
        ),
        *_t9_fault_cases(
            "model_timeout",
            ExecutionErrorCategory.TIMEOUT,
            ExecutionErrorCode.EXECUTION_TIMEOUT,
        ),
        *_t9_fault_cases(
            "future_private_provider_code",
            ExecutionErrorCategory.INTERNAL_ERROR,
            ExecutionErrorCode.INTERNAL_ERROR,
        ),
    ],
)
async def test_p2_t9_a5_full_runtime_fault_matrix_real_adapter_worker_repository(
    legacy_code, public_category, public_code, monkeypatch, caplog
):
    """T9 A5: every 03 section 6.1 RuntimeFault crosses the real execution chain."""
    with caplog.at_level(logging.INFO):
        off, on, observation, off_row, on_row = await _execute_t9_failure_pair(
            lambda: RuntimeFault(legacy_code), monkeypatch
        )

    _assert_t9_real_chain_failure(
        off,
        on,
        observation,
        on_row,
        legacy_code=legacy_code,
        public_category=public_category,
        public_code=public_code,
    )
    _assert_t9_run_view_and_terminal(off, off_row, legacy_code)
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert legacy_code not in messages


@pytest.mark.parametrize(
    "error_factory,legacy_code,public_category,public_code,raw_marker",
    [
        pytest.param(
            lambda: TimeoutError("SYNTHETIC_RAW_TIMEOUT_SECRET"),
            "run_timeout",
            ExecutionErrorCategory.TIMEOUT,
            ExecutionErrorCode.EXECUTION_TIMEOUT,
            "SYNTHETIC_RAW_TIMEOUT_SECRET",
            id="outer_run_timeout",
        ),
        pytest.param(
            lambda: RuntimeError("SYNTHETIC_RAW_PROVIDER_SECRET"),
            "execution_error",
            ExecutionErrorCategory.INTERNAL_ERROR,
            ExecutionErrorCode.INTERNAL_ERROR,
            "SYNTHETIC_RAW_PROVIDER_SECRET",
            id="unknown_ordinary_exception",
        ),
    ],
)
async def test_p2_t9_a5_timeout_and_unknown_exception_real_chain(
    error_factory,
    legacy_code,
    public_category,
    public_code,
    raw_marker,
    monkeypatch,
    caplog,
):
    with caplog.at_level(logging.INFO):
        off, on, observation, off_row, on_row = await _execute_t9_failure_pair(
            error_factory, monkeypatch
        )

    _assert_t9_real_chain_failure(
        off,
        on,
        observation,
        on_row,
        legacy_code=legacy_code,
        public_category=public_category,
        public_code=public_code,
    )
    _assert_t9_run_view_and_terminal(off, off_row, legacy_code)
    public_json = observation["result"].model_dump_json()
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert raw_marker not in public_json
    assert raw_marker not in messages
    assert raw_marker not in repr(on["events"])


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("NOT VALID", {"raw": "SYNTHETIC_RAW_EVENT_SECRET"}),
        ("run.started", {"raw": "SYNTHETIC_RAW_EVENT_SECRET"}),
        ("tool.replay", {"raw": "SYNTHETIC_RAW_EVENT_SECRET"}),
        ("engine.output_delta", ["not", "json", "SYNTHETIC_RAW_EVENT_SECRET"]),
        (
            "engine.output_delta",
            {"bad": object(), "raw": "SYNTHETIC_RAW_EVENT_SECRET"},
        ),
        (
            "engine.output_delta",
            {"timestamp": datetime.now(UTC), "raw": "SYNTHETIC_RAW_EVENT_SECRET"},
        ),
        ("engine.output_delta", {"execution_id": "SYNTHETIC_RAW_EVENT_SECRET"}),
        ("engine.output_delta", {"source": "SYNTHETIC_RAW_EVENT_SECRET"}),
    ],
)
async def test_p2_t9_a5_malformed_reserved_events_real_terminal_chain(
    kind, payload, monkeypatch, caplog
):
    """Malformed input is neither delivered nor acknowledged, but fails the real Run."""
    acknowledgements = []
    original_stream_events = ReactAdapter.stream_events

    def stream_events(adapter, handle):
        stream = original_stream_events(adapter, handle)
        original_acknowledge = stream.acknowledge

        async def acknowledge(event):
            acknowledgements.append(event)
            await original_acknowledge(event)

        stream.acknowledge = acknowledge
        return stream

    monkeypatch.setattr(ReactAdapter, "stream_events", stream_events)
    with caplog.at_level(logging.INFO):
        on, observation, on_row, repository = await _execute_t9_orchestrated_runtime(
            lambda: WorkerRuntime(events=((kind, payload),)), monkeypatch
        )

    _assert_t9_orchestrated_failure(
        on,
        observation,
        on_row,
        legacy_code="execution_error",
        public_category=ExecutionErrorCategory.PROTOCOL_ERROR,
        public_code=ExecutionErrorCode.PROTOCOL_ERROR,
        raw_marker="SYNTHETIC_RAW_EVENT_SECRET",
    )
    assert repository.finishes == [{"status": "failed", "error": "execution_error"}]
    assert repository.append_calls == 1
    assert on["events"] == []
    assert [event["type"] for event in on["replay"]] == ["run.failed"]
    assert acknowledgements == []
    public_json = observation["result"].model_dump_json()
    messages = "\n".join(record.getMessage() for record in caplog.records)
    for exposed in (public_json, messages, repr(repository.events)):
        assert "SYNTHETIC_RAW_EVENT_SECRET" not in exposed
        assert kind not in exposed


async def _execute_failure_pair(error):
    off_repository, _, _ = await execute_worker(WorkerRuntime(error=error))

    class FaultFactory:
        async def for_run(self, row, emit):
            return WorkerRuntime(error=error)

    on_repository, _, _ = await execute_orchestrated_worker(
        _build_execution_orchestrator(FaultFactory())
    )
    return off_repository, on_repository


@pytest.mark.parametrize(
    "error,expected_code",
    [
        (RuntimeFault("model_provider_unavailable"), "model_provider_unavailable"),
        (DomainError("model_provider_rejected", 503), "execution_error"),
        (RuntimeFault("future_private_provider_code"), "future_private_provider_code"),
        (RuntimeError("SYNTHETIC_RAW_PROVIDER_SECRET"), "execution_error"),
    ],
)
async def test_p2_it07_real_chain_failures_keep_legacy_codes_and_safe_logs(
    error, expected_code, caplog
):
    """P2-IT07/CM07: representative faults cross real Adapter/Worker without raw leakage."""
    with caplog.at_level(logging.INFO):
        off, on = await _execute_failure_pair(error)

    assert off.finished[0][2:] == on.finished[0][2:] == ("failed", {"error": expected_code})
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "SYNTHETIC_RAW_PROVIDER_SECRET" not in messages
    assert "future_private_provider_code" not in messages


async def test_p2_it20_public_run_view_and_observability_exclude_private_fields():
    """P2-IT20 non-PG: public DTO/log surfaces exclude Context, secrets and metric Run IDs."""
    now = datetime.now(UTC)
    run_id = uuid4()
    row = {
        "id": run_id,
        "conversation_id": uuid4(),
        "status": "failed",
        "cancel_requested": False,
        "output": None,
        "error_code": "execution_error",
        "created_at": now,
        "started_at": now,
        "finished_at": now,
        "config": {"agent": {"id": "forged-private-agent"}},
        "history": [{"content": "private-history"}],
        "execution_context": "private-context",
    }

    public = RunView.model_validate(row).model_dump(mode="json")

    assert set(public) == {
        "id",
        "conversation_id",
        "status",
        "cancel_requested",
        "output",
        "error_code",
        "created_at",
        "started_at",
        "finished_at",
    }
    serialized = json.dumps(public)
    assert "forged-private-agent" not in serialized
    assert "private-history" not in serialized
    assert "private-context" not in serialized
    worker_source = inspect.getsource(RuntimeWorker)
    assert "metrics" not in worker_source


class _GatedModel:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancel_calls = 0
        self.completed_calls = 0
        self.calls = 0
        self.seen = []

    async def ainvoke(self, messages):
        self.calls += 1
        self.seen.append(messages)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancel_calls += 1
            raise
        self.completed_calls += 1
        return AIMessage(content="late answer must not publish")


async def _cancel_real_model_path(enabled):
    model = _GatedModel()
    repository = ParityRepository()
    settings = Settings(_env_file=None, execution_orchestrator_enabled=enabled)
    async with httpx.AsyncClient() as client:
        engine = RuntimeEngine(model, ToolGateway(client, []), settings)

        class Factory:
            async def for_run(self, row, emit):
                return engine

        factory = Factory()
        worker = RuntimeWorker(
            repository,
            factory,
            settings,
            "parity-fingerprint",
            orchestrator=_build_execution_orchestrator(factory) if enabled else None,
        )
        task = asyncio.create_task(worker._execute(parity_worker_row()))
        try:
            await asyncio.wait_for(model.started.wait(), timeout=ASYNC_WATCHDOG_SECONDS)
            task.cancel()
            task.cancel()
            model.release.set()
            await asyncio.wait_for(task, timeout=ASYNC_WATCHDOG_SECONDS)
        finally:
            model.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    return model, repository


@pytest.mark.parametrize("enabled", [False, True])
async def test_p2_it08_cancel_waiting_model_repeat_cancel_and_late_release(enabled):
    """P2-IT08: cancellation owns model cleanup and suppresses every late terminal/event."""
    model, repository = await _cancel_real_model_path(enabled)

    assert model.cancel_calls == 1
    assert model.completed_calls == 0
    assert repository.finishes == [{"status": "cancelled", "error": None}]
    assert repository.events[-1]["type"] == "run.cancelled"
    assert repository.events[-1]["data"]["output"] is None
    assert len([event for event in repository.events if event["type"].startswith("run.")]) == 1
    assert all(event["type"] != "model.completed" for event in repository.events)


@pytest.mark.parametrize(
    "overrides,expected_code",
    [
        ({"model_timeout_seconds": 0.01, "run_timeout_seconds": 1}, "model_timeout"),
        ({"model_timeout_seconds": 30, "run_timeout_seconds": 1}, "run_timeout"),
    ],
)
async def test_p2_it10_model_and_outer_run_timeout_parity_without_retry(overrides, expected_code):
    """P2-IT10: inner model timeout and outer Run timeout remain distinct on both chains."""
    model = _GatedModel()
    off, on = await run_real_worker_pair(model=model, settings_overrides=overrides)

    assert_real_worker_parity(off, on)
    assert off["status"] == on["status"] == "failed"
    assert off["error_code"] == on["error_code"] == expected_code
    assert model.calls == 2
    assert model.cancel_calls == 2
    assert model.completed_calls == 0
    assert all(event["type"] != "model.completed" for event in on["events"])
