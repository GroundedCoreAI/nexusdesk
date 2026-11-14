"""Process-level worker heartbeats.

``runtime_runs.lease_until`` only proves that one run was renewed, so a wedged
or crashed loop can still look healthy. Every loop that is supposed to run
writes one row per role, whatever process owns it: the API process beats for
the loops it embeds, and each standalone worker entrypoint beats for its own.
The ``worker.runtime.heartbeat`` check then compares the rows against
``Settings.expected_worker_roles`` instead of trusting the newest one.
"""

import asyncio
import logging
import socket

from sqlalchemy.exc import SQLAlchemyError

from agent_platform.core_platform.platform_services.persistence.store import execute

BEAT_SECONDS = 15

logger = logging.getLogger(__name__)

UPSERT_BEAT = """
    INSERT INTO worker_heartbeats(worker_id, host, started_at, beat_at)
    VALUES(:worker_id, :host, now(), now())
    ON CONFLICT (worker_id) DO UPDATE SET beat_at = now(), host = EXCLUDED.host
"""


async def _beat(engine, roles) -> None:
    host = socket.gethostname()
    async with engine.begin() as conn:
        for role in roles:
            await execute(conn, UPSERT_BEAT, worker_id=role, host=host)


async def serve_heartbeats(engine, workers: dict[str, asyncio.Task]) -> None:
    """Beat only for the embedded loops that are still alive.

    A finished task is skipped on purpose: the row then ages out and the check
    reports the dead loop instead of the surviving process masking it.
    """

    while True:
        try:
            live = [name for name, task in workers.items() if not task.done()]
            if live:
                await _beat(engine, live)
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("Worker heartbeat skipped (%s)", type(exc).__name__)
        await asyncio.sleep(BEAT_SECONDS)


async def beat_forever(engine, *roles: str) -> None:
    """Beat for a standalone worker process until the task is cancelled."""

    while True:
        try:
            await _beat(engine, roles)
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("Worker heartbeat skipped (%s)", type(exc).__name__)
        await asyncio.sleep(BEAT_SECONDS)


def start_heartbeat(engine, *roles: str) -> asyncio.Task:
    return asyncio.create_task(beat_forever(engine, *roles))
