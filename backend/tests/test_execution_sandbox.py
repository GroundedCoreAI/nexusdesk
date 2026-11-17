"""Phase 6 T-08: strong Docker sandbox policy, plans, and real drills."""

import asyncio
import shutil
import subprocess
from uuid import uuid4

import pytest

from agent_platform.core_platform.agent_execution.host.docker_sandbox_provider import (
    DockerSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessSpec,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.local_sandbox_provider import (
    LocalSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.network_policy import (
    DestinationDecision,
    NetworkPolicy,
    NetworkRule,
    decide_destination,
    validate_connect_target,
)
from agent_platform.core_platform.agent_execution.host.sandbox_provider import (
    SandboxPolicyError,
)

IMAGE = "alpine:latest"


def _policy(*rules: NetworkRule) -> NetworkPolicy:
    return NetworkPolicy(rules=rules)


@pytest.mark.asyncio
async def test_network_policy_allows_only_public_allowlisted_destinations():
    policy = _policy(NetworkRule(host="api.example.com", port=443))
    allowed = decide_destination(
        policy, host="api.example.com", port=443, resolved_ips=("93.184.216.34",)
    )
    assert allowed.allowed is True
    assert allowed.pinned_ips == ("93.184.216.34",)
    denied_by_default = decide_destination(
        policy, host="evil.example", port=443, resolved_ips=("93.184.216.34",)
    )
    assert denied_by_default.allowed is False
    assert denied_by_default.reason_code == "egress_not_allowed"
    wrong_port = decide_destination(
        policy, host="api.example.com", port=80, resolved_ips=("93.184.216.34",)
    )
    assert wrong_port.allowed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "fd00::1",
    ],
)
async def test_network_policy_denies_private_loopback_linklocal_and_metadata(ip):
    policy = _policy(NetworkRule(host="api.example.com", port=443))
    decision = decide_destination(policy, host="api.example.com", port=443, resolved_ips=(ip,))
    assert decision.allowed is False
    assert decision.reason_code in {"egress_private_address", "egress_metadata_address"}


@pytest.mark.asyncio
async def test_dns_rebinding_and_redirects_are_checked_per_hop():
    policy = _policy(NetworkRule(host="api.example.com", port=443))
    # The hostname is allowed but one resolved address is private: deny all.
    rebound = decide_destination(
        policy,
        host="api.example.com",
        port=443,
        resolved_ips=("93.184.216.34", "10.0.0.5"),
    )
    assert rebound.allowed is False
    # A redirect to a non-allowlisted host is denied on its own hop.
    redirect = decide_destination(
        policy, host="169.254.169.254", port=80, resolved_ips=("169.254.169.254",)
    )
    assert redirect.allowed is False
    assert redirect.reason_code in {"egress_not_allowed", "egress_metadata_address"}
    # Unresolvable DNS fails closed.
    unresolved = decide_destination(policy, host="api.example.com", port=443, resolved_ips=())
    assert unresolved.allowed is False and unresolved.reason_code == "dns_unresolved"


def _spec(*argv: str) -> ProcessSpec:
    return ProcessSpec(
        executable_id="sandbox-drill",
        argv=argv,
        workdir_relative_path="tenant/run",
        resource_policy=ResourcePolicy(
            cpu_seconds=5,
            memory_bytes=128 * 1024 * 1024,
            max_processes=8,
            workdir_total_bytes=10 * 1024 * 1024,
            workdir_file_bytes=1024 * 1024,
            wall_seconds=10,
            output_max_bytes_per_stream=1024 * 1024,
        ),
    )


def test_local_provider_still_rejects_every_untrusted_shape():
    provider = LocalSandboxProvider(enforcement_required=False)
    for flags in (
        {"arbitrary_command": True},
        {"uploaded_code": True},
        {"untrusted_multi_tenant": True},
    ):
        with pytest.raises(SandboxPolicyError) as exc:
            asyncio.run(provider.prepare(_spec("/bin/true"), run_id=uuid4(), **flags))
        assert exc.value.code == "runtime_host_untrusted_target"


def test_docker_provider_fails_closed_without_a_configured_image():
    provider = DockerSandboxProvider(image="", docker_probe=lambda: True)
    with pytest.raises(SandboxPolicyError) as exc:
        asyncio.run(provider.prepare(_spec("/bin/true"), run_id=uuid4()))
    assert exc.value.code == "runtime_host_sandbox_unavailable"


def test_docker_provider_fails_closed_when_the_daemon_is_unavailable():
    provider = DockerSandboxProvider(image=IMAGE, docker_probe=lambda: False)
    with pytest.raises(SandboxPolicyError) as exc:
        asyncio.run(provider.prepare(_spec("/bin/true"), run_id=uuid4()))
    assert exc.value.code == "runtime_host_sandbox_unavailable"


