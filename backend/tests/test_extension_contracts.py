import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_platform.applications.customer_service.platform_routes import _ui_manifest_payload
from agent_platform.applications.platform_runtime.runtime_composition import RuntimeServices
from agent_platform.applications.platform_runtime.runtime_factory import RuntimeFactory
from agent_platform.business_capabilities.approval.capability import ApprovalCapability
from agent_platform.business_capabilities.approval.domain import (
    ApprovalRequest,
    ApprovalTransitionEngine,
    ApprovalTransitionError,
)
from agent_platform.business_capabilities.approval.tools import (
    APPROVAL_TOOL_DEFINITIONS,
    ApprovalToolContribution,
)
from agent_platform.business_capabilities.customer_service.capability import (
    CustomerServiceCapability,
)
from agent_platform.business_capabilities.customer_service.service import CustomerService
from agent_platform.business_capabilities.customer_service.tools import (
    CUSTOMER_SERVICE_TOOL_DEFINITIONS,
)
from agent_platform.business_capabilities.knowledge.capability import KnowledgeCapability
from agent_platform.business_capabilities.knowledge.tools import KNOWLEDGE_SEARCH_TOOL
from agent_platform.business_capabilities.memory.capability import MemoryCapability
from agent_platform.business_capabilities.memory.tools import MEMORY_SEARCH_TOOL
from agent_platform.core_platform.extension_platform import (
    BUILTIN_CAPABILITY_MANIFESTS,
    CapabilityRegistry,
    ExtensionRegistryError,
    UiExtensionRegistry,
    UiExtensionRegistryError,
    register_builtin_capabilities,
    register_builtin_ui_extensions,
)
from agent_platform.core_platform.extension_platform.compatibility import version_satisfies
from agent_platform.core_platform.platform_services.events import (
    DurableEventTaskDispatcher,
    EventDeliveryError,
    InProcessEventBus,
)
from agent_platform.core_platform.platform_services.identity.access import Principal
from agent_platform.core_platform.platform_services.integrations.business_tools.platform_tools import (
    PlatformTools,
)
from agent_platform.core_platform.platform_services.integrations.business_tools.registry import (
    HttpToolHandler,
)
from agent_platform.core_platform.policy_harness.service import ExecutionPolicy
from agent_platform.core_platform.tool_gateway.harness import ToolExecutionHarness
from agent_platform.core_platform.tool_gateway.service import HttpTool
from agent_platform.extension_contracts import (
    CapabilityManifest,
    EventEnvelope,
    OperationRecord,
    PolicyDecision,
    RunRequest,
    RuntimeBindings,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    UiExtensionManifest,
    UiNavigationItem,
    UiRouteContribution,
)


def test_contract_package_has_no_business_module_dependency():
    root = Path(__file__).parents[1] / "src" / "agent_platform" / "extension_contracts"
    forbidden_imports = set()
    for source_file in root.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                forbidden_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                forbidden_imports.add(node.module)

    assert not any(
        name.startswith(
            (
                "agent_platform.business_capabilities",
                "agent_platform.core_platform",
            )
        )
        for name in forbidden_imports
    )


def test_capability_manifest_validates_identity_and_contributions():
    manifest = CapabilityManifest(
        id="customer-service",
        version="1.0.0",
        name="Customer Service",
        contributions={"tools", "events", "ui"},
    )

    assert manifest.api_version == "v1"
    assert manifest.contributions == {"tools", "events", "ui"}


def test_capability_manifest_rejects_duplicate_or_self_dependencies():
    with pytest.raises(ValidationError):
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            dependencies=("customer-service", "customer-service"),
        )

    with pytest.raises(ValidationError):
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            dependencies=("approval",),
        )


def test_extension_versions_support_semver_compatibility_constraints():
    assert version_satisfies("1.4.2", "^1.2.0")
    assert version_satisfies("0.3.4", "^0.3.0")
    assert version_satisfies("1.2.9", ">=1.0.0,<2.0.0")
    assert not version_satisfies("2.0.0", "^1.2.0")
    assert not version_satisfies("0.4.0", "^0.3.0")


def test_capability_manifest_rejects_constraints_for_unknown_dependencies():
    with pytest.raises(ValidationError, match="matching dependencies"):
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            dependency_constraints={"knowledge": "^1.0.0"},
        )


def test_extension_permissions_are_declared_and_validated():
    manifest = CapabilityManifest(
        id="approval",
        version="1.0.0",
        name="Approval",
        permissions=frozenset({"approval.read", "approval.manage"}),
    )
    assert manifest.permissions == {"approval.read", "approval.manage"}

    with pytest.raises(ValidationError, match="dotted lowercase"):
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            permissions=frozenset({"Approval.Read"}),
        )


def test_capability_contributions_cannot_escalate_manifest_permissions():
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            permissions=frozenset({"approval.read"}),
        )
    )

    with pytest.raises(ExtensionRegistryError, match="undeclared permissions"):
        registry.validate_contribution_permissions(
            "approval",
            frozenset({"approval.manage"}),
        )


