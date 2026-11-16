"""Stage A Codex CLI end-to-end through the real RuntimeHost (04 P5-IT-01/03/06).

The target is the repository's deterministic fake Codex fixture: it reproduces
the CLI wire format exactly (bounded JSONL on stdout, exit 0) and nothing more.
This proves the *integration chain* - gate, ProcessSpec, trusted target,
process group, bounded stdout, event mapping, usage extraction, terminal state,
durable process record - and it deliberately **cannot** prove Codex provider
compatibility, credentials, or production security. Those stay `pending_env` in
the test report.

A PostgreSQL database is required because the Host's process registry is
durable and ``runtime_host_processes.run_id`` references a real Run. The fixture
creates a throwaway database and migrates it to head, the same way the Phase 4
orchestration suite does.
"""

import asyncio
import hashlib
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from test_ticket_migrations import migrate

from agent_platform.core_platform.agent_execution.adapters.codex.adapter import (
    CodexCliAdapter,
)
from agent_platform.core_platform.agent_execution.adapters.codex.cli_exec import (
    CODEX_CLI_EXECUTABLE_ID,
    CODEX_CLI_FIXED_ARGV,
)
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexStageGate,
)
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    ExecutionErrorCode,
    ExecutionRequest,
)
from agent_platform.core_platform.agent_execution.host.host_models import ResourcePolicy
from agent_platform.core_platform.agent_execution.host.local_sandbox_provider import (
    LocalSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.process_registry import ProcessRegistry
from agent_platform.core_platform.agent_execution.host.process_runner import (
    ProcessRunner,
    TrustedTargetDescriptor,
    TrustedTargetRegistry,
)
from agent_platform.core_platform.agent_execution.host.process_supervisor import ProcessSupervisor
from agent_platform.core_platform.agent_execution.host.resource_manager import ResourceManager
from agent_platform.core_platform.agent_execution.host.runtime_host import RuntimeHost

pytestmark = pytest.mark.postgres

TENANT = "phase5-codex"
FAKE_CODEX = Path(__file__).resolve().parent.parent / "fixtures" / "codex_fake" / "fake_codex.py"
BOOT_ID = "boot-" + uuid.uuid4().hex

_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=536_870_912,
    max_processes=64,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=1_048_576,
)

_GATE = CodexStageGate(
    cli_enabled=True,
    app_server_enabled=False,
    allowed_versions=("0.169.0",),
    trusted_tenants=(TENANT,),
    stage_a_verified=True,
)


@pytest.fixture(scope="module")
def codex_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(url)
    name = "phase5_codex_" + uuid.uuid4().hex

    async def admin(statement):
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    target = urlunsplit(parts._replace(path="/" + name))
    migrate(target, "head")
    try:
        yield target
    finally:
        asyncio.run(admin(f'DROP DATABASE "{name}" WITH (FORCE)'))


