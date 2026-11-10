"""End-to-end proof that a declared executor reaches the upstream service.

The mock upstream is a real HTTP server on loopback: the gateway's egress
policy, credential resolution, argument validation and response parsing all run
for real, and only the business service behind the URL is a stub.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from test_platform_postgres import platform as _platform

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]
ROOT = "/api/v1"


class _OrdersHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        if parts.path == "/orders":
            order_id = (query.get("order_id") or [""])[0]
            if order_id == "missing":
                self._reply(404, {"error": "not_found"})
                return
            self._reply(
                200,
                {
                    "data": {
                        "order": {
                            "status": "已签收",
                            "logistics_status": "已到站",
                            "amount": 88,
                        }
                    }
                },
            )
            return
        if parts.path == "/orders/list":
            self._reply(
                200,
                {
                    "data": {
                        "items": [
                            {"id": "order-1", "name": "订单 1", "status": "已签收"},
                            {"id": "order-2", "name": "订单 2", "status": "运输中"},
                        ]
                    }
                },
            )
            return
        self._reply(404, {"error": "unknown_path"})

    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Keep pytest output clean."""


@pytest.fixture
def orders_upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OrdersHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def publish_tool(client, base_url, name, path, properties):
    collection = await client.post(
        f"{ROOT}/tool-workspace/collections",
        json={
            "name": f"{name} 工具集",
            "description": "",
            "base_url": base_url,
            "auth_kind": "none",
            "header_secrets": {},
        },
    )
    assert collection.status_code == 201, collection.text
    group = collection.json()
    api = await client.post(
        f"{ROOT}/tool-workspace/collections/{group['id']}/apis",
        json={
            "display_name": name,
            "relative_path": path,
            "auth_mode": "inherit",
            "definition": {
                "name": name,
                "description": f"{name} 测试接口",
                "url": f"{base_url}{path}",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            },
        },
    )
    assert api.status_code == 201, api.text
    row = api.json()
    published = await client.post(
        f"{ROOT}/tool-workspace/apis/{row['id']}/publish",
        json={"revision": 1, "collection_revision": 1},
    )
    assert published.status_code == 200, published.text


async def publish_provider(client, *, executors):
    response = await client.post(
        f"{ROOT}/service-providers",
        json={
            "key": "order_provider",
            "kind": "object",
            "name": "订单数据",
            "enabled": True,
            "config": {"executors": executors} if executors is not None else {},
        },
    )
    assert response.status_code == 201, response.text


def scenario_config():
    return {
        "name": "查询订单状态",
        "description": "按订单查询状态与物流",
        "domain": "shopping",
        "category": "order_service",
        "template": "query",
        "facts": [
            {"key": "order_status", "label": "订单状态", "source": "status", "order": 10},
            {
                "key": "logistics_status",
                "label": "物流状态",
                "source": "logistics_status",
                "order": 20,
            },
        ],
        "object": {
            "type": "order",
            "provider": "order_provider",
            "required": True,
            "mode": "required",
            "candidate_strategy": {
                "sort": "recent_desc",
                "limit": 5,
                "filters": [],
                "empty_state": "没有可查询的订单",
                "unavailable_state": "订单服务暂不可用",
            },
        },
        "decisions": [
            {
                "key": "select-order",
                "kind": "select_object",
                "label": "选择订单",
                "options": [],
                "allow_free_text": False,
                "allow_skip": False,
                "confirm": False,
                "correctable": True,
                "when": {},
            }
        ],
        "handlers": [
            {
                "key": "object-query",
                "type": "query",
                "label": "查询订单",
                "priority": 10,
                "enabled": True,
                "tool": "order_status",
                "config": {},
            }
        ],
        "fallback_order": ["object-query"],
        "matching": {"keywords": ["订单"], "intents": [], "negative_keywords": []},
    }


