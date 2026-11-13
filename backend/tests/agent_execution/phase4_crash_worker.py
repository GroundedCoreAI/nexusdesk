"""Crash-lane worker for the Phase 4 P4-IT-08 restart corroboration (08 T16).

Run as a standalone interpreter process by the orchestration close-out test:
it boots a real Host/Registry/Runner stack against the migrated test
database, starts a long-lived trusted target (own process group) and then
blocks until the harness SIGKILLs this worker, leaving the durable ``running``
record and an orphaned target group behind - exactly the crash state the
identity-verified recovery path must converge. It is fixed test
infrastructure under ``backend/tests/agent_execution/`` (08 §1.9), never
reachable from product code or user input.

Usage (harness-supplied arguments only, no secrets on argv):

    python phase4_crash_worker.py <db_url_plain> <host_id> <boot_id> <marker_path>
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main(db_url: str, host_id: str, boot_id: str, marker: str) -> None:
    from agent_execution.process_test_adapters import build_trusted_registry, make_spec
    from agent_platform.core_platform.agent_execution.host.process_registry import (
        ProcessRegistry,
    )
    from agent_platform.core_platform.agent_execution.host.process_runner import ProcessRunner
    from agent_platform.core_platform.agent_execution.host.process_supervisor import (
        ProcessSupervisor,
    )
    from agent_platform.core_platform.agent_execution.host.runtime_host import RuntimeHost
    from agent_platform.core_platform.platform_services.persistence.database import (
        create_engine,
    )
    from agent_platform.core_platform.platform_services.platform_settings.settings import (
        Settings,
    )

    settings = Settings(
        _env_file=None,
        database_url=db_url.replace("postgresql://", "postgresql+asyncpg://"),
        tenant_id="phase4-crash-lane",
        embedded_worker=False,
    )
    engine = create_engine(settings)
    try:
        registry = ProcessRegistry(
            engine, host_id=host_id, host_instance_id=boot_id, sandbox_provider="local/v1"
        )
        host = RuntimeHost(
            enabled=True,
            host_id=host_id,
            runner=ProcessRunner(build_trusted_registry()),
            supervisor=ProcessSupervisor(cancel_grace_seconds=5, kill_timeout_seconds=5),
            registry=registry,
            wall_timeout_seconds=120,
        )
        # A durable Run row owns the FK; the marker proves the spawn landed.
        import uuid

        from agent_platform.applications.platform_runtime.runtime_hooks import (
            BusinessRuntimePersistenceHooks,
        )
        from agent_platform.core_platform.agent_runtime.repository import RunRepository
        from agent_platform.core_platform.agent_runtime.schemas import RunRequest

        repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
        row = await repo.submit(
            "phase4-crash-lane",
            RunRequest(conversation_id=f"conv-{uuid.uuid4()}", message="crash lane"),
            {"fingerprint": "phase4-crash-worker"},
            100,
            100,
            300,
        )
        run_id = uuid.UUID(str(row["id"]))
        managed = await host.start(
            make_spec("sleep", "120"),
            run_id=run_id,
            tenant_id="phase4-crash-lane",
            working_dir=Path(marker).parent,
        )
        Path(marker).write_text(
            json.dumps(
                {
                    "managed_id": str(managed.managed_id),
                    "run_id": str(run_id),
                    "pid": managed.os_pid,
                    "pgid": managed.process_group_id,
                }
            ),
            encoding="utf-8",
        )
        # Block until the harness SIGKILLs this worker: the durable record
        # stays 'running' under boot_id and the target group survives as a
        # true orphan of a crashed Host process.
        await asyncio.sleep(3600)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(2)
    asyncio.run(main(*sys.argv[1:5]))
