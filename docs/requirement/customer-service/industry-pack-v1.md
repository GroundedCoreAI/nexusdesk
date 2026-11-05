# 多行业场景包 V1 架构设计

> 状态：V1 架构设计草案，待评审
> 创建：2026-11-02
> 范围：只定义架构、数据映射、内容社区包和实施切片；本轮不修改业务代码
> 关联：
> - [服务场景平台](../service-scenario-platform/README.md)
> - [请求路由规划](../request-routing/README.md)
> - [知乎 / 抖音 / 高德案例分析](../request-routing/case-studies/01-service-scenario-analysis-zhihu-douyin-amap.md)

## 0. 结论摘要

本设计不新造一套“行业客服系统”，也不为每个行业复制场景、页面或执行链路。

核心判断如下：

1. **Industry Pack 是分发层，不是运行时租户实体。** 它负责把一组行业知识、对象模板、场景模板、策略模板、样例和验收用例打包交付。
2. **Scenario Template 是版本化蓝图，不是线上场景。** 它编译成现有的 `ScenarioConfig`；企业使用时生成 `service_scenarios` 中的场景实例。
3. **企业场景实例继续使用现有场景模型和版本表。** 不新增 `industry_scenarios`、`industry_objects`、`industry_instances` 等行业专属核心表。
4. **服务应用继续使用现有 `ServiceApplicationConfig`。** 行业包只提供应用蓝图，最终仍由 `service_applications` 组合场景、能力、目录和渠道。
5. **运行时只认通用契约。** 对象、事实、决策、承接和能力注册都走通用路径，不允许出现 `if industry == ...` 或 `if pack_key == ...`。
6. **模板升级必须显式、可预览、可回滚。** Pack 和模板发布后不可原地修改；企业升级生成新的场景草稿，经过三方合并、模拟验收和发布门禁后才进入生产。
7. **第一个新增行业包为“内容社区”。** V1 先定义 6 类业务对象和 11 个核心场景，成熟度按 `alpha / beta / ga` 标记，避免一次性铺满所有行业。

一句话概括：

```text
行业包提供可复用资产
  → 场景模板提供可版本化蓝图
  → 企业实例保存企业自己的配置和覆盖
  → 服务应用负责组合和交付
```

---

## 1. 现状核查与设计约束

### 1.1 已有实现

当前仓库已经具备多行业场景包的落点：

| 现有能力 | 实现位置 | 对行业包的意义 |
|---|---|---|
| 服务场景草稿、发布、版本、回滚 | `backend/src/agent_platform/business_capabilities/customer_service/scenarios/` | 企业场景实例不需要新建版本体系 |
| `ScenarioConfig` | `scenarios/models.py` | 场景模板可以直接编译成现有配置 |
| 确定性模拟 | `scenarios/simulation.py` | 行业包样例和验收用例可复用现有模拟器 |
| 场景轨迹 | `service_scenario_traces` | 行业包验收可沉淀为模拟轨迹，不新增表 |
| 服务应用、应用版本、发布 | `service_apps/` | 应用蓝图可以编译成现有应用配置 |
| 应用级服务目录 | `ServiceApplicationConfig.service_categories` | 行业包目录分类可映射到应用自己的目录 |
| 前端场景目录、业务编排、预览 | `frontend/src/features/service-apps/ServiceAppsPage.tsx` | 不需要为行业包新做一套页面 |
| 前端业务语义映射 | `frontend/src/features/service-scenarios/scenarioConfig.ts` | 需要从硬编码标签逐步转为模板/描述符驱动 |
| 当前演示种子 | `applications/seed_service_scenarios.py`、`scenarios/seed.py`、`service_apps/seed.py` | 后续可以复用为行业包安装器，不再写死“购物消费” |

### 1.2 必须正视的现有边界

1. **一个场景只有一个主业务对象。** `ScenarioConfig.object` 是单一 `BusinessObjectConfig`。  
   V1 不让行业包扩展成任意多对象编排。一个场景只能声明一个主对象，关联对象通过事实字段、对象引用或 `config.related_objects` 只读展示。

2. **服务目录分类当前只存名称和排序。** `ApplicationServiceCategory` 只有 `name` 和 `order`，没有稳定的 `category_key`。  
   V1 先以分类名称作为应用内业务键；行业包元数据保留 `category_key`，用于安装和升级时的映射。是否增加可选的稳定分类键，放到后续版本。

3. **`ServiceApplicationConfig` 没有自由扩展字段。**  
   因此不在应用配置上硬塞行业包状态。应用是否属于某个行业包，由它引用的场景实例中的 `config.industry_pack` 推导；应用蓝图只负责生成初始配置。

4. **当前演示种子是购物消费专用。**  
   `scenarios/seed.py` 中的 `domain`、对象、事实和工具都围绕订单。多行业包需要引入模板清单和编译器，不能继续在 `default_scenarios()` 中追加行业分支。

5. **现有前端对象标签是有限映射。**  
   `scenarioConfig.ts` 的 `objectTypeLabel()` 目前只覆盖订单、发票、物流等少数对象。内容社区需要补充描述符，但不能在每个页面写行业判断。

### 1.3 设计约束

- 不新增行业专属核心表。
- 不新增 `industry` 枚举进入 Core Platform。
- 不新增行业专属运行时服务。
- 不复制场景、对象、事实、决策、承接模型。
- Pack 和模板是资产；企业实例和应用才是租户数据。
- 已发布版本不可原地修改。
- 所有生产发布必须经过现有场景发布和应用发布链路。

---

## 2. 四层模型：Pack → Template → Instance → Application

