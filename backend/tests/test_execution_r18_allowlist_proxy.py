"""Phase 6 R-18(d)/R-19: managed allowlist proxy real enforcement.

A sandbox on the isolated internal network can only reach the managed proxy.
The proxy enforces the allowlist: allowed destination passes, non-allowlisted
and metadata destinations are denied at the actual network boundary.
"""

import asyncio
import os
import shutil
import socket
import subprocess
import threading
from dataclasses import replace
from uuid import uuid4

import pytest

from agent_platform.core_platform.agent_execution.host.docker_sandbox_provider import (
    DockerSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.egress_proxy import EgressProxyEndpoint
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessSpec,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.network_policy import (
    NetworkPolicy,
    NetworkRule,
)

DOCKER_READY = (
    shutil.which("docker") is not None
    and subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=False).returncode
    == 0
)
DOCKER_SKIP = pytest.mark.skipif(not DOCKER_READY, reason="docker_daemon_unavailable")

IMAGE = "alpine:latest"


def _spec(argv):
    return ProcessSpec(
        executable_id="sandbox-drill",
        argv=argv,
        workdir_relative_path="t/run",
        resource_policy=ResourcePolicy(
            cpu_seconds=5,
            memory_bytes=128 * 1024 * 1024,
            max_processes=8,
            workdir_total_bytes=10 * 1024 * 1024,
            workdir_file_bytes=1024 * 1024,
            wall_seconds=15,
            output_max_bytes_per_stream=1024 * 1024,
        ),
    )


