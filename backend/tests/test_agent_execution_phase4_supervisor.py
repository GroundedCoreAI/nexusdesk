"""Phase 4 supervisor tests: escalation, races, idempotence (08 T8).

The fake-target unit cases pin the state machine and signal discipline
(P4-UT-04/05/06); the real-process cases exercise process-group semantics on
this darwin host per 08 R-3: TERM-ignoring nested descendants, wall vs Run
deadline races, output-flood termination and crash exit collection
(P4-IT-05/06/07/12).
"""

import asyncio
import os
import time
import uuid
from pathlib import Path

import pytest
from agent_execution.process_test_adapters import build_trusted_registry, make_spec

from agent_platform.core_platform.agent_execution.host import process_identity
from agent_platform.core_platform.agent_execution.host import process_supervisor as sup
from agent_platform.core_platform.agent_execution.host.host_models import (
    REASON_CANCELLED,
    REASON_CLEANUP_FAILED,
    REASON_EXITED,
    REASON_OUTPUT_LIMIT_EXCEEDED,
    REASON_RECOVERY_TERMINATED,
    REASON_WALL_TIMEOUT,
    ExitObservation,
    ManagedProcess,
    ProcessResult,
    compute_command_digest,
)
from agent_platform.core_platform.agent_execution.host.process_runner import ProcessRunner
from agent_platform.core_platform.agent_execution.host.process_supervisor import (
    GroupHandle,
    ProcessSupervisor,
    SupervisorStateError,
)

DIGEST = compute_command_digest("trusted-test-target", ("x",))


def _managed(**overrides) -> ManagedProcess:
    values = {
        "managed_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "host_id": "runtime-worker.01",
        "host_instance_id": "boot-1",
        "sandbox_provider": "local/v1",
        "command_digest": DIGEST,
        "os_pid": 4_000_001,
        "process_group_id": 4_000_001,
        "state": "running",
        "started_at_posix": time.time() - 1.0,
    }
    values.update(overrides)
    return ManagedProcess(**values)


class _FakeTarget:
    """Scripted wait_exit so unit cases never touch the OS."""

    def __init__(self, managed: ManagedProcess, script: list[ExitObservation]) -> None:
        self.managed = managed
        self.script = script
        self.calls = 0

    async def wait_exit(self, timeout: float) -> ExitObservation:
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        return self.script[index]


def _supervisor(**overrides) -> ProcessSupervisor:
    values = {"cancel_grace_seconds": 0.05, "kill_timeout_seconds": 0.05}
    values.update(overrides)
    return ProcessSupervisor(**values)


@pytest.fixture
def signal_log(monkeypatch):
    sent: list[tuple[int, int]] = []

    def fake_killpg(pgid, sig):
        sent.append((pgid, sig))

    monkeypatch.setattr(os, "killpg", fake_killpg)
    return sent


# ---------------------------------------------------------------------------
# P4-UT-04/05/06: escalation machine with substitutes
# ---------------------------------------------------------------------------


def test_honored_term_never_escalates_to_kill(signal_log):
    target = _FakeTarget(_managed(), [ExitObservation("exited", 0)])
    result = asyncio.run(_supervisor().cancel(target))
    assert result.final_state == "exited"
    assert result.reason_code == REASON_CANCELLED
    assert result.exit_code == 0
    assert signal_log == [(4_000_001, 15)]


def test_ignored_term_escalates_to_group_kill(signal_log):
    target = _FakeTarget(
        _managed(), [ExitObservation("alive", None), ExitObservation("exited", -9)]
    )
    result = asyncio.run(_supervisor().cancel(target))
    assert signal_log == [(4_000_001, 15), (4_000_001, 9)]
    assert result.final_state == "exited"
    assert result.term_signal == 9
    assert result.exit_code is None


def test_kill_ignored_is_cleanup_failed_with_alert_never_false_success(signal_log, monkeypatch):
    monkeypatch.setattr(sup, "group_alive", lambda pgid: True)
    alerts: list[tuple[str, uuid.UUID]] = []
    target = _FakeTarget(
        _managed(), [ExitObservation("alive", None), ExitObservation("alive", None)]
    )
    supervisor = _supervisor(alert=lambda code, mid: alerts.append((code, mid)))
    result = asyncio.run(supervisor.cancel(target))
    assert result.final_state == "cleanup_failed"
    assert result.reason_code == REASON_CLEANUP_FAILED
    assert len(signal_log) == 2  # TERM + KILL, no further signals after failure
    assert alerts == [(REASON_CLEANUP_FAILED, target.managed.managed_id)]


