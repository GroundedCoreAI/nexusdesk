# Phase 6-2 · Execution Governance Observability — Acceptance Report

> 状态：已验收
> 验收依据：`05-acceptance-plan.md`（A-1~A-10、M-1~M-3、C-1~C-6、结论规则 §8）；测试执行以 `04-test-plan.md` 为准。
> 证据报告：`06-test-report.md`（状态：已执行）。

## 0. 单一验收记录（仅此一份，不虚构多角色签字）

| 字段 | 内容 |
|---|---|
| 验收负责人 | 待用户确认（按 05 §1 / §7.3 由用户指定；不虚构姓名或产品/QA/业务/财务/安全角色） |
| 执行人 | 独立验收子代理 accept-gov（自动化独立复核；按 05 §1 验收负责人与执行人可不同，负责人字段待用户确认） |
| 验收日期 | 2026-11-23 |
| 目标 SHA | `19ad42d1e32f46e1e477cc1c292e1e9474e1ec52`（分支 `feat/phase-6-2-execution-governance`） |
| 判定 | **通过（GO）** |
| 证据 / 遗留项 | 见本报告第 1~4 节与 `06-test-report.md`；无 P0 / P1 遗留；范围外项见第 5 节 |
| 高风险能力授权 | **不授权**（见第 6 节声明 / R-10） |

> 版本说明：被测实现位于目标 HEAD 之上的工作区（未提交）状态，即实际验收对象；HEAD SHA 标识版本基线。若后续提交改变该实现，需对受影响项重新验收。

---

## 1. 功能验收场景 A-1~A-10（对应 AC-1~AC-10）

证据统一链接：`06-test-report.md`。每条均记录环境、fixture/攻击点、实际结果与判定。

| # | 场景（摘要） | 关键证据（测试编号 / 命令结果） | 判定 |
|---|---|---|---|
| A-1 | 统一治理 API 权限与错误码：仅 admin 得分页数据；非 admin 403 `insufficient_role`；无效过滤/分页 400；无 Secret | UT-1/UT-2/UT-3/UT-4/UT-5（15 passed 子集）；FE-8；7 端点源码全 `user: Admin`；canary grep 零出现 | **pass** |
| A-2 | Fencing 拒绝查询：过滤/分页/JOIN `runtime_runs` 正确，孤立标注部署级，无 Secret | UT-3(fencing)/UT-9；IT-2；FE-3；PG 9/9 | **pass** |
| A-3 | Worker 丢失与恢复态：复用 `GET /notifications/checklist`、`GET /notifications`，明示部署级；未建事件历史表；Reader 行为不变 | FE-4、FE-6；CM-6；`platform_routes.py` diff 无新通知历史表、无 Reader 路由改动 | **pass** |
| A-4 | 清理失败与取消未确认：两类均返回；公开 `RunView` 零变更；状态不伪报 cancelled | UT-4(cleanup)；IT-3；FE-9；`schemas.py` 工作区零修改；`test_ut10` / `test_it3` 断言 RunView 字段集合不变 | **pass** |
| A-5 | Outbox lag 与投递失败：pending 数/滞留秒/`last_error`/24h published；无发布副作用；无 Prometheus | UT-5(outbox)；IT-4；FE-3；CM-6 | **pass** |
| A-6 | SSE 重放缺口：409 `event_replay_gap` + `X-Event-Retention-Floor`；有界缺口事件落库；契约零变更；head 重验 | UT-12、UT-13；IT-1、IT-6；CM-5；FE-9；`runtime_routes.py` diff 仅 best-effort 审计且被 try/except 包裹，409 三要素未改 | **pass** |
| A-7 | usage 冲突与修正链：链与重复来源可见、按 tenant 过滤；聚合语义不变 | UT-6；IT-5；FE-3 | **pass** |
| A-8 | parser 诊断（不含原始样本）：五类计数/趋势 + 有界脱敏原因码；样本与 Secret 零出现；collector 已接线 | UT-8、UT-14；IT-1、IT-7；CM-5；FE-4、FE-8；IT-7 经真实 mapper 驱动反 no-op 接线；`0073` 表无 sample 字段 | **pass** |
| A-9 | 凭据吊销与审计：revoked 状态可见；审计行按 tenant 过滤；`public_metadata()` 无 Secret；越权 403 | UT-7；IT-8；FE-4、FE-8；`test_ut13` 断言响应无 `secret` 文本 | **pass** |
| A-10 | 前端执行治理 tab：仅 admin 可见/挂载；空状态 fail-closed；四语齐平；hashRouter/App/RunView/SSE 零变更 | FE-1、FE-2、FE-5、FE-6、FE-7、FE-8、FE-9、FE-10；CM-2、CM-3、CM-4；`hashRouter.ts`/`App.tsx`/`schemas.py` 工作区零修改 | **pass** |

