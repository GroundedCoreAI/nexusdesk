# Phase 2 · React Provider 与执行编排器 — 验收报告

> 状态：已完成本地自动化辅助验收（结论：**有条件通过**；生产性能、真实部署证据与人工签字未完成）
> 创建：2026-11-11
> 依据：`05-acceptance-plan.md`（A1～A9、业务与性能指标、C1～C5）、`06-test-report.md`（本地功能出口通过，生产性能子指标 `pending_env`）
> 执行：独立子代理自动化辅助验收（非人工签字）；执行日期：2026-11-11

## 1. 验收组织与范围说明

本轮是**受控 fixtures 下的本地自动化辅助验收与文档/配置核对**，不是人工 UAT、生产 canary、生产性能验收或任何角色的人工批准。A1～A9 与 C1～C5 均逐项执行了对应的测试操作、证据复核或只读检查，并给出独立判定；`PASS(local controlled)` 仅表示本地受控范围满足 05 的判据，不能外推为生产通过。

**前置条件核对**：`06-test-report.md` §2～§5、§10 记录 P2-UT-01～24、P2-IT-01～20、P2-CM-01～08 全部有实际结果，功能主用例通过，off canonical diff 为零，无开放 P0/P1；CM08 的证据诚信/测量边界通过，真实生产性能为 `pending_env`。本轮使用同一受控 fixtures、专用租户与独立 PG17，不使用生产客户数据或凭据，不创建或修改 seed。

**后续任务边界**：T10/T11 尚未执行。本轮没有创建 Phase 2 示例种子，没有启动 quickstart 栈，没有执行实际容器 off/on、双 SSE 或 seed 验证；这些只能由 T10 后的 T11 实施并向本报告追加“验收后验证附录”，不得改写本轮证据。

> **证据生命周期**：`/Users/jackchow/.claude/jobs/a2066544/tmp` 是本 job 的临时目录，不是持久仓库证据区。最终资源清理后，T8/T9 原始日志、性能 JSON 和本报告中的临时链接会失效，原始证据不可复核；附录只保留关键摘要。本轮没有 CI artifacts 或其他经批准的持久归档，不暗示证据已长期归档。

## 2. 验收环境

| 环境 | 配置与证据边界 | 承担场景 |
|---|---|---|
| 本机 | Darwin 27.0.0；Python 3.11.9；uv；受控 demo/mock、Runtime/Adapter、Event/gate | A1～A7 的身份、对等、事件、错误、取消与调用链；A8 配置；C2/C3 |
| 独立 Docker PostgreSQL | 既有专用 `pgvector/pgvector:pg17` 容器 `nexusdesk-phase2-t6b-pg17-2b1d85c1afb9`；受限 env 静默注入，未打印连接串 | A1/A2/A4/A6～A9 的真实 asyncpg、Memory、SSE、竞态、Lease、混合 Worker 与迁移 |
| ASGI/FastAPI | `httpx.ASGITransport` 调用真实内部/Open 路由 | A4/A9、C1 的 400/422 矩阵、合法 max/strict replay、drain、delta、tool.replay 与脱敏 |
| Compose 渲染 | quickstart 默认/on 与 production fixture 仅执行 `config` 并输出非敏感摘要；未启动服务 | A8/C4 的配置形状核对；不是 live quickstart 或生产部署 |
| 性能样本 | 复用并独立复算 T8 本地 test-double JSON | 仅验证 05 §4 采样/计算方法；真实外部模型、工具和生产等价环境未提供 |
| CI/生产/人工 | 未运行 CI，无 run URL；无生产 canary、部署 traces/metrics、人工 UAT 或签字 | `pending_env` / `pending`，见 L-01～L-04、L-08 |

## 3. 功能验收记录（A1～A9）

执行人：独立子代理自动化辅助验收（非人工签字）；日期：2026-11-11。T9 新证据编号见附录 A；T8 证据编号沿用 `06-test-report.md` §2 与附录 A。