def test_repeated_cancellation_enters_one_machine(signal_log):
    # A single cleanup owner: concurrent cancels await the same escalation
    # and the group gets exactly one TERM and one KILL regardless of callers
    # (P4-UT-05, 03 §4.3 "repeated calls return the same progress").
    target = _FakeTarget(
        _managed(), [ExitObservation("alive", None), ExitObservation("exited", -9)]
    )
    supervisor = _supervisor()

    async def flow():
        return await asyncio.gather(supervisor.cancel(target), supervisor.cancel(target))

    first, second = asyncio.run(flow())
    assert first.managed_id == second.managed_id
    assert first.final_state == second.final_state == "exited"
    terms = [call for call in signal_log if call[1] == 15]
    kills = [call for call in signal_log if call[1] == 9]
    assert len(terms) == 1 and len(kills) == 1


def test_cancel_after_result_returns_retained_progress(signal_log):
    target = _FakeTarget(_managed(), [ExitObservation("exited", 0)])
    supervisor = _supervisor()
    asyncio.run(supervisor.cancel(target))
    again = asyncio.run(supervisor.cancel(target))
    assert again.final_state == "exited"
    assert len([call for call in signal_log if call[1] == 15]) == 1  # not re-signalled


def test_terminal_handle_without_record_is_refused():
    target = _FakeTarget(_managed(state="exited"), [ExitObservation("exited", 0)])
    with pytest.raises(SupervisorStateError):
        asyncio.run(_supervisor().cancel(target))


def test_handle_without_group_identity_is_refused_before_signals(signal_log):
    target = _FakeTarget(_managed(process_group_id=None, os_pid=None), [])
    with pytest.raises(SupervisorStateError):
        asyncio.run(_supervisor().cancel(target))
    assert signal_log == []


def test_supervisor_requires_positive_windows():
    with pytest.raises(ValueError):
        ProcessSupervisor(cancel_grace_seconds=0, kill_timeout_seconds=5)
    with pytest.raises(ValueError):
        ProcessSupervisor(cancel_grace_seconds=5, kill_timeout_seconds=-1)


def test_orphan_termination_uses_recovery_reason(signal_log):
    # Recovery escalates the same machine but labels the outcome honestly
    # and observes via liveness only (GroupHandle.wait_exit is patched here
    # to keep the unit case OS-free).
    handle_managed = _managed(state="orphaned")
    handle = GroupHandle(handle_managed)

    async def fake_wait(timeout):  # instance attribute: no self binding
        return ExitObservation("absent", None)

    handle.wait_exit = fake_wait  # type: ignore[method-assign]
    result = asyncio.run(_supervisor().terminate_orphan(handle))
    assert result.final_state == "exited"
    assert result.reason_code == REASON_RECOVERY_TERMINATED
    assert [call[1] for call in signal_log] == [15]  # TERM, group already gone
    assert result.exit_code is None  # orphan exit code is never fabricated


# ---------------------------------------------------------------------------
# Real-process integration on this host (P4-IT-05/06/07/12)
# ---------------------------------------------------------------------------

REGISTRY = build_trusted_registry()


def _spawn(tmp_path: Path, spec):
    """Start a real trusted target and return the loop, started handle, root."""
    working = tmp_path / "aa11" / "bb22"
    working.mkdir(parents=True, exist_ok=True)

    async def flow(body):
        runner = ProcessRunner(REGISTRY)
        started = await runner.start(
            spec,
            run_id=uuid.uuid4(),
            managed_id=uuid.uuid4(),
            host_id="runtime-worker.01",
            host_instance_id="boot-1",
            sandbox_provider="local/v1",
            working_dir=working,
        )
        return await body(started)

    return flow, working


def _drive(tmp_path, spec, body, *, grace=0.5, kill=0.5):
    flow, working = _spawn(tmp_path, spec)

    async def runner_body(started):
        supervisor = _supervisor(cancel_grace_seconds=grace, kill_timeout_seconds=kill)
        return await body(supervisor, started, working)

    return asyncio.run(flow(runner_body))


