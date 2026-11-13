"""Sandbox Provider contract and support-matrix vocabulary (Phase 4, 08 T11).

A replaceable interface between the Host and the mechanisms that constrain
managed processes (03 §4.6). Declarations are explicit per capability and per
strength - ``hard`` / ``approximate`` / ``unenforced`` - and the Provider
never claims more than its probe proves: the Local Provider supplies managed
process/resource controls only, with no mount/user/network namespace, syscall
filtering, network egress, credential isolation, or untrusted-code safety
guarantee (02 FR-8, AC-10/M1). The untrusted-execution gate is code, not
configuration: arbitrary commands, uploaded code and untrusted multi-tenant
flags are rejected at every Provider entry and no settings value can flip
them (08 R-3, 03 §4.6 last paragraph).

The cgroup-v2 probes implement the Linux detection branch only; live cgroup
enforcement experiments remain pending_env on this darwin host (08 §5).
"""

import hashlib
import logging
import os
import resource
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from .host_models import (
    REASON_SUPPORT_UNSUPPORTED,
    ProcessSpec,
)

logger = logging.getLogger(__name__)

# What a Provider DECLARES for one mechanism; resolution adds the
# "unenforced" outcome when enforcement is optional and nothing exists.
SupportDeclaration = Literal["hard", "approximate", "unsupported"]
CapabilityStrength = Literal["hard", "approximate", "unenforced"]

# Capability ids (stable, low-cardinality labels for the matrix and alerts).
CAP_PROCESS_GROUP = "process_group"
CAP_CPU_GROUP = "cpu_group"
CAP_CPU_RLIMIT = "cpu_rlimit"
CAP_MEMORY_GROUP = "memory_group"
CAP_MEMORY_RLIMIT = "address_space_rlimit"
CAP_PID_GROUP = "pid_group"
CAP_PID_COUNT = "descendant_count"
CAP_DISK_QUOTA = "fs_quota"
CAP_DISK_ACCOUNTING = "workdir_accounting"
CAP_FILE_SIZE_RLIMIT = "file_size_rlimit"
CAP_WALL_TIME = "wall_time"
CAP_OUTPUT_BOUND = "output_bound"

# The dimension -> preference ladder of 03 §4.6. Each required dimension
# resolves to its best available mechanism: the preferred (hard) row, then
# the explicitly-qualified development fallback (approximate), then
# unenforced (only legal when enforcement is not required; never silent).
DIMENSION_LADDER: dict[str, tuple[str, ...]] = {
    "cpu": (CAP_CPU_GROUP, CAP_CPU_RLIMIT),
    "memory": (CAP_MEMORY_GROUP, CAP_MEMORY_RLIMIT),
    "pid": (CAP_PID_GROUP, CAP_PID_COUNT),
    "disk": (CAP_DISK_QUOTA, CAP_DISK_ACCOUNTING, CAP_FILE_SIZE_RLIMIT),
    "wall": (CAP_WALL_TIME,),
    "output": (CAP_OUTPUT_BOUND,),
}
# Group-level hard ceilings that the phase treats as the full-acceptance
# mechanisms; per 08 R-3 their live experiments are pending_env on darwin.
HARD_ONLY_CANDIDATES = frozenset({CAP_CPU_GROUP, CAP_MEMORY_GROUP, CAP_PID_GROUP, CAP_DISK_QUOTA})


class SandboxPolicyError(RuntimeError):
    """Refusal carrying a stable reason code; zero side effects."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class CapabilityResolution:
    """One dimension's chosen mechanism and honest strength label."""

    dimension: str
    capability: str
    strength: CapabilityStrength
    note: str = ""


