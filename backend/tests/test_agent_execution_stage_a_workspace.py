"""Phase 5 stage-A P3 tests: real workspace availability + CODEX_HOME scaffold.

G3 (08 R-13/C5): a real WorkspaceAvailabilityPort is injected by composition
from the assembled workdir subsystem (code-level, R-44), never from a settings
or environment key, and ``workspace_required`` stays True on Codex.
P3 scaffold: a per-Execution private CODEX_HOME is created inside the validated
Run workdir with no-follow/owner-only semantics and no secret content (P5/P6).
"""

import asyncio
import os
import stat
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from agent_platform.core_platform.agent_execution.adapters.codex.adapter import (
    CodexCliAdapter,
)
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexStageGate,
)
from agent_platform.core_platform.agent_execution.capability import (
    ASSEMBLED_WORKSPACE_GENERATION,
    AssembledWorkspaceGeneration,
    NoTrustedWorkspaceGeneration,
)
from agent_platform.core_platform.agent_execution.capability.ports import WorkspaceScope
from agent_platform.core_platform.agent_execution.contracts import ExecutionRequest
from agent_platform.core_platform.agent_execution.host.host_models import ResourcePolicy
from agent_platform.core_platform.agent_execution.workspace.execution_workdir import (
    PRIVATE_ENGINE_HOME_NAME,
    WorkdirOperationError,
    ensure_private_engine_home,
)

_TENANT = "tenant-p3"
_AGENT = UUID("00000000-0000-4000-8000-000000000701")
_EXEC = UUID("00000000-0000-4000-8000-000000000702")
_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=67_108_864,
    max_processes=16,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=65_536,
)
_GATE = CodexStageGate(
    cli_enabled=True,
    stage_a_verified=True,
    allowed_versions=("0.169.0",),
    trusted_tenants=(_TENANT,),
)


# ---------------------------------------------------------------------------
# G3: honest real workspace availability port
# ---------------------------------------------------------------------------


def test_assembled_port_reports_a_stable_generation_for_a_trusted_scope():
    port = AssembledWorkspaceGeneration()
    scope = WorkspaceScope(business_scope="biz-1", workspace_id="ws-1")
    first = port.current(scope)
    second = port.current(scope)
    assert first is not None
    assert first.available is True
    assert first.generation == second.generation == ASSEMBLED_WORKSPACE_GENERATION
    # A scope-stable generation must not advance per call (R-44 cache key).
    assert first.generation == ASSEMBLED_WORKSPACE_GENERATION


def test_assembled_port_fails_closed_on_an_empty_scope():
    # The port guards defensively even though WorkspaceScope's OpaqueString
    # normally rejects empty values at construction (model_construct reaches it).
    port = AssembledWorkspaceGeneration()
    assert port.current(WorkspaceScope.model_construct(business_scope="", workspace_id="ws-1")) is None
    assert port.current(WorkspaceScope.model_construct(business_scope="biz-1", workspace_id="")) is None


def test_no_trusted_generation_still_returns_none():
    # The default-off invariant is untouched: a deployment that assembles no
    # real workdir subsystem keeps the honest None answer.
    assert NoTrustedWorkspaceGeneration().current(
        WorkspaceScope(business_scope="biz-1", workspace_id="ws-1")
    ) is None


def test_codex_still_declares_workspace_required():
    # R-13: never downgrade the declaration to bypass the barrier.
    from agent_platform.core_platform.agent_execution.adapters.codex.adapter import (
        DECLARED_CAPABILITIES,
    )

    assert DECLARED_CAPABILITIES.workspace_required is True


def test_composition_injects_the_real_port_only_from_an_assembled_subsystem():
    # R-44: the port is chosen by code through production_ports' workspace_port
    # seam, never by a settings/env key. No injection -> fail-closed default.
    from agent_platform.applications.platform_runtime.runtime_composition import (
        production_ports,
    )

    class _Clock:
        def __call__(self):
            return 0.0

    from agent_platform.core_platform.platform_services.platform_settings.settings import (
        Settings,
    )

    settings = Settings(_env_file=None)
    # production_ports only stores the registry in the probe (no lookup at
    # construction), so a sentinel suffices to test port selection.
    registry = object()
    default = production_ports(settings, registry, clock=_Clock())  # type: ignore[arg-type]
    assert isinstance(default.workspace_port, NoTrustedWorkspaceGeneration)

    real = AssembledWorkspaceGeneration()
    injected = production_ports(settings, registry, clock=_Clock(), workspace_port=real)  # type: ignore[arg-type]
    assert injected.workspace_port is real


# ---------------------------------------------------------------------------
# P3 scaffold: private CODEX_HOME directory
# ---------------------------------------------------------------------------


def test_private_engine_home_is_owner_only_and_inside_the_run(tmp_path: Path):
    run_dir = tmp_path / "aa11" / str(_EXEC)
    run_dir.mkdir(parents=True, mode=0o700)
    home = ensure_private_engine_home(run_dir)
    assert home == run_dir / PRIVATE_ENGINE_HOME_NAME
    assert home.is_dir()
    mode = stat.S_IMODE(os.stat(home).st_mode)
    assert mode == 0o700
    # Scaffolding is content-free: no config, no auth, no secrets.
    assert list(home.iterdir()) == []


def test_private_engine_home_is_idempotent(tmp_path: Path):
    run_dir = tmp_path / "bb22" / str(_EXEC)
    run_dir.mkdir(parents=True, mode=0o700)
    first = ensure_private_engine_home(run_dir)
    second = ensure_private_engine_home(run_dir)
    assert first == second
    assert second.is_dir()


def test_private_engine_home_refuses_a_planted_symlink(tmp_path: Path):
    run_dir = tmp_path / "cc33" / str(_EXEC)
    run_dir.mkdir(parents=True, mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (run_dir / PRIVATE_ENGINE_HOME_NAME).symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkdirOperationError):
        ensure_private_engine_home(run_dir)
    assert list(outside.iterdir()) == []


class _RecordingHost:
    def __init__(self) -> None:
        self.specs: list = []

    async def start(self, spec, *, run_id, tenant_id, working_dir, **_):
        self.specs.append(spec)
        return type("Managed", (), {"managed_id": uuid4()})()


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=_EXEC,
        engine_id="codex",
        protocol_id="cli_exec",
        adapter_version="v1",
        tenant_id=_TENANT,
        agent_id=_AGENT,
        input="inspect the workspace",
    )


def test_adapter_starts_with_a_private_home_scaffold(tmp_path: Path):
    host = _RecordingHost()
    adapter = CodexCliAdapter(
        host,
        config=CodexConfig(version="0.169.0"),
        gate=_GATE,
        workdir_root=tmp_path,
        resource_policy=_POLICY,
    )
    relative = f"aa11/{_EXEC}"
    (tmp_path / relative).mkdir(parents=True, mode=0o700)
    request = _request().model_copy(update={"execution_workdir": relative})

    asyncio.run(adapter.start(request))

    assert len(host.specs) == 1
    home = tmp_path / relative / PRIVATE_ENGINE_HOME_NAME
    assert home.is_dir()
    assert stat.S_IMODE(os.stat(home).st_mode) == 0o700
    assert list(home.iterdir()) == []
    # R17 discipline: the environment still carries only the typed PATH slot.
    assert set(host.specs[0].environment) == {"PATH"}
