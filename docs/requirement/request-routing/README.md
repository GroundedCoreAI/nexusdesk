# NexusDesk 请求路由 · 分阶段规划文档

> 状态：Phase 1 规划完成，待评审；Phase 2-4 仅列方向
> 创建：2026-10-30
> 修订：2026-10-30（初版）

## 背景

智能客服在一次对话里需要按问题复杂度选择处理方式：简单问题不该走完整 ReAct，复杂问题才需要多步推理与工具。当前实现存在三个具体问题：

1. **入口判定不可见。** `business_capabilities/customer_service/service.py::send()` 用连续 `if` 决定消息去向（`mode=closed` 第 129 行、`{"转人工","人工客服"}` 第 131 行、`mode in {human,waiting}` 第 142 行、黑名单转人工第 167 行），每个分支都不落任何记录。线上问"这条消息为什么没回复 / 为什么直接转人工了"，只能翻应用日志推断。
2. **转人工识别只覆盖中文。** 第 131 行硬编码 `{"转人工", "人工客服"}`。平台已有 7 个渠道适配器（企微 / 企微客服 / 飞书 / 钉钉 / Slack / Telegram / Discord）和 4 种语言（zh-CN / zh-TW / en / hi），海外用户在 WhatsApp、Telegram 说 `human` / `agent` 不会被识别，且该词表无法按租户配置。
3. **没有分流数据，无法判断后续档位值不值得做。** 简单问题（FAQ、订单状态查询）占比多少、延迟差多少，现在无法测量。在没有数据前引入轻量执行档位，存在"投入大、收益小"的风险。

本目录是请求路由的分阶段规划文档，供产品、研发按阶段独立评审。

## 产品案例研究

- [知乎 / 抖音 / 高德智能客服案例分析](case-studies/01-service-scenario-analysis-zhihu-douyin-amap.md)：从三个产品的客户端截图抽取服务场景、业务对象、上下文绑定、异常兜底与处理承接的共性，为后续 Direct / Interaction / 业务上下文设计提供产品依据

## 服务场景平台

- [服务场景平台文档](../service-scenario-platform/README.md)：配置化与平台化的产品模型、界面蓝图、核心契约和落地验收方案

## 总体原则

1. **先可见，再优化。** 第一阶段只增加决策观测，不改变任何既有行为；后续每个档位上线都必须能用第一阶段的数据证明收益。
2. **Core 只提供机制，不持有业务语义。** Core Platform 不得出现 `handoff` / `reject` / `退款` / `订单` 等业务词汇，也不得内置业务优先级；路由策略与业务处置由 Business Capabilities 实现。
3. **每阶段独立可上线、独立有价值。** Phase 1 即可上线，但它**不是零行为变更**：除决策记录外还包含人工请求规则扩展与两条 409 的返回契约调整（有意变更，已在阶段文档列明）；Phase 2 在 Phase 1 数据证明后才启动。
4. **执行策略与授权分离。** 路由决定"怎么执行"，是否允许由 `core_platform/policy_harness` 在实际执行时判定；Core 只做 `profile` 范围校验，不重复授权。
5. **空实现等价现状。** 任何阶段关闭开关后，系统行为必须与改造前逐条一致，且可用自动化测试证明 diff 为零。

## 业务处理路径模型

一条消息进入系统后被分配到哪种处理方式，称为一条**路径**。路径**不是**互斥的执行模式枚举——它们分属三个维度，组合使用：

| 维度 | 路径 | 含义 |
|---|---|---|
| 业务处置 | Reject / Handoff / Defer / **Continue** | 消息是否继续由机器人处理 |
| 执行档位 | Direct / Lightweight / Agent | `Continue` 时用哪种执行能力 |
| 过程控制 | Resume / Escalate | 跨轮次恢复既有任务 / 执行中改变处理主体或策略 |

组合关系（关键：它们不是并列的八个值）：

- 只有 `Continue` 才谈执行档位，在 Direct / Lightweight / Agent 之间选择
- `Resume` 之后可能进入 Lightweight，也可能进入 Agent
- `Escalate` 之后可能 Handoff，也可能升级到更强的 Agent Profile
- `Agent` 执行失败不一定 Handoff，可能重试、降级或要求用户补充信息
- `Clarify`（澄清）**不是路径**，而是任务状态 `waiting_user` 的交互动作；用户补充信息后走 `Resume`