**A 类小结：A-1~A-10 全部 pass，无 pending_env、无 fail。**

---

## 2. 关键人工检查 M-1~M-3

按 05 §4 以「代码审阅 + Playwright 断言证据」等价方式执行（如实记录方式，未另设客户端/业务代表角色）。

| # | 检查 | 执行方式 | 结果 / 证据 | 判定 |
|---|---|---|---|---|
| M-1 | tab 切换、治理请求发出时机、过滤/分页交互；非 admin 不触发请求；空状态与错误 fail-closed；不伪造恢复态/成功 | Playwright 断言（FE-1/2/3/5/6/7/8）：`FE-2` 断言 viewer 与总览 tab 零治理请求；`FE-3` 断言进入挂载/离开卸载；`FE-7`/`FE-8` 断言空响应与全端点 403 下 fail-closed | 非 admin 零请求；空/错误均 fail-closed；无伪造恢复态 | **pass（等价自动化）** |
| M-2 | 治理面板提示与错误文案不含 Secret / host 细节，保留运维关联信息 | 代码审阅：`ExecutionGovernancePanel.tsx` 含 canary/secret 形状 token 的 DOM 脱敏替换（→ `已隐藏`），仅展示 reason_code / 关联 id；`client.ts` 标注原因码「never a secret or a path」；canary grep 零出现；`FE-9` 断言 canary 零进 DOM | 文案无 Secret / host 路径，保留 reason_code / 关联 id | **pass（代码审阅 + 等价自动化）** |
| M-3 | 四语切换文案与空状态齐平；缺键被 `check:i18n` 拦截 | `FE-10` 四语切换断言 + `CM-2`（`check:i18n`：`Verified 2690 translations in zh-CN, zh-TW, en, hi`） | 四语齐平、语义一致，缺键由 CI 拦截 | **pass（等价自动化）** |

**M 类小结：M-1~M-3 完成或有等价自动化证据，满足 C-6。**

---

## 3. 验收门槛 C-1~C-6（逐字沿用批准范围基线）

