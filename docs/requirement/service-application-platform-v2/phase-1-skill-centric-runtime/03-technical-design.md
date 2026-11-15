# Phase 1 · 技能中心的应用运行时 — 技术落地文档

> 状态：技术方案已落地，代码与 `0058` 迁移完成；定向验证通过，全量 CI 待执行
> 创建：2026-11-11
> 依据：[01-business-goals.md](01-business-goals.md)、[02-requirements.md](02-requirements.md)
> 现状核查：仓库 `feat/customer-service-optimization`，Alembic head `0057_industry_pack_runtime`

## 1. 改动总览

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移 | `backend/migrations/versions/0058_service_application_v2.py`（新） | 一次性删除旧服务场景/Provider/行业安装表，重建应用 v2、技能、连接、凭据、trace；扩展渠道、入站事件与会话 |
| 模型 | `backend/src/agent_platform/business_capabilities/customer_service/service_apps/models.py` | 用 Application / Skill / Connection / RuleConfig v2 替换 Scenario/Capability v1 |
| 应用服务 | `.../service_apps/service.py` | 应用 CRUD、分页、发布、回滚、复制、readiness；拆分而非继续膨胀 |
| 技能 | `.../service_apps/skills.py`（新） | 技能 CRUD、schema/映射校验、安全规则、发布检查 |
| 连接 | `.../service_apps/connections.py`（新） | 应用连接 CRUD、连接测试、凭据轮换、运行时解析 |
| 发布 | `.../service_apps/releases.py`（新） | v2 快照、canonical digest、版本差异、readiness、回滚 |
| 运行时 | `.../service_apps/runtime.py`（新） | `ApplicationRuntimeResolver`：应用版本 → Agent 版本 → 授权技能/连接 |
| 示例与模板 | `.../service_apps/seed.py`（改） | 代码内置标准案例、不可变示例 seed、复制与 lineage；不保留行业包安装/升级生命周期 |
| API | `.../service_apps/routes.py` | 应用、技能、连接、连接测试、发布/回滚/复制、分页 API |
| 渠道 | `backend/src/agent_platform/business_capabilities/channel/service.py`、`applications/customer_service/platform_routes.py` | `ChannelInput.agent_id` → `application_id/application_version`；入站固定版本 |
| 会话 | `backend/src/agent_platform/business_capabilities/conversation/service.py` | 写入 `application_id/application_version`；`agent_id` 仅作查询冗余 |
| 运行 | `backend/src/agent_platform/business_capabilities/customer_service/service.py`、`applications/platform_runtime/runtime_factory.py` | 提交 run 时注入应用上下文；合并 Agent builtins 与应用技能，隔离全局 tool |
| 装配 | `backend/src/agent_platform/applications/platform_runtime/platform_services.py`、`service_groups.py` | 移除 Provider/Scenario/ToolBridge/IndustryPackService；接入应用运行时与示例服务 |
| 配置 | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | 示例 seed、连接超时/page size/preview write/credential key |
| 前端目录 | `frontend/src/features/service-apps/` | 拆分为 catalog、detail、agent、skills、rules、debug、channels-release 组件 |
| 前端 API | `frontend/src/shared/api/client.ts` | 删除 Scenario/Provider/Industry Upgrade 类型和函数；新增应用 v2、技能、连接、分页类型 |
| 前端删除 | `frontend/src/features/service-scenarios/`、`IndustryCapabilitiesPage.tsx` | 整目录/页面删除；`/service-apps/industry` 不保留 |
| 测试 | `backend/tests/test_service_application_v2*.py`、`frontend/tests/service-app-v2*.spec.ts` | 数据、发布、隔离、渠道、示例、E2E 与 clean-break 测试 |

## 2. 现状与目标对照

