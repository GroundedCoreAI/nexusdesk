import inspect
import io
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from agent_platform.business_capabilities.agent_config.service import AgentDraft
from agent_platform.business_capabilities.channel.service import IncomingMessage
from agent_platform.business_capabilities.customer_service.service import UNSET
from agent_platform.business_capabilities.evaluation.scoring import ProfileRef, ScoringOptions
from agent_platform.business_capabilities.evaluation.service import EvaluationCase
from agent_platform.business_capabilities.knowledge.chunking import ChunkingPolicy, chunk_document
from agent_platform.business_capabilities.knowledge.service import DocumentInput
from agent_platform.core_platform.extension_platform import (
    CapabilityContributionError,
    ExtensionRegistryError,
)
from agent_platform.core_platform.platform_services.identity.access import (
    Admin,
    ExtensionAdmin,
    Operator,
    Principal,
    Reader,
    require_permission,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError, many
from agent_platform.core_platform.platform_services.persistence.store import audit as audit_record
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolInput
from agent_platform.extension_contracts import CapabilityManifest

router = APIRouter(tags=["platform"])
ingress = APIRouter(tags=["channel-ingress"])

# Evaluation workbooks are spreadsheets of names and prompts, never attachments.
EVALUATION_WORKBOOK_BYTES = 5_000_000
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
logger = logging.getLogger(__name__)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NameInput(Input):
    name: str = Field(min_length=1, max_length=100)


class RevisionInput(Input):
    revision: int = Field(ge=1)


class DraftUpdate(AgentDraft):
    revision: int = Field(ge=1)


class VersionInput(Input):
    version: int = Field(ge=1)


class EnabledInput(Input):
    enabled: bool


class CapabilityConfigInput(Input):
    schema_version: str = Field(default="v1", min_length=1, max_length=100)
    config: dict[str, object] = Field(default_factory=dict)


class CapabilityConfigRollbackInput(Input):
    version: int = Field(ge=1)


class ArchiveInput(RevisionInput):
    archived: bool


class ToolDraftInput(ToolInput):
    revision: int = Field(ge=1)


class ToolSimulation(Input):
    definition: HttpTool
    arguments: dict
    response: dict | list | str | int | float | bool | None = None


class ChunkPreview(Input):
    content: str = Field(min_length=1, max_length=200000)
    policy: ChunkingPolicy = Field(default_factory=ChunkingPolicy)


class ConversationInput(Input):
    external_id: str = Field(min_length=1, max_length=128)
    agent_id: UUID | None = None
    source: Literal["business", "playground"] = "business"


class MessageInput(Input):
    content: str = Field(min_length=1, max_length=8000)


class HandoffInput(Input):
    reason: str = Field(min_length=1, max_length=1000)


class HandoffTransition(Input):
    operation: Literal["claim", "resume", "close"]
    assignee: str | None = Field(default=None, max_length=100)
    revision: int | None = Field(default=None, ge=1)


class ConversationTransition(RevisionInput):
    operation: Literal["close", "reopen"]


class StaffInput(NameInput):
    role: Literal["operator", "viewer"] = "operator"


class DecisionInput(Input):
    approve: bool


class TicketUpdate(Input):
    status: Literal["open", "in_progress", "waiting_customer", "resolved", "closed"]
    note: str = Field(default="", max_length=8000)
    revision: int = Field(ge=1)
    # Phase 3: marking a remark as a commitment records it in the customer's
    # event memory (only meaningful with a non-empty note).
    is_commitment: bool = False
    # Phase 4 (R12): operators may set a response deadline (or clear it with
    # an explicit null); the built-in complaint-risk rule scans this column.
    # Omitted means "leave unchanged".
    due_at: datetime | None = None


class ChannelInput(NameInput):
    agent_id: UUID
    signing_secret_ref: str | None = Field(
        default=None, pattern=r"^AGENT_CHANNEL_SECRET_[A-Z0-9_]+$"
    )
    provider: str = Field(default="generic_webhook", pattern=r"^[a-z][a-z0-9_]{0,39}$")
    config: dict[str, object] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)


class ChannelUpdateInput(Input):
    config: dict[str, object] | None = None
    credentials: dict[str, str] | None = None


