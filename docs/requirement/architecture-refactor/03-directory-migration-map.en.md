# 03. Directory Migration Map

## Old-to-new mapping

| Old path | New path | Layer |
|---|---|---|
| `agent_platform/apps/api` | `agent_platform/applications/customer_service` | Applications |
| `agent_platform/apps/worker` | `agent_platform/applications/worker` | Applications |
| `agent_platform/modules/agent_runtime` | `agent_platform/core_platform/agent_runtime` | Core Platform |
| `agent_platform/modules/tool_gateway` | `agent_platform/core_platform/tool_gateway` | Core Platform |
| `agent_platform/modules/policy` | `agent_platform/core_platform/policy_harness` | Core Platform |
| `agent_platform/extension_platform` | `agent_platform/core_platform/extension_platform` | Core Platform |
| `agent_platform/platform/*` | `agent_platform/core_platform/platform_services/*` | Core Platform |
| `agent_platform/integrations/*` | `agent_platform/core_platform/platform_services/integrations/*` | Core Platform |
| `agent_platform/modules/model_gateway` | `agent_platform/core_platform/platform_services/model_gateway` | Core Platform |
| `agent_platform/modules/observability` | `agent_platform/core_platform/platform_services/observability` | Core Platform |
| `agent_platform/modules/access_control` | `agent_platform/core_platform/platform_services/access_control` | Core Platform |
| `agent_platform/modules/agent_config` | `agent_platform/business_capabilities/agent_config` | Business Capabilities |
| `agent_platform/modules/channel` | `agent_platform/business_capabilities/channel` | Business Capabilities |
| `agent_platform/modules/conversation` | `agent_platform/business_capabilities/conversation` | Business Capabilities |
| `agent_platform/modules/customer_service` | `agent_platform/business_capabilities/customer_service` | Business Capabilities |
| `agent_platform/modules/evaluation` | `agent_platform/business_capabilities/evaluation` | Business Capabilities |
| `agent_platform/modules/human_handoff` | `agent_platform/business_capabilities/human_handoff` | Business Capabilities |
| `agent_platform/modules/knowledge` | `agent_platform/business_capabilities/knowledge` | Business Capabilities |
| `agent_platform/modules/memory` | `agent_platform/business_capabilities/memory` | Business Capabilities |
| `agent_platform/modules/open_platform` | `agent_platform/business_capabilities/open_platform` | Business Capabilities |
| `agent_platform/contracts` | `agent_platform/extension_contracts` | Extension Contracts |

## Legacy-directory policy

Legacy directories are not retained as compatibility layers after migration. If an old path appears in documentation, it must be limited to this migration map or historical notes; it must not appear in executable commands or runtime code.

## Special note

`platform_services/integrations` contains platform adapters and channel infrastructure, not a new business capability. Business semantics remain owned by Business Capabilities.