@dataclass
class SandboxReservation:
    """One Execution's sandbox admission outcome."""

    reservation_id: UUID
    run_id: UUID
    provider_id: str
    provider_version: str
    resolutions: tuple[CapabilityResolution, ...]
    policy_digest: str
    policy_values: dict[str, int] = field(default_factory=dict)
    released: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def strength_of(self, dimension: str) -> CapabilityStrength | None:
        for resolution in self.resolutions:
            if resolution.dimension == dimension:
                return resolution.strength
        return None

    @property
    def approximate_labels(self) -> tuple[str, ...]:
        return tuple(
            f"{r.dimension}:{r.capability}" for r in self.resolutions if r.strength == "approximate"
        )


def resolve_support(
    matrix: Mapping[str, SupportDeclaration],
    *,
    enforcement_required: bool,
) -> tuple[CapabilityResolution, ...]:
    """Pure ladder resolution over a declared matrix (P4-UT-15/16 core).

    Raises SandboxPolicyError(SUPPORT_UNSUPPORTED) when enforcement is
    required and any dimension has no mechanism at all; when enforcement is
    not required an unavailable dimension is recorded as ``unenforced`` with
    a structured warning - never silently ignored (02 FR-7 failure row).
    """
    resolutions: list[CapabilityResolution] = []
    for dimension, ladder in DIMENSION_LADDER.items():
        chosen: CapabilityResolution | None = None
        for capability in ladder:
            strength = matrix.get(capability, "unsupported")
            if strength == "hard":
                chosen = CapabilityResolution(
                    dimension=dimension, capability=capability, strength="hard"
                )
                break
            if strength == "approximate" and chosen is None:
                # Every fallback is explicitly labeled non-equivalent to the
                # group-hard ceiling it stands in for (03 §4.6, 08 R-3).
                chosen = CapabilityResolution(
                    dimension=dimension,
                    capability=capability,
                    strength="approximate",
                    note="approximate; non-equivalent to the group-hard ceiling (08 R-3)",
                )
        if chosen is None:
            if enforcement_required:
                raise SandboxPolicyError(
                    REASON_SUPPORT_UNSUPPORTED,
                    f"dimension {dimension} has no supported mechanism",
                )
            logger.warning(
                "runtime host dimension unenforced dimension=%s ladder=%s",
                dimension,
                ",".join(ladder),
            )
            chosen = CapabilityResolution(
                dimension=dimension, capability="none", strength="unenforced"
            )
        resolutions.append(chosen)
    return tuple(resolutions)


Probe = Callable[[], SupportDeclaration]


def probe_process_group() -> SupportDeclaration:
    return "hard" if os.name == "posix" else "unsupported"


def probe_wall_time() -> SupportDeclaration:
    return "hard"


def probe_output_bound() -> SupportDeclaration:
    return "hard"


def probe_workdir_accounting() -> SupportDeclaration:
    return "approximate"


def probe_descendant_count() -> SupportDeclaration:
    return "approximate"  # supervisor-side reactive counting, not isolation


def _rlimit_available(which: int) -> SupportDeclaration:
    try:
        import resource

        resource.getrlimit(which)
    except (ImportError, ValueError, OSError):  # pragma: no cover - POSIX has all three
        return "unsupported"
    return "approximate"


def probe_cpu_rlimit() -> SupportDeclaration:
    return _rlimit_available(_resource_constant("RLIMIT_CPU"))


def probe_address_space_rlimit() -> SupportDeclaration:
    """Applicability, not existence: fork-probe one real RLIMIT_AS set.

    macOS rejects setrlimit(RLIMIT_AS) below the address space an interpreter
    already maps, so "the constant exists" would overclaim. The fork child
    only calls setrlimit and _exit; its outcome is the honest declaration:
    ``approximate`` where an FR-10-scale limit actually applies (Linux and
    cooperative hosts), ``unsupported`` where it cannot (fail closed; the
    ladder then refuses under enforcement_required or records unenforced
    with a warning under false - never a silent limit).
    """
    which = _resource_constant("RLIMIT_AS")
    try:
        current = resource.getrlimit(which)
    except (ImportError, ValueError, OSError):  # pragma: no cover - non-POSIX
        return "unsupported"
    if current[0] != resource.RLIM_INFINITY or current[1] != resource.RLIM_INFINITY:
        # An inherited cap already exists; treat the mechanism as available
        # at whatever the deployment already applied.
        return "approximate"
    probe_limit = 256 * 1024 * 1024
    try:
        pid = os.fork()
    except OSError:  # pragma: no cover - fork exhaustion
        return "unsupported"
    if pid == 0:
        try:
            resource.setrlimit(which, (probe_limit, probe_limit))
            os._exit(0)
        except (ValueError, OSError):
            os._exit(1)
    try:
        _, status = os.waitpid(pid, 0)
    except OSError:  # pragma: no cover
        return "unsupported"
    return "approximate" if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0 else "unsupported"


