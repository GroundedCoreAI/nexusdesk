# Phase 6 · 安全、可靠性与事件治理 — 技术落地文档

> 状态：已批准作为直接继续实施的基线；2026-11-16 已按代码现实核查，尚未实施、尚未验收；不可信执行保持关闭。
> 创建：2026-11-02
> 修订：2026-11-16（重核 Phase 4/5 代码、测试、组合根、CI 与迁移图；选择增量分片方案；替换过期路径与迁移号）
> 依据：`01-business-goals.md`（G1~G7）、`02-requirements.md`（FR-1~FR-16、AC-1~AC-16）、架构第 7~10、12、16~22 节、`08-implementation-breakdown.md` R-1~R-15

用户“直接继续”的指令授权按既有 01～05 范围开发，但不虚构上游验收、真实环境、独立批准或已测基线。Phase 6 最终验收仍须满足 04/05 的全部适用门禁。

## 1. 现状核查与约束

| 核查面 | 2026-11-16 已核实事实 | 约束性设计结论 |
|---|---|---|
| 迁移图 | 单一 head 为 `0067_merge_heads`，连接 `0066_hosted_web` 与 `0059_execution_runtime_host`；旧规划 0056/0057 已占用。 | 规划 `0068_execution_fencing`（文件 `0068_execution_fencing_event_outbox.py`），`down_revision="0067_merge_heads"`；再规划 `0069_execution_credential`，`down_revision="0068_execution_fencing"`；T-02 前立即重验。 |
| Run/Lease | `agent_runtime/repository.py` 已按 `owner`、`lease_until`、取消和终态做条件校验；`claim` 不递增 epoch，`reap` 直接失败/取消过期行而非接管所有权。 | 新增数据库单调 `lease_epoch`，把 `(run_id, owner, lease_epoch)` 贯穿所有 Worker/Host/Workspace/replay 变更；保持 Run=一次尝试并复用队列。 |
| Worker/编排器 | `worker.py` 持有 Worker UUID 与 heartbeat；`ExecutionContext` 已携带 `owner`；`ExecutionOutcome.usage` 已存在，但 `RuntimeWorker.finish` 未持久化。 | 扩展这些既有接缝；Worker 不增加 Engine 分支，Fencing Token 不进入客户端 DTO 或 AgentConfig。 |
| 事件契约 | `contracts/events.py` 已定义 `AgentEvent.event_id`、`schema_version="v1"`、执行身份、Adapter 本地 sequence、source、timestamp、payload 和 trace ID；`orchestrator.py` 当前只向 Worker 传 `event_type` 与 `payload`。 | 保留既有信封并传到持久化。Adapter 本地 sequence 不等于 Run 内持久 `runtime_events.seq`；数据库仍是顺序权威。 |
| 事件写入 | `RunRepository._event` 在同一事务递增 `runtime_runs.event_seq` 并插入 `runtime_events`；`tool_gateway/replay.py` 是第二条生产插入路径；seed 也直接写历史/演示行。 | 用数据库默认值、Outbox 插入触发器与对账保证旧代码和直接写入不绕过可发布事件的发布；tool replay 增加 Fencing，其内部 payload 永不发布；历史不重编号，不批量重发迁移前事件。 |
| Outbox/投递 | 当前无 runtime Outbox；`platform_services/events.py` 已提供基于 `memory_tasks`、按幂等键至少一次投递的 `DurableEventBus`。 | 只新增 runtime 事务 Outbox 与调度器；通过明确的 enqueue 确认端口复用 durable bus；不引入新 broker，不宣称网络层 exactly-once；SSE 仍读 `runtime_events`。 |
| SSE | `runtime_routes.py` 已先鉴权、合并 `after`/`Last-Event-ID`、每页 200 条、保持 `id=seq`、NOTIFY 仅唤醒、`model.delta` 瞬时；无保留下界或 replay gap 响应。 | 保留上述语义；增加附加信封元数据、明确 400/409 和单调的 Run 级保留下界。 |
| Usage | React/Codex result 可带 usage；Codex 对缺项保持 unknown 而不填零；既有 `gateway_costs` 是按 attempt 记录的模型网关独立账务路径。 | 新增按稳定来源标识去重的 Execution usage 台账；不复用或重复计算 `gateway_costs`；修正形成可追踪链，旧 epoch 不得写入。 |
| Parser | Codex 解析已有大小边界、静态 protocol error、payload 过滤/截断；尚无分类、关联、率限的诊断记录。 | 扩展现有 mapper/parser 与统一脱敏；不新建第二套原生协议或原始样本事件流。 |
| 凭据 | `platform_services/secrets/vault.py` 提供绑定模型连接/地址的 Fernet 加密；模型凭据创建时可配密钥；没有 Execution grant/Broker。 | 新建 Execution 专用记录、绑定、grant hash 与审计；运行时缺密钥不自动创建；模型网关凭据保持独立。 |
| Host/沙箱 | Phase 4 已有 `RuntimeHost`、进程监管、资源管理、持久进程记录与 Workdir 清理；`LocalSandboxProvider` 明确拒绝任意/上传/不可信执行，且无 user/mount/network namespace 或 syscall 隔离。 | 扩展现有 Host 与 Sandbox Provider 端口；强 Provider 必须控制真实 launch/network/mount 边界；改名 Local 或只加 preexec 检查不算强沙箱。 |
| Workspace | `ExecutionWorkspaceManager` 与 `execution_workdir.py` 已实现平台生成路径、严格权限、no-follow、链接/竞态检查、作用域持久化、保留与清理。 | 复用并增加所有权保护；只补缺失的 mount/artifact 策略和强 Provider 接线。 |
| Codex/Stage B | Phase 5 Stage A CLI 已基于真实 Host；生产选择仍为 `react/native/v1`，生产 trusted-target registry 为空；App-Server transport、Session 持久化、审批与 Resume 仍锁定/未实现；Phase 5 07 仅为范围限定有条件通过。 | Phase 6 不完成 Phase 5B、不改生产路由；通用接缝用受控 Adapter 测试；真实 Session/Resume 与生产 Codex 发布证据仍是上游阻断。 |
| 组合根/配置 | 权威配置为 `core_platform/platform_services/platform_settings/settings.py`；组合根为 `applications/platform_runtime/runtime_composition.py`；runtime API 注册在 `applications/customer_service/application.py`。 | 扩展这些准确位置和既有 `.env.example`；新发布控制不进入 runtime fingerprint。 |
| CI | CI 执行 ruff+架构、全部非 PG、两个 PostgreSQL 17 分片（先 `alembic upgrade head`）及前端检查；默认 CI 不提供真实 Codex 或强沙箱证据。 | 确定性单测/PG 进入既有 lane；不可用真实 provider/sandbox/fault 环境不得写成通过；未变化的套件不在本地反复全跑。 |

