# Phase 2 · React Provider 与执行编排器 — 验收方案

> 状态：本地 T2～T11 与 R17 live 验证已完成，R18 生产修复及聚焦验证已完成，详见 06/07 及相应附录；R18 最小 live on/off 已完成；总体仍有条件通过
> 创建：2026-11-02
> 修订：2026-11-12（R18 与当前状态统一；设计期内容保留为历史计划）
> 依据：`01-business-goals.md`（G1～G4）、`02-requirements.md`（US-1～US-4、FR-1～FR-6、AC-1～AC-9）、`03-technical-design.md`、`04-test-plan.md`、`08-implementation-breakdown.md`（R1～R18、T8～T11）

## 1. 验收组织与证据边界

| 角色 | 责任 |
|---|---|
| 后端负责人 | 对照 R1～R18/T1～T7 解释实现边界，提供 off/on 路径、调用链、错误/取消和资源清理证据 |
| QA | 逐条执行 04 主测试并创建双语 06；准备等价受控 fixtures、串行/并行差异、真实 PG、双 SSE、Memory 与回滚证据 |
| SRE/发布负责人 | 验证默认 off、显式 on、off API/on Worker、混合 Workers、存量行、滚动重启与回滚；复核低基数观测 |
| 安全/平台评审人 | 复核 UUID/nil 身份边界、跨租户、公共错误、HTTP/SSE/日志/指标脱敏与依赖方向 |
| 产品/业务验收人 | 判断回复、工具、Memory、事件、错误与取消体验是否兼容，并签署遗留项 |
| 人工验收负责人 | 仅在 A1～A9 主场景及 C1～C5 有实际证据后创建双语 07，明确通过/有条件通过/不通过和签字 |

**证据边界**：

- 代码合入、自动化测试和人工验收是三个独立状态；Phase 1 经 merge `0a6c4b5` 合入 integration 不替代任何人工验收。
- T8 的本地/独立环境执行、CI run 和 T9 人工操作分别记录执行人、时间、环境、提交、命令/操作和原始证据链接，不能互相代签。
- 04 每条主测试在 06 独立记录，05 每个 A/C 项在 07 独立判定。skip、未运行、环境不足不写成通过；真实环境或人工签字不足标 `pending_env`。
- 当前设计冻结阶段不创建 Phase 2 06/07，不预填结果。T8/T9 实际完成后才创建；T11 只追加验收后附录，不重写先前证据。

## 2. 环境、数据与进入条件

### 2.1 主验收（T9）进入条件

1. T1～T7 按依赖完成，T8 主测试出口满足，无开放 P0/P1；off 路径与基线行为 diff 为零。
2. 使用独立新建 `pgvector/pgvector:pg17` Docker 容器、专用新 DB 和卷；连接串只在仓库外权限受限 env，经 `TEST_DATABASE_URL`/`AGENT_DATABASE_URL` 注入，全程不打印。
3. 动态记录当次 Alembic heads、空库 upgrade/current 和迁移目录前后清单/哈希；本次设计观测 0057 不是永久验收常量。
4. 新旧路径使用等价受控 fixtures：无快照 legacy base_runtime、真实已发布 Agent 快照、固定/并行工具、超时/错误、history/summary/customer_memory/reasoning 等；不得借用生产客户数据或凭据。
5. **T9 不提前创建 Phase 2 专属示例种子**；使用受控测试 fixtures，避免把示例数据准备混入正式验收。

### 2.2 验收后种子补充（T10/T11）

只有 T8 测试和 T9 正式验收完成后，T10 才新增 Phase 2 专属、幂等、低敏、可识别命名空间的示例数据；T11 才在 quickstart 验证默认 off、显式 on、内嵌 Worker、双 SSE、路径日志和 off 回滚。T11 结果作为 A8/C 项和 06/07 的“验收后验证附录”追加；失败重开缺陷及受影响验收项，不追认通过。

## 3. AC 逐条验收场景

### A1：固定 React 身份、无快照/已发布快照与串行回复对等

