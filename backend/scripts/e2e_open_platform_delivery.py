"""Real-HTTP acceptance run for open-platform delivery of a Service Application.

Boots an isolated instance (own tenant on the migrated test database) behind a
real socket, then drives the public ``/openapi/v1`` contract with an ``opk_``
key exactly as an integrator would: create conversation -> submit message ->
read the SSE stream -> resolve the run -> inspect the ledger and the in-product
conversation list.

Run from ``backend/``::

    $env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/agent_platform_test'
    .venv/Scripts/python.exe scripts/e2e_open_platform_delivery.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from pydantic import SecretStr
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from agent_platform.applications.customer_service.main import create_app
from agent_platform.core_platform.platform_services.platform_settings.settings import (
    Settings,
)

ADMIN = {"Authorization": "Bearer platform-admin"}


def settings_for(url: str, tenant: str) -> Settings:
    return Settings(
        database_url=url,
        tenant_id=tenant,
        embedded_worker=True,
        embedded_channel_worker=False,
        model_backend="demo",
        tools_file=None,
        require_password_change=True,
        api_token=SecretStr("platform-admin"),
        operator_api_token=SecretStr("platform-operator"),
        viewer_api_token=SecretStr("platform-viewer"),
        tool_allowed_hosts=Settings.model_fields["tool_allowed_hosts"].default,
        model_gateway_allowed_hosts=Settings.model_fields["model_gateway_allowed_hosts"].default,
        milvus_url=None,
        milvus_token=None,
        knowledge_parser_url=None,
        knowledge_s3_endpoint=None,
        knowledge_s3_bucket=None,
        knowledge_s3_access_key=None,
        knowledge_s3_secret_key=None,
    )


async def serve(app, port: int) -> tuple[uvicorn.Server, asyncio.Task]:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            return server, task
        await asyncio.sleep(0.05)
    raise RuntimeError("server did not start")


async def seed(client: httpx.AsyncClient, tenant: str) -> dict:
    """Publish one agent and one Service Application through the admin API."""

    from test_model_gateway import setup  # test helper: channel -> model -> profile

    _, _, profile = await setup(client, "chat")
    agent_body = {
        "name": "售后客服",
        "description": "开放平台交付验收",
        "config": {
            "system_prompt": "依据知识回答。",
            "model_profile_id": profile["id"],
            "model_profile_version": 1,
            "tool_names": [],
            "knowledge_base_ids": [],
            "max_model_rounds": 3,
        },
    }
    response = await client.post("/api/v1/agents", json=agent_body)
    response.raise_for_status()
    agent = response.json()
    response = await client.post(f"/api/v1/agents/{agent['id']}/publish", json={"revision": 1})
    response.raise_for_status()

    key = "e2e-app-" + uuid4().hex[:8]
    response = await client.post(
        "/api/v1/service-apps",
        json={
            "key": key,
            "name": "E2E 服务应用",
            "description": "开放平台交付验收",
            "agent_id": agent["id"],
            "agent_version": 1,
        },
    )
    response.raise_for_status()
    response = await client.post(
        f"/api/v1/service-apps/{key}/skills",
        json={"key": "handoff", "name": "转人工", "type": "handoff", "description": "进入默认队列"},
    )
    response.raise_for_status()
    detail = (await client.get(f"/api/v1/service-apps/{key}")).json()
    response = await client.post(
        f"/api/v1/service-apps/{key}/publish", json={"revision": detail["revision"]}
    )
    response.raise_for_status()
    published = (await client.get(f"/api/v1/service-apps/{key}")).json()
    return {"tenant": tenant, "agent": agent, "key": key, "application": published}


async def create_open_app(client: httpx.AsyncClient, application: dict, *, pin: int | None):
    body = {"name": "E2E 交付应用", "service_application_id": application["id"]}
    if pin is not None:
        body["service_application_version"] = pin
    response = await client.post("/api/v1/open-platform/applications", json=body)
    response.raise_for_status()
    app = response.json()
    response = await client.post(f"/api/v1/open-platform/applications/{app['id']}/keys", json={})
    response.raise_for_status()
    return app, response.json()


async def submit(public: httpx.AsyncClient, conversation: str, message: str, idem: str, stream: bool):
    return await public.post(
        f"/openapi/v1/conversations/{conversation}/messages",
        json={"message": message, "stream": stream},
        headers={"Idempotency-Key": idem},
    )


async def read_sse(response: httpx.Response) -> list[dict]:
    events, buffer = [], ""
    async for chunk in response.aiter_text():
        buffer += chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            name, data = None, []
            for line in block.splitlines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
            if data:
                events.append({"event": name, **json.loads("\n".join(data))})
    return events


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("E2E_PORT", "8011")))
    parser.add_argument("--database-url", default=os.environ.get("TEST_DATABASE_URL", ""))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("TEST_DATABASE_URL (or --database-url) is required")

    tenant = "test-e2e-" + uuid4().hex[:8]
    app = create_app(settings_for(args.database_url, tenant))
    checks: list[tuple[str, bool, str]] = []

    server, task = await serve(app, args.port)
    runtime = app.state.runtime
    base = f"http://127.0.0.1:{args.port}"
    try:
        async with httpx.AsyncClient(base_url=base, headers=ADMIN, timeout=60) as admin:
            seeded = await seed(admin, tenant)
            open_app, key = await create_open_app(admin, seeded["application"], pin=None)
            raw = key["key"]

            async with httpx.AsyncClient(
                base_url=base,
                headers={
                    "Authorization": "Bearer " + raw,
                    "X-External-User-ID": "employee-e2e",
                    "Idempotency-Key": "e2e-idem-1",
                },
                timeout=60,
            ) as public:
                targets = await public.get("/openapi/v1/targets")
                body = targets.json()
                target = body.get("target") or {}
                checks.append(
                    (
                        "GET /targets 指向服务应用",
                        targets.status_code == 200
                        and body.get("mode") == "service_application"
                        and target.get("id") == seeded["application"]["id"]
                        and target.get("published_version") == seeded["application"]["published_version"],
                        f"{targets.status_code} {body}",
                    )
                )

                created = await public.post(
                    "/openapi/v1/conversations", json={"external_session_id": "e2e-session-1"}
                )
                conversation = created.json()
                cid = conversation.get("conversation_id")
                checks.append(
                    (
                        "POST /conversations 建会话（无 agent_id）",
                        created.status_code == 201
                        and conversation.get("agent_id") is None
                        and bool(cid),
                        f"{created.status_code} {conversation}",
                    )
                )

                again = await public.post(
                    "/openapi/v1/conversations", json={"external_session_id": "e2e-session-1"}
                )
                checks.append(
                    (
                        "同一外部会话复用",
                        again.status_code == 201
                        and again.json().get("conversation_id") == cid,
                        again.text,
                    )
                )

                streamed = await submit(public, cid, "我要退货", "e2e-idem-msg-1", stream=True)
                events = await read_sse(streamed) if streamed.status_code == 200 else []
                names = [e.get("event") for e in events]
                checks.append(
                    (
                        "SSE 收到终态事件",
                        streamed.status_code == 200 and "run.completed" in names,
                        f"{streamed.status_code} events={names}",
                    )
                )

                run_id = next((e.get("run_id") for e in events if e.get("run_id")), None)
                checks.append(("事件中带 run_id", bool(run_id), str(run_id)))

                if run_id:
                    for _ in range(120):
                        run = (await public.get(f"/openapi/v1/runs/{run_id}")).json()
                        if run.get("status") in {"completed", "failed", "cancelled"}:
                            break
                        await asyncio.sleep(0.25)
                    checks.append(
                        (
                            "运行终态 = completed",
                            run.get("status") == "completed",
                            json.dumps(run, ensure_ascii=False)[:300],
                        )
                    )

                history = (
                    await public.get(f"/openapi/v1/conversations/{cid}/messages")
                ).json()
                roles = [item["role"] for item in history["items"]]
                checks.append(
                    ("会话历史包含 user+assistant", "user" in roles and "assistant" in roles, str(roles))
                )

                replay = await submit(public, cid, "我要退货", "e2e-idem-msg-1", stream=False)
                fresh = await submit(public, cid, "我要退货", "e2e-idem-msg-2", stream=False)
                replay_run = replay.json().get("id") if replay.status_code < 300 else None
                fresh_run = fresh.json().get("id") if fresh.status_code < 300 else None
                checks.append(
                    (
                        "同 Idempotency-Key 重放复用同一 run",
                        replay.status_code < 300
                        and fresh.status_code < 300
                        and bool(replay_run)
                        and bool(fresh_run)
                        and replay_run == run_id,
                        f"replay={replay.status_code} {replay_run} fresh={fresh_run} original={run_id}",
                    )
                )

            ledger_list = await admin.get(
                f"/api/v1/service-apps/{seeded['key']}/conversations?page_size=10"
            )
            items = ledger_list.json()["items"]
            checks.append(
                (
                    "后台工作台可见该会话",
                    ledger_list.status_code == 200 and len(items) >= 1,
                    f"{ledger_list.status_code} n={len(items)}",
                )
            )

        async with runtime.repository.engine.connect() as c:
            row = (
                await c.execute(
                    text(
                        "SELECT source, application_id, application_version FROM runtime_conversations "
                        "WHERE tenant_id=:t ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"t": tenant},
                )
            ).mappings().first()
            checks.append(
                (
                    "runtime 会话 source=open_platform 且钉住应用版本",
                    bool(row)
                    and row["source"] == "open_platform"
                    and str(row["application_id"]) == seeded["application"]["id"]
                    and row["application_version"] == seeded["application"]["published_version"],
                    json.dumps(dict(row) if row else {}, default=str)[:300],
                )
            )
            ledger = (
                await c.execute(
                    text(
                        "SELECT kind, external_user_id, metadata FROM service_application_conversations "
                        "WHERE tenant_id=:t ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"t": tenant},
                )
            ).mappings().first()
            checks.append(
                (
                    "台账行 kind=customer 且标注开放平台来源",
                    bool(ledger)
                    and ledger["kind"] == "customer"
                    and (ledger["metadata"] or {}).get("source") == "open_platform"
                    and (ledger["metadata"] or {}).get("open_app_id") == open_app["id"],
                    json.dumps(dict(ledger) if ledger else {}, default=str)[:300],
                )
            )
            runs = (
                await c.execute(
                    text(
                        "SELECT r.run_id, r.conversation_id, r.idempotency_key, r.payload_hash "
                        "FROM open_runs r JOIN open_applications a ON a.id = r.app_id "
                        "WHERE a.tenant_id=:t"
                    ),
                    {"t": tenant},
                )
            ).mappings().all()
            checks.append(
                ("open_runs 有记录且带 conversation_id", bool(runs) and all(r["conversation_id"] for r in runs), json.dumps([dict(r) for r in runs], default=str)[:300])
            )
            logs = (
                await c.execute(
                    text("SELECT count(*) AS n FROM open_request_logs WHERE tenant_id=:t"),
                    {"t": tenant},
                )
            ).scalar_one()
            checks.append(("open_request_logs 有请求记录", logs > 0, f"n={logs}"))
    finally:
        server.should_exit = True
        await task

    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