def test_docker_launch_plan_is_server_generated_default_deny_and_minimal(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    provider = DockerSandboxProvider(image=IMAGE, docker_probe=lambda: True)
    spec = _spec("/bin/sh", "-c", "cat /workspace/marker")
    reservation = asyncio.run(provider.prepare(spec, run_id=uuid4()))
    plan = provider.launch_plan(reservation, spec, working_dir=workdir, secret_dir=secret_dir)
    argv = " ".join(plan.argv)
    assert plan.argv[:2] == ("docker", "run")
    assert IMAGE in plan.argv
    assert "--network" in plan.argv and "none" in plan.argv
    assert "--read-only" in plan.argv
    assert "--cap-drop" in plan.argv and "ALL" in plan.argv
    assert "--security-opt" in plan.argv and "no-new-privileges" in plan.argv
    assert "--pids-limit" in plan.argv and "--memory" in plan.argv and "--cpus" in plan.argv
    assert "--user" in plan.argv and "65534:65534" in plan.argv
    assert "--tmpfs" in plan.argv and "/tmp" in argv
    assert f"source={workdir.resolve()}" in argv and "target=/workspace" in argv
    assert f"source={secret_dir.resolve()}" in argv and "readonly" in argv
    assert "/var/run/docker.sock" not in argv
    assert "host.docker.internal" not in argv
    assert plan.argv[-3:] == ("/bin/sh", "-c", "cat /workspace/marker")


def test_docker_allowlist_egress_requires_a_managed_proxy_and_fails_closed(tmp_path):
    provider = DockerSandboxProvider(
        image=IMAGE,
        docker_probe=lambda: True,
        network_policy=_policy(NetworkRule(host="api.example.com", port=443)),
    )
    workdir = tmp_path / "work"
    workdir.mkdir()
    with pytest.raises(SandboxPolicyError) as exc:
        provider.launch_plan(
            asyncio.run(provider.prepare(_spec("/bin/true"), run_id=uuid4())),
            _spec("/bin/true"),
            working_dir=workdir,
        )
    assert exc.value.code == "runtime_host_sandbox_unavailable"


def test_network_policy_rejects_a_connect_target_without_resolution():
    policy = _policy(NetworkRule(host="api.example.com", port=443))
    decision = validate_connect_target(
        policy, host="api.example.com", port=443, resolver=lambda _host: ()
    )
    assert isinstance(decision, DestinationDecision)
    assert decision.allowed is False


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, timeout=10, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


DOCKER_READY = _docker_ready()
DOCKER_SKIP = pytest.mark.skipif(not DOCKER_READY, reason="docker_daemon_unavailable")


def _run_plan(plan, timeout=30):
    return subprocess.run(
        list(plan.argv), capture_output=True, text=True, timeout=timeout, check=False
    )


@DOCKER_SKIP
def test_real_docker_default_deny_read_only_and_minimal_mounts(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "marker").write_text("inside-workdir")
    provider = DockerSandboxProvider(image=IMAGE, docker_probe=lambda: True)
    spec = _spec(
        "/bin/sh",
        "-c",
        "cat /workspace/marker; "
        "test ! -e /etc/nexusdesk-host-marker && echo no-host-files; "
        "test ! -S /var/run/docker.sock && echo no-docker-socket; "
        "touch /root-should-fail 2>/dev/null && echo root-writable || echo read-only-root; "
        "wget -T2 -q -O- http://169.254.169.254/ >/dev/null 2>&1 && echo egress-open || echo egress-denied",
    )
    reservation = asyncio.run(provider.prepare(spec, run_id=uuid4()))
    plan = provider.launch_plan(reservation, spec, working_dir=workdir)
    result = _run_plan(plan)
    assert result.returncode == 0, result.stderr
    assert "inside-workdir" in result.stdout
    assert "no-host-files" in result.stdout
    assert "no-docker-socket" in result.stdout
    assert "read-only-root" in result.stdout
    assert "egress-denied" in result.stdout
    assert "egress-open" not in result.stdout
    # Container auto-removes; the plan name must not linger.
    assert not subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={plan.container_name}", "-q"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


@DOCKER_SKIP
def test_real_docker_pid_limit_contains_a_fork_bomb(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    provider = DockerSandboxProvider(image=IMAGE, docker_probe=lambda: True)
    spec = _spec(
        "/bin/sh",
        "-c",
        "i=0; while [ $i -lt 64 ]; do sleep 30 & i=$((i+1)); done; wait",
    )
    reservation = asyncio.run(provider.prepare(spec, run_id=uuid4()))
    plan = provider.launch_plan(reservation, spec, working_dir=workdir)
    result = _run_plan(plan, timeout=20)
    # The PID ceiling refuses creation; the shell reports failure instead of
    # letting 64 descendants survive.
    assert result.returncode != 0 or "can't fork" in (result.stderr + result.stdout).lower()