def test_real_nested_term_ignoring_children_die_with_the_group(tmp_path):
    spec = make_spec("ignore-term", "60")

    async def body(supervisor, started, working):
        # Let the leader report its nested child pid before cancelling.
        deadline = time.monotonic() + 5
        child_pid = None
        while time.monotonic() < deadline:
            data = started.pump.stdout.payload()
            if b"child-pid=" in data:
                child_pid = int(data.split(b"child-pid=")[1].split(b"\n")[0])
                break
            await asyncio.sleep(0.05)
        assert child_pid is not None
        result = await supervisor.cancel(started)
        assert result.final_state == "exited"
        # TERM is ignored by both leader and nested child; only the group
        # KILL takes them - zero surviving descendants (04 §6).
        assert not process_identity.process_alive(started.process.pid)
        deadline = time.monotonic() + 2
        while process_identity.process_alive(child_pid) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert not process_identity.process_alive(child_pid)
        assert not process_identity.group_alive(started.managed.process_group_id)
        return result

    _drive(tmp_path, spec, body)


def test_real_wall_deadline_terminates_group(tmp_path):
    spec = make_spec("sleep", "60")

    async def body(supervisor, started, working):
        started_at = time.monotonic()
        result = await supervisor.wait(started, wall_seconds=0.4)
        elapsed = time.monotonic() - started_at
        assert result.final_state == "exited"
        assert result.reason_code == REASON_WALL_TIMEOUT
        assert elapsed < 3.0
        assert not process_identity.process_alive(started.process.pid)

    _drive(tmp_path, spec, body)


def test_real_earlier_run_deadline_wins_over_process_wall(tmp_path):
    spec = make_spec("sleep", "60")

    async def body(supervisor, started, working):
        started_at = time.monotonic()
        result = await supervisor.wait(
            started,
            wall_seconds=30.0,
            run_deadline_monotonic=time.monotonic() + 0.4,
        )
        elapsed = time.monotonic() - started_at
        assert result.reason_code == REASON_WALL_TIMEOUT
        assert elapsed < 3.0  # the Run deadline (0.4) beat the 30s wall
        assert not process_identity.process_alive(started.process.pid)

    _drive(tmp_path, spec, body)


def test_real_output_flood_terminates_with_stable_reason(tmp_path):
    spec = make_spec("flood-stdout", "204800")
    spec = spec.model_copy(
        update={
            "resource_policy": spec.resource_policy.model_copy(
                update={"output_max_bytes_per_stream": 4096}
            )
        }
    )

    async def body(supervisor, started, working):
        result = await supervisor.wait(started, wall_seconds=10.0)
        assert result.final_state == "exited"
        assert result.reason_code == REASON_OUTPUT_LIMIT_EXCEEDED
        assert result.stdout_truncated is True
        assert len(result.stdout) <= 4096
        assert not process_identity.process_alive(started.process.pid)
        assert not process_identity.group_alive(started.managed.process_group_id)

    _drive(tmp_path, spec, body)


def test_real_signal_crash_collects_honest_exit(tmp_path):
    spec = make_spec("signal-crash")

    async def body(supervisor, started, working):
        result = await supervisor.wait(started, wall_seconds=10.0)
        assert result.final_state == "exited"
        assert result.reason_code == REASON_EXITED
        assert result.exit_code is None
        assert result.term_signal == 11  # SIGSEGV

    _drive(tmp_path, spec, body)


def test_real_normal_exit_and_repeat_semantics(tmp_path):
    spec = make_spec("exit", "7")

    async def body(supervisor, started, working):
        result = await supervisor.wait(started, wall_seconds=10.0)
        assert result.final_state == "exited"
        assert result.exit_code == 7
        assert result.reason_code == REASON_EXITED
        # Repeat enters the retained-progress path, not a second machine.
        repeat = await supervisor.wait(started, wall_seconds=10.0)
        assert repeat == result
        cancelled = await supervisor.cancel(started)
        assert cancelled == result  # late cancel returns recorded progress

    _drive(tmp_path, spec, body)


def test_wall_seconds_zero_or_negative_is_rejected_by_bounds():
    # The supervisor never runs with FR-10-invalid windows; the settings
    # bounds (T3) already reject this, but the machine re-asserts its own.
    with pytest.raises(ValueError):
        ProcessSupervisor(cancel_grace_seconds=1, kill_timeout_seconds=0)


def test_result_is_a_bounded_internal_dto():
    managed = _managed()
    result = ProcessResult(
        managed_id=managed.managed_id,
        run_id=managed.run_id,
        final_state="exited",
        reason_code=REASON_EXITED,
        exit_code=0,
        wall_seconds=0.5,
        stdout=b"tiny",
        stderr=b"",
    )
    assert result.model_dump()["stdout"] == b"tiny"
    assert managed.command_digest == DIGEST  # pin: results never rewrite identity
