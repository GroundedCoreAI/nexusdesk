"""Docker strong Sandbox Provider (T-08, 02 FR-4–FR-6).

Each Execution runs as an unprivileged, read-only container with dropped
capabilities, no-new-privileges, PID/memory/CPU ceilings, a minimal per-Run
Workdir mount, and default-deny networking. An allowlist requires a managed
egress proxy endpoint; without one the provider fails closed rather than opening
direct egress. Missing Docker/image/support never falls back to the Host.
"""

import asyncio
import logging
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import UUID, uuid4

from .host_models import ProcessSpec
from .launch_plan import SandboxLaunchPlan
from .network_policy import NetworkPolicy
from .sandbox_provider import (
    CAP_CPU_GROUP,
    CAP_CPU_RLIMIT,
    CAP_DISK_ACCOUNTING,
    CAP_DISK_QUOTA,
    CAP_FILE_SIZE_RLIMIT,
    CAP_MEMORY_GROUP,
    CAP_MEMORY_RLIMIT,
    CAP_OUTPUT_BOUND,
    CAP_PID_COUNT,
    CAP_PID_GROUP,
    CAP_PROCESS_GROUP,
    CAP_WALL_TIME,
    SandboxPolicyError,
    SandboxReservation,
    SupportDeclaration,
    policy_digest,
    resolve_support,
)

logger = logging.getLogger(__name__)

_DOCKER_IMPLEMENTED: dict[str, SupportDeclaration] = {
    CAP_PROCESS_GROUP: "hard",
    CAP_CPU_GROUP: "hard",
    CAP_MEMORY_GROUP: "hard",
    CAP_PID_GROUP: "hard",
    CAP_DISK_QUOTA: "unsupported",
    CAP_DISK_ACCOUNTING: "approximate",
    CAP_FILE_SIZE_RLIMIT: "approximate",
    CAP_WALL_TIME: "hard",
    CAP_OUTPUT_BOUND: "hard",
    # Container-level total CPU time is enforced by the Supervisor/wall machine;
    # the rlimit labels belong to the Local provider only.
    CAP_CPU_RLIMIT: "unsupported",
    CAP_MEMORY_RLIMIT: "unsupported",
    CAP_PID_COUNT: "approximate",
}


def default_docker_probe() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, timeout=10, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


CallableProbe = Callable[[], bool]


