"""Phase 4 Runtime Host internals: process DTOs and the process state machine (08 T4).

The models section pins the internal-only surface: strict extra-forbid DTOs, the
monotone process state machine shared with ``runtime_host_processes.status``,
the single-source command digest (08 R-6) used later by the Runner and the
Registry, and the rule that none of these types leaks into the public contracts
module (02 FR-1 output row, 03 §4.1).

Runner spawn/IO cases (P4-UT-02/03/20) arrive with T7 and extend this file.
"""

import re
import typing
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_platform.core_platform.agent_execution import host
from agent_platform.core_platform.agent_execution.contracts import base as contracts_base
from agent_platform.core_platform.agent_execution.contracts.base import ExecutionContractModel
from agent_platform.core_platform.agent_execution.host import host_models
from agent_platform.core_platform.agent_execution.host.host_models import (
    HOST_REASON_CODES,
    PROCESS_STATE_TRANSITIONS,
    TERMINAL_PROCESS_STATES,
    HostHealth,
    HostReasonCode,
    ManagedProcess,
    ProcessResult,
    ProcessSpec,
    ProcessState,
    ProcessStateTransitionError,
    ResourcePolicy,
    compute_command_digest,
)

ALL_STATES = [
    "starting",
    "running",
    "terminating",
    "exited",
    "orphaned",
    "cleanup_failed",
]


def _policy(**overrides) -> ResourcePolicy:
    values = {
        "cpu_seconds": 600,
        "memory_bytes": 536_870_912,
        "max_processes": 64,
        "workdir_total_bytes": 1_073_741_824,
        "workdir_file_bytes": 134_217_728,
        "wall_seconds": 900,
        "output_max_bytes_per_stream": 1_048_576,
    }
    values.update(overrides)
    return ResourcePolicy(**values)


def _spec(**overrides) -> ProcessSpec:
    values = {
        "executable_id": "trusted-test-target",
        "argv": ("--mode", "echo"),
        "environment": {"PATH": "/usr/bin:/bin"},
        "workdir_relative_path": "aa11/550e8400-e29b-41d4-a716-446655440000",
        "resource_policy": _policy(),
    }
    values.update(overrides)
    return ProcessSpec(**values)


def _process(**overrides) -> ManagedProcess:
    values = {
        "managed_id": uuid4(),
        "run_id": uuid4(),
        "host_id": "runtime-worker.01",
        "host_instance_id": "boot-instance-1",
        "sandbox_provider": "local/v1",
        "command_digest": compute_command_digest("trusted-test-target", ("--mode", "echo")),
    }
    values.update(overrides)
    return ManagedProcess(**values)


# ---------------------------------------------------------------------------
# Internal surface discipline (02 FR-1, 03 §4.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "type_name",
    [
        "ProcessSpec",
        "ResourcePolicy",
        "ManagedProcess",
        "ProcessResult",
        "HostHealth",
        "ProcessState",
        "HostReasonCode",
    ],
)
def test_host_models_never_join_the_public_contracts_surface(type_name):
    import agent_platform.core_platform.agent_execution.contracts as public_contracts

    assert not hasattr(public_contracts, type_name)
    assert not hasattr(contracts_base, type_name)
    # Defined in the internal package only.
    assert hasattr(host_models, type_name)


def test_host_models_share_the_execution_contract_discipline():
    # Same strictness as the public DTOs without joining their module (T4):
    # extra=forbid + frozen + strict come from ExecutionContractModel.
    for model in (ProcessSpec, ResourcePolicy, ManagedProcess, ProcessResult, HostHealth):
        assert issubclass(model, ExecutionContractModel)
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["frozen"] is True
        assert model.model_config["strict"] is True


def test_process_spec_rejects_extra_fields_and_invalid_shapes():
    with pytest.raises(ValidationError):
        _spec(command="/bin/sh")
    with pytest.raises(ValidationError):
        _spec(executable_id="../escape")
    with pytest.raises(ValidationError):
        _spec(executable_id="Trusted-Target")
    with pytest.raises(ValidationError):
        _spec(environment={"BAD KEY": "x"})
    # Strict mode keeps sloppy coercions out of internal plumbing.
    with pytest.raises(ValidationError):
        _spec(workdir_relative_path="")
    with pytest.raises(ValidationError):
        _policy(wall_seconds=0)
    with pytest.raises(ValidationError):
        _policy(memory_bytes=-1)