```text
┌──────────────────────────────────────────────┐
│ 1. Industry Pack                             │
│    行业编码 / 版本 / 成熟度 / 目录 / 对象模板 │
│    场景模板 / 策略模板 / 样例 / 验收用例      │
└──────────────────────┬───────────────────────┘
                       │ 编译、安装、选择
                       ▼
┌──────────────────────────────────────────────┐
│ 2. Scenario Template                         │
│    一份可版本化的完整 ScenarioConfig 蓝图     │
│    包含对象、事实、决策、承接、兜底、样例      │
└──────────────────────┬───────────────────────┘
                       │ 企业实例化；允许企业覆盖
                       ▼
┌──────────────────────────────────────────────┐
│ 3. Enterprise Scenario Instance              │
│    service_scenarios 中的租户场景             │
│    草稿 / 发布版本 / 覆盖配置 / 场景轨迹       │
└──────────────────────┬───────────────────────┘
                       │ 引用并锁定具体版本
                       ▼
┌──────────────────────────────────────────────┐
│ 4. Service Application Composition           │
│    service_applications 中的交付单元           │
│    目录 / 场景引用 / 能力 / 渠道 / 应用版本    │
└──────────────────────────────────────────────┘
```

### 2.1 各层职责

| 层级 | 职责 | 持久化位置 | 版本 | 谁能修改 |
|---|---|---|---|---|
| Industry Pack | 行业资产的交付单元；提供目录、对象、场景、策略、样例和验收基线 | V1 作为代码/内容资产随应用发布；不在租户库建行业包表 | SemVer，例如 `1.0.0` | 平台/行业包维护者 |
| Scenario Template | 可复用、可测试、可引用的场景蓝图；描述一个标准客户任务 | Pack 资产中的 `scenario_templates[]`；不是运行时 `service_scenarios` 行 | 模板 SemVer，例如 `1.2.0` | 平台/行业包维护者 |
| Enterprise Scenario Instance | 企业实际运行和编辑的场景；保存企业自己的覆盖、发布版本和轨迹 | 现有 `service_scenarios`、`service_scenario_versions`、`service_scenario_traces` | 整数版本，例如 `v1`、`v2` | 企业管理员 |
| Service Application | 面向客户交付的服务应用；组合场景、目录、能力和渠道 | 现有 `service_applications`、`service_application_versions` | 整数版本，例如 `v1`、`v2` | 企业管理员 |

### 2.2 Pack 层

Pack 负责回答：

- 这是哪个行业？
- 这个行业包现在有多成熟？
- 包含哪些服务目录分类？
- 提供哪些标准业务对象、标准场景和策略模板？
- 每个模板有哪些样例数据和验收用例？
- 适用于哪些渠道？
- 哪些模板可以默认组合成一个服务应用？

Pack 不负责：

- 不保存某个租户的客户数据。
- 不保存某个租户的覆盖配置。
- 不直接产生线上场景。
- 不拥有运行时会话。
- 不替代服务应用发布。

### 2.3 Scenario Template 层

Scenario Template 是“带产品语义的完整 `ScenarioConfig` 蓝图”。它负责：

- 场景名称、描述、目录分类建议。
- 产品场景类型：查询、办理、诊断、服务。
- 对应现有执行模板：`consult`、`query`、`action`。
- 主业务对象及对象模式。
- 业务事实字段、格式、脱敏和受众。
- 用户决策点、确认和纠错。
- 推荐问题。
- 承接能力及兜底顺序。
- 匹配关键词。
- 适用渠道。
- 样例数据和验收用例引用。

必须区分两个“模板”：

| 概念 | 含义 | 示例 |
|---|---|---|
| Pack 中的 Scenario Template | 完整产品蓝图，包含整个场景定义 | `account-status-query@1.0.0` |
| `ScenarioConfig.template` | 现有执行模板族 | `consult` / `query` / `action` |

**不要重载 `ScenarioConfig.template` 字段。**  
产品场景类型和成熟度放在 `ScenarioConfig.config.industry_pack` 中；现有 `template` 仍只表达咨询、查询、办理三种执行模板。

### 2.4 Enterprise Scenario Instance 层

企业实例化时：

1. 复制模板编译后的 `ScenarioConfig`。
2. 生成租户内唯一的 `scenario_key`。
3. 写入 `service_scenarios.draft`，初始为草稿或模拟态。
4. 在 `config.industry_pack` 记录来源模板、模板版本、摘要和产品类型。
5. 企业可以编辑允许覆盖的部分。
6. 发布后生成 `service_scenario_versions` 的不可变版本。

实例是**复制后独立演进**的关系，不是运行时实时引用模板。模板升级不会自动改变已实例化场景。

### 2.5 Service Application 层

应用负责：

- 从应用自己的 `service_categories` 中选择目录分类。
- 通过 `ApplicationScenarioReference` 引用场景实例。
- 通过 `version` 锁定场景版本；未指定版本时，发布时解析为当前已发布版本。
- 组合 `capabilities`、`default_execution_order` 和 `channels`。
- 通过 `service_application_versions` 发布不可变应用版本。

现有应用发布逻辑已经把场景引用解析为具体版本，因此行业包升级不需要改变应用引用机制。

### 2.6 复用规则

| 规则 | 说明 |
|---|---|
| Pack 跨租户复用 | 同一 Pack 版本可以被多个租户安装或引用 |
| Template 跨租户、跨应用复用 | 同一模板可实例化为多个企业场景 |
| 企业实例按租户隔离 | `service_scenarios` 的作用域仍然由现有租户和业务范围控制 |
| 同一场景可被多个应用引用 | 一个租户内同一个场景实例可出现在多个服务应用中 |
| 应用发布时锁定场景版本 | 应用版本保存具体场景版本，不随场景后续发布漂移 |
| 场景实例不因模板升级自动变化 | 升级必须生成新的企业草稿并经过合并和发布 |
| Pack 不做租户内在线编辑 | 企业修改的是实例，不是平台 Pack |

---

## 3. 与现有模型的映射

### 3.1 总体映射