class DockerSandboxProvider:
    provider_id = "docker"
    provider_version = "v1"

    def __init__(
        self,
        *,
        image: str,
        docker_probe: CallableProbe | None = None,
        enforcement_required: bool = True,
        network_policy: NetworkPolicy | None = None,
        proxy_endpoint: str | None = None,
    ) -> None:
        self._image = image.strip()
        self._probe = docker_probe or default_docker_probe
        self._enforcement_required = enforcement_required
        self._network_policy = network_policy or NetworkPolicy()
        self._proxy_endpoint = proxy_endpoint
        self._docker_ready: bool | None = None

    def support_matrix(self) -> Mapping[str, SupportDeclaration]:
        if not self._available_probe():
            return {name: "unsupported" for name in _DOCKER_IMPLEMENTED}
        return dict(_DOCKER_IMPLEMENTED)

    def _available_probe(self) -> bool:
        if self._docker_ready is None:
            self._docker_ready = bool(self._probe())
        return self._docker_ready

    async def prepare(
        self,
        spec: ProcessSpec,
        *,
        run_id: UUID,
        arbitrary_command: bool = False,
        uploaded_code: bool = False,
        untrusted_multi_tenant: bool = False,
    ) -> SandboxReservation:
        # The strong provider is the only lane allowed to accept these flags,
        # but admission still requires an explicit deployment opt-in elsewhere.
        if not self._image or not self._available_probe():
            raise SandboxPolicyError(
                "runtime_host_sandbox_unavailable", "docker provider unavailable"
            )
        resolutions = resolve_support(
            self.support_matrix(), enforcement_required=self._enforcement_required
        )
        return SandboxReservation(
            reservation_id=uuid4(),
            run_id=run_id,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            resolutions=resolutions,
            policy_digest=policy_digest(spec),
            policy_values={
                "cpu_seconds": spec.resource_policy.cpu_seconds,
                "memory_bytes": spec.resource_policy.memory_bytes,
                "max_processes": spec.resource_policy.max_processes,
                "workdir_total_bytes": spec.resource_policy.workdir_total_bytes,
                "workdir_file_bytes": spec.resource_policy.workdir_file_bytes,
                "wall_seconds": spec.resource_policy.wall_seconds,
                "output_max_bytes_per_stream": spec.resource_policy.output_max_bytes_per_stream,
            },
            metadata={
                "image": self._image,
                "network": "proxy" if self._network_policy.rules else "none",
                "container": f"nexus-exec-{str(run_id).replace('-', '')[:24]}",
            },
        )

    def preexec_for(self, reservation: SandboxReservation):
        # Container isolation comes from the Docker daemon, not host preexec.
        return None

    def launch_plan(
        self,
        reservation: SandboxReservation,
        spec: ProcessSpec,
        *,
        working_dir: Path,
        secret_dir: Path | None = None,
        artifact_dir: Path | None = None,
    ) -> SandboxLaunchPlan:
        if self._network_policy.rules and self._proxy_endpoint is None:
            # Never open direct egress because no managed proxy is wired.
            raise SandboxPolicyError(
                "runtime_host_sandbox_unavailable",
                "managed egress proxy is required for an allowlist",
            )
        resolved = Path(working_dir).resolve()
        if not resolved.is_dir():
            raise SandboxPolicyError("runtime_host_sandbox_unavailable", "workdir missing")
        container = f"nexus-exec-{str(reservation.run_id).replace('-', '')[:24]}"
        policy = spec.resource_policy
        cpu_cores = max(1.0, min(4.0, policy.cpu_seconds / max(1, policy.wall_seconds)))
        network_mode = "none" if not self._network_policy.rules else "bridge"
        argv: list[str] = [
            "docker",
            "run",
            "--rm",
            "--init",
            "--name",
            container,
            "--network",
            network_mode,
            "--read-only",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(policy.max_processes),
            "--memory",
            f"{policy.memory_bytes}b",
            "--cpus",
            f"{cpu_cores:.2f}",
            "--ulimit",
            f"fsize={policy.workdir_file_bytes}:{policy.workdir_file_bytes}",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={min(policy.workdir_total_bytes, 64 * 1024 * 1024)}",
            "--mount",
            f"type=bind,source={resolved},target=/workspace",
        ]
        environment: list[tuple[str, str]] = []
        if secret_dir is not None:
            secrets = Path(secret_dir).resolve()
            if not secrets.is_dir():
                raise SandboxPolicyError("runtime_host_sandbox_unavailable", "secret dir missing")
            argv += ["--mount", f"type=bind,source={secrets},target=/run/secrets,readonly"]
        if artifact_dir is not None:
            artifacts = Path(artifact_dir).resolve()
            argv += ["--mount", f"type=bind,source={artifacts},target=/artifacts"]
        if self._network_policy.rules and self._proxy_endpoint is not None:
            argv += ["--add-host", "host.docker.internal:host-gateway"]
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                environment.append((name, self._proxy_endpoint))
            environment += [("NO_PROXY", "127.0.0.1,localhost,169.254.169.254")]
        for key, value in spec.environment.items():
            environment.append((key, value))
        argv += ["--workdir", "/workspace", self._image]
        argv += list(spec.argv)
        return SandboxLaunchPlan(
            argv=tuple(argv),
            environment=tuple(environment),
            container_name=container,
        )

    async def release(self, reservation: SandboxReservation) -> None:
        if reservation.released:
            return
        reservation.released = True
        name = reservation.metadata.get("container")
        if not isinstance(name, str) or not name.startswith("nexus-exec-"):
            name = None
        # metadata does not carry the name; Host container names are derived,
        # so cleanup is optional and --rm remains the primary guarantee.
        if name is None:
            return
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "rm", "-f", name],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("docker sandbox release deferred")
