"""Local Sandbox Provider: managed process/resource controls only (08 T11).

The one Provider Phase 4 ships. Its matrix is declared strictly through the
probe registry (defaults: real probes on the running platform; substitutable
per capability for tests and pending_env Linux branches), and every fallback
is labeled non-equivalent (03 §4.6, 08 R-3). It makes no strong-sandbox claim
anywhere: no mount/user/network namespace, no syscall filtering, no network
egress control, no credential isolation, no untrusted-code safety (02 FR-8,
M1). The untrusted-execution gate is hard-coded at every entry:
``arbitrary_command``/``uploaded_code``/``untrusted_multi_tenant`` are
refused with a stable code before any other work, and there is deliberately
no settings path that can flip this (P4-UT-18) - composition has no key to
pass true, and the code check refuses true if it ever arrives (deny-by-code
plus deny-by-absence, defense in depth over the Runner/Registry gates).
"""

import logging
import resource
from collections.abc import Callable, Mapping
from uuid import UUID, uuid4

from .host_models import REASON_UNTRUSTED_TARGET, ProcessSpec
from .sandbox_provider import (
    CAP_CPU_RLIMIT,
    CAP_DISK_ACCOUNTING,
    CAP_DISK_QUOTA,
    CAP_FILE_SIZE_RLIMIT,
    CAP_MEMORY_RLIMIT,
    CAP_OUTPUT_BOUND,
    CAP_PID_COUNT,
    CAP_PROCESS_GROUP,
    CAP_WALL_TIME,
    DEFAULT_PROBES,
    Probe,
    SandboxPolicyError,
    SandboxReservation,
    SupportDeclaration,
    policy_digest,
    resolve_support,
)

logger = logging.getLogger(__name__)

# The RLIMIT triples the Local Provider can apply in the child, keyed by the
# capability id; soft==hard is deliberate: the escalation machine is the
# Supervisor's job, a rlimit soft warning would only double-signal semantics.
_RLIMIT_BY_CAPABILITY: dict[str, int] = {
    CAP_CPU_RLIMIT: resource.RLIMIT_CPU,
    CAP_MEMORY_RLIMIT: resource.RLIMIT_AS,
    CAP_FILE_SIZE_RLIMIT: resource.RLIMIT_FSIZE,
}

_POLICY_FIELD_BY_CAPABILITY: dict[str, str] = {
    CAP_CPU_RLIMIT: "cpu_seconds",
    CAP_MEMORY_RLIMIT: "memory_bytes",
    CAP_FILE_SIZE_RLIMIT: "workdir_file_bytes",
}


# The mechanisms THIS provider actually applies. The cgroup/quota probes
# describe the environment, but the matrix never promises more than the
# implementation: per-Execution group ceilings and fs quota belong to the
# replacement Provider of the Linux full-acceptance environment (08 R-3
# pending_env), and Phase 6's strong sandbox - not to Phase 4's Local lane.
# Declaring them "hard" here would be a silent-limit violation on cgroup-v2
# CI runners.
LOCAL_IMPLEMENTED = frozenset(
    {
        CAP_PROCESS_GROUP,
        CAP_CPU_RLIMIT,
        CAP_MEMORY_RLIMIT,
        CAP_FILE_SIZE_RLIMIT,
        CAP_PID_COUNT,
        CAP_DISK_ACCOUNTING,
        CAP_WALL_TIME,
        CAP_OUTPUT_BOUND,
    }
)