| 行业包概念 | 现有模型/位置 | 是否新增核心模型 |
|---|---|---|
| Pack 元数据 | Pack 清单文件（JSON/YAML）+ 校验模型 | 否 |
| 目录分类 | `ServiceApplicationConfig.service_categories` | 否 |
| 对象模板 | `ScenarioConfig.object` + `facts` + `config.related_objects` | 否 |
| 场景模板 | 一个完整的 `ScenarioConfig` | 否 |
| 策略模板 | `entries`、`object`、`facts`、`decisions`、`recommendations`、`handlers`、`fallback_order`、`matching` 的配置片段 | 否 |
| 样例数据 | `SimulationRequest.object` / `SimulatedObject` / Pack fixtures | 否 |
| 验收用例 | Pack 测试资产 + 现有 `/simulate` 接口 + 模拟轨迹 | 否 |
| 企业场景实例 | `service_scenarios` + `service_scenario_versions` | 否 |
| 服务应用快速组合 | `ServiceApplicationConfig` + `service_applications` | 否 |
| 适用渠道 | `ScenarioConfig.channels` + `ServiceApplicationConfig.channels` | 否 |
| 成熟度 | `ScenarioConfig.config.industry_pack.maturity` | 否 |
| 产品场景类型 | `ScenarioConfig.config.industry_pack.scenario_kind` | 否 |

### 3.2 Pack 来源信息放入现有 `config`

`ScenarioConfig.config` 已经是 JSONB 自由配置，并随场景版本一起保存，因此适合承载来源信息。

建议结构：

```json
{
  "industry_pack": {
    "pack_key": "content-community",
    "pack_version": "1.0.0",
    "template_key": "account-status-query",
    "template_version": "1.0.0",
    "template_digest": "sha256:...",
    "scenario_kind": "query",
    "maturity": "ga",
    "catalog_category_key": "account-security",
    "base_template_version": "1.0.0",
    "last_merged_template_version": "1.0.0",
    "merge_state": "up_to_date"
  },
  "policy_profile": "read_only_query",
  "related_objects": []
}
```

约束：

- `industry_pack` 只用于来源追踪、升级、审计和展示。
- 路由、对象解析、承接选择和权限判断**不得读取 `pack_key` 来决定业务分支**。
- `template_digest` 用于检测模板基线和企业覆盖是否匹配。
- `merge_state` 可取 `up_to_date`、`update_available`、`conflicted`、`blocked`。
- 已发布版本中的来源信息不随 Pack 更新。

### 3.3 业务对象映射

Pack 的对象模板不是新运行时对象表，而是生成 `ScenarioConfig.object` 和事实字段的源数据。

映射示例：

| 对象模板字段 | 映射到 |
|---|---|
| `object_type` | `ScenarioConfig.object.type` |
| `provider_key` | `ScenarioConfig.object.provider` |
| `default_mode` | `ScenarioConfig.object.mode` |
| `permission_scope` | `ScenarioConfig.object.permission_policy` |
| `candidate_sort` / `candidate_limit` | `ScenarioConfig.object.candidate_strategy` |
| `fact_fields[]` | `ScenarioConfig.facts[]` |
| `sensitive_fields[]` | `ScenarioConfig.facts[].masked` / 脱敏配置 |
| `related_object_types[]` | `ScenarioConfig.config.related_objects`（只读元数据） |
| `sample_objects[]` | Pack fixtures，供模拟器使用 |

V1 约束：

- 每个场景只能有一个主对象。
- 关系对象不能在没有对象解析的情况下被当作事实来源。
- 对象只保存引用和必要事实，不复制完整业务快照。
- 权限过滤发生在对象候选和事实投影阶段，不在前端隐藏。

### 3.4 服务策略映射

“策略模板”不需要新模型，它是对现有场景配置片段的命名组合。

| 策略槽位 | 映射到现有字段 |
|---|---|
| 入口策略 | `entries` |
| 对象策略 | `object`、`candidate_strategy`、`permission_policy` |
| 事实策略 | `facts[]` |
| 决策策略 | `decisions[]` |
| 推荐策略 | `recommendations[]` |
| 承接策略 | `handlers[]` |
| 兜底策略 | `handlers` + `fallback_order` |
| 匹配策略 | `matching` |
| 渠道策略 | `channels` |
| 业务约束 | `config.policy_profile`、`config.governance` 等自由配置 |

策略模板只允许固定槽位和可解释配置，不支持任意脚本或 DSL。

### 3.5 模拟数据和验收用例映射

Pack 中的样例：

```json
{
  "sample_id": "content-community-account-001",
  "message": "我的账号为什么不能登录？",
  "entry": "natural_language",
  "object": {
    "id": "ACCOUNT-SIM-001",
    "type": "community_account",
    "status": "受限",
    "facts": {
      "account_status": "受限",
      "security_state": "需要验证",
      "registered_at": "2024-03-12"
    }
  },
  "selected_decision": null
}
```

验收用例：

```json
{
  "case_id": "AC-COMMUNITY-ACCOUNT-001",
  "pack_key": "content-community",
  "template_key": "account-status-query",
  "required": true,
  "given": "客户拥有一个状态受限的模拟账号",
  "when": "客户进入账号状态查询并选择该账号",
  "then": {
    "result_status": "succeeded",
    "handler_type": "query",
    "must_include_facts": ["account_status"],
    "must_not_include": ["access_token", "raw_phone"]
  }
}
```

执行方式：

- 通过现有场景模拟接口产生 `SimulationTrace`。
- 模拟结果以 `simulation=true` 写入现有 `service_scenario_traces`。
- Pack 验收信息放入 trace 的 JSON 扩展字段，例如 `trace.pack_acceptance`。
- 不为验收结果新建表，也不把测试数据写入生产业务对象。

### 3.6 应用蓝图映射

Pack 中的 `application_blueprint` 只用于生成初始应用配置：

| 应用蓝图字段 | 映射到 `ServiceApplicationConfig` |
|---|---|
| `name` | `name` |
| `description` | `description` |
| `catalog_categories[]` | `service_categories` |
| `scenario_template_keys[]` | `scenarios`（实例化后的 key 和版本） |
| `capabilities[]` | `capabilities` |
| `default_execution_order` | `default_execution_order` |
| `channels[]` | `channels` |

