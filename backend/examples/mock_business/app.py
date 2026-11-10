"""Mock business API for the console's demo industries.

Why this exists: the customer-service demo ships 15 object providers and 22
tool providers, but a provider only stops being a placeholder once its
``config.executors`` points at a real HTTP tool. This service is that upstream.

Two rules keep it importable into the tool gateway:

1. Every route has a fixed path and takes input as query parameters (GET) or a
   JSON body (POST). The gateway cannot build URLs with path templating, and the
   OpenAPI importer skips any path containing ``{``.
2. Every ``operation_id`` is already a valid gateway tool name
   (``^[a-zA-Z][a-zA-Z0-9_]{0,63}$``), so importing the spec produces callable
   names instead of something that has to be renamed afterwards.

Responses use one envelope so a provider executor can point ``result_root`` at
``data`` (single object) or ``data.items`` (list) and leave the rest alone.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import fixtures as fx

TOKEN = os.environ.get("MOCK_AUTH_TOKEN", "").strip()
LATENCY_MS = int(os.environ.get("MOCK_LATENCY_MS", "0") or 0)

app = FastAPI(
    title="NexusDesk mock business API",
    version="1.0.0",
    description="本地演示用的外部业务系统，覆盖购物、游戏、创作者、出行、社区五个行业包。",
)


class Body(BaseModel):
    """Request bodies are declared, never free-form.

    A ``dict[str, Any]`` body is published as ``additionalProperties: true``,
    which the tool gateway rejects: a tool's parameter schema must be a closed
    object. Declaring the fields keeps the mock importable.
    """

    model_config = ConfigDict(extra="forbid")


class AfterSaleCreate(Body):
    order_no: str = Field(description="订单号")
    reason: str = Field(default="", description="售后原因")


class InvoiceCreate(Body):
    order_no: str = Field(description="订单号")
    invoice_title: str = Field(default="个人", description="发票抬头")


class RechargeReport(Body):
    order_no: str = Field(description="充值单号")


class SanctionAppeal(Body):
    record_no: str = Field(description="处罚记录号")
    note: str = Field(default="", description="申诉说明")


class ReviewAppeal(Body):
    record_no: str = Field(description="审核记录号")
    note: str = Field(default="", description="申诉说明")


class CopyrightComplaint(Body):
    work_id: str = Field(description="作品 ID")
    evidence: str = Field(default="", description="权属证明说明")


class LostItemReport(Body):
    trip_no: str = Field(description="行程号")
    item: str = Field(description="遗失物品描述")


class FareDispute(Body):
    fare_trip_no: str = Field(description="行程号")
    reason: str = Field(default="", description="异议说明")

# Mutating calls land here so a reset restores the documented fixtures.
CREATED: list[dict[str, Any]] = []
FAULT = {"mode": "", "remaining": 0}
COUNTER = {"requests": 0}
SEQ: dict[str, int] = {}


def ok(data: Any) -> dict[str, Any]:
    return {"code": 0, "message": "ok", "data": data}


def not_found(message: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"code": 40401, "message": message, "data": None})


def page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"code": 0, "message": "ok", "data": {"items": items, "total": len(items)}}


def next_no(prefix: str) -> str:
    """Generated identifiers start at 9001 so they never collide with fixtures."""

    SEQ[prefix] = SEQ.get(prefix, 9000) + 1
    return f"{prefix}{SEQ[prefix]}"


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


@app.middleware("http")
async def simulate(request: Request, call_next):
    """Apply auth, latency and fault injection before the route runs."""

    if TOKEN and request.url.path not in {"/health", "/openapi.json"}:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"code": 40101, "message": "missing bearer token", "data": None},
            )
        if header.removeprefix("Bearer ").strip() != TOKEN:
            return JSONResponse(
                status_code=403,
                content={"code": 40301, "message": "invalid token", "data": None},
            )

    if LATENCY_MS:
        await asyncio.sleep(LATENCY_MS / 1000)

    if request.url.path == "/_admin/fault" or request.url.path == "/_admin/reset":
        return await call_next(request)

    COUNTER["requests"] += 1
    mode = request.query_params.get("__fault", "") or request.headers.get("x-mock-fault", "")
    if not mode and FAULT["remaining"] > 0:
        mode = FAULT["mode"]
        FAULT["remaining"] -= 1

    delay = request.query_params.get("__delay")
    if delay:
        await asyncio.sleep(min(float(delay), 30))

    if mode == "timeout":
        await asyncio.sleep(int(os.environ.get("MOCK_TIMEOUT_SECONDS", "35")))
    injected = {
        "404": (404, 40400, "injected not found"),
        "403": (403, 40300, "injected forbidden"),
        "500": (500, 50000, "injected upstream failure"),
    }.get(mode)
    if injected:
        status, code, message = injected
        return JSONResponse(status_code=status, content={"code": code, "message": message, "data": None})
    return await call_next(request)


@app.get("/health", operation_id="mock_health", summary="健康检查")
async def health() -> dict[str, Any]:
    return {"status": "ok", "requests": COUNTER["requests"], "created": len(CREATED)}


@app.post("/_admin/reset", operation_id="mock_admin_reset", summary="重置演示数据")
async def reset() -> dict[str, Any]:
    CREATED.clear()
    SEQ.clear()
    FAULT.update({"mode": "", "remaining": 0})
    COUNTER["requests"] = 0
    return {"status": "reset"}


@app.post("/_admin/fault", operation_id="mock_admin_fault", summary="注入故障")
async def set_fault(mode: str = "", count: int = 0) -> dict[str, Any]:
    FAULT.update({"mode": mode, "remaining": max(count, 0)})
    return {"status": "ok", "mode": mode, "remaining": FAULT["remaining"]}


# --------------------------------------------------------------------------
# 购物：purchase_order / shipment / after_sale_ticket
# --------------------------------------------------------------------------


@app.get("/orders", operation_id="shopping_order_status", summary="查询订单状态")
async def order_status(order_no: str = Query(..., description="订单号，如 PO20261110001")) -> Any:
    order = fx.ORDERS.get(order_no)
    return not_found(f"订单不存在: {order_no}") if order is None else ok(order)


@app.get("/orders/list", operation_id="shopping_order_list", summary="查询客户订单列表")
async def order_list(
    customer_id: str = Query(..., description="客户号，如 C1001"),
    limit: int = Query(20, ge=1, le=50, description="返回条数"),
) -> Any:
    items = [o for o in fx.ORDERS.values() if o["customer_id"] == customer_id][:limit]
    return page(items)


@app.get("/shipments", operation_id="shopping_shipment_track", summary="查询物流轨迹")
async def shipment_track(tracking_no: str = Query(..., description="运单号")) -> Any:
    shipment = fx.SHIPMENTS.get(tracking_no)
    return not_found(f"运单不存在: {tracking_no}") if shipment is None else ok(shipment)


@app.get("/after-sales", operation_id="shopping_after_sale_status", summary="查询售后单进度")
async def after_sale_status(ticket_no: str = Query(..., description="售后单号")) -> Any:
    ticket = fx.AFTER_SALES.get(ticket_no)
    return not_found(f"售后单不存在: {ticket_no}") if ticket is None else ok(ticket)


@app.post("/after-sales", operation_id="shopping_after_sale_create", summary="创建售后申请")
async def after_sale_create(body: AfterSaleCreate) -> Any:
    order_no = body.order_no.strip()
    if order_no not in fx.ORDERS:
        return not_found(f"订单不存在: {order_no}")
    ticket = {
        "ticket_no": next_no("AS"),
        "order_no": order_no,
        "status": "待商家确认",
        "reason": body.reason or "未填写",
        "submitted_at": now(),
        "resolution": "",
    }
    CREATED.append(ticket)
    return ok(ticket)


@app.post("/invoices", operation_id="shopping_invoice_create", summary="申请开票")
async def invoice_create(body: InvoiceCreate) -> Any:
    order_no = body.order_no.strip()
    order = fx.ORDERS.get(order_no)
    if order is None:
        return not_found(f"订单不存在: {order_no}")
    invoice = {
        "invoice_no": next_no("IV"),
        "order_no": order_no,
        "amount": order["paid_amount"],
        "invoice_title": body.invoice_title or "个人",
        "invoice_status": "开票中",
    }
    CREATED.append(invoice)
    return ok(invoice)


# --------------------------------------------------------------------------
# 游戏：game_role / recharge_order / sanction_record
# --------------------------------------------------------------------------


@app.get("/game/roles", operation_id="gaming_role_status", summary="查询游戏角色")
async def role_status(role_id: str = Query(..., description="角色 ID，如 ROLE-1001")) -> Any:
    role = fx.GAME_ROLES.get(role_id)
    return not_found(f"角色不存在: {role_id}") if role is None else ok(role)


@app.get("/game/recharges", operation_id="gaming_recharge_status", summary="查询充值到账")
async def recharge_status(order_no: str = Query(..., description="充值单号")) -> Any:
    record = fx.RECHARGES.get(order_no)
    return not_found(f"充值单不存在: {order_no}") if record is None else ok(record)


@app.post("/game/recharges/missing-report", operation_id="gaming_recharge_report", summary="上报充值未到账")
async def recharge_report(body: RechargeReport) -> Any:
    order_no = body.order_no.strip()
    record = fx.RECHARGES.get(order_no)
    if record is None:
        return not_found(f"充值单不存在: {order_no}")
    report = {
        "report_no": next_no("RP"),
        "order_no": order_no,
        "report_status": "已受理",
        "expected_arrival": "2 小时内",
    }
    CREATED.append(report)
    return ok(report)


@app.get("/game/sanctions", operation_id="gaming_sanction_status", summary="查询处罚记录")
async def sanction_status(record_no: str = Query(..., description="处罚记录号")) -> Any:
    record = fx.SANCTIONS.get(record_no)
    return not_found(f"处罚记录不存在: {record_no}") if record is None else ok(record)


@app.post("/game/sanctions/appeal", operation_id="gaming_sanction_appeal", summary="提交处罚申诉")
async def sanction_appeal(body: SanctionAppeal) -> Any:
    record_no = body.record_no.strip()
    if record_no not in fx.SANCTIONS:
        return not_found(f"处罚记录不存在: {record_no}")
    appeal = {
        "appeal_no": next_no("AP"),
        "record_no": record_no,
        "appeal_status": "审核中",
        "submitted_at": now(),
    }
    CREATED.append(appeal)
    return ok(appeal)


# --------------------------------------------------------------------------
# 创作者：creator_account / content_work / review_record / revenue_statement
# --------------------------------------------------------------------------


@app.get("/creator/accounts", operation_id="creator_account_status", summary="查询创作者账号")
async def creator_account(creator_id: str = Query(..., description="创作者 ID，如 CR-2001")) -> Any:
    account = fx.CREATOR_ACCOUNTS.get(creator_id)
    return not_found(f"创作者不存在: {creator_id}") if account is None else ok(account)


@app.get("/creator/works", operation_id="creator_work_status", summary="查询作品审核状态")
async def work_status(work_id: str = Query(..., description="作品 ID，如 WK20261110001")) -> Any:
    work = fx.WORKS.get(work_id)
    return not_found(f"作品不存在: {work_id}") if work is None else ok(work)


@app.get("/creator/works/list", operation_id="creator_work_list", summary="查询创作者作品列表")
async def work_list(
    creator_id: str = Query(..., description="创作者 ID"),
    limit: int = Query(20, ge=1, le=50, description="返回条数"),
) -> Any:
    items = [w for w in fx.WORKS.values() if w["creator_id"] == creator_id][:limit]
    return page(items)


@app.get("/creator/reviews", operation_id="creator_review_record", summary="查询审核记录")
async def review_record(record_no: str = Query(..., description="审核记录号")) -> Any:
    record = fx.REVIEW_RECORDS.get(record_no)
    return not_found(f"审核记录不存在: {record_no}") if record is None else ok(record)


@app.post("/creator/reviews/appeal", operation_id="creator_review_appeal", summary="提交审核申诉")
async def review_appeal(body: ReviewAppeal) -> Any:
    record_no = body.record_no.strip()
    if record_no not in fx.REVIEW_RECORDS:
        return not_found(f"审核记录不存在: {record_no}")
    appeal = {
        "appeal_no": next_no("RA"),
        "record_no": record_no,
        "appeal_status": "审核中",
        "expect_reply_hours": 48,
    }
    CREATED.append(appeal)
    return ok(appeal)


@app.post("/creator/copyright/complaints", operation_id="creator_copyright_complaint", summary="提交版权投诉")
async def copyright_complaint(body: CopyrightComplaint) -> Any:
    work_id = body.work_id.strip()
    if work_id not in fx.WORKS:
        return not_found(f"作品不存在: {work_id}")
    complaint = {
        "complaint_no": next_no("CC"),
        "work_id": work_id,
        "complaint_status": "已受理",
        "expect_reply_hours": 72,
    }
    CREATED.append(complaint)
    return ok(complaint)


@app.get("/creator/revenue", operation_id="creator_revenue_status", summary="查询收益结算单")
async def revenue_status(
    creator_id: str = Query(..., description="创作者 ID"),
    period: str = Query("", description="结算周期，如 2026-10，留空取最近一期"),
) -> Any:
    rows = [r for r in fx.REVENUE if r["creator_id"] == creator_id and (not period or r["period"] == period)]
    if not rows:
        return not_found(f"没有找到结算单: {creator_id} {period}".strip())
    return ok(rows[0])


# --------------------------------------------------------------------------
# 出行：trip_order / fare_breakdown
# --------------------------------------------------------------------------


@app.get("/mobility/trips", operation_id="mobility_trip_status", summary="查询行程状态")
async def trip_status(trip_no: str = Query(..., description="行程号，如 TR20261110001")) -> Any:
    trip = fx.TRIPS.get(trip_no)
    return not_found(f"行程不存在: {trip_no}") if trip is None else ok(trip)


@app.post("/mobility/trips/lost-items", operation_id="mobility_lost_item_report", summary="上报遗失物品")
async def lost_item_report(body: LostItemReport) -> Any:
    trip_no = body.trip_no.strip()
    if trip_no not in fx.TRIPS:
        return not_found(f"行程不存在: {trip_no}")
    report = {
        "report_no": next_no("LI"),
        "trip_no": trip_no,
        "item": body.item or "未填写",
        "report_status": "已登记",
        "contact_deadline": "48 小时内联系",
    }
    CREATED.append(report)
    return ok(report)


@app.get("/mobility/fares", operation_id="mobility_fare_detail", summary="查询计价明细")
async def fare_detail(fare_trip_no: str = Query(..., description="行程号")) -> Any:
    fare = fx.FARES.get(fare_trip_no)
    return not_found(f"计价单不存在: {fare_trip_no}") if fare is None else ok(fare)


@app.post("/mobility/fares/dispute", operation_id="mobility_fare_dispute", summary="提交费用异议")
async def fare_dispute(body: FareDispute) -> Any:
    trip_no = body.fare_trip_no.strip()
    if trip_no not in fx.FARES:
        return not_found(f"计价单不存在: {trip_no}")
    dispute = {
        "dispute_no": next_no("FD"),
        "fare_trip_no": trip_no,
        "dispute_status": "核实中",
        "expect_reply_hours": 24,
    }
    CREATED.append(dispute)
    return ok(dispute)


# --------------------------------------------------------------------------
# 社区：community_account / community_content / membership_entitlement
# --------------------------------------------------------------------------


@app.get("/community/accounts", operation_id="community_account_status", summary="查询社区账号")
async def community_account(account_id: str = Query(..., description="账号 ID，如 ACC-3001")) -> Any:
    account = fx.COMMUNITY_ACCOUNTS.get(account_id)
    return not_found(f"账号不存在: {account_id}") if account is None else ok(account)


@app.get("/community/contents", operation_id="community_content_status", summary="查询社区内容状态")
async def community_content(content_id: str = Query(..., description="内容 ID")) -> Any:
    content = fx.COMMUNITY_CONTENTS.get(content_id)
    return not_found(f"内容不存在: {content_id}") if content is None else ok(content)


@app.get("/community/memberships", operation_id="community_membership_entitlement", summary="查询会员权益")
async def membership_entitlement(account_id: str = Query(..., description="账号 ID")) -> Any:
    membership = fx.MEMBERSHIPS.get(account_id)
    return not_found(f"会员信息不存在: {account_id}") if membership is None else ok(membership)