| 现状 | 目标 |
|---|---|
| `service_applications.draft` 为 v1：`scenarios/capabilities/default_execution_order/channels` | v2：绑定 Agent、技能、应用连接、应用规则、渠道引用 |
| Agent 是 `CapabilityType.AGENT` | Agent 是应用级单值绑定，不再是技能/能力类型 |
| `service_provider_registry` 无 `application_id` | 连接属于 `service_application_connections`，以 `application_id` 隔离 |
| 凭据在 `tool_credentials`，与全局 `registered_tools` 绑定 | 凭据在应用连接凭据表，使用 Vault 密文；发布仅保存 credential ref |
| 场景通过 `ScenarioToolBridge` 引全局 tool/queue/provider | 技能只通过本应用连接解析，旧 Bridge 删除 |
| 渠道/会话只绑定 `agent_id` | 渠道/入站事件/会话绑定 `application_id/application_version`；Agent 由应用版本派生 |
| 行业包安装 + 升级预览 + 三方合并 | 代码模板 → 不可变示例 → 复制为用户应用；无安装/升级记录 |
| 应用列表返回全部 | 服务端分页，默认 10 |
| `ServiceAppsPage.tsx` 2384 行、`IndustryCapabilitiesPage.tsx` 1021 行 | 页面拆分；旧行业页删除 |

> 修订（2026-11-11）：`ServiceAppsPage.tsx` 行数以本次实测 2384 为准，不沿用早期“超过 3000 行”的概括。

## 3. 数据模型与迁移

### 3.1 迁移策略

历史迁移 `0054`～`0057` 已进入 Alembic 链，禁止修改。新增：

```text
backend/migrations/versions/0058_service_application_v2.py
down_revision = "0057_industry_pack_runtime"
```

本项目尚未正式上线，`0058` 是**一次性破坏式迁移**：

- 删除 `service_scenario_traces`。
- 删除 `service_scenario_versions`、`service_scenarios`。
- 删除 `service_provider_registry`。
- 删除 `industry_pack_upgrades`、`industry_pack_installations`。
- 删除并重建 `service_application_versions`、`service_applications`。
- 新建应用技能、连接、连接凭据、应用 trace。
- 为 `channels`、`channel_inbound_events`、`runtime_conversations` 增加应用字段。

迁移不做旧数据转换。升级前要求备份开发库；生产尚未开放，不存在正式存量承诺。`downgrade()` 只恢复旧结构的空壳，不恢复已删除数据，并在迁移 docstring 中明确声明。

### 3.2 `service_applications`

```sql
CREATE TABLE service_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  agent_id UUID NOT NULL REFERENCES agents(id),
  agent_version INTEGER NOT NULL CHECK (agent_version > 0),
  origin TEXT NOT NULL DEFAULT 'user'
    CHECK (origin IN ('user', 'example')),
  template_key TEXT NULL,
  template_version TEXT NULL,
  immutable BOOLEAN NOT NULL DEFAULT false,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'review', 'published', 'offline')),
  draft JSONB NOT NULL,
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision > 0),
  published_version INTEGER NULL CHECK (published_version > 0),
  archived BOOLEAN NOT NULL DEFAULT false,
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, business_id, workspace_id, application_key),
  UNIQUE (tenant_id, business_id, workspace_id, id),
  CHECK (origin = 'user' OR immutable = true)
);
```

约束：

- `agent_id/agent_version` 表示草稿当前绑定；已发布版本以版本快照为准。
- 示例必须 `immutable=true`；普通用户应用必须 `immutable=false`。
- `template_key/template_version` 只用于来源说明，不建立升级关系。
- 更新应用时同时校验 `draft_revision`；Agent 变更写审计。

### 3.3 `service_application_skills`

```sql
CREATE TABLE service_application_skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_id UUID NOT NULL,
  skill_key TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('knowledge','query','action','handoff')),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT true,
  connection_id UUID NULL,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, business_id, workspace_id, application_id, skill_key),
  FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
    REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
    ON DELETE CASCADE
);
```

`config` 结构：

```json
{
  "parameters": {"type": "object", "additionalProperties": false, "properties": {}},
  "argument_mapping": {},
  "result_mapping": {},
  "result_schema": {},
  "safety": {
    "requires_confirmation": false,
    "max_amount": null,
    "allowed_roles": [],
    "idempotency": "none",
    "timeout_seconds": 10,
    "on_error": "fail"
  }
}
```

### 3.4 `service_application_connections`

