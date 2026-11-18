# Phase 6 · 安全、可靠性与事件治理 — 实施拆解方案

> 状态：已裁定，作为开发/测试实施基线；本文不代表任何任务已实现，也不预设验收结论。
> 创建：2026-11-16
> 修订：2026-11-18（范围受限验收修订：R-5/R-15 的 Phase 0 零 diff 与真实/已测基线、性能/锁指标、样本/配对/报表延迟、CI 全量证据不再是阶段验收门槛，仅作历史背景或高风险启用/生产放量前置；R-9 真实能力单列为高风险启用/能力前置。本文记录的历史裁定与证据数值不变，仅其阶段门槛状态按 05/07 的 2026-11-18 修订解释）
> 依据：`01`～`05`、架构第 7～10/12/17～22 节，以及对分支 `feat/agent-execution-platform-v2-phase6`、基线 `7772a32324f2eb6bb2c5de141baed4350aa53715` 后端代码/测试的直接核查。
> 约束：直接继续授权仅针对已批准范围。保持模块化单体、Run=一次尝试、既有队列/Host/Workspace/事件契约及全部安全/数据/真实环境硬门禁；最多五轮协调返工，之后仍未解决的硬门禁争议继续阻断，仅真正非核心 P2/P3 项可协商转后续。

## 1. 选定交付形态与依赖顺序

采用 `03-technical-design.md` §2 选定的**增量三垂直切片方案**：

1. 可靠性/事件底座（T-01～T-06）。
2. 执行凭据与强隔离底座（T-07～T-08）。
3. 集成恢复、发布与证据（T-09～T-12）。

备选“平行替换栈”因制造两个事实源被否决；“一次性横向大爆炸”因垂直验证过晚、回滚风险高被否决。T-07 可在 T-03 后与 T-04～T-06 并行，但迁移图中 0071 始终在 0070 之后。任何任务都不得开放不可信执行。

