"""Phase 5 registration and capability-declaration tests (04 P5-UT-01/02/18)."""

import pytest

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.core_platform.agent_execution.adapters.codex.adapter import (
    CodexCliAdapter,
    declared_capabilities,
)
from agent_platform.core_platform.agent_execution.contracts import (
    ConfigurationError,
    ExecutionErrorCode,
)
from agent_platform.core_platform.agent_execution.registry import EngineRegistry
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

_BASE = {
    "_env_file": None,
    "database_url": "postgresql+asyncpg://agent:agent@127.0.0.1/none",
}

_ENABLED_CODEX = {
    "codex_cli_enabled": True,
    "codex_stage_a_verified": True,
    "codex_allowed_versions": ("0.169.0",),
    "codex_trusted_tenants": ("tenant-a",),
}


def _settings(**overrides) -> Settings:
    return Settings(**{**_BASE, **overrides})


def _registry(settings: Settings, *, runtime_host=None):
    registry = runtime_composition._execution_adapter_registry()
    runtime_composition._build_execution_orchestrator(
        None, registry, settings=settings, execution_runtime=_runtime(runtime_host)
    )
    return registry


class _RuntimeStub:
    """Only the two attributes the composition reads off the runtime subsystem."""

    def __init__(self, host) -> None:
        self.host = host
        self.workspace = object()


def _runtime(host):
    return None if host is None else _RuntimeStub(host)


def _error_code(action) -> ExecutionErrorCode:
    with pytest.raises(ConfigurationError) as caught:
        action()
    return caught.value.error.code


def test_both_protocols_share_one_engine_and_resolve_independently() -> None:
    settings = _settings(**_ENABLED_CODEX)
    engines = EngineRegistry()
    engines.register(runtime_composition.EngineDescriptor(engine_id="codex"))

    assert engines.get("codex") is not None

    registry = _registry(settings, runtime_host=object())
    descriptor = registry.metadata("codex", "cli_exec", "v1")
    assert descriptor.engine_id == "codex"
    assert descriptor.protocol_id == "cli_exec"

    # The App-Server Protocol is registered but never enabled in this phase.
    assert _error_code(lambda: registry.metadata("codex", "app_server", "v1")) is (
        ExecutionErrorCode.ADAPTER_DISABLED
    )


def test_default_deployment_disables_both_codex_protocols() -> None:
    registry = _registry(_settings())

    for protocol in ("cli_exec", "app_server"):
        assert _error_code(lambda p=protocol: registry.metadata("codex", p, "v1")) is (
            ExecutionErrorCode.ADAPTER_DISABLED
        )


def test_disabled_metadata_fails_closed_for_the_publish_path() -> None:
    """The publish/preview path resolves through ``metadata``; it must refuse."""
    registry = _registry(_settings())

    with pytest.raises(ConfigurationError) as caught:
        registry.metadata("codex", "cli_exec", "v1")
    assert caught.value.error.code is ExecutionErrorCode.ADAPTER_DISABLED
    assert "codex" in (caught.value.error.details.engine_id or "")


@pytest.mark.parametrize(
    "protocol",
    ["native", "unknown_protocol", ""],
)
def test_unknown_protocol_combinations_are_rejected(protocol: str) -> None:
    registry = _registry(_settings(**_ENABLED_CODEX))

    code = _error_code(lambda: registry.metadata("codex", protocol or "x", "v1"))
    assert code in {
        ExecutionErrorCode.UNKNOWN_PROTOCOL,
        ExecutionErrorCode.INCOMPATIBLE_ENGINE_PROTOCOL,
    }


def test_cli_registration_requires_a_runtime_host_to_be_enabled() -> None:
    """With no Host seam the descriptor stays disabled even when configured."""
    registry = _registry(_settings(**_ENABLED_CODEX))
    assert _error_code(lambda: registry.metadata("codex", "cli_exec", "v1")) is (
        ExecutionErrorCode.ADAPTER_DISABLED
    )


def test_instance_capabilities_match_the_registered_declaration() -> None:
    """``_assert_declared`` compares these two objects field by field."""
    import asyncio
    from pathlib import Path

    from agent_platform.core_platform.agent_execution.adapters.codex.config import (
        CodexConfig,
        CodexStageGate,
    )
    from agent_platform.core_platform.agent_execution.host.host_models import ResourcePolicy

    descriptor = runtime_composition._codex_adapters(_settings(), None)[0][0]
    adapter = CodexCliAdapter(
        None,  # type: ignore[arg-type] - the Host is unused by get_capabilities
        config=CodexConfig(version="0.169.0"),
        gate=CodexStageGate(),
        workdir_root=Path("/nonexistent"),
        resource_policy=ResourcePolicy(
            cpu_seconds=1,
            memory_bytes=1,
            max_processes=1,
            workdir_total_bytes=1,
            workdir_file_bytes=1,
            wall_seconds=1,
            output_max_bytes_per_stream=1,
        ),
    )

    assert asyncio.run(adapter.get_capabilities()) == descriptor.declared
    assert descriptor.declared == declared_capabilities()
    # C5: the declaration keeps the workspace requirement, accepting the
    # production barrier's fail-closed refusal instead of faking it to False.
    assert descriptor.declared.workspace_required is True