```sql
CREATE TABLE service_application_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_id UUID NOT NULL,
  connection_key TEXT NOT NULL,
  name TEXT NOT NULL,
  executor_kind TEXT NOT NULL
    CHECK (executor_kind IN ('http','internal','human_queue')),
  endpoint TEXT NULL,
  method TEXT NOT NULL DEFAULT 'GET'
    CHECK (method IN ('GET','POST')),
  public_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
  auth_kind TEXT NOT NULL DEFAULT 'none'
    CHECK (auth_kind IN ('none','bearer','api_key','custom')),
  timeout_seconds INTEGER NOT NULL DEFAULT 10
    CHECK (timeout_seconds BETWEEN 1 AND 60),
  max_response_bytes INTEGER NOT NULL DEFAULT 16000
    CHECK (max_response_bytes BETWEEN 128 AND 100000),
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, business_id, workspace_id, application_id, connection_key),
  FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
    REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
    ON DELETE CASCADE
);
```

HTTP 连接复用 `HttpTool` 对 endpoint、Header、schema、响应上限与超时的校验。公开 Header 禁止 Authorization/Cookie/Token 类敏感值；敏感认证必须走凭据表。

### 3.5 `service_application_connection_credentials`

```sql
CREATE TABLE service_application_connection_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  connection_id UUID NOT NULL UNIQUE,
  encrypted_secret TEXT NOT NULL,
  key_version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, business_id, workspace_id, connection_id)
    REFERENCES service_application_connections (tenant_id, business_id, workspace_id, id)
    ON DELETE CASCADE
);
```

使用 `CredentialVault.encrypt(payload, tenant, connection_id, vault_spec, create=True)`。API 只返回：

```json
{"auth_kind": "bearer", "credentials_configured": true}
```

### 3.6 `service_application_versions`

```sql
CREATE TABLE service_application_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_id UUID NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  schema_version TEXT NOT NULL CHECK (schema_version = 'v2'),
  config JSONB NOT NULL,
  config_digest TEXT NOT NULL,
  source_version INTEGER NULL CHECK (source_version > 0),
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, business_id, workspace_id, application_id, version),
  FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
    REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
    ON DELETE CASCADE
);
```

发布快照示例：

```json
{
  "schema_version": "v2",
  "agent": {"id": "uuid", "version": 3},
  "skills": [
    {
      "key": "order_lookup",
      "type": "query",
      "connection_key": "orders-api",
      "parameters": {...},
      "argument_mapping": {...},
      "result_mapping": {...},
      "safety": {...}
    }
  ],
  "connections": [
    {
      "key": "orders-api",
      "executor_kind": "http",
      "endpoint": "https://orders.example.com/v1/orders",
      "method": "GET",
      "auth_kind": "bearer",
      "credential_ref": "uuid",
      "revision": 2,
      "digest": "sha256:..."
    }
  ],
  "rules": {
    "fallback": "handoff",
    "handoff_queue": "customer-service"
  },
  "channels": [{"channel_id": "uuid", "provider": "slack"}]
}
```

`credential_ref` 是由服务端生成的引用，不等同于明文；快照不含加密密文。

### 3.7 `service_application_traces`

```sql
CREATE TABLE service_application_traces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_id UUID NOT NULL,
  application_version INTEGER NOT NULL,
  conversation_id UUID NULL,
  run_id UUID NULL,
  agent_id UUID NOT NULL,
  agent_version INTEGER NOT NULL,
  trace JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`trace` 包含应用 key/version、技能、连接、参数摘要（脱敏）、结果码、耗时和状态。禁止记录请求 Header、凭据、完整敏感响应。

### 3.8 渠道、入站和会话

```sql
ALTER TABLE channels
  ADD COLUMN application_id UUID NOT NULL,
  ADD COLUMN application_version INTEGER NOT NULL CHECK (application_version > 0),
  DROP COLUMN agent_id;

ALTER TABLE channel_inbound_events
  ADD COLUMN application_id UUID NOT NULL,
  ADD COLUMN application_version INTEGER NOT NULL;

ALTER TABLE runtime_conversations
  ADD COLUMN application_id UUID NULL,
  ADD COLUMN application_version INTEGER NULL,
  ADD COLUMN agent_version INTEGER NULL;