应用蓝图生成后，应用配置即成为租户自己的数据。后续 Pack 更新不直接改写已发布应用。

---

## 4. 行业包元数据

### 4.1 Pack 清单结构

建议 V1 使用 JSON 作为可部署资产格式，使用 Pydantic 清单模型校验。示例：

```json
{
  "schema_version": "v1",
  "pack_key": "content-community",
  "name": "内容社区",
  "description": "账号、内容、会员权益、社区治理和商家合作场景包",
  "pack_version": "1.0.0",
  "maturity": "beta",
  "supported_channels": ["web", "app", "wechat", "h5"],
  "catalog_categories": [
    {"key": "account-security", "name": "账号与安全", "order": 10},
    {"key": "content-creation", "name": "内容与创作", "order": 20},
    {"key": "membership", "name": "会员与权益", "order": 30},
    {"key": "governance", "name": "社区治理", "order": 40},
    {"key": "merchant", "name": "商家合作", "order": 50},
    {"key": "general", "name": "通用服务", "order": 60}
  ],
  "object_templates": [],
  "policy_templates": [],
  "scenario_templates": [],
  "sample_data": [],
  "acceptance_cases": [],
  "application_blueprint": {}
}
```

### 4.2 Pack 顶层字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | Pack 清单协议版本 |
| `pack_key` | 是 | 稳定行业编码，小写短横线，例如 `content-community` |
| `name` | 是 | 行业包展示名称 |
| `description` | 否 | 适用边界和定位 |
| `pack_version` | 是 | SemVer，发布后不可修改 |
| `maturity` | 是 | `alpha` / `beta` / `ga` |
| `supported_channels` | 是 | Pack 允许的渠道集合 |
| `catalog_categories` | 是 | 建议服务目录分类 |
| `object_templates` | 是 | 对象模板列表 |
| `policy_templates` | 是 | 策略模板列表 |
| `scenario_templates` | 是 | 场景模板列表 |
| `sample_data` | 是 | 样例文件或内联样例索引 |
| `acceptance_cases` | 是 | 验收用例索引 |
| `application_blueprint` | 否 | 推荐的应用初始组合 |

### 4.3 对象模板字段

| 字段 | 说明 |
|---|---|
| `object_template_key` | 稳定对象模板键 |
| `object_type` | 映射到 `ScenarioConfig.object.type` |
| `name` | 业务展示名 |
| `description` | 对象用途 |
| `provider_key` | 映射到 `object.provider`，通过适配器注册表解析 |
| `default_mode` | `none` / `implicit` / `optional` / `required` / `multiple` |
| `permission_scope` | 默认 `customer_scope` |
| `fact_fields` | 字段键、标签、来源、格式、脱敏、受众、刷新策略 |
| `sensitive_fields` | 禁止直接展示或传给模型的字段 |
| `candidate_strategy` | 排序、数量、过滤、空状态 |
| `sample_refs` | 样例数据引用 |

### 4.4 策略模板字段

| 字段 | 说明 |
|---|---|
| `policy_key` | 稳定策略键 |
| `name` | 策略名称 |
| `description` | 适用条件和风险说明 |
| `fragments` | 固定槽位的配置片段：入口、对象、事实、决策、承接、兜底、匹配 |
| `protected` | 不允许企业覆盖的字段集合 |
| `default_channels` | 该策略默认适用渠道 |

策略模板不是脚本，不包含条件表达式执行器。复杂逻辑优先由现有 `handlers[].when`、`fallback_order`、对象状态和决策键表达。

### 4.5 场景模板字段

| 字段 | 说明 |
|---|---|
| `template_key` | 场景模板稳定键 |
| `template_version` | 模板 SemVer |
| `name` | 场景名称 |
| `description` | 客户任务 |
| `scenario_kind` | `query` / `action` / `diagnosis` / `service` |
| `execution_template` | `consult` / `query` / `action`，映射到 `ScenarioConfig.template` |
| `maturity` | 模板成熟度 |
| `catalog_category_key` | 建议目录分类 |
| `object_template_key` | 主对象模板，可为空 |
| `policy_template_key` | 策略模板 |
| `config` | 完整 `ScenarioConfig` 蓝图 |
| `channels` | 适用渠道 |
| `sample_refs` | 样例引用 |
| `acceptance_case_refs` | 验收用例引用 |
| `deprecated` | 是否停止新实例化，但允许已有实例继续使用 |

### 4.6 成熟度语义

成熟度与场景状态是两件事：

| 成熟度 | 产品含义 | 发布约束 |
|---|---|---|
| `alpha` | 设计验证、样例和接口未稳定 | 只允许模拟或内部租户草稿，不允许生产发布 |
| `beta` | 可用于试点租户或灰度应用 | 允许发布到指定企业/应用，但必须有完整模拟验收和人工兜底 |
| `ga` | 稳定模板，可默认交付 | 可进入正式应用，必须通过发布门禁和验收用例 |

`ScenarioConfig.config.industry_pack.maturity` 记录模板成熟度；`service_scenarios.status` 仍记录 `draft / review / published / offline`。二者不能混用。

### 4.7 产品场景类型与现有执行模板

| 产品类型 | 客户任务 | 现有执行模板映射 | 说明 |
|---|---|---|---|
| `query` 查询 | 看对象、状态、进度、权益 | `query` | 以只读对象事实为主 |
| `action` 办理 | 提交申诉、举报、申请、设置 | `action` | 必须有确认、回执和失败兜底 |
| `diagnosis` 诊断 | 解释为什么异常、定位原因 | `consult` 或 `query` | 可使用知识、查询、Agent、人工组合 |
| `service` 服务 | 进入人工服务、合作跟进、投诉升级 | `consult` 或 `action` | 重点是上下文移交和人工承接 |