## 2. 实施方案与备选比较

### 选定：在现有模块上按三个垂直切片扩展

1. **可靠性/事件底座**：0068、所有权/Fencing、持久事件身份/去重/Outbox、SSE 缺口、usage 与诊断。
2. **执行安全**：0069、Vault/Broker/脱敏、强 launch/network/mount enforcement，以及 Host/Workspace 接线。
3. **集成恢复与发布**：取消确认、重试/配额对账、组合/部署、聚焦回归、真实演练与可信报告。

这是保留现有队列、Run/API/SSE 契约、Host、Workspace、Adapter 边界、durable event bus 与模块化单体的最小方案；每个切片都可在不开放不可信租户的情况下测试。

### 备选：平行新建安全/可靠性/事件子系统

新建 Event Store、进程监管、Workspace store 与调度式所有权服务虽能暂时隔离新代码，却会复制现有事务边界、形成两个事实源。迁移、回滚、Fencing 覆盖与回归成本更高且无必要架构收益，故否决。

### 备选：一次性横向大爆炸实现

先完成所有 schema 和接口，再统一接线 16 个 FR，会使可测试垂直行为最晚出现，故否决。分阶段垂直切片能更早暴露 Fencing、事件、凭据与沙箱缺陷，同时不降低任何最终硬门禁。