# ---------------------------------------------------------------------------
# Process state machine (03 §3.2/§4.3/§4.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ALL_STATES)
@pytest.mark.parametrize("target", ALL_STATES)
def test_state_machine_accepts_exactly_the_declared_transitions(source, target):
    process = _process(state=source)
    allowed = target in PROCESS_STATE_TRANSITIONS[source]
    if allowed:
        assert process.transition_to(target).state == target
    else:
        with pytest.raises(ProcessStateTransitionError):
            process.transition_to(target)


def test_state_machine_terminals_are_monotone():
    for terminal in TERMINAL_PROCESS_STATES:
        process = _process(state=terminal)
        for target in ALL_STATES:
            with pytest.raises(ProcessStateTransitionError):
                process.transition_to(target)


def test_normal_and_cancelled_lifecycle_walks_the_machine():
    process = _process()
    assert process.state == "starting"
    running = process.transition_to("running").transition_to("terminating")
    assert running.state == "terminating"
    assert running.transition_to("exited").state == "exited"
    # cleanup_failed is never reported as exited (03 §4.3): from the terminal
    # failure state there is no path back into the machine.
    failed = process.transition_to("running").transition_to("cleanup_failed")
    with pytest.raises(ProcessStateTransitionError):
        failed.transition_to("exited")


def test_recovery_orphan_path_only_through_the_same_machine():
    # 03 §4.4: match -> orphaned -> TERM/KILL -> exited; mismatch ->
    # cleanup_failed. Orphans never re-enter "running".
    orphaned = _process(state="running").transition_to("orphaned")
    assert orphaned.transition_to("terminating").state == "terminating"
    assert (
        _process(state="running").transition_to("orphaned").transition_to("cleanup_failed").state
        == "cleanup_failed"
    )
    with pytest.raises(ProcessStateTransitionError):
        orphaned.transition_to("running")


def test_process_state_names_match_the_database_check_constraint():
    # The runtime_host_processes.status CHECK and ManagedProcess.state must not
    # drift (03 §3.2): compare against the migration's own literal list.
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0059_execution_runtime_host.py"
    )
    spec = spec_from_file_location("migration_0059", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    recorder = type(
        "R", (), {"statements": [], "execute": lambda self, s: self.statements.append(s)}
    )()
    module.op = recorder  # type: ignore[attr-defined]
    module.upgrade()
    joined = " ".join(" ".join(statement.split()) for statement in recorder.statements)
    process_check = joined[joined.index("CREATE TABLE runtime_host_processes") :]
    for state in typing.get_args(ProcessState):
        assert f"'{state}'" in process_check


# ---------------------------------------------------------------------------
# Command digest: single source for T7/T9 (08 R-6)
# ---------------------------------------------------------------------------


def test_digest_helper_is_deterministic_and_argv_sensitive():
    digest_a = compute_command_digest("trusted-test-target", ("--mode", "echo"))
    digest_b = compute_command_digest("trusted-test-target", ["--mode", "echo"])
    digest_c = compute_command_digest("trusted-test-target", ("--mode", "cat"))
    digest_d = compute_command_digest("other-target", ("--mode", "echo"))

    assert digest_a == digest_b
    assert digest_a != digest_c
    assert digest_a != digest_d
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest_a)


def test_digest_never_contains_argv_or_environment_text():
    secretish = "token=super-secret-value"
    digest = compute_command_digest("trusted-test-target", (secretish,))
    assert secretish not in digest
    assert secretish.encode().hex() not in digest

    spec = _spec(argv=(secretish,), environment={"SECRET_TOKEN": secretish})
    assert spec.command_digest == digest
    assert secretish not in spec.command_digest


# ---------------------------------------------------------------------------
# Result and health DTOs
# ---------------------------------------------------------------------------


def test_reason_codes_are_stable_low_cardinality_literals():
    literal_members = set(typing.get_args(HostReasonCode))
    assert literal_members == set(HOST_REASON_CODES)
    for code in literal_members:
        assert code.startswith("runtime_host_")
        assert code == code.lower().strip()
        assert not any(character in code for character in "/ \\")


def test_process_result_requires_a_reason_and_final_state():
    result = ProcessResult(
        managed_id=uuid4(),
        run_id=uuid4(),
        final_state="exited",
        reason_code="runtime_host_cancelled",
        exit_code=-15,
        term_signal=15,
        wall_seconds=2.5,
    )
    assert result.final_state == "exited"
    # "cleanup_failed" is a legal final state, "running" is not (FR-3 output row).
    with pytest.raises(ValidationError):
        ProcessResult(
            managed_id=uuid4(),
            run_id=uuid4(),
            final_state="running",
            reason_code="runtime_host_cancelled",
            wall_seconds=2.5,
        )
    with pytest.raises(ValidationError):
        ProcessResult(
            managed_id=uuid4(),
            run_id=uuid4(),
            final_state="exited",
            reason_code="some_unknown_reason",
            wall_seconds=2.5,
        )
    with pytest.raises(ValidationError):
        ProcessResult(
            managed_id=uuid4(),
            run_id=uuid4(),
            final_state="exited",
            reason_code="runtime_host_cancelled",
            wall_seconds=-1,
        )


