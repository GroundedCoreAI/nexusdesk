"""Stage A Codex adapter unit tests with a stub Host (no process is started).

Covers the behaviour that must hold regardless of the Host implementation:
argv is a fixed prefix with zero trailing parameters, the gate refuses before any
Host call, the public handle carries no OS identity, history survives collection,
cancellation is idempotent, and every Host reason maps onto a frozen catalog code.
"""

import ast
import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from agent_platform.core_platform.agent_execution.adapters.codex.adapter import (
    CodexCliAdapter,
    declared_capabilities,
)
from agent_platform.core_platform.agent_execution.adapters.codex.cli_exec import (
    CODEX_CLI_FIXED_ARGV,
)
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexStageGate,
)
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    ConfigurationError,
    ExecutionErrorCode,
    ExecutionRequest,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessResult,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.runtime_host import HostStartError

_REAL_TRANSCRIPT = (
    Path(__file__).resolve().parent.parent / "fixtures" / "codex_fake" / "real_transcript.py"
)


def _load_real_transcript():
    """Load the measured-transcript fixture by path (tests/ is not a package)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("codex_real_transcript", _REAL_TRANSCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTION_ID = UUID("00000000-0000-4000-8000-000000000501")
AGENT_ID = UUID("00000000-0000-4000-8000-000000000502")
TENANT = "tenant-a"

_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=67_108_864,
    max_processes=16,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=65_536,
)

_ENABLED_GATE = CodexStageGate(
    cli_enabled=True,
    app_server_enabled=False,
    allowed_versions=("0.169.0",),
    trusted_tenants=(TENANT,),
    stage_a_verified=True,
)

_STDOUT = (
    b'{"type":"turn.started","turn_id":"t1"}\n'
    b'{"type":"message.completed","text":"fake codex result"}\n'
    b'{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":5,'
    b'"total_tokens":8,"cached_input_tokens":1,"cache_write_input_tokens":2,'
    b'"reasoning_output_tokens":4}}\n'
)


class StubHost:
    """Records every Host call; never spawns anything."""

    def __init__(self, result: ProcessResult | None = None) -> None:
        self.started: list = []
        self.waited: list = []
        self.cancelled: list = []
        self.result = result
        self.raise_on_start: BaseException | None = None

    async def start(self, spec, *, run_id, tenant_id, working_dir, **_):
        if self.raise_on_start is not None:
            raise self.raise_on_start
        self.started.append((spec, run_id, tenant_id, working_dir))
        managed_id = uuid4()
        return type("Managed", (), {"managed_id": managed_id})()

    async def wait(self, managed_id, *, wall_seconds=None, **_):
        self.waited.append((managed_id, wall_seconds))
        assert self.result is not None
        return self.result

    async def cancel(self, managed_id, **_):
        self.cancelled.append(managed_id)
        assert self.result is not None
        return self.result


def _process_result(**overrides) -> ProcessResult:
    data = {
        "managed_id": uuid4(),
        "run_id": EXECUTION_ID,
        "final_state": "exited",
        "reason_code": "runtime_host_exited",
        "exit_code": 0,
        "wall_seconds": 0.1,
        "stdout": _STDOUT,
        "stderr": b"",
    }
    data.update(overrides)
    return ProcessResult(**data)


def _request(**overrides) -> ExecutionRequest:
    data = {
        "execution_id": EXECUTION_ID,
        "engine_id": "codex",
        "protocol_id": "cli_exec",
        "adapter_version": "v1",
        "tenant_id": TENANT,
        "agent_id": AGENT_ID,
        "input": "inspect the workspace",
    }
    data.update(overrides)
    return ExecutionRequest(**data)


def _adapter(host, *, gate=_ENABLED_GATE, history=(), **config):
    return CodexCliAdapter(
        host,
        config=CodexConfig(version="0.169.0", **config),
        gate=gate,
        workdir_root=Path("/tmp"),
        resource_policy=_POLICY,
        history=history,
    )


async def _make_workdir(tmp_path: Path, request: ExecutionRequest) -> ExecutionRequest:
    relative = f"aa11/{request.execution_id}"
    (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    return request.model_copy(update={"execution_workdir": relative})


def test_argv_is_the_fixed_prefix_with_zero_trailing_parameters(tmp_path) -> None:
    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        request = await _make_workdir(tmp_path, _request())
        adapter._root = tmp_path
        await adapter.start(request)

        spec = host.started[0][0]
        assert spec.executable_id == "codex"
        assert spec.argv == CODEX_CLI_FIXED_ARGV
        assert spec.argv == (
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "-",
        )
        # No absolute path, credential or host environment value enters argv.
        assert all("/" not in token and "\\" not in token for token in spec.argv)
        # 08 R17: PATH is the one supplied variable (a ``/usr/bin/env node``
        # launcher cannot start in an empty environment). It stays a deployment
        # value, never a host-derived one.
        assert set(spec.environment) == {"PATH"}
        assert spec.environment["PATH"] == "/usr/local/bin:/usr/bin:/bin"

    asyncio.run(scenario())


def test_gate_refusal_happens_before_any_host_call(tmp_path) -> None:
    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host, gate=CodexStageGate())
        request = await _make_workdir(tmp_path, _request())

        with pytest.raises(ConfigurationError) as caught:
            await adapter.start(request)
        assert caught.value.error.code is ExecutionErrorCode.ADAPTER_DISABLED
        assert host.started == []

        untrusted = _adapter(
            host,
            gate=_ENABLED_GATE.model_copy(update={"trusted_tenants": ("other",)}),
        )
        with pytest.raises(ConfigurationError):
            await untrusted.start(request)
        assert host.started == []

        pinned = _adapter(
            host,
            gate=_ENABLED_GATE.model_copy(update={"allowed_versions": ("9.9.9",)}),
        )
        with pytest.raises(ConfigurationError):
            await pinned.start(request)
        assert host.started == []

    asyncio.run(scenario())


def test_the_prompt_is_delivered_on_stdin_and_never_in_argv(tmp_path) -> None:
    """08 R18: the prompt travels as a bounded stdin payload, not as an argument.

    The old contract refused every prompt-carrying start because the Host had no
    stdin channel. It now has one, so the assertion inverts: the exact UTF-8
    bytes must reach ``ProcessSpec.stdin_payload`` while ``argv`` stays the
    seven code constants, and no other spec field may carry the text.
    """

    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path
        prompt = "inspect the workspace: 中文 prompt 🙂"
        request = await _make_workdir(tmp_path, _request(input=prompt))

        await adapter.start(request)

        spec, _, _, _ = host.started[0]
        assert spec.stdin_payload == prompt.encode("utf-8")
        assert spec.argv == CODEX_CLI_FIXED_ARGV
        # The prompt is nowhere else on the spec: not argv, not the environment,
        # not the workdir path.
        assert all(prompt not in token for token in spec.argv)
        assert prompt not in spec.environment.values()
        assert prompt not in spec.workdir_relative_path
        # ... and it is invisible in every serialized/logged representation.
        assert prompt not in repr(spec)
        assert "stdin_payload" not in spec.model_dump()

    asyncio.run(scenario())


def test_host_start_failure_is_normalized_to_an_adapter_error(tmp_path) -> None:
    """D21: HostStartError cannot escape with an internal reason vocabulary."""

    async def scenario() -> None:
        host = StubHost(_process_result())
        host.raise_on_start = HostStartError("runtime_host_pipe_setup_failed")
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request())

        with pytest.raises(AdapterExecutionError) as caught:
            await adapter.start(request)
        assert caught.value.error.code is ExecutionErrorCode.ENGINE_UNAVAILABLE
        assert "runtime_host_pipe_setup_failed" not in str(caught.value)
        assert host.started == []

    asyncio.run(scenario())


def test_handle_identity_is_exact_and_carries_no_process_id(tmp_path) -> None:
    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request())
        handle = await adapter.start(request)

        assert (handle.engine_id, handle.protocol_id, handle.adapter_version) == (
            "codex",
            "cli_exec",
            "v1",
        )
        assert handle.process_id is None  # Phase 4 R-4b
        assert handle.provider_session_id is not None
        assert handle.execution_id == EXECUTION_ID

        # A mismatched identity never reaches the Host.
        forged = handle.model_copy(update={"protocol_id": "app_server"})
        with pytest.raises(ConfigurationError):
            await adapter.cancel(forged)

    asyncio.run(scenario())


def test_capabilities_match_the_composition_declaration() -> None:
    async def scenario() -> None:
        adapter = _adapter(StubHost(_process_result()))
        assert await adapter.get_capabilities() == declared_capabilities()
        assert declared_capabilities().workspace_required is True

    asyncio.run(scenario())


def test_completed_outcome_keeps_history_and_never_reports_empty(tmp_path) -> None:
    async def scenario() -> None:
        history = [
            {"role": "user", "content": "earlier"},
            {"role": "assistant", "content": "earlier answer"},
        ]
        host = StubHost(_process_result())
        adapter = _adapter(host, history=history)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request())
        handle = await adapter.start(request)

        events = [event async for event in adapter.stream_events(handle)]
        assert [event.event_type for event in events] == [
            "codex.turn.started",
            "codex.message.completed",
            "codex.turn.completed",
        ]
        assert [event.sequence for event in events] == [1, 2, 3]
        assert all(event.engine_session_id == handle.provider_session_id for event in events)

        outcome = await adapter.collect_outcome(handle)
        assert outcome.status == "completed"
        assert outcome.dropped == []
        assert outcome.history[:2] == history
        assert outcome.history[-1] == {"role": "assistant", "content": outcome.output}
        assert outcome.history != []

    asyncio.run(scenario())


def test_usage_is_measured_or_explicitly_unknown(tmp_path) -> None:
    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request())
        handle = await adapter.start(request)

        result = await adapter.collect_result(handle)
        assert result.status == "completed"
        assert result.usage == {
            "input_tokens": 3,
            "output_tokens": 5,
            "total_tokens": 8,
            "cached_input_tokens": 1,
            "cache_write_input_tokens": 2,
            "reasoning_output_tokens": 4,
        }

        no_usage_host = StubHost(
            _process_result(stdout=b'{"type":"message.completed","text":"hello"}\n')
        )
        no_usage = _adapter(no_usage_host)
        no_usage._root = tmp_path
        other = await _make_workdir(
            tmp_path, _request(execution_id=UUID("00000000-0000-4000-8000-000000000503"))
        )
        handle2 = await no_usage.start(other)
        assert (await no_usage.collect_result(handle2)).usage == {"status": "unknown"}

    asyncio.run(scenario())


def test_cancel_is_idempotent_and_caches_the_terminal_result(tmp_path) -> None:
    async def scenario() -> None:
        host = StubHost(_process_result(reason_code="runtime_host_cancelled", exit_code=None))
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request())
        handle = await adapter.start(request)

        await adapter.cancel(handle)
        await adapter.cancel(handle)
        assert len(host.cancelled) == 1

        result = await adapter.collect_result(handle)
        assert result.status == "cancelled"
        # A second collection must not re-enter the Host (which would raise
        # SupervisorStateError after the record was untracked).
        assert (await adapter.collect_result(handle)).status == "cancelled"

    asyncio.run(scenario())


def test_wall_timeout_and_resource_reasons_map_to_frozen_codes(tmp_path) -> None:
    async def scenario() -> None:
        cases = {
            "runtime_host_wall_timeout": ExecutionErrorCode.EXECUTION_TIMEOUT,
            "runtime_host_output_limit_exceeded": ExecutionErrorCode.RESOURCE_EXHAUSTED,
            "runtime_host_resource_exceeded": ExecutionErrorCode.RESOURCE_EXHAUSTED,
            "runtime_host_spawn_failed": ExecutionErrorCode.ENGINE_UNAVAILABLE,
        }
        for index, (reason, expected) in enumerate(cases.items()):
            host = StubHost(_process_result(reason_code=reason, exit_code=None))
            adapter = _adapter(host)
            adapter._root = tmp_path
            request = await _make_workdir(
                tmp_path,
                _request(execution_id=UUID(int=600 + index)),
            )
            handle = await adapter.start(request)
            result = await adapter.collect_result(handle)
            assert result.status == "failed"
            assert result.error is not None
            assert result.error.code is expected

        cleanup = StubHost(_process_result(final_state="cleanup_failed", exit_code=None))
        adapter = _adapter(cleanup)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request(execution_id=UUID(int=700)))
        handle = await adapter.start(request)
        result = await adapter.collect_result(handle)
        assert result.error is not None
        assert result.error.code is ExecutionErrorCode.RESOURCE_EXHAUSTED

    asyncio.run(scenario())


def test_a_malformed_native_line_fails_the_execution_as_protocol_error(tmp_path) -> None:
    async def scenario() -> None:
        host = StubHost(_process_result(stdout=b'{"type":"turn.started"}\n{not-json}\n'))
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request())
        handle = await adapter.start(request)

        stream = adapter.stream_events(handle)
        with pytest.raises(AdapterExecutionError) as caught:
            async for _ in stream:
                pass
        assert caught.value.error.code is ExecutionErrorCode.PROTOCOL_ERROR
        result = await adapter.collect_result(handle)
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.code is ExecutionErrorCode.PROTOCOL_ERROR

    asyncio.run(scenario())


def test_wall_ceiling_is_the_minimum_of_config_run_and_host() -> None:
    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)

        request = _request(timeout_seconds=30)
        adapter._request = request
        adapter._resource_policy = _POLICY.model_copy(update={"wall_seconds": 45})
        assert adapter._wall_seconds() == 30.0

        adapter._request = _request(timeout_seconds=None)
        assert adapter._wall_seconds() == 45.0

    asyncio.run(scenario())


def test_adapter_source_never_uses_direct_process_control() -> None:
    """Static pin: process control belongs to the RuntimeHost only."""
    source_path = (
        Path(__file__).parents[2]
        / "src"
        / "agent_platform"
        / "core_platform"
        / "agent_execution"
        / "adapters"
        / "codex"
        / "adapter.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_modules = {"subprocess", "signal", "os", "multiprocessing"}
    forbidden_names = {"Popen", "kill", "killpg", "fork", "spawnv"}

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not [name for name in imported if name.split(".")[0] in forbidden_modules]
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not (called & forbidden_names)
    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_names
    }
    assert attributes == set()


# ---------------------------------------------------------------------------
# D13: Workdir containment (authoritative workspace policy + root re-check)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "escape",
    [
        "/tmp",
        "/private/tmp",
        "../..",
        "../../etc",
        "aa11/../../../etc",
        "aa11/./bb22",
        "AA11/bb22",
        "aa11/bb22/",
        "C:aa11",
        "aa11%2fbb22",
        "aa11\\bb22",
    ],
)
def test_hostile_workdir_paths_are_refused_before_any_host_call(tmp_path, escape) -> None:
    """D13: an absolute path, ``..``, encoded separator or drive letter escapes root."""

    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path
        (tmp_path / "aa11").mkdir(mode=0o700)

        with pytest.raises(AdapterExecutionError) as caught:
            await adapter.start(_request(execution_workdir=escape))
        assert caught.value.error.code is ExecutionErrorCode.WORKSPACE_ERROR
        assert host.started == []

    asyncio.run(scenario())


def test_symlinked_workdir_cannot_escape_the_root(tmp_path) -> None:
    """A safe-looking relative path whose directory is a symlink outward is refused."""

    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path
        outside = tmp_path.parent / f"outside-{uuid4().hex}"
        outside.mkdir(mode=0o700)
        try:
            (tmp_path / "aa11").mkdir(mode=0o700)
            (tmp_path / "aa11" / "linked").symlink_to(outside, target_is_directory=True)

            with pytest.raises(AdapterExecutionError) as caught:
                await adapter.start(_request(execution_workdir="aa11/linked"))
            assert caught.value.error.code is ExecutionErrorCode.WORKSPACE_ERROR
            assert host.started == []
        finally:
            outside.rmdir()

    asyncio.run(scenario())


def test_missing_workdir_is_refused_with_workspace_error(tmp_path) -> None:
    """D11: the missing-directory branch is exercised explicitly."""

    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path

        with pytest.raises(AdapterExecutionError) as caught:
            await adapter.start(_request(execution_workdir="aa11/absent"))
        assert caught.value.error.code is ExecutionErrorCode.WORKSPACE_ERROR
        assert host.started == []

    asyncio.run(scenario())


def test_the_root_itself_is_not_an_execution_workdir(tmp_path) -> None:
    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path

        with pytest.raises(AdapterExecutionError) as caught:
            await adapter.start(_request(execution_workdir="."))
        assert caught.value.error.code is ExecutionErrorCode.WORKSPACE_ERROR
        assert host.started == []

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# D6: the measured real-CLI transcript shape
# ---------------------------------------------------------------------------


def test_real_codex_transcript_yields_the_nested_agent_message(tmp_path) -> None:
    """D6: ``item.completed{item.type=agent_message,text}`` is the real answer."""
    transcript_fixture = _load_real_transcript()
    REAL_CODEX_MINIMAL_SUCCESS = transcript_fixture.REAL_CODEX_MINIMAL_SUCCESS
    REAL_CODEX_SUCCESS_TRANSCRIPT = transcript_fixture.REAL_CODEX_SUCCESS_TRANSCRIPT
    REAL_CODEX_USAGE = transcript_fixture.REAL_CODEX_USAGE

    async def scenario() -> None:
        for transcript in (REAL_CODEX_SUCCESS_TRANSCRIPT, REAL_CODEX_MINIMAL_SUCCESS):
            host = StubHost(_process_result(stdout=transcript.encode()))
            adapter = _adapter(host)
            adapter._root = tmp_path
            request = await _make_workdir(
                tmp_path, _request(execution_id=UUID(int=800 + len(transcript)))
            )
            handle = await adapter.start(request)

            result = await adapter.collect_result(handle)
            assert result.status == "completed"
            # The diagnostic item must not become the answer.
            assert result.output == "ok"
            assert result.usage == REAL_CODEX_USAGE
            # The measured usage has no total_tokens at all; it is never invented.
            assert "total_tokens" not in result.usage

    asyncio.run(scenario())


def test_real_codex_error_item_is_never_reported_as_the_answer(tmp_path) -> None:
    REAL_CODEX_SUCCESS_TRANSCRIPT = _load_real_transcript().REAL_CODEX_SUCCESS_TRANSCRIPT

    async def scenario() -> None:
        host = StubHost(_process_result(stdout=REAL_CODEX_SUCCESS_TRANSCRIPT.encode()))
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request(execution_id=UUID(int=810)))
        handle = await adapter.start(request)

        result = await adapter.collect_result(handle)
        assert "model runner refused" not in (result.output or "")

    asyncio.run(scenario())


def test_flat_fixture_syntax_still_produces_the_answer(tmp_path) -> None:
    """Backwards compatibility: the pre-D6 fixture shape keeps working."""

    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request(execution_id=UUID(int=820)))
        handle = await adapter.start(request)

        result = await adapter.collect_result(handle)
        assert result.output == "fake codex result"

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# D17: collect_result shares the parser; the stream is claim-once
# ---------------------------------------------------------------------------


def test_collect_result_rejects_a_malformed_transcript(tmp_path) -> None:
    """D17: exit 0 with bad JSON must not be reported as a completed result."""

    async def scenario() -> None:
        host = StubHost(_process_result(stdout=b"{not-json}\n"))
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request(execution_id=UUID(int=830)))
        handle = await adapter.start(request)

        result = await adapter.collect_result(handle)
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.code is ExecutionErrorCode.PROTOCOL_ERROR
        assert result.output is None

    asyncio.run(scenario())


def test_stream_events_can_be_claimed_only_once(tmp_path) -> None:
    """D17: a second claim would restart the sequence and duplicate identities."""

    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host)
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request(execution_id=UUID(int=840)))
        handle = await adapter.start(request)

        first = [event async for event in adapter.stream_events(handle)]
        assert [event.sequence for event in first] == [1, 2, 3]
        with pytest.raises(ConfigurationError) as caught:
            adapter.stream_events(handle)
        assert caught.value.error.code is ExecutionErrorCode.INVALID_ADAPTER_STATE

    asyncio.run(scenario())


def test_process_spec_carries_only_the_deployment_path(tmp_path) -> None:
    """08 R17: an empty environment breaks the ``/usr/bin/env node`` launcher.

    The lane contributes exactly one variable. Only PATH may travel: a credential,
    proxy or host value has no field in ``CodexConfig`` to reach the child, so the
    supplied process environment stays provably secret-free (C1/C2).
    """

    async def scenario() -> None:
        host = StubHost(_process_result())
        adapter = _adapter(host, path_env="/opt/node/bin:/usr/bin")
        adapter._root = tmp_path
        request = await _make_workdir(tmp_path, _request(execution_id=UUID(int=841)))
        await adapter.start(request)

        spec, _, _, _ = host.started[0]
        assert spec.environment == {"PATH": "/opt/node/bin:/usr/bin"}
        # The argv is untouched by the environment addition.
        assert spec.argv == CODEX_CLI_FIXED_ARGV

    asyncio.run(scenario())


def test_path_env_rejects_relative_entries_and_parent_segments() -> None:
    """A PATH is code-adjacent: relative or ``..`` entries would be an escape."""

    for value in ("node/bin:/usr/bin", "/usr/bin::/bin", "/usr/bin:..:/bin", "usr/bin"):
        with pytest.raises(ValidationError):
            CodexConfig(version="0.169.0", path_env=value)