## 3. 改动总览

| 层 | 具体文件 | 改动 | 溯源 |
|---|---|---|---|
| 迁移 | `backend/migrations/versions/0068_execution_fencing_event_outbox.py`（新） | epoch/取消/清理/重试/保留元数据、事件身份/去重、Outbox 触发器/表、usage 台账。 | FR-7~FR-14、FR-16 |
| 迁移 | `backend/migrations/versions/0069_execution_credential_security.py`（新） | Execution 凭据版本、短期 grant 元数据与吊销索引。 | FR-1、FR-2、FR-16 |
| 所有权/恢复 | `core_platform/agent_execution/reliability/{ownership,recovery,retry}.py`（新）；`agent_runtime/{repository,worker}.py`；`tool_gateway/replay.py` | 内部所有权值对象、条件写协调、恢复/重试决策；SQL 权威仍在 Repository。 | FR-7~FR-10 |
| 事件持久化 | `core_platform/agent_execution/events/{envelope,outbox,replay}.py`（新）；`agent_runtime/repository.py`；`orchestration/orchestrator.py` | 传递既有 AgentEvent、区分 Adapter/持久 sequence、去重、Outbox 调度与 replay gap。 | FR-11~FR-13 |
| 既有 durable bus | `core_platform/platform_services/events.py` | 为 runtime Outbox 增加明确的 enqueue 确认操作；既有 `publish` 行为保持兼容。 | FR-12 |
| Usage/诊断 | `core_platform/agent_execution/events/{usage,diagnostics}.py`（新）；`adapters/{react,codex}`；`orchestration/execution_lifecycle.py`；`agent_runtime/worker.py` | 稳定来源身份、修正链、有界分类诊断和终态 usage 持久化。 | FR-14、FR-15 |
| SSE/API | `applications/customer_service/runtime_routes.py` | 保留既有字段与 `id=seq`；增加保留命名空间信封元数据及 400/409。 | FR-13 |
| 凭据 | `core_platform/agent_execution/credentials/{models,vault,broker,repository}.py`（新） | 兼容 Fernet 的安装密钥原语、Execution AAD/绑定、一次性 grant、轮换/吊销与审计。 | FR-1、FR-2 |
| 凭据 API | `applications/customer_service/execution_credential_routes.py`（新）；`application.py` | 仅管理员创建/轮换/吊销/元数据操作；无 Secret 回读接口。 | FR-1、FR-16 |
| 脱敏 | `core_platform/agent_execution/security/redaction.py`（新）；既有 Host/Adapter/API 边界 | 注册 Secret/canary/模式脱敏、有界诊断与泄露处置钩子。 | FR-3、FR-15 |
| 强沙箱 | `core_platform/agent_execution/host/{docker_sandbox_provider,network_policy,egress_proxy}.py`（新）；`{sandbox_provider,process_runner,runtime_host,resource_manager}.py` | Provider 生成内部 launch plan、非特权容器、cgroup 限制、最小挂载、真实默认拒绝网络与受管 allowlist proxy。 | FR-4~FR-6 |
| Workspace/Host 所有权 | `agent_execution/workspace/{workspace_provider,workspace_manager,execution_workdir}.py`；`host/process_registry.py` | 接收内部所有权/恢复授权，并在 SQL 中约束进程/Workdir 变更与释放。 | FR-6~FR-9 |
| 组合根 | `applications/platform_runtime/runtime_composition.py` | 按启动/关闭顺序组装 Outbox、凭据、脱敏、所选沙箱与恢复循环；失败关闭。 | FR-1~FR-16 |
| 配置 | `core_platform/platform_services/platform_settings/settings.py`；`backend/.env.example`；`deploy/production/.env.example`；相关 Compose 文件 | 安全有界默认值、Secret 文件路径/占位、Docker 沙箱拓扑、保留和发布控制。 | FR-16 |
| 测试 | `backend/tests/test_execution_{migration,fencing,events,outbox,sse,usage,diagnostics,credentials,redaction,sandbox,recovery}.py`（新）；受影响既有套件 | 单元、PostgreSQL、多 Worker、真实进程、迁移、对抗与故障点证据，映射 04。 | AC-1~AC-16 |