| # | 溯源、前置与实际操作 | 观察结果与独立判定 | 证据 |
|---|---|---|---|
| A1 | AC-1；FR-1/2；R2/R7/R8/R16。前置为无快照 legacy base_runtime、真实已发布快照、同串行无工具脚本及身份对抗 fixtures。本轮重跑 UT01 的 15 函数/33 参数例、no-snapshot/published-snapshot off/on 和真实 asyncpg claimed row→Context→Request→RuntimeFactory 链；规格复审后新增 `test_p2_t9_a1_published_snapshot_serial_no_tool_off_on_parity`，复用真实 `run_real_worker_pair`/`RuntimeFactory`，显式覆盖 published snapshot + serial + `tool_names=[]` 的同一输入 off/on | **PASS(local controlled)**。新增真实链逐项比较 output、成功 history/dropped、稳定事件语义、model.completed/聚合 usage、completed 终态，以及 capture 中 durable seq 连续和内容稳定；本节点不验证路由 replay 游标。严格 after/Last-Event-ID/replay 由 A4 的 T9-E02 `test_p2_it05_internal_sse_replay_delta_cursor_and_hidden_replay_parity`、`test_p2_it05_internal_sse_last_event_id_drain_and_invalid_cursor`、`test_p2_it06_open_sse_redaction_hidden_replay_and_cursor`、`test_p2_it06_open_sse_typed_invalid_cursor_and_last_event_id` 及 T9-E03 真实 PG 对应节点承担。仅按既有 canonicalizer 排除允许的实例/timing 字段，raw latency 不作对等替代。原有无快照与身份链结论保持：精确 stdlib UUID 保持原对象，UUID 子类受控转换；Request.execution_id 为精确 stdlib UUID且与 row.id 值相等；`context.row is claimed_row`、Factory 收同一原 row，原 row.id 对象/类型/值未改写；伪造/畸形/nil/恶意普通异常安全为 `INVALID_REQUEST`，控制流重抛。未借 Run/conversation UUID，nil 未进入查询或公共面 | T9-E01、T9-E02、T9-E03、T9-E17、T9-E22；T8 E02/E05/E06 与 06 附录 B、D.2 |
| A2 | AC-2；FR-1/3；R4/R7/R11。使用同模型轮、串行/并行工具、history 截断、summary/customer_memory、reasoning 与预算 fixtures；按 call_id/模型轮复核 off/on，并在真实 PG 重跑 summary/history/dropped、extract/reinforce/injection、失败/取消不写回。规格复审后新增 3 个真实 RuntimeEngine 预算 off/on 参数例：`max_model_rounds=1` 后请求第二轮触发 `model_round_limit`，`max_tool_calls=1` 时单轮请求两个工具在 HTTP 前触发 `tool_call_limit`，真实 64001 字符输出触发实现中独立存在的 `model_output_too_large` | **PASS(local controlled)**。三个预算错误均由真实 runtime/engine 执行触发而非 mapper 输入；逐项验证公共安全 `resource_exhausted`/静态 message、私有 Outcome/Repository/RunView/run.failed 保留各原 legacy code、failed 终态及失败时无 Memory completion/writeback，并保留 off/on 历史失败原因与控制流语义。原有工具参数/结果、call_id 局部偏序、模型轮边界、按轮 multiset、真实 PG Memory 事务结论保持；成功 Memory 仅经私有 Outcome 获得 history/dropped。T8 六 Memory 套件另有 156 passed、2 个替代环境 skip，skip 未计通过 | T9-E01、T9-E03、T9-E17、T9-E18；T8 E05/E08，06 P2-IT-17 |
| A3 | AC-3；FR-2/3；R3/R5/R8/R14。核对同步无 await 的 ContextVar set→registry.resolve→finally reset、零参 fresh factory、Worker/Orchestrator 独立 worker_emit、Adapter 私有 runtime_emit；重跑并发/嵌套/异常、多 Run、单次私有 Outcome 收集和 LocalTest 独立 Registry/selector | **PASS(local controlled)**。for_run/run 收同一 row 与同一 runtime_emit，Context 无 emit，worker_emit 仅由 Orchestrator 在公共取流后调用；React 在 worker_emit 成功后 ack，drain 后仅一次 `collect_outcome`，不重复公共收集或访问 `_execution`。LocalTest 无私有协议，保持 yield=delivery 及确定性 completed/failed/cancelled 回退。Worker 无 Engine 分支，Core 无反向依赖。T8 已逐项核对公共 suite 25 函数：19 复用、6 私有替代；本轮另复核精确守卫 | T9-E01、T9-E04；T8 E01～E03 与 06 附录 C |
| A4 | AC-4；FR-4；R5/R6/R7/R15。发送普通/扩展事件与伪造 run.*/tool.replay/畸形事件；重跑容量 1、慢 worker_emit、ack identity、no-stream/closed/terminal、append/emit 失败。经真实内部/Open ASGI 路由验证非法游标与合法重放 | **PASS(local controlled)**。合法事件原名同 payload 且只经公共流后到 worker_emit 一次；伪造保留事件不到 worker_emit。yield 不等于 delivery，ack exactly-once，重复 settled 幂等，错误身份/乱序/跨 Run abort；终帧最后且无第二终态。内部手工 header `bad/-1/2147483648/1.5` 均为 400/`invalid_last_event_id`；内部 typed after 四形态及 Open typed after/header 均为 422。双 API 合法游标按 max 合并且严格 `seq>after`；200+ drain、无 ID delta 不重放、tool.replay 隐藏但推进 cursor、字段过滤均通过，无悬挂任务 | T9-E02、T9-E03；T8 E05～E07 与 06 附录 D.1 |
| A5 | AC-5；FR-5；R4/R6。规格复审后逐项补齐 03 §6.1 的 26 个已知 RuntimeFault code + 1 个未来未知 code（共 27 参数例），每个均经真实 ReactAdapter/RuntimeWorker/ParityRepository 链；另跑 outer run timeout 与未知普通异常 2 例。最终边界复审新增同一组实际 **8** 个保留/畸形事件参数的真实 ReactAdapter→Orchestrator→RuntimeWorker→ParityRepository 完整终态链，以及 1 个真实 GatewayChatModel 流式拒绝→非流式 `ainvoke` fallback 反例；原有 8 个事件边界和 2 个 Gateway 聚焦回归同时重跑。普通 stream/worker_emit/Notifier、stale append 等已有节点的精确展开在 T9-E16 逐项列明，并结合真实 PG append 控制流复核 | **PASS(local controlled)**。27+2 个错误真实链参数例逐项验证公共 ExecutionResult 仅安全 ExecutionErrorCode/静态 message、私有 Outcome 与 Repository 持久化原 legacy code、RunView/run.failed 最终视图、off/on parity 和脱敏。新增 8 个事件完整链均为公共安全 protocol_error/静态 message、私有 execution_error、Repository failed 和 RunView/run.failed；伪造事件零 ack、零业务事件持久化且仅落终帧，原始 marker/kind 未泄露。真实 Gateway 反例观测流式 DomainError 后恰调用一次非流式 `ainvoke` 并返回实际成功结果，调用方未收到该错误。未来 code 公共 internal_error fallback，未知普通异常 internal_error/execution_error，agent_model_required 不变成 adapter_factory_failed。普通 emit 失败为 failed 非 cancelled；PG `[expired]/[reaped]/[cancelled]` stale append 均不 ack、不持久化、abort/aclose 后重抛 CancelledError，不改原终态且不归 execution_error。公开 Result/RunView 限定字段与日志未见秘密、input/config/history、原始异常或 stack | T9-E02、T9-E03、T9-E16、T9-E17、T9-E18、T9-E20；T8 E01～E03、06 附录 F |
| A6 | AC-6；FR-1/4/5；R5/R6/R10。以 Event/gate 覆盖首发 gate、模型等待、满队生产、阻塞消费、完成竞争、重复 cancel/aclose、单独与共享 collector；真实 PG 重跑 finish/reaper 先提交与 cancel 先提交两种顺序 | **PASS(local controlled)**。Adapter 显式取消 first-terminal-wins，cancelled 无 output/error，已完成 Result 不追溯取消；共享 collectors shield，单独 no-stream 取消清理后重抛。迟到事件/成功被抑制，无第二终态；Run 持久层 first-commit-wins，finish/reaper 先提交则 cancel no-op，cancel 先提交则 late finish 不改写；owned tasks done。外层 timeout 仅防悬挂，未用 sleep 巧合判定 | T9-E02、T9-E03；T8 E02/E05/E06 |
| A7 | AC-7；FR-5；R4/R10。分别注入 model/run timeout，构造 heartbeat lost、Lease 过期、reaper、旧 Worker 迟到 append/finish 与取消/完成竞争 | **PASS(local controlled)**。分别得到 failed/model_timeout、failed/run_timeout、failed/worker_lost，失租未伪装用户取消。stale/terminal/wrong-owner/expired finish 静默 no-op；对应 append 不持久化并重抛 CancelledError。cancelled-with-worker_lost/queue_timeout 变体保留，无自动重试或第二终态；仅承诺协作式协程有界清理 | T9-E02、T9-E03；T8 E05/E06 |
| A8 | AC-8；FR-6；R9/R12。前置为默认 off、显式 on、off API/on Worker、混合 legacy/orchestrator owners 及存量 queued/running/terminal fixtures。本轮重跑 Settings/fingerprint/fail-fast、混合独占 claim 与全 off 回滚；另渲染 quickstart off/on 和 production compose | **CONDITIONAL — PASS(local controlled rollout)，生产滚动重启/canary 与 live quickstart 为 `pending_env`**。受控 PG 中 off 仅 legacy、on 仅 Orchestrator，flag 不进 fingerprint；off API/on Worker 不冲突，混合执行不共享/重领 row，terminal 不改写，全 off 后新 Run 仅 legacy，on 失败不 fallback。compose 渲染默认 false、显式 true、内嵌 Worker 与服务集合正确。未执行真实进程滚动重启、生产 canary 或 quickstart 栈，不预写 T10/T11 结果 | T9-E03、T9-E04、T9-E06～T9-E09；T8 E05/E09 |
| A9 | AC-9；FR-4/6；R1/R4/R11/R15。复核保护面 diff、Phase 1 DTO/Registry/LocalTest、Repository/hooks、跨租户与低基数日志；动态执行 heads/current、重跑 IT19 和当前迁移源哈希对比，并复核 A4 实际路由 | **CONDITIONAL — PASS(local functional/static)，CI 与真实部署观测为 `pending_env`**。57/57 Python 迁移源文件零新增/删除/哈希变化，heads/current 均为当次 `0057_industry_pack_runtime (head)`；T8 临时空库 upgrade/current 已通过且临时库已删除。migration/ORM/public route/schema/frontend/Phase 1 保护路径零变更；公共状态码与错误体由实际路由复核。测试日志仅低基数 path/tuple/status/error/duration，run_id 不进 metrics，无私密/nil/history。未声称全量 pytest、CI 或生产 traces/metrics 通过 | T9-E02～T9-E04、T9-E11～T9-E13；T8 E10/E11/E13～E16 |

