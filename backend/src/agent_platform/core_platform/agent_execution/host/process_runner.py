"""Trusted-target runner: spawn, process group, and bounded I/O (08 T7, 02 FR-2).

The allowlist is code, not configuration: a target must be registered as a
fixed ``executable_id`` with a resolved executable path, a fixed argument
prefix, and a strict bounded-parameter pattern (08 §1.9, AC-6 gate). Nothing
here accepts a caller-supplied command, interpreter path or arbitrary argv,
and validation happens **before** ``exec`` (P4-UT-02).

Spawn uses ``asyncio.create_subprocess_exec`` with ``start_new_session=True``
so every engine runs in its own process group that the Supervisor can TERM/KILL
as one unit. stdout/stderr are pumped with independent byte bounds and
per-stream backpressure: the stream that breaches its limit stops consuming
(P4-UT-03), leaving the supervisor to terminate the group on overflow. Any
failure after spawn cleans up in reverse through the same managed handle and
fails closed (P4-UT-20). Secret values in the environment map never reach
logs or error text (P4-UT-21).

A spec may carry one bounded stdin payload (08 R18). Only that spec gets a
stdin pipe - every other target keeps the historical ``DEVNULL`` start - and
the write plus its EOF-close run inside a single bounded deadline, so a child
that never reads or one that exits early fails the start closed instead of
hanging the Worker.
"""

import asyncio
import logging
import os
import re
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from .host_models import (
    REASON_PIPE_SETUP_FAILED,
    REASON_SPAWN_FAILED,
    REASON_UNTRUSTED_TARGET,
    ExitObservation,
    ManagedProcess,
    ProcessSpec,
    ResourcePolicy,
)
from .launch_plan import SandboxLaunchPlan
from .process_identity import capture_start_token_async, read_pgid

logger = logging.getLogger(__name__)

# Parameters are bounded lowercase tokens (case names, sizes); "/" and "\" are
# deliberately excluded so a parameter can never smuggle a path.
_PARAMETER_TOKEN = re.compile(r"^[a-z0-9][a-z0-9:._=-]{0,63}$")

# One bounded deadline for the opt-in stdin channel (08 R18): it covers the
# single write plus its drain. A child that never reads (deadlock) or exits
# early must fail the start within a known window rather than hang the Worker.
STDIN_DELIVERY_TIMEOUT_SECONDS = 10.0


class UntrustedTargetError(ValueError):
    """Target/argv rejected before spawn; carries only a stable code+id."""

    def __init__(self, detail: str, executable_id: str = "") -> None:
        super().__init__(f"{REASON_UNTRUSTED_TARGET}: {detail}")
        self.detail = detail
        self.executable_id = executable_id


