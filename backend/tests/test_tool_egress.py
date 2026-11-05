import asyncio
from uuid import uuid4

import httpcore
import httpx
import pytest

from agent_platform.core_platform.tool_gateway.egress import (
    PinnedDestination,
    PinnedNetworkBackend,
    ToolEgressError,
    ToolEgressPolicy,
    ToolEgressTransport,
)
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway

pytestmark = pytest.mark.asyncio


def tool(url="https://public.test/orders", **kwargs):
    return HttpTool(
        name="lookup",
        description="Query demo",
        url=url,
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        **kwargs,
    )


async def fixed_resolver(_hostname, _port):
    return ("93.184.216.34", "2001:4860:4860::8888")


async def test_public_ipv4_and_ipv6_destinations_are_allowed():
    policy = ToolEgressPolicy(["public.test"], resolver=fixed_resolver)

    destination = await policy.validate("https://public.test/orders")

    assert destination == PinnedDestination(
        "public.test", 443, ("2001:4860:4860::8888", "93.184.216.34")
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.7",
        "169.254.10.4",
        "224.0.0.1",
        "240.0.0.1",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
    ],
)
async def test_non_public_destinations_are_rejected_by_default(address):
    async def resolver(_hostname, _port):
        return (address,)

    policy = ToolEgressPolicy(["public.test"], resolver=resolver)

    with pytest.raises(ToolEgressError, match="tool_destination_not_allowed"):
        await policy.validate("https://public.test/orders")


async def test_loopback_requires_an_explicit_local_allowlist():
    async def resolver(_hostname, _port):
        return ("127.0.0.1", "::1")

    policy = ToolEgressPolicy(["localhost"], resolver=resolver)

    destination = await policy.validate("http://localhost/orders")

    assert destination.addresses == ("127.0.0.1", "::1")


async def test_private_networks_require_an_explicit_policy_and_allowlist():
    async def resolver(_hostname, _port):
        return ("10.0.0.7",)

    policy = ToolEgressPolicy(["internal.test"], allow_private_networks=True, resolver=resolver)

    assert (await policy.validate("http://internal.test/orders")).addresses == ("10.0.0.7",)


async def test_initial_destination_check_precedes_credential_resolution():
    async def resolver(_hostname, _port):
        return ("127.0.0.1",)

    credential_calls = []

    async def credentials(_spec):
        credential_calls.append(True)
        return {"Authorization": "Bearer secret"}

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: None)) as client:
        result = await ToolGateway(
            client,
            [tool(credential_id=uuid4())],
            credential_resolver=credentials,
            network_policy=ToolEgressPolicy(["public.test"], resolver=resolver),
        ).execute("lookup", {})

    assert result == {"ok": False, "error": "tool_destination_not_allowed"}
    assert credential_calls == []


async def test_dns_rebinding_is_rejected_before_the_request_is_sent():
    answers = iter([("93.184.216.34",), ("10.0.0.7",)])

    async def resolver(_hostname, _port):
        return next(answers)

    requests = []
    credentials = []

    async def resolve_credentials(_spec):
        credentials.append(True)
        return {"Authorization": "Bearer secret"}

    async def request_handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(request_handler)) as client:
        result = await ToolGateway(
            client,
            [tool(credential_id=uuid4())],
            credential_resolver=resolve_credentials,
            network_policy=ToolEgressPolicy(["public.test"], resolver=resolver),
        ).execute("lookup", {})

    assert result == {"ok": False, "error": "tool_destination_not_allowed"}
    assert credentials == [True]
    assert requests == []


async def test_public_dns_answer_change_is_rejected_before_connecting():
    answers = iter([("93.184.216.34",), ("93.184.216.35",)])

    async def resolver(_hostname, _port):
        return next(answers)

    async def request_handler(_request):
        pytest.fail("the request must be rejected after the DNS answer changes")

    async with httpx.AsyncClient(transport=httpx.MockTransport(request_handler)) as client:
        result = await ToolGateway(
            client,
            [tool()],
            network_policy=ToolEgressPolicy(["public.test"], resolver=resolver),
        ).execute("lookup", {})

    assert result == {"ok": False, "error": "tool_destination_changed"}


async def test_pinned_backend_connects_to_validated_address():
    class Backend:
        def __init__(self):
            self.calls = []

        async def connect_tcp(
            self, host, port, timeout=None, local_address=None, socket_options=None
        ):
            self.calls.append((host, port, timeout, local_address, socket_options))
            return "stream"

        async def connect_unix_socket(self, path, timeout=None, socket_options=None):
            return path

        async def sleep(self, seconds):
            return None

    backend = Backend()
    pinned = PinnedNetworkBackend(backend)
    policy = ToolEgressPolicy(["public.test"], resolver=fixed_resolver)
    destination = await policy.validate("https://public.test/orders")

    with policy.pin(destination):
        stream = await pinned.connect_tcp("public.test", 443, timeout=2)

    assert stream == "stream"
    assert [call[0] for call in backend.calls] == ["2001:4860:4860::8888"]


async def test_pinned_backend_rejects_unvalidated_connections():
    class Backend:
        async def connect_tcp(self, *args, **kwargs):
            pytest.fail("unvalidated connection reached the backend")

        async def connect_unix_socket(self, *args, **kwargs):
            return None

        async def sleep(self, _seconds):
            return None

    with pytest.raises(httpcore.ConnectError, match="not validated"):
        await PinnedNetworkBackend(Backend()).connect_tcp("public.test", 443)


async def test_httpx_transport_uses_pinned_ip_and_original_host():
    seen_hosts = []
    response_body = b'{"ok":true}'

    async def handle(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        seen_hosts.append(
            next(
                line.split(b":", 1)[1].strip().decode()
                for line in request.split(b"\r\n")
                if line.lower().startswith(b"host:")
            )
        )
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            + b"Content-Type: application/json\r\n"
            + b"Content-Length: "
            + str(len(response_body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + response_body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    connect_hosts = []

    async def resolver(_hostname, _port):
        return ("127.0.0.1",)

    policy = ToolEgressPolicy(["localhost"], resolver=resolver)
    transport = ToolEgressTransport(policy, trust_env=False)
    delegate = transport._pool._network_backend.backend

    class RecordingBackend:
        async def connect_tcp(
            self, host, port, timeout=None, local_address=None, socket_options=None
        ):
            connect_hosts.append(host)
            return await delegate.connect_tcp(
                host,
                port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )

        async def connect_unix_socket(self, path, timeout=None, socket_options=None):
            return await delegate.connect_unix_socket(
                path, timeout=timeout, socket_options=socket_options
            )

        async def sleep(self, seconds):
            await delegate.sleep(seconds)

    transport._pool._network_backend = PinnedNetworkBackend(RecordingBackend())
    try:
        async with httpx.AsyncClient(transport=transport) as client:
            result = await ToolGateway(
                client,
                [tool(f"http://localhost:{port}/orders")],
                network_policy=policy,
            ).execute("lookup", {})
    finally:
        await transport.aclose()
        server.close()
        await server.wait_closed()

    assert result == {"ok": True, "data": {"ok": True}}
    assert connect_hosts == ["127.0.0.1"]
    assert seen_hosts == [f"localhost:{port}"]