## 4. 业务与性能指标逐项判定

| 指标 | 目标与本轮数据 | 判定 |
|---|---|---|
| 回复/工具/Memory 对等 | A1/A2 串行稳定字段零非预期差异；并行按 call_id、局部偏序、模型轮及 multiset 对齐。canonicalize 仅 03 §7.3 的 event/timestamp/实例计时与指定 gateway/duration 字段，call_id、业务 ID、参数/结果、output/error/usage 未规范化 | **PASS(local controlled)** |
| 事件/SSE/终态兼容 | A4 双 API 实际路由的每游标 replay、每 Run 连续 seq、瞬态 delta、隐藏 tool.replay cursor、终帧最后与唯一终态均符合 | **PASS(local controlled)** |
| 取消/超时/Lease 收敛 | A6/A7 的受控竞态、两种提交顺序、错误分类、迟到保护与任务清理均符合；未把 watchdog 当功能耗时 | **PASS(local controlled)** |
| 回滚可恢复性 | 受控 PG 全 off 后新 Run 仅 legacy，既有 terminal 不变，无迁移/修数/客户端变化；真实生产滚动重启未执行 | **PASS(local controlled)；生产验证 `pending_env`** |
| 端到端性能 | T8 原始 JSON 本轮独立复算：5 warm-up pairs 不计样本，30 有效 matched pairs，0 errors，old-first/new-first=15/15，nearest-rank 取 N=30 第 29 项。old/new p95=0.007500/0.095542 ms，ratio=12.738933333333；首 token p95=0.000292/0.093625 ms，paired-delta p95=0.089209 ms，adapter-overhead p95=0.095542 ms，外部时延未扣除 | **方法复核通过；≤5% 子指标 `pending_env`**。这些是 test-double 微小延迟，既不证明生产达标，也不构成生产退化结论；须以真实模型/工具和等价环境重测 |
| 验收后示例 | T10 专属幂等 seed、T11 live quickstart off/on/内嵌 Worker/双 SSE/回滚均未执行 | **pending_env / 未执行**；后续只追加附录，失败须重开 A8/C5 |

