"""Stage A Codex CLI engine adapter (Phase 5, 02 FR-1-FR-6).

The adapter is a thin protocol translation layer:

* :meth:`CodexCliAdapter.start` consults the deployment gate, builds one
  :class:`~...host.host_models.ProcessSpec`, and hands it to the injected
  :class:`~...host.runtime_host.RuntimeHost`. It never spawns, signals, or reaps a
  process itself (an AST pin test enforces the absence of ``subprocess``,
  ``signal``, ``os.kill`` and ``Popen``).
* The public :class:`~...contracts.ExecutionHandle` keeps ``process_id=None``
  (Phase 4 08 R-4b); OS identity stays inside the Host's private models.
* :meth:`CodexCliAdapter.stream_events` maps the Host's bounded stdout through
  :class:`~.events.CodexEventMapper`.
* :meth:`CodexCliAdapter.collect_outcome` returns the private outcome including
  Memory history. A completed Run must never carry an empty ``history``: the
  Repository hands it to ``on_completed``, which overwrites
  ``runtime_conversations.history`` with whatever it receives.

Prompt delivery
---------------
The prompt travels on the Host's opt-in stdin channel (08 R18): :meth:`start`
encodes ``request.input`` to UTF-8 and hands the bytes to ``ProcessSpec`` as
``stdin_payload``. ``ProcessRunner`` writes it and closes the pipe, which is
what makes ``codex exec … -`` start its turn. The prompt never enters ``argv``,
the environment, a filename, metadata, an event payload, a log line or an
exception message, and it is outside ``command_digest`` (which stays
executable id + argv). Encoding happens here, once, because a failure has a
defined semantic: an unencodable prompt is ``INVALID_REQUEST``.
"""

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from uuid import UUID

from ...contracts import (
    AdapterExecutionError,
    AgentEvent,
    ConfigurationError,
    EngineCapabilities,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
    ensure_handle_identity,
    ensure_request_identity,
)
from ...host.host_models import (
    MAX_STDIN_PAYLOAD_BYTES,
    ProcessResult,
    ProcessSpec,
    ResourcePolicy,
)
from ...host.runtime_host import HostStartError, RuntimeHost
from ...orchestration.execution_lifecycle import ExecutionOutcome
from ...workspace.execution_workdir import WorkdirOperationError, ensure_private_engine_home
from ...workspace.workspace_policy import WorkspacePathError, normalize_relative_path
from .cli_exec import CODEX_CLI_EXECUTABLE_ID, CODEX_CLI_FIXED_ARGV
from .config import (
    GATE_DENIED_DISABLED,
    GATE_DENIED_PROTOCOL,
    GATE_DENIED_TENANT,
    GATE_DENIED_VERSION,
    CodexConfig,
    CodexProtocol,
    CodexStageGate,
)
from .events import CodexEventMapper, CodexEventParser, parse_usage
from .home_config import CodexEngineHomeConfig, write_private_engine_config

ENGINE_ID = "codex"
PROTOCOL_ID = "cli_exec"
ADAPTER_VERSION = "v1"

# Stage A declares exactly what the Composition root registers. The
# Orchestrator's ``_assert_declared`` compares these two objects field by field,
# so this constant is the single declaration for both sides.
DECLARED_CAPABILITIES = EngineCapabilities(
    streaming=True,
    cancellation=True,
    native_events=True,
    workspace_required=True,
)

_GATE_CODES: dict[str, ExecutionErrorCode] = {
    GATE_DENIED_DISABLED: ExecutionErrorCode.ADAPTER_DISABLED,
    GATE_DENIED_VERSION: ExecutionErrorCode.ADAPTER_DISABLED,
    GATE_DENIED_TENANT: ExecutionErrorCode.ADAPTER_DISABLED,
    GATE_DENIED_PROTOCOL: ExecutionErrorCode.PROTOCOL_DISABLED,
}


def declared_capabilities() -> EngineCapabilities:
    """The one Stage A declaration shared by Registry metadata and the instance."""
    return DECLARED_CAPABILITIES