| # | 任务与具体完成边界 | 文件（新建/修改） | 依赖 | 快速自检范围 | 溯源 |
|---|---|---|---|---|---|
| T-01 | 冻结内部所有权/事件/凭据 DTO 与有界配置默认值；Token 仅在服务端内部；默认值不得开放暴露或删除历史。 | `core_platform/agent_execution/reliability/ownership.py`（新）、`events/envelope.py`（新）、`credentials/models.py`（新）、`platform_settings/settings.py`、settings 测试 | — | 新 DTO/settings 单测；`test_agent_execution_phase4_settings.py`；ruff | FR-1、FR-7、FR-11、FR-16；AC-16；R-3/R-10/R-11 |
| T-02 | 新增 0070 扩展、确定性事件回填、Outbox 触发器/水位/对账、usage 台账与保数据 downgrade 策略；先重验实际 head。 | `backend/migrations/versions/0070_execution_fencing_event_outbox.py`（新）、`backend/tests/test_execution_migration.py`（新）、迁移 fixtures | T-01 | 全新/存量 PG 升级；重复回填；旧结构可发布插入获得 ID+Outbox，内部 replay 不产生公共 Outbox；锁/耗时证据；head 图检查 | FR-7～FR-14、FR-16；AC-16；R-1/R-4/R-10 |
| T-03 | 实现单调 claim/takeover epoch，并在 snapshot、append/finish、heartbeat、usage、tool replay、process、Workdir 与资源释放上强制所有权；增加独立拒绝审计。 | `agent_runtime/{repository,worker}.py`、`orchestration/{execution_context,orchestrator}.py`、`tool_gateway/replay.py`、`host/process_registry.py`、`workspace/{workspace_provider,workspace_manager}.py`、`reliability/ownership.py`、`backend/tests/test_execution_fencing.py`（新） | T-02 | 新双 Worker/过期写矩阵，以及受影响的既有 claim/cancel/replay/Host/Workdir 用例 | FR-7～FR-9；AC-7～AC-9；R-2/R-12/R-13/R-14 |
| T-04 | 在 Orchestrator/Worker 间保留 AgentEvent；去重不占持久 seq；通过确认 enqueue 到既有 DurableEventBus 完成 Outbox 调度。 | `events/{envelope,outbox}.py`、`platform_services/events.py`、`agent_runtime/repository.py`、`orchestration/orchestrator.py`、`agent_runtime/worker.py`、`backend/tests/test_execution_{events,outbox}.py`（新） | T-03 | 并发去重、Adapter 本地 vs Run seq、提交/发布前后崩溃、直接写入发布、内部 replay 排除、bus 幂等 | FR-11、FR-12；AC-11、AC-12；R-3/R-4 |
| T-05 | 新增 SSE 保留命名空间信封元数据与保留下界 400/409；既有字段、`id=seq`、瞬时 delta、终态语义不变；清理仅在显式启用时运行。 | `events/replay.py`、`agent_runtime/repository.py`、`applications/customer_service/runtime_routes.py`、`backend/tests/test_execution_sse.py`（新） | T-04 | 超过 200 条重连、丢 NOTIFY、非法/过旧游标、终态追赶、既有 HTTP/SSE 用例 | FR-13；AC-13；R-10/R-15 |
| T-06 | 幂等持久化终态/原生 usage，支持修正链与可重建聚合；增加有界分类 parser 诊断，不替换既有 Codex 错误行为。 | `events/{usage,diagnostics}.py`、`orchestration/execution_lifecycle.py`、`agent_runtime/{repository,worker}.py`、`adapters/{react,codex}/*`、`backend/tests/test_execution_{usage,diagnostics}.py`（新） | T-04 | 重复/旧 epoch/修正/缺失 usage；malformed/unknown/oversized/率限/canary；既有 Codex mapper 用例 | FR-14、FR-15；AC-14、AC-15；R-8 |
| T-07 | 新增 0071、Execution Vault/Broker、管理员元数据/轮换/吊销 API、grant 绑定/TTL、审计、统一脱敏与泄露处置；无 Secret 回读 API，运行时缺密钥不自动创建。 | `backend/migrations/versions/0071_execution_credential.py`（新）、`credentials/{models,vault,broker,repository}.py`、`security/redaction.py`、`applications/customer_service/{execution_credential_routes.py,application.py}`、`backend/tests/test_execution_{credentials,redaction,migration}.py` | T-03 | 密文/AAD/绑定/吊销/过期/跨 Run；路由租户/角色；Secret 扫描；PG 迁移 | FR-1～FR-3；AC-1～AC-3；R-11 |
| T-08 | 扩展现有沙箱 launch 端口，实现真实 Docker 强 Provider、默认拒绝网络/受管 allowlist proxy、cgroup 限制、最小挂载与授权产物路径；Local 保持非强。 | `host/{sandbox_provider,docker_sandbox_provider,network_policy,egress_proxy,process_runner,runtime_host,resource_manager}.py`（新建/修改）、`workspace/execution_workdir.py`、`backend/tests/test_execution_sandbox.py`（新） | T-07 | 所有环境跑纯策略/support；专用环境跑真实 Linux Docker 逃逸、egress、挂载、fork/内存/磁盘与残留测试 | FR-4～FR-6；AC-4～AC-6；R-7 |
| T-09 | 集成 Worker 丢失、确认取消/超时、可重入清理、副作用感知重试、grant/network/Workdir 清理，以及独立 Run/Host 配额释放。 | `reliability/{recovery,retry}.py`、`agent_runtime/{repository,worker}.py`、`orchestration/orchestrator.py`、`host/{runtime_host,process_supervisor,process_registry}.py`、`workspace/workspace_manager.py`、`backend/tests/test_execution_recovery.py`（新） | T-06、T-08 | SIGKILL/heartbeat/迟到结果；正常/hang/清理失败；启动前 vs 模糊重试；终态/最终事件/配额对账 | FR-8～FR-10；AC-8～AC-10；R-2/R-13 |
| T-10 | 完成组合/部署接线、准入前启动恢复、Outbox/保留循环、安全关闭、指标告警与无 Secret 示例；保持生产 React selector 与 Stage B 锁定。 | `applications/platform_runtime/runtime_composition.py`、`backend/.env.example`、`deploy/production/.env.example`、`deploy/{quickstart,production}/compose.yaml`、settings/composition 测试 | T-09 | off 状态构造 diff、启动/关闭顺序、env 覆盖/默认值、Secret 扫描、架构门禁 | FR-16；AC-16；R-5/R-6/R-12 |
| T-11 | 完成全部代码侧 P6 UT/IT/CM，按需只跑受影响既有回归；最终全量后端/前端由 CI 执行一次；如实记录 skip 与 pending 环境。 | 所有受影响 `backend/tests/*`、`scripts/check_architecture.py` 使用方式；仅在确定性新 lane 需要注册时修改 `.github/workflows/ci.yml` | T-10 | ruff+架构；聚焦非 PG 与独立 Docker PG；最终 PR CI；每个任务后不重复本地全量 | 04 全部适用代码用例；AC-1～AC-16 代码部分 |
| T-12 | 执行真实对抗/故障/迁移/回滚演练并产出 06；逐条 A/C 验收并产出 07；缺独立批准或上游证据时不可信保持关闭。 | Phase 6 `06-test-report.md`（执行后新建）、`07-acceptance-report.md`（验收后新建）、链接外部证据 | T-11 | 04/05 每行独立结论/证据链接；pending_env/not_measured 不得写成通过 | 04/05 全部；G1～G7；R-5/R-9 |