```

说明：

- `channels` 显式固定应用版本；切换版本是独立 API/UI 操作。
- `channel_inbound_events` 固定入站时版本，防止排队期间发布/回滚改变处理路径。
- 新渠道会话必须有应用上下文；应用内会话 `application_id/version` 非空。
- `agent_id/agent_version` 保留为派生查询冗余，来源必须是应用发布快照；不得单独作为渠道路由依据。

## 4. API 设计

### 4.1 应用

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/service-apps?page=&page_size=&status=&origin=&q=` | 服务端分页 |
| POST | `/service-apps` | 创建用户应用 |
| GET | `/service-apps/{key}` | 详情，含 helper flags |
| PUT | `/service-apps/{key}` | 更新草稿与 revision |
| POST | `/service-apps/{key}/copy` | 从示例复制为用户应用 |
| POST | `/service-apps/{key}/publish` | 发布 v2 |
| POST | `/service-apps/{key}/rollback` | 追加式回滚 |
| POST | `/service-apps/{key}/archive` / `restore` | 生命周期 |
| GET | `/service-apps/{key}/versions` | 版本历史 |
| GET | `/service-apps/{key}/readiness` | 发布检查 |
| GET | `/service-apps/{key}/traces` | 分页 trace |

示例编辑/删除请求 Handler 层强制 `403 service_application_example_immutable`。

### 4.2 技能

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/service-apps/{key}/skills?page=&page_size=&q=` | Table 数据 |
| POST | `/service-apps/{key}/skills` | 新建技能 |
| PUT | `/service-apps/{key}/skills/{skill_key}` | 更新与 revision |
| PATCH | `/service-apps/{key}/skills/{skill_key}` | 启停 |
| DELETE | `/service-apps/{key}/skills/{skill_key}` | 删除草稿技能 |
| POST | `/service-apps/{key}/skills/{skill_key}/test` | 使用草稿或已发布连接测试 |

### 4.3 连接

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/service-apps/{key}/connections` | 连接列表，无秘密值 |
| POST | `/service-apps/{key}/connections` | 新建 |
| PUT | `/service-apps/{key}/connections/{connection_key}` | 更新公开配置 |
| PUT | `/service-apps/{key}/connections/{connection_key}/credentials` | 保存/轮换密文 |
| POST | `/service-apps/{key}/connections/{connection_key}/test` | 连接测试 |
| DELETE | `/service-apps/{key}/connections/{connection_key}` | 未引用时删除 |

### 4.4 渠道

`ChannelInput` 改为：

```python
class ChannelInput(NameInput):
    application_id: UUID
    application_version: int = Field(ge=1)
    provider: str = "generic_webhook"
    config: dict[str, object] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)
```

新增：

```text
PUT /channels/{cid}/application-version
```

切换前验证目标应用版本已发布且渠道配置兼容。

## 5. 核心流程

### 5.1 创建/编辑应用

```text
Admin
 → 校验 scope、key、Agent 存在且未归档
 → 校验 agent_version 存在
 → 保存 v2 draft + draft_revision
 → 审计 application.created/updated
```

父应用和技能/连接子资源通过 `application_id + scope` 强绑定，不接受客户端传入的跨应用 connection_id。

### 5.2 技能与连接保存

```text
保存 connection
 → 校验 endpoint/headers/auth/timeout（复用 HttpTool 规则）
 → credentials 存在则 Vault 加密
 → revision+1

保存 skill
 → 若引用 connection，校验 connection 属于同一 application
 → 校验 JSON Schema、映射、safety
 → action 写操作未配置确认/豁免时阻塞发布或返回 422
```

连接测试必须通过 `EgressPolicy`，禁止直接使用任意 `httpx` 绕过网络策略。

### 5.3 发布

```text
publish(key, revision)
 → 锁定 application
 → 校验 draft_revision
 → readiness:
    Agent/version 可解析
    每个启用的 query/action 技能有同应用连接
    认证类型要求的凭据存在
    schema/映射/安全规则合法
    示例不能直接发布为可编辑版本（但可作为 immutable example）
    渠道引用有效
 → 读取 connection revision 和 credential_ref
 → 生成 canonical config v2 + digest
 → INSERT version=max+1
 → UPDATE application.published_version
 → 审计 application.published
```

发布不自动修改任何渠道绑定。渠道管理员之后显式切换版本。

### 5.4 回滚

```text
rollback(key, target_version, revision)
 → 读取 target config
 → 校验 target Agent/连接引用仍可用
 → 生成新的最高版本，source_version=target_version
 → published_version 指向新版本
 → 审计 application.rolled_back
```

不把 `published_version` 直接指回旧记录，以保持版本审计线性、source 清晰。

### 5.5 应用级运行时解析