def _configuration_error(code: ExecutionErrorCode) -> ConfigurationError:
    return ConfigurationError(
        ExecutionError(category=ExecutionErrorCategory.CONFIGURATION_ERROR, code=code)
    )


def _bounded_error(
    category: ExecutionErrorCategory, code: ExecutionErrorCode
) -> AdapterExecutionError:
    return AdapterExecutionError(ExecutionError(category=category, code=code))


def _failed(
    execution_id: UUID,
    category: ExecutionErrorCategory,
    code: ExecutionErrorCode,
) -> ExecutionResult:
    return ExecutionResult(
        execution_id=execution_id,
        engine_id=ENGINE_ID,
        protocol_id=PROTOCOL_ID,
        adapter_version=ADAPTER_VERSION,
        status="failed",
        error=ExecutionError(category=category, code=code),
    )


def _answer_text(value: dict) -> str | None:
    """One assistant answer from either measured transcript shape, or ``None``.

    ``item.*`` (real CLI) is checked first: ``item.completed`` carries an
    ``item`` object whose ``type`` is ``agent_message`` for an answer and
    ``error`` for a diagnostic. The flat shape is the fixture contract.
    """
    item = value.get("item")
    event_type = value.get("type")
    if isinstance(item, dict):
        item_type = item.get("type")
        item_text = item.get("text")
        if (
            item_type == "agent_message"
            and isinstance(item_text, str)
            and isinstance(event_type, str)
            and event_type.endswith("completed")
        ):
            return item_text
        return None
    text = value.get("text")
    if (
        isinstance(text, str)
        and isinstance(event_type, str)
        and event_type.endswith("completed")
        and "usage" not in value
    ):
        return text
    return None