class LocalSandboxProvider:
    """Managed process/resource controls through the declared mechanisms."""

    provider_id = "local"
    provider_version = "v1"

    def __init__(
        self,
        *,
        enforcement_required: bool = True,
        probes: Mapping[str, Probe] | None = None,
    ) -> None:
        # enforcement_required mirrors execution_resource_enforcement_required
        # (shape-only here: the matrix decides per dimension).
        self._enforcement_required = enforcement_required
        self._probes = dict(DEFAULT_PROBES)
        if probes is not None:
            self._probes.update(probes)

    # ------------------------------------------------------------------
    # SandboxProvider contract
    # ------------------------------------------------------------------

    def support_matrix(self) -> Mapping[str, SupportDeclaration]:
        """Probe-declared environment intersected with implemented control.

        Capabilities beyond ``LOCAL_IMPLEMENTED`` report unsupported no
        matter what the environment could offer: the phase never claims
        mechanisms this Provider does not apply (fail closed, zero silent
        limits in either direction).
        """
        matrix: dict[str, SupportDeclaration] = {}
        for name, probe in self._probes.items():
            if name not in LOCAL_IMPLEMENTED:
                matrix[name] = "unsupported"
            else:
                matrix[name] = probe()
        return matrix

    async def prepare(
        self,
        spec: ProcessSpec,
        *,
        run_id: UUID,
        arbitrary_command: bool = False,
        uploaded_code: bool = False,
        untrusted_multi_tenant: bool = False,
    ) -> SandboxReservation:
        """Gate untrusted shapes, resolve support, admit zero-overclaim.

        The untrusted gate precedes everything including matrix probes:
        refused requests produce no reservation and no side effect. With
        enforcement required, a dimension whose ladder is fully unsupported
        rejects the start with ``runtime_host_support_unsupported`` -
        exactly the "no silently ignored required limits" core rule.
        """
        self._deny_untrusted(
            arbitrary_command=arbitrary_command,
            uploaded_code=uploaded_code,
            untrusted_multi_tenant=untrusted_multi_tenant,
        )
        resolutions = resolve_support(
            self.support_matrix(), enforcement_required=self._enforcement_required
        )
        policy = spec.resource_policy
        reservation = SandboxReservation(
            # Unique per admission: it is the dedup key for idempotent
            # release (P4-UT-16), so a constant would collapse executions.
            reservation_id=uuid4(),
            run_id=run_id,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            resolutions=resolutions,
            policy_digest=policy_digest(spec),
            policy_values={
                "cpu_seconds": policy.cpu_seconds,
                "memory_bytes": policy.memory_bytes,
                "max_processes": policy.max_processes,
                "workdir_total_bytes": policy.workdir_total_bytes,
                "workdir_file_bytes": policy.workdir_file_bytes,
                "wall_seconds": policy.wall_seconds,
                "output_max_bytes_per_stream": policy.output_max_bytes_per_stream,
            },
            metadata={
                "approximate": ",".join(
                    r.capability for r in resolutions if r.strength == "approximate"
                )
            },
        )
        if reservation.approximate_labels:
            logger.info(
                "local sandbox admitted approximate controls run_id=%s labels=%s",
                run_id,
                reservation.metadata["approximate"],
            )
        return reservation

    def preexec_for(self, reservation: SandboxReservation) -> Callable[[], None] | None:
        """Child-side hook consuming the T7 runner seam (RLIMIT application).

        Per-dimension resolution decides CPU and memory (only the chosen
        approximation is applied; an ``unenforced`` dimension applies
        nothing, its absence already recorded and warned). File size is the
        per-file complement of the disk row in 03 §4.6 ("per-file rlimit +
        periodic total monitoring"), so RLIMIT_FSIZE is applied whenever the
        mechanism is supported and no hard filesystem quota owns the disk
        dimension instead of it.
        """
        by_dimension = {r.dimension: r for r in reservation.resolutions}
        applied: list[tuple[int, int]] = []

        def add(capability: str) -> None:
            rlimit = _RLIMIT_BY_CAPABILITY.get(capability)
            if rlimit is None:
                return
            value = reservation.policy_values.get(_POLICY_FIELD_BY_CAPABILITY[capability])
            if value is not None:
                applied.append((rlimit, int(value)))

        cpu = by_dimension.get("cpu")
        if cpu is not None and cpu.capability == CAP_CPU_RLIMIT and cpu.strength != "unenforced":
            add(CAP_CPU_RLIMIT)
        memory = by_dimension.get("memory")
        if (
            memory is not None
            and memory.capability == CAP_MEMORY_RLIMIT
            and memory.strength != "unenforced"
        ):
            add(CAP_MEMORY_RLIMIT)
        disk = by_dimension.get("disk")
        fsize_supported = self.support_matrix().get(CAP_FILE_SIZE_RLIMIT, "unsupported")
        if (
            fsize_supported != "unsupported"
            and disk is not None
            and disk.strength != "unenforced"
            and disk.capability != CAP_DISK_QUOTA
        ):
            add(CAP_FILE_SIZE_RLIMIT)
        if not applied:
            return None

        def hook() -> None:  # runs in the forked child before exec
            for which, value in applied:
                resource.setrlimit(which, (value, value))

        return hook

    async def release(self, reservation: SandboxReservation) -> None:
        """Idempotent release: rlimits die with the process group (T12/P4-UT-16)."""
        if reservation.released:
            return
        reservation.released = True

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------

    @staticmethod
    def _deny_untrusted(
        *, arbitrary_command: bool, uploaded_code: bool, untrusted_multi_tenant: bool
    ) -> None:
        # Hard-coded, settings-unreachable (P4-UT-18, AC-10): Phase 6 owns
        # any change to this gate.
        if arbitrary_command or uploaded_code or untrusted_multi_tenant:
            logger.error("local sandbox refused untrusted execution request")
            raise SandboxPolicyError(REASON_UNTRUSTED_TARGET, "untrusted execution gate")