def test_ui_extensions_are_filtered_by_permission():
    manifest = UiExtensionManifest(
        extension_id="approval",
        version="1.0.0",
        navigation=(
            UiNavigationItem(
                id="approval-home",
                label_key="审批",
                path="/approval",
                icon="audit",
                group="approval",
                required_permissions=("approval.manage",),
            ),
        ),
        routes=(
            UiRouteContribution(
                id="approval-home",
                path="/approval",
                feature="approval/home",
                required_permissions=("approval.manage",),
            ),
        ),
    )
    admin = Principal("tenant-a", "admin", "admin")
    viewer = Principal("tenant-a", "viewer", "viewer")

    assert _ui_manifest_payload(manifest, admin)["extensionId"] == "approval"
    assert _ui_manifest_payload(manifest, viewer) is None


def test_ui_manifest_exposes_api_and_platform_compatibility():
    manifest = UiExtensionManifest(
        extension_id="approval",
        version="1.0.0",
        api_version="v1",
        requires_platform=">=0.1.0,<1.0.0",
    )

    assert manifest.api_version == "v1"
    assert manifest.requires_platform == ">=0.1.0,<1.0.0"


def test_tool_execution_contract_keeps_trusted_context_separate():
    definition = ToolDefinition(
        name="approve_request",
        description="Approve a pending request.",
        parameters={"type": "object", "additionalProperties": False},
        capability="approval",
        risk="write",
    )
    request = ToolExecutionRequest(
        definition=definition,
        context=ToolExecutionContext(
            tenant_id="tenant-a",
            source="application",
            actor_id="staff-1",
        ),
        arguments={},
    )

    assert request.context.tenant_id == "tenant-a"
    assert request.definition.capability == "approval"
    assert request.definition.risk == "write"


def test_policy_decision_exposes_confirmation_and_constraints():
    decision = PolicyDecision(
        effect="allow",
        reason_code="requires_approval",
        risk="proposal",
        confirmation={"required": True, "action": "approve"},
        constraint={"idempotency_required": True, "max_attempts": 2},
    )

    assert decision.allowed
    assert decision.confirmation.required
    assert decision.constraint.idempotency_required


def test_event_envelope_requires_timezone_and_idempotency():
    event = EventEnvelope(
        event_type="approval.requested",
        tenant_id="tenant-a",
        aggregate_type="approval",
        aggregate_id="request-1",
        idempotency_key="approval:request-1:requested",
        payload={"state": "pending"},
    )

    assert event.occurred_at.tzinfo == UTC
    assert event.event_version == 1

    with pytest.raises(ValidationError):
        EventEnvelope(
            event_type="approval.requested",
            tenant_id="tenant-a",
            aggregate_type="approval",
            aggregate_id="request-1",
            idempotency_key="approval:request-1:requested",
            occurred_at=datetime(2026, 10, 27, tzinfo=UTC).replace(tzinfo=None),
        )


def test_runtime_request_is_business_neutral():
    request = RunRequest(
        tenant_id="tenant-a",
        conversation_id=uuid4(),
        input="Please check this request.",
        config={"agent_version": 3},
        idempotency_key="conversation:1:message:2",
    )

    assert request.input.startswith("Please")
    assert request.config == {"agent_version": 3}


def test_runtime_bindings_expose_only_the_explicit_port_bundle():
    bindings = RuntimeBindings(
        engine=object(),
        settings=object(),
        snapshot={"fingerprint": "test"},
        tools=object(),
        policy=object(),
        retrieval=object(),
        customer=object(),
        memory_store=object(),
        gateway=object(),
        ledger=object(),
    )

    assert bindings.snapshot == {"fingerprint": "test"}
    assert bindings.ledger is not None
    assert not hasattr(bindings, "observability")


def test_operation_record_is_database_schema_neutral():
    record = OperationRecord(
        id=uuid4(),
        tenant_id="tenant-a",
        run_id=uuid4(),
        tool_name="knowledge_search",
        adapter_type="builtin",
        effect="read",
        status="succeeded",
        duration_ms=12,
    )

    assert record.error_code is None
    assert record.duration_ms == 12


@pytest.mark.asyncio
async def test_policy_adapter_returns_normalized_tool_decision():
    class Registry:
        async def enabled(self, tenant, name):
            return True

    decision = await ExecutionPolicy(Registry()).evaluate_tool(
        ToolExecutionContext(
            tenant_id="tenant-a",
            run_id=uuid4(),
            conversation_id=uuid4(),
            source="runtime",
        ),
        "propose_ticket",
        ["propose_ticket"],
        "proposal",
    )

    assert decision.allowed
    assert decision.risk == "proposal"
    assert decision.confirmation.required


