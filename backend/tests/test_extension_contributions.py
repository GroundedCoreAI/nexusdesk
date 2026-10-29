import pytest

from agent_platform.core_platform.extension_platform import (
    CapabilityContributionError,
    CapabilityContributionRegistry,
    CapabilityRegistry,
    EventSubscription,
    UiExtensionRegistry,
)
from agent_platform.core_platform.platform_services.events import InProcessEventBus
from agent_platform.core_platform.policy_harness.service import ExecutionPolicy
from agent_platform.extension_contracts import (
    CapabilityManifest,
    ConfirmationRequirement,
    EventEnvelope,
    PolicyContext,
    PolicyDecision,
    ToolDefinition,
    ToolExecutionContext,
    UiExtensionManifest,
    UiNavigationItem,
    UiRouteContribution,
)


class _ToolContribution:
    def handlers(self, row, emit):
        return ()


class _Subscriber:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    async def handle(self, event: EventEnvelope) -> None:
        self.events.append(event)


class _Policy:
    async def evaluate(
        self,
        context: PolicyContext,
        capability: str,
        action: str,
        risk: str,
    ) -> PolicyDecision:
        assert context.tenant_id == "tenant-a"
        assert capability == "sample"
        assert action == "sample_tool"
        return PolicyDecision(
            effect="allow",
            reason_code="sample_confirmation",
            risk=risk,
            confirmation=ConfirmationRequirement(required=True, action="review_sample"),
        )


def _registry() -> tuple[CapabilityRegistry, CapabilityContributionRegistry]:
    capabilities = CapabilityRegistry()
    capabilities.register(
        CapabilityManifest(
            id="sample",
            version="1.0.0",
            name="Sample",
            permissions=frozenset({"sample.read", "sample.manage"}),
            contributions=frozenset({"tools", "events", "policies", "ui"}),
        )
    )
    return capabilities, CapabilityContributionRegistry(
        capabilities,
        UiExtensionRegistry(),
    )


def _ui_manifest() -> UiExtensionManifest:
    return UiExtensionManifest(
        extension_id="sample",
        version="1.0.0",
        navigation=(
            UiNavigationItem(
                id="sample-home",
                label_key="sample.home",
                path="/sample",
                icon="app",
                group="sample",
                required_permissions=("sample.read",),
            ),
        ),
        routes=(
            UiRouteContribution(
                id="sample-home",
                path="/sample",
                feature="sample/home",
            ),
        ),
    )


def test_contribution_registry_registers_and_observes_all_extension_kinds():
    _, contributions = _registry()
    subscriber = _Subscriber()

    contributions.register_tool("sample", _ToolContribution())
    contributions.register_event(
        "sample",
        EventSubscription("sample.created", subscriber),
    )
    contributions.register_policy("sample", _Policy())
    contributions.register_ui("sample", _ui_manifest())

    assert contributions.observability() == {
        "tools": 1,
        "events": 1,
        "policies": 1,
        "ui": 1,
    }
    assert contributions.tool_contributions("sample")
    assert contributions.policy_providers("sample")[0][0] == "sample"
    assert contributions.ui_manifests("sample")[0].extension_id == "sample"


@pytest.mark.asyncio
async def test_event_contributions_attach_once_and_detach_cleanly():
    capabilities, contributions = _registry()
    subscriber = _Subscriber()
    contributions.register_event(
        "sample",
        EventSubscription("sample.created", subscriber),
    )
    bus = InProcessEventBus()

    await capabilities.start_all()
    contributions.attach_events(bus)
    contributions.attach_events(bus)
    event = EventEnvelope(
        event_type="sample.created",
        tenant_id="tenant-a",
        aggregate_type="sample",
        aggregate_id="sample-1",
        idempotency_key="sample.created:sample-1",
    )
    await bus.publish(event)

    assert subscriber.events == [event]
    assert bus.subscribers("sample.created") == (subscriber,)

    contributions.detach_events()
    assert bus.subscribers("sample.created") == ()


@pytest.mark.asyncio
async def test_policy_contributions_tighten_the_baseline_decision():
    capabilities, contributions = _registry()
    await capabilities.start_all()

    contributions.register_policy("sample", _Policy())

    class Tools:
        async def enabled(self, tenant, name):
            return True

    decision = await ExecutionPolicy(Tools(), contributions).evaluate_tool(
        ToolExecutionContext(
            tenant_id="tenant-a",
            actor_id="operator-1",
            source="runtime",
        ),
        "sample_tool",
        ["sample_tool"],
        "read",
    )

    assert decision.allowed
    assert decision.confirmation.required
    assert decision.confirmation.action == "review_sample"


