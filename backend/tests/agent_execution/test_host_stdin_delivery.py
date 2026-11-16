"""Host stdin delivery channel: bounds, ordering and fail-closed cleanup (08 R18).

These cases use the real ``ProcessRunner`` against the repository's trusted test
targets, so they observe a real pipe, a real process group and real EOF. They
are deliberately DB-free: the delivery channel belongs to the Runner, and the
Host-integration consequence is covered by
``test_codex_host_integration.py::test_prompt_is_consumed_from_stdin_end_to_end``.

The target reads stdin *before* doing anything (``stdin-digest``), which is the
whole point: a fixture that ignored stdin would let a payload merely sit in the
64 KiB pipe buffer and look like success.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from agent_execution.process_test_adapters import (
    TRUSTED_EXECUTABLE_ID,
    TRUSTED_TARGET_PATH,
    build_trusted_registry,
)
from agent_platform.core_platform.agent_execution.adapters.codex.events import (
    CodexEventMapper,
    CodexNativeEvent,
)
from agent_platform.core_platform.agent_execution.contracts import ExecutionRequest
from agent_platform.core_platform.agent_execution.host import process_identity
from agent_platform.core_platform.agent_execution.host.host_models import (
    MAX_STDIN_PAYLOAD_BYTES,
    REASON_PIPE_SETUP_FAILED,
    ProcessResult,
    ProcessSpec,
    ResourcePolicy,
    compute_command_digest,
)
from agent_platform.core_platform.agent_execution.host.process_runner import (
    STDIN_DELIVERY_TIMEOUT_SECONDS,
    ProcessRunner,
    ProcessSpawnError,
    StartedProcess,
    TrustedTargetDescriptor,
    TrustedTargetRegistry,
)
from agent_platform.core_platform.agent_execution.host.process_supervisor import (
    ProcessSupervisor,
)

_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=536_870_912,
    max_processes=64,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=1_048_576,
)


def _spec(case: str, parameter: str | None = None, *, payload: bytes | None = None) -> ProcessSpec:
    argv = (
        (TRUSTED_TARGET_PATH, case) if parameter is None else (TRUSTED_TARGET_PATH, case, parameter)
    )
    return ProcessSpec(
        executable_id=TRUSTED_EXECUTABLE_ID,
        argv=argv,
        environment={"PATH": "/usr/bin:/bin"},
        stdin_payload=payload,
        workdir_relative_path="aa11/bb22",
        resource_policy=_POLICY,
    )


def _digest_line(payload: bytes) -> bytes:
    return f"stdin={len(payload)}:{hashlib.sha256(payload).hexdigest()[:16]}".encode()


def _workdir(tmp_path: Path) -> Path:
    working = tmp_path / "aa11" / "bb22"
    working.mkdir(parents=True, exist_ok=True)
    return working


def _runner(
    *, pids: list[int] | None = None, timeout: float = STDIN_DELIVERY_TIMEOUT_SECONDS
) -> ProcessRunner:
    """A real Runner whose identity probe records the spawned pid for cleanup checks."""

    async def capture(pid: int) -> str | None:
        if pids is not None:
            pids.append(pid)
        return "stdin-test-token"

    return ProcessRunner(
        build_trusted_registry(),
        identity_capture=capture,
        stdin_delivery_timeout_seconds=timeout,
    )


def _start(
    runner: ProcessRunner, spec: ProcessSpec, working_dir: Path
) -> Awaitable[StartedProcess]:
    return runner.start(
        spec,
        run_id=uuid4(),
        managed_id=uuid4(),
        host_id="runtime-worker.01",
        host_instance_id="boot-stdin",
        sandbox_provider="local/v1",
        working_dir=working_dir,
    )


def _go(
    runner: ProcessRunner,
    spec: ProcessSpec,
    working_dir: Path,
    *,
    wall_seconds: float = 30,
) -> Awaitable[ProcessResult]:
    """Start, then wait through the supervisor inside one event loop."""

    async def run() -> ProcessResult:
        started = await _start(runner, spec, working_dir)
        supervisor = ProcessSupervisor(cancel_grace_seconds=0.5, kill_timeout_seconds=0.5)
        return await supervisor.wait(started, wall_seconds=wall_seconds)

    return run()


def _group_gone(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_identity.process_alive(pid) and not process_identity.group_alive(pid):
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------------------
# AC-S1: no payload keeps the historical DEVNULL start
# ---------------------------------------------------------------------------


def test_no_payload_keeps_devnull_and_the_child_sees_immediate_eof(tmp_path) -> None:
    spec = _spec("stdin-digest")
    assert spec.stdin_payload is None  # the default is "no channel", not "empty"

    result = asyncio.run(_go(_runner(), spec, _workdir(tmp_path)))
    assert result.reason_code == "runtime_host_exited"
    assert result.exit_code == 0
    assert result.stdout.strip() == _digest_line(b"")


def test_the_default_delivery_timeout_is_positive_and_rejects_nonpositive() -> None:
    assert STDIN_DELIVERY_TIMEOUT_SECONDS == 10.0
    with pytest.raises(ValueError, match="positive"):
        ProcessRunner(build_trusted_registry(), stdin_delivery_timeout_seconds=0)
    with pytest.raises(ValueError, match="positive"):
        ProcessRunner(build_trusted_registry(), stdin_delivery_timeout_seconds=-1)


# ---------------------------------------------------------------------------
# AC-S2: byte-exact delivery of the largest legal payload
# ---------------------------------------------------------------------------


def test_largest_payload_is_delivered_byte_for_byte_within_the_deadline(tmp_path) -> None:
    # The target delays its read by 2s, so the write cannot finish from pipe
    # buffering alone: the payload has to be actively consumed.
    payload = (b"prompt-" * 200_000)[:MAX_STDIN_PAYLOAD_BYTES].ljust(MAX_STDIN_PAYLOAD_BYTES, b"!")
    assert len(payload) == MAX_STDIN_PAYLOAD_BYTES

    started_at = time.monotonic()
    result = asyncio.run(
        _go(_runner(), _spec("stdin-slow-read", "2", payload=payload), _workdir(tmp_path))
    )
    elapsed = time.monotonic() - started_at
    assert result.exit_code == 0
    assert result.stdout.strip() == _digest_line(payload)
    assert elapsed < STDIN_DELIVERY_TIMEOUT_SECONDS + 10


def test_a_multibyte_prompt_round_trips_through_the_whole_runner(tmp_path) -> None:
    payload = "中文 prompt 🙂 with ASCII".encode()
    result = asyncio.run(_go(_runner(), _spec("stdin-digest", payload=payload), _workdir(tmp_path)))
    assert result.stdout.strip() == _digest_line(payload)


# ---------------------------------------------------------------------------
# AC-S3 (R1): the child closes its end before consuming -> fail closed
# ---------------------------------------------------------------------------


def test_a_child_that_closes_early_fails_the_start_and_leaves_no_group(tmp_path) -> None:
    # Far beyond one pipe buffer, so the child's early exit is observed as a
    # write/drain failure rather than being fully absorbed by the kernel.
    payload = b"x" * 400_000
    pids: list[int] = []
    runner = _runner(pids=pids)

    with pytest.raises(ProcessSpawnError) as caught:
        asyncio.run(_start(runner, _spec("stdin-refuse", payload=payload), _workdir(tmp_path)))
    assert caught.value.code == REASON_PIPE_SETUP_FAILED
    assert pids, "the group was spawned before delivery failed"
    assert _group_gone(pids[0])


# ---------------------------------------------------------------------------
# AC-S4 (R2): a child that never reads -> bounded failure, not a hang
# ---------------------------------------------------------------------------


def test_a_child_that_never_reads_fails_inside_the_delivery_deadline(tmp_path) -> None:
    payload = b"y" * 400_000
    pids: list[int] = []
    runner = _runner(pids=pids, timeout=0.2)

    started_at = time.monotonic()
    with pytest.raises(ProcessSpawnError) as caught:
        asyncio.run(
            _start(runner, _spec("stdin-never-read", "60", payload=payload), _workdir(tmp_path))
        )
    elapsed = time.monotonic() - started_at
    assert caught.value.code == REASON_PIPE_SETUP_FAILED
    assert elapsed < 2.0, f"delivery took {elapsed:.2f}s despite a 0.2s deadline"
    assert pids
    assert _group_gone(pids[0])


def test_delivery_timeout_is_capped_by_the_process_wall_budget(tmp_path) -> None:
    """D22: a 1s wall cannot be exceeded by the 10s delivery constant."""
    payload = b"w" * 400_000
    pids: list[int] = []
    runner = _runner(pids=pids)  # deliberately keeps the 10s default
    spec = _spec("stdin-never-read", "60", payload=payload).model_copy(
        update={"resource_policy": _POLICY.model_copy(update={"wall_seconds": 1})}
    )

    started_at = time.monotonic()
    with pytest.raises(ProcessSpawnError) as caught:
        asyncio.run(_start(runner, spec, _workdir(tmp_path)))
    elapsed = time.monotonic() - started_at
    assert caught.value.code == REASON_PIPE_SETUP_FAILED
    assert elapsed < 2.0, f"delivery took {elapsed:.2f}s despite a 1s wall budget"
    assert pids
    assert _group_gone(pids[0])


def test_delivery_failure_logs_only_stable_facts(tmp_path, caplog) -> None:
    # The sentinel must be big enough to leave the pipe buffer, otherwise the
    # write succeeds and no failure path is exercised at all.
    sentinel = b"SENTINEL-STDIN-PAYLOAD-DO-NOT-LOG" * 20_000
    assert len(sentinel) > 262_144
    runner = _runner(timeout=0.2)

    with caplog.at_level(logging.DEBUG), pytest.raises(ProcessSpawnError):
        asyncio.run(
            _start(runner, _spec("stdin-never-read", "60", payload=sentinel), _workdir(tmp_path))
        )
    assert "stdin delivery failed" in caplog.text
    assert "SENTINEL-STDIN-PAYLOAD-DO-NOT-LOG" not in caplog.text


# ---------------------------------------------------------------------------
# AC-S5: the DTO itself refuses empty, oversized and non-byte payloads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [b"", b"z" * (MAX_STDIN_PAYLOAD_BYTES + 1), "a string is not bytes"],
)
def test_process_spec_rejects_empty_oversized_and_str_payloads(payload) -> None:
    with pytest.raises(ValidationError):
        ProcessSpec(
            executable_id=TRUSTED_EXECUTABLE_ID,
            argv=("x",),
            stdin_payload=payload,
            workdir_relative_path="aa11/bb22",
            resource_policy=_POLICY,
        )


def test_the_ceiling_itself_is_accepted() -> None:
    spec = ProcessSpec(
        executable_id=TRUSTED_EXECUTABLE_ID,
        argv=("x",),
        stdin_payload=b"z" * MAX_STDIN_PAYLOAD_BYTES,
        workdir_relative_path="aa11/bb22",
        resource_policy=_POLICY,
    )
    assert spec.stdin_payload is not None
    assert len(spec.stdin_payload) == MAX_STDIN_PAYLOAD_BYTES


# ---------------------------------------------------------------------------
# AC-S6: the byte ceiling and the character ceiling stay coupled
# ---------------------------------------------------------------------------


def test_payload_ceiling_covers_the_worst_case_utf8_expansion_of_a_request() -> None:
    # 4 bytes is the worst UTF-8 expansion of one code point; the request bound
    # is 200_000 *characters*, so anything the contract accepts fits in bytes.
    assert MAX_STDIN_PAYLOAD_BYTES == 4 * 200_000
    input_field = ExecutionRequest.model_fields["input"]
    bounds = {getattr(item, "max_length", None) for item in input_field.metadata}
    assert 200_000 in bounds


# ---------------------------------------------------------------------------
# AC-S7: the payload never changes the command digest
# ---------------------------------------------------------------------------


def test_payload_is_outside_the_command_digest() -> None:
    without = _spec("stdin-digest")
    first = _spec("stdin-digest", payload=b"first prompt")
    second = _spec("stdin-digest", payload=b"a completely different prompt")
    assert first.command_digest == second.command_digest == without.command_digest
    assert first.command_digest == compute_command_digest(TRUSTED_EXECUTABLE_ID, first.argv)


# ---------------------------------------------------------------------------
# AC-S8: the payload is invisible in every representation
# ---------------------------------------------------------------------------


def test_the_payload_is_invisible_in_repr_and_dumps() -> None:
    prompt = "SENTINEL-PROMPT-CONTENT"
    spec = _spec("stdin-digest", payload=prompt.encode())
    assert prompt not in repr(spec)
    dumped = spec.model_dump(mode="json")
    assert prompt not in json.dumps(dumped)
    assert "stdin_payload" not in spec.model_dump()
    # Exclusion is about representation only: the Runner still receives it.
    assert spec.stdin_payload == prompt.encode()
    copied = spec.model_copy(update={"workdir_relative_path": "aa11/bb33"})
    assert copied.stdin_payload == prompt.encode()


def test_the_payload_never_enters_a_public_event_payload() -> None:
    prompt = "SENTINEL-PROMPT-CONTENT"
    mapper = CodexEventMapper.for_cli(
        execution_id=UUID("00000000-0000-4000-8000-000000000901"),
        engine_session_id=str(uuid4()),
    )
    event = mapper.map(
        CodexNativeEvent(event_type="turn.started", payload={"type": "turn.started"})
    )
    assert prompt not in json.dumps(event.payload)
    assert prompt not in str(event)


# ---------------------------------------------------------------------------
# Real-binary confirmation (local only; CI has no Codex binary)
# ---------------------------------------------------------------------------


def test_real_codex_consumes_the_prompt_through_the_host(tmp_path) -> None:
    """08 R18 real-provider half; `pending_env` wherever Codex is absent.

    No assertion touches the provider's answer content: the point is that the
    real binary leaves ``DEVNULL``-stdin failure behind (exit 1, "No prompt
    provided via stdin.") and completes a Turn from the delivered payload.
    """
    real = Path("/usr/local/bin/codex")
    if not real.is_file():
        pytest.skip("pending_env: no Codex CLI binary in this environment")

    working = _workdir(tmp_path)
    spec = ProcessSpec(
        executable_id="codex",
        argv=(
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "-",
        ),
        environment={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        stdin_payload=b"Reply with exactly the word: ok",
        workdir_relative_path="aa11/bb22",
        resource_policy=_POLICY.model_copy(
            update={"workdir_file_bytes": 134_217_728, "wall_seconds": 180}
        ),
    )
    runner = ProcessRunner(
        TrustedTargetRegistry(
            (
                TrustedTargetDescriptor(
                    executable_id="codex",
                    executable_path=str(real),
                    fixed_prefix=spec.argv,
                ),
            )
        )
    )

    async def run() -> ProcessResult:
        started = await _start(runner, spec, working)
        supervisor = ProcessSupervisor(cancel_grace_seconds=5, kill_timeout_seconds=5)
        return await supervisor.wait(started, wall_seconds=180)

    result = asyncio.run(run())
    assert result.reason_code == "runtime_host_exited"
    assert result.exit_code == 0
    # The measured 0.169.0 grammar: a real answer item plus a real usage block.
    assert b'"type":"turn.completed"' in result.stdout
    assert b'"type":"agent_message"' in result.stdout