@pytest.mark.asyncio
async def test_http_tool_handler_uses_the_common_execution_result():
    class Gateway:
        async def execute(self, name, arguments):
            return {"ok": True, "data": {"name": name, "arguments": arguments}}

    spec = HttpTool(
        name="order_lookup",
        description="Look up an order.",
        url="https://example.test/order",
        parameters={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    )
    handler = HttpToolHandler(Gateway(), spec)
    result = await handler.execute(
        ToolExecutionRequest(
            definition=handler.definition,
            context=ToolExecutionContext(tenant_id="tenant-a", source="runtime"),
            arguments={"order_id": "A-1"},
        )
    )

    assert result.status == "succeeded"
    assert result.data["name"] == "order_lookup"
    assert handler.definition.capability == "external-tool"


@pytest.mark.asyncio
async def test_execution_harness_applies_confirmation_and_idempotency_constraints():
    class Handler:
        async def execute(self, request):
            return ToolExecutionResult(status="succeeded", data={"ok": True})

    definition = ToolDefinition(
        name="write_order",
        description="Write an order.",
        parameters={"type": "object", "additionalProperties": False},
        capability="external-tool",
        risk="write",
    )
    request = ToolExecutionRequest(
        definition=definition,
        context=ToolExecutionContext(tenant_id="tenant-a", source="runtime"),
    )
    harness = ToolExecutionHarness()

    missing_key = await harness.execute(
        Handler(),
        request,
        PolicyDecision(
            effect="allow",
            reason_code="authorized",
            risk="write",
            constraint={"idempotency_required": True},
        ),
    )
    assert missing_key.error_code == "idempotency_key_required"

    proposal = await harness.execute(
        Handler(),
        request.model_copy(update={"idempotency_key": "runtime:test"}),
        PolicyDecision(
            effect="allow",
            reason_code="authorized",
            risk="proposal",
            confirmation={"required": True, "action": "confirm_tool"},
        ),
    )
    assert proposal.status == "requires_confirmation"


@pytest.mark.asyncio
async def test_execution_harness_gates_effectful_writes_before_the_handler_runs():
    """A confirmation on write/irreversible risk blocks the call, not just the label.

    The harness previously ran the handler and then relabelled a succeeded result,
    so a write policy that required confirmation still performed the write while
    reporting "awaiting confirmation".
    """

    calls: list[str] = []

    class Handler:
        async def execute(self, request):
            calls.append(request.definition.name)
            return ToolExecutionResult(status="succeeded", data={"written": True})

    definition = ToolDefinition(
        name="write_order",
        description="Write an order.",
        parameters={"type": "object", "additionalProperties": False},
        capability="external-tool",
        risk="write",
    )
    request = ToolExecutionRequest(
        definition=definition,
        context=ToolExecutionContext(tenant_id="tenant-a", source="runtime"),
        idempotency_key="runtime:test",
    )
    harness = ToolExecutionHarness()

    gated = await harness.execute(
        Handler(),
        request,
        PolicyDecision(
            effect="allow",
            reason_code="authorized",
            risk="write",
            confirmation={"required": True, "action": "confirm_tool"},
        ),
    )
    assert gated.status == "requires_confirmation"
    assert calls == []

    # Without a confirmation requirement the handler runs normally.
    direct = await harness.execute(
        Handler(),
        request,
        PolicyDecision(effect="allow", reason_code="authorized", risk="write"),
    )
    assert direct.status == "succeeded"
    assert calls == ["write_order"]


@pytest.mark.asyncio
async def test_gated_write_is_reported_as_requires_confirmation_not_succeeded():
    """A write that never ran must not be audited or reported as a success."""

    ran: list[str] = []

    class WriteHandler:
        definition = ToolDefinition(
            name="write_thing",
            description="Write a thing.",
            parameters={"type": "object", "additionalProperties": False},
            capability="demo",
            risk="write",
            idempotent=True,
        )

        async def execute(self, request):
            ran.append(request.definition.name)
            return ToolExecutionResult(status="succeeded", data={"written": True})

    class Contribution:
        def handlers(self, row, emit):
            return (WriteHandler(),)

    class GatedPolicy:
        async def evaluate_tool(self, context, name, allowed, risk="read"):
            return PolicyDecision(
                effect="allow",
                reason_code="authorized",
                risk="write",
                confirmation={"required": True, "action": "confirm_tool"},
            )

    class Http:
        def __init__(self):
            self.schemas: list[object] = []
            self.specs: dict[str, object] = {}

    row = {
        "id": str(uuid4()),
        "tenant_id": "tenant-a",
        "conversation_id": str(uuid4()),
        "config": {"agent": {"config": {}}},
    }
    tools = PlatformTools(
        Http(),
        RuntimeBindings(policy=GatedPolicy(), tool_contributions=(Contribution(),)),
        row,
        ["write_thing"],
        [],
        None,
    )

    result = await tools.execute("write_thing", {})

    assert result["execution_status"] == "requires_confirmation"
    # Nothing ran, so the model must not be told it succeeded. Unlike a proposal
    # (whose pending record does exist), a gated write reports ok=False plus a
    # code the caller can act on.
    assert result["ok"] is False
    assert result["error"] == "confirmation_required"
    # The contract status is consumed by the adapter, never leaked to the model.
    assert "_contract_status" not in result
    assert ran == []


def test_runtime_factory_lives_in_shared_platform_runtime_module():
    assert RuntimeFactory.__module__ == "agent_platform.applications.platform_runtime.runtime_factory"


def test_ui_manifest_contains_serializable_contributions():
    manifest = UiExtensionManifest(
        extension_id="customer-service",
        version="1.0.0",
        navigation=(
            UiNavigationItem(
                id="tickets",
                label_key="客服工单",
                path="/tickets",
                icon="ticket",
                group="customer-service",
            ),
        ),
    )

    assert manifest.navigation[0].path == "/tickets"


def test_ui_registry_validates_compatibility_and_navigation_routes():
    registry = UiExtensionRegistry(platform_version="0.1.0")
    with pytest.raises(UiExtensionRegistryError, match="unsupported UI extension API"):
        registry.register(
            UiExtensionManifest(extension_id="legacy", version="1.0.0", api_version="v2")
        )
    with pytest.raises(UiExtensionRegistryError, match="unsupported platform"):
        registry.register(
            UiExtensionManifest(
                extension_id="future",
                version="1.0.0",
                requires_platform=">=2.0.0",
            )
        )
    with pytest.raises(UiExtensionRegistryError, match="matching route"):
        registry.register(
            UiExtensionManifest(
                extension_id="broken",
                version="1.0.0",
                navigation=(
                    UiNavigationItem(
                        id="broken-home",
                        label_key="Broken",
                        path="/broken",
                        icon="app",
                        group="broken",
                    ),
                ),
            )
        )


def test_customer_service_owns_its_tool_contributions():
    assert {
        name: definition.capability
        for name, definition in CUSTOMER_SERVICE_TOOL_DEFINITIONS.items()
    } == {
        "ticket_lookup": "customer-service",
        "propose_ticket": "customer-service",
    }
    assert CUSTOMER_SERVICE_TOOL_DEFINITIONS["propose_ticket"].risk == "proposal"


def test_knowledge_capability_owns_the_agent_search_tool():
    assert KNOWLEDGE_SEARCH_TOOL.name == "knowledge_search"
    assert KNOWLEDGE_SEARCH_TOOL.capability == "knowledge"
    assert KNOWLEDGE_SEARCH_TOOL.risk == "read"


def test_memory_capability_owns_the_memory_search_tool():
    assert MEMORY_SEARCH_TOOL.name == "memory_search"
    assert MEMORY_SEARCH_TOOL.capability == "memory"
    assert MEMORY_SEARCH_TOOL.risk == "read"


class _Lifecycle:
    def __init__(self, events: list[str], name: str) -> None:
        self.events = events
        self.name = name

    async def start(self) -> None:
        self.events.append(f"start:{self.name}")

    async def stop(self) -> None:
        self.events.append(f"stop:{self.name}")


class _ConfigLifecycle(_Lifecycle):
    def __init__(self, events: list[str], name: str) -> None:
        super().__init__(events, name)
        self.config: dict[str, object] = {}

    async def configure(self, config: dict[str, object]) -> None:
        self.config = config
        self.events.append(f"configure:{self.name}:{config['mode']}")


@pytest.mark.asyncio
async def test_capability_registry_validates_dependencies_and_lifecycle_order():
    events: list[str] = []
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(
            id="customer-service",
            version="1.0.0",
            name="Customer Service",
        ),
        _Lifecycle(events, "customer-service"),
    )
    registry.register(
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            dependencies=("customer-service",),
        ),
        _Lifecycle(events, "approval"),
    )

    started = await registry.start_all()
    stopped = await registry.stop_all()

    assert events == [
        "start:customer-service",
        "start:approval",
        "stop:approval",
        "stop:customer-service",
    ]
    assert all(item.status == "stopped" for item in stopped)
    assert {item.status for item in started} == {"ready"}