产品类型不新增 `ScenarioConfig` 枚举，不改变现有执行器。

---

## 5. 内容社区行业包 V1

### 5.1 对象模板

内容社区 V1 定义 6 类主对象：

| 对象模板键 | 业务名称 | 建议 `object.type` | 关键事实 | 敏感信息 |
|---|---|---|---|---|
| `community_account` | 社区账号 | `community_account` | 账号状态、安全状态、注册时间、实名状态摘要 | 手机号、邮箱、证件信息不直接展示 |
| `community_content` | 内容/作品 | `community_content` | 标题、内容类型、发布状态、审核状态、可见性、发布时间 | 原文、草稿、未公开内容需授权 |
| `membership_entitlement` | 会员权益 | `membership_entitlement` | 会员等级、权益状态、生效时间、到期时间、可用权益 | 支付信息、账户标识脱敏 |
| `membership_order` | 会员订单 | `membership_order` | 商品名称、金额、支付状态、支付时间、权益开通状态 | 交易号、支付渠道脱敏 |
| `governance_case` | 治理/处罚案件 | `governance_case` | 案件类型、对象引用、违规类型、处理状态、处罚摘要、申诉期限 | 证据原文、举报人信息 |
| `merchant_collaboration` | 商家合作 | `merchant_collaboration` | 合作项目、合作类型、当前阶段、状态、负责队列 | 合同、结算、联系人信息 |

说明：

- “账号”通常是隐式上下文对象；当场景围绕内容或处罚案件时，以内容/案件为主对象，账号通过对象引用和事实投影带入。
- 会员权益和会员订单是相关但不同的对象；不能用同一个 `order` 对象强行承载所有会员场景。
- 治理/处罚案件不是“处罚文本”，而是可查询、可申诉的业务对象。
- 商家合作对象面向合作项目，不等同于商家账号。

### 5.2 核心场景

V1 先定义 11 个核心场景。`场景类型` 是产品分类，`执行模板` 是现有 `ScenarioConfig.template`。

| # | 模板键 | 场景名称 | 主对象 | 场景类型 | 执行模板 | 典型客户问题 | 主要承接 | 成熟度 |
|---|---|---|---|---|---|---|---|---|
| 1 | `account-status-query` | 账号状态查询 | `community_account` | 查询 | `query` | 我的账号现在是什么状态？为什么功能受限？ | 查询 + 知识 + 人工 | `ga` |
| 2 | `account-recovery-diagnosis` | 登录与账号找回诊断 | `community_account`（可选） | 诊断 | `consult` | 我登录不上，是密码、验证还是账号问题？ | 知识 + Agent + 人工 | `beta` |
| 3 | `account-penalty-query` | 账号处罚查询 | `governance_case` | 查询 | `query` | 我收到了什么处罚？处罚原因和期限是什么？ | 查询 + 人工 | `beta` |
| 4 | `account-penalty-appeal` | 账号处罚申诉 | `governance_case` | 办理 | `action` | 我要对账号处罚提出申诉 | 办理 + 人工，必须二次确认 | `alpha` |
| 5 | `content-status-query` | 内容状态查询 | `community_content` | 查询 | `query` | 我的内容为什么不能发布/不可见？ | 查询 + 人工 | `ga` |
| 6 | `content-violation-diagnosis` | 内容违规诊断 | `community_content` | 诊断 | `consult` | 这篇内容为什么被判定违规？ | 查询 + 知识 + Agent + 人工 | `beta` |
| 7 | `content-appeal` | 内容申诉办理 | `community_content` | 办理 | `action` | 我要对内容审核结果提出申诉 | 办理 + 人工，必须二次确认 | `alpha` |
| 8 | `membership-benefit-query` | 会员权益查询 | `membership_entitlement` | 查询 | `query` | 我的会员有哪些权益？什么时候到期？ | 查询 + 人工 | `ga` |
| 9 | `membership-renewal-diagnosis` | 会员续费/权益未到账诊断 | `membership_order` | 诊断 | `query` | 我续费了，为什么会员还没生效？ | 查询 + 知识 + Agent + 人工 | `beta` |
| 10 | `governance-report` | 举报与治理反馈 | `community_content` | 办理 | `action` | 我要举报一篇内容/一个账号 | 办理 + 治理队列，必须确认 | `beta` |
| 11 | `merchant-collaboration-service` | 商家合作进度与服务 | `merchant_collaboration` | 服务 | `query` | 我的合作项目现在到哪一步？ | 查询 + 人工合作队列 | `beta` |

场景设计原则：

1. 查询和办理分开。不要用“账号问题”一个大场景承载查询、申诉、找回、投诉四种任务。
2. 诊断不是新的运行时执行器，而是由知识、对象事实、Agent 和人工组合形成的产品类型。
3. 办理场景必须有 `confirm_action`，并在确认前展示对象、动作和可能后果。
4. 高风险办理场景（处罚申诉、内容申诉）先停留在 `alpha`，只允许模拟和内部验证。
5. 每个场景至少有一个无对象/对象失效/权限不足/人工兜底的出口。

### 5.3 推荐应用蓝图

Pack 提供一个默认应用蓝图，建议生成：

```text
应用名称：内容社区服务
应用标识：content-community-service

目录分类：
  账号与安全
  内容与创作
  会员与权益
  社区治理
  商家合作
  通用服务

默认纳入：
  account-status-query
  content-status-query
  membership-benefit-query

试点纳入：
  account-recovery-diagnosis
  account-penalty-query
  content-violation-diagnosis
  membership-renewal-diagnosis
  governance-report
  merchant-collaboration-service

模拟/内部验证：
  account-penalty-appeal
  content-appeal
```

应用蓝图只生成初始 `ServiceApplicationConfig`，不替代企业自己的目录、渠道和版本发布。

### 5.4 内容社区 V1 的验收基线

