"""Phase 4 sandbox & resource tests (08 T11/T12).

P4-UT-15/16/17/18 and the macOS-measurable halves of P4-IT-19/20/21/23/24.
The cgroup-v2 per-Execution hard limits (P4-IT-19 memory half, P4-IT-20,
quota total) are pending_env per 08 R-3 and stay skipped with attribution,
never substituted by the rlimit approximations this lane declares.
"""

import asyncio
import inspect
import os
import uuid
from pathlib import Path

import asyncpg
import pytest
from agent_execution.process_test_adapters import build_trusted_registry, make_spec
from test_ticket_migrations import migrate

from agent_platform.core_platform.agent_execution.host import runtime_host as host_module
from agent_platform.core_platform.agent_execution.host import sandbox_provider
from agent_platform.core_platform.agent_execution.host.host_models import (
    REASON_CANCELLED,
    REASON_EXITED,
    REASON_RESOURCE_EXCEEDED,
    REASON_SUPPORT_UNSUPPORTED,
    REASON_UNTRUSTED_TARGET,
    ProcessResult,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.local_sandbox_provider import (
    LocalSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.process_identity import process_alive
from agent_platform.core_platform.agent_execution.host.process_registry import ProcessRegistry
from agent_platform.core_platform.agent_execution.host.process_runner import ProcessRunner
from agent_platform.core_platform.agent_execution.host.process_supervisor import ProcessSupervisor
from agent_platform.core_platform.agent_execution.host.resource_manager import (
    ResourceManager,
    UsageSample,
    WorkdirUsage,
    default_group_observer,
)
from agent_platform.core_platform.agent_execution.host.runtime_host import (
    HostStartError,
    RuntimeHost,
)
from agent_platform.core_platform.agent_execution.host.sandbox_provider import (
    CAP_CPU_GROUP,
    CAP_CPU_RLIMIT,
    CAP_DISK_ACCOUNTING,
    CAP_DISK_QUOTA,
    CAP_FILE_SIZE_RLIMIT,
    CAP_MEMORY_GROUP,
    CAP_MEMORY_RLIMIT,
    CAP_OUTPUT_BOUND,
    CAP_PID_COUNT,
    CAP_PID_GROUP,
    CAP_PROCESS_GROUP,
    CAP_WALL_TIME,
    SandboxPolicyError,
    resolve_support,
)

TENANT = "phase4-sandbox"

# ---------------------------------------------------------------------------
# P4-UT-15: the Local Provider matrix declares exactly its support row
# ---------------------------------------------------------------------------


def test_local_matrix_declares_supported_subset_and_holds_no_strong_claims():
    matrix = LocalSandboxProvider().support_matrix()
    assert matrix[CAP_PROCESS_GROUP] == "hard"
    assert matrix[CAP_WALL_TIME] == "hard"
    assert matrix[CAP_OUTPUT_BOUND] == "hard"
    # RLIMIT approximations are declared approximate, never hard (08 R-3):
    # SIGXCPU/SIGXFSZ are real kernel enforcement, the group ceiling is not.
    assert matrix[CAP_CPU_RLIMIT] == "approximate"
    # RLIMIT_AS applicability is host-dependent (macOS refuses setrlimit(AS)
    # below the interpreter's mapped address space; the probe fork-tests it),
    # so the pin is matrix == probe, never a hardcoded value.
    assert matrix[CAP_MEMORY_RLIMIT] == sandbox_provider.probe_address_space_rlimit()
    assert matrix[CAP_MEMORY_RLIMIT] in {"approximate", "unsupported"}
    assert matrix[CAP_FILE_SIZE_RLIMIT] == "approximate"
    assert matrix[CAP_PID_COUNT] == "approximate"
    assert matrix[CAP_DISK_ACCOUNTING] == "approximate"
    # This provider implements no cgroup/quota mechanism: environment probes
    # may see controllers, the matrix still refuses to promise them.
    assert matrix[CAP_CPU_GROUP] == "unsupported"
    assert matrix[CAP_MEMORY_GROUP] == "unsupported"
    assert matrix[CAP_PID_GROUP] == "unsupported"
    assert matrix[CAP_DISK_QUOTA] == "unsupported"
    # ...and there is no strong-sandbox capability id to declare at all
    # (AC-10/M1): no namespace/network/credential rows exist.
    assert not [name for name in matrix if "namespace" in name or "network" in name]


def test_ladder_prefers_hard_then_labels_approximate_then_refuses():
    full = {
        CAP_CPU_GROUP: "hard",
        CAP_MEMORY_GROUP: "hard",
        CAP_PID_GROUP: "hard",
        CAP_DISK_QUOTA: "hard",
        CAP_WALL_TIME: "hard",
        CAP_OUTPUT_BOUND: "hard",
    }
    resolutions = resolve_support(full, enforcement_required=True)
    strengths = {r.dimension: r.strength for r in resolutions}
    assert strengths == {
        "cpu": "hard",
        "memory": "hard",
        "pid": "hard",
        "disk": "hard",
        "wall": "hard",
        "output": "hard",
    }

    host_matrix = LocalSandboxProvider().support_matrix()
    if host_matrix[CAP_MEMORY_RLIMIT] == "approximate":
        resolutions = resolve_support(host_matrix, enforcement_required=True)
    else:
        resolutions = resolve_support(host_matrix, enforcement_required=False)
    by_dimension = {r.dimension: r for r in resolutions}
    assert by_dimension["cpu"].strength == "approximate"
    assert by_dimension["cpu"].capability == CAP_CPU_RLIMIT
    # every approximation carries the non-equivalence label (03 §4.6)
    assert "non-equivalent" in by_dimension["cpu"].note

    memoryless = dict(host_matrix)
    memoryless[CAP_MEMORY_RLIMIT] = "unsupported"
    with pytest.raises(SandboxPolicyError) as excinfo:
        resolve_support(memoryless, enforcement_required=True)
    assert excinfo.value.code == REASON_SUPPORT_UNSUPPORTED


def test_unenforced_is_recorded_not_silent(caplog):
    matrix = LocalSandboxProvider().support_matrix()
    stripped = dict(matrix)
    stripped[CAP_MEMORY_RLIMIT] = "unsupported"
    with caplog.at_level("WARNING"):
        resolutions = resolve_support(stripped, enforcement_required=False)
    memory = next(r for r in resolutions if r.dimension == "memory")
    assert memory.strength == "unenforced"
    assert any("dimension=memory" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# P4-UT-17: cgroup detection parsing (substituted root; live enforcement
# experiments stay pending_env)
# ---------------------------------------------------------------------------


def test_cgroup_controller_probe_parses_lists_fail_closed(tmp_path):
    root = tmp_path / "cgroup"
    root.mkdir()
    assert sandbox_provider.probe_cgroup_v2_memory(root) == "unsupported"
    (root / "cgroup.controllers").write_text("cpuset cpu io memory pids\n")
    assert sandbox_provider.probe_cgroup_v2_memory(root) == "hard"
    assert sandbox_provider.probe_cgroup_v2_pids(root) == "hard"
    assert sandbox_provider.probe_cgroup_v2_cpu(root) == "hard"
    (root / "cgroup.controllers").write_text("cpuset io\n")
    assert sandbox_provider.probe_cgroup_v2_memory(root) == "unsupported"


# ---------------------------------------------------------------------------
# P4-UT-18: the untrusted gate is code, settings cannot flip it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["arbitrary_command", "uploaded_code", "untrusted_multi_tenant"])
def test_every_untrusted_entry_is_refused_before_anything(flag):
    provider = LocalSandboxProvider()
    with pytest.raises(SandboxPolicyError) as excinfo:
        asyncio.run(provider.prepare(make_spec("exit", "0"), run_id=uuid.uuid4(), **{flag: True}))
    assert excinfo.value.code == REASON_UNTRUSTED_TARGET


def test_gate_has_no_configuration_path():
    signature = inspect.signature(LocalSandboxProvider.prepare)
    for name in ("arbitrary_command", "uploaded_code", "untrusted_multi_tenant"):
        assert signature.parameters[name].default is False
    constructor = inspect.signature(LocalSandboxProvider.__init__)
    assert not {"arbitrary_command", "uploaded_code", "untrusted_multi_tenant"} & set(
        constructor.parameters
    )
    # No settings import exists in the provider module: the ONLY boolean knob
    # is enforcement_required, and it governs support, never trust.
    module = __import__(LocalSandboxProvider.__module__, fromlist=["x"])
    text = Path(module.__file__).read_text()
    assert "platform_settings" not in text
    assert "Settings" not in text
    assert "enforcement_required" in text


def test_gate_refuses_even_when_enforcement_relaxed():
    provider = LocalSandboxProvider(enforcement_required=False)
    with pytest.raises(SandboxPolicyError) as excinfo:
        asyncio.run(
            provider.prepare(
                make_spec("exit", "0"),
                run_id=uuid.uuid4(),
                untrusted_multi_tenant=True,
            )
        )
    assert excinfo.value.code == REASON_UNTRUSTED_TARGET


# ---------------------------------------------------------------------------
# P4-UT-16: idempotent release + excess decisions + classification
# ---------------------------------------------------------------------------


class _RecordingProvider:
    """A complete, DIFFERENT provider (P4-IT-24): different id/version, no
    rlimit hooks, release counter - the Host code never notices."""

    provider_id = "recording"
    provider_version = "v9"

    def __init__(self, matrix=None, enforcement_required=False) -> None:
        self.calls = {"prepare": 0, "release": 0}
        self._matrix = dict(matrix or LocalSandboxProvider().support_matrix())
        self._enforcement_required = enforcement_required

    def support_matrix(self):
        return self._matrix

    async def prepare(
        self,
        spec,
        *,
        run_id,
        arbitrary_command=False,
        uploaded_code=False,
        untrusted_multi_tenant=False,
    ):
        self.calls["prepare"] += 1
        if arbitrary_command or uploaded_code or untrusted_multi_tenant:
            raise SandboxPolicyError(REASON_UNTRUSTED_TARGET, "untrusted execution gate")
        resolutions = resolve_support(self._matrix, enforcement_required=self._enforcement_required)
        return sandbox_provider.SandboxReservation(
            reservation_id=uuid.uuid4(),
            run_id=run_id,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            resolutions=resolutions,
            policy_digest=sandbox_provider.policy_digest(spec),
            policy_values={},
        )

    def preexec_for(self, reservation):
        return None

    async def release(self, reservation):
        self.calls["release"] += 1
        reservation.released = True


def _reservation(**overrides):
    # False here because this host's AS applicability varies; the decision
    # consistency under True is pinned explicitly by its own test.
    resolutions = resolve_support(
        LocalSandboxProvider().support_matrix(), enforcement_required=False
    )
    values = {
        "reservation_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "provider_id": "local",
        "provider_version": "v1",
        "resolutions": resolutions,
        "policy_digest": "sha256:" + "0" * 64,
    }
    values.update(overrides)
    return sandbox_provider.SandboxReservation(**values)


def _policy(**overrides) -> ResourcePolicy:
    values = {
        "cpu_seconds": 60,
        "memory_bytes": 67_108_864,
        "max_processes": 16,
        "workdir_total_bytes": 67_108_864,
        "workdir_file_bytes": 16_777_216,
        "wall_seconds": 60,
        "output_max_bytes_per_stream": 65_536,
    }
    values.update(overrides)
    return ResourcePolicy(**values)


def _sample(**overrides) -> UsageSample:
    values = {
        "process_count": 1,
        "rss_bytes": 4096,
        "cpu_seconds": 0.1,
        "workdir_bytes": None,
        "workdir_files": None,
        "observed_at_posix": 0.0,
    }
    values.update(overrides)
    return UsageSample(**values)


def _result(reason=REASON_EXITED, final_state="exited", term_signal=None, exit_code=0):
    return ProcessResult(
        managed_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        final_state=final_state,
        reason_code=reason,
        exit_code=exit_code,
        term_signal=term_signal,
        wall_seconds=1.0,
    )


def test_release_is_idempotent_through_resource_manager():
    provider = _RecordingProvider()
    manager = ResourceManager(provider, sample_interval_seconds=0.1)
    reservation_a = asyncio.run(manager.admit(make_spec("exit", "0"), run_id=uuid.uuid4()))
    reservation_b = asyncio.run(manager.admit(make_spec("exit", "0"), run_id=uuid.uuid4()))
    asyncio.run(manager.release(reservation_a))
    asyncio.run(manager.release(reservation_a))
    assert provider.calls["release"] == 1  # usage release lands once (P4-UT-16)
    asyncio.run(manager.release(reservation_b))
    assert provider.calls["release"] == 2  # distinct reservations release separately


def test_rlimit_kill_classification_and_non_interference():
    manager = ResourceManager(_RecordingProvider(), sample_interval_seconds=0.1)
    reservation = _reservation()
    # Explicit CPU-applied reservation: the attribution under test must not
    # depend on what the *host* happens to probe for cpu_rlimit.
    cpu_provider = LocalSandboxProvider(probes={CAP_CPU_RLIMIT: lambda: "approximate"})
    reservation_cpu = _reservation(
        resolutions=resolve_support(cpu_provider.support_matrix(), enforcement_required=False)
    )

    assert manager.classify_result(_result(term_signal=24), reservation).reason_code == (
        REASON_RESOURCE_EXCEEDED
    )
    assert manager.classify_result(_result(term_signal=25), reservation).reason_code == (
        REASON_RESOURCE_EXCEEDED
    )
    # 08 R-14: on Linux a soft==hard RLIMIT_CPU delivers SIGKILL(9) in the same
    # tick as the would-be SIGXCPU, so a natural-exit SIGKILL over a Reservation
    # that applied the cpu_rlimit is the kernel's CPU enforcement - attributed
    # from the recorded mechanism, not from the ambiguous signal number.
    assert manager.classify_result(_result(term_signal=9), reservation_cpu).reason_code == (
        REASON_RESOURCE_EXCEEDED
    )
    # untouched reasons pass through: plain exit, cancellation, other signals.
    plain = _result()
    assert manager.classify_result(plain, reservation) is plain
    cancelled = _result(reason=REASON_CANCELLED)
    assert manager.classify_result(cancelled, reservation) is cancelled
    sigsegv = _result(term_signal=11)
    assert manager.classify_result(sigsegv, reservation).reason_code == REASON_EXITED
    # Non-interference: a SIGKILL with NO cpu rlimit applied (e.g. an external
    # kill) stays a plain exit - the attribution is gated on the CPU mechanism,
    # never on "any SIGKILL".
    no_cpu = LocalSandboxProvider(
        probes={CAP_CPU_GROUP: lambda: "unsupported", CAP_CPU_RLIMIT: lambda: "unsupported"}
    )
    reservation_no_cpu = _reservation(
        resolutions=resolve_support(no_cpu.support_matrix(), enforcement_required=False)
    )
    assert (
        manager.classify_result(_result(term_signal=9), reservation_no_cpu).reason_code
        == REASON_EXITED
    )
    # A Supervisor-initiated SIGKILL never reaches classify_result as EXITED
    # (its reason is CANCELLED/WALL_TIMEOUT/...), so it is never misattributed.
    assert (
        manager.classify_result(
            _result(term_signal=9, reason=REASON_CANCELLED), reservation_cpu
        ).reason_code
        == REASON_CANCELLED
    )


def test_sampling_excess_decisions_pid_and_disk():
    manager = ResourceManager(_RecordingProvider(), sample_interval_seconds=0.1)
    reservation = _reservation()

    excess = manager.excess(_sample(process_count=17), _policy(max_processes=16), reservation)
    assert excess is not None and excess.dimension == "pid"
    assert excess.reason_code == REASON_RESOURCE_EXCEEDED
    assert f"{CAP_PID_COUNT}:approximate" == excess.mechanism

    excess = manager.excess(
        _sample(process_count=1, workdir_bytes=70_000_000, workdir_files=3),
        _policy(workdir_total_bytes=67_108_864),
        reservation,
    )
    assert excess is not None and excess.dimension == "disk"
    assert excess.reason_code == REASON_RESOURCE_EXCEEDED
    assert f"{CAP_DISK_ACCOUNTING}:approximate" == excess.mechanism

    # no-data sampling never accuses (count zero cannot exceed a positive
    # bound); the cpu dimension is NOT reactively enforceable when the chosen
    # mechanism is the rlimit approximation (kernel's job, not the sampler's).
    assert manager.excess(_sample(process_count=0), _policy(), reservation) is None
    assert (
        manager.excess(
            _sample(cpu_seconds=999),
            _policy(cpu_seconds=1),
            reservation,
        )
        is None
    )


def test_workdir_accountant_integration():
    manager = ResourceManager(_RecordingProvider(), sample_interval_seconds=0.05)

    def accountant():
        return WorkdirUsage(total_bytes=1234, file_count=7)

    sample = asyncio.run(manager.observe(1, workdir_accountant=accountant))
    assert sample.workdir_bytes == 1234
    assert sample.workdir_files == 7


def test_watch_returns_first_excess_and_alerts():
    alerts = []
    manager = ResourceManager(
        _RecordingProvider(),
        sample_interval_seconds=0.01,
        group_observer=lambda pgid: (9, 1024, 0.0),
        alert=lambda excess: alerts.append(excess),
    )
    reservation = _reservation()

    async def flow():
        done = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(
            manager.watch(1, _policy(max_processes=4), reservation, until=done)
        )
        decision = await task
        done.set_result(None)
        return decision

    decision = asyncio.run(flow())
    assert decision is not None and decision.dimension == "pid"
    assert len(alerts) == 1


# ---------------------------------------------------------------------------
# Host gate integration (P4-IT-23 macOS column, provider-independence pins)
# ---------------------------------------------------------------------------


def _host(engine, *, sandbox=None, resources=None, host_id="worker-sandbox", boot="boot-1"):
    return RuntimeHost(
        enabled=True,
        host_id=host_id,
        runner=ProcessRunner(build_trusted_registry()),
        supervisor=ProcessSupervisor(cancel_grace_seconds=0.3, kill_timeout_seconds=0.3),
        registry=(
            ProcessRegistry(engine, host_id=host_id, host_instance_id=boot)
            if engine is not None
            else None
        ),
        wall_timeout_seconds=30,
        sandbox_provider=sandbox,
        resource_manager=resources,
    )


def test_support_unsupported_refuses_before_record_or_spawn():
    # enforcement_required=true on a provider whose full memory ladder is
    # unsupported: admission refuses. engine=None would explode on any DB
    # contact, so the clean raise proves zero side effects (P4-IT-23
    # measurable column).
    provider = LocalSandboxProvider(
        enforcement_required=True,
        probes={CAP_MEMORY_RLIMIT: lambda: "unsupported"},
    )
    host = _host(None, sandbox=provider)
    with pytest.raises(HostStartError) as excinfo:
        asyncio.run(
            host.start(
                make_spec("exit", "0"),
                run_id=uuid.uuid4(),
                tenant_id=TENANT,
                working_dir=Path("/tmp"),
            )
        )
    assert excinfo.value.code == REASON_SUPPORT_UNSUPPORTED


def test_enforcement_decision_matches_address_space_applicability():
    # enforcement_required=true must be exactly the probe's verdict: refuse
    # when no memory mechanism can be applied on this host, admit with the
    # approximate label where it can (P4-IT-23 macOS column consistency).
    provider = LocalSandboxProvider(enforcement_required=True)
    applicable = sandbox_provider.probe_address_space_rlimit() == "approximate"
    if applicable:
        reservation = asyncio.run(provider.prepare(make_spec("exit", "0"), run_id=uuid.uuid4()))
        memory = next(r for r in reservation.resolutions if r.dimension == "memory")
        assert memory.strength == "approximate"
    else:
        with pytest.raises(SandboxPolicyError) as excinfo:
            asyncio.run(provider.prepare(make_spec("exit", "0"), run_id=uuid.uuid4()))
        assert excinfo.value.code == REASON_SUPPORT_UNSUPPORTED


def test_host_module_never_references_a_concrete_provider():
    # P4-IT-24 static half: the Host speaks only the Protocol; swapping the
    # Provider cannot require a Host edit.
    source = Path(host_module.__file__).read_text()
    assert "LocalSandbox" not in source
    assert "Recording" not in source
    assert isinstance(LocalSandboxProvider(), sandbox_provider.SandboxProvider)
    assert isinstance(_RecordingProvider(), sandbox_provider.SandboxProvider)


# ---------------------------------------------------------------------------
# PG-backed end-to-end with the Local Provider (T12 measurable halves)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sandbox_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    name = "phase4_sandbox_" + uuid.uuid4().hex

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


def _drive(url, flow):
    async def main():
        from agent_platform.core_platform.platform_services.persistence.database import (
            create_engine,
        )
        from agent_platform.core_platform.platform_services.platform_settings.settings import (
            Settings,
        )

        settings = Settings(
            _env_file=None,
            database_url=url.replace("postgresql://", "postgresql+asyncpg://"),
            tenant_id=TENANT,
            embedded_worker=False,
        )
        engine = create_engine(settings)
        try:
            await flow(engine)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _make_run(engine):
    from agent_platform.applications.platform_runtime.runtime_hooks import (
        BusinessRuntimePersistenceHooks,
    )
    from agent_platform.core_platform.agent_runtime.repository import RunRepository
    from agent_platform.core_platform.agent_runtime.schemas import RunRequest

    repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    row = await repo.submit(
        TENANT,
        RunRequest(conversation_id=f"conv-{uuid.uuid4()}", message="sandbox test"),
        {"fingerprint": "phase4-sandbox"},
        100,
        100,
        120,
    )
    return uuid.UUID(str(row["id"]))


@pytest.mark.postgres
def test_local_provider_end_to_end_admits_applies_releases(sandbox_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        resources = ResourceManager(
            LocalSandboxProvider(enforcement_required=False),
            sample_interval_seconds=0.2,
        )
        host = _host(engine, resources=resources, host_id="worker-e2e")
        run_id = await _make_run(engine)
        managed = await host.start(
            make_spec("exit", "0"), run_id=run_id, tenant_id=TENANT, working_dir=root
        )
        result = await host.wait(managed.managed_id)
        assert result.final_state == "exited"
        assert result.reason_code == REASON_EXITED  # plain exit not relabeled
        assert managed.managed_id not in host._tracked
        row = await host.registry.fetch_one(managed.managed_id)
        assert row is not None and row.managed.state == "exited"

    _drive(sandbox_database, flow)


@pytest.mark.postgres
def test_rlimit_cpu_excess_classifies_and_terminates(sandbox_database, tmp_path):
    # P4-IT-19 CPU-approximation half. The applied RLIMIT_CPU (soft==hard)
    # kills the busy child; the Host must record the STABLE resource reason on
    # every platform (08 R-14: the reason code is the contract, the raw signal
    # is only a platform observation detail). The kernel path differs:
    #   - macOS: soft limit raises SIGXCPU(24), default disposition terminates.
    #   - Linux: soft==hard means the hard limit is reached in the same tick,
    #     so the kernel delivers SIGKILL(9) instead of a catchable SIGXCPU.
    # Both are the CPU rlimit doing its job; classify_result attributes the
    # Linux SIGKILL from the Reservation's recorded cpu_rlimit fact (never from
    # the signal number), so the reason code is identical cross-platform.
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        provider = LocalSandboxProvider(enforcement_required=False)
        resources = ResourceManager(provider, sample_interval_seconds=0.2)
        host = _host(engine, resources=resources, host_id="worker-cpu")
        run_id = await _make_run(engine)
        spec = make_spec("cpu-burn", "30")
        spec = spec.model_copy(
            update={"resource_policy": spec.resource_policy.model_copy(update={"cpu_seconds": 1})}
        )
        # R-14 mechanism/strength label: the cpu dimension resolved to the
        # cpu_rlimit approximation (never "hard" - hard CPU is the cgroup lane,
        # pending_env). This is the platform-independent evidence that the kill
        # came from the CPU rlimit mechanism.
        reservation = await provider.prepare(spec, run_id=run_id)
        cpu = next(r for r in reservation.resolutions if r.dimension == "cpu")
        assert cpu.capability == CAP_CPU_RLIMIT
        assert cpu.strength == "approximate"

        managed = await host.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=root)
        result = await host.wait(managed.managed_id)
        # Contract: stable excess reason code (both platforms).
        assert result.reason_code == REASON_RESOURCE_EXCEEDED
        # Honest shape: killed by a signal, not a clean exit; the observed
        # signal is one of the two documented kernel paths (SIGXCPU 24 on
        # macOS, SIGKILL 9 on Linux) - asserted as a set, never a single
        # platform's number, per R-14.
        assert result.final_state == "exited"
        assert result.term_signal in (24, 9)
        assert not process_alive(managed.os_pid)
        row = await host.registry.fetch_one(managed.managed_id)
        assert row is not None
        assert row.managed.state == "exited"

    _drive(sandbox_database, flow)


@pytest.mark.postgres
def test_rlimit_fsize_excess_classifies_and_terminates(sandbox_database, tmp_path):
    # P4-IT-21 per-file half: RLIMIT_FSIZE trips SIGXFSZ while the trusted
    # target writes past the bound; the observation stays inside the Run
    # directory and the excess is recorded with the stable code.
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        resources = ResourceManager(
            LocalSandboxProvider(enforcement_required=False),
            sample_interval_seconds=0.2,
        )
        host = _host(engine, resources=resources, host_id="worker-fsize")
        run_id = await _make_run(engine)
        spec = make_spec("alloc-write", "16777216")
        spec = spec.model_copy(
            update={
                "resource_policy": spec.resource_policy.model_copy(
                    update={"workdir_file_bytes": 16_384}
                )
            }
        )
        managed = await host.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=root)
        result = await host.wait(managed.managed_id)
        # The trusted target normalizes SIGXFSZ/EFBIG into exit 86; either
        # way the resource lane reports the stable excess reason.
        assert result.exit_code == 86 or result.term_signal == 25
        assert result.reason_code == REASON_RESOURCE_EXCEEDED
        assert b"resource-exceeded=fsize" in result.stderr
        assert not process_alive(managed.os_pid)

    _drive(sandbox_database, flow)


@pytest.mark.postgres
def test_sampling_observes_real_group_and_excess_wires_to_supervisor(sandbox_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        provider = LocalSandboxProvider(enforcement_required=False)
        host = _host(engine, sandbox=provider, host_id="worker-sampling")
        run_id = await _make_run(engine)
        managed = await host.start(
            make_spec("sleep", "30"), run_id=run_id, tenant_id=TENANT, working_dir=root
        )

        resources = ResourceManager(
            provider,
            sample_interval_seconds=0.2,
            group_observer=default_group_observer,
        )
        sample = await resources.observe(managed.process_group_id)
        assert sample.process_count >= 1
        assert sample.rss_bytes > 0

        # A ceiling below the observed count lands the reactive pid decision,
        # and the same supervisor machine then clears the group (P4-UT-15
        # reactive half; the cgroup hard ceiling remains pending_env).
        # max_processes is bounded gt=0 in the DTO, so the accusation uses a
        # count strictly above the smallest legal ceiling.
        reservation = _reservation()
        observed_over_ceiling = _sample(
            process_count=max(sample.process_count, 1) + 1, rss_bytes=sample.rss_bytes
        )
        excess = resources.excess(observed_over_ceiling, _policy(max_processes=1), reservation)
        assert excess is not None and excess.dimension == "pid"

        result = await host.cancel(managed.managed_id)
        assert result.final_state == "exited"
        assert not process_alive(managed.os_pid)

    _drive(sandbox_database, flow)


@pytest.mark.postgres
def test_child_group_membership_probe(sandbox_database, tmp_path):
    # P4-IT-05 foundation: descendants share the session group the Supervisor
    # signals, verified from inside the trusted target itself.
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        host = _host(engine, host_id="worker-group")
        run_id = await _make_run(engine)
        managed = await host.start(
            make_spec("child-group-probe"), run_id=run_id, tenant_id=TENANT, working_dir=root
        )
        result = await host.wait(managed.managed_id)
        assert result.final_state == "exited"
        assert b"group-match=1" in result.stdout

    _drive(sandbox_database, flow)


@pytest.mark.postgres
def test_provider_swap_needs_no_host_or_adapter_change(sandbox_database, tmp_path):
    # P4-IT-24: the recording substitute (different id/version, no rlimits)
    # drives the same RuntimeHost code the Local Provider drives.
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        substitute = _RecordingProvider()
        host = _host(engine, sandbox=substitute, host_id="worker-swap")
        run_id = await _make_run(engine)
        managed = await host.start(
            make_spec("exit", "0"), run_id=run_id, tenant_id=TENANT, working_dir=root
        )
        result = await host.wait(managed.managed_id)
        assert result.final_state == "exited"
        assert substitute.calls["prepare"] == 1
        assert substitute.calls["release"] == 1

        resources = ResourceManager(
            LocalSandboxProvider(enforcement_required=False), sample_interval_seconds=0.2
        )
        host2 = _host(engine, resources=resources, host_id="worker-swap")
        run_id = await _make_run(engine)
        managed = await host2.start(
            make_spec("exit", "0"), run_id=run_id, tenant_id=TENANT, working_dir=root
        )
        assert (await host2.wait(managed.managed_id)).final_state == "exited"

    _drive(sandbox_database, flow)


# ---------------------------------------------------------------------------
# pending_env attribution (08 R-3): never reported as pass on this host
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    True,
    reason="pending_env (08 R-3): cgroup v2 memory.max per-Execution hard "
    "limit needs the dedicated Linux full-acceptance environment",
)
def test_cgroup_memory_hard_limit_full_acceptance():  # pragma: no cover
    raise AssertionError("must not run outside the cgroup v2 environment")


@pytest.mark.skipif(
    True,
    reason="pending_env (08 R-3): cgroup v2 pids.max per-Execution hard "
    "limit needs the dedicated Linux full-acceptance environment",
)
def test_cgroup_pids_hard_limit_full_acceptance():  # pragma: no cover
    raise AssertionError("must not run outside the cgroup v2 environment")


@pytest.mark.skipif(
    True,
    reason="pending_env (08 R-3): filesystem/project quota enforcement needs "
    "the dedicated Linux full-acceptance environment",
)
def test_fs_quota_total_enforcement_full_acceptance():  # pragma: no cover
    raise AssertionError("must not run outside the quota environment")