@pytest.mark.asyncio
async def test_capability_registry_injects_active_config_at_start_and_runtime_update():
    events: list[str] = []
    lifecycle = _ConfigLifecycle(events, "approval")
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            configuration_schema_version="v1",
        ),
        lifecycle,
    )
    initial = registry.configure("approval", {"mode": "safe"}, "admin")

    await registry.start_all()
    assert lifecycle.config == {"mode": "safe"}
    assert events[:2] == ["configure:approval:safe", "start:approval"]

    updated = initial.model_copy(
        update={
            "version": 2,
            "config": {"mode": "fast"},
            "created_by": "admin",
        }
    )
    await registry.activate_config_version(updated)
    assert lifecycle.config == {"mode": "fast"}
    assert events[-1] == "configure:approval:fast"


@pytest.mark.asyncio
async def test_capability_registry_can_enable_disable_upgrade_and_rollback():
    events: list[str] = []
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(id="knowledge", version="1.0.0", name="Knowledge"),
        _Lifecycle(events, "knowledge-v1"),
    )
    registry.register(
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            dependencies=("knowledge",),
        ),
        _Lifecycle(events, "approval-v1"),
    )

    await registry.start_all()
    with pytest.raises(ExtensionRegistryError, match="enabled dependents"):
        await registry.disable("knowledge")

    disabled = await registry.disable("approval")
    assert disabled.enabled is False
    assert disabled.status == "stopped"
    enabled = await registry.enable("approval")
    assert enabled.enabled is True
    assert enabled.status == "ready"

    upgraded = await registry.upgrade(
        "approval",
        CapabilityManifest(
            id="approval",
            version="2.0.0",
            name="Approval v2",
            dependencies=("knowledge",),
            dependency_constraints={"knowledge": "^1.0.0"},
        ),
        _Lifecycle(events, "approval-v2"),
    )
    assert upgraded.version == "2.0.0"
    assert upgraded.status == "ready"

    rolled_back = await registry.rollback("approval")
    assert rolled_back.version == "1.0.0"
    assert rolled_back.status == "ready"
    assert events[-4:] == [
        "stop:approval-v1",
        "start:approval-v2",
        "stop:approval-v2",
        "start:approval-v1",
    ]