class ProcessSpawnError(RuntimeError):
    """Fail-closed spawn/pipe/registration failure after reverse cleanup."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class TrustedTargetDescriptor:
    """One allowlisted fixed executable: path is code, parameters are bounded.

    ``fixed_prefix`` is prepended verbatim to every argv (it pins which script
    of the repository the interpreter runs); only the remaining caller tokens
    are parameter-checked, and only against ``parameter_pattern``.
    """

    executable_id: str
    executable_path: str
    fixed_prefix: tuple[str, ...]
    max_parameters: int = 8
    parameter_pattern: re.Pattern[str] = field(default=_PARAMETER_TOKEN)

    def __post_init__(self) -> None:
        if not os.path.isabs(self.executable_path):
            raise ValueError("trusted executable path must be absolute")

    def resolve(self, spec: ProcessSpec) -> tuple[str, ...]:
        """Full argv for ``exec``, or ``UntrustedTargetError`` before any spawn."""
        if spec.executable_id != self.executable_id:
            raise UntrustedTargetError("executable id mismatch", spec.executable_id)
        argv = tuple(spec.argv)
        prefix_length = len(self.fixed_prefix)
        if argv[:prefix_length] != self.fixed_prefix:
            raise UntrustedTargetError("argv prefix is not the fixed target", self.executable_id)
        parameters = argv[prefix_length:]
        if len(parameters) > self.max_parameters:
            raise UntrustedTargetError("too many parameters", self.executable_id)
        for token in parameters:
            if token in ("", ".", "..") or not self.parameter_pattern.fullmatch(token):
                raise UntrustedTargetError("parameter token rejected", self.executable_id)
        return (self.executable_path,) + argv


class TrustedTargetRegistry:
    """The code-constant allowlist of executable ids the Host may run."""

    def __init__(self, descriptors: tuple[TrustedTargetDescriptor, ...]) -> None:
        self._by_id = {descriptor.executable_id: descriptor for descriptor in descriptors}
        if len(self._by_id) != len(descriptors):
            raise ValueError("duplicate trusted executable id")

    @property
    def executable_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    def resolve(self, spec: ProcessSpec) -> tuple[str, ...]:
        descriptor = self._by_id.get(spec.executable_id)
        if descriptor is None:
            raise UntrustedTargetError("executable id not registered", spec.executable_id)
        return descriptor.resolve(spec)


class _StreamRecorder:
    """One bounded output stream: independent limit, backpressure on breach."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.chunks: list[bytes] = []
        self.total = 0
        self.truncated = False
        self.overflowed = asyncio.Event()
        self.read_error = False
        self.error_event = asyncio.Event()

    def feed(self, data: bytes) -> bool:
        """Append ``data``; returns False (and stops reads) once over limit."""
        if self.total + len(data) > self.max_bytes:
            room = self.max_bytes - self.total
            if room > 0:
                self.chunks.append(data[:room])
                self.total = self.max_bytes
            self.truncated = True
            self.overflowed.set()
            return False
        self.chunks.append(data)
        self.total += len(data)
        return True

    def payload(self) -> bytes:
        return b"".join(self.chunks)


class StreamPump:
    """Bounded non-blocking pumps for stdout/stderr of one started process."""

    def __init__(self, process: asyncio.subprocess.Process, max_bytes_per_stream: int) -> None:
        self.stdout = _StreamRecorder(max_bytes_per_stream)
        self.stderr = _StreamRecorder(max_bytes_per_stream)
        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._process = process

    def start(self) -> None:
        self._tasks = (
            asyncio.create_task(self._pump(self._process.stdout, self.stdout)),
            asyncio.create_task(self._pump(self._process.stderr, self.stderr)),
        )

    async def _pump(self, stream: asyncio.StreamReader | None, sink: _StreamRecorder) -> None:
        if stream is None:  # pragma: no cover - PIPE always configured here
            return
        chunk_size = min(65_536, max(sink.max_bytes, 1))
        try:
            while True:
                data = await stream.read(chunk_size)
                if not data:
                    break
                if not sink.feed(data):
                    # FR-2's "stop reading" means stop RETAINING: after the
                    # breach the pump keeps draining while discarding, because
                    # a child blocked on a full pipe cannot complete exit
                    # until the pipe empties (kernel behaviour on Darwin;
                    # harmless elsewhere). The breach itself has already been
                    # recorded and the Supervisor terminates the group.
                    while await stream.read(chunk_size):
                        pass
                    break
        except (OSError, asyncio.IncompleteReadError) as exc:
            sink.read_error = True
            logger.warning("runtime host pipe read failed errno=%s", getattr(exc, "errno", None))
            sink.error_event.set()

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = ()

    async def drain(self, timeout: float = 1.0) -> None:
        """Let the pumps finish at EOF (bounded), then force-close leftovers."""
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True), timeout=timeout
                )
            except TimeoutError:
                pass
        await self.aclose()


@dataclass
class StartedProcess:
    """Live handle bundle the Supervisor and Host operate through."""

    managed: ManagedProcess
    process: asyncio.subprocess.Process
    pump: StreamPump
    spec: ProcessSpec

    @property
    def managed_id(self) -> UUID:
        return self.managed.managed_id

    async def wait_exit(self, timeout: float) -> ExitObservation:
        """Await the process exit up to ``timeout``; ``alive`` means still running."""
        try:
            code = await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except TimeoutError:
            return ExitObservation("alive", None)
        return ExitObservation("exited", code)

    def output(self) -> tuple[bytes, bytes]:
        return (self.pump.stdout.payload(), self.pump.stderr.payload())