canonical diff 只用于功能对等，原始延迟独立保存，未由 diff 隐藏或替代性能。本轮没有将 259 个补跑用例数解释为唯一覆盖率，也没有将其与 T8 的重叠计数相加。

## 5. 合规核对（C1～C5）

| # | 核对项与本轮操作 | 判定与证据 |
|---|---|---|
| C1 | 数据库与公开兼容性。检查 migration/ORM/public HTTP/SSE schema/frontend/Phase 1 DTO 路径，动态 heads/current、IT19、57 文件 SHA256、存量行；经真实 ASGI 复核 R15 400/422 与合法 max/strict replay | **PASS(local controlled)**。零保护面变化、零迁移源漂移，空库 upgrade 由 T8 E10 证明；实际路由、状态码、错误体和重放保持。证据 T9-E02/E03/E11～E13，T8 E05～E07/E10/E11 |
| C2 | 身份、多租户与敏感信息。重跑完整 R16 对抗与真实 asyncpg 链、伪造/nil 查询前拒绝、跨租户 Run/SSE、公共字段与安全错误；复核日志/metrics | **PASS(local controlled)**。精确 stdlib UUID/子类转换/两侧值相等/原 row 保留均符合；跨租户不可达，nil 不进入授权/查询/公共面，秘密、原始异常、history/Outcome/Context 不泄漏。证据 T9-E01～E04 |
| C3 | 双 emit、事件所有权与结构化交付。核对 Context 无 emit、worker/runtime emit 方向、run.*/tool.replay/delta 唯一来源、伪造隔离、ack identity/exactly-once/abort、React no-stream 与 LocalTest 差异；复核 25 函数裁定 | **PASS(local controlled)**。普通业务事件只经公共流投递，Repository 仍是唯一终态写者；React 私有 ack 与 LocalTest yield=delivery 未混用，19 复用/6 私有替代有逐项清单。证据 T9-E01～E04，06 附录 C |
| C4 | 配置、发布与依赖治理。重跑默认 off/on、fingerprint、fail-fast、Worker off/on 与混合回滚；渲染 compose、核对 rollout/quickstart 双语文档及 Core/Worker 依赖边界 | **CONDITIONAL — PASS(local controlled)，生产发布验证 `pending_env`**。默认 off、启动生效、on 不兜底、无第二套 ReAct/新服务；文档命令与双语 bash blocks 一致、相对链接有效。生产 canary/live quickstart 未执行。证据 T9-E03/E04/E06～E09 |
| C5 | 生命周期、功能/性能出口与证据诚信。逐项检查 05 A/C 是否有独立结果，复核 T8 功能出口、CM08、性能原始样本、本地/CI/人工边界及 T10/T11 顺序。规格复审指出 A1/A2/A5 证据缺口后，本轮新增真实测试补证并保留旧日志，未篡改已批准 06；原四组命令、exit、精确参数展开与零交集另经 collect-only 复核。最终 A5 仅补 8 个畸形事件完整链与 1 个真实 Gateway fallback，未重跑其他套件 | **CONDITIONAL**。本地功能与 CM08 证据诚信通过；新增 42 个 A1/A2/A5 补证参数例及 20 个聚焦回归均通过，未改生产实现。性能/CI/真实部署/人工签字如实 pending；T10/T11 未执行且未预写通过。临时证据索引包含原四组 259 次与新增执行的精确命令/节点，无 CI URL 或持久 artifacts。证据 T9-E05、T9-E16～E22、L-01～L-04/L-08 |