表中 `core_platform/...` 位于 `backend/src/agent_platform/`。开发中如发现新的路径、迁移、公共契约或门禁冲突，必须先更新 03 与本文再改生产代码。

## 2. 文档与现实不一致清单及裁定

### R-1 — 规划迁移号已失效

**文档**：01/03/04/05 预留 0056/0057，旧核查仍写 head 0052。

**现实**：`0067_merge_heads.py:22–23` 是单一 head，连接 `0066_hosted_web` 与 `0059_execution_runtime_host`；0056/0057 已占用。

**裁定**：revision 标识使用 `0070_execution_fencing`（文件 `0070_execution_fencing_event_outbox.py`；`down_revision="0067_merge_heads"`）与 `0071_execution_credential`（`down_revision="0070_execution_fencing"`）。标识必须适配 `alembic_version.version_num VARCHAR(32)`（R-16）。T-02 动态重验；如有变化，先新增 R-n 并同步 01/03/04/05/08 再实施。

### R-2 — Host、监管、资源与 Workspace 已存在

**文档**：旧 03 使用规划中的 `host/{runtime_host,process_supervisor,resource_manager}` 与 `sandbox/` 路径，措辞近似尚未存在。

**现实**：Phase 4 实现已存在；`host/sandbox_provider.py:315–337` 定义 Provider 端口；`local_sandbox_provider.py:89–255` 实现受管本地进程；Workspace 已有持久路径/清理保护。

**裁定**：扩展现有 Host/Workspace 模块与测试；新可靠性代码只协调所有权，不替换进程监管、Workdir 持久化或 Repository SQL 权威。

### R-3 — 公共 AgentEvent 已存在，但身份被丢弃且 sequence 域不同

**文档**：旧核查称公共信封尚缺，且可能误把 AgentEvent.sequence 写入持久存储。

**现实**：`contracts/events.py:12–23` 已定义 v1 信封；`orchestration/orchestrator.py:337–341` 只发送 type/payload；Adapter mapper 从 1 开始计数，而 `runtime_runs.event_seq` 已包含 queued/started。

**裁定**：把信封传到 Repository，`runtime_events.seq` 仍是唯一持久 Run sequence，Adapter sequence 仅作生产者元数据；按 event_id 与可选稳定 producer key 去重；两个 producer 字段是附加的可选 v1 元数据，既有生产者保持有效。

### R-4 — 只在 Repository 做 Outbox 会漏生产写入

**文档**：旧设计主要把事件/Outbox 写入分配给 `RunRepository`。

**现实**：`tool_gateway/replay.py:80–119` 直接递增 event_seq 并插入；seed 也直接写入；`platform_services/events.py:117–327` 已有基于 `memory_tasks` 的至少一次 durable bus。

**裁定**：0070 增加数据库事件身份默认值、面向可发布类型的 AFTER-INSERT Outbox 触发器及灰度水位对账；内部 `tool.replay` 有身份和 Fencing，但绝不向扩展订阅者发布；T-03 为 tool replay 加 Fencing；T-04 给既有 bus 增加确认 enqueue 端口；不新建第二 Event Store 或外部 broker。

