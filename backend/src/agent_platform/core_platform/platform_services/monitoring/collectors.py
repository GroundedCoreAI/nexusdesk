"""Platform collectors: fetch raw data only, never decide a status.

Every collector returns a plain ``dict`` of measurements. Deciding what those
measurements mean belongs to ``rules``; a collector that cannot produce data
raises ``CollectorError`` so the check degrades to ``unknown`` instead of
silently looking healthy.
"""

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agent_platform.core_platform.platform_services.persistence.store import many, one

from .registry import CollectorContext, CollectorError

BACKEND_ROOT = Path(__file__).resolve().parents[5]
MODEL_PROBE_ACTION = "model.connection.probed"
HTTP_PROBE_TIMEOUT = 3.0


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


async def pg_connection(ctx: CollectorContext) -> dict:
    started = time.monotonic()
    try:
        async with ctx.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise CollectorError("pg_unavailable", error_code=type(exc).__name__) from None
    return {"latency_ms": int((time.monotonic() - started) * 1000)}


def _alembic_heads() -> list[str]:
    config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    return list(ScriptDirectory.from_config(config).get_heads())


async def pg_migration(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(conn, "SELECT version_num FROM alembic_version LIMIT 1")
    if row is None:
        raise CollectorError("alembic_version_missing")
    heads = await asyncio.to_thread(_alembic_heads)
    return {
        "revision": str(row["version_num"]),
        "heads": heads,
        "multi_head": len(heads) > 1,
        "behind": str(row["version_num"]) not in heads,
    }


async def pgvector(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn, "SELECT extversion FROM pg_extension WHERE extname = 'vector' LIMIT 1"
        )
    return {"installed": row is not None, "version": (row or {}).get("extversion", "")}


async def db_pool(ctx: CollectorContext) -> dict:
    pool = ctx.engine.pool
    try:
        size = pool.size()
        checked_out = pool.checkedout()
        overflow = pool.overflow()
    except (AttributeError, NotImplementedError) as exc:
        raise CollectorError("pool_metrics_unavailable", error_code=type(exc).__name__) from None
    return {"checked_out": checked_out, "capacity": max(size + overflow, 1)}


async def required_config(ctx: CollectorContext) -> dict:
    settings = ctx.settings
    missing: list[str] = []
    if settings.model_backend == "openai":
        if not settings.model_name:
            missing.append("model_name")
        if not settings.model_api_key:
            missing.append("model_api_key")
        if not settings.model_base_url:
            missing.append("model_base_url")
    if not settings.tenant_id:
        missing.append("tenant_id")
    return {"missing": ",".join(missing), "missing_count": len(missing)}


async def credential_resolve(ctx: CollectorContext) -> dict:
    # The master key materialises every stored credential (model gateway,
    # channels, webhooks, object storage), whatever ``model_backend`` is set to.
    # Gating the probe on the chat backend used to report "not configured" while
    # the key file was present and in use; probe the file unconditionally.
    path = Path(ctx.settings.model_credential_key_file)
    exists = await asyncio.to_thread(path.exists)
    readable = await asyncio.to_thread(lambda: path.is_file() and os.access(path, os.R_OK))
    return {"exists": exists, "readable": readable}


# ---------------------------------------------------------------------------
# Optional integrations
# ---------------------------------------------------------------------------


async def milvus(ctx: CollectorContext) -> dict:
    url = (ctx.settings.milvus_url or "").strip()
    if not url:
        return {"configured": False}
    headers = {"Content-Type": "application/json"}
    token = ctx.settings.milvus_token
    if token is not None:
        headers["Authorization"] = "Bearer " + token.get_secret_value()
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=HTTP_PROBE_TIMEOUT) as client:
            # Milvus serves the REST v2 API and /healthz on different ports
            # (19530 vs 9091), so probing /healthz would report a healthy
            # REST endpoint as broken. Call what the client actually calls.
            response = await client.post(
                url.rstrip("/") + "/v2/vectordb/collections/list",
                json={},
                headers=headers,
            )
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        raise CollectorError(
            "milvus_unreachable",
            error_code=type(exc).__name__,
            latency_ms=int((time.monotonic() - started) * 1000),
        ) from None
    try:
        code = int(response.json().get("code"))
    except (TypeError, ValueError, AttributeError):
        code = -1
    return {
        "configured": True,
        "http_status": response.status_code,
        "code": code,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def _head_bucket(settings, bucket: str) -> None:
    client = boto3.client(
        "s3",
        endpoint_url=settings.knowledge_s3_endpoint,
        aws_access_key_id=settings.knowledge_s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.knowledge_s3_secret_key.get_secret_value(),
        region_name="us-east-1",
        config=BotoConfig(
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 1},
            s3={"addressing_style": "path"},
        ),
    )
    try:
        client.head_bucket(Bucket=bucket)
    finally:
        client.close()


