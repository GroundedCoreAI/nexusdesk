"""memory_search tool unit tests: registration gate and execution rendering.

P3-UT-09/10 pure parts; the end-to-end tool call through a run lives in the
PostgreSQL integration suites. ``_execute`` is called directly so no database
is needed (``execute`` only adds the tool_calls ledger around it).
"""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_platform.applications.platform_runtime.tool_defaults import (
    BUILTIN_SCHEMAS,
    default_tool_contributions,
)
from agent_platform.business_capabilities.memory.store import current_search_mode
from agent_platform.core_platform.platform_services.integrations.business_tools.platform_tools import (
    PlatformTools,
)
from agent_platform.core_platform.tool_gateway.replay import ProcessToolReplayCache
from agent_platform.core_platform.tool_gateway.service import HttpTool
from agent_platform.extension_contracts import EventEnvelope, RuntimeBindings


class _Policy:
    async def check(self, tenant, name, allowed):
        return None


class _Store:
    def __init__(self, hits, mode="text"):
        self.hits, self.calls, self._mode = hits, [], mode

    def available(self):
        return self._mode

    async def search(self, tenant_id, customer_id, query, limit):
        self.calls.append((tenant_id, customer_id, query, limit))
        return self.hits


class _StampedStore(_Store):
    """Double that stamps the per-call mode contextvar like the real stores."""

    async def search(self, tenant_id, customer_id, query, limit):
        current_search_mode.set(self._mode)
        return await super().search(tenant_id, customer_id, query, limit)


class _Ledger:
    def __init__(self):
        self.records = []

    async def record(self, operation):
        self.records.append(operation)


def make_tools(row, allowed, hits=(), emit=None, store=None, mode="text", ledger=None, events=None):
    http = SimpleNamespace(schemas=[], specs={})
    memory_store = store if store is not None else _Store(list(hits), mode)
    bindings = RuntimeBindings(
        policy=_Policy(), memory_store=memory_store, ledger=ledger, events=events
    )
    # Core no longer falls back to business defaults; the composition root (here,
    # the test) supplies the contributions explicitly.
    bindings = replace(bindings, tool_contributions=default_tool_contributions(bindings))
    return PlatformTools(http, bindings, row, allowed, [], emit)


def make_row(customer=True, memory_enabled=None):
    agent_config = {} if memory_enabled is None else {"memory_enabled": memory_enabled}
    return {
        "id": str(uuid4()),
        "tenant_id": "t1",
        "conversation_id": str(uuid4()),
        "customer_id": str(uuid4()) if customer else None,
        "config": {"agent": {"config": agent_config}},
    }


def names(tools):
    return {schema["function"]["name"] for schema in tools.schemas}


def test_schema_is_registered_with_customer_and_memory_enabled():
    tools = make_tools(make_row(), ["memory_search"])
    assert "memory_search" in names(tools)


def test_schema_hidden_without_customer():
    assert "memory_search" not in names(make_tools(make_row(customer=False), ["memory_search"]))


def test_schema_hidden_when_memory_disabled():
    tools = make_tools(make_row(memory_enabled=False), ["memory_search"])
    assert "memory_search" not in names(tools)


def test_schema_hidden_when_removed_from_draft():
    tools = make_tools(make_row(), ["knowledge_search"])
    assert "memory_search" not in names(tools)


def test_schema_description_and_parameters():
    schema = BUILTIN_SCHEMAS["memory_search"]["function"]
    assert "历史服务记录" in schema["description"]
    props = schema["parameters"]["properties"]
    assert set(props) == {"query", "limit"}
    assert props["limit"]["default"] == 5


@pytest.mark.asyncio
async def test_execute_renders_hits_and_forwards_arguments():
    hit = {
        "content": "工单 TK-1 已解决：已补发",
        "key": "ticket:TK-1:resolved",
        "updated_at": "2026-10-01",
        "score": 0.87654321,
    }
    tools = make_tools(make_row(), ["memory_search"], [hit])
    result = await tools._execute("memory_search", {"query": "补发"})
    assert result["ok"] and result["data"][0]["content"] == hit["content"]
    assert result["data"][0]["score"] == 0.876543
    _tenant, _customer, query, limit = tools.bindings.memory_store.calls[0]
    assert (query, limit) == ("补发", 5)


@pytest.mark.asyncio
async def test_execute_publishes_memory_search_event_contract():
    events: list[EventEnvelope] = []

    class Publisher:
        async def publish(self, event: EventEnvelope) -> None:
            events.append(event)

    row = make_row()
    tools = make_tools(row, ["memory_search"], events=Publisher())

    result = await tools._execute("memory_search", {"query": "补发"})

    assert result["ok"]
    assert len(events) == 1
    assert events[0].event_type == "memory.search.completed"
    assert events[0].tenant_id == row["tenant_id"]
    assert events[0].aggregate_type == "customer-memory"
    assert events[0].aggregate_id == row["customer_id"]
    assert events[0].payload == {"query": "补发", "hits": 0}
    assert events[0].idempotency_key.startswith(f"memory.search.completed:{row['id']}:")


