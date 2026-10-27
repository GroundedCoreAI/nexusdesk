"""Built-in capability manifests registered by the application composition root."""

from collections.abc import Mapping

from agent_platform.extension_contracts import (
    CapabilityLifecycle,
    CapabilityManifest,
    UiExtensionManifest,
    UiNavigationItem,
    UiRouteContribution,
)

from .registry import CapabilityRegistry
from .ui_registry import UiExtensionRegistry

BUILTIN_CAPABILITY_MANIFESTS: tuple[CapabilityManifest, ...] = (
    CapabilityManifest(
        id="knowledge",
        version="1.0.0",
        name="Knowledge",
        description="Knowledge ingestion and retrieval capability.",
        configuration_schema_version="v1",
        permissions=frozenset({"knowledge.read", "knowledge.manage"}),
        contributions=frozenset({"tools", "events", "ui"}),
    ),
    CapabilityManifest(
        id="customer-service",
        version="1.0.0",
        name="Customer Service",
        description="Customer conversations, tickets, and human handoff.",
        configuration_schema_version="v1",
        dependencies=("knowledge",),
        dependency_constraints={"knowledge": "^1.0.0"},
        permissions=frozenset({"ticket.read", "ticket.manage"}),
        contributions=frozenset({"tools", "policies", "events", "ui"}),
    ),
    CapabilityManifest(
        id="memory",
        version="1.0.0",
        name="Customer Memory",
        description="Customer memory extraction, retrieval, and governance.",
        configuration_schema_version="v1",
        dependencies=("knowledge", "customer-service"),
        dependency_constraints={
            "knowledge": "^1.0.0",
            "customer-service": "^1.0.0",
        },
        permissions=frozenset({"memory.read"}),
        contributions=frozenset({"tools", "events", "ui"}),
    ),
    CapabilityManifest(
        id="approval",
        version="1.0.0",
        name="Approval",
        description="Independent approval requests and decision rules.",
        configuration_schema_version="v1",
        permissions=frozenset({"approval.read", "approval.manage"}),
        contributions=frozenset({"tools", "policies", "events", "ui"}),
    ),
)


CUSTOMER_SERVICE_UI_MANIFEST = UiExtensionManifest(
    extension_id="customer-service",
    version="1.0.0",
    navigation=(
        UiNavigationItem(
            id="tickets",
            label_key="服务工单",
            path="/tickets",
            icon="ticket",
            group="customer-service",
            required_permissions=("ticket.read",),
            required_capability="customer-service",
        ),
    ),
    routes=(
        UiRouteContribution(
            id="customer-service-tickets",
            path="/tickets",
            feature="customer-service/tickets",
            required_capability="customer-service",
        ),
    ),
)

KNOWLEDGE_UI_MANIFEST = UiExtensionManifest(
    extension_id="knowledge",
    version="1.0.0",
    navigation=(
        UiNavigationItem(
            id="knowledge",
            label_key="知识库",
            path="/knowledge",
            icon="book",
            group="knowledge",
            required_permissions=("knowledge.read",),
            required_capability="knowledge",
        ),
    ),
    routes=(
        UiRouteContribution(
            id="knowledge-workspace",
            path="/knowledge",
            feature="knowledge/workspace",
            required_capability="knowledge",
        ),
    ),
)

APPROVAL_UI_MANIFEST = UiExtensionManifest(
    extension_id="approval",
    version="1.0.0",
    navigation=(
        UiNavigationItem(
            id="approvals",
            label_key="审批工作台",
            path="/approvals",
            icon="audit",
            group="approval",
            required_permissions=("approval.read",),
            required_capability="approval",
        ),
    ),
    routes=(
        UiRouteContribution(
            id="approval-workbench",
            path="/approvals",
            feature="approval/workbench",
            required_capability="approval",
        ),
    ),
)


def register_builtin_capabilities(
    registry: CapabilityRegistry,
    lifecycles: Mapping[str, CapabilityLifecycle] | None = None,
) -> None:
    """Register the capabilities shipped with the modular monolith."""

    lifecycles = lifecycles or {}
    for manifest in BUILTIN_CAPABILITY_MANIFESTS:
        registry.register(manifest, lifecycles.get(manifest.id))


def register_builtin_ui_extensions(
    registry: UiExtensionRegistry,
    contributions=None,
) -> None:
    """Register UI contributions shipped with the modular monolith."""

    for manifest in (
        CUSTOMER_SERVICE_UI_MANIFEST,
        KNOWLEDGE_UI_MANIFEST,
        APPROVAL_UI_MANIFEST,
    ):
        if contributions is None:
            registry.register(manifest)
        else:
            contributions.register_ui(manifest.extension_id, manifest)