**因此决策记录用「处置 + 档位 + 过程控制」三列表达，不写成单一 `RouteMode` 枚举。** 这是本主题的核心设计约束：一旦写成 8 值枚举，路由就把客服业务语义固化成平台枚举了。

目标路径共 8 条：Reject、Handoff、Defer、Direct、Lightweight、Agent、Resume、Escalate。**这是目标模型，不代表当前已实现。** 现状只实现了 4 种处置（Reject / Handoff / Defer / Continue→Agent），`Active` 执行档位只有 Agent 一种；Direct、Lightweight、Resume、Escalate 均未实现（详见 `01-business-goals.md` 的范围说明）。

## 阶段路线图

| 阶段 | 主题 | 新增路径 | 核心价值 | 难度 | 预估 | 目录 |
|---|---|---|---|---|---|---|
| Phase 1 | 路由决策可见 | 现有 4 处置（Reject / Handoff / Defer / Continue→Agent） | 决策可查询；人工请求规则扩展；两条 409 不再被无效重试 | 低 | ~1 周 | [phase-1-routing-decision-trace/](phase-1-routing-decision-trace/) |
| Phase 2 | Direct 档（确定性回答） | Direct | 简单问题零模型、零工具；优先用于系统话术回执 | 中 | ~1.5 周 | 待规划 |
| Phase 3 | Lightweight 档 + 执行升级 | Lightweight、Escalate | 检索 + 受限工具；引入 Core 的 provider host 与执行档位循环 | 高 | ~2-3 周 | 待规划 |
| Phase 4 | 会话内任务生命周期 | Resume | 多轮任务的创建、延续、澄清、切换与恢复 | 高 | ~2-3 周 | 待规划 |

各阶段目录下统一包含的文档：

- `01-business-goals.md` — 业务目标、价值、成功指标、范围边界
- `02-requirements.md` — 用户故事、功能需求、验收标准
- `03-technical-design.md` — 数据模型、代码改动点、接口设计、测试方案概要
- `04-test-plan.md` — 测试方案：单元/集成用例、通用核对项、出口准则
- `05-acceptance-plan.md` — 验收方案：AC 逐条验收步骤、业务指标测量、合规核对与签字
- `06-test-report.md` — 测试报告（测试完成后生成）
- `07-acceptance-report.md` — 验收报告（验收完成后生成）
- `08-implementation-breakdown.md` — 实施拆解与裁定（可选，大型阶段）

## 明确不做的（整体边界）

- **不做独立微服务**：请求路由是模块化单体内部的关注点，不引入新部署单元。
- **不做通用流程设计器 / 规则 DSL**：规则以结构化配置与代码实现，避免自研 DSL 的维护成本。
- **不做通用 Task Engine**：任务生命周期属于会话域；客服任务规则属于客服能力。不在 Core 建包含退款、订单、工单概念的通用任务引擎。
- **不让模型决定工具权限**：路由产出的是执行计划，授权始终由 `policy_harness` 执行时判定。
- **不以模型分类替代确定性规则**：会话关闭、用户明确要求人工、黑名单等判断必须优先于模型分类，且先于模型执行。
- **不为每个客服意图建独立 Runtime**：档位是执行策略，不是 Runtime 实例。
- **Phase 1 不发事件、不建 Outbox**：`routing.decision_created` 暂无消费者，且可靠投递需要事件总线与 Outbox 支撑；等真有消费者再评估。

## Review 指引

- 每个阶段可独立评审、独立排期；**必须先完成 Phase 1 并拿到数据，再评审 Phase 2**。
- 评审重点：
  - Phase 1：`send()` 判定序列与原分支是否动作等价（FR-3/FR-4 两处有意变更除外）；决策写入是否用 SAVEPOINT 隔离、是否在既有事务与锁序之内；两条 409 的契约改动是否只影响 `send()` 内部而不改变对外状态码。
  - Phase 2：`direct` 档的适用边界（哪些意图允许确定性回答）、误分流风险的兜底。
  - Phase 3：Core 是否只增加 provider host 与执行档位，未新增业务枚举、未新增业务优先级；`routers` 贡献 kind 是否复用 `extension_platform` 既有注册体系。
  - Phase 4：任务表归属（会话域）与客服任务规则的边界；任务状态与 `runtime_runs` 状态不合并。