- **溯源**：AC-1；FR-1/2；G1/G2；R2/R7/R8/R16；P2-UT-01～04、P2-IT-01/02/18/20。
- **步骤**：分别准备无快照 legacy base_runtime 与真实已发布快照；用同一串行无工具脚本跑默认 off 和显式 on；执行 P2-UT-01 的精确 stdlib UUID 原对象、UUID 子类受控转换、字符串/整数/None/伪造非 UUID、值不匹配、恶意 `__str__`/描述符普通异常和控制流重抛用例。通过 P2-IT-18 使用真实 asyncpg 驱动取得未经 fixture 预先规范化的 claimed row，实际走 claimed row→ExecutionContext→ExecutionRequest 链并 spy RuntimeFactory 入参；检查 `config.agent.id` 真实 UUID、缺失/畸形/nil 失败和受限 UUID(int=0) 哨兵；比较 output、成功 history/dropped、稳定 payload、顺序、每 Run seq、usage、error_code、终帧与各游标 replay。
- **通过判据**：精确 stdlib UUID 规范化保持原对象，UUID 子类转换为精确 stdlib UUID；row.id 与 execution_id 分别规范化后以 `==` 值相等而非 `is`，公共 Request.execution_id 为精确 stdlib UUID 且值直接等于 claimed row.id。真实 asyncpg 链中 `context.row is claimed_row`，RuntimeFactory 收到同一原 row，原 row.id 保持同一对象，类型和值未变，未发生复制、替换或改写；字符串/整数/None/伪造非 UUID/值不匹配及恶意普通异常只产生安全静态 `INVALID_REQUEST`，控制流异常原样重抛。不得借 Run/conversation UUID 充当 Agent；nil 不进入 selector/授权/查询/DB/HTTP/SSE/日志/指标/metadata；生产只选 react/native/v1；串行差异仅限 03 §7.3 显式路径且原字段校验合法。usage 非 optional 且不得为 None；React v1 无聚合输入时公共 Result 与私有 Outcome 都为 `{}`，不是既有聚合或伪造零 token，model.completed usage 原样保留。
- **证据**：受控 fixture 说明、新旧结构化结果、事件/重放逐项 diff、身份对抗用例和实际测试节点。R16 另附真实 asyncpg 驱动返回类型、规范化前后对象身份/类型/值关系、Request 精确 stdlib UUID 与 row.id 值相等、`context.row is claimed_row`、`context.row["id"] is original_row_id`、RuntimeFactory 收到同一原 row、原 row.id 未改写的断言/原始输出，以及伪造输入和恶意普通异常的安全静态 `INVALID_REQUEST`、控制流重抛证据；helper 单测或 fixture 预转换不能替代 P2-IT-18 真实链。原始延迟另列，不由 canonical diff 代替。

### A2：工具、并行偏序、Memory 与 reasoning 对等

- **溯源**：AC-2；FR-1/3；G1/G2；R4/R7/R11；P2-UT-04/12/22、P2-IT-02/03/15/17。
- **步骤**：用同一模型轮、串行和并行工具参数/结果、预算、history 截断、summary/customer_memory 和 reasoning 脚本跑 off/on；按 call_id 对齐 started/completed，检查每模型轮边界、无 call_id 并行事件 multiset；在真实 PG 验证 summary/history/extract/reinforce/injection 事务。
- **通过判据**：工具集合、同 call_id started→completed 局部偏序、模型轮边界、参数/结果和预算错误一致；并行分支不强制跨路径全局顺序/绝对 seq；成功 history/dropped 只经私有 Outcome 给 Memory，失败/取消不写回；usage 非 optional 且不得为 None，React v1 无聚合输入时 Result/Outcome 均为 `{}`，不是既有聚合或零 token；model.completed usage 原样保留。
- **证据**：call_id/模型轮对齐表、原始 payload 与 usage、Memory 输入/提交/回滚及租户隔离记录；不得规范化 call_id、业务 ID、工具参数/结果、output/error/usage。

### A3：Orchestrator 调用链、同步/异步装配与 LocalTest 解耦