class CodexCliAdapter:
    """Single-execution Stage A adapter over one injected RuntimeHost."""

    def __init__(
        self,
        host: RuntimeHost,
        *,
        config: CodexConfig,
        gate: CodexStageGate,
        workdir_root: Path,
        resource_policy: ResourcePolicy,
        history: Sequence[Mapping[str, object]] = (),
        ownership: object | None = None,
        credential_broker: object | None = None,
        credential_ref: object | None = None,
        engine_home_config: CodexEngineHomeConfig | None = None,
        clock: object | None = None,
        id_factory: object | None = None,
    ) -> None:
        self._host = host
        # Internal Fencing evidence captured from the claimed ExecutionContext;
        # never serialized into the public handle or request.
        self._ownership = ownership
        # R-18(a): the Host consumes the grant before spawn; the adapter passes
        # the credential reference and audience so the Host binds it to this Run.
        self._credential_broker = credential_broker
        self._credential_ref = credential_ref
        self._engine_home_config = engine_home_config
        self._config = config
        self._gate = gate
        self._root = workdir_root
        self._resource_policy = resource_policy
        # The claimed row's retained history arrives through the composition
        # factory (the frozen ``ExecutionRequest`` carries no history field).
        self._history = [dict(item) for item in history]
        self._clock = clock
        self._id_factory = id_factory
        self._request: ExecutionRequest | None = None
        self._handle: ExecutionHandle | None = None
        self._managed_id: UUID | None = None
        self._private_home: Path | None = None
        # Host ``wait``/``cancel`` untrack a record once it reaches a terminal
        # result, so a second call would raise SupervisorStateError. The first
        # terminal observation is cached here and every later read serves it.
        self._process_result: ProcessResult | None = None
        self._terminal: ExecutionResult | None = None
        self._stream_claimed = False

    # -- identity ---------------------------------------------------------

    @property
    def engine_id(self) -> str:
        return ENGINE_ID

    @property
    def protocol_id(self) -> str:
        return PROTOCOL_ID

    @property
    def adapter_version(self) -> str:
        return ADAPTER_VERSION

    async def get_capabilities(self) -> EngineCapabilities:
        return declared_capabilities()

    @property
    def timeout_seconds(self) -> int:
        """Configured ceiling; the Run deadline and Host wall stay authoritative."""
        return self._config.timeout_seconds

    # -- lifecycle --------------------------------------------------------

    async def start(self, request: ExecutionRequest) -> ExecutionHandle:
        """Gate, then start exactly one Host-managed process group."""
        if not isinstance(request, ExecutionRequest):
            raise _configuration_error(ExecutionErrorCode.INVALID_REQUEST)
        ensure_request_identity(request, self)
        if self._request is not None:
            raise _configuration_error(ExecutionErrorCode.INVALID_ADAPTER_STATE)
        denial = self._gate.denial(
            CodexProtocol.CLI_EXEC,
            version=self._config.version,
            tenant_id=request.tenant_id,
        )
        if denial is not None:
            raise _configuration_error(_GATE_CODES[denial])

        # P6/G5: the published config carries only a UUID reference. Resolve it
        # here and hand an explicit audience to the Host; never let the Host
        # fall back to "native"/"default", which would broaden credential reuse.
        credential_ref: UUID | None = None
        broker_audience: dict[str, str] = {}
        if self._config.credential_ref is not None:
            try:
                credential_ref = UUID(self._config.credential_ref)
            except (TypeError, ValueError):
                raise _bounded_error(
                    ExecutionErrorCategory.ENGINE_UNAVAILABLE,
                    ExecutionErrorCode.ENGINE_UNAVAILABLE,
                ) from None
            if (
                self._credential_broker is None
                or self._engine_home_config is None
                or request.workspace_id is None
            ):
                raise _bounded_error(
                    ExecutionErrorCategory.ENGINE_UNAVAILABLE,
                    ExecutionErrorCode.ENGINE_UNAVAILABLE,
                )
            broker_audience = {
                "engine_id": self.engine_id,
                "protocol_id": self.protocol_id,
                "workspace_id": str(request.workspace_id),
            }

        # 08 R18: encode once, here, before anything has a side effect. An
        # unencodable or over-ceiling prompt must not create the adhoc Workdir
        # below, and must never reach the Host as a truncated prompt.
        payload = self._stdin_payload(request)

        relative = self._workdir_relative(request)
        working_dir = self._contained_workdir(relative)
        # G3 (08 R-13/C5, Phase 5 stage-A P3): create the per-Execution private
        # CODEX_HOME scaffold inside the validated run workdir. P5 optionally
        # renders a key-free config.toml there and points the typed CODEX_HOME
        # slot at it; P6 owns the typed credential/env injection. A symlink or
        # ownership fault here is a WORKSPACE_ERROR before any Host call.
        try:
            private_home = ensure_private_engine_home(working_dir)
            engine_env = {"PATH": self._config.path_env}
            if self._engine_home_config is not None:
                write_private_engine_config(private_home, self._engine_home_config)
                engine_env["CODEX_HOME"] = str(private_home)
        except WorkdirOperationError:
            raise _bounded_error(
                ExecutionErrorCategory.WORKSPACE_ERROR, ExecutionErrorCode.WORKSPACE_ERROR
            ) from None
        self._private_home = private_home

        spec = ProcessSpec(
            executable_id=CODEX_CLI_EXECUTABLE_ID,
            argv=CODEX_CLI_FIXED_ARGV,
            # 08 R17: the Host starts targets with an empty environment, and the
            # installed CLI is a ``#!/usr/bin/env node`` launcher. Without PATH
            # the kernel fails the exec itself (measured exit 127). PATH and
            # CODEX_HOME are typed, non-secret slots; credentials/proxies/host
            # values have no field to travel in.
            environment=engine_env,
            # P6/G5: a typed, closed-allowlist variable name. The Host binds the
            # Broker secret to it after issue/consume and clears this slot.
            credential_env_key=(
                self._engine_home_config.env_key if credential_ref is not None else None
            ),
            # 08 R18: the prompt goes to the Host stdin channel, never argv.
            stdin_payload=payload,
            workdir_relative_path=relative,
            resource_policy=self._resource_policy,
        )
        try:
            managed = await self._host.start(
                spec,
                run_id=request.execution_id,
                tenant_id=request.tenant_id,
                working_dir=working_dir,
                credential_ref=credential_ref,
                broker_audience=broker_audience,
            )
        except HostStartError:
            # HostStartError is an internal Host failure, not an adapter error:
            # do not let its reason code or exception text escape the public
            # vocabulary (D21). Start failures are engine-unavailable here for
            # the same reason the terminal-result mapper uses that catalog code.
            raise _bounded_error(
                ExecutionErrorCategory.ENGINE_UNAVAILABLE, ExecutionErrorCode.ENGINE_UNAVAILABLE
            ) from None
        self._managed_id = managed.managed_id
        # R-4b: no OS identity crosses into the public handle.
        handle = ExecutionHandle(
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            provider_session_id=str(managed.managed_id),
            process_id=None,
        )
        self._request = request
        self._handle = handle
        return handle

    def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        """One-claim stream; not a coroutine function (contract requirement)."""
        if self._stream_claimed:
            # D17: a second claim would rebuild the mapper and restart the
            # sequence at 1, producing duplicate identities for one execution.
            raise _configuration_error(ExecutionErrorCode.INVALID_ADAPTER_STATE)
        self._stream_claimed = True
        return self._stream(handle)

    async def _stream(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        self._execution_for(handle)
        result = await self._wait(handle)
        mapper = CodexEventMapper(
            execution_id=handle.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            engine_session_id=handle.provider_session_id,
            trace_id=self._request.trace_id if self._request is not None else None,
            clock=self._clock,
            id_factory=self._id_factory,
        )
        try:
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                for event in mapper.map_lines(
                    (line,),
                    max_line_bytes=self._resource_policy.output_max_bytes_per_stream,
                ):
                    yield event
        except AdapterExecutionError:
            # A malformed native line is a protocol failure of this execution:
            # remember it so the terminal collection reports failure instead of
            # the exit-code-zero "completed" reading.
            self._terminal = _failed(
                handle.execution_id,
                ExecutionErrorCategory.PROTOCOL_ERROR,
                ExecutionErrorCode.PROTOCOL_ERROR,
            )
            raise

    async def cancel(self, handle: ExecutionHandle) -> None:
        """Idempotent: a terminal observation is returned unchanged."""
        self._execution_for(handle)
        if self._process_result is not None or self._managed_id is None:
            return
        self._process_result = await self._host.cancel(self._managed_id)

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        """Collect the terminal result, validating the transcript first.

        D17: this used to read stdout directly and therefore reported
        ``completed`` for a stream that ``stream_events`` calls a protocol
        error. Both paths now go through the same parser, so a malformed line
        is a `PROTOCOL_ERROR` regardless of which entry point a caller uses.
        """
        self._execution_for(handle)
        if self._terminal is not None:
            return self._terminal
        result = await self._wait(handle)
        try:
            self._validate_transcript(result)
        except AdapterExecutionError:
            self._terminal = _failed(
                handle.execution_id,
                ExecutionErrorCategory.PROTOCOL_ERROR,
                ExecutionErrorCode.PROTOCOL_ERROR,
            )
            return self._terminal
        terminal = self._map_result(handle, result)
        self._terminal = terminal
        return terminal

    def _validate_transcript(self, result: ProcessResult) -> None:
        """Raise the bounded protocol error if any non-empty line is malformed."""
        try:
            CodexEventParser(
                max_line_bytes=self._resource_policy.output_max_bytes_per_stream
            ).parse_lines(result.stdout.splitlines())
        except (TypeError, ValueError):
            raise _bounded_error(
                ExecutionErrorCategory.PROTOCOL_ERROR, ExecutionErrorCode.PROTOCOL_ERROR
            ) from None

    async def collect_outcome(self, handle: ExecutionHandle) -> ExecutionOutcome:
        """Private collection: completed outcomes always carry Memory history."""
        result = await self.collect_result(handle)
        if result.status != "completed":
            return ExecutionOutcome.from_result(result, legacy_error_code=self._legacy_code(result))
        return ExecutionOutcome.from_result(
            result,
            history=[*self._history, {"role": "assistant", "content": result.output or ""}],
            dropped=[],
        )

    # -- internals --------------------------------------------------------

    def _execution_for(self, handle: ExecutionHandle) -> None:
        if not isinstance(handle, ExecutionHandle) or self._request is None:
            raise _configuration_error(ExecutionErrorCode.INVALID_HANDLE)
        ensure_handle_identity(self._request, handle)
        if self._handle is not None and (
            handle.provider_session_id != self._handle.provider_session_id
        ):
            raise _configuration_error(ExecutionErrorCode.INVALID_HANDLE)

    def _wall_seconds(self) -> float:
        """C6: the effective ceiling is the minimum of config, Run and Host wall."""
        deadline = self._request.timeout_seconds if self._request is not None else None
        candidates = [
            float(self._config.timeout_seconds),
            float(self._resource_policy.wall_seconds),
        ]
        if deadline is not None:
            candidates.append(float(deadline))
        return min(candidates)

    async def _wait(self, handle: ExecutionHandle) -> ProcessResult:
        if self._process_result is not None:
            return self._process_result
        if self._managed_id is None:
            raise _configuration_error(ExecutionErrorCode.INVALID_HANDLE)
        self._process_result = await self._host.wait(
            self._managed_id,
            wall_seconds=self._wall_seconds(),
        )
        return self._process_result

    def _stdin_payload(self, request: ExecutionRequest) -> bytes:
        """The one place a prompt becomes bytes for the Host (08 R18).

        ``ExecutionRequest.input`` is bounded in *characters* by the public
        contract, so an over-ceiling UTF-8 encoding is the only case that can
        reach the byte bound; both rejections are ``INVALID_REQUEST`` before
        any Host call, any directory creation and before the payload could be
        truncated. The error carries a static catalog code only - never the
        prompt text and never the exception text.
        """
        try:
            payload = request.input.encode("utf-8")
        except UnicodeEncodeError:
            # A lone surrogate cannot be encoded; it is a malformed request, not
            # an engine failure.
            raise _configuration_error(ExecutionErrorCode.INVALID_REQUEST) from None
        if len(payload) > MAX_STDIN_PAYLOAD_BYTES:
            raise _configuration_error(ExecutionErrorCode.INVALID_REQUEST)
        return payload

    def _workdir_relative(self, request: ExecutionRequest) -> str:
        if request.execution_workdir:
            return str(request.execution_workdir)
        # A caller may run without a prepared Workdir record; the Host still
        # requires an existing directory, so the adapter creates the
        # per-execution one under its own root with owner-only mode. This runs
        # only after the prompt passed its byte/encoding gate (08 R18), so a
        # rejected request never leaves an empty directory behind.
        relative = f"adhoc/{request.execution_id}"
        (self._root / relative).mkdir(parents=True, exist_ok=True, mode=0o700)
        return relative

    def _contained_workdir(self, relative: str) -> Path:
        """Resolve one Workdir strictly beneath the adapter root, or refuse.

        D13: ``(root / relative).resolve()`` alone is not containment - an
        absolute ``execution_workdir`` discards ``root`` entirely and ``..``
        escapes it, both of which merely passed the old ``is_dir()`` check.
        The authoritative validator is the Phase 4 workspace policy
        (``normalize_relative_path``: rejects absolute paths, drive letters,
        ``.``/``..``, encoded separators and non-lowercase components), and the
        resolved path is then re-checked against the root so a symlinked
        directory cannot escape either. Every rejection is ``WORKSPACE_ERROR``
        before any Host call.
        """
        try:
            normalize_relative_path(relative)
        except WorkspacePathError:
            raise _bounded_error(
                ExecutionErrorCategory.WORKSPACE_ERROR, ExecutionErrorCode.WORKSPACE_ERROR
            ) from None
        root = self._root.resolve()
        try:
            candidate = (root / relative).resolve()
        except (OSError, RuntimeError):  # symlink loop, permission fault, ...
            raise _bounded_error(
                ExecutionErrorCategory.WORKSPACE_ERROR, ExecutionErrorCode.WORKSPACE_ERROR
            ) from None
        if not candidate.is_relative_to(root) or candidate == root:
            raise _bounded_error(
                ExecutionErrorCategory.WORKSPACE_ERROR, ExecutionErrorCode.WORKSPACE_ERROR
            )
        if not candidate.is_dir():
            raise _bounded_error(
                ExecutionErrorCategory.WORKSPACE_ERROR, ExecutionErrorCode.WORKSPACE_ERROR
            )
        return candidate

    def _map_result(self, handle: ExecutionHandle, result: ProcessResult) -> ExecutionResult:
        if result.final_state == "cleanup_failed":
            return _failed(
                handle.execution_id,
                ExecutionErrorCategory.RESOURCE_EXHAUSTED,
                ExecutionErrorCode.RESOURCE_EXHAUSTED,
            )
        if result.reason_code == "runtime_host_cancelled":
            return ExecutionResult(
                execution_id=handle.execution_id,
                engine_id=ENGINE_ID,
                protocol_id=PROTOCOL_ID,
                adapter_version=ADAPTER_VERSION,
                status="cancelled",
            )
        if result.reason_code == "runtime_host_wall_timeout":
            return _failed(
                handle.execution_id,
                ExecutionErrorCategory.TIMEOUT,
                ExecutionErrorCode.EXECUTION_TIMEOUT,
            )
        if result.reason_code in (
            "runtime_host_output_limit_exceeded",
            "runtime_host_resource_exceeded",
            "runtime_host_cleanup_race",
        ):
            return _failed(
                handle.execution_id,
                ExecutionErrorCategory.RESOURCE_EXHAUSTED,
                ExecutionErrorCode.RESOURCE_EXHAUSTED,
            )
        if result.reason_code != "runtime_host_exited" or result.exit_code != 0:
            return _failed(
                handle.execution_id,
                ExecutionErrorCategory.ENGINE_UNAVAILABLE,
                ExecutionErrorCode.ENGINE_UNAVAILABLE,
            )
        output, usage = self._completed_output(result)
        return ExecutionResult(
            execution_id=handle.execution_id,
            engine_id=ENGINE_ID,
            protocol_id=PROTOCOL_ID,
            adapter_version=ADAPTER_VERSION,
            status="completed",
            output=output,
            usage=usage,
        )

    @staticmethod
    def _completed_output(result: ProcessResult) -> tuple[str, dict[str, object]]:
        """Extract the final answer and measured usage from bounded stdout.

        Two transcript shapes are accepted because both are real:

        * the measured Codex 0.169.0 CLI shape (D6), where the answer is nested:
          ``{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}``;
          ``item.type == "error"`` is a diagnostic, never an answer;
        * the flat Stage A fixture shape, ``{"type":"message.completed","text":...}``,
          which the earlier contract tests pin.

        Usage stays ``{"status": "unknown"}`` when the provider omitted it; a
        missing counter is never zero-filled, and the measured provider output
        has no ``total_tokens`` at all.
        """
        texts: list[str] = []
        usage: dict[str, object] = {"status": "unknown"}
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            text = _answer_text(value)
            if text is not None:
                texts.append(text)
            parsed = parse_usage(value)
            if parsed.get("status") != "unknown":
                usage = parsed
        return ("\n".join(texts), usage)

    @staticmethod
    def _legacy_code(result: ExecutionResult) -> str:
        if result.error is None:
            return "execution_error"
        if result.error.code is ExecutionErrorCode.EXECUTION_TIMEOUT:
            return "run_timeout"
        if result.error.category is ExecutionErrorCategory.CANCELLED:
            return "execution_cancelled"
        return result.error.code.value


__all__ = [
    "ADAPTER_VERSION",
    "DECLARED_CAPABILITIES",
    "ENGINE_ID",
    "PROTOCOL_ID",
    "CodexCliAdapter",
    "declared_capabilities",
]