上述 `core_platform/...` 均位于 `backend/src/agent_platform/` 下。既有模块是修改点，不得复制成第二套实现。

## 4. 数据模型与迁移 0068

### 4.1 `runtime_runs` 扩展

| 字段 | 类型/默认值 | 用途 |
|---|---|---|
| `lease_epoch` | BIGINT NOT NULL DEFAULT 0 | 每次新 claim/takeover 在事务内递增；新认领获得 epoch 1。 |
| `cancel_requested_at` / `cancel_confirmed_at` | TIMESTAMPTZ NULL | 区分取消意图与真实 Host/Workdir 确认；保留既有 boolean 兼容线上契约。 |
| `cleanup_status` / `cleanup_updated_at` | TEXT / TIMESTAMPTZ | `not_started/in_progress/completed/failed`；历史终态回填 `completed`，其余 `not_started`。 |
| `retry_of_run_id` / `attempt_no` | UUID 自引用 NULL / INT NOT NULL DEFAULT 1 | 关联人工/安全重试，不引入 Task 表。 |
| `side_effect_policy` | JSONB NULL | 服务端重试/副作用快照；客户端不得提供。 |
| `event_retention_floor_seq` | INTEGER NOT NULL DEFAULT 0 | 已知被保留清理删除的最大 seq；只能与合格删除同事务单调前进。 |

### 4.2 `runtime_events` 扩展

| 字段 | 类型/默认值 | 用途 |
|---|---|---|
| `event_id` | UUID；确定性回填后 NOT NULL + 全局 UNIQUE；新行默认 `gen_random_uuid()` | 重连、Outbox、消费端稳定身份；回填由 `run_id:seq` 按文档算法派生，重复执行不随机变化。 |
| `schema_version` | TEXT NOT NULL DEFAULT `v1` | 存量与旧写入保持 v1；未知主版本失败关闭。 |
| `source` | TEXT NOT NULL DEFAULT `platform` + CHECK | `platform` 或 `engine_native`。 |
| `producer_id` / `producer_event_id` | TEXT NULL | 可选稳定原生/生产者去重键；对 `(run_id, producer_id, producer_event_id)` 建部分唯一索引。 |
| `engine_session_id` / `trace_id` | TEXT NULL | 对齐现有 OpaqueString 契约；Session 不存在是合法状态。 |

保留 `(run_id,seq)` 主键、`type/data/created_at` 与历史 sequence。`AgentEvent.sequence` 仅为 Adapter 本地元数据，绝不覆盖持久 `seq`。T-01 在既有 v1 AgentEvent/持久化接缝增加可选 `producer_id`/`producer_event_id` 元数据；这是附加变更，既有生产者仍有效，React 的信封冲突防护同步覆盖这两个保留名。

### 4.3 `runtime_event_outbox`

| 字段 | 类型/约束 | 用途 |
|---|---|---|
| `(run_id, seq)` | 复合 PK/FK 到 `runtime_events` ON DELETE CASCADE | 每个可发布持久事件一条 Outbox。 |
| `event_id` | UUID NOT NULL UNIQUE | 发布与消费幂等身份。 |
| `status` | TEXT CHECK `pending/published` | 发布到既有 durable bus 的状态，不代表订阅者完成。 |
| `attempts` / `available_at` | INT / TIMESTAMPTZ | 有界重试/退避与重扫。 |
| `created_at` / `published_at` | TIMESTAMPTZ | lag 与恢复证据。 |
| `last_error` | TEXT NULL | 有界脱敏稳定诊断；不含事件 payload。 |

`AFTER INSERT` 触发器为**每个可发布**新事件在同一事务创建 Outbox，包括旧二进制和直接生产写入；内部 `tool.replay` 类型明确排除，因为其幂等 payload 不是公共扩展事件，但仍获得事件身份与 Fencing。应用可使用 `ON CONFLICT DO NOTHING`，不得替代触发器。迁移不给迁移前历史创建 Outbox，而记录灰度水位，只对水位后缺失的可发布行对账，避免直接写入缺口、内部 payload 泄露和历史事件洪峰。保留清理只能删除 Outbox 已发布的事件；随后 cascade 删除发布行，usage/audit 仍保留。

