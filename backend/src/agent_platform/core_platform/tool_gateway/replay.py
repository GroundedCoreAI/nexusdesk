"""Replay stores for completed idempotent tool operations."""

import asyncio
import json
from collections import OrderedDict
from uuid import UUID

from sqlalchemy import text

from agent_platform.core_platform.platform_services.persistence.store import execute, one


class ProcessToolReplayCache:
    """Bounded cache used until durable result columns are introduced.

    The key is generated from the tenant-scoped Runtime run, tool name, and
    canonical arguments. This prevents duplicate side effects within one
    process while keeping the database schema unchanged.
    """

    def __init__(self, max_entries: int = 4096):
        self.max_entries = max_entries
        self._items: OrderedDict[str, dict[str, object]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, idempotency_key: str):
        async with self._lock:
            result = self._items.get(idempotency_key)
            if result is None:
                return None
            self._items.move_to_end(idempotency_key)
            return dict(result)

    async def put(self, idempotency_key: str, result: dict[str, object]) -> None:
        async with self._lock:
            self._items[idempotency_key] = dict(result)
            self._items.move_to_end(idempotency_key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


class DurableToolReplayCache:
    """Persist replay results in the existing Runtime event log.

    ``tool.replay`` is an internal event. Public event streams must advance
    past it without serializing its payload.
    """

    event_type = "tool.replay"

    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _run_id(idempotency_key: str) -> UUID:
        prefix, run_id, digest = idempotency_key.split(":", 2)
        if prefix != "runtime" or len(digest) != 64:
            raise ValueError("invalid_runtime_idempotency_key")
        return UUID(run_id)

    async def get(self, idempotency_key: str) -> dict[str, object] | None:
        run_id = self._run_id(idempotency_key)
        async with self.engine.connect() as connection:
            row = await one(
                connection,
                """SELECT data->'result' AS result
                FROM runtime_events
                WHERE run_id=:run_id
                  AND type=:event_type
                  AND data->>'idempotency_key'=:idempotency_key
                ORDER BY seq DESC
                LIMIT 1""",
                run_id=run_id,
                event_type=self.event_type,
                idempotency_key=idempotency_key,
            )
        result = row["result"] if row else None
        return dict(result) if isinstance(result, dict) else None

    async def put(self, idempotency_key: str, result: dict[str, object]) -> None:
        run_id = self._run_id(idempotency_key)
        async with self.engine.begin() as connection:
            await connection.execute(
                text("SELECT id FROM runtime_runs WHERE id=:run_id FOR UPDATE"),
                {"run_id": run_id},
            )
            existing = await one(
                connection,
                """SELECT 1 AS present
                FROM runtime_events
                WHERE run_id=:run_id
                  AND type=:event_type
                  AND data->>'idempotency_key'=:idempotency_key
                LIMIT 1""",
                run_id=run_id,
                event_type=self.event_type,
                idempotency_key=idempotency_key,
            )
            if existing:
                return
            sequence = await connection.scalar(
                text("""UPDATE runtime_runs SET event_seq=event_seq+1
                WHERE id=:run_id RETURNING event_seq"""),
                {"run_id": run_id},
            )
            if sequence is None:
                raise ValueError("runtime_run_not_found")
            await execute(
                connection,
                """INSERT INTO runtime_events(run_id,seq,type,data)
                VALUES (:run_id,:sequence,:event_type,CAST(:data AS jsonb))""",
                run_id=run_id,
                sequence=sequence,
                event_type=self.event_type,
                data=json.dumps(
                    {"idempotency_key": idempotency_key, "result": dict(result)},
                    ensure_ascii=False,
                ),
            )