- **溯源**：AC-3；FR-2/3；G2/G3；R3/R5/R8/R14；P2-UT-02/03/08～11/14～16/21/24、P2-IT-04/14。
- **步骤**：检查并演示同步无 await 的 ContextVar set→registry.resolve→finally reset、应用零参 fresh factory 捕获不含任何 emit 的 Context；Worker 将原回调作为独立 worker_emit 传给 Orchestrator，Adapter runner 创建私有 runtime_emit 并以同一 claimed row、同一函数对象传给 for_run/run；执行并发、嵌套、异常、多 Run 和双 emit spy；验证 React drain 后私有 `collect_outcome` 仅一次及 completed/failed/cancelled 三类 Outcome，再以无协议 LocalTest 独立 Registry/selector 经同一 Orchestrator/Worker 跑公共 collect→Outcome 回退的成功/失败/取消。
- **通过判据**：Worker 无 Engine 类型分支，Core 不 import applications/business；Factory/PlatformTools/RuntimeEngine 不得触达 worker_emit，Orchestrator 独占 worker_emit 且只在公共流取事件后调用；Context 不跨 task 泄漏且每次复位，Adapter 创建后不再读 ContextVar；每实例单 active execution、状态不共享；agent_model_required 保留 legacy code，开启失败不 fallback；React 检测 Core 私有 `AcknowledgingEventStream` 并在 worker_emit 成功后 ack，LocalTest 无协议且保持 claim 前入队、terminal 丢弃、yield=delivery。`OutcomeCollectingAdapter` 真异步/描述符异常 fail closed；React 不重复公共/私有 collect、不访问 `_execution`，completed 保留真实 history/dropped，failed 保留含未知 RuntimeFault 的原 code，cancelled 无 code；LocalTest 只按公共 error code 确定性回退，公共 Result/engine_metadata 无私有字段。
- **证据**：调用链日志/trace、依赖静态检查、并发/异常测试输出、双 emit spy 的逐段顺序/次数；Outcome 协议检测、React 三类、LocalTest 三类、Handle/collector/取消一致性、单次收集与不访问 `_execution` 的实际节点/输出；按 03 §4.2 对公共 suite 25 个函数逐项列出 19 个复用（流式用例显式 worker_emit/ack 包装）、6 个排除及私有替代结果，私有协议直接使用 raw stream；不得声称公共 AsyncIterator 套件自行证明私有 ack delivery。

### A4：开放事件、ack 背压、内部/Open SSE 与重放兼容

- **溯源**：AC-4；FR-4；G1/G4；R5/R6/R7/R15；P2-UT-05/17～21、P2-IT-05/06/15/16。
- **步骤**：发送 model.delta/model/tool、knowledge.retrieved、memory_search.completed 和扩展业务事件；伪造 run.*/tool.replay 与畸形事件并记录 runtime_emit→公共 yield→worker_emit→ack spy；验证 start→立即 stream 首事件不丢、单独 no-stream collector 显式放行、closed/terminal 后 stream、cancel/aclose 唤醒首发 gate；以容量 1、多事件慢 worker_emit、阻塞 put/get、错误/重复/乱序/跨 execution ack、append/emit 失败和迟到结果控制竞态；对内部/Open 分别测 Last-Event-ID、after、200+ drain、delta、tool.replay 和字段过滤。必须通过 ASGI/FastAPI 实际路由分别举证：内部手工 Last-Event-ID 非法/越界、内部 typed after 类型/范围错误、Open typed after 与 Last-Event-ID 类型/范围错误，以及双 API 合法游标的 max/strict replay。
- **通过判据**：合法业务事件原名同 JSON payload 无 allowlist，只经公共流后到 worker_emit 一次；保留事件来源唯一且伪造事件不到 worker_emit。React 私有 never-claimed/claimed-active/closed/terminal 和先到 collect/stream 线性化正确，no-stream suppression 不再类比 LocalTest；yield 不是 delivery，ack 按 execution_id/event_id 匹配唯一 in-flight 并 exactly-once，重复已结算幂等，错误身份/乱序/无 in-flight 安全 protocol_error 并 abort。runner pending result 在 producer finished 且 queued+in-flight undelivered=0 后唯一发布，空闲未关闭 claimed stream 不阻塞 collect；drain→collect→Worker finish 使 run.* 终帧最后；delta 无 DB seq/replay，隐藏 tool.replay 仍推进 cursor。内部手工 header 边界为 `400 / invalid_last_event_id`，内部 typed after 与 Open typed after/header 边界均为 422，合法游标以 `max(after,last_id)` 合并且严格只重放 `seq>after`；不得交换 400/422 或改变路由、schema、状态码、错误体；无重复终态、私有数据泄漏或悬挂任务。
- **证据**：事件输入/输出原样对照、双 emit 与 queue/ack identity 状态轨迹、首发/no-stream/closed/terminal 状态轨迹、双 SSE 游标/重放记录、Notifier 指定 PG/OS delta 失败与其他 emit 异常的边界结果、任务清理清单。分别附内部实际路由的手工 header `400 / invalid_last_event_id` 响应、内部实际路由 typed after 422 响应、Open 实际路由 typed after/header 422 响应，以及双 API 合法 `max(after,last_id)` 与严格 `seq>after` 的请求/响应和重放序列；helper 单测不能替代这些 ASGI/FastAPI 路由证据。

