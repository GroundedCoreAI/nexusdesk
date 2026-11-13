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
