"""Application credentials, authorization and isolated enterprise conversations."""

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    audit,
    execute,
    many,
    one,
    required,
)
from agent_platform.extension_contracts import BusinessScope


class ApplicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    agent_ids: list[UUID] = Field(default_factory=list, max_length=100)
    agent_versions: dict[UUID, int] = Field(default_factory=dict, max_length=100)
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=100)
    rpm: int = Field(default=120, ge=1, le=10000)
    max_concurrency: int = Field(default=5, ge=1, le=100)
    # Delivery subject (new). Mutually exclusive with ``agent_ids``: an
    # application either delivers one Service Application or (legacy) grants a
    # list of agents. ``service_application_version`` pins the release; omitted
    # means "follow the current published version".
    service_application_id: UUID | None = None
    service_application_version: int | None = Field(default=None, ge=1)


class ApplicationUpdate(ApplicationInput):
    revision: int = Field(ge=1)


@dataclass(frozen=True)
class AppIdentity:
    app_id: UUID
    key_id: UUID
    tenant: str
    external_user_id: str | None = None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def session_identity(identity, user):
    """Memory identity for an open-platform conversation (FR-1, P2-UT-04).

    Application API keys scope the customer to the app; enterprise-embedded
    sessions already carry the ``enterprise:{user_id}`` convention in their
    external user id, and keep it verbatim as the key.
    """
    if identity.external_user_id:
        return {"source": "enterprise", "external_key": user}
    return {"source": "open_platform", "external_key": f"{identity.app_id}:{user}"}