### A5：完整错误矩阵与安全失败

- **溯源**：AC-5；FR-5；G1/G4；R4/R6；P2-UT-06/09/20、P2-IT-07/16。
- **步骤**：逐项注入 03 §6.1 全矩阵：agent_model_required/configuration_changed、非法/空响应、重复/重放工具 call、轮/工具/输出预算、model_resource_not_found/disabled、model_profile_version_not_found、model_input_too_large、model_tools_not_supported、model_provider_unavailable/model_rate_limited/model_provider_rejected/model_transport_error、content_blocked_input/output、gateway_concurrency_exceeded/request_quota_exceeded、model_credential_unavailable、model_response_too_large、model_stream_interrupted、model/run timeout；另注入未来未知 RuntimeFault code、保留/畸形事件、普通 stream/worker_emit、stale append 和未知普通异常，检查公共 ExecutionResult 与 RunView/run.failed。
- **通过判据**：公共仅安全 ExecutionErrorCode/静态 message，不复制 Provider/Domain 文本；所有已知及未来未知 RuntimeFault 的私有 legacy_error_code 逐字保留，未来 code 公共 internal_error 安全 fallback，未知普通异常 internal_error/execution_error，普通 emit 失败 failed 非 cancelled；agent_model_required 不变成 adapter_factory_failed，model_stream_not_supported 当前 fallback；stale/cancelled/expired append 的 CancelledError 不 ack、不持久化、abort/aclose 后重抛且不改原终态，不归普通 execution_error；无秘密、input/config/history、原始异常/stack 进入公共面。
- **证据**：03 §6.1 全矩阵逐行结果、公共与私有错误对照、安全日志/API 检查；缺失任一项不得以抽样代替完整覆盖。

### A6：取消、aclose、collector 取消与迟到结果保护

- **溯源**：AC-6；FR-1/4/5；G1/G3；R5/R6/R10；P2-UT-07/18～20、P2-IT-08/09/16。
- **步骤**：在首发 gate 未放行、模型等待、producer 满队、consumer 等待和完成竞争时显式 cancel 后释放成功；重复 cancel/aclose；分别取消单独 no-stream collector、共享 collector 和 Orchestrator 调用方；真实 PG 用 gate 分别跑 finish/reaper 先提交后 cancel、cancel 先提交后 late finish。
- **通过判据**：Adapter 显式 cancel 是内部 first-terminal-wins，得无 output/error cancelled Result，已完成 Result 不追溯取消；共享 collectors shield，单独 no-stream collector 取消唤醒 gate 并停止执行，不借用 LocalTest 语义，调用方 CancelledError 清理后重抛；队列/runner 被原子抑制、取消并 drain，迟到事件/成功不产生第二终态。Run 持久层按提交顺序 first-commit-wins：finish/reaper 先提交则 cancel no-op，cancel 先提交则 late finish 不改写；所有 owned tasks done。
- **证据**：Event/gate 控制的两种顺序时序、Adapter Result 与 Repository 条件更新/事件序列、重复操作和任务状态；外层 timeout 仅防悬挂，不以 sleep 巧合作为证据。

