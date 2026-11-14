"""Application-scoped customer sessions (B1).

The preview endpoint answers through a released snapshot, but it writes no
conversation anywhere: a session opened here is the first entry point where a
real customer turn is persisted under an application. The channel path already
proved the shape — resolve the release, open a Runtime conversation pinned to
it, call ``CustomerService.send`` with the resolved context, then mirror the
customer message and the turn into the business ledger. This module reuses that
shape without channels: the session is keyed by the application and an optional
external conversation id, and completion is written back by the same runtime
hooks every other path uses.

Lock ordering follows the channel rule: Runtime first, business ledger second.
``CustomerService.send`` locks the Runtime conversation; the ledger helpers
below lock the business conversation. The idempotency probe is deliberately a
plain (non-locking) read so it cannot invert that order.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

from agent_platform.business_capabilities.customer_service.service_apps.business_conversations import (
    BusinessConversationService,
)
from agent_platform.business_capabilities.conversation.service import ConversationService
from agent_platform.business_capabilities.customer_service.service import CustomerService
from agent_platform.business_capabilities.customer_service.service_apps.runtime import (
    ApplicationRuntimeContext,
    ApplicationRuntimeResolver,
)
from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    one,
    required,
    transaction,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

MAX_TEXT_LENGTH = 4000


def _session_digest(application_key: str, external_conversation_id: str) -> str:
    """Stable 32-char session hash, matching the channel external-id rule."""

    digest = hashlib.sha256(f"{application_key}:{external_conversation_id}".encode()).hexdigest()
    return digest[:32]


def _ledger_external_id(application_key: str, runtime_external_id: str) -> str:
    """Deterministic ledger external id, derived from the Runtime external id.

    Both ``open_session`` and ``send_message`` must land on the same business
    conversation for one session. Deriving the value from the Runtime
    conversation's own external id keeps that guarantee without a lock-order
    violating lookup: neither call site needs to read the ledger to compute it.
    """

    return f"app:{application_key}:{_session_digest(application_key, runtime_external_id)}"


class ApplicationSessionService:
    """Open customer sessions on a published application release and run turns."""

    def __init__(
        self,
        engine: object,
        *,
        conversations: ConversationService,
        customer: CustomerService,
        application_runtime: ApplicationRuntimeResolver,
    ) -> None:
        self.engine = engine
        self.conversations = conversations
        self.customer = customer
        self.application_runtime = application_runtime

    async def _application(
        self,
        connection: object,
        tenant: str,
        key: str,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        scope_sql, scope_params = scope_predicate(scope, alias="a")
        row = await one(
            connection,
            f"""
            SELECT a.id,a.application_key,a.name,a.published_version
            FROM service_applications a
            WHERE a.tenant_id=:tenant
              AND {scope_sql}
              AND a.application_key=:key
              AND NOT a.archived
            """,
            tenant=tenant,
            key=key,
            **scope_params,
        )
        application = required(row, "service_application_not_found")
        if application.get("published_version") is None:
            raise DomainError("service_application_not_published", 409)
        return application

    async def _runtime_conversation(
        self,
        connection: object,
        tenant: str,
        scope: BusinessScope,
        conversation_id: UUID | str,
    ) -> dict[str, Any]:
        scope_sql, scope_params = scope_predicate(scope, alias="rc")
        try:
            selected = UUID(str(conversation_id))
        except (TypeError, ValueError, AttributeError):
            raise DomainError(
                "service_application_session_not_found",
                404,
            ) from None
        row = await one(
            connection,
            f"""
            SELECT rc.*
            FROM runtime_conversations rc
            WHERE rc.id=:conversation_id
              AND rc.tenant_id=:tenant
              AND {scope_sql}
            """,
            conversation_id=selected,
            tenant=tenant,
            **scope_params,
        )
        return required(row, "service_application_session_not_found")

    async def open_session(
        self,
        tenant: str,
        key: str,
        *,
        actor: str,
        scope: BusinessScope | None = None,
        external_conversation_id: str | None = None,
        external_user_id: str | None = None,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """Open (or re-open) a customer session pinned to the published release."""

        resolved = persisted_scope(tenant, scope)
        async with transaction(self.engine) as c:
            application = await self._application(c, tenant, key, resolved)
            version = int(application["published_version"])
            context = await self.application_runtime.resolve(
                c,
                tenant,
                application["id"],
                version,
                scope=resolved,
            )
            if external_conversation_id:
                external = (
                    "app:"
                    + str(application["application_key"])
                    + ":"
                    + _session_digest(str(application["application_key"]), external_conversation_id)
                )
            else:
                external = (
                    "app:" + str(application["application_key"]) + ":" + uuid4().hex[:32]
                )
            conv = await one(
                c,
                """
                SELECT * FROM runtime_conversations
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND external_id=:external
                """,
                tenant=resolved.tenant_id,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                external=external,
            )
            if not conv:
                conv = await self.conversations.create(
                    tenant,
                    actor,
                    external,
                    context.agent_id,
                    c,
                    source="business",
                    scope=resolved,
                    application_id=context.application_id,
                    application_version=context.application_version,
                    agent_version=context.agent_version,
                )
            business_conversation = await self._find_ledger_conversation(
                c,
                tenant,
                resolved,
                application_id=context.application_id,
                external_conversation_id=_ledger_external_id(
                    str(application["application_key"]),
                    str(conv["external_id"]),
                ),
            )
            if business_conversation is None:
                business_conversation = (
                    await BusinessConversationService.ensure_conversation(
                        c,
                        tenant=tenant,
                        scope=resolved,
                        application_id=context.application_id,
                        agent_id=context.agent_id,
                        agent_version=context.agent_version,
                        external_conversation_id=_ledger_external_id(
                            str(application["application_key"]),
                            str(conv["external_id"]),
                        ),
                        kind="customer",
                        runtime_conversation_id=conv["id"],
                        external_user_id=external_user_id,
                        user_name=user_name,
                        created_by="application",
                        metadata={
                            "client_external_conversation_id": external_conversation_id,
                        },
                    )
                )
            return {
                "application_key": str(application["application_key"]),
                "application_version": context.application_version,
                "conversation_id": str(conv["id"]),
                "ledger_conversation_id": str(business_conversation["id"]),
                "agent_id": str(context.agent_id),
                "agent_version": context.agent_version,
            }

    async def send_message(
        self,
        tenant: str,
        key: str,
        conversation_id: UUID | str,
        content: str,
        *,
        actor: str,
        scope: BusinessScope | None = None,
        idempotency_key: str | None = None,
        external_user_id: str | None = None,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """Run one customer turn inside an application session."""

        text = str(content or "").strip()
        if not text or len(text) > MAX_TEXT_LENGTH:
            raise DomainError("service_application_session_message_invalid", 422)
        resolved = persisted_scope(tenant, scope)
        async with transaction(self.engine) as c:
            application = await self._application(c, tenant, key, resolved)
            conv = await self._runtime_conversation(c, tenant, resolved, conversation_id)
            if conv.get("application_id") is None or UUID(str(conv["application_id"])) != (
                UUID(str(application["id"]))
            ):
                raise DomainError("service_application_session_mismatch", 409)
            # A session stays on the release it was opened with; a fresh session
            # picks up whatever is published now.
            version = _positive_version(
                conv.get("application_version") or application["published_version"],
            )
            context: ApplicationRuntimeContext = await self.application_runtime.resolve(
                c,
                tenant,
                application["id"],
                version,
                conversation_id=conv["id"],
                scope=resolved,
            )

            run_id: UUID | None = None
            duplicate = False
            ledger_external = _ledger_external_id(
                str(application["application_key"]),
                str(conv["external_id"]),
            )
            if idempotency_key:
                prior = await self._turn_by_idempotency_key(
                    c,
                    tenant,
                    resolved,
                    application_id=context.application_id,
                    external_conversation_id=ledger_external,
                    idempotency_key=idempotency_key,
                )
                if prior is not None:
                    return {
                        "conversation_id": str(conv["id"]),
                        "ledger_conversation_id": str(prior["conversation_id"]),
                        "run_id": (
                            str(prior["runtime_run_id"])
                            if prior.get("runtime_run_id")
                            else None
                        ),
                        "status": str(prior.get("status") or "queued"),
                        "duplicate": True,
                    }
            result = await self.customer.send(
                tenant,
                actor,
                conv["id"],
                text,
                c,
                scope=resolved,
                application_context=context,
            )
            rejected = result.get("rejected") if isinstance(result, dict) else None
            if rejected:
                raise DomainError(str(rejected), 409)
            run = result.get("run") if isinstance(result, dict) else None
            run_id = UUID(str(run["id"])) if run and run.get("id") else None

            ledger_external = _ledger_external_id(
                str(application["application_key"]),
                str(conv["external_id"]),
            )
            # Plain lookup first: the ledger's unique index only covers
            # channel-linked rows (channel_id IS NOT NULL), so for application
            # sessions ``ensure_conversation``'s INSERT never conflicts and its
            # fallback lookup never runs — calling it blindly would create a
            # second row per message. The lookup is non-locking, so it cannot
            # invert the Runtime-first lock order.
            business_conversation = await self._find_ledger_conversation(
                c,
                tenant,
                resolved,
                application_id=context.application_id,
                external_conversation_id=ledger_external,
            )
            if business_conversation is None:
                business_conversation = (
                    await BusinessConversationService.ensure_conversation(
                        c,
                        tenant=tenant,
                        scope=resolved,
                        application_id=context.application_id,
                        agent_id=context.agent_id,
                        agent_version=context.agent_version,
                        external_conversation_id=ledger_external,
                        kind="customer",
                        runtime_conversation_id=conv["id"],
                        external_user_id=external_user_id,
                        user_name=user_name,
                        created_by="application",
                    )
                )
            ledger_key = f"app:{idempotency_key}" if idempotency_key else None
            customer_message, _created = await BusinessConversationService.append_message(
                c,
                business_conversation,
                role="customer",
                content=text,
                idempotency_key=ledger_key,
                payload={"application_version": context.application_version},
            )
            if run_id:
                turn, turn_created = await BusinessConversationService.start_turn(
                    c,
                    business_conversation,
                    customer_message_id=customer_message["id"],
                    application_version=context.application_version,
                    agent_id=context.agent_id,
                    agent_version=context.agent_version,
                    status=str(run.get("status") or "queued"),
                    runtime_conversation_id=conv["id"],
                    runtime_run_id=run_id,
                )
                # Only a freshly created turn needs linking. A concurrent
                # delivery that lost the race reuses the existing turn, which
                # already carries its own Runtime ids.
                if turn_created:
                    await BusinessConversationService.link_turn(
                        c,
                        turn,
                        runtime_conversation_id=conv["id"],
                        runtime_run_id=run_id,
                        status=str(run.get("status") or "queued"),
                    )
            return {
                "conversation_id": str(conv["id"]),
                "ledger_conversation_id": str(business_conversation["id"]),
                "run_id": str(run_id) if run_id else None,
                "status": str((run or {}).get("status") or "queued"),
                "duplicate": duplicate,
            }

    @staticmethod
    async def _find_ledger_conversation(
        connection: object,
        tenant: str,
        scope: BusinessScope,
        *,
        application_id: UUID | str,
        external_conversation_id: str,
    ) -> dict[str, Any] | None:
        scope_sql, scope_params = scope_predicate(scope, alias="bc")
        return await one(
            connection,
            f"""
            SELECT bc.*
            FROM service_application_conversations bc
            WHERE bc.tenant_id=:tenant
              AND {scope_sql}
              AND bc.application_id=CAST(:application_id AS uuid)
              AND bc.kind='customer'
              AND bc.channel_id IS NULL
              AND bc.external_conversation_id=:external_conversation_id
            ORDER BY bc.created_at,bc.id
            LIMIT 1
            """,
            tenant=tenant,
            application_id=str(application_id),
            external_conversation_id=external_conversation_id,
            **scope_params,
        )

    @staticmethod
    async def _turn_by_idempotency_key(
        connection: object,
        tenant: str,
        scope: BusinessScope,
        *,
        application_id: UUID | str,
        external_conversation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        # Plain read: locking the ledger here would invert the Runtime-first
        # lock order against CustomerService.send below. The ledger
        # conversation is located by its deterministic external id because the
        # caller only knows the Runtime conversation id, while messages and
        # turns are keyed by the ledger id.
        scope_sql, scope_params = scope_predicate(scope, alias="m")
        return await one(
            connection,
            f"""
            SELECT t.conversation_id,t.runtime_run_id,t.status
            FROM service_application_messages m
            JOIN service_application_conversations bc
              ON bc.tenant_id=m.tenant_id
             AND bc.business_id=m.business_id
             AND bc.workspace_id=m.workspace_id
             AND bc.id=m.conversation_id
            JOIN service_application_turns t
              ON t.tenant_id=m.tenant_id
             AND t.business_id=m.business_id
             AND t.workspace_id=m.workspace_id
             AND t.conversation_id=m.conversation_id
             AND t.customer_message_id=m.id
            WHERE m.tenant_id=:tenant
              AND {scope_sql}
              AND bc.application_id=CAST(:application_id AS uuid)
              AND bc.kind='customer'
              AND bc.channel_id IS NULL
              AND bc.external_conversation_id=:external_conversation_id
              AND m.idempotency_key=:idempotency_key
            ORDER BY t.created_at DESC,t.id DESC
            LIMIT 1
            """,
            tenant=tenant,
            application_id=str(application_id),
            external_conversation_id=external_conversation_id,
            idempotency_key=f"app:{idempotency_key}",
            **scope_params,
        )


def _positive_version(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise DomainError("service_application_version_invalid", 422) from None
    if parsed < 1:
        raise DomainError("service_application_version_invalid", 422)
    return parsed


__all__ = ["ApplicationSessionService", "MAX_TEXT_LENGTH"]
