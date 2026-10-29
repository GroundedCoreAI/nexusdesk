# 03. 目录迁移映射

## 旧目录到新目录

| 旧路径 | 新路径 | 归属 |
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

## 旧目录处理原则

迁移完成后不保留旧目录作为兼容层。旧路径如果继续出现在文档中，只能出现在本迁移映射或历史说明中，不能出现在可执行命令和运行时代码中。

## 特殊说明

`platform_services/integrations` 是平台适配器和渠道基础设施，不代表新的业务能力；业务语义仍由 Business Capabilities 负责。