def _ui_manifest_payload(manifest, user=None, extensions=None):
    def allowed(permissions, capability):
        if user is not None and any(not user.can(permission) for permission in permissions):
            return False
        return not (capability and extensions is not None and not extensions.is_enabled(capability))

    routes = tuple(
        route
        for route in manifest.routes
        if allowed(route.required_permissions, route.required_capability)
    )
    route_paths = {route.path for route in routes}
    navigation = tuple(
        item
        for item in manifest.navigation
        if item.path in route_paths and allowed(item.required_permissions, item.required_capability)
    )
    if user is not None and not navigation:
        return None
    return {
        "extensionId": manifest.extension_id,
        "version": manifest.version,
        "apiVersion": manifest.api_version,
        "requiresPlatform": manifest.requires_platform,
        "navigation": [
            {
                "id": item.id,
                "labelKey": item.label_key,
                "path": item.path,
                "icon": item.icon,
                "group": item.group,
                "requiredPermissions": list(item.required_permissions),
                "requiredCapability": item.required_capability,
                "order": item.order,
            }
            for item in navigation
        ],
        "routes": [
            {
                "id": route.id,
                "path": route.path,
                "feature": route.feature,
                "requiredPermissions": list(route.required_permissions),
                "requiredCapability": route.required_capability,
            }
            for route in routes
        ],
    }


def groups(request):
    return request.app.state.runtime.groups


def runtime(request):
    return groups(request).runtime


def tool_services(request):
    return groups(request).tools


def business(request):
    return groups(request).business


def application(request):
    return groups(request).application


async def _audit_extension_action(
    request: Request, user: Principal, action: str, resource: str, **details
):
    """Record platform lifecycle operations without persisting sensitive config values."""

    try:
        async with runtime(request).engine.begin() as conn:
            await audit_record(conn, user.tenant, user.actor, action, resource, **details)
    except SQLAlchemyError:
        # The lifecycle operation already completed in the process-local registry.
        # Keep the API response truthful while making the audit outage visible.
        logger.exception("failed to audit extension lifecycle operation: %s", action)


async def _run_extension_lifecycle_action(
    request: Request,
    capability_id: str,
    actor: str,
    operation: Callable[[], Awaitable[object]],
):
    """Serialize one capability mutation across API processes."""

    state = request.app.state.runtime.capability_state

    async def mutate():
        result = await operation()
        await state.persist(capability_id, actor)
        return result

    return await state.run_lifecycle_locked(capability_id, mutate)


@router.get("/me")
async def me(user: Reader):
    return {
        "tenant": user.tenant,
        "role": user.role,
        "actor": user.actor,
        "user_id": user.user_id,
        "auth_source": user.auth_source,
        "session_id": user.session_id,
        "permissions": sorted(user.permissions),
    }


@router.get("/extensions/ui")
async def ui_extension_manifests(request: Request, user: Reader):
    """Return UI contributions without exposing extension implementations."""

    return [
        payload
        for manifest in request.app.state.runtime.ui_extensions.list()
        if (
            payload := _ui_manifest_payload(
                manifest,
                user,
                request.app.state.runtime.extensions,
            )
        )
        is not None
    ]


@router.get("/extensions/capabilities")
async def capability_status(request: Request, user: Reader):
    """Return capability lifecycle and durable event-delivery health."""

    runtime_services = request.app.state.runtime
    events = runtime_services.events
    if hasattr(events, "delivery_status"):
        delivery = events.delivery_status(user.tenant)
    else:
        delivery = events.observability() if hasattr(events, "observability") else {}
    if inspect.isawaitable(delivery):
        delivery = await delivery
    return {
        "capabilities": runtime_services.extensions.observability(),
        "discovery": [
            {
                "file": result.path.name,
                "capability_id": result.capability_id,
                "status": result.status,
                "error": result.error,
            }
            for result in getattr(runtime_services, "extension_discovery", ())
        ],
        "events": delivery,
    }


@router.post("/extensions/capabilities/{capability_id}/enable")
async def enable_capability(capability_id: str, request: Request, user: ExtensionAdmin):
    try:
        result = await _run_extension_lifecycle_action(
            request,
            capability_id,
            user.actor,
            lambda: request.app.state.runtime.extensions.enable(capability_id),
        )
    except ExtensionRegistryError as exc:
        raise DomainError("extension_registry_conflict", 409) from exc
    await _audit_extension_action(
        request,
        user,
        "extension.enabled",
        capability_id,
        version=result.version,
        status=result.status,
    )
    request.app.state.runtime.contributions.attach_events(request.app.state.runtime.events)
    return result


@router.post("/extensions/capabilities/{capability_id}/disable")
async def disable_capability(capability_id: str, request: Request, user: ExtensionAdmin):
    try:
        result = await _run_extension_lifecycle_action(
            request,
            capability_id,
            user.actor,
            lambda: request.app.state.runtime.extensions.disable(capability_id),
        )
    except ExtensionRegistryError as exc:
        raise DomainError("extension_registry_conflict", 409) from exc
    await _audit_extension_action(
        request,
        user,
        "extension.disabled",
        capability_id,
        version=result.version,
        status=result.status,
    )
    request.app.state.runtime.contributions.detach_capability_events(capability_id)
    return result