## 6. 遗留问题清单

以下为环境、发布或证据遗留，不是本轮发现的本地功能失败；owner 均为角色建议，期限均为建议而非承诺。

| # | 级别 | 问题与影响 | owner 角色建议 | 期限建议 | 补证方法 |
|---|---|---|---|---|---|
| L-01 | P1 发布门禁 / `pending_env` | 真实外部模型/工具与生产等价环境性能未测，≤5% 目标未判定 | Runtime 维护者、QA、真实性能验收人 | 生产发布前；建议 2026-11-18 前完成首轮 | 按 05 §4 同环境同脚本执行 5 warm-up+至少 30 matched pairs，保存原始 e2e/首 token/overhead/errors，以 nearest-rank 独立复算 |
| L-02 | P1 发布门禁 / `pending_env` | CI 未执行、无 run URL；真实部署 traces/metrics 与全量回归缺失，本地选择不能替代 | QA、发布负责人、CI 维护者 | 正式人工签字与生产发布前 | 在合法提交/PR 的干净检出运行完整 CI，保存 run URL、全量结果及部署低基数 traces/metrics；同时核对旧目录环境问题是否消失 |
| L-03 | P1 验收入口 / `pending_env` | 生产 canary、真实滚动重启/回滚、人工 UAT 与业务/QA/发布/安全签字未完成 | 发布负责人、Runtime 维护者、QA、产品/业务负责人、安全评审人 | 生产发布前 | 按 rollout runbook 执行默认 off→小组 on→混合 Worker→全 off，记录存量行、路径、终态与观测；人工体验后由各角色真实签字 |
| L-04 | P2 后续验证 / `pending_env` | T10/T11 未执行，live quickstart 的 seed、off/on、内嵌 Worker、双 SSE 与回滚无证据 | Runtime 维护者、QA | T10 完成后、Phase 2 关闭前；建议 2026-11-20 前 | T10 新建专属幂等低敏 seed 后，由 T11 实际启动 quickstart 验证并仅向 06/07 追加附录；失败重开 A8/C5 |
| L-05 | P3 替代环境 | Memory 六套件 2 个无 embedding 列降级节点 skip，未计通过；必需 PG17 主路径已通过 | Memory 维护者、QA | 下一次 Memory 回归或正式发布证据归档前 | 在独立无 embedding 列数据库执行两个精确节点，保留 skip 原因与新结果，不删除原记录 |
| L-06 | P3 既存基线 | 全 `src` 有 32 个与本阶段零交集的既存格式偏差；本阶段 12 个源文件通过，不能写成全树格式通过 | 后端维护者 | 独立基线清理时；建议 2026-11-18 前评估 | 另开格式化变更并跑对应检查，保留本阶段文件集合与基线归属，不在 T9 越权修改 |
| L-07 | P3 本地环境 | raw 架构门禁受四个既存 ignored legacy 根影响；原 `.git` 有 macOS macl 限制，本轮使用仓库外临时 metadata | 平台维护者、QA | CI/正式签字前复核 | 在干净 checkout/CI 运行 raw 架构与 Git 检查；不得删除用户旧目录，保留 clean-export 与 raw 限制的区别 |
| L-08 | P2 证据持久性 | T8/T9 原始证据仅在 job tmp，清理后不可复核；本轮无 CI artifacts 或批准的持久归档 | QA、发布负责人 | 人工签字与生产发布前 | 将授权的非敏感日志、样本和 CI 链接存入批准的持久证据区，记录保留期；不得把本报告摘要冒称原始归档 |

## 7. 结论与签字

**结论：有条件通过。**

- A1～A7 的本地受控功能验收通过；A8/A9 的本地功能与静态范围通过，但真实滚动部署、生产观测和 CI 未完成；C1～C3 本地合规通过，C4/C5 因发布与证据边界为有条件通过。
- 本地功能出口、off/on canonical diff、错误/终态/事件对等、真实 PG 关键链与配置/迁移核对均满足 05；本轮没有发现产品功能失败，没有新增开放实现 P0/P1。
- 对规格复审的 A1/A2/A5 缺口已新增 42 个真实链/真实 fallback 补证参数例并全部通过，另跑 20 个聚焦回归通过；最终仅补 8 个畸形事件完整链和 1 个 Gateway fallback。只修改验收测试与 T9 报告/临时证据，未改生产实现，旧日志和 fixture 校正记录均保留。
- 真实等价环境 ≤5% 性能子指标、CI/真实部署 traces/metrics、生产 canary/人工 UAT 与签字、live quickstart T11 尚未完成，因此**不能写完全通过**。
- T10/T11 尚未执行。T11 只能在后续实际完成后追加验收后附录；任何失败必须重开受影响项，不得追溯粉饰本报告。