class _AllowlistProxy(threading.Thread):
    """Minimal managed forward proxy enforcing a host allowlist."""

    def __init__(self, allowed_host: str):
        super().__init__(daemon=True)
        self.allowed_host = allowed_host
        self.allow_hits = 0
        self.deny_hits = 0
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("0.0.0.0", 0))
        self._server.listen(8)
        self.port = self._server.getsockname()[1]

    def run(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            data = conn.recv(4096)
            line = data.split(b"\r\n", 1)[0].decode("latin1")
            target = line.split(" ")[1] if len(line.split(" ")) > 1 else ""
            host = target.split("/")[2].split(":")[0] if target.startswith("http") else target
            if self.allowed_host == host:
                self.allow_hits += 1
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            else:
                self.deny_hits += 1
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self._server.close()


@DOCKER_SKIP
@pytest.mark.asyncio
async def test_allowlist_proxy_permits_allowed_and_denies_metadata(tmp_path):
    workdir = tmp_path / "w"
    workdir.mkdir()
    proxy_name = "nexus-egress-proxy-test"
    network = f"nexus-egress-{proxy_name}"
    created_network = (
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "network", "inspect", network],
            capture_output=True,
            check=False,
        )
    ).returncode != 0
    if created_network:
        await asyncio.to_thread(
            subprocess.run,
            ["docker", "network", "create", "--internal", network],
            check=True,
            capture_output=True,
        )
    # Run the managed proxy as a container on the internal network: the sandbox
    # can only reach it there, proving the enforced boundary.
    await asyncio.to_thread(
        subprocess.run, ["docker", "rm", "-f", proxy_name], capture_output=True, check=False
    )
    proxy_script = (
        "import http.server,socketserver\n"
        "class P(http.server.BaseHTTPRequestHandler):\n"
        "  def do_GET(self):\n"
        "    host=self.path.split('/')[2].split(':')[0] if self.path.startswith('http') else ''\n"
        "    if host=='example.com':\n"
        "      self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
        "    else:\n"
        "      self.send_response(403); self.end_headers()\n"
        "socketserver.TCPServer(('0.0.0.0',3128),P).serve_forever()\n"
    )
    proxy_container = await asyncio.to_thread(
        subprocess.run,
        [
            "docker",
            "run",
            "-d",
            "--name",
            proxy_name,
            "--network",
            network,
            "python:3.12-slim-bookworm",
            "python",
            "-c",
            proxy_script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proxy_container.returncode == 0, proxy_container.stderr
    proxy_ip = proxy_name  # reach the proxy by its container name on the network
    proxy_port = 3128
    # Wait for the proxy to accept connections on the internal network.

    for _ in range(20):
        probe = await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "run",
                "--rm",
                "--network",
                network,
                "alpine:latest",
                "nc",
                "-z",
                "-w2",
                proxy_name,
                str(proxy_port),
            ],
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            break
        await asyncio.sleep(0.3)
    plans = []
    try:
        provider = DockerSandboxProvider(
            image=IMAGE,
            docker_probe=lambda: True,
            network_policy=NetworkPolicy(rules=(NetworkRule(host="example.com", port=80),)),
            proxy_endpoint=EgressProxyEndpoint(host=proxy_ip, port=proxy_port),
        )
        allowed_spec = _spec(
            ("/bin/sh", "-c", "wget -T5 -q -O- http://example.com/ && echo ALLOWED")
        )
        reservation = await provider.prepare(allowed_spec, run_id=uuid4())
        plan = provider.launch_plan(reservation, allowed_spec, working_dir=workdir)
        # Managed DNS decoy: hostname resolution is pinned independently of proxy policy.
        pivot = plan.argv.index("--workdir")
        plan = replace(
            plan,
            argv=plan.argv[:pivot] + ("--add-host", "example.com:192.0.2.10") + plan.argv[pivot:],
        )
        plans.append(plan)
        allowed = await asyncio.to_thread(
            subprocess.run,
            list(plan.argv),
            capture_output=True,
            text=True,
            env={**os.environ, **dict(plan.environment)},
            timeout=30,
            check=False,
        )
        assert allowed.returncode == 0, allowed.stderr
        assert "okALLOWED" in allowed.stdout.replace("\n", "")

        denied_spec = _spec(
            (
                "/bin/sh",
                "-c",
                (
                    "wget -T3 -q -O- http://169.254.169.254/ >/dev/null 2>&1 "
                    "&& echo METADATA_OPEN || echo METADATA_DENIED; "
                    "wget -T3 -q -O- http://evil.example/ >/dev/null 2>&1 "
                    "&& echo EVIL_OPEN || echo EVIL_DENIED; "
                    "nc -z -w2 1.1.1.1 80 >/dev/null 2>&1 "
                    "&& echo DIRECT_OPEN || echo DIRECT_DENIED"
                ),
            )
        )
        denied_reservation = await provider.prepare(denied_spec, run_id=uuid4())
        denied_plan = provider.launch_plan(denied_reservation, denied_spec, working_dir=workdir)
        pivot = denied_plan.argv.index("--workdir")
        denied_plan = replace(
            denied_plan,
            argv=denied_plan.argv[:pivot]
            + ("--add-host", "evil.example:192.0.2.20")
            + denied_plan.argv[pivot:],
        )
        plans.append(denied_plan)
        denied = await asyncio.to_thread(
            subprocess.run,
            list(denied_plan.argv),
            capture_output=True,
            text=True,
            env={**os.environ, **dict(denied_plan.environment)},
            timeout=30,
            check=False,
        )
        assert denied.returncode == 0, denied.stderr
        assert "METADATA_DENIED" in denied.stdout
        assert "EVIL_DENIED" in denied.stdout
        assert "DIRECT_DENIED" in denied.stdout
        assert "OPEN" not in denied.stdout
        assert "bridge" not in " ".join(plan.argv)
    finally:
        await asyncio.to_thread(
            subprocess.run, ["docker", "rm", "-f", proxy_name], capture_output=True, check=False
        )
        for plan in plans:
            remaining = (
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "ps", "-a", "--filter", f"name={plan.container_name}", "-q"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            ).stdout.strip()
            assert not remaining
        if created_network:
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "network", "rm", network],
                check=True,
                capture_output=True,
            )
