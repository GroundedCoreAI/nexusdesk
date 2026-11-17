"""Phase 6 T-05: additive SSE envelope metadata and explicit replay gaps.

Every existing SSE field and ``id=seq`` stays intact; the only wire addition is
the reserved ``_execution`` object. Cursors below the per-Run retention floor
return an explicit 409 instead of silently resetting, and invalid cursors stay
400. Replay remains paged at 200 and terminal catch-up still ends the stream.
"""

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from test_runtime_postgres import internal_runtime_client

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.contracts import AgentEvent
from agent_platform.core_platform.agent_execution.events.envelope import from_agent_event
from agent_platform.core_platform.agent_execution.events.replay import (
    MAX_CURSOR,
    resolve_cursor,
    retention_gap,
    sse_payload,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

pytestmark = pytest.mark.postgres


# ---------------------------------------------------------------------------
# Pure helpers: cursor merge, gap classification, payload reservation
# ---------------------------------------------------------------------------


def test_cursor_merge_uses_strict_maximum_of_query_and_header():
    assert resolve_cursor(0, None) == 0
    assert resolve_cursor(5, None) == 5
    assert resolve_cursor(5, "9") == 9
    assert resolve_cursor(9, "5") == 9
    assert resolve_cursor(0, "0") == 0


@pytest.mark.parametrize(
    ("after", "last_event_id"),
    [
        (-1, None),
        (MAX_CURSOR + 1, None),
        (True, None),
        (0, ""),
        (0, "abc"),
        (0, "-1"),
        (0, str(MAX_CURSOR + 1)),
        (0, "1.5"),
    ],
)
def test_invalid_cursors_are_rejected(after, last_event_id):
    with pytest.raises(ValueError):
        resolve_cursor(after, last_event_id)


def test_retention_gap_is_only_below_a_positive_floor():
    assert retention_gap(10, 0) is False
    assert retention_gap(5, 5) is False
    assert retention_gap(6, 5) is False
    assert retention_gap(4, 5) is True
    assert retention_gap(0, 5) is True


def test_sse_payload_preserves_every_existing_key_and_adds_only_reserved_metadata():
    row = {
        "seq": 7,
        "type": "extension.note",
        "data": {"note": "hello", "count": 2},
        "event_id": uuid4(),
        "schema_version": "v1",
        "source": "engine_native",
        "trace_id": "trace-1",
    }
    payload = sse_payload(row)

    assert payload["note"] == "hello"
    assert payload["count"] == 2
    assert payload["_execution"] == {
        "event_id": str(row["event_id"]),
        "schema_version": "v1",
        "source": "engine_native",
        "trace_id": "trace-1",
    }
    # No existing key is moved, renamed, or dropped.
    assert set(payload) == {"note", "count", "_execution"}


def test_reserved_execution_key_overrides_untrusted_payload_content():
    row = {
        "data": {"_execution": {"event_id": "client-forged"}, "note": "x"},
        "event_id": uuid4(),
        "schema_version": "v1",
        "source": "platform",
        "trace_id": None,
    }
    payload = sse_payload(row)
    assert payload["_execution"]["event_id"] == str(row["event_id"])
    assert payload["note"] == "x"


def test_platform_event_metadata_defaults_are_stable():
    row = {"data": {"output": "ok"}, "event_id": uuid4()}
    payload = sse_payload(row)
    assert payload == {
        "output": "ok",
        "_execution": {
            "event_id": str(row["event_id"]),
            "schema_version": "v1",
            "source": "platform",
            "trace_id": None,
        },
    }


# ---------------------------------------------------------------------------
# PostgreSQL + HTTP end-to-end
# ---------------------------------------------------------------------------


async def _run_with_events(settings, tenant, *, count=205, floor=0):
    engine = create_engine(settings)
    repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        run = await repo.submit(
            tenant,
            RunRequest(conversation_id="sse-" + uuid4().hex[:10], message="sse"),
            {"fingerprint": "sse"},
            1000,
            100,
            120,
        )
        owner = uuid4()
        claimed = await repo.claim(owner, 120, tenant)
        assert claimed is not None and claimed["id"] == run["id"]
        epoch = claimed["lease_epoch"]
        for index in range(count):
            event = AgentEvent(
                event_id=uuid4(),
                execution_id=run["id"],
                engine_id="react",
                protocol_id="native",
                adapter_version="v1",
                sequence=index + 1,
                event_type="extension.note",
                source="engine_native",
                timestamp=datetime.now(UTC),
                payload={"note": index},
            )
            await repo.append_event(run["id"], owner, from_agent_event(event), lease_epoch=epoch)
        if floor:
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE runtime_runs SET event_retention_floor_seq=:floor WHERE id=:id"),
                    {"floor": floor, "id": run["id"]},
                )
        await repo.finish(
            run["id"],
            owner,
            "completed",
            output="done",
            history=[{"role": "assistant", "content": "done"}],
            lease_epoch=epoch,
        )
        return run["id"]
    finally:
        await engine.dispose()