@router.post("/extensions/capabilities/{capability_id}/retry")
async def retry_capability(capability_id: str, request: Request, user: ExtensionAdmin):
    try:
        result = await _run_extension_lifecycle_action(
            request,
            capability_id,
            user.actor,
            lambda: request.app.state.runtime.extensions.retry(capability_id),
        )
    except ExtensionRegistryError as exc:
        raise DomainError("extension_registry_conflict", 409) from exc
    request.app.state.runtime.contributions.attach_events(request.app.state.runtime.events)
    await _audit_extension_action(
        request,
        user,
        "extension.retried",
        capability_id,
        version=result.version,
        status=result.status,
    )
    return result


@router.post("/extensions/capabilities/{capability_id}/upgrade")
async def upgrade_capability(
    capability_id: str,
    body: CapabilityManifest,
    request: Request,
    user: ExtensionAdmin,
):
    try:
        async def upgrade():
            request.app.state.runtime.contributions.validate_manifest_change(capability_id, body)
            return await request.app.state.runtime.extensions.upgrade(capability_id, body)

        previous = request.app.state.runtime.extensions.get(capability_id)
        result = await _run_extension_lifecycle_action(
            request,
            capability_id,
            user.actor,
            upgrade,
        )
        request.app.state.runtime.contributions.attach_events(request.app.state.runtime.events)
    except (CapabilityContributionError, ExtensionRegistryError) as exc:
        raise DomainError("extension_registry_conflict", 409) from exc
    await _audit_extension_action(
        request,
        user,
        "extension.upgraded",
        capability_id,
        previous_version=previous.version if previous else None,
        version=result.version,
        status=result.status,
    )
    return result


@router.post("/extensions/capabilities/{capability_id}/rollback")
async def rollback_capability(capability_id: str, request: Request, user: ExtensionAdmin):
    try:
        async def rollback():
            target = request.app.state.runtime.extensions.rollback_manifest(capability_id)
            if target is not None:
                request.app.state.runtime.contributions.validate_manifest_change(
                    capability_id,
                    target,
                )
            return await request.app.state.runtime.extensions.rollback(capability_id)

        previous = request.app.state.runtime.extensions.get(capability_id)
        result = await _run_extension_lifecycle_action(
            request,
            capability_id,
            user.actor,
            rollback,
        )
        request.app.state.runtime.contributions.attach_events(request.app.state.runtime.events)
    except (CapabilityContributionError, ExtensionRegistryError) as exc:
        raise DomainError("extension_registry_conflict", 409) from exc
    await _audit_extension_action(
        request,
        user,
        "extension.rolled_back",
        capability_id,
        previous_version=previous.version if previous else None,
        version=result.version,
        status=result.status,
    )
    return result


@router.get("/extensions/capabilities/{capability_id}/config")
async def capability_config(capability_id: str, request: Request, user: ExtensionAdmin):
    try:
        config = await request.app.state.runtime.capability_config.current(capability_id)
    except ExtensionRegistryError as exc:
        raise DomainError("extension_config_conflict", 409) from exc
    if config is None:
        raise DomainError("extension_config_not_found", 404)
    return config


@router.get("/extensions/capabilities/{capability_id}/config/versions")
async def capability_config_versions(
    capability_id: str,
    request: Request,
    user: ExtensionAdmin,
):
    try:
        versions = await request.app.state.runtime.capability_config.versions(capability_id)
    except ExtensionRegistryError as exc:
        raise DomainError("extension_registry_conflict", 409) from exc
    return {"items": versions}


@router.post("/extensions/capabilities/{capability_id}/config")
async def configure_capability(
    capability_id: str,
    body: CapabilityConfigInput,
    request: Request,
    user: ExtensionAdmin,
):
    try:
        return await request.app.state.runtime.capability_config.configure(
            capability_id,
            body.config,
            user.tenant,
            user.actor,
            body.schema_version,
        )
    except ExtensionRegistryError as exc:
        raise DomainError("extension_config_conflict", 409) from exc


@router.post("/extensions/capabilities/{capability_id}/config/rollback")
async def rollback_capability_config(
    capability_id: str,
    body: CapabilityConfigRollbackInput,
    request: Request,
    user: ExtensionAdmin,
):
    try:
        return await request.app.state.runtime.capability_config.rollback_config(
            capability_id,
            body.version,
            user.tenant,
            user.actor,
        )
    except ExtensionRegistryError as exc:
        raise DomainError("extension_config_conflict", 409) from exc