def test_capability_registry_versions_configuration_and_rolls_back_a_snapshot():
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(
            id="approval",
            version="1.0.0",
            name="Approval",
            configuration_schema_version="v1",
        )
    )

    first = registry.configure("approval", {"retention_days": 30}, "admin")
    second = registry.configure("approval", {"retention_days": 60}, "admin")
    restored = registry.rollback_config("approval", first.version, "admin")

    assert first.version == 1
    assert second.version == 2
    assert restored.version == 3
    assert restored.rollback_of == 1
    assert restored.config == {"retention_days": 30}
    assert registry.config("approval") == restored
    assert registry.get("approval").config_version == 3
    assert [item.version for item in registry.config_versions("approval")] == [1, 2, 3]

    with pytest.raises(ExtensionRegistryError, match="configuration schema"):
        registry.configure("approval", {}, "admin", schema_version="v2")
    with pytest.raises(ExtensionRegistryError, match="must be JSON"):
        registry.configure("approval", {"bad": {1, 2}}, "admin")


def test_capability_registry_hydrates_durable_configuration_history():
    source = CapabilityRegistry()
    manifest = CapabilityManifest(
        id="approval",
        version="1.0.0",
        name="Approval",
        configuration_schema_version="v1",
    )
    source.register(manifest)
    source.configure("approval", {"retention_days": 30}, "admin")
    source.configure("approval", {"retention_days": 60}, "admin")

    hydrated = CapabilityRegistry()
    hydrated.register(manifest)
    for snapshot in source.config_versions("approval"):
        hydrated.load_config_version(snapshot)

    assert hydrated.config("approval").config == {"retention_days": 60}
    assert hydrated.get("approval").config_version == 2


@pytest.mark.asyncio
async def test_capability_upgrade_without_lifecycle_keeps_installed_runtime_hook():
    events: list[str] = []
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(id="approval", version="1.0.0", name="Approval"),
        _Lifecycle(events, "approval-v1"),
    )
    await registry.start_all()

    upgraded = await registry.upgrade(
        "approval",
        CapabilityManifest(id="approval", version="2.0.0", name="Approval v2"),
    )

    assert upgraded.status == "ready"
    assert events == [
        "start:approval-v1",
        "stop:approval-v1",
        "start:approval-v1",
    ]


@pytest.mark.asyncio
async def test_capability_rollback_failure_restores_current_version_and_history():
    events: list[str] = []

    class ToggleLifecycle(_Lifecycle):
        def __init__(self, events: list[str], name: str) -> None:
            super().__init__(events, name)
            self.fail_start = False

        async def start(self) -> None:
            events.append(f"start:{self.name}")
            if self.fail_start:
                raise RuntimeError("rollback_version_unavailable")

    v1 = ToggleLifecycle(events, "approval-v1")
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(id="approval", version="1.0.0", name="Approval"),
        v1,
    )
    await registry.start_all()
    await registry.upgrade(
        "approval",
        CapabilityManifest(id="approval", version="2.0.0", name="Approval v2"),
        _Lifecycle(events, "approval-v2"),
    )
    assert registry.get("approval").status == "ready"
    v1.fail_start = True

    with pytest.raises(ExtensionRegistryError, match="rollback failed to start"):
        await registry.rollback("approval")

    current = registry.get("approval")
    assert current.version == "2.0.0"
    assert current.status == "ready"
    assert current.enabled is True
    assert registry.observability()["summary"]["total"] == 1


@pytest.mark.asyncio
async def test_capability_registry_rejects_duplicate_and_missing_dependencies():
    registry = CapabilityRegistry()
    manifest = CapabilityManifest(id="knowledge", version="1.0.0", name="Knowledge")
    registry.register(manifest)

    with pytest.raises(ExtensionRegistryError):
        registry.register(manifest)

    broken = CapabilityRegistry()
    with pytest.raises(ExtensionRegistryError, match="missing capability dependency"):
        broken.register(
            CapabilityManifest(
                id="approval",
                version="1.0.0",
                name="Approval",
                dependencies=("customer-service",),
            )
        )


def test_builtin_capabilities_are_registered_from_manifests():
    registry = CapabilityRegistry()
    register_builtin_capabilities(registry)

    assert tuple(item.capability_id for item in registry.list()) == (
        "approval",
        "customer-service",
        "knowledge",
        "memory",
    )
    assert registry.get("customer-service").status == "registered"
    assert next(
        manifest for manifest in BUILTIN_CAPABILITY_MANIFESTS if manifest.id == "customer-service"
    ).dependencies == ("knowledge",)
    assert next(
        manifest for manifest in BUILTIN_CAPABILITY_MANIFESTS if manifest.id == "customer-service"
    ).dependency_constraints == {"knowledge": "^1.0.0"}


