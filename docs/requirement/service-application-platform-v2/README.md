# NexusDesk 服务应用平台 v2 · 分阶段规划文档

> 状态：Phase 1 已进入代码实现，核心契约、前后端与迁移已完成；定向测试与静态门禁通过，全量 CI、quickstart 空卷验证和人工 UAT 待执行
> 创建：2026-11-11
> 依据：现有 `service_apps` / `scenarios` / `providers` / `industry_packs` / `channels` 代码核查（仓库 `feat/customer-service-optimization`，迁移至 `0057_industry_pack_runtime`）及已确认的产品讨论

## 背景

当前系统在 Agent 之上增加了一层服务应用，但该层仍混合了两套模型：

1. `service_applications` 的 v1 配置由 `scenarios + capabilities + default_execution_order` 组成，Agent 只是 `capability` 的一种类型，不是应用级绑定。
2. `service_provider_registry` 按租户/业务/工作区隔离，没有 `application_id`；真实 HTTP URL、Header 与凭据仍在 Tool Gateway 的 `registered_tools` / `tool_credentials` 中。
3. 场景可以通过 `ScenarioToolBridge` 引用全局 tool、queue、provider，容易绕过应用边界。
4. `channels` 与 `runtime_conversations` 直接绑定 `agent_id`，入站消息没有固定到某个服务应用发布版本。
5. 行业模板安装、升级预览、冲突合并会形成第二套生命周期，和“复制标准案例后由用户拥有”的产品逻辑冲突。
6. 前端 `ServiceAppsPage.tsx` 实测 2384 行，并同时承载应用、场景、能力、调试、发布与行业入口，概念和交互过重。

本目录定义服务应用平台 v2 的收敛方案，供产品、后端、前端、QA 按同一份基线评审和实现。

## 最终架构

```text
客户渠道
  ↓ 固定应用发布版本
已发布的服务应用版本
  ↓ 绑定 Agent 版本
Agent（Prompt / 模型 / 知识 / 记忆 / 评测）
  ↓ 仅能看到本应用授权的技能
应用技能（Skill）
  ↓ 解析本应用连接
应用连接（Connection）/ 知识库 / 人工队列
```

核心边界：

1. **服务应用是业务交付主体**，不从 Agent 管理回退。
2. **Agent 是推理与执行底座**，不拥有应用级 URL、鉴权和业务技能。
3. **技能直接属于服务应用**；同名技能在不同应用中可指向不同连接。
4. **连接随应用隔离**；相同 URL 也不默认共享实例、凭据或授权。
5. **渠道绑定应用发布版本**；入站事件、会话与运行都保留应用版本快照。
6. **不增加外置 Router**；仍由 Agent 循环调用应用授权的技能。
7. **确定性规则守住安全边界**：人工确认、金额/权限限制、幂等、超时、降级和结果验证不由模型自由发挥。

## 概念收敛

用户界面只保留五个主概念：

- 服务应用
- Agent
- 技能
- 应用连接
- 客户渠道

以下旧概念从新代码、新 API 和新 UI 中删除：

- 场景、业务编排、执行能力、接入能力
- Provider、行业包安装实例、升级预览、升级记录
- 业务对象 Template
- Scenario Handler、ScenarioToolBridge

旧文档可保留历史说明，但不再作为当前产品或实现依据。

## 阶段路线图

| 阶段 | 主题 | 核心价值 | 难度 | 预估 | 目录 |
|---|---|---|---|---|---|
| Phase 1 | 技能中心的应用运行时 | 应用级 Agent 绑定、应用技能/连接、不可变发布、渠道按版本路由、示例复制与 clean-break | 高 | ~3～4 周 | [phase-1-skill-centric-runtime/](phase-1-skill-centric-runtime/) |
| Phase 2 | 运营增强 | 在 Phase 1 验收后，按真实使用数据增强版本灰度、批量渠道切换与高级观测；当前不展开设计 | 中 | 待排期 | 待创建 |

Phase 1 目录统一包含：

- `01-business-goals.md` — 业务目标、成功指标、范围与风险
- `02-requirements.md` — 用户故事、功能/非功能需求与验收标准
- `03-technical-design.md` — 数据模型、迁移、接口、运行时与前后端改造
- `04-test-plan.md` — UT / IT / CM 用例、回归范围与出口准则
- `05-acceptance-plan.md` — AC 逐条验收、业务指标、合规与签字
- `08-implementation-breakdown.md` — 任务拆解、依赖、现状差异与裁定
- `06-test-report.md` / `07-acceptance-report.md` — 分别在实际测试、验收结束后生成

## 明确不做的（整体边界）

- **不做通用拖拽工作流设计器**：服务应用不是低代码平台，复杂业务仍由 Agent + 明确技能完成。
- **不做外置应用路由器**：不新增独立意图分类服务或第二套编排运行时。
- **不做通用 Agent 平台扩张**：Prompt、模型、知识、记忆和评测继续归 Agent；业务交付归服务应用。
- **不做旧数据迁移与双读双写**：项目尚未正式上线，允许清空开发数据；旧概念不做兼容层。
- **不做行业包安装/升级生命周期**：标准案例只以不可变示例应用出现，用户复制后拥有自己的副本。
- **不把凭据写入发布 JSON、API 响应、审计或日志**：只保存密文引用。
- **不新增业务对象 Template 体系**：业务对象如仍需存在，应作为某个技能或连接的数据契约，而不是平台级新概念。

## Review 指引

各阶段可独立评审。Phase 1 评审重点：

1. “服务应用 / Agent / 技能 / 应用连接 / 客户渠道”五概念是否足以表达真实业务，不再引入中间层。
2. 同名技能在不同应用中连接不同 URL、凭据和规则是否被数据模型与运行时彻底隔离。
3. 发布版本是否真正不可变；渠道、入站 outbox、会话与运行是否都固定应用版本。
4. clean-break 是否彻底：旧 API、旧 UI、旧表引用与旧测试是否全部删除。
5. 标准案例“不可编辑、复制后拥有、重启不覆盖”的边界是否成立。
6. 技能安全规则是否覆盖人工确认、金额/权限、幂等、超时、降级和结果验证。