@router.get("/extensions/events")
async def extension_events(
    request: Request,
    user: Admin,
    status: Literal["pending", "running", "done", "failed"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    events = request.app.state.runtime.events
    if not hasattr(events, "list_tasks"):
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    return await events.list_tasks(user.tenant, status, page, page_size)


@router.post("/extensions/events/{event_id}/retry")
async def retry_extension_event(event_id: UUID, request: Request, user: Admin):
    events = request.app.state.runtime.events
    if not hasattr(events, "retry_task"):
        raise DomainError("event_not_retryable", 409)
    return await events.retry_task(user.tenant, event_id)


@router.get("/staff")
async def staff(
    request: Request,
    user: Annotated[Principal, Depends(require_permission("credential.read"))],
):
    return await application(request).staff.list(user.tenant)


@router.post("/staff", status_code=201)
async def create_staff(
    body: StaffInput,
    request: Request,
    user: Annotated[Principal, Depends(require_permission("credential.manage"))],
):
    return await application(request).staff.create(user.tenant, user.actor, body.name, body.role)


@router.patch("/staff/{sid}")
async def enable_staff(
    sid: UUID,
    body: EnabledInput,
    request: Request,
    user: Annotated[Principal, Depends(require_permission("credential.manage"))],
):
    return await application(request).staff.enable(user.tenant, user.actor, sid, body.enabled)


@router.post("/conversations/{cid}/transition")
async def conversation_transition(
    cid: UUID, body: ConversationTransition, request: Request, user: Operator
):
    return await business(request).conversations.transition(
        user.tenant, user.actor, cid, body.operation, body.revision
    )


@router.get("/agents")
async def agents(
    request: Request,
    user: Reader,
    q: str = Query(default="", max_length=100),
    include_archived: bool = False,
):
    return await business(request).agents.list(user.tenant, q, include_archived)


@router.get("/agents/counts")
async def agent_counts(request: Request, user: Reader):
    return await business(request).conversations.counts_by_agent(user.tenant)


@router.get("/agents/catalog")
async def agent_catalog(
    request: Request,
    user: Reader,
    q: str = Query(default="", max_length=100),
    include_archived: bool = False,
    status: Literal["all", "published", "unpublished"] = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    industry: Annotated[list[str] | None, Query(max_length=20)] = None,
    tag: Annotated[list[str] | None, Query(max_length=10)] = None,
    examples_only: bool = False,
    mine_only: bool = False,
):
    return await business(request).agents.catalog(
        user.tenant,
        q,
        include_archived,
        status,
        page,
        page_size,
        industry,
        tag,
        examples_only,
        created_by=user.actor if mine_only else None,
    )


@router.get("/agents/memory-config-caps")
async def agent_memory_config_caps(request: Request, user: Reader):
    """Platform-side memory capability caps for the agent config form (C-6).

    Returns the platform-level switches and ceilings the form uses to show
    "platform disabled" hints and to warn about numeric truncation. These are
    tenant-agnostic deployment settings; authentication is still required, and
    no tenant-scoped data is exposed.
    """
    s = runtime(request).settings
    return {
        "summary_enabled": s.summary_enabled,
        "memory_inject_enabled": s.memory_inject_enabled,
        "memory_extract_enabled": s.memory_extract_enabled,
        "memory_inject_max_items": s.memory_inject_max_items,
        # The agent-facing ceiling (D2), not the store's second-line clamp
        # memory_search_limit_max: the form warns against the value the
        # effective config actually truncates to.
        "memory_search_limit": s.memory_search_limit,
        "memory_blacklist_auto_handoff": s.memory_blacklist_auto_handoff,
    }


@router.get("/agents/{aid}")
async def agent_detail(aid: UUID, request: Request, user: Reader):
    return await business(request).agents.get(user.tenant, aid)


@router.get("/agents/{aid}/conversations/counts")
async def agent_conversation_counts(aid: UUID, request: Request, user: Reader):
    return await business(request).conversations.agent_counts(user.tenant, str(aid))


@router.get("/agents/{aid}/conversations")
async def agent_conversations(
    aid: UUID,
    request: Request,
    user: Reader,
    source: Literal["all", "business", "playground"] = "all",
    q: str = Query(default="", max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
):
    return await business(request).conversations.agent_records(
        user.tenant, aid, source, q, page, page_size
    )


@router.delete("/agents/{aid}")
async def delete_agent(aid: UUID, request: Request, user: Admin, revision: int = Query(ge=1)):
    return await business(request).agents.delete(user.tenant, user.actor, aid, revision)


@router.patch("/agents/{aid}/archive")
async def archive_agent(aid: UUID, body: ArchiveInput, request: Request, user: Admin):
    return await business(request).agents.archive(
        user.tenant, user.actor, aid, body.archived, body.revision
    )


@router.get("/agents/{aid}/diff")
async def agent_diff(aid: UUID, request: Request, user: Reader, version: int = Query(ge=1)):
    return await business(request).agents.diff(user.tenant, aid, version)


@router.post("/agents", status_code=201)
async def create_agent(body: AgentDraft, request: Request, user: Admin):
    return await business(request).agents.create(user.tenant, user.actor, body)


@router.put("/agents/{aid}")
async def update_agent(aid: UUID, body: DraftUpdate, request: Request, user: Admin):
    return await business(request).agents.update(user.tenant, user.actor, aid, body, body.revision)


@router.get("/agents/{aid}/versions")
async def versions(aid: UUID, request: Request, user: Reader):
    return await business(request).agents.versions(user.tenant, aid)


@router.post("/agents/{aid}/publish")
async def publish(aid: UUID, body: RevisionInput, request: Request, user: Admin):
    return await business(request).agents.publish(user.tenant, user.actor, aid, body.revision)


@router.post("/agents/{aid}/rollback")
async def rollback(aid: UUID, body: VersionInput, request: Request, user: Admin):
    return await business(request).agents.rollback(user.tenant, user.actor, aid, body.version)


@router.get("/tools")
async def tools(request: Request, user: Reader):
    return await tool_services(request).tools.list(user.tenant)


@router.post("/tools", status_code=201)
async def create_tool(body: ToolInput, request: Request, user: Admin):
    return await tool_services(request).tools.create(user.tenant, user.actor, body)


@router.patch("/tools/{tid}")
async def enable_tool(tid: UUID, body: EnabledInput, request: Request, user: Admin):
    return await tool_services(request).tools.toggle(user.tenant, user.actor, tid, body.enabled)


@router.put("/tools/{tid}")
async def update_tool(tid: UUID, body: ToolDraftInput, request: Request, user: Admin):
    spec = ToolInput.model_validate(body.model_dump(exclude={"revision"}))
    return await tool_services(request).tools.update(
        user.tenant, user.actor, tid, spec, body.revision
    )


@router.get("/tools/{tid}/versions")
async def tool_versions(tid: UUID, request: Request, user: Reader):
    return await tool_services(request).tools.versions(user.tenant, tid)


@router.post("/tools/{tid}/publish")
async def publish_tool(tid: UUID, body: RevisionInput, request: Request, user: Admin):
    return await tool_services(request).tools.publish(user.tenant, user.actor, tid, body.revision)


@router.post("/tool-simulations")
async def simulate_tool(body: ToolSimulation, user: Admin):
    if not Draft202012Validator(body.definition.parameters).is_valid(body.arguments):
        raise DomainError("invalid_arguments")
    if body.definition.response_schema is not None and not Draft202012Validator(
        body.definition.response_schema
    ).is_valid(body.response):
        raise DomainError("invalid_output_schema")
    return {
        "ok": True,
        "data": body.response,
        "execution_status": "succeeded",
        "simulation": True,
        "upstream_called": False,
    }


@router.get("/tool-calls")
async def tool_calls(request: Request, user: Reader, before: UUID | None = None):
    async with runtime(request).engine.connect() as c:
        return await many(
            c,
            "SELECT * FROM tool_calls WHERE tenant_id=:t AND (CAST(:before AS uuid) IS NULL OR (created_at,id) < (SELECT created_at,id FROM tool_calls WHERE id=:before AND tenant_id=:t)) ORDER BY created_at DESC,id DESC LIMIT 100",
            t=user.tenant,
            before=before,
        )


@router.get("/knowledge-bases")
async def bases(request: Request, user: Reader):
    return await business(request).knowledge.bases(user.tenant)


@router.post("/knowledge-bases", status_code=201)
async def create_base(body: NameInput, request: Request, user: Admin):
    return await business(request).knowledge.create_base(user.tenant, user.actor, body.name)


@router.get("/knowledge-bases/{kid}/documents")
async def documents(kid: UUID, request: Request, user: Reader):
    return await business(request).knowledge.documents(user.tenant, kid)


@router.post("/knowledge/chunk-preview")
async def chunk_preview(body: ChunkPreview, user: Admin):
    return {"chunks": chunk_document(body.content, body.policy), "policy": body.policy.model_dump()}


@router.post("/knowledge-bases/{kid}/uploads", status_code=202)
async def knowledge_upload(
    kid: UUID, request: Request, user: Admin, filename: str = Query(min_length=1, max_length=255)
):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > runtime(request).settings.knowledge_upload_bytes:
            raise DomainError("document_size_exceeded", 413)
    return await business(request).ingestion.create(
        user.tenant, user.actor, kid, filename, bytes(content)
    )


@router.get("/knowledge-bases/{kid}/jobs")
async def knowledge_jobs(kid: UUID, request: Request, user: Reader):
    return await business(request).ingestion.list(user.tenant, kid)


@router.post("/knowledge-jobs/{jid}/cancel")
async def cancel_knowledge(jid: UUID, request: Request, user: Admin):
    return await business(request).ingestion.cancel(user.tenant, user.actor, jid)


@router.post("/knowledge-jobs/{jid}/retry")
async def retry_knowledge(jid: UUID, request: Request, user: Admin):
    return await business(request).ingestion.retry(user.tenant, user.actor, jid)


@router.get("/knowledge-jobs/{jid}/pages")
async def knowledge_pages(jid: UUID, request: Request, user: Reader):
    return await business(request).ingestion.pages(user.tenant, jid)


@router.post("/knowledge-bases/{kid}/vector-index")
async def build_vector_index(kid: UUID, body: ProfileRef, request: Request, user: Admin):
    return await business(request).vector_index.build(user.tenant, user.actor, kid, body)


@router.get("/knowledge-bases/{kid}/vector-search")
async def vector_search(
    kid: UUID, request: Request, user: Reader, q: str = Query(min_length=1, max_length=500)
):
    return await business(request).vector_index.search(user.tenant, kid, q)


@router.post("/knowledge-bases/{kid}/documents", status_code=201)
async def create_document(kid: UUID, body: DocumentInput, request: Request, user: Admin):
    return await business(request).knowledge.save_document(user.tenant, user.actor, kid, body)


@router.put("/knowledge-bases/{kid}/documents/{did}")
async def update_document(
    kid: UUID,
    did: UUID,
    body: DocumentInput,
    request: Request,
    user: Admin,
    version: Annotated[int, Query(ge=1)],
):
    return await business(request).knowledge.save_document(
        user.tenant, user.actor, kid, body, did, version
    )


@router.patch("/documents/{did}")
async def enable_document(did: UUID, body: EnabledInput, request: Request, user: Admin):
    return await business(request).knowledge.toggle(user.tenant, user.actor, did, body.enabled)


@router.get("/knowledge/search")
async def search(
    request: Request,
    user: Reader,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    kb: UUID | None = None,
):
    return await business(request).knowledge.search(user.tenant, q, [kb] if kb else None)


@router.get("/conversations")
async def conversations(
    request: Request,
    user: Reader,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    agent_id: UUID | None = None,
    status: Literal["all", "bot", "waiting", "human", "closed"] = "all",
):
    return await business(request).conversations.list_paginated(
        user.tenant,
        page,
        page_size,
        agent_id=str(agent_id) if agent_id else None,
        status=status,
    )


@router.post("/conversations", status_code=201)
async def create_conversation(body: ConversationInput, request: Request, user: Operator):
    return await business(request).conversations.create(
        user.tenant, user.actor, body.external_id, body.agent_id, source=body.source
    )


@router.get("/conversations/{cid}")
async def conversation(
    cid: UUID, request: Request, user: Reader, after: Annotated[int, Query(ge=0)] = 0
):
    return await business(request).conversations.detail(user.tenant, cid, after)


@router.get("/conversations/{cid}/history")
async def conversation_history(
    cid: UUID,
    request: Request,
    user: Reader,
    before: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
):
    return await business(request).conversations.history(user.tenant, cid, before, limit)


@router.post("/conversations/{cid}/messages", status_code=202)
async def message(cid: UUID, body: MessageInput, request: Request, user: Operator):
    return await business(request).customer.send(user.tenant, user.actor, cid, body.content)


@router.post("/conversations/{cid}/human-replies")
async def human_reply(cid: UUID, body: MessageInput, request: Request, user: Operator):
    return await business(request).conversations.human_reply(
        user.tenant, user.actor, cid, body.content, administrator=user.role == "admin"
    )


@router.post("/conversations/{cid}/handoffs")
async def request_handoff(cid: UUID, body: HandoffInput, request: Request, user: Operator):
    return await business(request).handoffs.request(user.tenant, user.actor, cid, body.reason)


@router.get("/handoffs")
async def handoffs(request: Request, user: Reader):
    return await business(request).handoffs.list(user.tenant)


@router.post("/handoffs/{hid}/transition")
async def transition(hid: UUID, body: HandoffTransition, request: Request, user: Operator):
    return await business(request).handoffs.transition(
        user.tenant,
        user.actor,
        hid,
        body.operation,
        body.assignee,
        body.revision,
        administrator=user.role == "admin",
    )


@router.post("/actions/{aid}/decision")
async def decision(aid: UUID, body: DecisionInput, request: Request, user: Operator):
    return await business(request).confirmation.decide(
        user.tenant,
        user.actor,
        aid,
        body.approve,
    )


@router.get("/tickets")
async def tickets(request: Request, user: Reader):
    return await business(request).customer.tickets(user.tenant)


@router.patch("/tickets/{tid}")
async def ticket(tid: UUID, body: TicketUpdate, request: Request, user: Operator):
    # due_at only travels when the field was sent explicitly (set or clear);
    # an omitted field keeps the stored deadline.
    due_at = body.due_at if "due_at" in body.model_fields_set else UNSET
    return await business(request).customer.update_ticket(
        user.tenant,
        user.actor,
        tid,
        body.status,
        body.note,
        body.revision,
        body.is_commitment,
        due_at=due_at,
    )


@router.get("/channels")
async def channels(request: Request, user: Reader):
    return await business(request).channels.list(user.tenant)


@router.get("/channels/providers")
async def channel_providers(request: Request, user: Reader):
    return business(request).channels.providers()


@router.post("/channels", status_code=201)
async def channel(body: ChannelInput, request: Request, user: Admin):
    return await business(request).channels.create(
        user.tenant,
        user.actor,
        body.name,
        body.agent_id,
        body.signing_secret_ref,
        provider=body.provider,
        config=body.config,
        credentials=body.credentials,
    )


@router.post("/channels/{cid}/config")
async def configure_channel(cid: UUID, body: ChannelUpdateInput, request: Request, user: Admin):
    return await business(request).channels.update(
        user.tenant,
        user.actor,
        cid,
        config=body.config,
        credentials=body.credentials,
    )


@router.patch("/channels/{cid}")
async def toggle_channel(cid: UUID, body: EnabledInput, request: Request, user: Admin):
    return await business(request).channels.toggle(user.tenant, user.actor, cid, body.enabled)


@router.post("/channels/{cid}/rotate-token")
async def rotate_channel(cid: UUID, request: Request, user: Admin):
    return await business(request).channels.rotate(user.tenant, user.actor, cid)


@router.get("/channels/{cid}/deliveries")
async def channel_deliveries(
    cid: UUID,
    request: Request,
    user: Reader,
    page: int = Query(default=1, ge=1),
):
    return await business(request).channels.deliveries(user.tenant, cid, page)


@router.post("/channels/{cid}/deliveries/{did}/retry")
async def retry_channel_delivery(cid: UUID, did: UUID, request: Request, user: Admin):
    return await business(request).channels.retry_delivery(user.tenant, user.actor, cid, did)


@ingress.post("/ingress/channels/{cid}/messages", status_code=202)
async def ingest(
    cid: UUID,
    body: IncomingMessage,
    request: Request,
    x_channel_token: Annotated[str, Header()],
    x_channel_timestamp: Annotated[str | None, Header()] = None,
    x_channel_signature: Annotated[str | None, Header()] = None,
):
    await business(request).channels.verify_signature(
        cid, await request.body(), x_channel_timestamp, x_channel_signature
    )
    return await business(request).channels.ingest(cid, x_channel_token, body)


@ingress.get("/ingress/channels/{cid}/replies")
async def channel_replies(
    cid: UUID,
    request: Request,
    x_channel_token: Annotated[str, Header()],
    session_id: Annotated[str, Query(min_length=1, max_length=128)],
    after: Annotated[int, Query(ge=0)] = 0,
):
    return await business(request).channels.replies(cid, x_channel_token, session_id, after)


@ingress.api_route(
    "/ingress/channels/{cid}/webhook/{provider}",
    methods=["GET", "POST"],
    status_code=200,
)
async def channel_webhook(cid: UUID, provider: str, request: Request):
    result = await business(request).channels.webhook(
        cid,
        provider,
        await request.body(),
        dict(request.query_params),
        dict(request.headers),
    )
    if result.ack is not None:
        return JSONResponse(result.ack)
    if result.challenge is not None:
        if provider == "feishu":
            return JSONResponse({"challenge": str(result.challenge)})
        return PlainTextResponse(str(result.challenge))
    if provider in {"wecom", "wecom_kf", "slack"}:
        return PlainTextResponse("")
    if provider == "dingtalk":
        return JSONResponse({"success": True})
    if provider == "feishu":
        return JSONResponse({"code": 0, "msg": "success"})
    return JSONResponse({"ok": True})


@router.get("/observability/summary")
async def summary(request: Request, user: Reader):
    return await application(request).observability.summary(user.tenant)


@router.get("/observability/gateways")
async def gateway_metrics(request: Request, user: Reader):
    return await application(request).observability.gateways(user.tenant)


@router.get("/observability/memory")
async def memory_metrics(request: Request, user: Reader):
    # Phase 4 (FR-7): extraction volume, injection hit rate, pending backlog,
    # governance/decay counters, reinforcement and memory_search telemetry.
    return await application(request).observability.memory_summary(user.tenant)


@router.get("/observability/runs/{rid}/trace")
async def unified_trace(rid: UUID, request: Request, user: Reader):
    return await application(request).observability.trace(user.tenant, rid)


@router.get("/observability/runs")
async def runs(
    request: Request,
    user: Reader,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
):
    return await application(request).observability.runs(user.tenant, page, page_size)


@router.get("/audit")
async def audit(
    request: Request,
    user: Admin,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    action_type: Annotated[str | None, Query(max_length=160)] = None,
):
    return await application(request).observability.audit(user.tenant, page, page_size, action_type)


@router.get("/agents/{aid}/evaluation-cases")
async def cases(aid: UUID, request: Request, user: Reader):
    return await application(request).evaluation.cases(user.tenant, aid)


@router.post("/agents/{aid}/evaluation-cases", status_code=201)
async def create_case(aid: UUID, body: EvaluationCase, request: Request, user: Admin):
    return await application(request).evaluation.create(user.tenant, user.actor, aid, body)


@router.get("/agents/{aid}/evaluation-cases/template")
async def evaluation_case_template(aid: UUID, request: Request, user: Reader):
    content, filename = await application(request).evaluation.template(user.tenant, aid)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Content-Length": str(len(content)),
        },
    )


@router.post("/agents/{aid}/evaluation-cases/import")
async def import_evaluation_cases(
    aid: UUID, request: Request, user: Admin, filename: str = Query("", max_length=255)
):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > EVALUATION_WORKBOOK_BYTES:
            raise DomainError("workbook_size_exceeded", 413)
    return await application(request).evaluation.import_workbook(
        user.tenant, user.actor, aid, bytes(content), filename
    )


@router.patch("/agents/{aid}/evaluation-cases/{cid}")
async def update_case(aid: UUID, cid: UUID, body: EvaluationCase, request: Request, user: Admin):
    return await application(request).evaluation.update(user.tenant, user.actor, aid, cid, body)


@router.delete("/agents/{aid}/evaluation-cases/{cid}")
async def delete_case(aid: UUID, cid: UUID, request: Request, user: Admin):
    return await application(request).evaluation.delete(user.tenant, user.actor, aid, cid)


@router.post("/agents/{aid}/evaluation-cases/{cid}/run")
async def run_case(
    aid: UUID,
    cid: UUID,
    request: Request,
    user: Admin,
    body: ScoringOptions | None = None,
):
    return await application(request).evaluation.run_case(user.tenant, user.actor, aid, cid, body)


@router.get("/agents/{aid}/evaluation-reports")
async def reports(
    aid: UUID,
    request: Request,
    user: Reader,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    agent_version: int | None = None,
):
    return await application(request).evaluation.reports(
        user.tenant, aid, page, page_size, agent_version
    )


@router.get("/agents/{aid}/evaluation-trend")
async def evaluation_trend(
    aid: UUID,
    request: Request,
    user: Reader,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await application(request).evaluation.trend(user.tenant, aid, limit)


@router.post("/agents/{aid}/evaluate")
async def evaluate(aid: UUID, request: Request, user: Admin, body: ScoringOptions | None = None):
    return await application(request).evaluation.run(user.tenant, user.actor, aid, body)


@router.get("/evaluation/overview")
async def evaluation_overview(
    request: Request,
    user: Reader,
    report_limit: Annotated[int, Query(ge=1, le=1000)] = 500,
):
    """Cross-agent quality board; replaces the per-agent picker that duplicated
    the agent-scoped evaluation tab."""
    return await application(request).evaluation.overview(user.tenant, report_limit)


@router.get("/evaluation/reviews")
async def evaluation_reviews(
    request: Request,
    user: Reader,
    status: Literal["needs_review", "error", "failed", "passed", "all"] = "needs_review",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await application(request).evaluation.reviews(user.tenant, status, page, page_size)


@router.get("/evaluation/regressions")
async def evaluation_regressions(
    request: Request,
    user: Reader,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await application(request).evaluation.regressions(user.tenant, page, page_size)


@router.get("/policy")
async def effective_policy(request: Request, user: Reader):
    settings = request.app.state.settings
    return {
        key: getattr(settings, key)
        for key in [
            "model_backend",
            "model_name",
            "max_model_rounds",
            "max_tool_calls",
            "worker_concurrency",
            "tool_allowed_hosts",
        ]
    }