### A7：model/run 超时、Lease 失租与唯一终态

- **溯源**：AC-7；FR-5；G1/G3/G4；R4/R10；P2-UT-23、P2-IT-10/11。
- **步骤**：独立构造 model_timeout 与 run_timeout；让 heartbeat lost、Lease 过期并被 reaper 接管，再释放旧 Worker 成功/append/finish；同时制造取消/超时/完成竞争。
- **通过判据**：分别 failed/model_timeout、failed/run_timeout、failed/worker_lost；失租不伪装用户取消；stale/terminal/wrong-owner/expired finish 静默 no-op，stale/cancelled/expired append 不持久化并抛 CancelledError、由 Orchestrator 不 ack 且清理后重抛，不改原终态、不归普通 execution_error；reaper 保持 cancelled-with-worker_lost/queue_timeout 变体，无自动重试或第二终态；协作式协程在外层 timeout 下有界 drain，不声称强杀非协作协程。
- **证据**：真实 PG owner/lease/terminal 行、monitor_failure 结果、append/finish 不同控制流、两种提交顺序及 reaper 变体、旧 Worker 日志和唯一终态事件；资源未清理单列 P0/P1，不得忽略。

### A8：默认 off、灰度、混合 Workers、回滚及验收后种子附录

- **溯源**：AC-8；FR-6；G3/G4；R9/R12；P2-UT-10/13/24、P2-IT-12/13/18；附录 P2-CM-09/10。
- **T9 主步骤**：分别默认启动、显式 on、off API/on Worker、混合 legacy/orchestrator Workers；检查 fingerprint、存量 queued/running/terminal 行和混合 claim；禁用/删除注册项观察 fail fast；最后全部 off 滚动重启。
- **主通过判据**：off 仅 legacy、on 仅 Orchestrator，flag 不进 fingerprint；混合执行不共享/重领 row、terminal 不改写；回滚后新 Run 全 legacy，在途按取消/Lease 收敛；on 失败不静默 fallback，无迁移、数据修复或客户端改动。
- **验收后附录**：仅 T9 正式验收后执行 T10/T11；新种子必须不是“只重跑现有 seeds”，具备 Phase 2 专属命名空间、真实 Agent ID、幂等和低敏属性，只用现有 schema/API/已发布快照；quickstart 验证 published-snapshot 与 no-snapshot legacy base-runtime 的 off/on、内嵌 Worker、双 SSE、路径日志、off 回滚，无新增服务。
- **证据**：主验收存配置/进程/路径/fingerprint/存量行/回滚记录；T11 追加种子二次执行结果和 quickstart 实际日志/SSE。T9 不得预写种子结果，T11 失败重开本项。

### A9：零公共变更、动态迁移、观测与回归完整性

- **溯源**：AC-9；FR-4/6；G3/G4；R1/R4/R11/R15；P2-CM-01～08、P2-IT-05/06/19/20。
- **步骤**：动态执行 heads/空库 upgrade/current 和迁移目录前后比较；审查 ORM、公共 HTTP/SSE 路由、schema、状态码、错误体及前端 diff；检查 Phase 1 保护面、跨租户、公共错误/字段、日志/trace/metrics；逐项核对受影响测试、CI 与人工证据，并复核 A4 的 R15 实际路由响应。
- **通过判据**：无新增/修改迁移、ORM、公共 schema 或前端；公共 API 路由、schema、状态码和错误体零变化，R15 既有的内部手工 header 400、内部 typed after 422、Open typed after/header 422 不得互换或改写；当次 heads 与基线动态一致、目录零漂移、存量行兼容；run_id 仅日志/trace，metrics 标签低基数，无 nil/秘密/input/config/history/raw stack；Phase 1 DTO/Registry/LocalTest、Repository/hooks 和 API 行为不变；每条测试/A/C 证据可定位。P2 功能 UT/IT/CM 必须全过，CM08 证据诚信/测量边界可独立通过；真实性能子指标不足为 pending_env，不否定功能出口但 T9 最多有条件通过。
- **证据**：只读命令输出、版本目录清单/哈希、公开路由/schema/状态码/错误体及前端 diff、A4 三类非法游标边界与合法 max/strict replay 的实际 ASGI/FastAPI 路由记录、跨租户与观测样本、实际测试和 CI 链接；本地未跑全量不得写成全量通过。