def test_host_health_counts_are_bounded_and_active_count_is_derived():
    health = HostHealth(
        host_id="runtime-worker.01",
        host_instance_id="boot-instance-1",
        sandbox_provider="local/v1",
        admission_enabled=True,
        resource_enforcement_required=True,
        starting_count=1,
        running_count=2,
        terminating_count=3,
        orphaned_count=4,
        cleanup_failed_count=5,
        workdir_cleanup_failed_count=6,
        last_reconcile_age_seconds=1.5,
    )
    assert health.active_count == 10
    with pytest.raises(ValidationError):
        HostHealth(
            host_id="runtime-worker.01",
            host_instance_id="boot-instance-1",
            sandbox_provider="local/v1",
            admission_enabled=False,
            resource_enforcement_required=False,
            running_count=-1,
        )


def test_managed_process_os_identity_is_unset_by_default_and_bounded():
    # 08 R-4: OS identity exists only on ManagedProcess and starts unknown;
    # the Runner (T7) fills it at spawn time.
    process = _process()
    assert process.os_pid is None
    assert process.process_group_id is None
    assert process.start_token is None
    with pytest.raises(ValidationError):
        _process(os_pid=0)
    with pytest.raises(ValidationError):
        _process(process_group_id=-7)


def test_host_package_is_importable_and_internal():
    assert host.__name__.endswith("agent_execution.host")
    assert host.__doc__ is not None


# ---------------------------------------------------------------------------
# T7: start identity, allowlist gate, real spawn and bounded I/O
# (P4-UT-02/03/20/21 + P4-IT-02/03/04, measurable on darwin per 08 R-3)
# ---------------------------------------------------------------------------

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from agent_execution.process_test_adapters import (
    TRUSTED_TARGET_PATH,
    build_trusted_registry,
    make_spec,
)

from agent_platform.core_platform.agent_execution.host import (
    process_identity,
    process_runner,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    REASON_UNTRUSTED_TARGET,
)
from agent_platform.core_platform.agent_execution.host.process_runner import (
    ProcessRunner,
    UntrustedTargetError,
)

REGISTRY = build_trusted_registry()


def _runner(**overrides):
    return ProcessRunner(REGISTRY, **overrides)


def _workdir(tmp_path: Path) -> Path:
    working = tmp_path / "aa11" / "bb22"
    working.mkdir(parents=True, exist_ok=True)
    return working


# ---------------------------------------------------------------------------
# Identity probes (08 R-6)
# ---------------------------------------------------------------------------


def test_linux_token_parser_reads_starttime_and_cmdline_digest(monkeypatch):
    stat_body = (
        b"123 (python) S 1 123 123 0 -1 0 4194304 100 0 0 0 5 5 20 0 1 0 0 "
        b"987654321 12345678 9999999 18446744073709551615 0 0 0 0"
    )
    cmdline = b"/usr/bin/python\x00-m\x00trusted_targets\x00exit\x000\x00"

    class _FakeFile:
        def __init__(self, payload: bytes):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._payload

    def fake_open(path, *args, **kwargs):
        return _FakeFile(stat_body if str(path).endswith("/stat") else cmdline)

    monkeypatch.setattr("builtins.open", fake_open)
    import hashlib

    expected_digest = hashlib.sha256(cmdline).hexdigest()[:16]
    # starttime is /proc field 22, index 19 of the tokens after ")".
    token = process_identity._linux_token(123)
    assert token == f"linux:987654321:{expected_digest}"


def test_identity_matches_is_fail_closed():
    assert process_identity.identity_matches("macos:x", "macos:x")
    assert not process_identity.identity_matches("macos:x", "macos:y")
    assert not process_identity.identity_matches(None, "macos:y")
    assert not process_identity.identity_matches("macos:x", None)
    assert not process_identity.identity_matches(None, None)


def test_start_token_capture_is_platform_honest():
    token = process_identity.capture_start_token(os.getpid())
    if sys.platform.startswith("linux"):
        assert token is None or token.startswith("linux:")
    elif sys.platform == "darwin":
        # The macOS dev-subset probe is best-effort (08 R-6): either a
        # parsable token or None, never a fabricated value.
        assert token is None or token.startswith("macos:")
    else:  # pragma: no cover - unsupported platforms fail closed
        assert token is None


