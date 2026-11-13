"""Two process-capable test Adapters sharing one RuntimeHost (08 T10, AC-1).

These are the engine triples that prove the Host has no Engine-specific
branches: distinct engine/protocol/version identities, distinct protocol
parsers (line-JSON vs key=value blocks), identical Host usage. Adapters
contain no direct spawn/signal/resource code (an AST pin test enforces it):
everything OS-shaped goes through the RuntimeHost contract, and the public
ExecutionHandle never carries a PID (08 R-4b - ``process_id`` stays unset).
"""

import json
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from agent_platform.core_platform.agent_execution.contracts import (
    AgentEvent,
    EngineCapabilities,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessResult,
    ProcessSpec,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.process_runner import (
    TrustedTargetDescriptor,
    TrustedTargetRegistry,
)
from agent_platform.core_platform.agent_execution.host.runtime_host import RuntimeHost

TRUSTED_TARGET_PATH = str(Path(__file__).resolve().parent / "trusted_targets.py")
TRUSTED_EXECUTABLE_ID = "trusted-test-target"

_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=67_108_864,
    max_processes=16,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=65_536,
)


def build_trusted_registry() -> TrustedTargetRegistry:
    """The code-constant allowlist: interpreter + this repository's target file."""
    return TrustedTargetRegistry(
        (
            TrustedTargetDescriptor(
                executable_id=TRUSTED_EXECUTABLE_ID,
                executable_path=sys.executable,
                fixed_prefix=(TRUSTED_TARGET_PATH,),
            ),
        )
    )


def make_spec(
    case: str, parameter: str | None = None, *, workdir_relative: str = "aa11/bb22"
) -> ProcessSpec:
    argv = (
        (TRUSTED_TARGET_PATH, case) if parameter is None else (TRUSTED_TARGET_PATH, case, parameter)
    )
    return ProcessSpec(
        executable_id=TRUSTED_EXECUTABLE_ID,
        argv=argv,
        environment={"PATH": "/usr/bin:/bin"},
        workdir_relative_path=workdir_relative,
        resource_policy=_POLICY,
    )


def make_request(
    engine: str, protocol: str, *, case: str, parameter: str = "0"
) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=uuid4(),
        engine_id=engine,
        protocol_id=protocol,
        adapter_version="v1",
        tenant_id="phase4-adapter-test",
        agent_id=uuid4(),
        input="process adapter",
        config={"case": case, "parameter": parameter},
        execution_workdir="aa11/bb22",
    )


class _HostBackedAdapter:
    """Shared plumbing: only identity tuples and parsing differ per adapter."""

    _CASE = "unset"
    _ENGINE_ID = "unset"
    _PROTOCOL_ID = "unset"

    def __init__(self, host: RuntimeHost, *, root: Path) -> None:
        self._host = host
        self._root = root
        self._managed_by_execution: dict[UUID, UUID] = {}
        self._results: dict[UUID, tuple[ProcessResult, ExecutionResult]] = {}

    @property
    def engine_id(self) -> str:
        return self._ENGINE_ID

    @property
    def protocol_id(self) -> str:
        return self._PROTOCOL_ID

    @property
    def adapter_version(self) -> str:
        return "v1"

    async def get_capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(native_events=True, cancellation=True, workspace_required=True)

    async def start(self, request: ExecutionRequest) -> ExecutionHandle:
        case = str(request.config.get("case", self._CASE))
        if case != self._CASE:
            raise ValueError(f"{self.engine_id} runs only its own trusted case")
        parameter = str(request.config.get("parameter", "0"))
        relative = str(request.execution_workdir or f"adhoc/{request.execution_id}")
        working_dir = self._root / relative
        working_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        spec = make_spec(case, parameter, workdir_relative=relative)
        managed = await self._host.start(
            spec, run_id=request.execution_id, tenant_id=request.tenant_id, working_dir=working_dir
        )
        self._managed_by_execution[request.execution_id] = managed.managed_id
        # R-4b pin: the public handle carries no OS identity; process_id stays
        # at its default None even for Host-managed executions.
        return ExecutionHandle(
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version="v1",
            provider_session_id=str(managed.managed_id),
        )

    async def cancel(self, handle: ExecutionHandle) -> None:
        managed_id = self._managed_by_execution.get(handle.execution_id)
        if managed_id is None:
            raise ValueError("unknown handle")
        if handle.execution_id in self._results:
            return  # idempotent: the adapter returns the recorded progress
        await self._host.cancel(managed_id)

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        cached = self._results.get(handle.execution_id)
        if cached is not None:
            return cached[1]
        managed_id = self._managed_by_execution.get(handle.execution_id)
        if managed_id is None:
            raise ValueError("unknown handle")
        host_result = await self._host.wait(managed_id)
        mapped = self._map_result(handle, host_result)
        self._results[handle.execution_id] = (host_result, mapped)
        return mapped

    async def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        cached = self._results.get(handle.execution_id)
        if cached is None:
            await self.collect_result(handle)
            cached = self._results[handle.execution_id]
        for event in self._parse_events(handle, cached[0]):
            yield event

    # Parser hooks (overridden per adapter) --------------------------------

    def _map_result(self, handle: ExecutionHandle, host_result: ProcessResult) -> ExecutionResult:
        raise NotImplementedError

    def _parse_events(
        self, handle: ExecutionHandle, host_result: ProcessResult
    ) -> list[AgentEvent]:
        raise NotImplementedError

    def _base(self, handle: ExecutionHandle) -> dict:
        return {
            "execution_id": handle.execution_id,
            "engine_id": self.engine_id,
            "protocol_id": self.protocol_id,
            "adapter_version": "v1",
        }

    def _common_failure(self, handle: ExecutionHandle, host_result: ProcessResult):
        """Shared status mapping: every Host reason lands on a catalog code."""
        if host_result.final_state == "cleanup_failed":
            return ExecutionResult(
                **self._base(handle),
                status="failed",
                error=ExecutionError(
                    category=ExecutionErrorCategory.RESOURCE_EXHAUSTED,
                    code=ExecutionErrorCode.RESOURCE_EXHAUSTED,
                ),
            )
        if host_result.reason_code == "runtime_host_cancelled":
            return ExecutionResult(**self._base(handle), status="cancelled")
        if host_result.reason_code == "runtime_host_wall_timeout":
            return ExecutionResult(
                **self._base(handle),
                status="failed",
                error=ExecutionError(
                    category=ExecutionErrorCategory.TIMEOUT,
                    code=ExecutionErrorCode.EXECUTION_TIMEOUT,
                ),
            )
        if host_result.reason_code == "runtime_host_output_limit_exceeded":
            return ExecutionResult(
                **self._base(handle),
                status="failed",
                error=ExecutionError(
                    category=ExecutionErrorCategory.RESOURCE_EXHAUSTED,
                    code=ExecutionErrorCode.RESOURCE_EXHAUSTED,
                ),
            )
        return None