@pytest.mark.asyncio
async def test_execute_empty_result_has_explicit_message():
    tools = make_tools(make_row(), ["memory_search"])
    result = await tools._execute("memory_search", {"query": "不存在"})
    assert result == {"ok": True, "data": [], "message": "未找到相关历史记录"}


@pytest.mark.asyncio
async def test_execute_rejected_when_not_registered():
    tools = make_tools(make_row(customer=False), ["memory_search"])
    result = await tools._execute("memory_search", {"query": "x"})
    assert result == {"ok": False, "error": "memory_search_unavailable"}
    assert tools.bindings.memory_store.calls == []


@pytest.mark.asyncio
async def test_execute_invalid_arguments():
    tools = make_tools(make_row(), ["memory_search"])
    assert await tools._execute("memory_search", {"query": ""}) == {
        "ok": False,
        "error": "invalid_arguments",
    }
    assert await tools._execute("memory_search", {"query": "x", "limit": 0}) == {
        "ok": False,
        "error": "invalid_arguments",
    }


# ---------------------------------------------------------------------------
# Phase 7: memory_search.completed payload carries the retrieval mode
# ---------------------------------------------------------------------------


def capture_emit():
    emitted = []

    async def emit(kind, data):
        emitted.append((kind, data))

    return emit, emitted


HIT = {
    "content": "工单 TK-1 已解决：已补发",
    "key": "ticket:TK-1:resolved",
    "updated_at": "2026-10-01",
    "score": 0.87654321,
}


@pytest.mark.asyncio
async def test_event_payload_has_mode_hits_and_returned():
    emit, emitted = capture_emit()
    tools = make_tools(make_row(), ["memory_search"], [HIT], emit=emit)
    result = await tools._execute("memory_search", {"query": "补发"})
    assert result["ok"]
    assert emitted == [
        ("memory_search.completed", {"mode": "text", "hits": 1, "returned": 1})
    ]


@pytest.mark.asyncio
async def test_event_payload_mode_from_store_stamp():
    """A store stamping the contextvar (PgVectorStore behaviour) wins over
    the available() fallback — this is how vector and keyword_fallback
    surface per call."""
    emit, emitted = capture_emit()
    tools = make_tools(
        make_row(),
        ["memory_search"],
        emit=emit,
        store=_StampedStore([HIT], mode="vector"),
    )
    await tools._execute("memory_search", {"query": "补发"})
    assert emitted[0][1] == {"mode": "vector", "hits": 1, "returned": 1}

    emit, emitted = capture_emit()
    tools = make_tools(
        make_row(),
        ["memory_search"],
        emit=emit,
        store=_StampedStore([], mode="keyword_fallback"),
    )
    await tools._execute("memory_search", {"query": "补发"})
    assert emitted[0][1] == {"mode": "keyword_fallback", "hits": 0, "returned": 0}


@pytest.mark.asyncio
async def test_event_payload_mode_does_not_bleed_across_calls():
    """A fallback stamp from one call must not leak into a later unstamped
    call in the same task: the emitter clears the contextvar before search."""
    emit, emitted = capture_emit()
    row = make_row()
    stamped = make_tools(
        row, ["memory_search"], emit=emit, store=_StampedStore([], "keyword_fallback")
    )
    await stamped._execute("memory_search", {"query": "x"})
    # Same task, a different (unstamped) store on the next call.
    plain = make_tools(row, ["memory_search"], [HIT], emit=emit)
    await plain._execute("memory_search", {"query": "y"})
    assert emitted[0][1]["mode"] == "keyword_fallback"
    assert emitted[1][1]["mode"] == "text"


@pytest.mark.asyncio
async def test_execute_records_through_operation_ledger_port():
    ledger = _Ledger()
    tools = make_tools(make_row(), ["memory_search"], ledger=ledger)

    result = await tools.execute("memory_search", {"query": "补发"})

    assert result["execution_status"] == "succeeded"
    assert len(ledger.records) == 1
    assert ledger.records[0].tool_name == "memory_search"


@pytest.mark.asyncio
async def test_idempotent_write_replays_completed_result_within_process():
    calls = []

    async def execute(name, arguments):
        calls.append((name, arguments))
        return {"ok": True, "data": {"accepted": True}}

    spec = HttpTool(
        name="write_order",
        description="Write an order.",
        url="https://example.test/order",
        method="POST",
        parameters={"type": "object", "additionalProperties": False},
    )
    http = SimpleNamespace(
        schemas=[spec.model_schema()],
        specs={spec.name: spec},
        execute=execute,
    )
    bindings = RuntimeBindings(
        policy=_Policy(),
        replay=ProcessToolReplayCache(),
    )
    tools = PlatformTools(
        http,
        bindings,
        make_row(),
        ["write_order"],
        [],
        None,
    )

    first = await tools.execute("write_order", {})
    second = await tools.execute("write_order", {})

    assert first == second
    assert calls == [("write_order", {})]