async def object_storage(ctx: CollectorContext) -> dict:
    settings = ctx.settings
    bucket = settings.knowledge_s3_bucket
    if not (bucket and settings.knowledge_s3_access_key and settings.knowledge_s3_secret_key):
        return {"configured": False}
    started = time.monotonic()
    try:
        await asyncio.to_thread(_head_bucket, settings, bucket)
    except (BotoCoreError, OSError, TimeoutError) as exc:
        raise CollectorError(
            "object_storage_unreachable",
            error_code=type(exc).__name__,
            bucket=bucket,
            latency_ms=int((time.monotonic() - started) * 1000),
        ) from None
    return {
        "configured": True,
        "bucket": bucket,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


async def knowledge_parser(ctx: CollectorContext) -> dict:
    url = (ctx.settings.knowledge_parser_url or "").strip()
    if not url:
        return {"configured": False}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=HTTP_PROBE_TIMEOUT) as client:
            response = await client.get(url.rstrip("/") + "/health")
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        raise CollectorError(
            "parser_unreachable",
            error_code=type(exc).__name__,
            latency_ms=int((time.monotonic() - started) * 1000),
        ) from None
    # A 404 still proves the service is up; deployments without a /health route
    # must not be reported as an outage.
    return {
        "configured": True,
        "http_status": response.status_code,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


# ---------------------------------------------------------------------------
# Model gateway
# ---------------------------------------------------------------------------

PUBLISHED_CHAT_PROFILES = """
    FROM gateway_profiles p
    JOIN gateway_models m ON m.id = (p.spec->>'model_id')::uuid
    JOIN gateway_connections k ON k.id = (m.spec->>'connection_id')::uuid
    WHERE p.tenant_id = :t AND p.published_version IS NOT NULL
      AND p.spec->>'operation' = 'chat'
"""


async def model_chat_available(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            "SELECT count(*)::int AS n,"
            " count(*) FILTER (WHERE p.enabled AND m.enabled AND k.enabled"
            "   AND k.spec->>'protocol' <> 'demo')::int AS usable " + PUBLISHED_CHAT_PROFILES,
            t=ctx.tenant,
        )
    return {"published": row["n"], "usable": row["usable"]}


async def model_profile_capability(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            "SELECT count(*) FILTER (WHERE"
            "   COALESCE((p.spec->>'require_tools')::boolean, false)"
            "   AND NOT COALESCE((m.spec->>'tool_calling')::boolean, false))::int AS missing_tools"
            + PUBLISHED_CHAT_PROFILES,
            t=ctx.tenant,
        )
    return {"missing_tools": row["missing_tools"]}


async def model_profile_consistency(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS broken,
            count(*) FILTER (WHERE NOT p.enabled)::int AS disabled_profile,
            count(*) FILTER (WHERE NOT m.enabled)::int AS disabled_model,
            count(*) FILTER (WHERE NOT k.enabled)::int AS disabled_connection
            FROM gateway_profiles p
            JOIN gateway_models m ON m.id = (p.spec->>'model_id')::uuid
            JOIN gateway_connections k ON k.id = (m.spec->>'connection_id')::uuid
            WHERE p.tenant_id = :t AND p.published_version IS NOT NULL
              AND (NOT p.enabled OR NOT m.enabled OR NOT k.enabled)""",
            t=ctx.tenant,
        )
    return dict(row)


async def model_success_rate(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS samples,
            count(*) FILTER (WHERE status = 'completed')::int AS completed,
            count(*) FILTER (WHERE status = 'failed')::int AS failed
            FROM gateway_calls
            WHERE tenant_id = :t AND created_at > now() - interval '24 hours'""",
            t=ctx.tenant,
        )
    return dict(row)


async def model_error_class(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS samples,
            count(*) FILTER (WHERE a.error_code IN
              ('model_timeout', 'model_transport_error', 'model_provider_unavailable'))::int AS bad
            FROM gateway_attempts a JOIN gateway_calls c ON c.id = a.call_id
            WHERE c.tenant_id = :t AND a.created_at > now() - interval '24 hours'""",
            t=ctx.tenant,
        )
    return dict(row)


async def model_latency(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        recent = await one(
            conn,
            """SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95,
            count(*)::int AS samples
            FROM gateway_calls
            WHERE tenant_id = :t AND duration_ms IS NOT NULL
              AND created_at > now() - interval '24 hours'""",
            t=ctx.tenant,
        )
        baseline = await one(
            conn,
            """SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
            FROM gateway_calls
            WHERE tenant_id = :t AND duration_ms IS NOT NULL
              AND created_at BETWEEN now() - interval '8 days' AND now() - interval '1 day'""",
            t=ctx.tenant,
        )
    return {
        "p95_ms": recent["p95"],
        "baseline_p95_ms": baseline["p95"] if baseline else None,
        "samples": recent["samples"],
    }


async def model_quota(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS active FROM gateway_leases
            WHERE tenant_id = :t AND expires_at > now()""",
            t=ctx.tenant,
        )
    return {"active_leases": row["active"], "capacity": ctx.settings.model_gateway_concurrency}


async def model_probe_freshness(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        probe = await one(
            conn,
            """SELECT max(created_at) AS last_at,
            count(*)::int AS samples,
            (array_agg(details->>'status' ORDER BY created_at DESC))[1] AS last_status,
            (array_agg(details->>'error_code' ORDER BY created_at DESC))[1] AS last_error
            FROM audit_records
            WHERE tenant_id = :t AND action = :action""",
            t=ctx.tenant,
            action=MODEL_PROBE_ACTION,
        )
        traffic = await one(
            conn,
            """SELECT max(completed_at) AS last_at FROM gateway_calls
            WHERE tenant_id = :t AND status = 'completed'""",
            t=ctx.tenant,
        )
    probe_at = probe["last_at"] if probe else None
    traffic_at = traffic["last_at"] if traffic else None
    stamps = [stamp for stamp in (probe_at, traffic_at) if stamp is not None]
    last_at = max(stamps) if stamps else None
    age_seconds = (datetime.now(UTC) - last_at).total_seconds() if last_at else None
    return {
        "age_seconds": age_seconds,
        "probe_samples": probe["samples"] if probe else 0,
        "last_probe_status": (probe or {}).get("last_status") or "",
        "last_probe_error": (probe or {}).get("last_error") or "",
    }


# ---------------------------------------------------------------------------
# Workers and queues
# ---------------------------------------------------------------------------


async def worker_heartbeat(ctx: CollectorContext) -> dict:
    """Measure every role the deployment is supposed to run, one by one.

    Reading only the newest row made this check mean "some process is alive":
    the API process beats for the loops it embeds, so a dead standalone worker
    stayed invisible for as long as the API was up.
    """

    expected = list(getattr(ctx.settings, "expected_worker_roles", ()) or ())
    async with ctx.engine.connect() as conn:
        rows = await many(
            conn,
            """SELECT worker_id, EXTRACT(EPOCH FROM now() - beat_at) AS age_seconds
            FROM worker_heartbeats""",
        )
    ages = {str(row["worker_id"]): float(row["age_seconds"] or 0) for row in rows}
    present = {role: age for role, age in ages.items() if role in expected}
    timeout = float(ctx.settings.monitor_worker_heartbeat_timeout_seconds)
    missing = [role for role in expected if role not in ages]
    stale = [role for role, age in present.items() if age > timeout]
    return {
        "expected": ",".join(expected),
        "missing": ",".join(missing),
        "stale": ",".join(stale),
        "alive": len(present) - len(stale),
        "total": len(expected),
        "age_seconds": max(present.values(), default=0.0),
    }


async def queue_runtime(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS queued,
            EXTRACT(EPOCH FROM now() - min(created_at)) AS oldest_seconds
            FROM runtime_runs WHERE tenant_id = :t AND status = 'queued'""",
            t=ctx.tenant,
        )
    oldest = row["oldest_seconds"]
    return {"queued": row["queued"], "oldest_seconds": float(oldest) if oldest else 0.0}


async def runtime_lease_expired(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS expired FROM runtime_runs
            WHERE tenant_id = :t AND status = 'running'
              AND lease_until IS NOT NULL AND lease_until < now()""",
            t=ctx.tenant,
        )
    return {"expired": row["expired"]}


async def monitor_scan(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT EXTRACT(EPOCH FROM now() - (
                SELECT COALESCE(max(finished_at), max(started_at)) FROM monitor_scans
            )) AS age_seconds""",
        )
    # The current scan row is inserted before checks run, so a scanner that is
    # alive always has a fresh stamp; NULL means nothing has ever scanned.
    if row is None or row["age_seconds"] is None:
        raise CollectorError("no_scan_recorded")
    return {"age_seconds": float(row["age_seconds"] or 0)}