def test_probe_of_a_dead_pid_returns_none():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert process_identity.capture_start_token(proc.pid) is None


def test_group_and_process_liveness_probes():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        assert process_identity.process_alive(proc.pid)
        pgid = process_identity.read_pgid(proc.pid)
        assert pgid is not None
        assert process_identity.group_alive(pgid)
    finally:
        proc.kill()
        proc.wait()
    assert not process_identity.process_alive(proc.pid)


# ---------------------------------------------------------------------------
# Allowlist gate before spawn (P4-UT-02)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        (TRUSTED_TARGET_PATH, "exit", "0"),
        (TRUSTED_TARGET_PATH, "sleep", "30"),
        (TRUSTED_TARGET_PATH, "json-events"),
    ],
)
def test_registry_accepts_the_fixed_target_and_bounded_parameters(argv):
    spec = make_spec("exit", "0").model_copy(update={"argv": argv})
    resolved = REGISTRY.resolve(spec)
    assert resolved[0] == sys.executable
    assert resolved[1:] == argv


@pytest.mark.parametrize(
    "argv",
    [
        (),  # empty argv never matches the fixed prefix
        ("/tmp/evil.sh", "exit", "0"),  # caller-supplied executable path
        (TRUSTED_TARGET_PATH, "../escape"),
        (TRUSTED_TARGET_PATH, "exit; rm -rf /"),
        (TRUSTED_TARGET_PATH, "EXIT"),  # uppercase is outside the grammar
        (TRUSTED_TARGET_PATH, "exit", "0", ".."),
        (TRUSTED_TARGET_PATH, "exit", "0") * 10,  # too many parameters
        (TRUSTED_TARGET_PATH, "exit", "a b"),
        (TRUSTED_TARGET_PATH, "exit", "x" * 65),
    ],
)
def test_registry_rejects_unregistered_and_arbitrary_argv(argv):
    spec = make_spec("placeholder").model_copy(update={"argv": argv})
    with pytest.raises(UntrustedTargetError):
        REGISTRY.resolve(spec)


def test_unregistered_executable_id_is_rejected():
    spec = make_spec("exit", "0").model_copy(update={"executable_id": "other-engine"})
    with pytest.raises(UntrustedTargetError):
        REGISTRY.resolve(spec)