## 4. 业务与性能指标测量

| 指标 | 方法与通过判据 | 证据边界 |
|---|---|---|
| 回复/工具/Memory 对等 | 按 A1/A2 的串行严格规则、并行偏序/multiset 和真实 PG 事务比较；稳定字段零非预期差异 | 保存原值和精确 canonical 路径；不得全局删 ID 或隐藏差异 |
| 事件/SSE/终态兼容 | 按 A4 逐游标重放，检查每 Run seq 连续、delta 瞬态、tool.replay cursor、终帧最后与唯一终态 | 内部/Open 分开举证；AgentEvent seq 不替代 DB/SSE ID |
| 取消/超时/Lease 收敛 | 按 A6/A7 在受控竞态和真实 PG 检查分类、清理与迟到保护 | 外层 timeout 不是功能耗时；非协作协程不承诺强杀 |
| 回滚可恢复性 | 全部 off 滚动重启后新 Run 仅 legacy，无迁移/数据修复/客户端变更 | 保存发布前后配置、进程和路径证据 |
| 性能 | 严格按下述可复现方法在真实等价外部环境成对采样，新路径 nearest-rank p95 端到端延迟增幅 ≤5%；首 token、原始 paired overhead、错误率独立报告 | canonical diff 不能替代性能；test double 仅功能证据，真实外部环境不足为 `pending_env`，不得宣称达标 |
| 验收后示例 | T10/T11 幂等种子及 quickstart off/on/回滚附录实际完成 | 只追加新证据，失败重开 A8/C 项 |

### 4.1 可复现性能采样与计算口径

1. **固定 matched pairs**：每个固定场景至少采集 **30 个有效 matched pairs**，每对包含同一输入的 legacy-off 与 orchestrator-on 各一次。先执行 **5 组 matched warm-up pairs** 预热进程、连接与缓存，warm-up 明确标记且不计入 30 对样本；失败/异常样本不得静默剔除，错误率单独记录。
2. **等价环境与顺序**：同一主机/容器资源、同一脚本、同一真实模型与 Profile、工具配置、数据和依赖版本；off/on 交替执行或使用平衡顺序，保存顺序、环境非敏感标识和原始样本，避免路径与时间/缓存趋势混淆。
3. **p95 算法**：分别对 old/new 的 N 个端到端样本升序排序，采用 **nearest-rank**，取 1-based 第 `ceil(0.95 × N)` 个值；N=30 时取第 **29** 个。目标为 `p95(new) <= p95(old) * 1.05`，不得换用插值算法或只报告均值。
4. **独立保存指标**：保存每对原始 old/new end-to-end、paired delta/ratio、Adapter 原始开销、首 token 与错误率；paired overhead 与 p95 分开展示，canonical diff 不得替代或隐藏原始时延。
5. **外部时延边界**：真实外部模型/工具时延包含在 end-to-end 口径中，不得扣除以掩盖回归；可另报 Adapter 内部开销用于定位，但不得用该内部值替代端到端目标。
6. **环境不足**：test double、mock/demo 模型和 MockTransport 只能证明功能/测量方法，不能宣称生产性能。没有真实外部模型/工具或等价环境时，性能子指标记 `pending_env`；功能测试与 CM08 证据诚信可独立通过，但 T9 最多“有条件通过/待补性能证据”，不能写完全通过。

## 5. 合规核对