### R-5 — 上游验收前置尚未满足（真实需求冲突）

**文档**：01/05 写 Phase 6 前 Phase 0～5 已验收；用户授权直接继续。

**现实**：Phase 5 `07-acceptance-report.md:135–159` 仅给出 R18 范围限定代码就绪，有明确“Stage A 完整验收未通过、Stage B 未解锁”，Phase 0 diff、真实凭据/租户、稳定性和环境证据仍开放。

**裁定**：直接继续授权实施，不虚构前置通过。T-01～T-11 可在不可信关闭下开发；适用上游证据补齐前，最终 A16/C11 与 Phase 6 总体验收继续阻断，或由验收负责人如实给出更窄结论；不得删除硬门禁。

### R-6 — 生产 Codex 路由刻意不可达

**文档**：AC-16 要求 React/Codex 回归，但未授权路由重设计。

**现实**：`execution_context.py:42` 固定生产选择 React；`runtime_composition.py:901–919` 构造空 trusted-target registry；Phase 5 还记录 capability/workspace 拒绝。

**裁定**：Phase 6 不改生产 selector、trusted-target 注册、publish-path 映射或 Stage A/B 门禁；代码测试使用注入的受控 Codex/Host 接缝；生产 Codex 启用仍属上游/部署后续，回归证据不得冒充其已可用。

### R-7 — Local Sandbox 不能靠配置变强

**文档**：FR-4～FR-6 要求真实强隔离。

**现实**：`local_sandbox_provider.py:247–255` 拒绝不可信形态；端口只有 prepare/preexec/release，无容器 launch/network namespace 控制；settings 仅允许 `local`（`settings.py:142–148`）。

**裁定**：Local 保留给受控开发，新增显式 Provider launch-plan 接缝与真实 Docker Provider；仅改名 Local、增加路径检查或 mock `--network=none` 均不算验收；缺 Linux/Docker enforcement 时 A4～A6 保持 pending_env，不可信关闭。

### R-8 — Execution usage 与网关账务相互独立

**文档**：旧核查笼统称 usage 缺失，未区分既有模型网关成本账务。

**现实**：`ExecutionOutcome.usage` 已存在（`execution_lifecycle.py:14–84`），但 Worker finish 丢弃；`model_gateway/governance.py:440–451` 另按 attempt 写 `gateway_costs`。

**裁定**：在新来源唯一台账中以稳定终态/原生身份持久 Execution usage；不迁移、不复制、不隐式汇总 gateway costs；unknown 保持 unknown，修正用新来源记录与 supersedes 链接。

### R-9 — Engine Session/Resume 不存在

**文档**：FR-2/FR-7 与 AC-2/AC-7 包含 Resume 和 Session 写入。

**现实**：Phase 5 App-Server 只有 codec/state 原语；无 `agent_engine_sessions` 模型或迁移。

**裁定**：实现通用 Broker 重新授权与 Fencing 端口，用受控 fake 测试；Phase 6 不新增 Stage B Session 持久化；真实 Session/Resume 子步骤保持 `pending_upstream`，在 Phase 5B 提供能力前阻断对应完整 AC/上游发布结论，不得静默写成不适用。

### R-10 — 保留需要持久缺口下界与安全默认值

**文档**：FR-13 要求过旧游标显式处理，旧 schema 无下界且保留时机未定。

**现实**：`runtime_routes.py:83–154` 有重放但无清理/下界；现有部署无限期保留事件。

**裁定**：新增 `runtime_runs.event_retention_floor_seq`，与合格删除原子推进；默认 `execution_event_cleanup_enabled=false`，保留 30 天策略供后续评审启用；cursor 小于下界返回 409，不得静默从最早可用重置。

### R-11 — 模型 CredentialVault 不能当作 Execution 授权

**文档**：FR-1 要求缺密钥不自动重建，并要求 Execution 绑定。

**现实**：`platform_services/secrets/vault.py:13–60` 绑定 tenant/connection/address/protocol，支持 `create=True` 配密钥；无 Execution grant。

