"""Explicit service groups owned by the application composition root."""

from dataclasses import dataclass

from agent_platform.extension_contracts import RuntimeBindings


@dataclass(frozen=True)
class RuntimePlatformServices:
    engine: object
    settings: object
    snapshot: dict[str, object]
    gateway: object
    events: object
    ui_extensions: object
    contributions: object | None
    extensions: object


@dataclass(frozen=True)
class ToolPolicyServices:
    tools: object
    tool_workspace: object
    policy: object
    ledger: object
    replay: object
    contributions: tuple[object, ...]


@dataclass
class BusinessCapabilityServices:
    approval: object
    agents: object
    knowledge: object
    ingestion: object
    vector_index: object
    knowledge_workspace: object
    retrieval: object
    memory: object
    memory_store: object
    conversations: object
    handoffs: object
    customer: object
    confirmation: object
    channels: object


@dataclass
class ApplicationOnlyServices:
    staff: object
    members: object
    observability: object
    open_platform: object
    evaluation: object | None


@dataclass
class PlatformServiceGroups:
    runtime: RuntimePlatformServices
    tools: ToolPolicyServices
    business: BusinessCapabilityServices
    application: ApplicationOnlyServices


def build_service_groups(services: object) -> PlatformServiceGroups:
    """Project composition-owned services into explicit dependency groups."""

    return PlatformServiceGroups(
        runtime=RuntimePlatformServices(
            engine=services.engine,
            settings=services.settings,
            snapshot=services.snapshot,
            gateway=services.gateway,
            events=services.event_bus,
            ui_extensions=services.ui_extensions,
            contributions=getattr(services, "contributions", None),
            extensions=getattr(services, "extensions", None),
        ),
        tools=ToolPolicyServices(
            tools=services.tools,
            tool_workspace=services.tool_workspace,
            policy=services.policy,
            ledger=services.ledger,
            replay=services.replay,
            contributions=services.tool_contributions,
        ),
        business=BusinessCapabilityServices(
            approval=services.approval,
            agents=services.agents,
            knowledge=services.knowledge,
            ingestion=services.ingestion,
            vector_index=services.vector_index,
            knowledge_workspace=services.knowledge_workspace,
            retrieval=services.retrieval,
            memory=services.memory,
            memory_store=services.memory_store,
            conversations=services.conversations,
            handoffs=services.handoffs,
            customer=services.customer,
            confirmation=services.confirmation,
            channels=services.channels,
        ),
        application=ApplicationOnlyServices(
            staff=services.staff,
            members=services.members,
            observability=services.observability,
            open_platform=services.open_platform,
            evaluation=services.evaluation,
        ),
    )


def build_runtime_bindings(groups: PlatformServiceGroups) -> RuntimeBindings:
    """Build the Runtime port bundle from explicit service groups."""

    return RuntimeBindings(
        engine=groups.runtime.engine,
        settings=groups.runtime.settings,
        snapshot=groups.runtime.snapshot,
        tools=groups.tools.tools,
        policy=groups.tools.policy,
        retrieval=groups.business.retrieval,
        customer=groups.business.customer,
        confirmation=groups.business.confirmation,
        memory_store=groups.business.memory_store,
        gateway=groups.runtime.gateway,
        ledger=groups.tools.ledger,
        replay=groups.tools.replay,
        events=groups.runtime.events,
        tool_contributions=groups.tools.contributions,
        contributions=groups.runtime.contributions,
        extensions=groups.runtime.extensions,
    )