### 4.4 `runtime_usage_ledger`

| 字段 | 类型/约束 | 用途 |
|---|---|---|
| `id` | UUID PK | 来源记录 ID。 |
| `run_id` / `tenant_id` / `lease_epoch` | UUID FK / TEXT / BIGINT | 作用域与所有权证据；tenant 冗余用于有界作用域查询。 |
| `source` / `source_event_id` / `usage_schema_version` | TEXT | 唯一来源与版本化解析；终态 result usage 使用如 `engine_terminal:result` 的确定来源，修正报告使用新 source ID。 |
| `usage` | JSONB NOT NULL | 校验后的测量值；unknown 标记保持显式。 |
| `cost` / `is_estimate` | NUMERIC NULL / BOOLEAN NOT NULL | 成本缺失保持 NULL；估计值明确标记。 |
| `supersedes_id` | UUID 自引用 NULL | 供应商修正链；聚合只取有效叶节点。 |
| `created_at` / `updated_at` | TIMESTAMPTZ | 重建与审计。 |

使用 `UNIQUE(run_id, source, source_event_id)`；重复投递返回原行，不占新 sequence、不改变聚合。模型网关 `gateway_costs` 保持独立，不复制、不隐式合并求和。

### 4.5 迁移执行规则

- T-02 必须重验单一 head；若已变化，先登记 R-n 并同步修订 01/03/04/05/08 双语，再创建文件；不得编辑 0001～0067 或其他已合入迁移。
- 使用 expand → 确定性批量回填 → validate → 读写切换；在存量副本测量加 NOT NULL/check/unique 前的锁耗时；扩展期保持旧行默认兼容。
- 开启 epoch 强制前必须排干旧 Worker；不支持新旧强制混写。回滚同样先停新执行并排干新 Writer，再运行旧代码；旧代码不得删除新列/表。
- 正常回滚保留扩展；有数据 downgrade 需显式导出/保护，不属于常规回滚。

## 5. 数据模型与迁移 0069

### 5.1 `execution_credentials`

| 字段 | 类型/约束 | 用途 |
|---|---|---|
| `id` / `credential_ref` / `tenant_id` | UUID 版本行 PK / UUID + 索引 / TEXT + 索引 | 不可变版本行 ID、稳定公共凭据引用与租户边界；增加 `UNIQUE(credential_ref, version)`。 |
| `name` / `credential_type` | TEXT | 管理标识与类型化 Secret 处理。 |
| `encrypted_secret` / `key_version` | TEXT | 带 Execution 绑定的安装密钥加密；不存明文。 |
| `version` / `status` | INT / TEXT CHECK `active/superseded/revoked` | 轮换插入新版本行并 supersede 旧行；吊销作用于全部版本。 |
| `allowed_engines` / `allowed_workspaces` | JSONB | 最大范围；Broker 每次 grant 再收窄。 |
| `created_at` / `updated_at` / `rotated_at` / `revoked_at` | TIMESTAMPTZ | 生命周期审计。 |

### 5.2 `execution_credential_grants`

| 字段 | 类型/约束 | 用途 |
|---|---|---|
| `id` / `grant_hash` | UUID PK / TEXT UNIQUE | 内部 grant 身份与不可逆校验；不存可重放 Token 明文。 |
| `credential_id` / `credential_version` | UUID FK / INT | 固定签发时 Secret 版本。 |
| `run_id` / `tenant_id` | UUID FK / TEXT + 索引 | Execution 与租户绑定。 |
| `engine_id` / `protocol_id` / `workspace_id` | TEXT | 受众与 Workspace 绑定；当前 Workspace 类型为 TEXT。 |
| `scopes` | JSONB NOT NULL | 最小环境/挂载/操作权限范围。 |
| `issued_at` / `expires_at` / `revoked_at` / `last_used_at` | TIMESTAMPTZ | TTL、吊销与使用审计。 |