**裁定**：只复用 Fernet 经验；新 Execution AAD 包含 credential ID/tenant/version，grant 绑定 Run/engine/protocol/workspace/scope/expiry；运行时缺密钥不自动创建；既有模型/工具凭据行为不变。

### R-12 — 组合/配置路径已确认，但 Writer 灰度必须显式排干

**文档**：旧 03 组合路径正确，却默认新旧 Writer 可渐进共存，未定义 epoch 切换。

**现实**：settings/composition 路径与核查一致；旧 Writer 不提供 epoch，直接资源操作不校验 Run 所有权。

**裁定**：先兼容扩展，再停新执行并排干旧 Writer，之后强制 epoch；回滚也先排干新 Writer；不支持混合强制，schema 默认值本身不是 Fencing 证据。

### R-13 — 既有 reaper 不是完整恢复所有者

**文档**：FR-8/FR-9 要求恢复前 Fencing 与确认清理。

**现实**：`repository.py:586–610` 对过期行直接 failed/cancelled；Host 又独立 reconcile 进程记录，两者未由 epoch 或单一终态/Outbox 事务协调。

**裁定**：T-03 引入所有权/takeover 原语；T-09 在终态完成前协调 Host/Workdir/grant 清理；取消未确认时保持 failed/cleanup_failed/pending cleanup，绝不伪报 cancelled。

### R-14 — Fencing 审计不能随业务事务一起回滚

**文档**：FR-7 同时要求零部分写入与拒绝审计。

**现实**：过期条件写必须回滚业务事务；同事务插入的审计也会消失。

**裁定**：业务决定仅由条件 SQL rowcount/约束作出；回滚后在独立事务按可信 scope 记录有界拒绝审计/指标，不含 payload；审计失败不得把已拒绝写变成允许。

### R-15 — Phase 0 零回归 diff 必须区分附加事件元数据

**文档**：AC-16/C11 原要求 diff 为零，FR-13 又要求 SSE payload 携带 event_id/schema_version。

**现实**：`runtime_routes.py:120–121` 当前只序列化业务 `data`；把它移到新信封会破坏客户端，但增加事件身份必然改变序列化对象。

**裁定**：保留全部既有 key，仅增加保留的 `_execution.{event_id,schema_version,source,trace_id}` 元数据。Phase 0 兼容指除该明确评审的附加 key 外行为/回归 diff 为零；不允许其他线上变更、字段丢失、持久历史重排或瞬时 delta 语义变化。


### R-16 — Alembic revision 标识必须适配 ``VARCHAR(32)``

**文档：** R-1 与 01/03 把完整迁移名当作 revision 标识。

**现实：** ``alembic_version.version_num`` 为 ``VARCHAR(32)``；``0070_execution_fencing_event_outbox`` 长 36，规划的 ``0071_execution_credential`` 长 33，升级时会截断/失败。

**裁定：** 保留描述性文件名，revision 标识改用 ``0070_execution_fencing`` 与 ``0071_execution_credential``（均不超过 32）。0071 的 ``down_revision`` 为 ``0070_execution_fencing``。任务表中的文件名保持不变，仅标识字符串变化。


### R-17 — 受管 allowlist egress proxy 属于外部部署依赖

**文档：** T-08 与 FR-5 要求受管 allowlist egress proxy。

**现实：** Docker provider 可以生成每 Execution 的网络/挂载/资源计划，并在未配置代理端点时 fail closed，但本轮纯代码交付不包含 proxy 服务镜像或 daemon 侧 proxy 容器。默认拒绝（`--network=none`）已实现并本地演练；allowlist、DNS rebinding、metadata 与 proxy bypass 演练需要专用环境提供的受管代理。

**裁定：** 未配置 `execution_sandbox_docker_proxy_endpoint` 时 provider 拒绝 allowlist（fail closed，不开放直连）。该端点是部署级无 Secret URL。真实 allowlist/proxy 演练保持 `pending_env`，在受管代理交付并演练前 A5 不能通过。

### R-18 — 延后的启动、脱敏、原生用量与 allowlist 接线不是纯测试工作

**文档**：T-06 要求终态**和原生** usage 持久化；T-07 要求 Broker/脱敏/泄露处置；T-08 要求受管 allowlist proxy；T-10 要求组合接线。T-12 负责真实演练与报告，不负责缺失的生产行为。