def _frames(body):
    return [line.removeprefix("data: ") for line in body.splitlines() if line.startswith("data: ")]


def _ids(body):
    return [int(line.removeprefix("id: ")) for line in body.splitlines() if line.startswith("id: ")]


@pytest.mark.asyncio
async def test_multipage_reconnect_terminal_catchup_and_additive_metadata():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "sse-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    run_id = await _run_with_events(settings, tenant, count=205)
    try:
        async with internal_runtime_client(settings) as (_app, client):
            full = await client.get(f"/api/v1/runs/{run_id}/events?after=0")
            assert full.status_code == 200
            ids = _ids(full.text)
            assert ids == list(range(1, ids[-1] + 1))  # contiguous, no gaps
            assert len(ids) >= 208  # queued + started + 205 notes + completed
            frames = [json.loads(frame) for frame in _frames(full.text)]
            for frame in frames:
                assert "_execution" in frame
                assert set(frame["_execution"]) == {
                    "event_id",
                    "schema_version",
                    "source",
                    "trace_id",
                }
                assert frame["_execution"]["event_id"]
            note_frames = [f for f in frames if "note" in f]
            assert len(note_frames) == 205
            assert note_frames[0]["note"] == 0
            # Existing fields are untouched; only the reserved key is added.
            completed = [f for f in frames if "output" in f]
            assert completed[-1]["output"] == "done"

            reconnect = await client.get(f"/api/v1/runs/{run_id}/events?after=150")
            assert reconnect.status_code == 200
            reconnect_ids = _ids(reconnect.text)
            assert reconnect_ids[0] == 151
            assert reconnect_ids == list(range(151, ids[-1] + 1))

            invalid = await client.get(
                f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "abc"}
            )
            assert invalid.status_code == 400
            assert invalid.json()["detail"] == "invalid_last_event_id"
    finally:
        await _cleanup_db(url, tenant)


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", [0, 50, 99])
async def test_cursor_below_retention_floor_returns_explicit_409(cursor):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "sse-gap-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    run_id = await _run_with_events(settings, tenant, count=5, floor=100)
    try:
        async with internal_runtime_client(settings) as (_app, client):
            response = await client.get(f"/api/v1/runs/{run_id}/events?after={cursor}")
            assert response.status_code == 409
            assert response.json()["detail"] == "event_replay_gap"
            assert response.headers["X-Event-Retention-Floor"] == "100"
            # No silent earliest-available reset and no event frames leak;
            # the JSON error body is the explicit 409 contract.
            assert "id: " not in response.text
            assert "data: " not in response.text
            # At/above the floor the stream is still served (terminal run ends it).
            ok = await client.get(f"/api/v1/runs/{run_id}/events?after=100")
            assert ok.status_code == 200
    finally:
        await _cleanup_db(url, tenant)


async def _cleanup_db(url, tenant):
    engine = create_engine(Settings(database_url=url, tenant_id=tenant, embedded_worker=False))
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM execution_fencing_denials WHERE run_id IN "
                    "(SELECT id FROM runtime_runs WHERE tenant_id=:tenant)"
                ),
                {"tenant": tenant},
            )
            await conn.execute(
                text("DELETE FROM runtime_runs WHERE tenant_id=:tenant"), {"tenant": tenant}
            )
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _require_database():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