@pytest.mark.asyncio
async def test_capability_registry_starts_dependencies_before_dependents():
    events: list[str] = []
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(id="knowledge", version="1.0.0", name="Knowledge"),
        _Lifecycle(events, "knowledge"),
    )
    registry.register(
        CapabilityManifest(
            id="customer-service",
            version="1.0.0",
            name="Customer Service",
            dependencies=("knowledge",),
        ),
        _Lifecycle(events, "customer-service"),
    )

    await registry.start_all()

    assert events == ["start:knowledge", "start:customer-service"]


@pytest.mark.asyncio
async def test_capability_registry_degrades_dependents_when_dependency_start_fails():
    events: list[str] = []

    class FailingLifecycle(_Lifecycle):
        async def start(self) -> None:
            events.append(f"start:{self.name}")
            raise RuntimeError("knowledge_unavailable")

    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(id="knowledge", version="1.0.0", name="Knowledge"),
        FailingLifecycle(events, "knowledge"),
    )
    registry.register(
        CapabilityManifest(
            id="customer-service",
            version="1.0.0",
            name="Customer Service",
            dependencies=("knowledge",),
        ),
        _Lifecycle(events, "customer-service"),
    )

    statuses = await registry.start_all()

    assert events == ["start:knowledge"]
    assert registry.get("knowledge").status == "degraded"
    assert registry.get("knowledge").reason == "knowledge_unavailable"
    assert registry.get("customer-service").status == "degraded"
    assert registry.get("customer-service").reason == "dependency_not_ready:knowledge"
    assert {item.status for item in statuses} == {"degraded"}


@pytest.mark.asyncio
async def test_customer_service_capability_lifecycle_registers_and_removes_event_subscriber():
    registry = CapabilityRegistry()
    event_bus = InProcessEventBus()
    register_builtin_capabilities(
        registry,
        {"customer-service": CustomerServiceCapability(event_bus)},
    )

    await registry.start_all()
    subscribers = event_bus.subscribers("ticket.created")
    assert subscribers
    assert registry.get("customer-service").status == "ready"

    await event_bus.publish(
        EventEnvelope(
            event_type="ticket.created",
            tenant_id="tenant-a",
            aggregate_type="ticket",
            aggregate_id="ticket-1",
            idempotency_key="ticket.created:tenant-a:ticket-1",
        )
    )
    assert subscribers[0].counts["ticket.created"] == 1

    await registry.stop_all()
    assert not event_bus.subscribers("ticket.created")


@pytest.mark.asyncio
async def test_knowledge_capability_lifecycle_receives_retrieval_events():
    event_bus = InProcessEventBus()
    capability = KnowledgeCapability(event_bus)
    await capability.start()

    event = EventEnvelope(
        event_type="knowledge.retrieved",
        tenant_id="tenant-a",
        aggregate_type="knowledge-search",
        aggregate_id="run-1",
        idempotency_key="knowledge.retrieved:run-1",
    )
    await event_bus.publish(event)

    assert capability.projection.counts["knowledge.retrieved"] == 1
    assert capability.projection.last_event == event
    await capability.stop()


@pytest.mark.asyncio
async def test_memory_capability_lifecycle_receives_cross_capability_events():
    event_bus = InProcessEventBus()
    capability = MemoryCapability(event_bus)
    await capability.start()

    for event_type in (
        "ticket.created",
        "knowledge.retrieved",
        "memory.search.completed",
    ):
        await event_bus.publish(
            EventEnvelope(
                event_type=event_type,
                tenant_id="tenant-a",
                aggregate_type="customer-memory",
                aggregate_id="customer-1",
                idempotency_key=f"{event_type}:customer-1",
            )
        )

    assert capability.projection.counts["ticket.created"] == 1
    assert capability.projection.counts["knowledge.retrieved"] == 1
    assert capability.projection.counts["memory.search.completed"] == 1

    await capability.stop()
    assert not event_bus.subscribers("ticket.created")
    assert not event_bus.subscribers("knowledge.retrieved")
    assert not event_bus.subscribers("memory.search.completed")


def test_approval_domain_keeps_state_rules_out_of_runtime():
    request = ApprovalRequest(
        tenant_id="tenant-a",
        title="Release production change",
        requested_by="operator-1",
    )
    engine = ApprovalTransitionEngine()

    pending = engine.transition(request, "submit", "operator-1")
    assert pending.status == "pending"
    assert pending.revision == 2

    with pytest.raises(ApprovalTransitionError, match="separation_of_duties"):
        engine.transition(pending, "approve", "operator-1")

    approved = engine.transition(pending, "approve", "reviewer-1")
    assert approved.status == "approved"
    assert approved.revision == 3

    with pytest.raises(ApprovalTransitionError, match="invalid_transition"):
        engine.transition(approved, "cancel", "reviewer-1")


def test_approval_tools_use_the_shared_tool_contract():
    assert set(APPROVAL_TOOL_DEFINITIONS) == {
        "approval_lookup",
        "submit_approval",
        "decide_approval",
    }
    assert APPROVAL_TOOL_DEFINITIONS["submit_approval"].capability == "approval"
    assert APPROVAL_TOOL_DEFINITIONS["decide_approval"].risk == "write"
    assert APPROVAL_TOOL_DEFINITIONS["decide_approval"].idempotent