| 门槛 | 判定内容 | 判定与证据 | 结论 |
|---|---|---|---|
| C-1 功能语义 | A-1~A-10 步骤与预期成立；七端点与八类面板按 FR 返回呈现；统一错误码与空状态符合约束 | A-1~A-10 全 pass；UT/IT/FE 独立结论全通过；`06-test-report.md` | **pass** |
| C-2 租户/权限隔离 | 新增端点仅 admin，非 admin 403 `insufficient_role`；无 tenant_id 表 JOIN `runtime_runs`；跨租户默认拒绝；worker_heartbeats 明示部署级 | 7 端点源码全 `user: Admin`（platform_routes.py:1887/1972/2067/2171/2265/2343/2427）；UT-1/2/9；IT-2/8；A-1/2/7/9 均 pass | **pass** |
| C-3 Secret 与脱敏 | 治理响应、`public_metadata()`、诊断与 UI 均无 Secret；parser 原始样本与 Secret 零出现，仅分类计数与有界脱敏原因码 | UT-10/8；IT-7；FE-9；CM-6；`0073` 表无 sample 列；`test_ut13` 断言响应无 secret 文本；canary grep 零出现；A-1/8/9 pass | **pass** |
| C-4 数据完整性与迁移 | head 单一重验；0072/0073 一致；历史迁移零改；409 缺口与 parser sink 有界落库；分页/JOIN 口径正确；并发唯一约束生效 | `alembic heads`=唯一 `0073_execution_parser_diag`；链 0071→0072→0073；历史 0001~0071 工作区零修改；UT-13/14；IT-1/2/5/6/7；CM-5；A-6/8 pass | **pass** |
| C-5 兼容性 | 公开 `RunView` 字段零变更；SSE `id=sequence`/`event_replay_gap`/`X-Event-Retention-Floor` 零变更；hashRouter 与全局导航零变更；Reader 的 `GET /notifications/*` 不变；无 Prometheus | `schemas.py`/`hashRouter.ts`/`App.tsx` 工作区零修改（git diff/status 确认）；`runtime_routes.py` diff 仅新增被 try/except 包裹的 best-effort 审计，409 status/body/header 未改（IT-6 断言零 diff）；UT-4/12；IT-3/6；FE-9/10；CM-1/6 | **pass** |
| C-6 无 P0/P1 且单一验收记录 | 不存在 P0/P1；M-1~M-3 完成或有等价证据；仅单一验收负责人记录，不虚构多角色签字 | 全部用例通过，无 P0/P1（第 0 节记录）；M-1~M-3 等价证据齐备（第 2 节）；本报告为唯一验收记录，负责人字段待用户确认、不虚构角色 | **pass** |

**门槛小结：C-1~C-6 全部 pass。**

---

## 4. 结论规则判定（05 §8）

| 规则 | 判定 |
|---|---|
| 阶段通过：A/C 全通过、M 完成或有等价证据、无 P0/P1、仅单一记录、不虚构角色 | **满足** → 判定「通过（GO）」 |
| 有条件通过：仅剩非安全/非权限/非 Secret/非数据完整性/非兼容性 P2/P3 | 不适用（无遗留 P2/P3） |
| 不通过：任一门槛失败 / 越权 / Secret 外泄 / 静默数据缺口 / 公开契约变更 / 功能安全准则失败 | 未触发（均未发现） |
| pending_env 不改写为 pass | 遵守（范围内无 pending_env） |
| 不得虚构角色 | 遵守（负责人字段待用户确认） |
| 不得推断状态 | 遵守（结论仅在报告生成、证据齐备、无 P0/P1 后给出） |

---

## 5. 范围限定与遗留项

- **范围外、不阻塞（05 §6）**：性能基线（p50/p95、Outbox 滞留阈值、容量样本）、真实不可信执行环境、高风险能力启用均不作为本阶段门槛，不产生 `pending_env`。
- **已知环境相关失败**：`test_real_codex_consumes_the_prompt_through_the_host`（`backend/tests/agent_execution/test_host_stdin_delivery.py`）需真实 Codex CLI；该文件未被阶段 6-2 修改，属真实 Provider 范围外，按 05 §6 不阻塞，不计入门槛。
- **P0 / P1 遗留**：无。**P2 / P3 遗留**：无。
- **issue / PR 号**：不登记（尚无）。

---

## 6. 不授权高风险能力声明（R-10）

阶段性验收通过**不授权**以下任何能力或动作：不可信多租户开放、生产 Codex 路由、生产放行。相关批准须在阶段外单独取得。本阶段治理信号仅由确定性 fixture、PG 分片与 Playwright mock harness 产生；可观测性面板为只读管理面，不改变执行语义、不触发发布副作用、不引入新监控依赖。

---

## 7. 最终判定

> **GO — 验收通过。** A-1~A-10、M-1~M-3、C-1~C-6 全部满足，范围内无 skip / pending_env、无 P0 / P1，无越权、无 Secret 外泄、无公开契约变更。阶段通过不授权高风险能力启用（见第 6 节）。
