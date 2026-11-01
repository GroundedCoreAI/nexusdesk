from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agent_platform.business_capabilities.customer_service.routing.decision import (
    RoutingDecision,
)
from agent_platform.business_capabilities.customer_service.routing.repository import (
    list_decisions,
    record,
    summarize_decisions,
)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConn:
    def __init__(self, results=None, fail=False):
        self.results = list(results or [])
        self.fail = fail
        self.calls = []
        self.savepoints = 0

    @asynccontextmanager
    async def begin_nested(self):
        self.savepoints += 1
        yield self

    async def execute(self, statement, params=None):
        if self.fail:
            raise RuntimeError("insert failed")
        self.calls.append((str(statement), params))
        return _Result(self.results.pop(0) if self.results else [])


def _decision():
    return RoutingDecision(
        tenant_id="tenant-a",
        business_id="customer-service",
        workspace_id="default",
        conversation_id=uuid4(),
        request_id=uuid4(),
        disposition="continue",
        execution_tier="agent",
        action="submit_agent_run",
        reason_code="default_agent",
        matched_rule_id=None,
        decider="cs_routing_v1",
        message_length=5,
    )


@pytest.mark.asyncio
async def test_record_inserts_inside_savepoint_with_parameterized_values():
    conn = FakeConn()
    decision = _decision()

    assert await record(conn, decision) is True

    assert conn.savepoints == 1
    sql, params = conn.calls[0]
    assert "INSERT INTO routing_decisions" in sql
    assert "tenant_id" in sql and "request_id" in sql
    assert params["tenant_id"] == "tenant-a"
    assert params["request_id"] == decision.request_id
    assert params["message_length"] == 5


@pytest.mark.asyncio
async def test_record_swallows_insert_failure_after_savepoint(caplog):
    conn = FakeConn(fail=True)

    with caplog.at_level("WARNING"):
        assert await record(conn, _decision()) is False

    assert conn.savepoints == 1
    assert "routing decision not recorded" in caplog.text


@pytest.mark.asyncio
async def test_list_decisions_uses_scope_compound_cursor_and_limit():
    conn = FakeConn(results=[[{"id": uuid4()}]])
    conversation_id = uuid4()
    before_at = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    before_id = uuid4()

    rows = await list_decisions(
        conn,
        tenant_id="tenant-a",
        business_id="customer-service",
        workspace_id="default",
        conversation_id=conversation_id,
        before_at=before_at,
        before_id=before_id,
        limit=25,
    )

    assert len(rows) == 1
    sql, params = conn.calls[0]
    assert "tenant_id = :tenant_id" in sql
    assert "business_id = :business_id" in sql
    assert "workspace_id = :workspace_id" in sql
    assert "conversation_id = :conversation_id" in sql
    assert "(created_at, id) <" in sql
    assert "ORDER BY created_at DESC, id DESC" in sql
    assert params == {
        "tenant_id": "tenant-a",
        "business_id": "customer-service",
        "workspace_id": "default",
        "conversation_id": conversation_id,
        "limit": 25,
        "before_at": before_at,
        "before_id": before_id,
    }


@pytest.mark.asyncio
async def test_list_decisions_requires_both_cursor_components():
    with pytest.raises(ValueError, match="provided together"):
        await list_decisions(
            FakeConn(),
            tenant_id="tenant-a",
            business_id="customer-service",
            workspace_id="default",
            conversation_id=uuid4(),
            before_at=datetime.now(UTC),
            before_id=None,
            limit=50,
        )


@pytest.mark.asyncio
async def test_list_decisions_omits_workspace_predicate_when_scope_has_none():
    conn = FakeConn(results=[[]])

    await list_decisions(
        conn,
        tenant_id="tenant-a",
        business_id="customer-service",
        workspace_id=None,
        conversation_id=uuid4(),
        before_at=None,
        before_id=None,
        limit=50,
    )

    sql, params = conn.calls[0]
    assert "business_id = :business_id" in sql
    assert "workspace_id = :workspace_id" not in sql
    assert "workspace_id" not in params


@pytest.mark.asyncio
async def test_summarize_decisions_returns_both_aggregate_lists():
    conn = FakeConn(
        results=[
            [{"key": "continue", "count": 2}],
            [{"key": "default_agent", "count": 2}],
        ]
    )
    since = datetime(2026, 10, 1, tzinfo=UTC)
    until = datetime(2026, 10, 8, tzinfo=UTC)

    summary = await summarize_decisions(
        conn,
        tenant_id="tenant-a",
        business_id="customer-service",
        workspace_id="default",
        since=since,
        until=until,
    )

    assert summary == {
        "by_disposition": [{"key": "continue", "count": 2}],
        "by_reason_code": [{"key": "default_agent", "count": 2}],
    }
    disposition_sql, disposition_params = conn.calls[0]
    reason_sql, reason_params = conn.calls[1]
    assert "GROUP BY disposition" in disposition_sql
    assert "GROUP BY reason_code" in reason_sql
    assert (
        disposition_params
        == reason_params
        == {
            "tenant_id": "tenant-a",
            "business_id": "customer-service",
            "workspace_id": "default",
            "since": since,
            "until": until,
        }
    )