| 编号 | 核对项 | 通过判据与证据 | 溯源 |
|---|---|---|---|
| C1 | 数据库与公开兼容性 | 无迁移/ORM/公共 HTTP/SSE schema/前端变更；公共 API 路由、schema、状态码和错误体零变化，R15 的内部手工 header 400、内部 typed after 422、Open typed after/header 422 及合法 max/strict replay 有实际 ASGI/FastAPI 路由证据；动态 heads、空库 upgrade、目录零漂移和存量行证据齐全；Phase 1 DTO 不变 | AC-4/9、R1/R15、P2-IT-05/06、P2-CM-01/05/07 |
| C2 | 身份、多租户与敏感信息 | R16 私有 Execution UUID 规范化有完整证据：精确 stdlib 原对象、UUID 子类受控转换、两侧 `==` 值相等、公共 Request 精确 stdlib UUID、真实 asyncpg 链与 Context/RuntimeFactory 原 row 保留；伪造输入和恶意普通异常仅安全静态 `INVALID_REQUEST`，控制流重抛，原 row.id 不改写。快照 Agent UUID 严格、nil 仅限内部 Request 且不泄漏/查询；跨租户不可达；公共错误/Result/日志/指标不含秘密、原始异常、history/Outcome/Context | AC-1/4/5/9、R2/R4/R16、P2-UT-01、P2-IT-18/20、P2-CM-03/04 |
| C3 | 双 emit、事件所有权与结构化交付语义 | Context 无 emit，worker_emit 仅 Worker/Orchestrator，runtime_emit 仅私有 Runtime 链；普通业务事件经公共流后开放透传，run.* 仅 Repository、tool.replay 仅 DurableToolReplayCache、delta 仅 Notifier，伪造事件不到 worker_emit；React 首发 gate/no-stream、ack identity/exactly-once/abort 有独立证据，公共 suite 25 函数逐项裁定，LocalTest claim 前入队/terminal 丢弃/yield=delivery 不变 | AC-3/4、R3/R5/R6、P2-UT-03/05/09/17～21 |
| C4 | 配置、发布与依赖治理 | 默认 off、启动生效、fingerprint 排除、on fail fast、混合 Workers/回滚可证；Core 无反向应用依赖，无第二套 ReAct/新服务 | AC-3/8、R3/R8/R9、P2-CM-02/06 |
| C5 | 生命周期、功能/性能出口与证据诚信 | T8 才创建双语 06、T9 才创建双语 07；每条测试和 A/C 有实际结果，功能 UT/IT/CM 全过，CM08 证据诚信/测量边界独立通过；本地/CI/人工分开，性能 pending_env 如实且 T9 最多有条件通过；T10/T11 在验收后且只追加附录，失败重开 | AC-8/9、R11/R12、04 全部主/附录用例 |

## 6. 通过标准、遗留与签字

### 6.1 正式主验收（T9）

- A1～A9 的**主场景**及 C1～C5 全部有证据并满足判据；T8 主测试出口已满足，无开放 P0/P1。
- P2 仅可在产品/业务负责人明确接受并有 owner、期限、影响范围时有条件通过；P3 记录排期。
- 性能若未达到真实外部环境测量条件，仅性能子指标标 `pending_env`；这不否定已全绿的功能 UT/IT/CM 与 CM08 证据诚信/测量边界，但 T9 总体最多“有条件通过/待补性能证据”，不能写完全通过。
- 验收人签署结论、日期、提交、证据链接和遗留项；代码合入或 CI green 本身不能替代签字。

### 6.2 验收后附录（T11）

T10/T11 不反向提前成为 T9 的预置条件；其实际结果必须补入 06/07 和 A8/C5 附录。若种子或 quickstart 验证失败，重开 A8 及相关 C 项，修复并复验后才可恢复结论；旧报告原文和失败证据保留。

### 6.3 签字表（实际验收时填写）

| 角色 | 姓名 | 结论 | 日期 | 证据/备注 |
|---|---|---|---|---|
| 后端负责人 | 待填写 | 待验收 | 待填写 | 待填写 |
| QA | 待填写 | 待验收 | 待填写 | 待填写 |
| SRE/发布负责人 | 待填写 | 待验收 | 待填写 | 待填写 |
| 安全/平台评审人 | 待填写 | 待验收 | 待填写 | 待填写 |
| 产品/业务验收人 | 待填写 | 待验收 | 待填写 | 待填写 |