```python
class ApplicationRuntimeResolver:
    async def resolve(
        self,
        conn,
        tenant: str,
        application_id: UUID,
        application_version: int,
        conversation_id: UUID,
    ) -> ApplicationRuntimeContext:
        release = await self.releases.get(...)
        agent_snapshot = await self.agents.snapshot(
            tenant, release["agent"]["id"], conn, release["agent"]["version"]
        )
        skills = [s for s in release["skills"] if s["enabled"]]
        connections = {
            c["key"]: c for c in release["connections"]
            if c["key"] in {s["connection_key"] for s in skills}
        }
        builtin_tools = intersect(agent_snapshot["config"]["tool_names"], PLATFORM_BUILTINS)
        return ApplicationRuntimeContext(
            application_id=application_id,
            application_version=application_version,
            agent_snapshot=agent_snapshot,
            skills=skills,
            connections=connections,
            builtin_tools=builtin_tools,
        )
```

`CustomerService._submit_run` 把 context 写入 run snapshot：

```json
{
  "agent": {...},
  "application": {
    "id": "...",
    "version": 7,
    "skills": [...],
    "connections": [...],
    "builtin_tools": [...]
  }
}
```

`RuntimeFactory.for_run`：

1. 若存在 `snapshot["application"]`，只从应用 connections 构建 HTTP `ToolGateway`。
2. 只暴露应用授权技能与 Agent builtin 的交集。
3. 连接解析器按 `application_id + connection_key + revision` 查找，且校验 credential。
4. 不再把 Agent `tool_snapshot` 中的全局自定义工具无条件注入客户应用 run。

全局工具目录可继续用于管理/调试，但不作为应用 runtime 的隐式权限来源。

### 5.6 渠道入站

```text
Webhook
 → 读取 channels.application_id/application_version
 → 入站 outbox 行固定 application_id/application_version
 → worker claim
 → 查/建会话，会话写 application/version
 → resolver 按入站固定版本生成 run snapshot
 → trace 关联 application/version/skill/connection
```

如入站事件处理前渠道被禁用，按既有规则标记失败；不得回退到 Agent 当前版本。

### 5.7 示例 seed 与复制

```text
startup seed
 → 对每个代码模板计算 template_key/version/digest
 → INSERT service_application(origin=example, immutable=true)
    ON CONFLICT(scope, key) DO NOTHING
 → 不 UPDATE 已存在行

copy example
 → 读取示例完整 config
 → 新 key/name、origin=user、immutable=false
 → 重新生成技能/连接 id，复制 credential 密文引用或要求重新配置
 → 审计 copied_from_example
```

若示例含真实外部凭据，不应内置敏感值；复制后要求配置凭据。模板可携带 mock/demo 连接。

### 5.8 删除旧链

后端删除/迁移：

- `providers/models.py`、`providers/service.py`、`providers/routes.py`、`providers/executors.py`。
- `scenarios/models.py`、`scenarios/service.py`、`scenarios/routes.py`、`scenarios/simulation.py`、`scenarios/tool_bridge.py`、`scenarios/seed.py`。
- `industry_packs/installations.py`、`merge.py`、`runtime_models.py`、`routes.py`。
- `PlatformServices` 中 Provider/Scenario/IndustryPack 装配、`ScenarioToolBridge`。
- `applications/customer_service/application.py` 中旧 Router 注册。

保留并重构行业模板内容：把 pack manifest 中有价值的模板内容收敛到 `service_apps/seed.py`，仅用于生成应用 v2 标准示例，不包含 tenant installation 状态。

前端删除：

- `features/service-scenarios/**`。
- `features/service-apps/IndustryCapabilitiesPage.tsx`。
- `App.tsx` 中 `/service-apps/industry` 标题、描述和路由分支。
- `shared/api/client.ts` 中 ServiceProvider、ServiceScenario、Industry Installation/Upgrade 类型与函数。
- 相关 CSS、i18n、Playwright 用例。

## 6. 前端设计

### 6.1 应用目录

```text
服务应用
├── 筛选：全部 / 我的应用 / 标准案例 / 已发布 / 配置中
├── 卡片：名称、描述、Agent、技能数、发布状态、来源标签
├── 操作：打开；示例卡片仅“预览/复制为我的应用”
└── 底部分页：默认 10
```

应用目录不提供“行业能力”单独入口；标准案例是应用目录中的来源筛选。

### 6.2 应用详情