def test_approval_tools_are_bound_as_a_runtime_contribution():
    contribution = ApprovalToolContribution(object())
    handlers = contribution.handlers({"id": str(uuid4())}, None)

    assert {handler.definition.name for handler in handlers} == {
        "approval_lookup",
        "submit_approval",
        "decide_approval",
    }


@pytest.mark.asyncio
async def test_decide_approval_tool_forwards_revision_to_service():
    approval_id = uuid4()
    captured: dict[str, object] = {}

    class FakeApprovalService:
        async def decide(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return {"id": approval_id, "status": "approved"}

    contribution = ApprovalToolContribution(FakeApprovalService())
    handler = next(
        handler
        for handler in contribution.handlers({"id": str(uuid4())}, None)
        if handler.definition.name == "decide_approval"
    )
    request = ToolExecutionRequest(
        definition=handler.definition,
        context=ToolExecutionContext(
            tenant_id="tenant-a",
            actor_id="reviewer-1",
            source="runtime",
            business_id="customer-service",
            workspace_id="default",
        ),
        arguments={
            "request_id": str(approval_id),
            "decision": "approve",
            "revision": 2,
        },
    )

    result = await handler.execute(request)

    assert result.status == "succeeded"
    assert result.data == {"id": approval_id, "status": "approved"}
    assert captured["args"] == (
        "tenant-a",
        "reviewer-1",
        approval_id,
        "approve",
        2,
    )
    assert captured["kwargs"]["scope"].tenant_id == "tenant-a"
    assert captured["kwargs"]["scope"].business_id == "customer-service"
    assert captured["kwargs"]["scope"].workspace_id == "default"


@pytest.mark.asyncio
async def test_approval_capability_lifecycle_is_independent_from_customer_service():
    event_bus = InProcessEventBus()
    capability = ApprovalCapability(event_bus)
    await capability.start()

    event = EventEnvelope(
        event_type="approval.requested",
        tenant_id="tenant-a",
        aggregate_type="approval",
        aggregate_id="request-1",
        idempotency_key="approval.requested:request-1",
    )
    await event_bus.publish(event)
    await event_bus.publish(event)

    assert capability.projection.counts["approval.requested"] == 1
    assert event_bus.subscribers("approval.requested")

    await capability.stop()
    assert not event_bus.subscribers("approval.requested")


def test_builtin_ui_extensions_are_registered_through_the_ui_contract():
    registry = UiExtensionRegistry()
    register_builtin_ui_extensions(registry)

    manifest = registry.get("customer-service")
    assert manifest is not None
    assert manifest.navigation[0].path == "/tickets"
    assert manifest.navigation[0].required_capability == "customer-service"
    payload = _ui_manifest_payload(manifest)
    assert payload["extensionId"] == "customer-service"
    assert payload["apiVersion"] == "v1"
    assert payload["navigation"][0]["labelKey"] == "服务工单"
    assert payload["routes"][0]["feature"] == "customer-service/tickets"

    approval = registry.get("approval")
    assert approval is not None
    assert approval.navigation[0].path == "/approvals"
    assert approval.navigation[0].required_capability == "approval"
    assert approval.routes[0].feature == "approval/workbench"

    with pytest.raises(UiExtensionRegistryError):
        register_builtin_ui_extensions(registry)


@pytest.mark.asyncio
async def test_capability_registry_does_not_stop_a_lifecycle_that_never_started():
    events: list[str] = []

    class FailingLifecycle(_Lifecycle):
        async def start(self) -> None:
            events.append(f"start:{self.name}")
            raise RuntimeError("startup_failed")

    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(id="knowledge", version="1.0.0", name="Knowledge"),
        FailingLifecycle(events, "knowledge"),
    )

    await registry.start_all()
    await registry.stop_all()

    assert events == ["start:knowledge"]
    assert registry.get("knowledge").status == "stopped"


def test_runtime_services_exposes_extension_registry():
    assert "extensions" in RuntimeServices.__annotations__
    assert "ui_extensions" in RuntimeServices.__annotations__
    assert "events" in RuntimeServices.__annotations__


@pytest.mark.asyncio
async def test_in_process_event_bus_delivers_each_idempotency_key_once():
    events: list[EventEnvelope] = []

    class Subscriber:
        async def handle(self, event: EventEnvelope) -> None:
            events.append(event)

    bus = InProcessEventBus()
    bus.subscribe("ticket.created", Subscriber())
    event = EventEnvelope(
        event_type="ticket.created",
        tenant_id="tenant-a",
        aggregate_type="ticket",
        aggregate_id="ticket-1",
        idempotency_key="ticket.created:tenant-a:ticket-1",
    )

    await bus.publish(event)
    await bus.publish(event)

    assert events == [event]