轮换采用插入而非覆盖，grant 始终引用其固定的确切凭据版本行；只有最新 active 版本可签发新 grant，superseded 版本不可新签发，既有 grant 在未显式吊销时正常到期。grant 不跨 Run；未来 Session Resume 必须通过同一 Broker 端口重新授权新 grant，Phase 6 不新增缺失的 Stage B Session store。Secret 仅存在于受控 launch channel。外键删除与保留须遵守现有 Run 保留并保全审计；任何 cascade 不得抹去必要安全历史。

## 6. 核心流程

### 6.1 Claim、Fencing 与资源所有权

```text
claim/takeover 事务锁定 Run
→ lease_epoch += 1；替换 owner + lease_until
→ Worker 构造内部 ExecutionOwnership(run_id, owner, lease_epoch)
→ snapshot/append/finish/usage/replay/Host/process/Workdir 写在 SQL 断言同一元组
→ 过期元组匹配零行并回滚整个变更
→ 回滚后以独立事务记录有界 Fencing 审计/指标
```

先查后写只用于诊断。Host/process 与 Workdir 更新必须 join 或以其他方式约束当前 `runtime_runs` 所有权；独立恢复通过 fence 旧 epoch 获取显式 recovery authority，绝不冒充旧 Worker。Token 仅在 Worker/ExecutionContext/Adapter/Host 内部端口传递。

### 6.2 持久事件、去重、Outbox 与 Usage

```text
Adapter 发出既有 AgentEvent
→ Orchestrator 把完整信封交给 Worker event sink
→ Repository 在事务内校验当前 epoch、schema、source、大小与去重键
→ event_id/producer key 重复时返回原持久结果，不递增 event_seq
→ 新事件原子递增 runtime_runs.event_seq 并插入 runtime_events
→ AFTER INSERT 触发器同事务为可发布类型插入 runtime_event_outbox（绝不发布 tool.replay）
→ 必要 usage 按来源唯一约束同事务写入
→ 提交后 NOTIFY 唤醒 SSE，Outbox dispatcher 扫描 pending
→ 以 event_id 为 idempotency_key 经确认 enqueue 到既有 DurableEventBus
→ 标记 Outbox published；发布前后崩溃均可安全重试
```

发布时 dispatcher join Run tenant，并映射为既有 `EventEnvelope`：沿用 `event_id`、`event_type`，`event_version=1`、`aggregate_type="runtime_run"`、`aggregate_id=run_id`、脱敏业务 payload/元数据、`idempotency_key=str(event_id)`；仅 trace_id 是合法 UUID 时设置 `correlation_id`。durable bus 随后向订阅者至少一次投递；Outbox `published` 表示 durable transport 已接收，不表示每个订阅者已提交。SSE 不依赖发布器健康。`RunRepository._event` 创建的平台事件同样获得 v1 身份/默认值/触发器行为。

### 6.3 SSE 重放与保留

```text
鉴权 Run/tenant/scope
→ after 与 Last-Event-ID 取大值；非法输入 400
→ cursor < event_retention_floor_seq 时返回 409 event_replay_gap + 安全 reset floor
→ 按 seq 每页 200 条读取持久事件
→ 发送 id=seq、event=type、既有 data 字段 + 保留的 _execution 元数据
→ _execution 包含 event_id/schema_version/source/trace_id；旧 key 不移动、不改名
→ 瞬时 model.delta 仍不进入持久游标
→ Run 终态且 cursor >= event_seq 后结束
```

灰度期保留清理默认关闭。启用后只删合格行，并在同事务推进下界；不得删除账务/安全所需 usage/audit。附加 `_execution` 元数据是唯一获准的 Phase 0 线上差异；历史字段与 SSE `id` 语义不变。

### 6.4 Vault/Broker、脱敏与启动

```text
管理员按凭据引用创建/轮换/吊销；无 Secret 回读 API
→ Host start 前 Broker 校验 tenant/agent/run/engine/protocol/workspace/version/scopes
→ 事务保存 grant hash/元数据与无 Secret 审计
→ 强 Sandbox 准备 launch、网络、挂载与资源限制
→ Broker 仅向该 Execution channel 物化 allowlist 中的 Secret 值
→ 统一脱敏覆盖日志/事件/SSE/错误/审计/诊断/产物元数据
→ 到期/吊销/终态清理时吊销 grant 并销毁 channel
```