- 6 类对象模板都有字段、权限、脱敏和样例数据。
- 11 个场景都有完整 `ScenarioConfig`。
- 每个场景至少有 1 条样例和 1 条验收用例。
- 3 个 `ga` 场景可以在默认应用中使用。
- `beta` 场景可以进入指定应用灰度。
- 2 个 `alpha` 办理场景只能模拟或内部使用。
- 所有场景不出现行业分支代码。
- 所有办理场景在确认前不能显示“已成功”。

---

## 6. 如何避免 `if industry` 分支

### 6.1 原则

行业差异只能出现在**数据、模板、契约和注册表**中，不能出现在运行时业务分支中。

禁止：

```text
if pack_key == "content-community":
    call_content_api()
elif pack_key == "local-life":
    call_local_life_api()
```

禁止：

```text
if scenario_key == "account-penalty-appeal":
    special_account_appeal_flow()
```

### 6.2 四个通用扩展点

#### 扩展点 1：模板编译器

输入 Pack 清单，输出：

- 若干个 `ScenarioConfig`。
- 一个 `ServiceApplicationConfig` 初始蓝图。
- 样例和验收用例索引。

编译器只做结构转换和校验，不执行行业业务逻辑。

#### 扩展点 2：对象 Provider 注册表

通过稳定 `provider_key` 找到通用对象适配器：

```text
list_candidates(scene, customer, permission_scope)
get_object(object_ref, permission_scope)
project_facts(object_ref, fact_keys, audiences)
```

适配器返回统一对象引用和事实投影，不返回 UI 分支。

#### 扩展点 3：承接能力注册表

继续使用现有 `HandlerType`：

- `direct`
- `knowledge`
- `query`
- `action`
- `agent`
- `human`
- `tracking`

行业差异通过 `handler.tool`、`handler.queue` 和 `handler.config` 指向通用适配器/配置，不新增行业专属 handler 类型。

例如：

```text
handler.type = "query"
handler.tool = "community.account.status"
handler.config.provider_key = "community_account_provider"
```

运行时按 `handler.type` 和注册表查找，不按 Pack 名称分支。

#### 扩展点 4：策略模板组合

行业差异通过固定槽位组合：

- 入口
- 对象
- 事实
- 决策
- 推荐
- 承接
- 兜底
- 匹配
- 渠道

不允许引入任意表达式、脚本或“行业专属流程节点”。

### 6.3 运行时只读通用字段

运行时可以读：

- `ScenarioConfig.template`
- `object.mode` / `object.required` / `object.provider`
- `facts[].source`
- `decisions[].kind`
- `handlers[].type` / `handlers[].tool` / `handlers[].queue`
- `fallback_order`
- `matching`

运行时不应该读：

- `config.industry_pack.pack_key` 来改变处理逻辑。
- `name` 中包含“账号”“内容”等业务词来判断分支。
- 前端/后端硬编码行业名称。

`industry_pack` 可以用于展示、审计、升级和指标分组，但不能成为业务执行条件。

### 6.4 前端避免行业分支

前端应由模板/描述符提供：

- 对象类型显示名。
- 场景类型显示名。
- 字段显示名和格式化方式。
- 结果状态业务文案。
- 目录分类和场景卡片。

当前 `scenarioConfig.ts` 的硬编码标签可以作为 V1 的兼容回退，但不应继续扩展成每个行业一套 `switch`。最终应改为：

```text
业务描述符注册表
  → 对象标签
  → 场景类型标签
  → 字段格式化
  → 结果语义
```

前端只渲染配置，不判断“内容社区应该显示什么”。

---

## 7. 版本、覆盖、合并、发布门禁与回滚

### 7.1 版本模型

| 对象 | 版本字段 | 版本语义 |
|---|---|---|
| Pack | `pack_version` | SemVer；发布后不可修改 |
| Scenario Template | `template_version` | SemVer；发布后不可修改 |
| 企业场景 | `draft_revision` + `published_version` | 现有草稿修订号 + 不可变整数发布版本 |
| 服务应用 | `draft_revision` + `published_version` | 现有应用草稿修订号 + 不可变整数发布版本 |

兼容性建议：

- **Patch**：文案、标签、非行为性排序调整。
- **Minor**：新增可选事实、推荐问题、场景模板或非必需决策。
- **Major**：对象类型、事实来源、必需决策、承接契约或权限语义变化。

Major 升级不得自动合并到现有企业实例。

### 7.2 企业覆盖配置

企业可以覆盖：

- 场景显示名称和业务说明。
- 目录分类名称、排序和归属。
- 推荐问题文案和顺序。
- 人工队列、渠道和启用状态。
- 非敏感展示字段的顺序和格式化。
- 模拟样例和试点范围。
- 策略未锁定部分的阈值和文案。

企业不应覆盖：

- 权限范围和租户隔离语义。
- 事实来源和对象类型（除非新建模板）。
- 高风险动作必须确认的约束。
- 结果状态语义和审计要求。
- 平台不变量（关闭会话、黑名单、权限不足等）。
- 未注册 Provider 的工具调用。

V1 建议把可覆盖/不可覆盖集合写入 Pack 的 `protected` 元数据和场景 `config`，由校验器执行。

### 7.3 模板更新三方合并

升级流程：

```text
旧模板 v1
  + 企业实例（基于 v1 的覆盖）
  + 新模板 v2
  → 三方合并
  → 生成企业草稿
  → 冲突处理
  → 模拟验收
  → 发布门禁
  → 场景新版本 + 应用新版本
```

算法：

1. 读取企业实例记录中的 `base_template_version` 和 `template_digest`。
2. 确认租户仍持有对应旧模板版本；不存在则标记 `blocked`。
3. 计算企业相对旧模板的差异。
4. 将新模板变更应用到企业未修改字段。
5. 保留企业覆盖字段。
6. 同一字段两边都修改时标记 `conflicted`，不自动选边。
7. 新增强制字段插入安全默认值，并标记需要审核。
8. 模板删除的字段不直接物理删除，先标记废弃，避免企业历史数据丢失。
9. 重新执行 `ScenarioConfig`  schema 校验和发布门禁。