@pytest.mark.asyncio
async def test_inactive_capability_contributions_are_not_active():
    capabilities, contributions = _registry()
    subscriber = _Subscriber()
    contributions.register_event("sample", EventSubscription("sample.created", subscriber))
    contributions.register_policy("sample", _Policy())
    bus = InProcessEventBus()

    contributions.attach_events(bus)
    assert bus.subscribers("sample.created") == ()
    assert contributions.event_subscriptions(active_only=True) == ()
    assert contributions.policy_providers(active_only=True) == ()

    await capabilities.start_all()
    contributions.attach_events(bus)
    assert bus.subscribers("sample.created") == (subscriber,)
    assert len(contributions.policy_providers(active_only=True)) == 1

    await capabilities.disable("sample")
    contributions.attach_events(bus)
    assert bus.subscribers("sample.created") == ()
    assert contributions.policy_providers(active_only=True) == ()


@pytest.mark.asyncio
async def test_degraded_capability_contributions_are_not_active():
    capabilities = CapabilityRegistry()

    class FailingLifecycle:
        async def start(self):
            raise RuntimeError("unavailable")

        async def stop(self):
            return None

    capabilities.register(
        CapabilityManifest(
            id="failing",
            version="1.0.0",
            name="Failing",
            contributions=frozenset({"events"}),
        ),
        FailingLifecycle(),
    )
    contributions = CapabilityContributionRegistry(capabilities, UiExtensionRegistry())
    subscriber = _Subscriber()
    contributions.register_event("failing", EventSubscription("failing.created", subscriber))
    await capabilities.start_all()

    bus = InProcessEventBus()
    contributions.attach_events(bus)

    assert capabilities.get("failing").status == "degraded"
    assert bus.subscribers("failing.created") == ()


def test_ui_required_capability_must_match_contribution_owner():
    _, contributions = _registry()
    manifest = UiExtensionManifest(
        extension_id="sample",
        version="1.0.0",
        routes=(
            UiRouteContribution(
                id="sample-home",
                path="/sample",
                feature="sample/home",
                required_capability="other",
            ),
        ),
    )

    with pytest.raises(CapabilityContributionError, match="required_capability"):
        contributions.register_ui("sample", manifest)


def test_contribution_registry_rejects_duplicate_instances_and_validates_state():
    _, contributions = _registry()
    tool = _ToolContribution()

    contributions.register_tool("sample", tool)
    with pytest.raises(CapabilityContributionError, match="already registered"):
        contributions.register_tool("sample", tool)

    contributions.validate()


def test_manifest_upgrade_cannot_remove_bound_contribution_kinds_or_permissions():
    _, contributions = _registry()
    contributions.register_ui("sample", _ui_manifest())
    contributions.validate_tool_definitions(
        "sample",
        (
            ToolDefinition(
                name="sample_tool",
                description="Sample",
                parameters={"type": "object"},
                capability="sample",
                required_permissions=frozenset({"sample.manage"}),
            ),
        ),
    )

    with pytest.raises(CapabilityContributionError, match="removes active ui"):
        contributions.validate_manifest_change(
            "sample",
            CapabilityManifest(
                id="sample",
                version="2.0.0",
                name="Sample v2",
                permissions=frozenset({"sample.read"}),
                contributions=frozenset({"tools", "events", "policies"}),
            ),
        )

    with pytest.raises(CapabilityContributionError, match="removes UI permissions"):
        contributions.validate_manifest_change(
            "sample",
            CapabilityManifest(
                id="sample",
                version="2.0.0",
                name="Sample v2",
                permissions=frozenset({"sample.manage"}),
                contributions=frozenset({"tools", "events", "policies", "ui"}),
            ),
        )

    with pytest.raises(CapabilityContributionError, match="removes tool permissions"):
        contributions.validate_manifest_change(
            "sample",
            CapabilityManifest(
                id="sample",
                version="2.0.0",
                name="Sample v2",
                permissions=frozenset({"sample.read"}),
                contributions=frozenset({"tools", "events", "policies", "ui"}),
            ),
        )


def test_contribution_registry_enforces_manifest_kinds_identity_and_permissions():
    capabilities = CapabilityRegistry()
    capabilities.register(
        CapabilityManifest(
            id="limited",
            version="1.0.0",
            name="Limited",
            permissions=frozenset({"limited.read"}),
            contributions=frozenset({"tools"}),
        )
    )
    contributions = CapabilityContributionRegistry(capabilities, UiExtensionRegistry())

    with pytest.raises(CapabilityContributionError, match="does not declare events"):
        contributions.register_event("limited", EventSubscription("limited.created", _Subscriber()))
    with pytest.raises(CapabilityContributionError, match="does not match contribution owner"):
        contributions.validate_tool_definitions(
            "limited",
            (
                ToolDefinition(
                    name="other_tool",
                    description="Other",
                    parameters={"type": "object"},
                    capability="other",
                ),
            ),
        )
    with pytest.raises(CapabilityContributionError, match="undeclared permissions"):
        contributions.validate_tool_definitions(
            "limited",
            (
                ToolDefinition(
                    name="limited_tool",
                    description="Limited",
                    parameters={"type": "object"},
                    capability="limited",
                    required_permissions=frozenset({"limited.manage"}),
                ),
            ),
        )

    with pytest.raises(CapabilityContributionError, match="does not declare ui"):
        contributions.register_ui(
            "limited",
            UiExtensionManifest(extension_id="limited", version="1.0.0"),
        )