默认 grant TTL 为 300 秒，部署硬上限 3600 秒。缺密钥、绑定不匹配、过期、跨原 Run 重放和沙箱不可用均在启动前拒绝。泄露处置吊销相关凭据并停止新执行；取证记录仅含标识与稳定错误码。

### 6.5 强沙箱、网络与文件

`LocalSandboxProvider` 保持受控/可信开发 Provider，继续拒绝不可信执行。`DockerSandboxProvider` 是首个强 Provider 实现候选，只有真实 support probe 通过才可选择。它必须：

- 通过既有 Sandbox Provider/Runner 接缝生成服务端 launch plan；Execution 内无客户端 argv 或 Docker socket；
- 使用非特权用户、只读根、drop capabilities、no-new-privileges、seccomp、PID/CPU/内存限制，仅挂载单次 Execution Workdir/Secret；
- 无放行时使用 `--network=none`；任何放行都必须使用受管的单次 Execution egress proxy/network，逐跳校验 DNS/IP/port 并固定实际连接 IP；
- 拒绝私网/链路本地/元数据地址、DNS rebinding、未授权重定向、隧道及绕过 proxy 的直连；
- 仅经 Workspace 授权导出产物，不残留容器、网络、挂载或 Secret。

能创建非特权 sibling 容器/网络的 Docker daemon 是真实环境前置，mock 不能提供该证据。任一必需维度无法 enforcement 时准入失败关闭，`execution_untrusted_tenants_enabled` 保持 false。

### 6.6 恢复、取消、重试与配额

```text
持久化取消/超时/Worker 丢失意图
→ 新业务写入前 recovery fence 旧 epoch
→ 既有 Supervisor 确认进程组退出或 cleanup_failed
→ Workspace/Host/grant/network 清理完成，或留下明确可重试失败
→ 只有确认取消才提交 cancelled + 最终事件 + Outbox
→ Run 活跃容量与 Host 资源预留按各自真实证据独立释放
```

自动重试仅限已证明未启动且无副作用的失败；新 attempt 使用 `retry_of_run_id`、`attempt_no+1` 和新的 claim epoch。模糊超时/断连/外部写入默认人工处理。复用 Phase 4 进程/Workdir 恢复，Phase 6 负责与 Run 所有权及终态/事件事务协调。

### 6.7 Usage 修正与 Parser 诊断

- 终态 `ExecutionOutcome.usage` 以确定来源身份传入 `RunRepository.finish`；重复 finish/replay 不重复计数。
- 原生 usage 在可用时使用稳定 producer/native 身份；缺项保持 unknown；供应商修正用 `supersedes_id`；聚合从有效台账叶节点重建。
- Parser 诊断分类为 `malformed`、`unknown_schema`、`unknown_type`、`size_limit`、`critical_terminal`，关联 Run/protocol/adapter，并按 Run 率限。
- 原始样本默认关闭；临时启用时也必须脱敏、最多 1024 字节、私有且有保留期限；诊断失败不得递归生成诊断。
- Codex 既有 malformed/oversized 行为与 payload 过滤作为回归输入，不被替换。

## 7. 配置

在 `platform_settings/settings.py` 新增下列配置，发布控制不进入 runtime fingerprint：

