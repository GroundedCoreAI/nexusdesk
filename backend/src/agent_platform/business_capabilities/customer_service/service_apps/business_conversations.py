"""Business conversation ledger for service applications.

The Agent Runtime owns context, tools, events, and diagnostics. This module
owns the customer-visible business conversation, its ordered messages, and the
turn that links one customer message to a Runtime run.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    one,
    required,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

CONVERSATION_KINDS = frozenset({"customer", "debug"})
CONVERSATION_STATUSES = frozenset({"open", "waiting", "human", "closed"})
MESSAGE_ROLES = frozenset({"customer", "assistant", "human", "system"})
TURN_STATUSES = frozenset({"queued", "running", "completed", "failed", "cancelled"})
TERMINAL_TURN_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _uuid_or_none(value: UUID | str | None, code: str) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise DomainError(code, 422) from None


def _scope_params(conversation: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenant": conversation["tenant_id"],
        "business": conversation["business_id"],
        "workspace": conversation["workspace_id"],
        "conversation_id": conversation["id"],
    }


def _validate_choice(value: str, choices: frozenset[str], code: str) -> str:
    if value not in choices:
        raise DomainError(code, 422)
    return value


class BusinessConversationService:
    """Reusable, transaction-aware business ledger operations."""

    @staticmethod
    async def ensure_conversation(
        connection: object,
        *,
        tenant: str | None = None,
        tenant_id: str | None = None,
        scope: BusinessScope | None,
        application_id: UUID | str,
        kind: str = "customer",
        channel_id: UUID | str | None = None,
        external_conversation_id: str | None = None,
        customer_id: UUID | str | None = None,
        external_user_id: str | None = None,
        user_name: str | None = None,
        assigned_to: str | None = None,
        agent_id: UUID | str | None = None,
        agent_version: int | None = None,
        runtime_conversation_id: UUID | str | None = None,
        created_by: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or load the business conversation under the caller's lock."""

        _validate_choice(kind, CONVERSATION_KINDS, "service_application_kind_invalid")
        selected_tenant = tenant or tenant_id or (scope.tenant_id if scope else None)
        if not selected_tenant:
            raise DomainError("service_application_tenant_required", 422)
        resolved = persisted_scope(selected_tenant, scope)
        app_id = _uuid_or_none(application_id, "service_application_id_invalid")
        if app_id is None:
            raise DomainError("service_application_id_invalid", 422)
        selected_channel = _uuid_or_none(
            channel_id,
            "service_application_conversation_channel_id_invalid",
        )
        selected_customer = _uuid_or_none(
            customer_id,
            "service_application_conversation_customer_id_invalid",
        )
        selected_agent = _uuid_or_none(
            agent_id,
            "service_application_conversation_agent_id_invalid",
        )
        if agent_version is not None and agent_version < 1:
            raise DomainError("service_application_conversation_agent_version_invalid", 422)
        runtime_id = _uuid_or_none(
            runtime_conversation_id,
            "service_application_conversation_runtime_id_invalid",
        )
        conversation_metadata = dict(metadata or {})
        if runtime_id is not None:
            conversation_metadata["runtime_conversation_id"] = str(runtime_id)

        inserted = await one(
            connection,
            """
            INSERT INTO service_application_conversations(
                id,tenant_id,business_id,workspace_id,application_id,kind,status,
                channel_id,external_conversation_id,customer_id,external_user_id,
                user_name,assigned_to,agent_id,agent_version,created_by,metadata
            ) VALUES(
                :id,:tenant,:business,:workspace,:application_id,:kind,'open',
                :channel_id,:external_conversation_id,:customer_id,:external_user_id,
                :user_name,:assigned_to,:agent_id,:agent_version,:created_by,
                CAST(:metadata AS jsonb)
            )
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            id=uuid4(),
            tenant=resolved.tenant_id,
            business=resolved.business_id,
            workspace=resolved.workspace_id,
            application_id=app_id,
            kind=kind,
            channel_id=selected_channel,
            external_conversation_id=external_conversation_id,
            customer_id=selected_customer,
            external_user_id=external_user_id,
            user_name=user_name,
            assigned_to=assigned_to,
            agent_id=selected_agent,
            agent_version=agent_version,
            created_by=created_by,
            metadata=json.dumps(conversation_metadata, ensure_ascii=False),
        )
        if inserted is not None:
            return inserted

        existing = await one(
            connection,
            """
            SELECT *
            FROM service_application_conversations
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND application_id=:application_id
              AND kind=:kind
              AND channel_id IS NOT DISTINCT FROM CAST(:channel_id AS uuid)
              AND external_conversation_id IS NOT DISTINCT FROM :external_conversation_id
            ORDER BY created_at,id
            LIMIT 1
            FOR UPDATE
            """,
            tenant=resolved.tenant_id,
            business=resolved.business_id,
            workspace=resolved.workspace_id,
            application_id=app_id,
            kind=kind,
            channel_id=selected_channel,
            external_conversation_id=external_conversation_id,
        )
        conversation = required(
            existing,
            "service_application_conversation_conflict",
        )
        return await one(
            connection,
            """
            UPDATE service_application_conversations
            SET customer_id=COALESCE(:customer_id,customer_id),
                external_user_id=COALESCE(:external_user_id,external_user_id),
                user_name=COALESCE(:user_name,user_name),
                assigned_to=COALESCE(:assigned_to,assigned_to),
                agent_id=COALESCE(:agent_id,agent_id),
                agent_version=COALESCE(:agent_version,agent_version),
                metadata=metadata || CAST(:metadata AS jsonb),
                updated_at=now()
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND id=:conversation_id
            RETURNING *
            """,
            **{
                **_scope_params(conversation),
                "customer_id": selected_customer,
                "external_user_id": external_user_id,
                "user_name": user_name,
                "assigned_to": assigned_to,
                "agent_id": selected_agent,
                "agent_version": agent_version,
                "metadata": json.dumps(conversation_metadata, ensure_ascii=False),
            },
        )

    @staticmethod
    async def append_message(
        connection: object,
        conversation: dict[str, Any],
        *,
        role: str,
        content: str,
        content_type: str = "text",
        payload: dict[str, Any] | None = None,
        runtime_message_id: UUID | str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Append one ordered message, returning the existing row on retry."""

        _validate_choice(role, MESSAGE_ROLES, "service_application_message_role_invalid")
        runtime_id = _uuid_or_none(
            runtime_message_id,
            "service_application_message_runtime_id_invalid",
        )
        required(
            await one(
                connection,
                """
                SELECT id
                FROM service_application_conversations
                WHERE tenant_id=:tenant
                  AND business_id=:business
                  AND workspace_id=:workspace
                  AND id=:conversation_id
                FOR UPDATE
                """,
                **_scope_params(conversation),
            ),
            "service_application_conversation_not_found",
        )

        existing = await BusinessConversationService._existing_message(
            connection,
            conversation,
            runtime_message_id=runtime_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing, False

        next_seq = await connection.scalar(
            text(
                """
                SELECT COALESCE(max(seq),0)+1
                FROM service_application_messages
                WHERE tenant_id=:tenant
                  AND business_id=:business
                  AND workspace_id=:workspace
                  AND conversation_id=:conversation_id
                """
            ),
            _scope_params(conversation),
        )
        inserted = await one(
            connection,
            """
            INSERT INTO service_application_messages(
                id,tenant_id,business_id,workspace_id,conversation_id,seq,
                role,content,content_type,payload,runtime_message_id,idempotency_key
            ) VALUES(
                :id,:tenant,:business,:workspace,:conversation_id,:seq,
                :role,:content,:content_type,CAST(:payload AS jsonb),
                :runtime_message_id,:idempotency_key
            )
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            id=uuid4(),
            seq=int(next_seq or 1),
            role=role,
            content=content,
            content_type=content_type,
            payload=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            runtime_message_id=runtime_id,
            idempotency_key=idempotency_key,
            **_scope_params(conversation),
        )
        if inserted is None:
            inserted = await BusinessConversationService._existing_message(
                connection,
                conversation,
                runtime_message_id=runtime_id,
                idempotency_key=idempotency_key,
            )
        message = required(inserted, "service_application_message_conflict")
        await connection.execute(
            text(
                """
                UPDATE service_application_conversations
                SET last_message_at=:created_at,updated_at=now()
                WHERE tenant_id=:tenant
                  AND business_id=:business
                  AND workspace_id=:workspace
                  AND id=:conversation_id
                """
            ),
            {**_scope_params(conversation), "created_at": message["created_at"]},
        )
        return message, True

    @staticmethod
    async def _existing_message(
        connection: object,
        conversation: dict[str, Any],
        *,
        runtime_message_id: UUID | None,
        idempotency_key: str | None,
    ) -> dict[str, Any] | None:
        if runtime_message_id is None and idempotency_key is None:
            return None
        return await one(
            connection,
            """
            SELECT *
            FROM service_application_messages
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND conversation_id=:conversation_id
              AND (
                (CAST(:runtime_message_id AS uuid) IS NOT NULL
                 AND runtime_message_id=CAST(:runtime_message_id AS uuid))
                OR (CAST(:idempotency_key AS text) IS NOT NULL
                    AND idempotency_key=CAST(:idempotency_key AS text))
              )
            ORDER BY seq
            LIMIT 1
            """,
            runtime_message_id=runtime_message_id,
            idempotency_key=idempotency_key,
            **_scope_params(conversation),
        )

    @staticmethod
    async def message_by_idempotency_key(
        connection: object,
        conversation: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        return await one(
            connection,
            """
            SELECT *
            FROM service_application_messages
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND conversation_id=:conversation_id
              AND idempotency_key=:idempotency_key
            LIMIT 1
            """,
            idempotency_key=idempotency_key,
            **_scope_params(conversation),
        )

    @staticmethod
    async def start_turn(
        connection: object,
        conversation: dict[str, Any],
        customer_message: dict[str, Any] | UUID | str | None = None,
        *,
        customer_message_id: UUID | str | None = None,
        application_version: int,
        agent_id: UUID | str,
        agent_version: int,
        status: str = "queued",
        runtime_conversation_id: UUID | str | None = None,
        runtime_run_id: UUID | str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Create one turn per customer message, no-op on duplicate delivery."""

        _validate_choice(status, TURN_STATUSES, "service_application_turn_status_invalid")
        selected_message_id = customer_message_id
        if selected_message_id is None and isinstance(customer_message, dict):
            selected_message_id = customer_message.get("id")
        elif selected_message_id is None:
            selected_message_id = customer_message
        customer_id = _uuid_or_none(
            selected_message_id,
            "service_application_turn_customer_message_invalid",
        )
        selected_agent = _uuid_or_none(
            agent_id,
            "service_application_turn_agent_invalid",
        )
        runtime_conversation = _uuid_or_none(
            runtime_conversation_id,
            "service_application_turn_runtime_conversation_invalid",
        )
        runtime_run = _uuid_or_none(
            runtime_run_id,
            "service_application_turn_runtime_run_invalid",
        )
        if (
            customer_id is None
            or selected_agent is None
            or application_version < 1
            or agent_version < 1
        ):
            raise DomainError("service_application_turn_invalid", 422)
        inserted = await one(
            connection,
            """
            INSERT INTO service_application_turns(
                id,tenant_id,business_id,workspace_id,conversation_id,
                customer_message_id,application_version,agent_id,agent_version,
                runtime_conversation_id,runtime_run_id,status,finished_at
            ) VALUES(
                :id,:tenant,:business,:workspace,:conversation_id,
                :customer_message_id,:application_version,:agent_id,:agent_version,
                :runtime_conversation_id,:runtime_run_id,:status,
                CASE WHEN :status IN ('completed','failed','cancelled')
                     THEN now() ELSE NULL END
            )
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            id=uuid4(),
            customer_message_id=customer_id,
            application_version=application_version,
            agent_id=selected_agent,
            agent_version=agent_version,
            runtime_conversation_id=runtime_conversation,
            runtime_run_id=runtime_run,
            status=status,
            **_scope_params(conversation),
        )
        if inserted is not None:
            return inserted, True
        existing = await one(
            connection,
            """
            SELECT *
            FROM service_application_turns
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND conversation_id=:conversation_id
              AND customer_message_id=:customer_message_id
            FOR UPDATE
            """,
            customer_message_id=customer_id,
            **_scope_params(conversation),
        )
        existing_turn = required(existing, "service_application_turn_conflict")
        if existing_turn.get("runtime_run_id") is None and (
            runtime_conversation is not None or runtime_run is not None
        ):
            existing_turn = await BusinessConversationService.link_turn(
                connection,
                existing_turn,
                runtime_conversation_id=runtime_conversation or existing_turn["runtime_conversation_id"],
                runtime_run_id=runtime_run,
                status=status,
            )
        return existing_turn, False

    @staticmethod
    async def link_turn(
        connection: object,
        turn: dict[str, Any],
        *,
        runtime_conversation_id: UUID | str,
        runtime_run_id: UUID | str | None,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        """Link a turn to Runtime conversation/run and publish its current status."""

        _validate_choice(status, TURN_STATUSES, "service_application_turn_status_invalid")
        runtime_conversation = _uuid_or_none(
            runtime_conversation_id,
            "service_application_turn_runtime_conversation_invalid",
        )
        runtime_run = _uuid_or_none(
            runtime_run_id,
            "service_application_turn_runtime_run_invalid",
        )
        if runtime_conversation is None:
            raise DomainError("service_application_turn_runtime_conversation_invalid", 422)
        updated = await one(
            connection,
            """
            UPDATE service_application_turns
            SET runtime_conversation_id=:runtime_conversation_id,
                runtime_run_id=COALESCE(runtime_run_id,:runtime_run_id),
                status=:status,
                error_code=:error_code,
                finished_at=CASE
                    WHEN :status IN ('completed','failed','cancelled') THEN now()
                    ELSE NULL
                END
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND id=:turn_id
              AND (runtime_run_id IS NULL OR runtime_run_id=:runtime_run_id)
            RETURNING *
            """,
            runtime_conversation_id=runtime_conversation,
            runtime_run_id=runtime_run,
            status=status,
            error_code=error_code,
            turn_id=turn["id"],
            tenant=turn["tenant_id"],
            business=turn["business_id"],
            workspace=turn["workspace_id"],
        )
        return required(updated, "service_application_turn_not_found")

    @staticmethod
    async def complete_turn_from_runtime(
        connection: object,
        *,
        runtime_run_id: UUID | str,
        tenant_id: str,
        business_id: str,
        workspace_id: str,
        assistant_content: str,
        runtime_message_id: UUID | str,
    ) -> dict[str, Any] | None:
        """Idempotently write the assistant reply and complete its business turn."""

        run_id = _uuid_or_none(runtime_run_id, "service_application_turn_runtime_run_invalid")
        if run_id is None:
            return None
        turn = await one(
            connection,
            """
            SELECT *
            FROM service_application_turns
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND runtime_run_id=:runtime_run_id
            FOR UPDATE
            """,
            tenant=tenant_id,
            business=business_id,
            workspace=workspace_id,
            runtime_run_id=run_id,
        )
        if turn is None:
            return None
        conversation = await one(
            connection,
            """
            SELECT *
            FROM service_application_conversations
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND id=:conversation_id
            FOR UPDATE
            """,
            tenant=tenant_id,
            business=business_id,
            workspace=workspace_id,
            conversation_id=turn["conversation_id"],
        )
        if conversation is None:
            return None
        assistant_message, _created = await BusinessConversationService.append_message(
            connection,
            conversation,
            role="assistant",
            content=str(assistant_content or ""),
            runtime_message_id=runtime_message_id,
            idempotency_key=f"runtime-run:{run_id}:assistant",
        )
        completed = await one(
            connection,
            """
            UPDATE service_application_turns
            SET assistant_message_id=:assistant_message_id,
                status='completed',
                error_code=NULL,
                finished_at=now()
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND id=:turn_id
            RETURNING *
            """,
            tenant=tenant_id,
            business=business_id,
            workspace=workspace_id,
            turn_id=turn["id"],
            assistant_message_id=assistant_message["id"],
        )
        await connection.execute(
            text(
                """
                UPDATE service_application_conversations
                SET status=CASE
                        WHEN status IN ('waiting','human','closed') THEN status
                        ELSE 'open'
                    END,
                    updated_at=now()
                WHERE tenant_id=:tenant
                  AND business_id=:business
                  AND workspace_id=:workspace
                  AND id=:conversation_id
                """
            ),
            {
                "tenant": tenant_id,
                "business": business_id,
                "workspace": workspace_id,
                "conversation_id": conversation["id"],
            },
        )
        return completed

    @staticmethod
    async def finish_turn_from_runtime(
        connection: object,
        *,
        runtime_run_id: UUID | str,
        tenant_id: str,
        business_id: str,
        workspace_id: str,
        status: str,
        error_code: str | None,
    ) -> dict[str, Any] | None:
        if status not in {"failed", "cancelled"}:
            raise DomainError("service_application_turn_status_invalid", 422)
        run_id = _uuid_or_none(runtime_run_id, "service_application_turn_runtime_run_invalid")
        if run_id is None:
            return None
        return await one(
            connection,
            """
            UPDATE service_application_turns
            SET status=:status,error_code=:error_code,finished_at=now()
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND runtime_run_id=:runtime_run_id
              AND status NOT IN ('completed','failed','cancelled')
            RETURNING *
            """,
            tenant=tenant_id,
            business=business_id,
            workspace=workspace_id,
            runtime_run_id=run_id,
            status=status,
            error_code=error_code,
        )

    @staticmethod
    async def conversation_for_runtime(
        connection: object,
        *,
        tenant: str | None = None,
        tenant_id: str | None = None,
        scope: BusinessScope | None,
        runtime_conversation_id: UUID | str,
    ) -> dict[str, Any] | None:
        """Resolve the customer business conversation linked to a Runtime conversation."""

        selected_tenant = tenant or tenant_id or (scope.tenant_id if scope else None)
        if not selected_tenant:
            return None
        resolved = persisted_scope(selected_tenant, scope)
        runtime_id = _uuid_or_none(
            runtime_conversation_id,
            "service_application_runtime_conversation_id_invalid",
        )
        if runtime_id is None:
            return None
        scope_sql, scope_params = scope_predicate(resolved, alias="c")
        return await one(
            connection,
            f"""
            SELECT c.*
            FROM service_application_conversations c
            WHERE c.tenant_id=:tenant
              AND c.kind='customer'
              AND {scope_sql}
              AND (
                EXISTS(
                    SELECT 1
                    FROM service_application_turns t
                    WHERE t.tenant_id=c.tenant_id
                      AND t.business_id=c.business_id
                      AND t.workspace_id=c.workspace_id
                      AND t.conversation_id=c.id
                      AND t.runtime_conversation_id=:runtime_conversation_id
                )
                OR c.metadata->>'runtime_conversation_id'=:runtime_conversation_id_text
              )
            ORDER BY c.updated_at DESC,c.id DESC
            LIMIT 1
            FOR UPDATE
            """,
            tenant=resolved.tenant_id,
            runtime_conversation_id=runtime_id,
            runtime_conversation_id_text=str(runtime_id),
            **scope_params,
        )

    @staticmethod
    async def append_runtime_message(
        connection: object,
        *,
        tenant: str | None = None,
        tenant_id: str | None = None,
        scope: BusinessScope | None,
        runtime_conversation_id: UUID | str,
        role: str,
        content: str,
        runtime_message_id: UUID | str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool] | None:
        """Mirror an existing Runtime message into the business ledger if linked."""

        conversation = await BusinessConversationService.conversation_for_runtime(
            connection,
            tenant=tenant,
            tenant_id=tenant_id,
            scope=scope,
            runtime_conversation_id=runtime_conversation_id,
        )
        if conversation is None:
            return None
        return await BusinessConversationService.append_message(
            connection,
            conversation,
            role=role,
            content=content,
            runtime_message_id=runtime_message_id,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    async def set_status_for_runtime(
        connection: object,
        *,
        tenant: str | None = None,
        tenant_id: str | None = None,
        scope: BusinessScope | None,
        runtime_conversation_id: UUID | str,
        status: str,
        assigned_to: str | None = None,
    ) -> dict[str, Any] | None:
        """Mirror a customer-visible Runtime mode into the business conversation."""

        _validate_choice(status, CONVERSATION_STATUSES, "service_application_status_invalid")
        conversation = await BusinessConversationService.conversation_for_runtime(
            connection,
            tenant=tenant,
            tenant_id=tenant_id,
            scope=scope,
            runtime_conversation_id=runtime_conversation_id,
        )
        if conversation is None:
            return None
        return await one(
            connection,
            """
            UPDATE service_application_conversations
            SET status=:status,assigned_to=:assigned_to,updated_at=now()
            WHERE tenant_id=:tenant
              AND business_id=:business
              AND workspace_id=:workspace
              AND id=:conversation_id
            RETURNING *
            """,
            status=status,
            assigned_to=assigned_to,
            **_scope_params(conversation),
        )

    @staticmethod
    async def set_runtime_status(
        connection: object,
        *,
        tenant: str | None = None,
        tenant_id: str | None = None,
        scope: BusinessScope | None,
        runtime_conversation_id: UUID | str,
        status: str,
        assigned_to: str | None = None,
    ) -> dict[str, Any] | None:
        """Compatibility alias used by handoff and conversation services."""

        return await BusinessConversationService.set_status_for_runtime(
            connection,
            tenant=tenant,
            tenant_id=tenant_id,
            scope=scope,
            runtime_conversation_id=runtime_conversation_id,
            status=status,
            assigned_to=assigned_to,
        )


__all__ = [
    "CONVERSATION_KINDS",
    "CONVERSATION_STATUSES",
    "MESSAGE_ROLES",
    "TERMINAL_TURN_STATUSES",
    "TURN_STATUSES",
    "BusinessConversationService",
]
