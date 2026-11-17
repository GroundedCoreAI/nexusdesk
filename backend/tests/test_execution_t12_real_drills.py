"""Phase 6 T-12: smallest local real Docker Secret/resource drills."""

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


def _docker_ready():
    return (
        shutil.which("docker") is not None
        and subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10, check=False
        ).returncode
        == 0
    )


pytestmark = pytest.mark.skipif(not _docker_ready(), reason="docker_daemon_unavailable")


def _spec(argv, *, memory=32 * 1024 * 1024, secret=None):
    return ProcessSpec(
        executable_id="sandbox-drill",
        argv=argv,
        workdir_relative_path="t/run",
        environment={} if secret is None else {"EXECUTION_CREDENTIAL": secret},
        resource_policy=ResourcePolicy(
            cpu_seconds=5,
            memory_bytes=memory,
            max_processes=8,
            workdir_total_bytes=8 * 1024 * 1024,
            workdir_file_bytes=1024 * 1024,
            wall_seconds=15,
            output_max_bytes_per_stream=1024 * 1024,
        ),
    )


def _run(plan):
    return subprocess.run(list(plan.argv), capture_output=True, text=True, timeout=30, check=False)


def test_real_docker_child_receives_controlled_secret_without_echo(tmp_path):
    workdir = tmp_path / "w"
    workdir.mkdir()
    canary = "t12-secret-canary-not-for-output"
    spec = _spec(
        ("/bin/sh", "-c", 'test "$EXECUTION_CREDENTIAL" = "$EXPECTED" && echo CHANNEL_OK'),
        secret=canary,
    )
    spec = spec.model_copy(update={"environment": {**spec.environment, "EXPECTED": canary}})
    provider = DockerSandboxProvider(image="alpine:latest", docker_probe=lambda: True)
    reservation = asyncio.run(provider.prepare(spec, run_id=uuid4()))
    plan = provider.launch_plan(reservation, spec, working_dir=workdir)
    assert canary not in " ".join(plan.argv)
    result = _run(plan)
    assert result.returncode == 0, result.stderr
    assert "CHANNEL_OK" in result.stdout
    assert canary not in result.stdout + result.stderr
    assert not subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={plan.container_name}", "-q"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def test_real_docker_memory_and_tmpfs_exhaustion_do_not_affect_host(tmp_path):
    workdir = tmp_path / "w"
    workdir.mkdir()
    provider = DockerSandboxProvider(image="alpine:latest", docker_probe=lambda: True)
    memory_spec = _spec(
        ("/bin/sh", "-c", 'awk \'BEGIN { s=sprintf("%*s", 67108864, "x"); print length(s) }\''),
        memory=16 * 1024 * 1024,
    )
    memory_reservation = asyncio.run(provider.prepare(memory_spec, run_id=uuid4()))
    memory_plan = provider.launch_plan(memory_reservation, memory_spec, working_dir=workdir)
    memory = _run(memory_plan)
    assert memory.returncode != 0
    assert "67108864" not in memory.stdout

    disk_spec = _spec(
        ("/bin/sh", "-c", "dd if=/dev/zero of=/tmp/full bs=1M count=32 2>/dev/null"),
        memory=32 * 1024 * 1024,
    )
    disk_reservation = asyncio.run(provider.prepare(disk_spec, run_id=uuid4()))
    disk_plan = provider.launch_plan(disk_reservation, disk_spec, working_dir=workdir)
    disk = _run(disk_plan)
    assert disk.returncode != 0
    assert (workdir / "host-survives").write_text("ok") is not None
    assert (workdir / "host-survives").read_text() == "ok"
    for plan in (memory_plan, disk_plan):
        assert not subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={plan.container_name}", "-q"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