| 配置 | 默认值与边界 | 含义 |
|---|---|---|
| `execution_untrusted_tenants_enabled` | `false` | 不可信开放总门禁；不能绕过子策略或独立批准。 |
| `execution_sandbox_required` | `true` | 不可信执行无宿主降级。 |
| `execution_sandbox_provider` | 既有 `local`；T-08 才增加 `docker` | Local 非强沙箱；Docker 需 support probe。 |
| `execution_network_default_deny` | `true` | 默认无直接 egress。 |
| `execution_credential_grant_ttl_seconds` | `300`，范围 30～3600 | 短期 grant 与硬上限。 |
| `execution_outbox_enabled` | 灰度期 `false` | 只控制 dispatcher；持久化、触发器、Fencing、脱敏不关闭。 |
| `execution_outbox_batch_size` / `execution_outbox_poll_seconds` | `100` / `1.0` | 有界扫描/重试节奏。 |
| `execution_event_retention_days` | `30`，范围 1～3650 | 仅在清理启用时使用的保留策略。 |
| `execution_event_cleanup_enabled` | `false` | 防止灰度时立即删除历史。 |
| `execution_parser_raw_sample_enabled` | `false` | 原始样本默认关闭。 |
| `execution_parser_sample_max_bytes` / `execution_parser_max_diagnostics_per_minute` | `1024` / `10` | 有界私有诊断。 |
| `execution_credential_key_file` | 本地 `data/credentials/execution.key`；生产设置 Secret 挂载路径 | 缺失/不可读失败关闭；真实密钥来自部署 Secret 存储，示例不生成 Secret。 |

既有进程取消、wall、资源与 Workdir 配置仍是相应限制的唯一来源。新配置在 `.env.example` 仅写占位；不提交密钥、Token、密码或宿主 home 路径。

## 8. 模型调用与既有账务

本阶段不改变 React/Codex 模型选择、Stage A/B 门禁、生产 Adapter 选择、推理循环或模型网关 profile 行为。Execution 凭据与模型连接凭据不可互换。Execution usage 走 Adapter/ExecutionOutcome → Run 所有权校验 → `runtime_usage_ledger`；模型网关 `gateway_costs` 继续独立按 gateway attempt 记账。

## 9. 测试方案

| 层 | 用例 |
|---|---|
| 单测 | 所有权/重试矩阵、信封/去重、Outbox 状态、游标缺口、usage 修正、诊断、grant 绑定/TTL、脱敏、launch/network/path 策略、安全配置。 |
| PostgreSQL 集成 | 迁移/回填/触发器、双 Worker Fencing、直接写入覆盖/内部 replay 排除、state+event+Outbox+usage 故障、Outbox 重扫、多页 SSE、凭据审计。 |
| 真实进程/对抗 | 强容器逃逸/资源限制、DNS/元数据/proxy 攻击、链接/挂载/产物、Secret canary、SIGKILL/hang/timeout/cleanup failure。 |
| 聚焦回归 | 按 `08` §3 只重跑受影响 runtime、Orchestrator、Host、Workspace、Codex、凭据/egress 与迁移用例；全量由 CI 最终执行一次，不在未变化时反复执行。 |

详细 ID 见 `04-test-plan.md`；真实环境不可用保持 `pending_env` 并阻断对应最终门禁。

## 10. 上线与回滚

1. 保留直接继续的开发入口，同时记录 Phase 0 与完整 Phase 5 验收尚未完成；代码就绪不得写成阶段最终验收。
2. 重验 head，落地 0068，回填/校验并排干旧 Writer，再启用 epoch 强制。先开 Outbox 持久化、后开 dispatcher；每次切换前后对账 pending/缺失行。
3. 发布 SSE 附加元数据与默认关闭的保留清理，再发布 usage/诊断；启用删除前演练旧二进制读取与显式 replay gap。
4. 落地 0069 与凭据管理，不可信执行保持关闭；任何真实 Secret provider 场景前先在受控测试 Run 灰度 Broker/脱敏。
5. 只有 support probe 与真实攻击矩阵通过才启用强 Provider；`execution_untrusted_tenants_enabled=true` 还须所有 A/C 门禁及独立安全、SRE/运维批准。
6. 回滚关闭新执行、吊销 grant、隔离/清理活动沙箱、排干 Writer、关闭新发布器，同时保留表/事件/usage/凭据；旧二进制运行前对账 Outbox，禁止用删数据 downgrade 作为常规回滚。
7. 任一 Secret 泄露、成功逃逸、有效过期写、重复计费、静默事件缺口或终态/账务不一致都停止新执行并阻断验收；五轮协调上限不是豁免硬门禁的依据。
