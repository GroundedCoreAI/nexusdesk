from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_platform.applications.customer_service.trusted_extensions import (
    register_trusted_external_bindings,
)
from agent_platform.business_capabilities.sample_operations.sample_operations import (
    SAMPLE_OPERATIONS_CAPABILITY_ID,
    SampleOperationsLifecycle,
)
from agent_platform.core_platform.extension_platform import (
    CapabilityContributionRegistry,
    CapabilityImplementationRegistry,
    CapabilityRegistry,
    UiExtensionRegistry,
    load_capability_manifest,
)
from agent_platform.core_platform.platform_services.events import InProcessEventBus
from agent_platform.extension_contracts import (
    EventEnvelope,
    ToolExecutionContext,
    ToolExecutionRequest,
)

SAMPLE_MANIFEST = (
    Path(__file__).parents[1]
    / "examples"
    / "external_plugins"
    / "sample-operations"
    / "manifest.yaml"
)


@pytest.mark.asyncio
async def test_reference_external_plugin_runs_full_lifecycle() -> None:
    platform = SimpleNamespace(event_bus=InProcessEventBus())
    implementations = CapabilityImplementationRegistry()
    register_trusted_external_bindings(implementations, platform)

    capabilities = CapabilityRegistry()
    results = capabilities.register_manifest_directory(
        SAMPLE_MANIFEST.parent,
        implementation_registry=implementations,
        require_implementation=True,
        require_contribution_binding=True,
    )
    assert [(item.capability_id, item.status) for item in results] == [
        (SAMPLE_OPERATIONS_CAPABILITY_ID, "registered")
    ]

    ui_extensions = UiExtensionRegistry()
    contributions = CapabilityContributionRegistry(capabilities, ui_extensions)
    bundle_factory = implementations.contribution_factory(SAMPLE_OPERATIONS_CAPABILITY_ID)
    assert bundle_factory is not None
    contributions.register_bundle(
        SAMPLE_OPERATIONS_CAPABILITY_ID,
        bundle_factory(platform),
    )
    contributions.validate()

    await capabilities.start_all()
    lifecycle = platform.sample_operations_lifecycle
    assert isinstance(lifecycle, SampleOperationsLifecycle)
    assert lifecycle.started is True

    contributions.attach_events(platform.event_bus)
    event = EventEnvelope(
        event_type="sample-operations.created",
        tenant_id="test-tenant",
        aggregate_type="sample-operation",
        aggregate_id="operation-1",
        idempotency_key="sample-operations.created:operation-1",
    )
    await platform.event_bus.publish(event)
    assert lifecycle.received_events == [event.idempotency_key]

    tool = contributions.tool_contributions(SAMPLE_OPERATIONS_CAPABILITY_ID)[0]
    handler = tool.handlers({}, None)[0]
    result = await handler.execute(
        ToolExecutionRequest(
            definition=handler.definition,
            context=ToolExecutionContext(
                tenant_id="test-tenant",
                source="runtime",
            ),
        )
    )
    assert result.data == {
        "started": True,
        "configured": False,
        "tenant": "test-tenant",
    }

    await capabilities.disable(SAMPLE_OPERATIONS_CAPABILITY_ID)
    contributions.attach_events(platform.event_bus)
    assert lifecycle.started is False
    assert platform.event_bus.subscribers("sample-operations.created") == ()

    await capabilities.enable(SAMPLE_OPERATIONS_CAPABILITY_ID)
    contributions.attach_events(platform.event_bus)
    assert lifecycle.started is True

    upgraded = load_capability_manifest(SAMPLE_MANIFEST).model_copy(
        update={"version": "1.1.0", "description": "Upgraded sample capability."}
    )
    contributions.validate_manifest_change(SAMPLE_OPERATIONS_CAPABILITY_ID, upgraded)
    await capabilities.upgrade(SAMPLE_OPERATIONS_CAPABILITY_ID, upgraded)
    assert capabilities.get(SAMPLE_OPERATIONS_CAPABILITY_ID).version == "1.1.0"

    await capabilities.rollback(SAMPLE_OPERATIONS_CAPABILITY_ID)
    assert capabilities.get(SAMPLE_OPERATIONS_CAPABILITY_ID).version == "1.0.0"
