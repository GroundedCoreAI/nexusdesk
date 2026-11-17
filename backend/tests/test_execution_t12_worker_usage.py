"""Phase 6 T-12: actual RuntimeWorker native-usage path."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_execution_t12_matrix import _claim, repo  # noqa: F401

from agent_platform.core_platform.agent_execution.contracts import AgentEvent
from agent_platform.core_platform.agent_execution.orchestration.execution_lifecycle import (
    ExecutionOutcome,
)
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def test_worker_persists_adapter_native_usage_and_terminal_usage(repo):  # noqa: F811
    repository, tenant, engine, settings = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]

    class Orchestrator:
        selector = ("codex", "cli_exec", "v1")

        async def execute(self, context, sink):
            await sink.emit_event(
                AgentEvent(
                    event_id=uuid4(),
                    execution_id=run_id,
                    engine_id="codex",
                    protocol_id="cli_exec",
                    adapter_version="v1",
                    sequence=1,
                    event_type="codex.usage",
                    source="engine_native",
                    timestamp=datetime.now(UTC),
                    payload={"usage": {"total_tokens": 7}},
                    producer_id="codex",
                    producer_event_id="worker-native-1",
                )
            )
            return ExecutionOutcome(
                status="completed",
                output="done",
                history=[],
                dropped=[],
                usage={"total_tokens": 8},
            )

    configured = settings.model_copy(
        update={"execution_phase3_enabled": True, "execution_orchestrator_enabled": True}
    )
    worker = RuntimeWorker(repository, object(), configured, "t12", orchestrator=Orchestrator())
    worker.owner = owner
    await worker._execute(claimed)
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT source,source_event_id,usage FROM runtime_usage_ledger "
                        "WHERE run_id=:id ORDER BY created_at"
                    ),
                    {"id": run_id},
                )
            )
            .mappings()
            .all()
        )
    by_source = {row["source"]: row for row in rows}
    assert by_source["codex"]["source_event_id"] == "worker-native-1"
    assert by_source["codex"]["usage"] == {"total_tokens": 7}
    assert by_source["engine_terminal"]["usage"] == {"total_tokens": 8}
    assert (await repository.get(run_id, tenant))["status"] == "completed"