def test_host_gate_blocks_before_any_spawn(monkeypatch, tmp_path):
    spawns = {"count": 0}
    real_create = asyncio.create_subprocess_exec

    async def counting_create(*args, **kwargs):
        spawns["count"] += 1
        return await real_create(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", counting_create)
    runner = _runner()
    bad_spec = make_spec("exit", "0").model_copy(update={"argv": ("/bin/sh", "-c", "true")})
    with pytest.raises(UntrustedTargetError):
        asyncio.run(
            runner.start(
                bad_spec,
                run_id=uuid4(),
                managed_id=uuid4(),
                host_id="runtime-worker.01",
                host_instance_id="boot-1",
                sandbox_provider="local/v1",
                working_dir=_workdir(tmp_path),
            )
        )
    assert spawns["count"] == 0  # zero exec attempts, AC-6/P4-UT-02
    assert REASON_UNTRUSTED_TARGET == "runtime_host_untrusted_target"


# ---------------------------------------------------------------------------
# Real spawn, bounded I/O, identity (P4-UT-03/21, P4-IT-02/03/04)
# ---------------------------------------------------------------------------


def _start_and_collect(tmp_path, spec, *, wait_timeout=10):
    """Spawn through the Runner and collect to completion (test helper)."""

    async def flow():
        runner = _runner()
        started = await runner.start(
            spec,
            run_id=uuid4(),
            managed_id=uuid4(),
            host_id="runtime-worker.01",
            host_instance_id="boot-1",
            sandbox_provider="local/v1",
            working_dir=_workdir(tmp_path),
        )
        assert started.managed.state == "running"
        assert started.managed.os_pid == started.process.pid
        assert started.managed.process_group_id == started.process.pid  # own session
        exit_code = await asyncio.wait_for(started.process.wait(), wait_timeout)
        await started.pump.drain(2.0)
        return started, exit_code

    return asyncio.run(flow())


def test_real_spawn_runs_the_trusted_target_in_the_workdir(tmp_path):
    spec = make_spec("workdir-marker", None, workdir_relative="aa11/bb22")
    started, exit_code = _start_and_collect(tmp_path, spec)
    assert exit_code == 0
    marker = _workdir(tmp_path) / "marker.txt"
    assert marker.read_bytes() == b"inside-workdir"
    assert started.managed.command_digest == spec.command_digest


def test_start_identity_and_digest_are_attached_at_spawn(tmp_path):
    spec = make_spec("exit", "0")
    started, exit_code = _start_and_collect(tmp_path, spec)
    assert exit_code == 0
    assert started.managed.start_token is None or ":" in started.managed.start_token
    if sys.platform.startswith("linux"):
        assert started.managed.start_token is not None  # /proc is authoritative there
    assert started.managed.command_digest.startswith("sha256:")


def test_secret_environment_values_never_reach_logs_or_output(tmp_path, caplog):
    secret = "super-secret-value-xyzzy"
    spec = make_spec("env-silent").model_copy(
        update={"environment": {"PATH": "/usr/bin:/bin", "AGENT_TOKEN": secret}}
    )
    with caplog.at_level("DEBUG"):
        started, exit_code = _start_and_collect(tmp_path, spec)
    assert exit_code == 0
    stdout, stderr = started.output()
    assert stdout == b""
    assert stderr == b""
    assert secret not in caplog.text
    assert secret not in str(started.managed)


def test_independent_per_stream_byte_limits_with_backpressure(tmp_path):
    # 200KiB into stdout against a 4KiB bound: the pump stops consuming at
    # the limit (the child blocks on the full pipe), while the independently
    # bounded stderr stays clean - the group must not be killed until the
    # Supervisor decides (tested there), so this case ends with a manual
    # group KILL and zero surviving descendants (04 §6).
    spec = make_spec("flood-stdout", "204800")
    spec = spec.model_copy(
        update={
            "resource_policy": spec.resource_policy.model_copy(
                update={"output_max_bytes_per_stream": 4096}
            )
        }
    )

    async def flow():
        runner = _runner()
        started = await runner.start(
            spec,
            run_id=uuid4(),
            managed_id=uuid4(),
            host_id="runtime-worker.01",
            host_instance_id="boot-1",
            sandbox_provider="local/v1",
            working_dir=_workdir(tmp_path),
        )
        try:
            await asyncio.wait_for(started.pump.stdout.overflowed.wait(), timeout=10)
            assert started.pump.stdout.truncated is True
            assert len(started.pump.stdout.payload()) == 4096
            assert not started.pump.stderr.overflowed.is_set()
            assert started.pump.stderr.payload() == b""
            # The pump stopped retaining bytes; the child stays alive, which
            # is what the Supervisor-side termination is exercised on.
            assert started.process.returncode is None
        finally:
            os.killpg(started.managed.process_group_id, signal.SIGKILL)
            await asyncio.wait_for(started.process.wait(), timeout=10)
            await started.pump.aclose()

    asyncio.run(flow())


# ---------------------------------------------------------------------------
# Reverse-order cleanup on spawn/pipe/registration failure (P4-UT-20)
# ---------------------------------------------------------------------------


def test_spawn_failure_surfaces_when_exec_fails(tmp_path, monkeypatch):
    async def failing_create(*args, **kwargs):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", failing_create)
    runner = _runner()
    with pytest.raises(process_runner.ProcessSpawnError) as excinfo:
        asyncio.run(
            runner.start(
                make_spec("exit", "0"),
                run_id=uuid4(),
                managed_id=uuid4(),
                host_id="runtime-worker.01",
                host_instance_id="boot-1",
                sandbox_provider="local/v1",
                working_dir=_workdir(tmp_path),
            )
        )
    assert excinfo.value.code == "runtime_host_spawn_failed"


def test_pipe_setup_failure_kills_group_and_reaps(tmp_path, monkeypatch):
    # The exec succeeded but the registration step (pump start) fails: the
    # runner must terminate the freshly created group through the same
    # handle and re-validate before surfacing the error.
    captured = {}
    real_pump_start = process_runner.StreamPump.start

    def broken_start(self):
        captured["pid"] = self._process.pid
        raise RuntimeError("pipe setup exploded")

    monkeypatch.setattr(process_runner.StreamPump, "start", broken_start)
    runner = _runner()
    spec = make_spec("sleep", "60")
    with pytest.raises(RuntimeError):
        asyncio.run(
            runner.start(
                spec,
                run_id=uuid4(),
                managed_id=uuid4(),
                host_id="runtime-worker.01",
                host_instance_id="boot-1",
                sandbox_provider="local/v1",
                working_dir=_workdir(tmp_path),
            )
        )
    assert captured["pid"] is not None
    deadline = time.monotonic() + 5
    while process_identity.process_alive(captured["pid"]) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not process_identity.process_alive(captured["pid"])
    assert not process_identity.group_alive(captured["pid"])
    assert real_pump_start is not None  # keep the reference honest