class OpenPlatform:
    def __init__(self, platform):
        self.p = platform
        self.engine = platform.engine
        from .knowledge import KnowledgeSync
        from .webhooks import Webhooks

        self.knowledge = KnowledgeSync(self)
        self.webhooks = Webhooks(self)
        from .enterprise import Enterprise

        self.enterprise = Enterprise(self)

    async def application(self, c, tenant, app_id, lock=False):
        return required(
            await one(
                c,
                "SELECT * FROM open_applications WHERE tenant_id=:t AND id=:id"
                + (" FOR UPDATE" if lock else ""),
                t=tenant,
                id=app_id,
            ),
            "application_not_found",
        )

    async def save(self, tenant, actor, body, app_id=None):
        async with self.engine.begin() as c:
            # Names are the human handle across keys, logs and the impact
            # dialogs, so they must stay unique per tenant. Archived rows still
            # count: they can be restored, and purging releases the name.
            if app_id:
                old = await self.application(c, tenant, app_id, True)
                if old["archived"]:
                    raise DomainError("application_archived", 409)
                if old["revision"] != body.revision:
                    raise DomainError("application_revision_conflict", 409)
                if body.name != old["name"] and await one(
                    c,
                    "SELECT id FROM open_applications WHERE tenant_id=:t AND name=:n AND id<>:id",
                    t=tenant,
                    n=body.name,
                    id=app_id,
                ):
                    raise DomainError("application_name_taken", 409)
            elif await one(
                c,
                "SELECT id FROM open_applications WHERE tenant_id=:t AND name=:n",
                t=tenant,
                n=body.name,
            ):
                raise DomainError("application_name_taken", 409)
                if "service_application_id" not in body.model_fields_set:
                    # An update that omits the delivery subject keeps the
                    # current binding: partial writers (e.g. the integration
                    # settings form) must not silently unbind the application.
                    # Passing ``service_application_id: null`` clears it.
                    current = next(
                        (
                            row
                            for row in await self.targets(c, app_id)
                            if row["target_kind"] == "service_application"
                        ),
                        None,
                    )
                    if current:
                        body = body.model_copy(
                            update={
                                "service_application_id": current["target_id"],
                                "service_application_version": current["version_pin"],
                            }
                        )
            delivery = await self._validate_service_application(c, tenant, body)
            if delivery is not None:
                # Binding a Service Application derives the agent grant
                # automatically: the application wraps exactly one agent, and
                # the delivery target (not the agent list) drives the runtime.
                body = body.model_copy(
                    update={"agent_ids": [delivery["agent_id"]], "agent_versions": {}}
                )
            for aid in set(body.agent_ids):
                row = await one(
                    c,
                    "SELECT id FROM agents WHERE id=:id AND tenant_id=:t AND NOT archived AND published_version IS NOT NULL",
                    id=aid,
                    t=tenant,
                )
                if not row:
                    raise DomainError("agent_not_published_or_available", 422)
            for aid, version in body.agent_versions.items():
                if (
                    aid not in body.agent_ids
                    or version < 1
                    or not await one(
                        c,
                        "SELECT version FROM agent_versions WHERE agent_id=:a AND version=:v",
                        a=aid,
                        v=version,
                    )
                ):
                    raise DomainError("invalid_agent_version_pin", 422)
            for kid in set(body.knowledge_base_ids):
                if not await one(
                    c,
                    "SELECT id FROM knowledge_bases WHERE id=:id AND tenant_id=:t AND enabled",
                    id=kid,
                    t=tenant,
                ):
                    raise DomainError("knowledge_base_not_available", 422)
            values = body.model_dump(
                exclude={
                    "revision",
                    "service_application_id",
                    "service_application_version",
                }
            )
            values["agent_versions"] = json.dumps(
                {str(k): v for k, v in body.agent_versions.items()}
            )
            values["knowledge_base_ids"] = list(set(body.knowledge_base_ids))
            values["agent_ids"] = list(set(body.agent_ids))
            values.update(id=app_id or uuid4(), t=tenant)
            if app_id:
                row = await one(
                    c,
                    """UPDATE open_applications SET name=:name,description=:description,
                    enabled=:enabled,agent_ids=:agent_ids,rpm=:rpm,max_concurrency=:max_concurrency,
                    agent_versions=CAST(:agent_versions AS jsonb),knowledge_base_ids=:knowledge_base_ids,
                    revision=revision+1,updated_at=now() WHERE id=:id AND tenant_id=:t RETURNING *""",
                    **values,
                )
            else:
                row = await one(
                    c,
                    """INSERT INTO open_applications(id,tenant_id,name,description,enabled,agent_ids,rpm,max_concurrency,agent_versions,knowledge_base_ids)
                    VALUES(:id,:t,:name,:description,:enabled,:agent_ids,:rpm,:max_concurrency,CAST(:agent_versions AS jsonb),:knowledge_base_ids) RETURNING *""",
                    **values,
                )
            await self._sync_targets(c, row["id"], body)
            await audit(
                c,
                tenant,
                actor,
                "open_application.updated" if app_id else "open_application.created",
                row["id"],
            )
            return {**row, "target": await self.target(c, row)}

    async def _validate_service_application(self, c, tenant, body):
        """Validate the optional Service Application binding, or return ``None``."""

        if body.service_application_version is not None and not body.service_application_id:
            raise DomainError("service_application_required_for_version_pin", 422)
        if not body.service_application_id:
            return None
        row = await one(
            c,
            """SELECT id,application_key,name,business_id,workspace_id,published_version,
            status,archived,agent_id FROM service_applications WHERE id=:id AND tenant_id=:t""",
            id=body.service_application_id,
            t=tenant,
        )
        if (
            not row
            or row["archived"]
            or row["status"] == "offline"
            or row["published_version"] is None
        ):
            # Only a live, released application can be delivered: the open
            # platform resolves a release on every new session.
            raise DomainError("service_application_not_available", 422)
        if body.service_application_version is not None and not await one(
            c,
            """SELECT version FROM service_application_versions
            WHERE tenant_id=:t AND business_id=:b AND workspace_id=:w
              AND application_id=:a AND version=:v""",
            t=tenant,
            b=row["business_id"],
            w=row["workspace_id"],
            a=row["id"],
            v=body.service_application_version,
        ):
            raise DomainError("invalid_service_application_version_pin", 422)
        return row

    async def _sync_targets(self, c, app_id, body):
        """Rewrite the delivery-subject rows of one application.

        The table is a projection of the request, so a full rewrite is cheaper
        to reason about than a diff: switching from an agent list to a service
        application (or back) drops the other kind automatically.
        """

        await execute(c, "DELETE FROM open_application_targets WHERE app_id=:a", a=app_id)
        if not body.service_application_id:
            for agent_id in sorted(set(body.agent_ids), key=str):
                await execute(
                    c,
                    """INSERT INTO open_application_targets(app_id,target_kind,target_id,version_pin)
                    VALUES(:a,'agent',:t,:v)""",
                    a=app_id,
                    t=agent_id,
                    v=body.agent_versions.get(agent_id),
                )
        if body.service_application_id:
            await execute(
                c,
                """INSERT INTO open_application_targets(app_id,target_kind,target_id,version_pin)
                VALUES(:a,'service_application',:t,:v)""",
                a=app_id,
                t=body.service_application_id,
                v=body.service_application_version,
            )

    async def targets(self, c, app_id):
        return await many(
            c,
            """SELECT target_kind,target_id,version_pin,created_at
            FROM open_application_targets WHERE app_id=:a
            ORDER BY (target_kind='service_application') DESC,created_at,target_id""",
            a=app_id,
        )

    async def target(self, c, app):
        """Primary delivery subject, or ``None`` for an application without one.

        A Service Application target is resolved to its readable identity so
        management UIs can render ``name`` / ``key`` directly; the raw
        ``target_kind`` / ``target_id`` / ``version_pin`` stay untouched.
        """

        rows = await self.targets(c, app["id"])
        row = rows[0] if rows else None
        if row is None or row["target_kind"] != "service_application":
            return row
        subject = await one(
            c,
            """SELECT application_key,name,status,published_version
            FROM service_applications WHERE id=:id AND tenant_id=:t""",
            id=row["target_id"],
            t=app["tenant_id"],
        )
        if subject is None:
            return row
        return {
            **row,
            "key": subject["application_key"],
            "name": subject["name"],
            "status": subject["status"],
            "published_version": subject["published_version"],
            "version": row["version_pin"] or subject["published_version"],
            "pinned": row["version_pin"] is not None,
        }

    async def delivery(self, c, app):
        """Resolve the bound Service Application (release, scope) or ``None``.

        ``None`` means a legacy agent application: its sessions are pinned to one
        agent and keep running through the Runtime path. A bound but unusable
        application raises instead of silently degrading to the agent path.
        """

        row = await one(
            c,
            """SELECT target_id,version_pin FROM open_application_targets
            WHERE app_id=:a AND target_kind='service_application'""",
            a=app["id"],
        )
        if not row:
            return None
        service_application = required(
            await one(
                c,
                """SELECT id,application_key,name,business_id,workspace_id,
                published_version,status,archived
                FROM service_applications WHERE id=:id AND tenant_id=:t""",
                id=row["target_id"],
                t=app["tenant_id"],
            ),
            "service_application_not_found",
        )
        if service_application["archived"]:
            raise DomainError("service_application_unavailable", 409)
        if service_application["status"] == "offline":
            raise DomainError("service_application_offline", 409)
        if service_application["published_version"] is None:
            raise DomainError("service_application_not_published", 409)
        return {
            "id": service_application["id"],
            "key": service_application["application_key"],
            "name": service_application["name"],
            "version": int(row["version_pin"] or service_application["published_version"]),
            "pinned": row["version_pin"] is not None,
            "published_version": int(service_application["published_version"]),
            "scope": BusinessScope(
                tenant_id=app["tenant_id"],
                business_id=service_application["business_id"],
                workspace_id=service_application["workspace_id"],
            ),
        }

    async def describe(self, c, identity, app):
        """Publicly readable description of what this application delivers."""

        delivery = await self.delivery(c, app)
        if delivery is not None:
            return {
                "mode": "service_application",
                "target": {
                    "kind": "service_application",
                    "id": str(delivery["id"]),
                    "key": delivery["key"],
                    "name": delivery["name"],
                    "version": delivery["version"],
                    "pinned": delivery["pinned"],
                    "published_version": delivery["published_version"],
                },
            }
        rows = await many(
            c,
            """SELECT id,name,description,published_version FROM agents
            WHERE tenant_id=:t AND id=ANY(:ids) AND NOT archived AND published_version IS NOT NULL
            ORDER BY name,id""",
            t=identity.tenant,
            ids=app["agent_ids"],
        )
        return {
            "mode": "agent",
            "target": None,
            "agents": [
                {
                    **row,
                    "effective_version": app["agent_versions"].get(
                        str(row["id"]), row["published_version"]
                    ),
                }
                for row in rows
            ],
        }

    async def keys(self, tenant, app_id):
        async with self.engine.connect() as c:
            await self.application(c, tenant, app_id)
            return await many(
                c,
                """SELECT id,prefix,created_at,expires_at,revoked_at,
                (revoked_at IS NULL AND (expires_at IS NULL OR expires_at>now())) AS active
                FROM open_api_keys WHERE app_id=:id ORDER BY created_at DESC""",
                id=app_id,
            )

    async def issue_key(
        self, tenant, actor, app_id, expires_at=None, replace_id=None, grace_minutes=0
    ):
        if expires_at and expires_at <= datetime.now(UTC):
            raise DomainError("key_expiry_must_be_future", 422)
        secret = "opk_" + secrets.token_urlsafe(36)
        async with self.engine.begin() as c:
            app = await self.application(c, tenant, app_id, True)
            if app["archived"]:
                raise DomainError("application_archived", 409)
            if replace_id:
                required(
                    await one(
                        c,
                        """UPDATE open_api_keys SET expires_at=LEAST(COALESCE(expires_at,'infinity'::timestamptz),
                    now()+:grace*interval '1 minute') WHERE app_id=:a AND id=:id AND revoked_at IS NULL
                    AND (expires_at IS NULL OR expires_at>now()) RETURNING id""",
                        a=app_id,
                        id=replace_id,
                        grace=grace_minutes,
                    ),
                    "active_key_not_found",
                )
            count = await one(
                c,
                """SELECT count(*) AS n FROM open_api_keys WHERE app_id=:a AND revoked_at IS NULL
                AND (expires_at IS NULL OR expires_at>now())""",
                a=app_id,
            )
            if count["n"] >= 10:
                raise DomainError("active_key_limit", 409)
            row = await one(
                c,
                """INSERT INTO open_api_keys(id,app_id,token_hash,prefix,expires_at)
                VALUES(:id,:a,:hash,:prefix,:expiry) RETURNING id,prefix,created_at,expires_at""",
                id=uuid4(),
                a=app_id,
                hash=digest(secret),
                prefix=secret[:12] + "…" + secret[-4:],
                expiry=expires_at,
            )
            await audit(
                c,
                tenant,
                actor,
                "open_key.rotated" if replace_id else "open_key.created",
                row["id"],
                app_id=str(app_id),
            )
            return {**row, "key": secret}

    async def revoke(self, tenant, actor, app_id, key_id):
        async with self.engine.begin() as c:
            app = await self.application(c, tenant, app_id, True)
            if app["archived"]:
                raise DomainError("application_archived", 409)
            required(
                await one(
                    c,
                    "UPDATE open_api_keys SET revoked_at=COALESCE(revoked_at,now()) WHERE app_id=:a AND id=:id RETURNING id",
                    a=app_id,
                    id=key_id,
                )
            )
            await audit(c, tenant, actor, "open_key.revoked", key_id, app_id=str(app_id))
        return {"revoked": True}

    async def archive_impact(self, tenant, app_id):
        """Count what archiving one application would affect, for the UI.

        The numbers are the confirm-dialog contract: active API keys that will
        be revoked, the embed / hosted page switches that will stop answering,
        the request volume of the last 30 days and the bound Service
        Application count. Kept read-only so the dialog can refresh without
        side effects.
        """

        async with self.engine.connect() as c:
            app = await self.application(c, tenant, app_id)
            if app["archived"]:
                raise DomainError("application_archived", 409)
            keys = await one(
                c,
                """SELECT count(*) AS n FROM open_api_keys WHERE app_id=:a AND revoked_at IS NULL
                AND (expires_at IS NULL OR expires_at>now())""",
                a=app_id,
            )
            embed = await one(
                c,
                "SELECT enabled,hosted FROM open_embed_configs WHERE app_id=:a",
                a=app_id,
            )
            requests = await one(
                c,
                """SELECT count(*) AS n FROM open_request_logs WHERE app_id=:a
                AND created_at>now()-interval '30 days'""",
                a=app_id,
            )
            targets = await one(
                c,
                """SELECT count(*) AS n FROM open_application_targets
                WHERE app_id=:a AND target_kind='service_application'""",
                a=app_id,
            )
            return {
                "name": app["name"],
                "active_keys": int(keys["n"]),
                "embed_enabled": bool(embed["enabled"]) if embed else False,
                "hosted_enabled": bool(embed["hosted"]) if embed else False,
                "requests_30d": int(requests["n"]),
                "service_applications": int(targets["n"]),
            }

    async def archive(self, tenant, actor, app_id):
        """Soft-archive one application.

        Keys are revoked (records kept, ``revoked_at`` written) so every
        credential stops working immediately; embed / hosted / webhook rows are
        kept untouched so a restore brings the whole configuration back. There
        is no physical delete: request logs are the only audit trail of the
        open API and must survive.
        """

        async with self.engine.begin() as c:
            app = await self.application(c, tenant, app_id, True)
            if app["archived"]:
                return app
            await execute(
                c,
                "UPDATE open_api_keys SET revoked_at=COALESCE(revoked_at,now()) WHERE app_id=:a AND revoked_at IS NULL",
                a=app_id,
            )
            row = await one(
                c,
                """UPDATE open_applications SET archived=true,revision=revision+1,updated_at=now()
                WHERE id=:id AND tenant_id=:t RETURNING *""",
                id=app_id,
                t=tenant,
            )
            await audit(c, tenant, actor, "open_application.archived", app_id, app_id=str(app_id))
            return row

    async def restore(self, tenant, actor, app_id):
        async with self.engine.begin() as c:
            app = await self.application(c, tenant, app_id, True)
            if not app["archived"]:
                raise DomainError("application_not_archived", 409)
            row = await one(
                c,
                """UPDATE open_applications SET archived=false,revision=revision+1,updated_at=now()
                WHERE id=:id AND tenant_id=:t RETURNING *""",
                id=app_id,
                t=tenant,
            )
            await audit(c, tenant, actor, "open_application.restored", app_id, app_id=str(app_id))
            return row

    async def purge_impact(self, tenant, app_id):
        """Count what a permanent delete would physically remove, for the UI.

        Only archived applications may be purged. Unlike the archive preview
        these numbers are rows that will be cascade-deleted and can never be
        recovered, so the dialog shows totals (all keys, all request logs)
        rather than the "active" slices used by the archive preview.
        """

        async with self.engine.connect() as c:
            app = await self.application(c, tenant, app_id)
            if not app["archived"]:
                raise DomainError("application_not_archived", 409)
            keys = await one(
                c, "SELECT count(*) AS n FROM open_api_keys WHERE app_id=:a", a=app_id
            )
            logs = await one(
                c, "SELECT count(*) AS n FROM open_request_logs WHERE app_id=:a", a=app_id
            )
            sessions = await one(
                c, "SELECT count(*) AS n FROM open_sessions WHERE app_id=:a", a=app_id
            )
            runs = await one(
                c, "SELECT count(*) AS n FROM open_runs WHERE app_id=:a", a=app_id
            )
            webhooks = await one(
                c, "SELECT count(*) AS n FROM open_webhooks WHERE app_id=:a", a=app_id
            )
            targets = await one(
                c,
                """SELECT count(*) AS n FROM open_application_targets
                WHERE app_id=:a AND target_kind='service_application'""",
                a=app_id,
            )
            return {
                "name": app["name"],
                "keys": int(keys["n"]),
                "request_logs": int(logs["n"]),
                "sessions": int(sessions["n"]),
                "runs": int(runs["n"]),
                "webhooks": int(webhooks["n"]),
                "service_applications": int(targets["n"]),
            }

    async def purge(self, tenant, actor, app_id):
        """Physically delete one archived application and all of its rows.

        Every child table (keys, sessions, runs, request logs, webhooks,
        embed / hosted config, targets, rate windows, sync state) cascades via
        foreign keys, so one statement is enough. Irreversible by design: the
        caller must already have confirmed through the archive flow, and only
        archived applications can be purged.
        """

        async with self.engine.begin() as c:
            app = await self.application(c, tenant, app_id, True)
            if not app["archived"]:
                raise DomainError("application_not_archived", 409)
            await audit(c, tenant, actor, "open_application.purged", app_id, app_id=str(app_id))
            await execute(
                c,
                "DELETE FROM open_applications WHERE id=:id AND tenant_id=:t",
                id=app_id,
                t=tenant,
            )
            return {"purged": True, "id": str(app_id), "name": app["name"]}

    async def authenticate(self, authorization, request):
        if authorization and authorization.startswith("Bearer chat_") and len(authorization) < 200:
            async with self.engine.connect() as c:
                session = await self.enterprise.validate_session(c, token=authorization[7:])
            if not session["app_id"] or not re.fullmatch(
                r"/openapi/v1/(agents|targets|conversations(?:/[0-9a-f-]+/messages)?|runs/[0-9a-f-]+(?:/(events|cancel))?)",
                request.url.path,
            ):
                raise DomainError("chat_scope_required", 403)
            identity = AppIdentity(
                session["app_id"],
                session["id"],
                session["tenant_id"],
                "enterprise:" + str(session["user_id"]),
            )
            return await self.admit(identity, request)
        if (
            not authorization
            or not authorization.startswith("Bearer opk_")
            or len(authorization) > 200
        ):
            raise DomainError("invalid_application_key", 401)
        async with self.engine.connect() as c:
            row = await one(
                c,
                """SELECT k.id,k.app_id,a.tenant_id FROM open_api_keys k JOIN open_applications a ON a.id=k.app_id
                WHERE k.token_hash=:hash AND a.tenant_id=:t AND NOT a.archived""",
                hash=digest(authorization[7:]),
                t=self.p.settings.tenant_id,
            )
        if not row:
            raise DomainError("invalid_application_key", 401)
        identity = AppIdentity(row["app_id"], row["id"], row["tenant_id"])
        return await self.admit(identity, request)

    async def admit(self, identity, request):
        request.state.open_identity = identity
        async with self.engine.begin() as c:
            app = await self.check(c, identity, lock=True)
            window = await one(
                c,
                """INSERT INTO open_rate_windows(app_id,window_start,requests)
                VALUES(:id,date_trunc('minute',now()),1) ON CONFLICT(app_id) DO UPDATE SET
                window_start=EXCLUDED.window_start,requests=CASE WHEN open_rate_windows.window_start=EXCLUDED.window_start
                THEN open_rate_windows.requests+1 ELSE 1 END RETURNING requests""",
                id=identity.app_id,
            )
            exceeded = window["requests"] > app["rpm"]
        if exceeded:
            raise DomainError("application_rate_limit", 429)
        return identity

    async def check(self, c, identity, lock=False):
        app = await self.application(c, identity.tenant, identity.app_id, lock)
        if app["archived"]:
            # Archived applications answer every open-API path as if they did
            # not exist: no feature negotiation, no state leakage.
            raise DomainError("application_not_found", 404)
        if identity.external_user_id:
            session = await self.enterprise.validate_session(c, session_id=identity.key_id)
            if (
                session["app_id"] != identity.app_id
                or "enterprise:" + str(session["user_id"]) != identity.external_user_id
            ):
                raise DomainError("invalid_enterprise_session", 401)
            if not app["enabled"]:
                raise DomainError("application_disabled", 403)
            # A bound but unavailable delivery subject fails every request
            # rather than silently falling back to the agent path.
            await self.delivery(c, app)
            return app
        key = await one(
            c,
            """SELECT id FROM open_api_keys WHERE id=:id AND app_id=:a AND revoked_at IS NULL
            AND (expires_at IS NULL OR expires_at>now())""",
            id=identity.key_id,
            a=identity.app_id,
        )
        if not key:
            raise DomainError("invalid_application_key", 401)
        if not app["enabled"]:
            raise DomainError("application_disabled", 403)
        await self.delivery(c, app)
        return app

    async def grant(self, c, app, agent_id):
        if agent_id not in app["agent_ids"]:
            raise DomainError("agent_not_authorized", 403)
        if not await one(
            c,
            "SELECT id FROM agents WHERE id=:id AND tenant_id=:t AND NOT archived AND published_version IS NOT NULL",
            id=agent_id,
            t=app["tenant_id"],
        ):
            raise DomainError("agent_not_available", 409)

    async def session(self, c, identity, user, cid, app=None):
        app = app or await self.check(c, identity)
        row = required(
            await one(
                c,
                """SELECT s.*,v.external_id,v.application_id FROM open_sessions s
            JOIN runtime_conversations v ON v.id=s.conversation_id
            WHERE s.conversation_id=:id AND s.app_id=:a AND s.external_user_id=:u AND v.tenant_id=:t""",
                id=cid,
                a=identity.app_id,
                u=user,
                t=identity.tenant,
            ),
            "conversation_not_found",
        )
        if row["agent_id"] is None:
            # Application session: the grant check is the binding itself — the
            # conversation must run the application this key delivers.
            delivery = await self.delivery(c, app)
            if delivery is None or str(row.get("application_id")) != str(delivery["id"]):
                raise DomainError("conversation_not_found", 404)
            return row
        await self.grant(c, app, row["agent_id"])
        return row

    async def create_session(self, identity, user, agent_id, external_session):
        async with self.engine.begin() as c:
            app = await self.check(c, identity, lock=True)
            delivery = await self.delivery(c, app)
            old = await one(
                c,
                "SELECT conversation_id,agent_id FROM open_sessions WHERE app_id=:a AND external_user_id=:u AND external_session_id=:s",
                a=identity.app_id,
                u=user,
                s=external_session,
            )
            if delivery is not None:
                if agent_id is not None:
                    raise DomainError("agent_id_not_applicable", 422)
                if old:
                    if old["agent_id"] is not None:
                        # The binding changed after this session was opened; the
                        # caller must start a new one instead of reusing an
                        # agent-pinned conversation.
                        raise DomainError("session_target_conflict", 409)
                    return {
                        "conversation_id": old["conversation_id"],
                        "agent_id": None,
                        "application_key": delivery["key"],
                        "application_version": delivery["version"],
                    }
                opened = await self.p.service_apps.sessions.open_session(
                    identity.tenant,
                    delivery["key"],
                    actor="open_platform",
                    scope=delivery["scope"],
                    external_conversation_id=self._external_session_key(
                        identity.app_id, user, external_session
                    ),
                    external_user_id=user,
                    kind="customer",
                    source="open_platform",
                    release_version=delivery["version"],
                    metadata={
                        "source": "open_platform",
                        "open_app_id": str(identity.app_id),
                    },
                )
                await execute(
                    c,
                    """INSERT INTO open_sessions(conversation_id,app_id,external_user_id,external_session_id,agent_id)
                    VALUES(:id,:a,:u,:s,NULL)""",
                    id=UUID(opened["conversation_id"]),
                    a=identity.app_id,
                    u=user,
                    s=external_session,
                )
                return {
                    "conversation_id": UUID(opened["conversation_id"]),
                    "agent_id": None,
                    "application_key": opened["application_key"],
                    "application_version": opened["application_version"],
                }
            if agent_id is None:
                raise DomainError("agent_id_required", 422)
            await self.grant(c, app, agent_id)
            if old:
                if old["agent_id"] != agent_id:
                    raise DomainError("session_agent_conflict", 409)
                return old
            key = self._external_session_key(identity.app_id, user, external_session)
            conv = await self.p.conversations.create(
                identity.tenant,
                "app:" + str(identity.app_id),
                key,
                agent_id,
                connection=c,
                identity=session_identity(identity, user),
            )
            await execute(
                c,
                """INSERT INTO open_sessions(conversation_id,app_id,external_user_id,external_session_id,agent_id)
                VALUES(:id,:a,:u,:s,:agent)""",
                id=conv["id"],
                a=identity.app_id,
                u=user,
                s=external_session,
                agent=agent_id,
            )
            return {"conversation_id": conv["id"], "agent_id": agent_id}

    @staticmethod
    def _external_session_key(app_id, user, external_session):
        """Stable per-session id, namespaced by the open-platform application."""

        return "open:" + str(app_id) + ":" + digest(json.dumps([user, external_session]))[:48]

    async def _idempotent_run(self, c, identity, user, idempotency, payload_hash):
        old = await one(
            c,
            "SELECT * FROM open_runs WHERE app_id=:a AND external_user_id=:u AND idempotency_key=:k",
            a=identity.app_id,
            u=user,
            k=idempotency,
        )
        if not old:
            return None
        if old["payload_hash"] != payload_hash:
            raise DomainError("idempotency_conflict", 409)
        return required(
            await one(
                c,
                "SELECT * FROM runtime_runs WHERE id=:id AND tenant_id=:t",
                id=old["run_id"],
                t=identity.tenant,
            )
        )

    async def _check_concurrency(self, c, identity, app):
        count = await one(
            c,
            """SELECT count(*) AS n FROM open_runs o JOIN runtime_runs r ON r.id=o.run_id
            WHERE o.app_id=:a AND r.status IN ('queued','running')""",
            a=identity.app_id,
        )
        if count["n"] >= app["max_concurrency"]:
            raise DomainError("application_concurrency_limit", 429)

    async def submit(self, identity, user, cid, message, idempotency, request_id):
        payload_hash = digest(json.dumps([str(cid), message]))
        async with self.engine.begin() as c:
            # Same lock order as all Runtime admission paths.
            app = await self.check(c, identity, lock=True)
            session = await self.session(c, identity, user, cid, app)
            if session["agent_id"] is not None:
                return await self._submit_agent(
                    c,
                    identity,
                    user,
                    session,
                    app,
                    message,
                    idempotency,
                    payload_hash,
                    request_id,
                )
            delivery = await self.delivery(c, app)
            previous = await self._idempotent_run(c, identity, user, idempotency, payload_hash)
            if previous is not None:
                return previous
            await self._check_concurrency(c, identity, app)
        # The application path runs its own transactions (routing, admission,
        # queue, ledger) through the same entry an in-product customer session
        # uses, so skills, rules, knowledge and handoff are shared verbatim.
        # Keeping it outside this transaction avoids holding the application row
        # lock across the Runtime admission lock.
        result = await self.p.service_apps.sessions.send_message(
            identity.tenant,
            delivery["key"],
            session["conversation_id"],
            message,
            actor="open_platform",
            scope=delivery["scope"],
            idempotency_key=idempotency,
            external_user_id=user,
            kind="customer",
        )
        run_id = result.get("run_id")
        if not run_id:
            # Handoff (human queue) or a deferral produces no agent run; the
            # open-platform contract is run-centric, so say so explicitly.
            raise DomainError("service_application_turn_unavailable", 409)
        async with self.engine.begin() as c:
            await execute(
                c,
                """INSERT INTO open_runs(run_id,app_id,external_user_id,conversation_id,idempotency_key,payload_hash,request_id)
                VALUES(:id,:a,:u,:cid,:k,:hash,:request)
                ON CONFLICT (app_id,external_user_id,idempotency_key) DO NOTHING""",
                id=UUID(str(run_id)),
                a=identity.app_id,
                u=user,
                cid=cid,
                k=idempotency,
                hash=payload_hash,
                request=request_id,
            )
        return required(await self.p.repository.get(run_id, identity.tenant), "run_not_found")

    async def _submit_agent(
        self, c, identity, user, session, app, message, idempotency, payload_hash, request_id
    ):
        await execute(c, "SELECT pg_advisory_xact_lock(71432019)")
        previous = await self._idempotent_run(c, identity, user, idempotency, payload_hash)
        if previous is not None:
            return previous
        await self._check_concurrency(c, identity, app)
        snapshot = dict(self.p.snapshot)
        snapshot["agent"] = await self.p.agents.snapshot(
            identity.tenant,
            session["agent_id"],
            c,
            version=app["agent_versions"].get(str(session["agent_id"])),
        )
        settings = self.p.settings
        row = await self.p.repository.submit(
            identity.tenant,
            RunRequest(conversation_id=session["external_id"], message=message),
            snapshot,
            settings.queue_capacity,
            settings.tenant_capacity,
            settings.queue_timeout_seconds,
            connection=c,
        )
        await execute(
            c,
            """INSERT INTO open_runs(run_id,app_id,external_user_id,conversation_id,idempotency_key,payload_hash,request_id)
            VALUES(:id,:a,:u,:cid,:k,:hash,:request)""",
            id=row["id"],
            a=identity.app_id,
            u=user,
            cid=session["conversation_id"],
            k=idempotency,
            hash=payload_hash,
            request=request_id,
        )
        return row

    async def run(self, identity, user, run_id):
        async with self.engine.connect() as c:
            app = await self.check(c, identity)
            row = required(
                await one(
                    c,
                    "SELECT conversation_id FROM open_runs WHERE run_id=:id AND app_id=:a AND external_user_id=:u",
                    id=run_id,
                    a=identity.app_id,
                    u=user,
                ),
                "run_not_found",
            )
            await self.session(c, identity, user, row["conversation_id"], app)
        return required(await self.p.repository.get(run_id, identity.tenant), "run_not_found")