**`671b637` 现实**：生产代码在 Codex/Host 启动处没有 Broker issue/consume 调用，也没有 Secret channel；`SecretRedactor` 无生产调用点，Outbox 直接转发存储 data，泄露处置未接线；`RunRepository.record_usage` 无 Adapter/Orchestrator 调用方，故只有终态 usage 被持久化。R-17 正确记录默认拒绝的失败关闭证据，但受管 allowlist 集成同样缺失。

**裁定（协调第 1 轮）**：(a)～(c) 是立即返回开发的修复，完成前不得再次宣称 code-ready，不得转为 T-12 测试债：
1. 在 spawn 前接线 Broker 签发/消费，绑定当前 Run/engine/protocol/workspace/scopes；Secret 仅物化到受控 launch channel，所有终态路径吊销/清理；证明拒绝时零 spawn 且日志/事件/DB 无 Secret。
2. 在日志、事件、SSE、Outbox、错误/诊断和产物信任边界统一脱敏；实现泄露触发的凭据吊销与准入关闭，并以 canary 断言。
3. 原生 usage 经 Adapter/Orchestrator 边界写入受所有权校验的来源唯一台账，使用稳定 producer 身份，保持重复/旧 epoch/修正/unknown 语义；仅终态持久化不算完成 FR-14。

对 (d)，R-17 的默认拒绝通过与 `pending_env` 结论保持有效，真实 allowlist/DNS/元数据/proxy-bypass 演练属于 T-12；但 R-17 不得把已批准的受管 proxy 集成整体改划为外部/测试工作：开发必须提供或集成受管 endpoint 并证明真实 enforcement 契约，之后才能宣称 T-08 code-complete。无 proxy 时 allowlist 保持不可用/失败关闭，A5 不得通过。真实多 Worker/故障演练同样属于 T-12。此裁定不改变任何 FR/AC、不豁免硬门禁；不可信执行保持关闭。


### R-19 — 真实网络边界、在线 reaper 确认、以及先 fence 后 cleanup

**文档：** 测试 preflight（协调第 1 轮）验证了 FR-5/FR-8/FR-9 下的三个生产阻断项。

**现实（`7c2373c`）：**（1）Docker allowlist 使用不受限 `--network=bridge` 加建议性 proxy 环境变量，并非真实网络边界；（2）在线 Worker 仍调用 `repository.reap()`，在未确认 cleanup 的情况下终态取消/失败过期 Run；（3）`RecoveryCoordinator` 在 `apply_recovery` 递增 epoch 之前执行 cleanup，导致 cleanup 运行在过期 ownership 下。

**裁定（同属协调第 1 轮，不计新一轮）：**（1）受管 allowlist 必须落实真实网络边界（internal 容器网络 + 受管 egress proxy，proxy 不可用时显式拒绝）；默认拒绝保持 `--network=none`。（2）在线 Worker reaper 路径必须使用已确认的 RecoveryCoordinator，未确认取消不得报告 cancelled。（3）recovery 必须先 fence/接管过期 claim（新 epoch），再在新 ownership 下执行 cleanup。这些是生产修复而非测试债；不变更 FR/AC 或硬门禁。

### R-20 — 集成分支前进并与 0068/0069 迁移号冲突

**文档：** 08 R-1/R-16 在规划号与其他分支冲突后，将阶段 6 revision 定为 `0070_execution_fencing` / `0071_execution_credential`。

**现实（PR #142 CI）：** `integration` 合入了自己的 `0068_open_application_archive` 与 `0069_open_app_unique_name`，两者都接在 `0067_merge_heads` 之后。PR 合并结果因此出现双 head，`alembic upgrade head` 在任何测试执行前即报 “Multiple head revisions are present”。

**裁定：** 将最新 `integration` 合入阶段 6 分支，并把阶段 6 revision 顺延为 `0070_execution_fencing`（文件 `0070_execution_fencing_event_outbox.py`，`down_revision="0069_open_app_unique_name"`）与 `0071_execution_credential`（文件 `0071_execution_credential.py`，`down_revision="0070_execution_fencing"`）。开放平台 0068/0069 现为历史迁移，不得修改。revision 标识仍满足 `VARCHAR(32)`。测试与 01/03/04/05/06/07 已同步；不变更 FR/AC、安全门禁或验收结论。


