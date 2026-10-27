"""Default capability tool contributions for transitional callers."""

from agent_platform.business_capabilities.approval.tools import APPROVAL_TOOL_DEFINITIONS
from agent_platform.business_capabilities.customer_service.tools import (
    CUSTOMER_SERVICE_TOOL_DEFINITIONS,
    CustomerServiceToolContribution,
)
from agent_platform.business_capabilities.knowledge.tools import (
    KNOWLEDGE_SEARCH_TOOL,
    KnowledgeToolContribution,
)
from agent_platform.business_capabilities.memory.tools import (
    MEMORY_SEARCH_TOOL,
    MemoryToolContribution,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

BUILTIN_SCHEMAS = {
    name: definition.model_schema()
    for name, definition in CUSTOMER_SERVICE_TOOL_DEFINITIONS.items()
}
BUILTIN_SCHEMAS.update(
    {
        KNOWLEDGE_SEARCH_TOOL.name: KNOWLEDGE_SEARCH_TOOL.model_schema(),
        MEMORY_SEARCH_TOOL.name: MEMORY_SEARCH_TOOL.model_schema(),
    }
)
BUILTIN_SCHEMAS.update(
    {name: definition.model_schema() for name, definition in APPROVAL_TOOL_DEFINITIONS.items()}
)


def default_tool_contributions(bindings):
    """Return transitional contributions from explicit runtime ports."""

    settings = bindings.settings or Settings(_env_file=None)
    return (
        CustomerServiceToolContribution(bindings.customer),
        KnowledgeToolContribution(bindings.retrieval, bindings.events),
        MemoryToolContribution(bindings.memory_store, settings, bindings.events),
    )