class LineJsonProcessAdapter(_HostBackedAdapter):
    """Protocol A: one JSON object per stdout line."""

    _CASE = "json-events"
    _ENGINE_ID = "proc-json"
    _PROTOCOL_ID = "line-json"

    def _map_result(self, handle: ExecutionHandle, host_result: ProcessResult) -> ExecutionResult:
        mapped = self._common_failure(handle, host_result)
        if mapped is not None:
            return mapped
        if host_result.exit_code == 0:
            answer = next(
                (
                    obj["payload"].get("answer", "")
                    for obj in _json_lines(host_result.stdout)
                    if obj.get("type") == "engine.run.completed"
                ),
                "",
            )
            return ExecutionResult(**self._base(handle), status="completed", output=answer)
        return ExecutionResult(
            **self._base(handle),
            status="failed",
            error=ExecutionError(
                category=ExecutionErrorCategory.ENGINE_UNAVAILABLE,
                code=ExecutionErrorCode.ENGINE_UNAVAILABLE,
            ),
        )

    def _parse_events(
        self, handle: ExecutionHandle, host_result: ProcessResult
    ) -> list[AgentEvent]:
        events = []
        for index, obj in enumerate(_json_lines(host_result.stdout)):
            events.append(
                AgentEvent(
                    **self._base(handle),
                    event_id=uuid4(),
                    sequence=index + 1,
                    event_type=obj["type"],
                    source="engine_native",
                    timestamp=datetime.now(UTC),
                    payload=obj.get("payload", {}),
                    engine_session_id=str(handle.provider_session_id),
                )
            )
        return events


class KeyValueProcessAdapter(_HostBackedAdapter):
    """Protocol B: blank-line-separated key=value blocks (distinct parser)."""

    _CASE = "kv-events"
    _ENGINE_ID = "proc-kv"
    _PROTOCOL_ID = "key-value"

    def _map_result(self, handle: ExecutionHandle, host_result: ProcessResult) -> ExecutionResult:
        mapped = self._common_failure(handle, host_result)
        if mapped is not None:
            return mapped
        records = _kv_records(host_result.stdout)
        if host_result.exit_code == 0:
            answer = next(
                (
                    record.get("answer", "")
                    for record in records
                    if record.get("type") == "engine.run.completed"
                ),
                "",
            )
            return ExecutionResult(**self._base(handle), status="completed", output=answer)
        return ExecutionResult(
            **self._base(handle),
            status="failed",
            error=ExecutionError(
                category=ExecutionErrorCategory.PROTOCOL_ERROR,
                code=ExecutionErrorCode.PROTOCOL_ERROR,
            ),
        )

    def _parse_events(
        self, handle: ExecutionHandle, host_result: ProcessResult
    ) -> list[AgentEvent]:
        events = []
        for index, record in enumerate(_kv_records(host_result.stdout)):
            payload = {key: value for key, value in record.items() if key not in ("seq", "type")}
            events.append(
                AgentEvent(
                    **self._base(handle),
                    event_id=uuid4(),
                    sequence=index + 1,
                    event_type=record.get("type", "engine.unknown"),
                    source="engine_native",
                    timestamp=datetime.now(UTC),
                    payload=payload,
                    engine_session_id=str(handle.provider_session_id),
                )
            )
        return events


def _json_lines(stdout: bytes) -> list[dict]:
    parsed = []
    for line in stdout.splitlines():
        if line.strip():
            parsed.append(json.loads(line))
    return parsed


def _kv_records(stdout: bytes) -> list[dict]:
    records = []
    for block in stdout.decode("utf-8", "ignore").split("\n\n"):
        record = {}
        for line in block.strip().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                record[key.strip()] = value.strip()
        if record:
            records.append(record)
    return records