数组合并规则：

- `entries`、`facts`、`decisions`、`recommendations`、`handlers` 按稳定 `key` 合并。
- `options` 按 `value` 合并。
- 字符串列表（渠道、关键词）按集合合并或按模板声明的替换策略处理。
- 不使用数组下标做隐式合并。
- 合并策略必须是显式的模板元数据，不能依赖前端猜测。

### 7.4 发布门禁

场景发布和应用发布仍走现有 API，但需要增加 Pack 相关的校验。建议门禁分为阻断项和警告项。

| 门禁 | 检查内容 | 级别 |
|---|---|---|
| G1 Pack 清单 | `pack_key`、版本、模板版本和摘要完整且可解析 | 阻断 |
| G2 场景结构 | `ScenarioConfig` 校验通过，来源信息完整 | 阻断 |
| G3 对象契约 | 主对象类型、provider、权限和事实字段有效 | 阻断 |
| G4 承接契约 | 至少一个启用承接；`fallback_order` 有效；办理场景有确认 | 阻断 |
| G5 能力可用 | `ga`/`beta` 生产所需的 Provider 和工具已注册；缺失时只能模拟 | 阻断 |
| G6 模拟验收 | 必选验收用例全部通过，关键事实和状态符合预期 | 阻断 |
| G7 应用组合 | 场景引用存在、版本已发布、目录分类可解析、能力引用有效 | 阻断 |
| G8 覆盖冲突 | `merge_state=conflicted/blocked` 时禁止发布 | 阻断 |
| G9 高风险动作 | 申诉、举报、处罚等动作有二次确认和人工兜底 | 阻断 |
| G10 渠道 | 场景渠道是应用渠道和 Pack 支持渠道的子集 | 阻断 |
| G11 权限和脱敏 | 不出现明文敏感字段、越权对象和未注册工具 | 阻断 |
| G12 版本锁定 | 应用发布时将场景引用解析为具体版本 | 阻断 |

成熟度额外约束：

- `alpha`：只允许模拟；禁止进入生产发布。
- `beta`：允许指定应用/租户灰度；必须通过必选验收和人工兜底检查。
- `ga`：允许默认交付；必须通过全部阻断门禁和发布回归。

### 7.5 回滚策略

1. **包版本不可回滚。** Pack 发布后不可原地改版本；发现问题发布新版本或标记旧版本为 deprecated。
2. **企业场景回滚。** 使用现有场景版本回滚到之前的 `service_scenario_versions`。
3. **服务应用回滚。** 使用现有应用版本回滚到之前的 `service_application_versions`；应用版本保存具体场景版本，因此可整体恢复。
4. **禁止删除历史版本。** 历史模板、场景版本和应用版本是升级合并、审计和回滚所需资产。
5. **回滚后验证。** 回滚应用后，检查场景引用是否仍可解析、模拟轨迹是否恢复、人工队列是否可用。
6. **不把回滚等同于模板降级。** 包维护者的模板修复必须通过新模板版本和新场景实例发布，不能静默覆盖企业配置。

推荐操作顺序：

```text
停止新发布
  → 回滚服务应用版本
  → 必要时回滚场景版本
  → 验证客户入口和人工兜底
  → 记录事故和 Pack/Template 版本
  → 修复后重新走门禁
```

---

## 8. 分阶段实施切片

### 切片 A：架构骨架

目标：证明 Pack 可以编译成现有模型，而不新增行业表。

工作内容：

- 定义 Pack 清单模型和 JSON 资产目录规范。
- 实现清单校验、模板引用解析、摘要生成和 `ScenarioConfig` 编译。
- 在 `ScenarioConfig.config.industry_pack` 写入来源和覆盖元数据。
- 提供应用蓝图到 `ServiceApplicationConfig` 的编译。
- 建立样例和验收用例的引用校验。
- 为现有购物消费场景保留兼容路径。

验收标准：

- 不需要数据库迁移即可加载一个测试 Pack。
- 编译产物能通过现有 `ScenarioConfig` / `ServiceApplicationConfig` 校验。
- 现有购物消费演示不受影响。
- 同一个 Pack 能在测试租户中重复安装而不覆盖已有企业编辑。
- 编译结果不含行业专属运行时分支。

### 切片 B：内容社区包 V1

目标：交付第一个新增行业包的完整模板资产。

工作内容：

- 6 类对象模板。
- 11 个场景模板。
- 策略模板、样例数据、验收用例。
- 应用蓝图和目录分类。
- `ga` / `beta` / `alpha` 成熟度标记。
- 通用客户体验描述符。

验收标准：

- 3 个 `ga` 场景可实例化、模拟、发布并进入应用。
- 6 个 `beta` 场景可在试点应用中灰度，具备人工兜底。
- 2 个 `alpha` 场景只能模拟，发布门禁能阻断生产发布。
- 11 个场景均至少有一个失败/无对象/人工兜底路径。
- 不新增行业专属核心表。
- 不新增 `if industry` / `if pack_key` 业务分支。
- 现有购物消费应用回归通过。

### 切片 C：第二个行业包

目标：证明第二行业不是复制代码，而是复用同一套契约。

建议第二个包：**本地生活**。原因：

- 有订单、履约、预约、退款、人工客服等对象，可验证对象适配。
- 与内容社区的对象差异足够大，能暴露错误抽象。
- 可以作为电商和内容社区之间的中间复杂度。

最小场景建议：

- 订单状态查询。
- 预约/到店进度查询。
- 履约异常诊断。
- 退款/售后办理。
- 商家合作或人工服务。

验收标准：

- 第二个 Pack 至少 4 个场景，不修改核心场景/应用模型。
- 只新增对象模板、Provider 描述符、场景模板、策略和样例。
- 复用现有对象选择、事实投影、决策、确认、承接、人工兜底。
- 应用可以单独组合第二行业场景，不依赖内容社区。
- 没有任何运行时 `industry` 分支。
- 第二行业包可以在不修改场景前端页面的情况下通过配置进入统一体验。