def _wrapper(root: Path, scenario: str) -> Path:
    """A test-only launcher that runs the fake Codex with one scenario.

    The Host executes ``(executable_path, *argv)`` and requires ``argv`` to start
    with the fixed prefix, so the fixture cannot be the process itself: this
    wrapper pins the interpreter and the scenario, and the argv the adapter
    builds lands in ``"$@"`` where the fake script ignores it. The wrapper is
    itself the trusted target, which keeps the allowlist code-constant.
    """
    path = root / f"fake-codex-{scenario}"
    path.write_text(
        "#!/bin/sh\n"
        "export FAKE_CODEX_MODE=cli\n"
        f"export FAKE_CODEX_SCENARIO={scenario}\n"
        f'exec "{sys.executable}" "{FAKE_CODEX}" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _host(engine, root: Path, scenario: str) -> RuntimeHost:
    provider = LocalSandboxProvider(enforcement_required=False)
    return RuntimeHost(
        enabled=True,
        host_id="worker-codex",
        runner=ProcessRunner(
            TrustedTargetRegistry(
                (
                    TrustedTargetDescriptor(
                        executable_id=CODEX_CLI_EXECUTABLE_ID,
                        executable_path=str(_wrapper(root, scenario)),
                        fixed_prefix=CODEX_CLI_FIXED_ARGV,
                    ),
                )
            )
        ),
        supervisor=ProcessSupervisor(cancel_grace_seconds=0.5, kill_timeout_seconds=0.5),
        registry=ProcessRegistry(
            engine, host_id="worker-codex", host_instance_id=BOOT_ID, sandbox_provider="local/v1"
        ),
        wall_timeout_seconds=30,
        resource_manager=ResourceManager(provider, sample_interval_seconds=0.2),
    )


def _engine(url):
    from agent_platform.core_platform.platform_services.persistence.database import (
        create_engine,
    )
    from agent_platform.core_platform.platform_services.platform_settings.settings import (
        Settings,
    )

    return create_engine(
        Settings(
            _env_file=None,
            database_url=url.replace("postgresql://", "postgresql+asyncpg://"),
            tenant_id=TENANT,
            embedded_worker=False,
        )
    )


async def _submit_run(engine) -> uuid.UUID:
    """Pending rows need a real Run: the FK is genuine, not a test artifact."""
    from agent_platform.applications.platform_runtime.runtime_hooks import (
        BusinessRuntimePersistenceHooks,
    )
    from agent_platform.core_platform.agent_runtime.repository import RunRepository
    from agent_platform.core_platform.agent_runtime.schemas import RunRequest

    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    row = await repository.submit(
        TENANT,
        RunRequest(conversation_id=f"conv-{uuid.uuid4()}", message="codex stage a"),
        {"fingerprint": "phase5-codex"},
        100,
        100,
        120,
    )
    return uuid.UUID(str(row["id"]))


def _request(root: Path, execution_id: uuid.UUID, *, prompt: str = "run the fake codex fixture"):
    relative = f"aa11/{execution_id}"
    (root / relative).mkdir(parents=True, exist_ok=True, mode=0o700)
    return ExecutionRequest(
        execution_id=execution_id,
        engine_id="codex",
        protocol_id="cli_exec",
        adapter_version="v1",
        tenant_id=TENANT,
        agent_id=uuid.uuid4(),
        input=prompt,
        execution_workdir=relative,
    )


def _adapter(host, root: Path) -> CodexCliAdapter:
    return CodexCliAdapter(
        host,
        config=CodexConfig(version="0.169.0"),
        gate=_GATE,
        workdir_root=root,
        resource_policy=_POLICY,
        history=[{"role": "user", "content": "earlier turn"}],
    )


def _run(url, flow, roots: Path, scenario: str):
    async def main() -> None:
        engine = _engine(url)
        host = _host(engine, roots, scenario)
        try:
            await flow(host, roots, engine)
        finally:
            await host.close()
            await engine.dispose()

    asyncio.run(main())


def test_cli_success_end_to_end_through_the_real_host(codex_database, tmp_path) -> None:
    async def flow(host, root, engine) -> None:
        run_id = await _submit_run(engine)
        adapter = _adapter(host, root)
        handle = await adapter.start(_request(root, run_id))

        assert handle.process_id is None  # R-4b survives the real Host path
        assert handle.execution_id == run_id
        events = [event async for event in adapter.stream_events(handle)]
        # The fixture now emits the measured real-CLI shape (thread/turn/
        # item.completed/turn.completed), so the mapped names follow it.
        assert [event.event_type for event in events] == [
            "codex.thread.started",
            "codex.turn.started",
            "codex.item.completed",
            "codex.turn.completed",
        ]
        assert [event.sequence for event in events] == [1, 2, 3, 4]
        assert all(event.source == "engine_native" for event in events)
        assert all(event.engine_session_id == handle.provider_session_id for event in events)

        outcome = await adapter.collect_outcome(handle)
        assert outcome.status == "completed"
        assert outcome.output == "fake codex result"
        assert outcome.history == [
            {"role": "user", "content": "earlier turn"},
            {"role": "assistant", "content": "fake codex result"},
        ]
        assert outcome.dropped == []
        assert outcome.usage == {
            "input_tokens": 3,
            "output_tokens": 5,
            "total_tokens": 8,
        }

        # The durable process record reached a terminal state owned by the Host.
        pending = await host.registry.fetch_pending(batch_size=16)
        assert all(row.run_id != run_id for row in pending)
        assert host.health().active_count == 0

    _run(codex_database, flow, tmp_path, "success")


def test_malformed_cli_output_is_a_bounded_protocol_error(codex_database, tmp_path) -> None:
    async def flow(host, root, engine) -> None:
        run_id = await _submit_run(engine)
        adapter = _adapter(host, root)
        handle = await adapter.start(_request(root, run_id))

        with pytest.raises(AdapterExecutionError) as caught:
            async for _ in adapter.stream_events(handle):
                pass
        assert caught.value.error.code is ExecutionErrorCode.PROTOCOL_ERROR

        result = await adapter.collect_result(handle)
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.code is ExecutionErrorCode.PROTOCOL_ERROR
        assert "{" not in str(result.error)

    _run(codex_database, flow, tmp_path, "malformed")


def test_cancellation_terminates_the_real_process_group(codex_database, tmp_path) -> None:
    async def flow(host, root, engine) -> None:
        run_id = await _submit_run(engine)
        adapter = _adapter(host, root)
        handle = await adapter.start(_request(root, run_id))

        await asyncio.sleep(0.3)  # let the group start and block
        await adapter.cancel(handle)
        await adapter.cancel(handle)  # idempotent

        result = await adapter.collect_result(handle)
        assert result.status == "cancelled"
        assert result.output is None
        assert result.error is None
        # No survivor: the Host reaped the group and closed its record.
        pending = await host.registry.fetch_pending(batch_size=16)
        assert all(row.run_id != run_id for row in pending)
        health = host.health()
        assert health.active_count == 0

    _run(codex_database, flow, tmp_path, "hang")


def test_prompt_is_consumed_from_stdin_end_to_end(codex_database, tmp_path) -> None:
    """08 R18: the answer is the digest of exactly the bytes the Host delivered.

    The fixture reads stdin before emitting anything, so this cannot pass on a
    prompt that merely sat in the pipe buffer: the child must have consumed the
    payload and seen EOF (``codex exec … -`` semantics).
    """

    async def flow(host, root, engine) -> None:
        run_id = await _submit_run(engine)
        adapter = _adapter(host, root)
        prompt = "summarise the workspace inventory, please"
        handle = await adapter.start(_request(root, run_id, prompt=prompt))

        await adapter.stream_events(handle).__anext__()
        outcome = await adapter.collect_outcome(handle)
        assert outcome.status == "completed"
        expected = "stdin=" + str(len(prompt.encode("utf-8")))
        assert outcome.output is not None
        assert outcome.output.startswith(expected + ":")
        # The same bytes the request carried, no truncation and no re-encoding.
        assert outcome.output.split(":", 1)[1] == hashlib.sha256(prompt.encode()).hexdigest()[:16]

        pending = await host.registry.fetch_pending(batch_size=16)
        assert all(row.run_id != run_id for row in pending)
        assert host.health().active_count == 0

    _run(codex_database, flow, tmp_path, "prompt-digest")
