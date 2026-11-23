"""Opt-in synthetic governance demo dataset for the execution platform.

This seeder is deliberately separate from ``seed_execution_platform``. The
formal platform demo dataset seeds *no* fencing/usage/grant rows (its test
pins that contract). This module fills the six Phase 6-2 governance signals
with clearly synthetic, deterministic rows so a quickstart that opts in can
see representative data in the 执行治理 panel:

* fencing denials (2), replay gaps (2), usage conflicts (chain + duplicate),
  parser diagnostics (2), an Outbox pending error, an unconfirmed-cancel
  cleanup row, and a revoked synthetic credential with audit rows.

Everything here is synthetic demonstration data, **not acceptance evidence**.
No real key, secret, live process or credential grant is ever created. The
module is opt-in (``AGENT_SEED_EXECUTION_GOVERNANCE_DEMO``), idempotent on
re-run, and preserves rows an operator has edited. It is never called by
bootstrap unless that flag is explicitly enabled.

Standalone verification is available with::

    python -m agent_platform.applications.seed_execution_governance
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.applications.seed_memory_i18n import T, set_locale
from agent_platform.core_platform.agent_execution.credentials.vault import (
    ExecutionCredentialKeyError,
)
from agent_platform.core_platform.platform_services.persistence.store import one
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    resource_scope_values,
)

# Own namespace/lock/batch so ids never collide with the platform seeder.
BATCH = "execution-governance-demo-v1"
ACTOR = "execution_demo_governance_seed"
LOCK_ID = 71432029
ROOT_NS = UUID("a27f4d31-9b6c-4e08-8f5d-2c1b7e9a3d40")

# Prefix for every free-form synthetic value (reason codes, actor, errors).
SYNTHETIC = "execution_demo_governance_"
# Distinct input prefix so governance demo runs never overlap platform demo runs.
INPUT_PREFIX = "[execution-governance-demo]"

CONVERSATION_KEY = "governance-conversation"
RUN_SIGNALS = "governance-run-signals"
RUN_CANCEL = "governance-run-unconfirmed-cancel"

ENGINE_ID = "react"
CANARY_SECRET = "execution-governance-canary-not-a-real-secret"  # synthetic, never a real key

COUNT_KEYS = (
    "conversations",
    "runs",
    "events",
    "outbox",
    "fencing_denials",
    "replay_gaps",
    "usage_rows",
    "parser_diagnostics",
    "credentials",
    "credential_audits",
)

NOW = datetime.now(UTC)


def resource_id(tenant: str, kind: str, key: str) -> str:
    """Stable tenant-scoped identity for a governance demo row."""

    return str(uuid5(ROOT_NS, f"agent-platform:{tenant}:{BATCH}:{kind}:{key}"))


def ts(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def new_counts() -> dict[str, int]:
    return {key: 0 for key in COUNT_KEYS}


def credential_name() -> str:
    return T(
        zh="[演示] 执行治理合成凭据（已吊销，无真实密钥）",
        en="[Demo] Execution governance synthetic credential (revoked, no real secret)",
        zh_tw="[演示] 執行治理合成憑證（已吊銷，無真實金鑰）",
        hi="[डेमो] सिंथेटिक गवर्नेंस क्रेडेंशियल (रद्द, कोई वास्तविक कुंजी नहीं)",
    )


def credential_names() -> tuple[str, ...]:
    """All localized names so a locale switch cannot duplicate the credential."""

    return (
        "[演示] 执行治理合成凭据（已吊销，无真实密钥）",
        "[Demo] Execution governance synthetic credential (revoked, no real secret)",
        "[演示] 執行治理合成憑證（已吊銷，無真實金鑰）",
        "[डेमो] सिंथेटिक गवर्नेंस क्रेडेंशियल (रद्द, कोई वास्तविक कुंजी नहीं)",
    )


def _run_config() -> str:
    return json.dumps(
        {
            "fingerprint": f"{BATCH}-fingerprint",
            "side_effect_policy": {"allow_external": False},
            "synthetic": True,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


async def _ensure_conversation(conn: Any, tenant: str, counts: dict[str, int]) -> str:
    """Create the single scoped conversation the governance demo runs attach to."""

    existing = await one(
        conn,
        """SELECT id FROM runtime_conversations
           WHERE tenant_id=:t AND external_id=:e""",
        t=tenant,
        e=CONVERSATION_KEY,
    )
    if existing:
        return str(existing["id"])
    identifier = resource_id(tenant, "conversation", CONVERSATION_KEY)
    await conn.execute(
        text("""INSERT INTO runtime_conversations(
                    id,tenant_id,business_id,workspace_id,external_id,history,mode,source,summary,created_at)
                VALUES(:id,:t,:business_id,:workspace_id,:e,CAST(:h AS jsonb),'bot','business',:s,:ca)
                ON CONFLICT DO NOTHING"""),
        {
            "id": identifier,
            "t": tenant,
            **resource_scope_values(),
            "e": CONVERSATION_KEY,
            "h": json.dumps(
                [
                    {
                        "role": "assistant",
                        "content": T(
                            zh="[演示] 合成治理演示会话（非验收证据）。",
                            en="[Demo] Synthetic governance demo conversation (not acceptance evidence).",
                            zh_tw="[演示] 合成治理演示會話（非驗收證據）。",
                            hi="[डेमो] सिंथेटिक गवर्नेंस डेमो बातचीत (स्वीकृति प्रमाण नहीं)।",
                        ),
                    }
                ],
                ensure_ascii=False,
            ),
            "s": T(
                zh="[演示] 执行治理合成演示",
                en="[Demo] Execution governance synthetic demo",
                zh_tw="[演示] 執行治理合成演示",
                hi="[डेमो] निष्पादन गवर्नेंस सिंथेटिक डेमो",
            ),
            "ca": ts(3),
        },
    )
    counts["conversations"] += 1
    return identifier


async def _ensure_run(
    conn: Any,
    tenant: str,
    conversation_id: str,
    run_key: str,
    *,
    status: str,
    cancel_requested: bool,
    cancel_confirmed: bool,
    cleanup_status: str,
    counts: dict[str, int],
) -> str:
    """Create a dedicated governance demo run; never mutates platform demo runs."""

    run_id = resource_id(tenant, "run", run_key)
    existing = await one(conn, "SELECT id FROM runtime_runs WHERE id=:id", id=run_id)
    if existing:
        return run_id
    created = ts(2) + timedelta(minutes=1)
    finished = created + timedelta(milliseconds=600)
    await conn.execute(
        text("""INSERT INTO runtime_runs(
                    id,conversation_id,tenant_id,business_id,workspace_id,input,config,
                    status,cancel_requested,cancel_requested_at,cancel_confirmed_at,
                    event_seq,queue_expires_at,created_at,finished_at,cleanup_status,
                    cleanup_updated_at,lease_epoch,attempt_no,error_code)
                VALUES(:id,:c,:t,:business_id,:workspace_id,:inp,CAST(:cfg AS jsonb),
                    :st,:cr,:cra,:cca,0,:qe,:ca,:fa,:cl,:clu,0,1,:err)
                ON CONFLICT DO NOTHING"""),
        {
            "id": run_id,
            "c": conversation_id,
            "t": tenant,
            **resource_scope_values(),
            "inp": f"{INPUT_PREFIX} {run_key}",
            "cfg": _run_config(),
            "st": status,
            "cr": cancel_requested,
            "cra": created + timedelta(milliseconds=120) if cancel_requested else None,
            "cca": finished if cancel_confirmed else None,
            "qe": created + timedelta(minutes=2),
            "ca": created,
            "fa": finished,
            "cl": cleanup_status,
            "clu": finished,
            "err": f"{SYNTHETIC}demo_failure" if status == "failed" else None,
        },
    )
    counts["runs"] += 1
    return run_id


async def _ensure_events(conn: Any, run_id: str, counts: dict[str, int]) -> None:
    """Create run events; the 0070 trigger enqueues their Outbox rows.

    The enqueued Outbox rows stay pending. One is marked with a synthetic
    last_error so the Outbox governance panel shows a representative failure
    without invoking any live worker. Re-runs never touch existing rows.
    """

    existing = await one(
        conn, "SELECT seq FROM runtime_events WHERE run_id=:r LIMIT 1", r=run_id
    )
    if existing:
        return
    for seq, event_type, data in (
        (1, "run.queued", {}),
        (2, "run.started", {}),
        (
            3,
            "run.completed",
            {
                "output": T(
                    zh="[演示] 合成治理演示完成。",
                    en="[Demo] Synthetic governance demo completed.",
                    zh_tw="[演示] 合成治理演示完成。",
                    hi="[डेमो] सिंथेटिक गवर्नेंस डेमो पूरा हुआ।",
                ),
                "error_code": None,
            },
        ),
    ):
        await conn.execute(
            text("""INSERT INTO runtime_events(run_id,seq,type,data,created_at)
                    VALUES(:r,:s,:ty,CAST(:d AS jsonb),:ca) ON CONFLICT DO NOTHING"""),
            {
                "r": run_id,
                "s": seq,
                "ty": event_type,
                "d": json.dumps(data, ensure_ascii=False),
                "ca": ts(2) + timedelta(minutes=1, milliseconds=seq * 10),
            },
        )
    counts["events"] += 3
    # Set one Outbox row into a representative pending-with-error state. The
    # trigger created the row as pending; only the demo error fields change.
    result = await conn.execute(
        text("""UPDATE runtime_event_outbox
                SET status='pending', attempts=3, available_at=:at,
                    last_error=:err, published_at=NULL
                WHERE run_id=:r AND seq=3 AND last_error IS NULL"""),
        {
            "r": run_id,
            "at": ts(1),
            "err": f"{SYNTHETIC}outbox_delivery_failed_sample",
        },
    )
    counts["outbox"] += result.rowcount or 0


async def _ensure_fencing(conn: Any, tenant: str, run_id: str, counts: dict[str, int]) -> None:
    """Two synthetic fencing denials. reason/operation are enum-constrained, so
    the synthetic marker is the demo run reference and the synthetic owners."""

    specs = (
        ("snapshot", "stale_epoch", "stale-owner", 1, "current-owner", 3),
        ("append", "owner_mismatch", "other-owner", 2, "current-owner", 3),
    )
    for index, (operation, reason, stale_key, stale_epoch, current_key, current_epoch) in enumerate(
        specs, start=1
    ):
        identifier = resource_id(tenant, "fencing", f"denial-{index}")
        existing = await one(
            conn, "SELECT id FROM execution_fencing_denials WHERE id=:id", id=identifier
        )
        if existing:
            continue
        await conn.execute(
            text("""INSERT INTO execution_fencing_denials(
                        id,run_id,operation,reason,stale_owner,stale_lease_epoch,
                        current_owner,current_lease_epoch,created_at)
                    VALUES(:id,:r,:op,:reason,:so,:se,:co,:ce,:ca)
                    ON CONFLICT DO NOTHING"""),
            {
                "id": identifier,
                "r": run_id,
                "op": operation,
                "reason": reason,
                "so": resource_id(tenant, "fencing-owner", stale_key),
                "se": stale_epoch,
                "co": resource_id(tenant, "fencing-owner", current_key),
                "ce": current_epoch,
                "ca": ts(2),
            },
        )
        counts["fencing_denials"] += 1


async def _ensure_replay_gaps(conn: Any, tenant: str, run_id: str, counts: dict[str, int]) -> None:
    """Two synthetic cursor-below-floor replay gaps.

    reason_code is enum-constrained to 'cursor_below_floor', so the synthetic
    marker is the deterministic id and the demo run reference.
    """

    for index, (requested, floor) in enumerate(((1, 5), (2, 6)), start=1):
        identifier = resource_id(tenant, "replay-gap", f"gap-{index}")
        existing = await one(
            conn, "SELECT id FROM execution_replay_gap_events WHERE id=:id", id=identifier
        )
        if existing:
            continue
        await conn.execute(
            text("""INSERT INTO execution_replay_gap_events(
                        id,run_id,tenant_id,requested_cursor_seq,retention_floor_seq,
                        reason_code,created_at)
                    VALUES(:id,:r,:t,:req,:floor,'cursor_below_floor',:ca)
                    ON CONFLICT DO NOTHING"""),
            {
                "id": identifier,
                "r": run_id,
                "t": tenant,
                "req": requested,
                "floor": floor,
                "ca": ts(2),
            },
        )
        counts["replay_gaps"] += 1


async def _ensure_usage(conn: Any, tenant: str, run_id: str, counts: dict[str, int]) -> None:
    """Three synthetic usage rows showing both a duplicate source and a chain."""

    base_id = resource_id(tenant, "usage", "base")
    duplicate_id = resource_id(tenant, "usage", "duplicate")
    chain_id = resource_id(tenant, "usage", "chain")
    rows = (
        (base_id, f"{SYNTHETIC}model", "base-event", None, 3, False),
        (duplicate_id, f"{SYNTHETIC}model", "duplicate-event", None, 3, False),
        (chain_id, f"{SYNTHETIC}correction", "chain-event", base_id, 2, True),
    )
    for identifier, source, source_event_id, supersedes_id, tokens, estimate in rows:
        existing = await one(
            conn, "SELECT id FROM runtime_usage_ledger WHERE id=:id", id=identifier
        )
        if existing:
            continue
        await conn.execute(
            text("""INSERT INTO runtime_usage_ledger(
                        id,run_id,tenant_id,lease_epoch,source,source_event_id,
                        usage_schema_version,usage,cost,is_estimate,supersedes_id,
                        created_at,updated_at)
                    VALUES(:id,:r,:t,0,:src,:ev,'v1',CAST(:usage AS jsonb),
                        :cost,:est,:sup,:ca,:ua)
                    ON CONFLICT DO NOTHING"""),
            {
                "id": identifier,
                "r": run_id,
                "t": tenant,
                "src": source,
                "ev": source_event_id,
                "usage": json.dumps(
                    {"input_tokens": tokens * 10, "output_tokens": tokens}, sort_keys=True
                ),
                "cost": 0.01,
                "est": estimate,
                "sup": supersedes_id,
                "ca": ts(2),
                "ua": ts(2),
            },
        )
        counts["usage_rows"] += 1


async def _ensure_parser(conn: Any, tenant: str, run_id: str, counts: dict[str, int]) -> None:
    """Two classified synthetic parser diagnostics (counts only, no samples)."""

    specs = (
        ("malformed", f"{SYNTHETIC}malformed_sample", 2),
        ("unknown_schema", f"{SYNTHETIC}unknown_schema_sample", 1),
    )
    for index, (category, reason_code, count) in enumerate(specs, start=1):
        identifier = resource_id(tenant, "parser", f"diagnostic-{index}")
        existing = await one(
            conn, "SELECT id FROM execution_parser_diagnostics WHERE id=:id", id=identifier
        )
        if existing:
            continue
        await conn.execute(
            text("""INSERT INTO execution_parser_diagnostics(
                        id,tenant_id,run_id,category,reason_code,count,bucket_start)
                    VALUES(:id,:t,:r,:cat,:reason,:count,:bucket)
                    ON CONFLICT DO NOTHING"""),
            {
                "id": identifier,
                "t": tenant,
                "r": run_id,
                "cat": category,
                "reason": reason_code,
                "count": count,
                "bucket": ts(2),
            },
        )
        counts["parser_diagnostics"] += 1


async def _ensure_credential(
    repository: Any, tenant: str, engine: Any, counts: dict[str, int]
) -> dict[str, Any]:
    """Create then revoke a synthetic credential; add stable governance audits.

    The credential ref is random (repository API), so idempotency is keyed on
    the stable localized display name. If the vault key is unavailable the
    credential row is skipped, but the revoked audit rows still use a
    deterministic credential_ref (the table has no FK on that column).
    """

    fallback_ref = resource_id(tenant, "credential-ref", "governance-revoked")
    if repository is None:
        return {"status": "unavailable", "reason": "repository_unavailable"}

    known_names = credential_names()
    rows = await repository.list(tenant_id=tenant)
    record = next(
        (row for row in rows if row.public_metadata().get("name") in known_names), None
    )
    if record is None:
        try:
            record = await repository.create(
                tenant_id=tenant,
                name=credential_name(),
                credential_type="token",
                secret=CANARY_SECRET,
                allowed_engines=(ENGINE_ID,),
                allowed_workspaces=(resource_scope_values()["workspace_id"],),
                actor=ACTOR,
            )
        except ExecutionCredentialKeyError:
            record = None
        else:
            counts["credentials"] += 1

    if record is not None:
        credential_ref = str(record.credential_ref)
        if record.public_metadata().get("status") == "active":
            await repository.revoke(
                credential_ref=record.credential_ref, tenant_id=tenant, actor=ACTOR
            )
    else:
        # Vault key unavailable: no credential row, but a stable ref for audits.
        credential_ref = fallback_ref

    # Explicit governance audit rows with prefixed actor/reason codes. Ids are
    # deterministic and inserted with ON CONFLICT DO NOTHING to preserve edits.
    async with engine.begin() as conn:
        for key, reason in (
            ("revoked", f"{SYNTHETIC}credential_revoked_sample"),
            ("grant_denied", f"{SYNTHETIC}grant_denied_sample"),
        ):
            identifier = resource_id(tenant, "credential-audit", key)
            existing = await one(
                conn,
                "SELECT id FROM execution_credential_audit WHERE id=:id",
                id=identifier,
            )
            if existing:
                continue
            await conn.execute(
                text("""INSERT INTO execution_credential_audit(
                            id,tenant_id,credential_ref,action,outcome,reason_code,actor,created_at)
                        VALUES(:id,:t,:ref,:action,'success',:reason,:actor,:ca)
                        ON CONFLICT DO NOTHING"""),
                {
                    "id": identifier,
                    "t": tenant,
                    "ref": credential_ref,
                    "action": key,
                    "reason": reason,
                    "actor": ACTOR,
                    "ca": ts(2),
                },
            )
            counts["credential_audits"] += 1
    return {
        "status": "credential_revoked" if record is not None else "audit_only",
        "credential_ref": credential_ref,
        "note": "fallback audit rows use a deterministic ref; no credential row without the vault key",
    }


async def seed(
    groups: Any,
    tenant: str,
    credential_repository: Any = None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create or preserve the opt-in synthetic governance demo dataset."""

    if settings is not None:
        set_locale(settings)
    created = new_counts()

    async with groups.runtime.engine.connect() as lock:
        await lock.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        try:
            async with groups.runtime.engine.begin() as conn:
                conversation_id = await _ensure_conversation(conn, tenant, created)
                signals_run = await _ensure_run(
                    conn,
                    tenant,
                    conversation_id,
                    RUN_SIGNALS,
                    status="completed",
                    cancel_requested=False,
                    cancel_confirmed=False,
                    cleanup_status="completed",
                    counts=created,
                )
                await _ensure_run(
                    conn,
                    tenant,
                    conversation_id,
                    RUN_CANCEL,
                    status="cancelled",
                    cancel_requested=True,
                    cancel_confirmed=False,
                    cleanup_status="not_started",
                    counts=created,
                )
                await _ensure_events(conn, signals_run, created)
                await _ensure_fencing(conn, tenant, signals_run, created)
                await _ensure_replay_gaps(conn, tenant, signals_run, created)
                await _ensure_usage(conn, tenant, signals_run, created)
                await _ensure_parser(conn, tenant, signals_run, created)
                # The unconfirmed-cancel run is referenced only through its
                # stored cancel_requested_at / cancel_confirmed_at columns; the
                # cleanup endpoint derives the category from them.
            credential = await _ensure_credential(
                credential_repository, tenant, groups.runtime.engine, created
            )
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})

    return {
        "batch": BATCH,
        "created": created,
        "runs": {"signals": RUN_SIGNALS, "unconfirmed_cancel": RUN_CANCEL},
        "credential": credential,
        "note": (
            "Synthetic governance demonstration data only. Every free-form value is "
            f"prefixed with '{SYNTHETIC}'. No real secret, grant, live process or "
            "acceptance evidence is seeded."
        ),
    }


async def main() -> None:
    """Run the seed with the standard application settings."""

    settings = Settings()
    set_locale(settings)
    async with runtime_services(settings) as services:
        report = await seed(
            services.groups,
            settings.tenant_id,
            services.execution_credentials,
            settings=settings,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