def test_codex_registration_does_not_add_a_second_warm_target() -> None:
    """R-46: warming describes enabled registrations only."""
    settings = _settings(execution_phase3_enabled=True, **_ENABLED_CODEX)
    registry = runtime_composition._execution_adapter_registry()
    subsystem = runtime_composition._build_execution_capability_subsystem(settings, registry)

    targets = tuple(subsystem.warm_targets)
    assert len(targets) == 1
    assert (targets[0].engine_id, targets[0].protocol_id) == ("react", "native")


def test_orchestrator_closed_loop_with_an_injected_codex_selector(tmp_path) -> None:
    """C1: prove the loop by injecting a selector; never change the Worker default.

    The production selector stays ``("react","native","v1")`` - that is exactly
    why this test has to pass its own. A stub Host stands in for process
    creation, so the assertion is about Orchestrator -> Adapter -> outcome
    plumbing (event emission, private outcome, no identity drift), not about
    spawning.
    """
    import asyncio
    import json
    from uuid import UUID, uuid4

    from agent_platform.core_platform.agent_execution.adapters.codex.adapter import (
        CodexCliAdapter,
    )
    from agent_platform.core_platform.agent_execution.adapters.codex.config import (
        CodexConfig,
        CodexStageGate,
    )
    from agent_platform.core_platform.agent_execution.host.host_models import (
        ProcessResult,
        ResourcePolicy,
    )
    from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
        build_execution_context,
        capture_execution_context,
    )
    from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
        ExecutionOrchestrator,
    )
    from agent_platform.core_platform.agent_execution.registry import (
        AdapterDescriptor,
        AdapterRegistry,
        EngineDescriptor,
        EngineRegistry,
        ProtocolDescriptor,
        ProtocolRegistry,
    )

    run_id = UUID("00000000-0000-4000-8000-000000000777")
    tenant = "tenant-a"
    stdout = (
        b'{"type":"message.completed","text":"codex says hi"}\n'
        b'{"type":"turn.completed","usage":{"input_tokens":2,"output_tokens":3}}\n'
    )

    class StubHost:
        def __init__(self) -> None:
            self.started = []

        async def start(self, spec, *, run_id, tenant_id, working_dir, **_):
            self.started.append((spec, run_id, tenant_id, working_dir))
            return type("Managed", (), {"managed_id": uuid4()})()

        async def wait(self, managed_id, *, wall_seconds=None, **_):
            return ProcessResult(
                managed_id=managed_id,
                run_id=run_id,
                final_state="exited",
                reason_code="runtime_host_exited",
                exit_code=0,
                wall_seconds=0.0,
                stdout=stdout,
            )

        async def cancel(self, managed_id, **_):  # pragma: no cover - success path
            raise AssertionError("successful execution must not be cancelled")

    host = StubHost()
    policy = ResourcePolicy(
        cpu_seconds=60,
        memory_bytes=67_108_864,
        max_processes=16,
        workdir_total_bytes=67_108_864,
        workdir_file_bytes=16_777_216,
        wall_seconds=60,
        output_max_bytes_per_stream=65_536,
    )
    gate = CodexStageGate(
        cli_enabled=True,
        allowed_versions=("0.169.0",),
        trusted_tenants=(tenant,),
        stage_a_verified=True,
    )

    engines = EngineRegistry()
    engines.register(EngineDescriptor(engine_id="codex"))
    protocols = ProtocolRegistry()
    protocols.register(ProtocolDescriptor(protocol_id="cli_exec"))
    registry = AdapterRegistry(engines, protocols)
    created: list[CodexCliAdapter] = []

    def factory() -> CodexCliAdapter:
        # Same seam the production composition uses: the claimed row's retained
        # history is read from the per-run ContextVar because the frozen
        # ``ExecutionRequest`` cannot carry it.
        adapter = CodexCliAdapter(
            host,
            config=CodexConfig(version="0.169.0"),
            gate=gate,
            workdir_root=tmp_path,
            resource_policy=policy,
            history=capture_execution_context().history,
        )
        created.append(adapter)
        return adapter

    registry.register(
        AdapterDescriptor(
            engine_id="codex",
            protocol_id="cli_exec",
            adapter_version="v1",
            config_schema=CodexConfig,
            declared=declared_capabilities(),
        ),
        factory,
    )

    context = build_execution_context(
        {
            "id": run_id,
            "tenant_id": tenant,
            "conversation_id": UUID("00000000-0000-4000-8000-000000000778"),
            "input": "current question",
            "config": {},
        },
        history=[{"role": "user", "content": "earlier"}],
        timeout_seconds=30,
    )
    emitted: list[tuple[str, dict]] = []

    # The production factory reads this exact ContextVar, so the loop below
    # carries the same history a real Run would: a completed outcome must never
    # drop it (on_completed overwrites the conversation history with it).
    async def emit(kind, data) -> None:
        emitted.append((kind, data))

    orchestrator = ExecutionOrchestrator(registry, selector=("codex", "cli_exec", "v1"))
    outcome = asyncio.run(orchestrator.execute(context, emit))

    assert outcome.status == "completed"
    assert outcome.output == "codex says hi"
    assert outcome.usage == {"input_tokens": 2, "output_tokens": 3}
    assert [kind for kind, _ in emitted] == [
        "codex.message.completed",
        "codex.turn.completed",
    ]
    assert outcome.history == [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "codex says hi"},
    ]
    assert created and created[0]._history == [{"role": "user", "content": "earlier"}]
    assert len(host.started) == 1
    spec, started_run_id, started_tenant, _ = host.started[0]
    assert started_run_id == run_id
    assert started_tenant == tenant
    assert json.dumps(spec.argv) == json.dumps(
        [
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "-",
        ]
    )