| 角色 | 签字/状态 | 结论 | 日期 | 备注 |
|---|---|---|---|---|
| 本地自动化执行者 | **独立子代理自动化辅助验收（非人工签字）** | 本地功能通过；总体有条件通过 | 2026-11-11 | 本报告及 T9 临时证据；不代表任何人类批准 |
| 后端负责人 | **pending / 未签字** | 待人工验收 | 待填写 | 不得以 agent 输出代签 |
| QA 负责人 | **pending / 未签字** | 待人工验收 | 待填写 | CI、替代环境及证据归档待复核 |
| SRE/发布负责人 | **pending / 未签字** | 待真实部署验收 | 待填写 | 生产 canary、滚动回滚与 quickstart 未执行 |
| 安全/平台评审人 | **pending / 未签字** | 待人工复核 | 待填写 | 本地安全测试不等于生产安全签字 |
| 产品/业务负责人 | **pending / 未签字** | 待人工 UAT | 待填写 | 回复、工具、Memory、事件、错误与取消体验待确认 |
| 真实性能验收人 | **pending / 未签字** | `pending_env` | 待填写 | 真实等价环境 ≤5% 指标未测 |

## 8. 附录 A：T9 输出与证据快照

> 本附录仅为关键结果摘要；临时原始链接受 §1 生命周期限制。T8 证据同样受 `06-test-report.md` §1 的临时性约束。

| 证据 | 实际输出摘要 | 原始链接 |
|---|---|---|
| T9-E01 | A1/A2/A3 身份、串并行对等、Context/LocalTest：**89 passed in 1.37s** | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-01-a1-a2-a3-identity-parity-orchestration.log) |
| T9-E02 | A4/A5/A6 全错误矩阵、事件/ack、实际路由、取消与公开面：**106 passed in 3.47s** | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-02-a4-a5-a6-events-errors-routes-cancellation.log) |
| T9-E03 | 真实 PG 的 R16、Memory、R15、竞态、Lease、混合回滚与迁移：**35 passed in 15.69s** | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-03-a1-a2-a4-a6-a7-a8-a9-real-pg.log) |
| T9-E04 | Settings、fingerprint、Worker、fail-fast、19/6 守卫与受控日志：**29 passed in 0.81s** | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-04b-a3-a8-c3-c4-config-worker-observability.log) |
| T9-E05 | 独立复算 5 warm-up、30 pairs、0 errors、15/15、item 29；生产性能 pending_env | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-05-performance-independent-recompute.log)、[T8 JSON](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-performance.json) |
| T9-E06 | quickstart 默认渲染：app embedded=true、orchestrator=false；三服务，无启动 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-06-compose-quickstart-default.log) |
| T9-E07 | quickstart 显式 on 渲染：orchestrator=true；服务集合不变，无启动 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-07-compose-quickstart-on.log) |
| T9-E08 | production 当前 compose 与 T7 fixture 一致；API/runtime-worker 默认 false，无新增服务 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-08b-compose-production-shape.log) |
| T9-E09 | rollout/quickstart 双语文档必需项、bash blocks、相对链接通过；live/canary=false | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-09b-rollout-quickstart-docs-check.log) |
| T9-E10 | 报告前工作树状态快照；使用临时 Git metadata，未修改原 `.git` | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-10-worktree-status-before-reports.log) |
| T9-E11 | 当前 57 个 Python 迁移源与 T8 对比：added/removed/sha256_changed 均为空 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-11b-migration-drift.log) |
| T9-E12 | 动态 heads/current 均为 `0057_industry_pack_runtime (head)` | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-12-alembic-heads-current.log) |
| T9-E13 | migration/ORM/public route/schema/frontend/Phase 1 保护路径均为空 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-13-protected-surface-check.log) |
| T9-E16 | T9 证据索引含原四组精确命令、exit、A/C 映射与全部参数展开；collect-only 验证四组无交集、259 次 | [证据索引](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-evidence.md)、[collect log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-16b-original-four-collect-only.log) |
| T9-E17 | 规格复审 A1/A2/A5 真实链补证：**33 passed in 1.45s**（A1 1、A2 3、A5 29），含 33 个精确参数 ID | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-17b-a1-a2-a5-acceptance-gap-real-chains.log)、[nodes](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-17b-a1-a2-a5-acceptance-gap-real-chains.nodes) |
| T9-E18 | 受影响的 parity/Memory/public-view 聚焦回归：**10 passed in 1.00s** | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-18-focused-parity-memory-public-regression.log) |
| T9-E19 | 两个修改测试模块 ruff check 与 format --check 通过 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-19-test-lint-format.log) |
| T9-E20 | 最终 A5 边界：8 个新畸形事件完整链、8 个受影响原事件及 2 个 Gateway 回归通过；新 Gateway 节点首次因 mock 协议格式错误失败，修正 fixture 后单独 **1 passed**。失败与成功日志均保留 | [首次 log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-21-a5-malformed-terminal-and-gateway-fallback.log)、[修正后 log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-21b-a5-gateway-fallback-corrected-fixture.log) |
| T9-E21 | 最终修改测试 ruff check、runtime_baseline format 与新 Gateway 测试范围 format 通过；全文件既有格式差异未扩展修改 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-22b-a5-focused-test-lint-format.log) |
| T9-E22 | 质量评审移除 A1 同列表过滤的 replay 自证循环，仅保留 capture durable seq/稳定内容断言；路由游标明确归 A4 T9-E02/E03。A1 单节点重跑 **1 passed in 1.26s** | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t9-logs/t9-24-a1-capture-seq-scope-correction.log) |

