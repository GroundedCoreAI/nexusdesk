# Phase 0 · 基线与盘点 — 测试方案

> 状态：进行中（2026-11-07 开始基线建设）
> 创建：2026-11-02
> 依据：`02-requirements.md`（FR-1–FR-6、AC-1–AC-6）、`03-technical-design.md`（无迁移、实际状态机、兼容 fixture、双跑基线）

## 1. 测试范围与原则

**范围**：现状代码/测试盘点、Run 生命周期与事件、Agent 配置兼容样本、ReAct/Worker/PostgreSQL/SSE 回归、基线度量与重构检查清单。

**原则**：

1. **以现状为准**：先保存现有结果再补测试；发现缺陷不通过改断言制造兼容。
2. **确定性**：外部 Engine/模型不进入必过路径；时间、取消与租约竞态用可控任务和直接数据构造。
3. **证据双向可溯**：状态/配置结论既有代码引用，也有测试或运行证据；skip/xfail 不得隐藏覆盖空白。
4. **样本最小化**：合法与非法样本均脱敏；fixture 不因为未来默认值而被预先改写。
5. **无生产变更**：本阶段无数据库迁移和运行时开关，回滚 diff 检查针对测试/文档改动本身。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 单测 | Engine/Worker 纯逻辑、错误映射、配置模型与 fixture 清单校验 |
| 集成（项目既有 PostgreSQL fixture） | claim/heartbeat/reap/finish/cancel、事件持久化、发布快照和 SSE |
| mock/demo 模型与工具 | 确定性 ReAct 成功、预算、异常和取消路径 |
| 干净 CI 环境（连续两次） | 测试计数、覆盖率、耗时、skip/xfail/flaky 的可复现基线 |

**数据构造约定**：保留现有测试 ID 和 fixture 风格；新增样本置于 `backend/tests/fixtures/agent_execution_baseline/`，附字段覆盖与来源类别清单。租约过期、排队超时、取消竞争直接构造数据库状态或可控同步原语，不依赖真实长等待。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P0-UT-01 | RuntimeEngine 正常消息—工具循环 | 固定 output/history/事件形状，结果与现状一致 | FR-2/FR-4 |
| P0-UT-02 | 模型/工具异常、预算耗尽与空输出 | 错误码和输出形状与现状一致，不泄漏 provider 原文 | FR-2/FR-4 |
| P0-UT-03 | Worker 对 factory/runtime 的调用与 emit 分流 | 持久事件走 Repository，`model.delta` 仅走 notifier | FR-1/FR-2 |
| P0-UT-04 | 执行期间取消与 watcher 清理 | 取消语义保持，协程无未回收任务 | FR-2/FR-4 |
| P0-UT-05 | 合法历史/缺省/边界 AgentConfig fixture | 现有默认值、规范化和校验结果逐样本一致，源 fixture 不变 | FR-3/AC-3 |
| P0-UT-06 | 未知或非法配置字段 | 按现有模型明确接受或拒绝，结果登记，不自动映射未来 Engine | FR-3 |
| P0-UT-07 | fixture 清单与文件一一对应 | 每个 fixture 有版本、覆盖字段、预期和脱敏标记，无孤立文件 | FR-3/FR-6 |
| P0-UT-08 | 标识与 Run/Execution 示例静态核对 | `(react,native,v1)` 格式一致，无 Task 表或 Worker 引擎分支假设 | FR-5/AC-5 |
| P0-UT-09 | 基线结果计数解析 | 通过/失败/skip/xfail 和耗时完整记录，缺失值不是 0 | FR-6 |
| P0-UT-10 | 两次基线结果差异比较 | 非确定用例被显式列出，不因数量相同而忽略节点级变化 | FR-6/AC-4 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P0-IT-01 | Run 创建→claim→正常 finish | `queued→running→completed`，owner/lease/output/history 与终态事件符合现状 | AC-1/AC-2 |
| P0-IT-02 | queued 与 running 两种取消 | queued 直接终态；running 取消后迟到成功不能覆盖 | AC-2/FR-2 |
| P0-IT-03 | 执行超时、RuntimeFault 与普通异常 | failed 与既有 error code、终态事件一致 | FR-2/FR-4 |
| P0-IT-04 | lease 过期、heartbeat 失租与 reaper | 实际终态和 `worker_lost` 等语义有证据，不失租提交 | AC-2 |
| P0-IT-05 | queued 超时与取消竞争 | 按现有优先级进入唯一合法终态，只产生一次有效终态提交 | FR-2 |
| P0-IT-06 | 重复 finish、迟到 append 和并发 Worker | 条件更新拒绝非法写入，事件序号与 Run 状态一致 | AC-2/FR-4 |
| P0-IT-07 | 持久事件与 SSE `after` 重放 | 事件顺序、游标边界、终态事件和瞬态 delta 差异与现状一致 | FR-2/FR-4 |
| P0-IT-08 | 历史草稿→发布→快照→按版本读取 | 合法 fixture 走完整链路，历史版本不被改写，跨租户不可读 | AC-3 |
| P0-IT-09 | 完整 mock ReAct 执行与内存注入现状 | 成功/失败/取消结果及 summary/memory 调用保持基线 | FR-1/FR-4 |
| P0-IT-10 | 同一提交干净环境双跑并收集覆盖率 | 节点级结果一致，计数/耗时/覆盖率及环境信息齐全 | AC-4/AC-6 |

## 5. 通用核对项

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P0-CM-01 | 提交与证据完整性 | 文档记录 SHA/工作树；核心结论均有 `path:line` 或测试节点，无无主关键 unknown | FR-1/AC-1 |
| P0-CM-02 | 无生产模型/迁移漂移 | diff 不含生产执行重构、Agent/Run JSONB 改写或 Alembic 迁移 | FR-3/范围 |
| P0-CM-03 | fixture 与输出敏感信息扫描 | 无 Token、连接串、客户 PII；例外经安全评审且最小化 | FR-3/非功能 |
| P0-CM-04 | 基线确定性 | 两次节点结果一致；skip/xfail/flaky 有独立原因、owner 和处置 | AC-4 |
| P0-CM-05 | Phase 1 入口清单 | 标识、覆盖率、耗时、缺陷、分阶段回归映射完整；P0/P1 阻断为 0 | FR-5/FR-6/AC-6 |

## 6. 回归范围

- 现有 `test_runtime_engine.py`、`test_runtime_postgres.py`、`test_runtime_availability.py`、`test_runtime_scope.py`；
- Agent Config 草稿/发布/版本/回滚、Run API、事件/SSE、内存注入与模型/工具网关的相关测试；
- 现有 CI 的 lint、迁移检查和受影响后端套件仍须通过；本阶段不新增迁移，不代表可跳过仓库既有迁移检查。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 基线样本泄密；测试破坏数据；现状无法构建或核心执行无法测量 | 停止后续阶段，修复并重建干净基线 |
| P1 严重 | 核心路径无证据；结果非确定；历史合法配置无法加载；用弱断言掩盖失败 | Phase 1 前关闭并回归 |
| P2 一般 | 非关键覆盖空白、文档映射不完整、可解释的性能波动 | 有 owner/期限，经评审可不阻断 |
| P3 轻微 | 格式、命名、非关键报告可读性问题 | 排期修复 |

**出口准则**：P0-UT/IT/CM 全通过；AC-1–AC-6 在目标提交复现；双跑节点级一致；既有适用回归无新增失败；所有 skip/xfail 有解释；无 P0/P1 未关闭。未执行或未安装的环境项标 `pending_env`，不得写成通过。