```text
概览 | 智能体 | 技能 | 业务规则 | 预览与调试 | 客户渠道与发布
```

- **概览**：应用状态、绑定 Agent/version、技能/连接健康度、未发布变更、最近 trace。
- **智能体**：选择 Agent 与版本；展示 Prompt/模型/知识的只读摘要，链接到 Agent 管理。
- **技能**：Ant Design Table + Drawer。
- **业务规则**：应用级 fallback/handoff；技能级确认/金额/权限/幂等摘要。
- **预览与调试**：明确“草稿预览”与“已发布版本”；默认不允许写操作。
- **客户渠道与发布**：渠道绑定版本、切换版本、发布检查、版本历史与回滚。

### 6.3 组件拆分

```text
features/service-apps/
├── ServiceAppsPage.tsx                 # 路由编排，目标 <= 300 行
├── catalog/ApplicationCatalog.tsx
├── detail/ApplicationDetail.tsx
├── detail/ApplicationOverviewTab.tsx
├── detail/ApplicationAgentTab.tsx
├── skills/SkillsTab.tsx
├── skills/SkillDrawer.tsx
├── connections/ConnectionsSection.tsx
├── connections/ConnectionDrawer.tsx
├── rules/ApplicationRulesTab.tsx
├── debug/ApplicationDebugTab.tsx
└── release/ChannelsReleaseTab.tsx
```

约束：

- 表格分页使用 Ant Design Table 原生 `pagination`，默认 10、可切 20/50、显示总数、底部对齐。
- 所有可见文案使用 i18n。
- 密钥输入使用密码控件，保存后清空本地表单，不回填。
- 示例只提供只读视图与复制按钮。

## 7. 配置

`backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`：

```python
service_app_examples_enabled: bool = True
service_app_connection_timeout_seconds: int = 10       # Field(ge=1, le=60)
service_app_connection_timeout_max: int = 60           # Field(ge=1, le=60)
service_app_default_page_size: int = 10                # Field(ge=1, le=100)
service_app_preview_write_enabled: bool = False
```

凭据密钥复用现有 `model_credential_key_file` / Vault 配置；若需要独立密钥，新增 `service_app_credential_key_file`，不得允许缺失时明文降级。

## 8. 模型调用路径

本阶段不改变模型网关：

- Agent 继续通过 `model_profile_id/model_profile_version` 调用 Gateway。
- 应用绑定 Agent 版本后，运行时使用该 Agent 快照的 profile，不自行选模型。
- 技能调用由 Agent 提出，经确定性规则检查后执行应用连接。
- 模型用量仍按 `run_id` 落 `gateway_calls`。

## 9. 观测与审计

- 应用 trace 关联 `application_id/version`、`agent_id/version`、`skill_key`、`connection_key`。
- 审计动作：应用创建/更新/发布/回滚/归档/复制、技能变更、连接变更、凭据配置状态、渠道版本切换。
- 任何审计详情不得包含连接密钥、Authorization、Cookie 或完整外部响应。
- 发布失败记录明确 readiness 错误码，不记录凭据值。

## 10. 测试方案

| 层 | 用例 |
|---|---|
| 单测 | v2 contract、schema/映射、safety、digest、readiness、示例 immutable、分页参数 |
| 集成 | 两应用同名技能不同连接、同一 Agent 隔离、发布/回滚、渠道入站固定版本、seed/复制、审计脱敏 |
| 迁移 | 空库 `0058`、pre-release 库销毁旧表、迁移后 seed 与发布 |
| 前端 | 目录分页、详情页签、技能 Table/Drawer、示例只读、旧路由删除 |
| 回归 | RBAC、Agent 发布、会话、渠道 outbox/delivery、知识/记忆、运行与审计 |

详细用例见 `04-test-plan.md`。

## 11. 上线与回滚

- `0058` 是破坏式迁移，必须先备份；quickstart 推荐 `down` 后删除数据卷重建。
- 后端、前端、迁移必须同版本部署，禁止旧前端连接新后端或滚动混部。
- Phase 1 不提供运行时开关回旧模型；clean-break 是产品决策。
- 应用级行为回滚通过应用版本和渠道绑定版本完成。
- 迁移级回滚只用于开发环境恢复结构，不恢复数据；生产回滚应恢复备份并部署前一版本。
- seed 每次启动幂等，不修改用户应用。