**有效执行计数（总评审更正）**：原四组 4 个 pytest 命令保持 **259 passed**（89+106+35+29，精确展开无交集，仅为本轮验收节点计数，不与 T8 累计）；首轮 A1/A2/A5 补证首次执行 **33 例次、32 passed、1 failed**，修正 Memory fixture 后重跑 **33 passed**；必要聚焦回归 **10 passed**。最终 A5 两次调用执行 20 例次：首轮 18 passed + 1 个 Gateway mock fixture 失败，修正后该节点 1 passed；A1 证据范围校正后单节点重跑 1 passed。本轮完整口径为 **10 个 case-executing pytest 命令、356 例次、354 例次通过、2 例次失败**；两次 fixture 失败均已修正，原始失败与修正日志均保留。其中 18 个回归节点与原四组重复，修正重跑不增加唯一覆盖数；另有性能复算、原 8 项静态/配置/文档检查及补证 lint/format。未重跑 T8 全套，未运行全量 pytest。

**调用校正留痕**：首次 T9-E04 将一个日志节点误写到 `test_execution_orchestrator.py`，pytest 在收集阶段报 not found、0 测试；随后用 06 记载的正确 `test_runtime_baseline.py` 节点重跑通过。首次 production 渲染缺少服务相对 env fixture、首次文档检查把 rollout 专属词错误要求到 quickstart、首次迁移清单误纳入 `__pycache__`，分别保留原始失败日志并以限定 fixture、按文档范围及仅 `*.py` 源文件的校正检查重跑。新增补证首次运行中 A1 因未提供 Memory completion fixture 而令 dropped 观测为 `None`、断言失败（其余 32 通过）；提供 `ParityMemory` 后 33 全过，原始 `t9-17` 与校正后 `t9-17b` 均保留。最终 Gateway 反例首次 mock 错用 OpenAI 响应结构，真实 fallback 已命中但非流式结果被拒绝；改为 `gateway_http` 规定结构后单节点通过，`t9-21`/`t9-21b` 均保留。上述均为验收命令/checker/fixture 问题，不是产品功能失败，未用于通过判定。

## 附录 B：T8 复核锚点

- 功能出口与逐条用例：`06-test-report.md` §2～§5、§10。
- R15 真实路由矩阵：`06-test-report.md` 附录 D.1；本轮由 T9-E02/E03 重新执行关键节点。
- R16 原 asyncpg row、精确 stdlib UUID、Factory 原 row：`06-test-report.md` 附录 D.2；本轮由 T9-E01/E03 重新执行对抗与真实链。
- 25 个公共 Adapter 函数裁定：`06-test-report.md` 附录 C。
- 27 项错误矩阵与对抗：`06-test-report.md` 附录 F；原 T9-E02 重跑 21 函数/58 参数例，规格复审后 T9-E17 另以 26 个已知 RuntimeFault + 1 个未来 code 及 timeout/普通异常 2 例逐项通过真实 Adapter/Worker/Repository 公共与私有链；T9-E20 最终补齐实际 8 个畸形事件完整终态链与真实 Gateway 非流式 fallback。
- 动态空库 upgrade/current、临时库清理：T8 E10；本轮 T9-E03/E11/E12 复核当前迁移态，不伪称重新创建空库。
- 性能原始口径：`06-test-report.md` 附录 E；本轮 T9-E05 独立复算，不沿用文字结论代替计算。

## 验收后验证附录（T11）

> 本附录仅追加 T10 seed 后的真实 quickstart 验证，不改变上述 T9 签字、历史证据或生产性能 `pending_env` 限制。逐项命令、Run ID、日志和测试输出见 `06-test-report.md` 的 T11 附录及 [非敏感证据索引](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-evidence.md)。

### A8 验收后场景判定：通过（R17 修复后）

- **默认 off / 内嵌 Worker**：真实 `sh nexusdesk quickstart` 路径起栈，三个既有服务 healthy，无 runtime-worker；Settings 为 `orchestrator=False embedded_worker=True`。两类新 Run 均 completed、output 非空、`error_code=null`，无 `configuration_changed` 或对应 orchestrator 路径行。
- **T10 幂等 seed**：真实模块两次执行，首次 created=`1/1/1/1/2/1`，二次全 preserved 且 ID/version 不变；真实 Agent/Profile 各一个发布版本，published/no-snapshot 会话身份符合设计。
- **显式 on**：初次实测发现 quickstart WARNING 配置吞掉 Worker INFO 受控日志，已暂停并重开 R17，未伪造通过。独立修复评审后重建 app，复用同一 seed；on 容器全部 8 个 Run 各有且只有一条合法 `path=orchestrator tuple=react/native/v1` 终态行，均 completed、duration 有限非负，无安全字段越界或静默 fallback。
- **内部/Open SSE**：真实 stream 均到 completed，after=0 replay 的持久 seq 均为 1–5、终帧最后；终态 `after`/`Last-Event-ID` 均严格无重复。Open 仅保留允许的 `accepted` 差异，无工具、retrieval、gateway、history/config 等私有字段；no-snapshot 未伪称 Open 支持。4 个临时 Key 全部撤销且 inactive。
- **全 off 回滚**：显式 false force-recreate 后新进程为 false，两类新 Run 成功且无 orchestrator 行。回滚前 95 个 off/on/Open/示例 Run 的 status/output/error/timestamps 与事件哈希全部不变；无 downgrade、修数、客户端变化、新服务或卷删除。