## 3. 聚焦回归复用（未变化不得全量重跑）

| 既有证据/用例 | 复用或重跑规则 |
|---|---|
| `test_runtime_postgres.py::test_concurrent_submit_and_exclusive_claim`、`::test_capacity_and_tenant_isolation` | T-03 前复用；T-03/T-09 改 claim/admission 后重跑。 |
| `::test_cancellation_wins_finish_race_and_event_replay`、`::test_lost_worker_is_failed_and_cannot_publish_late_result`、`::test_queue_expiration_and_cancel_without_worker` | T-03 与 T-09 后重跑；另加 epoch/清理断言，不放宽旧预期。 |
| `::test_http_api_authorization_conflicts_cancel_and_sse`、`::test_end_to_end_demo_uses_real_http_and_persistent_events` | T-05/T-09 后重跑；断言旧字段+附加 `_execution`，不做 SSE 字节完全相等。 |
| Phase 4 `test_agent_execution_phase4_supervisor.py` 真实 TERM/KILL/wall/crash 用例 | 未触碰 Host 行为时复用；仅在 T-08/T-09 修改对应路径后重跑。 |
| Phase 4 `test_agent_execution_phase4_sandbox.py` Local gate/support/release 用例 | T-08 后重跑，证明 Local 仍拒绝不可信执行；Linux 硬 cgroup pending 用例保持归因，不改成通过。 |
| Phase 4 `test_agent_execution_phase4_workdir.py` 路径/链接/竞态/租户/清理用例 | T-03/T-08/T-09 后重跑受影响路径与持久用例；未改纯策略用例复用。 |
| Phase 4 migration/settings/composition/orchestration 套件 | 仅重跑与 T-02/T-03/T-09/T-10 改动对应的文件。 |
| Codex `test_codex_events.py`、`test_codex_adapter_unit.py`、`test_host_stdin_delivery.py` | 仅在 T-06/T-07/T-08 改 mapper、Secret、launch 或诊断后重跑；保留 R18 stdin 语义。 |
| Codex `test_codex_host_integration.py` 与 Phase 4 PG Host 用例 | T-03/T-07/T-08/T-09 后在独立 Docker PostgreSQL 执行；CI 无二进制时真实 Codex 仍单独归因/pending。 |
| `test_gateway_credentials.py`、`test_tool_credentials.py`、`test_tool_egress.py`、`test_tool_workspace.py` | 凭据/网络/Workspace 改动后重跑；不得放宽既有模型/工具凭据语义。 |
| 全量后端/前端 | 最终 PR merge result 由 CI 执行；文档或每个任务后不在本地重复全量；失败修复后仅先重跑受影响范围。 |

## 4. 协调问题与门禁责任

1. **协调者/验收**：提供 Phase 0 baseline diff 并解决 Phase 5 完整验收前置，否则最终 Phase 6 结论保持阻断/收窄；直接继续不是证据。T-01 开发无需等待。
2. **开发/测试/验收**：确认可销毁 Linux 环境，Docker daemon 能创建非特权 sibling 容器、cgroup、可销毁网络/卷、DNS/元数据诱饵及两个 Worker；没有时 T-08 可按失败关闭落地，但 A4～A6 与阶段总体验收保持 `pending_env`。
3. **协调者/安全运维**：任何 `execution_untrusted_tenants_enabled=true` 请求前，指定独立安全与 SRE/运维批准人；四个实施子代理不能自我签发这些批准。
4. **开发/测试**：Stage B Session/Resume 与生产 Codex 路由不属于 Phase 6；使用受控测试 Adapter；真实 Session/Resume 和生产发布缺口按 R-5/R-6/R-9 报告，不扩大范围。
5. **测试/验收**：按 §3 复用既有通过证据，改动后重跑受影响用例，全量证据留给最终 CI；仅非代码/描述性 P2/P3 可由验收负责人有条件接受，硬门禁或主流程缺口不得豁免。

报告必须使用规定的 `06-test-report.md` 与 `07-acceptance-report.md` 模板；未到实际执行阶段不得预建报告。
