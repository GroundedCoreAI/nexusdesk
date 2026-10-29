from agent_platform.business_capabilities.agent_config.service import AgentService
from agent_platform.business_capabilities.approval.service import ApprovalService
from agent_platform.business_capabilities.approval.tools import ApprovalToolContribution
from agent_platform.business_capabilities.channel.service import ChannelService
from agent_platform.business_capabilities.conversation.service import ConversationService
from agent_platform.business_capabilities.customer_service.confirmation import (
    CustomerConfirmationAdapter,
)
from agent_platform.business_capabilities.customer_service.service import CustomerService
from agent_platform.business_capabilities.customer_service.tools import (
    CustomerServiceToolContribution,
)
from agent_platform.business_capabilities.human_handoff.service import HandoffService
from agent_platform.business_capabilities.knowledge.ingestion import IngestionService
from agent_platform.business_capabilities.knowledge.retrieval import Retrieval
from agent_platform.business_capabilities.knowledge.service import KnowledgeService
from agent_platform.business_capabilities.knowledge.tools import KnowledgeToolContribution
from agent_platform.business_capabilities.knowledge.vector_store import VectorIndex
from agent_platform.business_capabilities.knowledge.workspace import Workspace
from agent_platform.business_capabilities.memory.service import MemoryService
from agent_platform.business_capabilities.memory.store import TsVectorStore
from agent_platform.business_capabilities.memory.tools import MemoryToolContribution
from agent_platform.business_capabilities.open_platform.service import OpenPlatform
from agent_platform.core_platform.platform_services.access_control.service import MemberDirectory
from agent_platform.core_platform.platform_services.events import DurableEventBus
from agent_platform.core_platform.platform_services.identity.staff import StaffDirectory
from agent_platform.core_platform.platform_services.model_gateway.gateway import ModelGateway
from agent_platform.core_platform.platform_services.observability.service import (
    ObservabilityService,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    TenantScopeService,
)
from agent_platform.core_platform.policy_harness.service import ExecutionPolicy
from agent_platform.core_platform.tool_gateway.ledger import ToolOperationLedger
from agent_platform.core_platform.tool_gateway.registry import ToolRegistry
from agent_platform.core_platform.tool_gateway.replay import DurableToolReplayCache
from agent_platform.core_platform.tool_gateway.workspace import ToolWorkspace


class PlatformServices:
    def __init__(
        self,
        engine,
        repository,
        settings,
        snapshot,
        file_specs,
        model_client,
        contributions=None,
    ):
        self.engine, self.repository, self.settings, self.snapshot = (
            engine,
            repository,
            settings,
            snapshot,
        )
        self.extensions = None
        self.contributions = contributions
        self.event_bus = DurableEventBus(engine)
        self.tools = ToolRegistry(engine, settings, file_specs)
        self.ledger = ToolOperationLedger(engine)
        self.replay = DurableToolReplayCache(engine)
        self.tool_workspace = ToolWorkspace(self.tools, model_client)
        self.tools.workspace = self.tool_workspace
        self.staff = StaffDirectory(engine)
        self.members = MemberDirectory(engine)
        self.approval = ApprovalService(engine, self.event_bus)
        self.tool_contributions = (ApprovalToolContribution(self.approval),)
        self.policy = ExecutionPolicy(self.tools, contributions)
        self.gateway = ModelGateway(engine, settings, model_client)
        self.agents = AgentService(engine, self.tools, self.gateway.catalog)
        self.knowledge = KnowledgeService(engine)
        self.ingestion = IngestionService(engine, self.knowledge, settings, model_client)
        self.vector_index = VectorIndex(engine, self.gateway, settings, model_client)
        self.knowledge_workspace = Workspace(
            engine, settings, model_client, self.vector_index, self.gateway
        )
        self.retrieval = Retrieval(engine, self.knowledge, self.vector_index, self.gateway)
        self.memory = MemoryService(engine, settings)
        # Phase 3 retrieval store. The keyword implementation is always safe;
        # ``platform_runtime.runtime_composition.runtime_services`` replaces it with
        # the startup-probed implementation (pgvector when available).
        self.memory_store = TsVectorStore(engine, settings)
        self.conversations = ConversationService(engine, settings.history_turns, self.memory)
        self.handoffs = HandoffService(engine, repository)
        self.customer = CustomerService(
            engine,
            repository,
            self.agents,
            self.handoffs,
            settings,
            snapshot,
            self.memory,
            events=self.event_bus,
        )
        self.confirmation = CustomerConfirmationAdapter(self.customer)
        self.channels = ChannelService(
            engine, self.conversations, self.customer, self.agents, settings
        )
        self.tool_contributions = ()
        # Phase 7: settings feed the maintenance-overdue cadence of rule_scan
        # (2x the configured scan interval) in the memory health sections.
        self.observability = ObservabilityService(engine, settings)
        self.scope = TenantScopeService(engine)
        self.open_platform = OpenPlatform(self)
        self.evaluation = None

    def bind_tool_contributions(self) -> None:
        """Bind capability-owned tools after runtime probes finish."""

        contributions = (
            ("customer-service", CustomerServiceToolContribution(self.customer)),
            ("knowledge", KnowledgeToolContribution(self.retrieval, self.event_bus)),
            ("memory", MemoryToolContribution(self.memory_store, self.settings, self.event_bus)),
            ("approval", ApprovalToolContribution(self.approval)),
        )
        if self.contributions is None:
            self.tool_contributions = tuple(item for _, item in contributions)
            return
        for capability_id, contribution in contributions:
            self.contributions.register_tool(capability_id, contribution)
        self.tool_contributions = self.contributions.tool_contributions()