@pytest.mark.asyncio
async def test_in_process_event_bus_isolates_subscriber_failures():
    received: list[EventEnvelope] = []

    class BrokenSubscriber:
        async def handle(self, event: EventEnvelope) -> None:
            raise RuntimeError("subscriber_failed")

    class HealthySubscriber:
        async def handle(self, event: EventEnvelope) -> None:
            received.append(event)

    bus = InProcessEventBus()
    bus.subscribe("ticket.created", BrokenSubscriber())
    bus.subscribe("ticket.created", HealthySubscriber())
    event = EventEnvelope(
        event_type="ticket.created",
        tenant_id="tenant-a",
        aggregate_type="ticket",
        aggregate_id="ticket-1",
        idempotency_key="ticket.created:tenant-a:ticket-1:failure-isolation",
    )

    await bus.publish(event)

    assert received == [event]
    assert bus.failures() == (
        {
            "event_type": "ticket.created",
            "idempotency_key": event.idempotency_key,
            "subscriber": "BrokenSubscriber",
            "error_type": "RuntimeError",
        },
    )


@pytest.mark.asyncio
async def test_in_process_event_bus_retries_failed_delivery_without_duplicate_projection():
    event_bus = InProcessEventBus()
    capability = MemoryCapability(event_bus)
    await capability.start()
    attempts = 0

    class FlakySubscriber:
        async def handle(self, event: EventEnvelope) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary_failure")

    event_bus.subscribe("memory.search.completed", FlakySubscriber())
    event = EventEnvelope(
        event_type="memory.search.completed",
        tenant_id="tenant-a",
        aggregate_type="customer-memory",
        aggregate_id="customer-1",
        idempotency_key="memory.search.completed:retry",
    )

    await event_bus.publish(event)
    await event_bus.publish(event)

    assert attempts == 2
    assert capability.projection.counts["memory.search.completed"] == 1
    assert len(event_bus.failures()) == 1


@pytest.mark.asyncio
async def test_durable_event_task_dispatcher_delivers_serialized_event():
    event_bus = InProcessEventBus()
    capability = MemoryCapability(event_bus)
    await capability.start()
    dispatcher = DurableEventTaskDispatcher(event_bus)
    event = EventEnvelope(
        event_type="memory.search.completed",
        tenant_id="tenant-a",
        aggregate_type="customer-memory",
        aggregate_id="customer-1",
        idempotency_key="memory.search.completed:task",
    )

    result = await dispatcher.execute({"payload": {"event": event.model_dump(mode="json")}})

    assert result == "done"
    assert capability.projection.counts["memory.search.completed"] == 1


@pytest.mark.asyncio
async def test_durable_event_task_dispatcher_raises_for_retryable_delivery_failure():
    class BrokenSubscriber:
        async def handle(self, event: EventEnvelope) -> None:
            raise RuntimeError("subscriber_failed")

    event_bus = InProcessEventBus()
    event_bus.subscribe("memory.search.completed", BrokenSubscriber())
    dispatcher = DurableEventTaskDispatcher(event_bus)
    event = EventEnvelope(
        event_type="memory.search.completed",
        tenant_id="tenant-a",
        aggregate_type="customer-memory",
        aggregate_id="customer-1",
        idempotency_key="memory.search.completed:task-failed",
    )

    with pytest.raises(EventDeliveryError, match="subscriber_failed"):
        await dispatcher.execute({"payload": {"event": event.model_dump(mode="json")}})


@pytest.mark.asyncio
async def test_builtin_capabilities_start_in_dependency_order_with_lifecycles():
    event_bus = InProcessEventBus()
    registry = CapabilityRegistry()
    register_builtin_capabilities(
        registry,
        {
            "knowledge": KnowledgeCapability(event_bus),
            "customer-service": CustomerServiceCapability(event_bus),
            "memory": MemoryCapability(event_bus),
        },
    )

    started = await registry.start_all()

    assert {item.status for item in started} == {"ready"}
    assert event_bus.subscribers("knowledge.retrieved")
    assert event_bus.subscribers("ticket.created")
    assert event_bus.subscribers("memory.search.completed")

    await registry.stop_all()


@pytest.mark.asyncio
async def test_capability_registry_exposes_operational_status():
    registry = CapabilityRegistry()
    registry.register(
        CapabilityManifest(id="knowledge", version="1.0.0", name="Knowledge"),
        _Lifecycle([], "knowledge"),
    )

    await registry.start_all()
    status = registry.observability()

    assert status["summary"] == {
        "total": 1,
        "by_status": {
            "registered": 0,
            "starting": 0,
            "ready": 1,
            "degraded": 0,
            "stopped": 0,
        },
        "failures": 0,
    }
    assert status["items"][0]["status"] == "ready"
    assert status["items"][0]["last_started_at"] is not None


@pytest.mark.asyncio
async def test_customer_service_publishes_ticket_events_through_the_contract():
    events: list[EventEnvelope] = []

    class Publisher:
        async def publish(self, event: EventEnvelope) -> None:
            events.append(event)

    service = object.__new__(CustomerService)
    service.events = Publisher()

    await service._publish_ticket_event(
        "ticket.status_changed",
        "tenant-a",
        "ticket-1",
        {"old_status": "open", "new_status": "resolved"},
        "ticket.status_changed:tenant-a:ticket-1:2",
    )

    assert events[0].aggregate_type == "ticket"
    assert events[0].aggregate_id == "ticket-1"
    assert events[0].payload["new_status"] == "resolved"