PreexecFactory = Callable[[ResourcePolicy], Callable[[], None]]


class ProcessRunner:
    """Validate-then-spawn for trusted targets with identity capture (FR-2)."""

    def __init__(
        self,
        registry: TrustedTargetRegistry,
        *,
        identity_capture: Callable[[int], Awaitable[str | None]] | None = None,
        clock: Callable[[], float] | None = None,
        preexec_factory: PreexecFactory | None = None,
        stdin_delivery_timeout_seconds: float = STDIN_DELIVERY_TIMEOUT_SECONDS,
    ) -> None:
        if stdin_delivery_timeout_seconds <= 0:
            raise ValueError("stdin delivery timeout must be positive")
        self._registry = registry
        self._identity_capture = identity_capture or capture_start_token_async
        self._clock = clock or time.time
        self._preexec_factory = preexec_factory
        self._stdin_timeout = stdin_delivery_timeout_seconds

    def resolve_trusted(self, spec: ProcessSpec) -> tuple[str, ...]:
        """Allowlist gate exposed to the Host for pre-record validation."""
        return self._registry.resolve(spec)

    async def start(
        self,
        spec: ProcessSpec,
        *,
        run_id: UUID,
        managed_id: UUID,
        host_id: str,
        host_instance_id: str,
        sandbox_provider: str,
        working_dir: Path,
        preexec: Callable[[], None] | None = None,
        launch_plan: SandboxLaunchPlan | None = None,
    ) -> StartedProcess:
        """Resolve through the allowlist, spawn in a new session, capture identity.

        ``run_id``/``managed_id``/identity fields are caller (Host) supplied;
        the Runner never derives durable identities.

        Ordering for the opt-in stdin channel (08 R18) is deliberate: the pumps
        start before the payload is written, so a child whose stdout fills a
        pipe cannot deadlock against the Host writing stdin; the handle is
        assigned before delivery, so a failed delivery still runs the existing
        ``hard_cleanup`` (which closes the pumps only through the handle).
        """
        argv = self._registry.resolve(spec)  # raises before any side effect
        spawn_dir = working_dir if launch_plan is None else (launch_plan.working_dir or working_dir)
        spawn_env = dict(spec.environment)
        if launch_plan is not None:
            # Provider-generated argv/environment: the client never supplies it.
            argv = launch_plan.argv
            spawn_env = dict(launch_plan.environment)
        if not spawn_dir.is_dir():
            raise ProcessSpawnError(REASON_PIPE_SETUP_FAILED, "workdir missing at spawn")

        # The stdin channel must also fit the process wall budget (D22). The
        # configured delivery timeout is only an upper bound: a tighter wall
        # ceiling wins, including time already spent spawning and capturing
        # identity. This uses the same monotonic clock as the delivery drain.
        start_monotonic = asyncio.get_running_loop().time()
        preexec_fn = preexec or (
            self._preexec_factory(spec.resource_policy) if self._preexec_factory else None
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                # 08 R18: only a spec that carries a payload gets a pipe; every
                # other target keeps the historical DEVNULL start.
                stdin=(
                    asyncio.subprocess.PIPE
                    if spec.stdin_payload is not None
                    else asyncio.subprocess.DEVNULL
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(spawn_dir),
                env=spawn_env,
                start_new_session=True,
                preexec_fn=preexec_fn,
            )
        except OSError as exc:
            logger.error(
                "runtime host spawn failed errno=%s executable_id=%s run_id=%s",
                getattr(exc, "errno", None),
                spec.executable_id,
                run_id,
            )
            raise ProcessSpawnError(REASON_SPAWN_FAILED) from exc

        started = None
        try:
            start_token = await self._identity_capture(process.pid)
            pgid = read_pgid(process.pid) or process.pid
            managed = ManagedProcess(
                managed_id=managed_id,
                run_id=run_id,
                host_id=host_id,
                host_instance_id=host_instance_id,
                sandbox_provider=sandbox_provider,
                state="starting",
                os_pid=process.pid,
                process_group_id=pgid,
                start_token=None if start_token is None else str(start_token),
                command_digest=spec.command_digest,
                workdir_relative_path=spec.workdir_relative_path,
                started_at_posix=self._clock(),
            ).transition_to("running")
            pump = StreamPump(process, spec.resource_policy.output_max_bytes_per_stream)
            pump.start()
            started = StartedProcess(managed=managed, process=process, pump=pump, spec=spec)
            if spec.stdin_payload is not None:
                await self._deliver_stdin(started, spec.stdin_payload, start_monotonic)
            return started
        except BaseException:
            # Reverse-order cleanup through the same handle: kill the group,
            # reap, stop the pumps. A failure that cannot confirm cleanup is
            # surfaced too - never an orphan left "unowned" (P4-UT-20).
            await self.hard_cleanup(started, process=process)
            raise

    async def _deliver_stdin(
        self, started: StartedProcess, payload: bytes, start_monotonic: float
    ) -> None:
        """Write one bounded payload then EOF, inside one deadline (08 R18).

        Both failure modes are the same fail-closed outcome: a child that closes
        its end early (``EPIPE``/``ECONNRESET`` -> ``OSError``) and a child that
        never reads (deadline -> ``TimeoutError``) raise the existing
        ``REASON_PIPE_SETUP_FAILED``. ``close()`` is mandatory because
        ``codex exec … -`` starts its turn only after reading EOF; waiting on
        ``wait_closed()`` is deliberately skipped (it logs asyncio noise after
        the child exits and buys nothing). Only stable facts are logged - never
        the payload.

        D22: the deadline is the smaller of the configured delivery timeout and
        the process wall budget left at this point. A 1-second wall therefore
        cannot turn into a 10-second stdin wait.
        """
        stdin = started.process.stdin
        if stdin is None:  # pragma: no cover - PIPE is configured for a payload
            raise ProcessSpawnError(REASON_PIPE_SETUP_FAILED, "stdin pipe unavailable")
        loop = asyncio.get_running_loop()
        wall_remaining = max(
            0.0,
            float(started.spec.resource_policy.wall_seconds) - (loop.time() - start_monotonic),
        )
        deadline = loop.time() + min(self._stdin_timeout, wall_remaining)
        reason: str | None = None
        try:
            stdin.write(payload)
            await asyncio.wait_for(stdin.drain(), timeout=max(0.0, deadline - loop.time()))
        except TimeoutError:
            reason = "timeout"
        except OSError:
            reason = "closed_early"
        try:
            stdin.close()
        except OSError:  # pragma: no cover - close rarely fails after a write error
            reason = reason or "closed_early"
        if reason is not None:
            logger.warning(
                "runtime host stdin delivery failed reason=%s executable_id=%s run_id=%s",
                reason,
                started.spec.executable_id,
                started.managed.run_id,
            )
            raise ProcessSpawnError(REASON_PIPE_SETUP_FAILED, "stdin delivery failed")

    async def hard_cleanup(
        self, started: StartedProcess | None, *, process: asyncio.subprocess.Process | None = None
    ) -> None:
        """SIGKILL the group and reap; safe to call once on a failed start."""
        target = started.process if started is not None else process
        if target is None:  # pragma: no cover - defensive
            return
        pgid = read_pgid(target.pid)
        if started is not None:
            await started.pump.aclose()
        if target.returncode is None:
            try:
                os.killpg(target.pid if pgid is None else pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(target.wait(), timeout=5)
            except TimeoutError:  # pragma: no cover - KILL is uncatchable
                # No OS identity in logs (P4-UT-21): the group was killed but
                # not reaped; the durable record and alert lanes carry the
                # correlation, this line only states the fact.
                logger.error("runtime host spawn cleanup could not reap the killed group")