### C5 与出口复核

- 新增 live pytest 节点为显式 opt-in，默认 CI 不控制 Docker、不需要秘密；本轮实际执行两次均 **1 passed**，不是 skip。目标文件既有 PG 聚焦回归 **3 passed, 1 deselected**，Ruff check/format 最终均 exit 0；未重跑 T8/T9 全套。
- 两次临时 SSE checker 断言错误（内部 terminal 结构、Open accepted 差异）均保留失败记录并修正验证器，不作为产品失败或通过证据；首次 format check 失败也已记录并仅格式化目标文件。
- 本轮仅为本地 demo backend 功能验收，不宣称生产性能达标，也不改变 T9 的有条件通过性质。最终 quickstart 保持显式 off、healthy；quickstart 卷及独立 Phase 2 PG17 容器/卷保留供独立评审。

### 非零冲突游标补证（规格评审更正）

前述零/非零 cursor 证据不足以独立证明两个非零冲突值取 max。现保留原记录，并在 live 节点对内部/Open 各补 `(after=4,Last-Event-ID=5)` 与 `(after=5,Last-Event-ID=4)`，均无持久事件，证明较大值不受 query/header 位置影响且严格排除边界。当前 off healthy 栈实测同一 opt-in 节点 **1 passed in 4.45s**，Ruff check/format 均通过；本次 Key 已 finally 撤销，累计 5 个 Key 全部 revoked/inactive。详见 [补证日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest-nonzero-cursor.log) 与 [证据索引](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-evidence.md)。未改生产或重跑旧套件。

### Live 测试可靠性质量补证

按质量评审，仅调整 live helper：SSE 整个消费循环增加 `asyncio.timeout(60)` 并保留 stream context 关闭语义，避免持续心跳无限等待；Open Key 签发响应先保存 `key_id` 再读取 `app_key`，确保 key 字段异常时 finally 仍可吊销。全部 cursor/redaction 断言未放松。当前 off healthy 栈实测同一 opt-in 节点 **1 passed in 4.38s**，Ruff check/format 均通过；本次 Key 已撤销，累计 6 个 Key 全部 revoked/inactive。详见 [质量补证日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest-quality-reliability.log) 与 [证据索引](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-evidence.md)。未改生产、未重跑旧套件，历史计数保持不变。

## 最终跨阶段评审补证（R18，2026-11-12）

- 已修复 Worker 正常 Outcome 在 finish 前记录日志的顺序缺陷：现仅当对应 `repository.finish` 成功返回后记录受控终态 INFO；completed finish 普通失败只会进入既有异常路径，记录一次 failed 并重试 failed finish，不再形成 completed+failed 矛盾双日志。终态持久化、Memory、off legacy 及异常/取消语义未扩大修改。
- 新增 finish 故障注入与严格顺序两项回归，连同相关 Worker path-log/deployment 聚焦选择实测 **16 passed in 1.17s**；三个目标 Python 文件 Ruff check/format 均通过。精确节点和原始日志见 [最终修复证据](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-final-fix-evidence.md)。
- T9 历史执行汇总已完整更正为 **10 个 case-executing pytest 命令、356 例次、354 通过、2 失败**；两次失败均为后续已修正的 fixture 问题，原始失败与修正重跑均保留，重跑不增加唯一覆盖。
- 本轮未重建 quickstart、未执行 R18 live Run，也未重跑旧全套。T11 最小最终代码 on/off live 复测仍 pending，因此 R18 目前只完成生产修复和聚焦验证，不宣称 live 闭环。生产性能、CI、真实部署 canary、人类 UAT/签字与持久证据归档继续 pending；总体结论保持**有条件通过**。

### R18 最小 live on/off 已完成（后续补证）

保留上述历史 pending，现追加最终代码实测：mirror 构建 app 与显式 on/off force-recreate 均 exit 0。on published Run `c8e390f2-18fa-4193-9f39-62bd79030563` completed，其 `path=orchestrator` 总数 **1**、completed **1**、failed **0**，`duration_ms=123.639` 有限非负且 tuple 正确；off published Run `53b29563-5933-4f4e-9a7b-deea3a087b18` completed，其 orchestrator/failed 均 **0**。旧 on Run 回滚后仍 completed 且完整 RunView 不变，最终三服务 healthy、显式 off。

精确命令、exit、原始响应和日志计数见 [T11 证据](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-evidence.md)、[R18 证据](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-final-fix-evidence.md) 与 `06-test-report` R18 闭环附录。本补证未运行 seed、Open、双 SSE 或旧全套，未签发 Key、未改生产；生产性能、CI、真实部署 canary、人类 UAT/签字与持久归档仍 pending，总体仍为**有条件通过**。