### 切片 D：运营验证与治理

目标：让 Pack 可以长期升级、解释、审计和回滚。

工作内容：

- 三方合并和冲突状态。
- 模板升级预览。
- Pack/Template/Instance/Application 四层版本对比。
- 发布门禁结果展示。
- 场景和应用回滚演练。
- 按 Pack、模板、场景、对象类型、成熟度聚合指标。
- 模板废弃和迁移指引。

验收标准：

- 可以模拟一次模板升级并列出企业覆盖和冲突。
- 未修改字段自动采用新模板，企业覆盖字段保持不变。
- 冲突未解决时不能发布。
- 应用发布后场景版本被锁定。
- 回滚应用后可以恢复上一稳定组合。
- 能按 Pack 和模板查看场景量、解决率、转人工率和失败原因。
- 升级和回滚操作有审计记录。

---

## 9. 当前明确不建议做的内容

### 9.1 不做复杂流程设计器

不做：

- 任意拖拽节点和连线。
- 任意条件分支 DSL。
- 通用脚本执行器。
- 任意表单设计器。
- 让业务管理员配置底层路由表达式。

原因：

- 场景平台的核心是“场景、对象、事实、决策、承接”，不是流程图。
- 流程设计器会把行业差异变成不可治理的图形配置。
- 现有 `ScenarioConfig` 和固定模板已经能表达 V1 所需业务。

### 9.2 不做行业专属核心表

不建：

- `industry_packs`
- `industry_templates`
- `industry_objects`
- `industry_scenario_bindings`
- 每个行业一套 `xxx_service_scenarios`

原因：

- Pack 是版本化资产，不是租户运行时数据。
- 企业实例、版本、轨迹继续使用现有场景表。
- 行业专属表会让跨行业复用、统一发布和统一审计失效。

### 9.3 不提前大规模铺场景

V1 不做：

- 一次性接入十几个行业。
- 每个行业铺几十个场景。
- 没有真实 Provider、样例和验收就宣称可生产。
- 用静态 FAQ 填满目录。
- 把“订单问题”“账号问题”当作单一场景。

原则：

> 先用一个行业包验证模板、对象、策略和门禁，再扩展第二个行业包。

### 9.4 不做全自动行业识别

V1 不根据租户名称、消息内容或域名自动安装行业包。Pack 安装、模板实例化和应用组合必须由管理员显式操作，并保留审计。

---

## 10. 风险与待评审决策

| 风险/决策 | 说明 | V1 建议 |
|---|---|---|
| Pack 存放方式 | 数据库、对象存储还是代码资产 | 先使用代码/内容资产 + 清单校验，避免首批迁移 |
| 分类稳定键 | 现有应用目录只有名称 | V1 由 Pack 保存 `category_key`，应用仍用名称；后续再评估可选 `category_key` |
| 多对象场景 | 现有模型只有一个主对象 | V1 只允许一个主对象；关联对象只读引用 |
| Provider 缺失 | 模板可配置但真实系统未接入 | 缺失时仅模拟，生产发布门禁阻断 |
| 模板覆盖边界 | 企业可能改坏契约 | 通过 `protected` 元数据和校验器限制 |
| 旧模板保留 | 升级合并和回滚需要旧模板 | 发布版本不可删除，至少保留所有已发布 Pack/Template |
| 前端行业标签 | 当前标签是硬编码 | V1 保留兼容回退，后续转描述符注册表 |
| 应用混合 Pack | 一个应用可能组合多个行业 | V1 允许场景级混合，但默认应用蓝图以一个主 Pack 为主 |
| 人力成本 | 行业包需要持续维护 | 每个 Pack 设 owner、成熟度和废弃策略 |

---

## 11. 建议下一步代码任务

本轮只完成设计，不在本文件中修改业务代码。下一步建议按以下顺序落地：

1. **Pack 清单和编译器骨架**
   - 定义 Pack/Template 清单 schema。
   - 实现清单校验、模板引用解析、摘要生成。
   - 编译为现有 `ScenarioConfig` 和 `ServiceApplicationConfig`。

2. **内容社区 Pack 资产**
   - 先落 6 类对象模板和 3 个 `ga` 场景。
   - 再补 `beta` 场景和 2 个 `alpha` 办理场景。

3. **通用描述符和适配器注册**
   - 对象/场景/结果标签从硬编码转为描述符查找。
   - Provider、工具和人工队列通过注册表解析。

4. **升级合并和发布门禁**
   - 三方合并、冲突状态、验收用例执行。
   - 场景发布和应用发布增加 Pack 门禁。

5. **第二行业包验证**
   - 用本地生活验证“不修改核心模型即可新增行业”。
   - 若必须改核心模型，先复盘抽象，不直接加行业分支。

---

## 12. 参考实现文件

- `frontend/src/features/service-apps/ServiceAppsPage.tsx`
- `frontend/src/features/service-apps/ServiceCatalogManager.tsx`
- `frontend/src/features/service-scenarios/scenarioConfig.ts`
- `backend/src/agent_platform/business_capabilities/customer_service/scenarios/models.py`
- `backend/src/agent_platform/business_capabilities/customer_service/scenarios/service.py`
- `backend/src/agent_platform/business_capabilities/customer_service/scenarios/simulation.py`
- `backend/src/agent_platform/business_capabilities/customer_service/scenarios/seed.py`
- `backend/src/agent_platform/business_capabilities/customer_service/service_apps/models.py`
- `backend/src/agent_platform/business_capabilities/customer_service/service_apps/service.py`
- `backend/src/agent_platform/business_capabilities/customer_service/service_apps/seed.py`
- `backend/src/agent_platform/applications/seed_service_scenarios.py`
- `backend/migrations/versions/0054_service_scenarios.py`
- `backend/migrations/versions/0055_service_applications.py`