async def publish_scenario(client):
    key = "order-status-" + uuid4().hex[:8]
    created = await client.post(
        f"{ROOT}/service-scenarios",
        json={"key": key, "config": scenario_config()},
    )
    assert created.status_code == 201, created.text
    published = await client.post(
        f"{ROOT}/service-scenarios/{key}/publish",
        json={"revision": created.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    return key


async def simulate(client, key, body):
    response = await client.post(f"{ROOT}/service-scenarios/{key}/simulate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def test_object_read_uses_upstream_facts(platform, orders_upstream):
    client, _, _ = platform
    await publish_tool(client, orders_upstream, "order_status", "/orders", {"order_id": {"type": "string"}})
    await publish_provider(
        client,
        executors={
            "get": {
                "tool": "order_status",
                "arguments": {"order_id": "$object.id"},
                "result_root": "data.order",
            }
        },
    )
    key = await publish_scenario(client)

    trace = await simulate(
        client,
        key,
        {
            "message": "我的订单到哪了",
            "object": {"id": "order-1", "type": "order", "facts": {}},
        },
    )

    values = {fact["key"]: fact["value"] for fact in trace["facts"]}
    assert values == {"order_status": "已签收", "logistics_status": "已到站"}
    assert trace["provider"]["execution"] == {
        "tool": "order_status",
        "ok": True,
        "error": None,
        "error_status": 0,
        "upstream_called": True,
    }
    assert trace["result"]["status"] == "succeeded"


async def test_missing_object_is_reported_from_upstream(platform, orders_upstream):
    client, _, _ = platform
    await publish_tool(client, orders_upstream, "order_status", "/orders", {"order_id": {"type": "string"}})
    await publish_provider(
        client,
        executors={
            "get": {
                "tool": "order_status",
                "arguments": {"order_id": "$object.id"},
                "result_root": "data.order",
                "on_error": "fail",
            }
        },
    )
    key = await publish_scenario(client)

    trace = await simulate(
        client,
        key,
        {
            "message": "查一下这个订单",
            "object": {"id": "missing", "type": "order", "facts": {}},
        },
    )

    object_step = next(step for step in trace["steps"] if step["step"] == "object")
    assert object_step["reason"] == "object_missing"
    assert object_step["object_id"] == "missing"
    assert trace["result"]["reason"] == "object_missing"
    assert trace["facts"] == []
    assert trace["provider"]["execution"]["error_status"] == 404


async def test_object_list_populates_candidates(platform, orders_upstream):
    client, _, _ = platform
    await publish_tool(
        client,
        orders_upstream,
        "order_list",
        "/orders/list",
        {"customer_id": {"type": "string"}},
    )
    await publish_provider(
        client,
        executors={
            "list": {
                "tool": "order_list",
                "arguments": {"customer_id": "$customer.id"},
                "result_root": "data.items",
            }
        },
    )
    key = await publish_scenario(client)

    trace = await simulate(
        client,
        key,
        {"message": "我要查订单", "customer": {"id": "customer-9"}},
    )

    assert trace["provider"]["candidates"] == [
        {"id": "order-1", "title": "订单 1", "status": "已签收"},
        {"id": "order-2", "title": "订单 2", "status": "运输中"},
    ]
    # Without a selected object the deterministic path still stops for input.
    assert trace["result"]["reason"] == "object_required"
    assert trace["provider"]["execution"]["tool"] == "order_list"


async def test_placeholder_provider_keeps_the_label_only_simulation(platform):
    client, _, _ = platform
    await publish_provider(client, executors=None)
    key = await publish_scenario(client)

    trace = await simulate(
        client,
        key,
        {
            "message": "我的订单到哪了",
            "object": {"id": "order-1", "type": "order", "status": "运输中", "facts": {"status": "运输中"}},
        },
    )

    # No declaration means no call and no provider evidence.
    assert "provider" not in trace
    assert trace["result"]["status"] == "succeeded"
    assert {fact["key"]: fact["value"] for fact in trace["facts"]} == {
        "order_status": "运输中",
        "logistics_status": None,
    }


async def test_executor_declaration_is_validated_before_persisting(platform):
    client, _, _ = platform
    response = await client.post(
        f"{ROOT}/service-providers",
        json={
            "key": "order_provider",
            "kind": "object",
            "name": "订单数据",
            "config": {"executors": {"get": {"tool": "shopping.order.status"}}},
        },
    )

    # A dotted semantic identifier cannot be a callable gateway tool.
    assert response.status_code == 422
    assert response.json()["detail"] == "provider_executor_tool_invalid"
