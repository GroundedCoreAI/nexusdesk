"""Formal quickstart demo dataset for agent-execution-platform-v2 phases 0-6.

This seeder is part of the normal quickstart bootstrap. It creates a coherent,
persistent demo dataset that a customer can inspect in the console and API:

* phase 0 - published and draft agents plus runs in all three terminal states;
* phase 1 - stable run/event DTO shapes and secret-free audit rows;
* phase 2 - published-snapshot and legacy conversations, ordered SSE replay;
* phase 3 - published agent config plus the five run-side snapshot columns;
* phase 4 - workdir/process metadata for a failed cleanup, with no real process;
* phase 5 - safe default-off evidence only (real Codex is never simulated);
* phase 6 - credential metadata without a secret read path, published Outbox
  rows, and empty fencing/usage tables for observation.

All rows are synthetic, deterministic and locale-aware. The seeder never
enables a high-risk flag, never issues a credential grant, never stores a real
secret, and never claims to be acceptance evidence. Re-running preserves rows
created by the first run or by an operator.

Standalone verification is available with::

    python -m agent_platform.applications.seed_execution_platform
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.applications.seed_memory_common import current_audit_actor, ensure_demo_profile
from agent_platform.applications.seed_memory_i18n import T, set_locale
from agent_platform.business_capabilities.agent_config.service import AgentConfig, AgentDraft
from agent_platform.core_platform.agent_execution.capability.resolver import CapabilityResolution
from agent_platform.core_platform.agent_execution.capability.snapshots import (
    build_capability_snapshots,
)
from agent_platform.core_platform.agent_execution.contracts.capabilities import (
    CAPABILITY_ORDER,
    NO_EXECUTION_RESTRICTIONS,
    POLICY_LAYER_ORDER,
    AvailableCapabilities,
    CapabilityDecision,
    CapabilityPolicy,
    DeclaredCapabilities,
    EffectiveCapabilities,
    EffectiveCapabilityDecision,
    EngineCapabilities,
    PolicyDecisionSet,
    PolicyLayerDecision,
    PolicyLayerVersion,
    canonical_digest,
    disabled_capabilities_digest,
)
from agent_platform.core_platform.agent_execution.contracts.snapshots import serialize_snapshot
from agent_platform.core_platform.agent_execution.credentials.vault import (
    ExecutionCredentialKeyError,
)
from agent_platform.core_platform.platform_services.persistence.store import one
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    resource_scope_values,
)

BATCH = "execution-platform-demo-v1"
ACTOR = "seed-execution-platform"
LOCK_ID = 71432028
ROOT_NS = UUID("3f8b2a64-1c4a-4e2b-9b7e-7d5c6a1f0028")

PUBLISHED_CONVERSATION = "execution-platform-published"
LEGACY_CONVERSATION = "execution-platform-legacy"
COMPLETED_RUN = "execution-platform-run-completed"
CANCELLED_RUN = "execution-platform-run-cancelled"
FAILED_RUN = "execution-platform-run-failed"

CANARY_CREDENTIAL = "execution-platform-canary-credential"
CANARY_SECRET = "execution-platform-canary-not-a-real-secret"  # synthetic, never a real key

ENGINE_ID = "react"
PROTOCOL_ID = "native"
ADAPTER_VERSION = "v1"
PROBE_ID = "execution-platform-probe"
POLICY_PROVIDER_ID = "execution-platform-policy"
SNAPSHOT_MARKER = "execution-platform-snapshot-v1"
DEMO_DISABLED_CAPABILITIES = ("session_resume", "human_approval", "interactive_input")
DEMO_ENABLED_CAPABILITIES = tuple(
    name for name in CAPABILITY_ORDER if name not in DEMO_DISABLED_CAPABILITIES
)

COUNT_KEYS = (
    "connections",
    "models",
    "profiles",
    "agents",
    "conversations",
    "runs",
    "events",
    "outbox",
    "workdirs",
    "host_processes",
    "credentials",
    "audits",
)

NOW = datetime.now(UTC)


def resource_id(tenant: str, kind: str, key: str) -> str:
    """Stable tenant-scoped identity for a demo row."""

    return str(uuid5(ROOT_NS, f"agent-platform:{tenant}:{BATCH}:{kind}:{key}"))


def ts(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def new_counts() -> dict[str, int]:
    return {key: 0 for key in COUNT_KEYS}


def display_name() -> str:
    return T(
        zh="执行平台演示 Agent（已发布）",
        en="Execution Platform Demo Agent (Published)",
        zh_tw="執行平台演示 Agent（已發布）",
        hi="एक्ज़िक्यूशन प्लेटफ़ॉर्म डेमो एजेंट (प्रकाशित)",
    )


def draft_name() -> str:
    return T(
        zh="执行平台演示 Agent（草稿）",
        en="Execution Platform Demo Agent (Draft)",
        zh_tw="執行平台演示 Agent（草稿）",
        hi="एक्ज़िक्यूशन प्लेटफ़ॉर्म डेमो एजेंट (ड्राफ़्ट)",
    )


def credential_name() -> str:
    return T(
        zh="[演示] 执行平台合成凭据（无真实密钥）",
        en="[Demo] Execution Platform synthetic credential (no real secret)",
        zh_tw="[演示] 執行平台合成憑證（無真實金鑰）",
        hi="[डेमो] सिंथेटिक निष्पादन क्रेडेंशियल (कोई वास्तविक कुंजी नहीं)",
    )


def credential_names() -> tuple[str, ...]:
    """All localized display names, so changing seed_locale cannot duplicate the row."""

    return (
        "[演示] 执行平台合成凭据（无真实密钥）",
        "[Demo] Execution Platform synthetic credential (no real secret)",
        "[演示] 執行平台合成憑證（無真實金鑰）",
        "[डेमो] सिंथेटिक निष्पादन क्रेडेंशियल (कोई वास्तविक कुंजी नहीं)",
    )


def _bind_profile(config: AgentConfig, profile: dict[str, Any], version: int) -> AgentConfig:
    """Bind both config aliases at construction time (D-1 safe pattern)."""

    if config.react is None:
        config.model_profile_id = profile["id"]
        config.model_profile_version = version
        return config
    bound = config.model_dump(mode="json")
    bound["react"]["model_profile_id"] = str(profile["id"])
    bound["react"]["model_profile_version"] = version
    bound["model_profile_id"] = str(profile["id"])
    bound["model_profile_version"] = version
    return AgentConfig.model_validate(bound)


async def _ensure_agents(
    platform: Any, tenant: str, profile: dict[str, Any], version: int, counts: dict[str, int]
) -> tuple[dict[str, Any], dict[str, Any]]:
    existing = {row["name"]: row for row in await platform.business.agents.list(tenant)}

    published_name = display_name()
    published = existing.get(published_name)
    created_published = False
    if published is None:
        config = AgentConfig(
            system_prompt=T(
                zh="你是一个用于产品演示的执行平台 Agent。只使用演示数据，不请求凭据，也不执行真实交易。",
                en="You are an agent execution platform demo agent. Use only demo data; never request credentials or perform real transactions.",
                zh_tw="你是用於產品演示的執行平台 Agent。只使用演示資料，不要求憑證，也不執行真實交易。",
                hi="आप एक उत्पाद डेमो के लिए निष्पादन-प्लेटफ़ॉर्म एजेंट हैं। केवल डेमो डेटा का उपयोग करें; क्रेडेंशियल न मांगें और वास्तविक लेनदेन न करें।",
            ),
            disabled_capabilities=DEMO_DISABLED_CAPABILITIES,
            reply_language="auto",
        )
        published = await platform.business.agents.create(
            tenant,
            ACTOR,
            AgentDraft(
                name=published_name,
                description=T(
                    zh="覆盖配置快照、SSE 回放与终态语义的已发布演示 Agent。",
                    en="Published demo agent covering config snapshots, SSE replay and terminal semantics.",
                    zh_tw="涵蓋設定快照、SSE 回放與終態語意的已發布演示 Agent。",
                    hi="कॉन्फ़िग स्नैपशॉट, SSE रीप्ले और टर्मिनल सेमेंटिक्स को दर्शाने वाला प्रकाशित डेमो एजेंट।",
                ),
                config=_bind_profile(config, profile, version),
                is_example=True,
            ),
        )
        created_published = True
    if published.get("published_version") is None:
        await platform.business.agents.publish(
            tenant, ACTOR, published["id"], published["draft_revision"]
        )
        published = next(
            row
            for row in await platform.business.agents.list(tenant)
            if row["id"] == published["id"]
        )
        counts["agents"] += int(created_published)

    draft = existing.get(draft_name())
    if draft is None:
        draft = await platform.business.agents.create(
            tenant,
            ACTOR,
            AgentDraft(
                name=draft_name(),
                description=T(
                    zh="未发布草稿，用于演示编辑、校验与发布后生成快照。",
                    en="Unpublished draft for demonstrating edit, validation and publish-time snapshotting.",
                    zh_tw="未發布草稿，用於示範編輯、驗證與發布後產生快照。",
                    hi="अप्रकाशित ड्राफ़्ट, संपादन, सत्यापन और प्रकाशन-समय स्नैपशॉट दिखाने के लिए।",
                ),
                config=AgentConfig(
                    system_prompt=T(
                        zh="这是一个未发布的演示草稿，请勿在生产环境中发布。",
                        en="This is an unpublished demo draft; do not publish it in production.",
                        zh_tw="這是一個未發布的演示草稿，請勿在生產環境中發布。",
                        hi="यह एक अप्रकाशित डेमो ड्राफ़्ट है; इसे उत्पादन में प्रकाशित न करें।",
                    )
                ),
                is_example=True,
            ),
        )
        counts["agents"] += 1
    return published, draft


async def _ensure_conversation(
    conn: Any,
    tenant: str,
    external_id: str,
    agent_id: str | None,
    summary: str,
    counts: dict[str, int],
) -> tuple[str, bool]:
    identifier = resource_id(tenant, "conversation", external_id)
    existing = await one(
        conn,
        "SELECT id FROM runtime_conversations WHERE tenant_id=:t AND external_id=:e",
        t=tenant,
        e=external_id,
    )
    if existing:
        return str(existing["id"]), False
    history = [
        {
            "role": "user",
            "content": T(
                zh="请演示这条执行链路。",
                en="Please demonstrate this execution path.",
                zh_tw="請示範這條執行鏈路。",
                hi="कृपया यह निष्पादन पथ दिखाएँ।",
            ),
        },
        {
            "role": "assistant",
            "content": T(
                zh="[演示] 已收到请求。下面展示可回放的执行事件。",
                en="[Demo] Request received. Replayable execution events are shown below.",
                zh_tw="[演示] 已收到請求。以下展示可回放的執行事件。",
                hi="[डेमो] अनुरोध प्राप्त हुआ। नीचे दोबारा देखने योग्य निष्पादन इवेंट दिए गए हैं।",
            ),
        },
    ]
    await conn.execute(
        text("""INSERT INTO runtime_conversations(
                id,tenant_id,business_id,workspace_id,external_id,history,mode,agent_id,source,summary)
            VALUES(:id,:t,:business_id,:workspace_id,:e,CAST(:h AS jsonb),'bot',:a,'business',:s)
            ON CONFLICT DO NOTHING"""),
        {
            "id": identifier,
            "t": tenant,
            **resource_scope_values(),
            "e": external_id,
            "h": json.dumps(history, ensure_ascii=False),
            "a": agent_id,
            "s": summary,
        },
    )
    counts["conversations"] += 1
    return identifier, True


def _capability_snapshots(run_id: str, tenant: str) -> dict[str, str]:
    """Build valid phase-3 snapshots from the production builders."""

    declared_capabilities = EngineCapabilities(
        **{name: name in DEMO_ENABLED_CAPABILITIES for name in CAPABILITY_ORDER}
    )
    declaration_digest = canonical_digest(declared_capabilities)
    declared = DeclaredCapabilities(
        engine_id=ENGINE_ID,
        protocol_id=PROTOCOL_ID,
        adapter_version=ADAPTER_VERSION,
        declaration_schema_version=ADAPTER_VERSION,
        declaration_digest=declaration_digest,
        capabilities=declared_capabilities,
    )
    availability = AvailableCapabilities(
        engine_id=ENGINE_ID,
        protocol_id=PROTOCOL_ID,
        adapter_version=ADAPTER_VERSION,
        probe_id=PROBE_ID,
        probe_version=ADAPTER_VERSION,
        observed_at=NOW,
        declaration_digest=declaration_digest,
        deployment_digest=declaration_digest,
        items=tuple(
            CapabilityDecision(
                name=name,
                available=name in DEMO_ENABLED_CAPABILITIES,
                reason_code="allowed" if name in DEMO_ENABLED_CAPABILITIES else "not_declared",
            )
            for name in CAPABILITY_ORDER
        ),
    )
    policy = PolicyDecisionSet(
        policy_provider_id=POLICY_PROVIDER_ID,
        policy_version=ADAPTER_VERSION,
        policy_revision=1,
        resolved_at=NOW,
        layer_versions=tuple(
            PolicyLayerVersion(layer=layer, version=ADAPTER_VERSION, revision=1)
            for layer in POLICY_LAYER_ORDER
        ),
        decisions=tuple(
            CapabilityPolicy(
                name=name,
                layers=tuple(
                    PolicyLayerDecision(
                        layer=layer,
                        allowed=name in DEMO_ENABLED_CAPABILITIES,
                        source=POLICY_PROVIDER_ID,
                        reason_code=(
                            "allowed" if name in DEMO_ENABLED_CAPABILITIES else "not_declared"
                        ),
                    )
                    for layer in POLICY_LAYER_ORDER
                ),
            )
            for name in CAPABILITY_ORDER
        ),
    )
    effective = EffectiveCapabilities(
        engine_id=ENGINE_ID,
        protocol_id=PROTOCOL_ID,
        adapter_version=ADAPTER_VERSION,
        tenant_id=tenant,
        declaration_digest=declaration_digest,
        probe_id=PROBE_ID,
        probe_version=ADAPTER_VERSION,
        policy_provider_id=POLICY_PROVIDER_ID,
        policy_version=ADAPTER_VERSION,
        policy_revision=1,
        items=tuple(
            EffectiveCapabilityDecision(
                name=name,
                effective=name in DEMO_ENABLED_CAPABILITIES,
                reason_code="allowed" if name in DEMO_ENABLED_CAPABILITIES else "not_declared",
            )
            for name in CAPABILITY_ORDER
        ),
    )
    resolution = CapabilityResolution(
        declared=declared,
        available=availability,
        policy=policy,
        effective=effective,
        availability_status="fresh",
        policy_status="fresh",
    )
    snapshots = build_capability_snapshots(
        UUID(run_id),
        resolution,
        disabled_capabilities_digest=disabled_capabilities_digest(DEMO_DISABLED_CAPABILITIES),
        execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
    )
    return {
        "execution_config_snapshot": json.dumps(
            {
                "contract_version": "v1",
                "engine": {
                    "engine_id": ENGINE_ID,
                    "protocol_id": PROTOCOL_ID,
                    "adapter_version": ADAPTER_VERSION,
                },
                "disabled_capabilities": list(DEMO_DISABLED_CAPABILITIES),
                "snapshot_marker": SNAPSHOT_MARKER,
            },
            sort_keys=True,
        ),
        "declared_capabilities_snapshot": serialize_snapshot(snapshots.declared),
        "available_capabilities_snapshot": serialize_snapshot(snapshots.available),
        "effective_capabilities_snapshot": serialize_snapshot(snapshots.effective),
        "execution_policy_snapshot": serialize_snapshot(snapshots.policy),
    }


def _run_config(agent_id: str | None, snapshot: bool) -> str:
    config: dict[str, Any] = {
        "agent": {"id": agent_id, "tools": [], "version": 1},
        "model_name": "demo",
        "model_backend": "demo",
        "fingerprint": f"{BATCH}-fingerprint",
        "side_effect_policy": {"allow_external": False},
    }
    if snapshot:
        config["execution_config_snapshot_marker"] = SNAPSHOT_MARKER
    return json.dumps(config, ensure_ascii=False, sort_keys=True)


async def _ensure_run(
    conn: Any,
    tenant: str,
    conversation_id: str,
    run_key: str,
    status: str,
    agent_id: str | None,
    *,
    snapshot: bool,
    counts: dict[str, int],
    error_code: str | None = None,
    cancel_requested: bool = False,
    cleanup_status: str = "completed",
) -> tuple[str, bool]:
    run_id = resource_id(tenant, "run", run_key)
    existing = await one(conn, "SELECT id FROM runtime_runs WHERE id=:id", id=run_id)
    if existing:
        return run_id, False
    created = ts(2)
    started = created + timedelta(milliseconds=40)
    finished = created + timedelta(milliseconds=640)
    snapshots = _capability_snapshots(run_id, tenant) if snapshot else {}
    await conn.execute(
        text("""INSERT INTO runtime_runs(
                id,conversation_id,tenant_id,input,config,status,output,error_code,event_seq,
                cancel_requested,cancel_requested_at,cancel_confirmed_at,queue_expires_at,
                created_at,started_at,finished_at,cleanup_status,cleanup_updated_at,
                lease_epoch,side_effect_policy,
                execution_config_snapshot,declared_capabilities_snapshot,
                available_capabilities_snapshot,effective_capabilities_snapshot,
                execution_policy_snapshot)
            VALUES(:id,:c,:t,:inp,CAST(:cfg AS jsonb),:st,:out,:err,:eseq,
                :cr,:cra,:cca,:qe,:ca,:sa,:fa,:cl,:clu,0,CAST(:sep AS jsonb),
                CAST(:ecs AS jsonb),CAST(:dcs AS jsonb),CAST(:acs AS jsonb),
                CAST(:efs AS jsonb),CAST(:eps AS jsonb))
            ON CONFLICT DO NOTHING"""),
        {
            "id": run_id,
            "c": conversation_id,
            "t": tenant,
            "inp": f"[execution-demo] {run_key}",
            "cfg": _run_config(agent_id, snapshot),
            "st": status,
            "out": T(
                zh="[演示] 执行完成。",
                en="[Demo] Execution completed.",
                zh_tw="[演示] 執行完成。",
                hi="[डेमो] निष्पादन पूरा हुआ।",
            )
            if status == "completed"
            else None,
            "err": error_code,
            "eseq": 5,
            "cr": cancel_requested,
            "cra": created + timedelta(milliseconds=120) if cancel_requested else None,
            "cca": finished if status == "cancelled" else None,
            "qe": created + timedelta(minutes=2),
            "ca": created,
            "sa": started,
            "fa": finished,
            "cl": cleanup_status,
            "clu": finished,
            "sep": json.dumps({"allow_external": False}),
            "ecs": snapshots.get("execution_config_snapshot"),
            "dcs": snapshots.get("declared_capabilities_snapshot"),
            "acs": snapshots.get("available_capabilities_snapshot"),
            "efs": snapshots.get("effective_capabilities_snapshot"),
            "eps": snapshots.get("execution_policy_snapshot"),
        },
    )
    counts["runs"] += 1
    return run_id, True


async def _ensure_events(conn: Any, run_id: str, status: str) -> bool:
    existing = await one(conn, "SELECT seq FROM runtime_events WHERE run_id=:r LIMIT 1", r=run_id)
    if existing:
        return False
    terminal_type = {
        "completed": "run.completed",
        "cancelled": "run.cancelled",
        "failed": "run.failed",
    }[status]
    terminal_data: dict[str, Any] = {
        "completed": {"output": "[execution-demo] completed", "error_code": None},
        "cancelled": {"reason": "execution_demo_cancellation"},
        "failed": {"error_code": "execution_demo_failure"},
    }[status]
    events = [
        (1, "run.queued", {}),
        (2, "run.started", {}),
        (3, terminal_type, terminal_data),
    ]
    for seq, event_type, data in events:
        await conn.execute(
            text("""INSERT INTO runtime_events(run_id,seq,type,data,created_at)
                    VALUES(:r,:s,:ty,CAST(:d AS jsonb),:ca) ON CONFLICT DO NOTHING"""),
            {
                "r": run_id,
                "s": seq,
                "ty": event_type,
                "d": json.dumps(data, ensure_ascii=False),
                "ca": ts(2) + timedelta(milliseconds=seq * 10),
            },
        )
    # The 0070 trigger enqueues each event. Publishing the synthetic rows keeps
    # the Outbox demo-visible without invoking live workers.
    await conn.execute(
        text("""UPDATE runtime_event_outbox
                SET status='published', attempts=1, available_at=:at, published_at=:at
                WHERE run_id=:r"""),
        {"r": run_id, "at": ts(2) + timedelta(milliseconds=100)},
    )
    return True


async def _ensure_workdir_and_process(
    conn: Any, tenant: str, run_id: str
) -> tuple[bool, bool]:
    workdir_id = resource_id(tenant, "workdir", run_id)
    existing = await one(conn, "SELECT id FROM execution_workdirs WHERE id=:id", id=workdir_id)
    created = False
    if existing is None:
        await conn.execute(
            text("""INSERT INTO execution_workdirs(
                    id,run_id,tenant_id,business_id,workspace_id,relative_path,status,quota_bytes,
                    size_bytes,file_count,created_at,updated_at,last_error_code)
                VALUES(:id,:r,:t,:business_id,:workspace_id,:p,'cleanup_failed',:q,0,0,:ca,:ua,:err)
                ON CONFLICT DO NOTHING"""),
            {
                "id": workdir_id,
                "r": run_id,
                "t": tenant,
                **resource_scope_values(),
                "p": f"execution-demo/{run_id}",
                "q": 64 * 1024 * 1024,
                "ca": ts(2),
                "ua": ts(2),
                "err": "execution_demo_cleanup_failed_sample",
            },
        )
        created = True

    process_id = resource_id(tenant, "process", run_id)
    existing_process = await one(
        conn, "SELECT id FROM runtime_host_processes WHERE id=:id", id=process_id
    )
    process_created = False
    if existing_process is None:
        await conn.execute(
            text("""INSERT INTO runtime_host_processes(
                    id,run_id,workdir_id,tenant_id,host_id,host_instance_id,sandbox_provider,
                    status,command_digest,created_at,updated_at,last_observed_at,exit_code,
                    last_error_code,metadata)
                VALUES(:id,:r,:w,:t,:host,:instance,'local-demo',
                    'exited',:digest,:ca,:ua,:oa,0,:err,CAST(:m AS jsonb))
                ON CONFLICT DO NOTHING"""),
            {
                "id": process_id,
                "r": run_id,
                "w": workdir_id,
                "t": tenant,
                "host": "execution-platform-host",
                "instance": "execution-platform-instance",
                "digest": "execution-platform-command-digest",
                "ca": ts(2),
                "ua": ts(2),
                "oa": ts(2),
                "err": "execution_demo_sample",
                "m": json.dumps(
                    {
                        "purpose": "execution-platform-demo",
                        "real_process": False,
                        "synthetic": True,
                    }
                ),
            },
        )
        process_created = True
    return created, process_created


async def _ensure_credential(
    repository: Any, tenant: str, counts: dict[str, int]
) -> dict[str, Any]:
    if repository is None:
        return {"status": "unavailable", "reason": "repository_unavailable"}
    rows = await repository.list(tenant_id=tenant)
    known_names = credential_names()
    existing = next(
        (row for row in rows if row.public_metadata().get("name") in known_names), None
    )
    if existing is not None:
        return {"status": "preserved", "credential_ref": str(existing.credential_ref)}
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
        return {"status": "unavailable", "reason": "execution_credential_key_unavailable"}
    counts["credentials"] += 1
    return {"status": "created", "credential_ref": str(record.credential_ref)}


async def _ensure_audit(
    conn: Any, tenant: str, actor: str, resource_id_value: str, counts: dict[str, int]
) -> bool:
    existing = await one(
        conn,
        """SELECT id FROM audit_records
           WHERE tenant_id=:t AND actor=:a AND action='execution_platform_seed' AND resource=:r
           LIMIT 1""",
        t=tenant,
        a=actor,
        r=resource_id_value,
    )
    if existing:
        return False
    await conn.execute(
        text("""INSERT INTO audit_records(tenant_id,actor,action,resource,details,created_at)
                VALUES(:t,:a,'execution_platform_seed',:r,CAST(:d AS jsonb),:ca)"""),
        {
            "t": tenant,
            "a": actor,
            "r": resource_id_value,
            "d": json.dumps(
                {
                    "note": "synthetic agent execution platform demo; no secret values",
                    "batch": BATCH,
                }
            ),
            "ca": ts(2),
        },
    )
    counts["audits"] += 1
    return True


async def seed(
    platform: Any,
    tenant: str,
    credential_repository: Any = None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create or preserve the formal execution platform demo dataset."""

    if settings is not None:
        set_locale(settings)
    created = new_counts()
    preserved = new_counts()

    async with platform.runtime.engine.connect() as lock:
        await lock.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        try:
            gateway_names = (
                (
                    "connections",
                    T(
                        zh="示例模拟连接",
                        en="Sample Demo Connection",
                        zh_tw="示例模擬連接",
                        hi="सैंपल डेमो कनेक्शन",
                    ),
                ),
                (
                    "models",
                    T(
                        zh="示例模拟 Chat",
                        en="Sample Demo Chat",
                        zh_tw="示例模擬 Chat",
                        hi="सैंपल डेमो Chat",
                    ),
                ),
                (
                    "profiles",
                    T(
                        zh="示例客服模型方案",
                        en="Sample Support Model Profile",
                        zh_tw="示例客服模型方案",
                        hi="सैंपल सपोर्ट मॉडल प्रोफ़ाइल",
                    ),
                ),
            )
            gateway_existed: dict[str, bool] = {}
            for kind, name in gateway_names:
                rows = await platform.runtime.gateway.catalog.list(tenant, kind)
                gateway_existed[kind] = any(row["name"] == name for row in rows)
            profile, version = await ensure_demo_profile(platform, tenant, ACTOR)
            for kind, existed in gateway_existed.items():
                created[kind] = int(not existed)
                preserved[kind] = int(existed)
            published, draft = await _ensure_agents(
                platform, tenant, profile, version, created
            )
            # Agent creation already counted the published agent; mirror the
            # preserved counter for a deterministic created/preserved report.
            preserved["agents"] = 2 - created["agents"]

            actor = await current_audit_actor(platform, tenant)
            async with platform.runtime.engine.begin() as conn:
                published_conv, _ = await _ensure_conversation(
                    conn,
                    tenant,
                    PUBLISHED_CONVERSATION,
                    str(published["id"]),
                    T(
                        zh="执行平台演示：带快照的发布路径",
                        en="Agent execution platform demo: published path with config snapshot",
                        zh_tw="執行平台演示：帶快照的發布路徑",
                        hi="निष्पादन डेमो: कॉन्फ़िग स्नैपशॉट के साथ प्रकाशित पथ",
                    ),
                    created,
                )
                legacy_conv, _ = await _ensure_conversation(
                    conn,
                    tenant,
                    LEGACY_CONVERSATION,
                    None,
                    T(
                        zh="执行平台演示：无 Agent 的兼容路径",
                        en="Agent execution platform demo: legacy path without an agent",
                        zh_tw="執行平台演示：無 Agent 的相容路徑",
                        hi="निष्पादन डेमो: एजेंट के बिना लीगेसी पथ",
                    ),
                    created,
                )
                preserved["conversations"] = 2 - created["conversations"]

                completed, _ = await _ensure_run(
                    conn,
                    tenant,
                    published_conv,
                    COMPLETED_RUN,
                    "completed",
                    str(published["id"]),
                    snapshot=True,
                    counts=created,
                )
                cancelled, _ = await _ensure_run(
                    conn,
                    tenant,
                    legacy_conv,
                    CANCELLED_RUN,
                    "cancelled",
                    None,
                    snapshot=False,
                    counts=created,
                    cancel_requested=True,
                )
                failed, _ = await _ensure_run(
                    conn,
                    tenant,
                    legacy_conv,
                    FAILED_RUN,
                    "failed",
                    None,
                    snapshot=False,
                    counts=created,
                    error_code="execution_demo_failure",
                    cleanup_status="failed",
                )
                for run_id, status in (
                    (completed, "completed"),
                    (cancelled, "cancelled"),
                    (failed, "failed"),
                ):
                    if await _ensure_events(conn, run_id, status):
                        created["events"] += 3
                        created["outbox"] += 3
                    else:
                        preserved["events"] += 3
                        preserved["outbox"] += 3
                preserved["runs"] = 3 - created["runs"]

                workdir_created, process_created = await _ensure_workdir_and_process(
                    conn, tenant, failed
                )
                created["workdirs"] += int(workdir_created)
                preserved["workdirs"] += int(not workdir_created)
                created["host_processes"] += int(process_created)
                preserved["host_processes"] += int(not process_created)
                await _ensure_audit(conn, tenant, actor, completed, created)
                preserved["audits"] = 1 - created["audits"]

            credential = await _ensure_credential(credential_repository, tenant, created)
            if credential["status"] == "preserved":
                preserved["credentials"] += 1
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})

    return {
        "batch": BATCH,
        "created": created,
        "preserved": preserved,
        "published_agent_id": str(published["id"]),
        "published_agent_version": published.get("published_version"),
        "draft_agent_id": str(draft["id"]),
        "conversations": {"published": PUBLISHED_CONVERSATION, "legacy": LEGACY_CONVERSATION},
        "runs": {
            "completed": COMPLETED_RUN,
            "cancelled": CANCELLED_RUN,
            "failed": FAILED_RUN,
        },
        "credential": credential,
        "note": (
            "Synthetic customer-demo data only. High-risk flags remain off; no grant, "
            "usage, fencing denial or real credential is seeded. Not acceptance evidence."
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