def probe_file_size_rlimit() -> SupportDeclaration:
    return _rlimit_available(_resource_constant("RLIMIT_FSIZE"))


def _resource_constant(name: str) -> int:
    import resource

    return getattr(resource, name)


def _cgroup_controllers(root: Path = Path("/sys/fs/cgroup")) -> list[str] | None:
    """Read the unified-hierarchy controller list; None when unreadable."""
    try:
        return (root / "cgroup.controllers").read_text().split()
    except OSError:
        return None


def probe_cgroup_v2_memory(
    root: Path = Path("/sys/fs/cgroup"),
) -> SupportDeclaration:
    """Linux cgroup v2 detection branch only; live experiments pending_env.

    Absent hierarchy or unlisted controllers declare ``unsupported``
    (fail closed, never a guess).
    """
    listed = _cgroup_controllers(root)
    if listed is None:
        return "unsupported"
    return "hard" if "memory" in listed else "unsupported"


def probe_cgroup_v2_pids(root: Path = Path("/sys/fs/cgroup")) -> SupportDeclaration:
    listed = _cgroup_controllers(root)
    if listed is None:
        return "unsupported"
    return "hard" if "pids" in listed else "unsupported"


def probe_cgroup_v2_cpu(root: Path = Path("/sys/fs/cgroup")) -> SupportDeclaration:
    listed = _cgroup_controllers(root)
    if listed is None:
        return "unsupported"
    return "hard" if "cpu" in listed else "unsupported"


def probe_fs_quota() -> SupportDeclaration:
    """Filesystem/project quota detection: no probe proves it here."""
    return "unsupported"


DEFAULT_PROBES: dict[str, Probe] = {
    CAP_PROCESS_GROUP: probe_process_group,
    CAP_CPU_GROUP: probe_cgroup_v2_cpu,
    CAP_CPU_RLIMIT: probe_cpu_rlimit,
    CAP_MEMORY_GROUP: probe_cgroup_v2_memory,
    CAP_MEMORY_RLIMIT: probe_address_space_rlimit,
    CAP_PID_GROUP: probe_cgroup_v2_pids,
    CAP_PID_COUNT: probe_descendant_count,
    CAP_DISK_QUOTA: probe_fs_quota,
    CAP_DISK_ACCOUNTING: probe_workdir_accounting,
    CAP_FILE_SIZE_RLIMIT: probe_file_size_rlimit,
    CAP_WALL_TIME: probe_wall_time,
    CAP_OUTPUT_BOUND: probe_output_bound,
}


def policy_digest(spec: ProcessSpec) -> str:
    payload = spec.resource_policy.model_dump_json()
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


@runtime_checkable
class SandboxProvider(Protocol):
    """Replaceable sandbox contract: prepare/start-hooks/release (03 §2)."""

    provider_id: str
    provider_version: str

    def support_matrix(self) -> Mapping[str, SupportDeclaration]: ...

    async def prepare(
        self,
        spec: ProcessSpec,
        *,
        run_id: UUID,
        arbitrary_command: bool = False,
        uploaded_code: bool = False,
        untrusted_multi_tenant: bool = False,
    ) -> SandboxReservation: ...

    def preexec_for(self, reservation: SandboxReservation) -> Callable[[], None] | None: ...

    async def release(self, reservation: SandboxReservation) -> None: ...
