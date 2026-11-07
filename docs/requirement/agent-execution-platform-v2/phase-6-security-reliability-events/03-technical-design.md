# Phase 6 · 安全、可靠性与事件治理 — 技术落地文档

> 状态：待评审（仅规划，未实施；迁移号与目标路径均须实施前重核）
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1~G7）、`02-requirements.md`（FR-1~FR-16、AC-1~AC-16）、架构第 7~10、12、16~18 节

> 写本文前已核查现状代码、测试、迁移、凭据与 SSE 先例；修订时须在对应小节记录日期与原因。

## 现状核查与约束

| 核查面 | 2026-11-02 事实 | 本阶段约束 |
|---|---|---|
| Run/Lease | `agent_runtime/repository.py` 使用 owner、lease_until、终态检查与条件更新；`worker.py` heartbeat 丢失会取消 Task。 | 复用队列，新增单调 lease_epoch 并覆盖所有写入/资源操作；不能只保护 finish。 |
| Worker 恢复 | `reap()` 将过期 running 标 failed/worker_lost；`test_runtime_postgres.py` 覆盖迟到结果。 | 保留终态先例，补充接管、清理、重试副作用和 Host 存活证据。 |
| 事件事实源 | `runtime_runs.event_seq` 与 `runtime_events(run_id,seq)` 同事务更新；主键保证 Run 内顺序。 | 扩展 event_id/schema/source/dedup/Outbox，不替换历史 seq、不重编号。 |
| SSE | `customer_service/runtime_routes.py` 从 Event Store 分批读取，支持 `after`/`Last-Event-ID`，SSE id=seq，NOTIFY 仅唤醒；model.delta 为瞬时。 | 保留 wire 兼容与瞬时 delta 语义，补 event_id 去重、保留缺口与追赶竞态测试。 |
| 凭据 | `platform_services/secrets/vault.py` 使用安装密钥 Fernet；`0016_gateway_credentials` 和模型 Catalog 提供租户/地址绑定，无 Execution grant/Broker。 | 复用加密与绑定思路，新建 Engine Execution 专用记录和 Broker；不复用公共模型连接 ID 冒充 Execution 授权。 |
| 网络/文件 | `tool_gateway/egress.py` 有 HTTP 工具 host/IP 防护；逻辑 Workspace 有 scope。 | 可复用规范化/IP 判定经验，但任意子进程网络与挂载必须在 Sandbox/OS 边界执行，不能只靠 HTTP client。 |
| Codex/Host | 当前无 Codex 或 `agent_execution` 实现；Phase 4/5 是前置规划。 | 目标文件按 Phase 4/5 实际产物重核，不在本阶段重复实现 Adapter 或 RuntimeHost。 |
| 迁移 | 当前 head `0052_memory_tasks_tenant_index`；0055 为 Phase 5 条件性规划号。 | 0056/0057 均为规划预留；实际 down_revision 依实施时 head，不假设 0055 一定存在，不改历史迁移。 |

## 改动总览

| 层 | 文件 | 改动 | 溯源 |
|---|---|---|---|
| 凭据 | `backend/src/agent_platform/core_platform/agent_execution/credentials/{vault,broker,models,repository}.py` | Execution 凭据版本、短期 grant、范围/受众绑定、轮换/吊销/审计。 | FR-1、FR-2 |
| 脱敏 | `.../agent_execution/security/redaction.py`（或 Phase 4 实际安全包） | 统一日志/事件/错误/诊断/产物元数据脱敏与泄露处置接口。 | FR-3 |
| 沙箱 | `.../agent_execution/sandbox/{provider,policy,network,filesystem}.py` | 强沙箱策略、网络/文件边界与资源限制的 Engine 无关实现。 | FR-4~FR-6 |
| Host 接线 | `.../agent_execution/host/{runtime_host,process_supervisor,resource_manager}.py` | 在 Phase 4 实现上接入 sandbox、grant、真实退出/清理确认和 epoch。 | FR-2、FR-4、FR-7、FR-9 |
| 可靠性 | `.../agent_execution/reliability/{fencing,recovery,cancellation,retry}.py` | 所有权校验、Worker 接管、清理/配额协调和副作用重试分类。 | FR-7~FR-10 |
| Run 持久化 | `backend/src/agent_platform/core_platform/agent_runtime/repository.py` | claim/heartbeat/append/finish/reap 增加 epoch、取消/清理和事务性 Outbox/usage。 | FR-7~FR-12、FR-14 |
| 事件 | `.../agent_execution/events/{schema,store,dedup,outbox,dispatcher,replay}.py` | 版本化外层、去重、Outbox 发布/重扫、游标与保留缺口。 | FR-11~FR-13 |
| 用量/诊断 | `.../agent_execution/events/{usage,diagnostics}.py` | 来源唯一 usage 台账、聚合重建、parser 分类/率限/脱敏。 | FR-14、FR-15 |
| Adapter 接线 | Phase 1/5 实际 Adapter 基类与 Codex Provider | 传递原生去重键、schema、usage 和 parser 诊断；不在 Worker 加 Engine 分支。 | FR-11、FR-14、FR-15 |
| SSE/API | `backend/src/agent_platform/applications/customer_service/runtime_routes.py` | 保留 `id=seq`，补 event_id/schema、409 replay gap、重连/终态一致性。 | FR-13 |
| 组合根 | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | 组装 Vault/Broker/Sandbox/Recovery/Outbox/Usage；安全组件缺失时 fail closed。 | FR-1~FR-16 |
| 配置 | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | 有界 grant TTL、保留/清理/重试、默认拒绝网络和不可信总开关。 | FR-16 |
| 迁移 | `backend/migrations/versions/0056_execution_fencing_event_outbox.py` | 规划新增 epoch/取消清理/重试元数据、事件身份/dedup、Outbox 与 usage 台账。 | FR-7~FR-14 |
| 迁移 | `backend/migrations/versions/0057_execution_credential_security.py` | 规划新增 Execution 凭据和短期 grant 表；沙箱策略使用配置/Run 快照。 | FR-1、FR-2 |
| 部署 | `backend/.env.example`、`deploy/production/.env.example`、实际沙箱部署配置 | 只放无 Secret 占位、网络/挂载/资源策略；真实密钥由部署 Secret 管理。 | FR-1~FR-6、FR-16 |
| 测试 | `backend/tests/test_execution_{security,fencing,recovery,outbox,sse,usage,diagnostics}.py` | 单元/Postgres/多 Worker/故障点/沙箱对抗与迁移回归。 | AC-1~AC-16 |

> 上表省略号表示同一 `backend/src/agent_platform/core_platform/` 根目录；模块路径为规划边界，若 Phase 1~5 已有等价模块，应扩展而非平行新建。

## 数据模型

### 规划迁移 `0056_execution_fencing_event_outbox.py`

**A. `runtime_runs` 扩展**

| 字段 | 规划类型/约束 | 用途 |
|---|---|---|
| `lease_epoch` | BIGINT NOT NULL，存量回填 0 | claim/takeover 单调递增；与 owner 共同构成 Fencing 证据。 |
| `cancel_requested_at` / `cancel_confirmed_at` | TIMESTAMPTZ NULL | 区分取消请求与真实退出/清理确认。 |
| `cleanup_status` / `cleanup_updated_at` | TEXT / TIMESTAMPTZ | `not_started/in_progress/completed/failed`，支持重入恢复和告警。 |
| `retry_of_run_id` / `attempt_no` | UUID 自引用 NULL / INT | Run=一次尝试，关联重试而不引入 Task 表。 |
| `side_effect_policy` | TEXT/JSONB，按 Phase 1 配置模型重核 | 固定自动重试/人工确认等快照，禁止客户端放大。 |

**B. `runtime_events` 扩展**

| 字段 | 规划类型/约束 | 用途 |
|---|---|---|
| `event_id` | UUID，回填后 NOT NULL + 全局 UNIQUE | 跨重连/Outbox/usage 的稳定去重标识；存量用 Run+seq 确定性回填。 |
| `schema_version` | TEXT，存量回填 `v1` | 显式版本路由与兼容。 |
| `source` | TEXT，存量回填 `platform` | `platform` 或 `engine_native`。 |
| `producer_id` / `producer_event_id` | TEXT NULL | 原生/生产者去重键；非空时与 run_id 建唯一约束。 |
| `engine_session_id` / `trace_id` | UUID/TEXT NULL，按实际模型重核 | 关联 Session 与链路，不改变公共历史事件。 |

保留 `(run_id,seq)` 主键、既有 `type/data/created_at` 和 SSE id=seq；不添加会与历史语义冲突的 NOT NULL payload 改写。

**C. 新表 `runtime_event_outbox`**

| 字段 | 规划类型/约束 | 用途 |
|---|---|---|
| `(run_id, seq)` | 复合 PK/FK 到 `runtime_events` | 一事件一 Outbox，关联事实源。 |
| `event_id` | UUID NOT NULL UNIQUE | 发布与消费去重关联。 |
| `status` | TEXT CHECK：`pending/published` | 发布状态；失败保持 pending 并记录有界错误。 |
| `attempts` / `available_at` | INT / TIMESTAMPTZ | 有界退避与恢复扫描。 |
| `created_at` / `published_at` | TIMESTAMPTZ | lag、恢复与审计指标。 |
| `last_error` | TEXT NULL | 有界脱敏发布诊断，不含 payload/Secret。 |

**D. 新表 `runtime_usage_ledger`**

| 字段 | 规划类型/约束 | 用途 |
|---|---|---|
| `id` | UUID PK | 用量来源记录 ID。 |
| `run_id` / `lease_epoch` | UUID FK / BIGINT | 关联 Run 和写入所有权证据。 |
| `source` / `source_event_id` / `usage_schema_version` | TEXT | 来源唯一键和版本化解析。 |
| `usage` | JSONB NOT NULL | 类型化校验后的 token/调用等用量，不含 Secret。 |
| `cost` / `is_estimate` | NUMERIC NULL / BOOLEAN | 可空成本与估计标记，缺失不填零。 |
| `supersedes_id` | UUID 自引用 NULL | 供应商修正链，不盲目累加。 |
| `created_at` / `updated_at` | TIMESTAMPTZ | 聚合重建与审计。 |

规划 `UNIQUE(run_id, source, source_event_id)`；聚合视图/查询只按当前有效修正链计算，旧 epoch 写入在同事务校验 Run 所有权后拒绝。

设计要点：

- 采用 expand → 批量确定性回填 → validate → 切换读写；大表默认值、索引和 NOT NULL 的在线步骤按 PostgreSQL 版本与实际数据量评审，避免长锁。
- 所有状态+事件+Outbox+必要 usage 在同一事务；Outbox 是至少一次投递+event_id 幂等消费，不宣称网络层 exactly-once。
- 现有事件不回填 Outbox 重发给所有客户端，除非迁移评审明确要求；只建立发布起点，避免历史事件洪峰。
- downgrade 有数据时按仓库惯例显式导出/保护；正常回滚保留新列/表，旧代码不得删除或重编号数据。

### 规划迁移 `0057_execution_credential_security.py`

**A. 新表 `execution_credentials`**

| 字段 | 规划类型/约束 | 用途 |
|---|---|---|
| `id` / `tenant_id` | UUID PK / TEXT + 索引 | 凭据引用与租户边界。 |
| `name` / `credential_type` | TEXT | 管理标识和类型化解析。 |
| `encrypted_secret` / `key_version` | TEXT | 安装密钥/KMS 接口加密，不明文落库。 |
| `version` / `status` | INT / TEXT CHECK：`active/revoked` | 轮换版本和即时吊销。 |
| `allowed_engines` / `allowed_workspaces` | JSONB | 凭据可绑定的最大范围，Broker 仍需逐次授权。 |
| `created_at` / `updated_at` / `rotated_at` / `revoked_at` | TIMESTAMPTZ | 生命周期审计。 |

**B. 新表 `execution_credential_grants`**

| 字段 | 规划类型/约束 | 用途 |
|---|---|---|
| `id` / `grant_hash` | UUID PK / TEXT UNIQUE | grant 标识与不可逆校验，不存可重放 Token 明文。 |
| `credential_id` / `credential_version` | UUID FK / INT | 固定签发时凭据版本。 |
| `run_id` / `tenant_id` | UUID FK / TEXT + 索引 | 仅指定 Execution/租户可使用。 |
| `engine_id` / `protocol_id` / `workspace_id` | TEXT（Workspace 类型重核） | 受众与 Workspace 绑定。 |
| `scopes` | JSONB NOT NULL | 最小权限集合，不允许执行时扩大。 |
| `issued_at` / `expires_at` / `revoked_at` / `last_used_at` | TIMESTAMPTZ | 短期有效、吊销与使用审计。 |

设计要点：

- grant 不跨 Run/Session Resume 复用；Resume 创建新 Run 并重新签发。Secret 挂载/环境只在受控沙箱内短期存在，数据库只存元数据和不可逆校验值。
- 复用现有审计设施的 actor/action/resource/revision 关联，审计记录不得写 `encrypted_secret`、grant Token、环境值或完整挂载内容。
- 删除/降级不得级联抹除审计所需记录；外键删除策略和保留期限在实施评审中按现有 Run 保留规则冻结。

## 核心流程

### 1. Vault/Broker 与沙箱启动（`credentials/` + `sandbox/`）

```text
受信 API/Worker 请求启动
→ Broker 校验 tenant/agent/run、Engine/Protocol、Workspace、credential version/scopes
→ 同事务记录短期 grant 元数据与无 Secret 审计
→ Sandbox Provider 创建非特权、默认拒绝网络、最小挂载和资源受限环境
→ Broker 仅向该 Execution 的受控 Secret 通道物化凭据
→ Host 启动 Engine；日志/事件/诊断出口统一脱敏
→ 到期/取消/完成/吊销后撤销 grant、销毁通道和沙箱
```

- 沙箱/grant 任一不可用即不启动；禁止回退宿主直接执行或长期共享环境。
- 现有 `ToolEgressPolicy` 可复用 host/IP 规范化经验，但不能替代 OS/沙箱网络 enforcement。

### 2. Claim/Takeover 与全写路径 Fencing（`repository.py`、`reliability/fencing.py`）

```text
claim/takeover 事务锁定 Run
→ 验证可认领/可接管状态
→ lease_epoch = lease_epoch + 1，写 owner/lease_until
→ 返回 (run_id, owner, lease_epoch) 给 Worker/Host
→ 每个 append/finish/usage/session/outbox/resource 操作在 DB 条件中校验同一三元组及 lease
→ 不匹配则零行更新、事务回滚、记录 Fencing 拒绝
```

- heartbeat 同样校验三元组；不能先 SELECT 再无约束 UPDATE。资源清理若允许独立 recovery actor，使用单独的受权 recovery ownership，不伪造旧 Worker epoch。
- 旧 epoch 的迟到事件/usage 不进入去重台账或 Outbox；终态与最终事件同事务提交。

### 3. Worker 丢失、取消/超时、清理与重试（`recovery.py`、`cancellation.py`、`retry.py`）

```text
故障/取消/超时
→ 固定 cancel/timeout 意图并阻止新业务写入
→ Recovery 获取新 epoch 或受权清理所有权，旧 Worker 被 fence
→ Host 检查进程树/连接/挂载并执行优雅→强制清理
→ 确认实际退出与资源释放后写唯一终态+最终事件+Outbox
→ 无法确认则 failed/cleanup_failed 或显式待清理恢复状态并告警，不伪报 cancelled
→ 对账释放 Run 活跃配额与 Host 资源预留
```

- 自动重试仅限未启动且无副作用的错误；新 Run 使用 `retry_of_run_id`、新 attempt/epoch 和幂等关联。超时、断连或已发生外部写入时默认人工处理。
- 当前 admission 以 queued/running 计数形成容量约束，可复用“唯一终态释放活跃槽位”先例；Host 资源配额必须另有真实释放确认，二者不可混为一谈。

### 4. 状态、事件、去重、Outbox 与 Usage 事务（`events/`）

```text
接收带 Run/epoch 的原生或平台事件
→ 事务内校验所有权、schema/version、payload 上限
→ 按 (run_id, producer_id, producer_event_id) 查重
→ 重复则返回首次结果；新事件才原子递增 event_seq
→ 插入 runtime_events(event_id, seq, ...) 与 runtime_event_outbox
→ 如含 usage，以来源唯一键写 runtime_usage_ledger
→ 同事务提交状态/事件/Outbox/usage；提交后 NOTIFY 唤醒
→ Dispatcher 读 pending、至少一次发布并以 event_id 幂等标记 published
→ 崩溃后重扫 pending，数据库 Event Store 始终可重放
```

- 重复事件不占新 seq，不重复产生审计副作用或 usage。终态事件与 Run 终态同事务，SSE 只有看到最终事件才结束持久流。
- 发布器故障不改变 Run 的事实终态；监控 Outbox lag，恢复后以数据库为准，不靠 NOTIFY 补数据。

### 5. SSE 重连与保留缺口（`runtime_routes.py`、`events/replay.py`）

```text
鉴权 Run/tenant/scope
→ 解析 after 与 Last-Event-ID，取较大游标并校验
→ 若游标早于保留下界：409 event_replay_gap + 可安全重置信息
→ 从 Event Store 按 seq 分批读取，发送 id=seq、event/type/data（data 含 event_id/schema_version）
→ 订阅 live 唤醒并再次读库消除订阅/查询竞态
→ 客户端按 event_id 去重；瞬时 model.delta 无持久游标，不影响最终答案
→ Run 终态且 cursor >= event_seq 后结束
```

- 保留期外不承诺完整重放，绝不静默从“最早可用”开始冒充无缺口。保留清理不得删除未满足审计/账务要求的数据。

### 6. Usage 纠正与 Parser Diagnostics（`usage.py`、`diagnostics.py`）

- usage 以 `(run_id, source, source_event_id)` 幂等写入；重复返回原记录，供应商修正用 `supersedes_id` 建链，聚合从台账可重建，旧 epoch 一律拒绝。
- parser 错误按 malformed/unknown_schema/unknown_type/size_limit/critical_terminal 分类，关联 Run/Protocol/Adapter 版本；诊断只含有界脱敏样本并率限。
- 可跳过事件与关键终态不可解析采用不同策略；诊断写入失败不能递归生成诊断事件，安全泄露走独立告警与凭据吊销流程。

## 配置

规划在 `platform_settings/settings.py` 增加不可信总开关（默认 false）、沙箱必需/网络默认拒绝（默认 true）、grant TTL 硬上限、清理/重试/退避、事件保留、Outbox 批大小/间隔、usage 聚合和 parser 样本/率限参数。

- `execution_sandbox_required` 与默认拒绝策略不是可用性开关；旧路径兼容仅适用于既有可信 React/受控执行，不允许不可信任务绕过。
- `execution_outbox_enabled` 只控制灰度发布器，不能关闭 Event Store 持久化、Fencing、脱敏或安全审计；回滚时需重扫/协调新旧写入。
- Secret、主密钥、grant Token 只通过部署 Secret 文件/环境或受控挂载提供，`.env.example` 仅含占位。

## 模型调用路径

本阶段不改变 React/Codex 的模型选择或推理路径。现有 Model Gateway 凭据仍由其 Catalog/Vault 管理，Engine Execution 凭据由新 Broker 管理，二者不可隐式互换。所有模型/Engine usage 统一经 Adapter → ExecutionResult/原生 usage → `runtime_usage_ledger` → 幂等聚合；缺失为 unknown，成本估计明确标记，不从事件重复累计。

## 测试方案

| 层 | 用例 |
|---|---|
| 单测 | grant scope/TTL、脱敏、网络/IP/路径、Fencing 条件、重试矩阵、schema/dedup/usage/parser。 |
| 集成 | 多 Worker 接管、故障点事务、Outbox 重扫、SSE 多页重连、迁移回填、真实 Vault/Broker。 |
| 对抗/故障演练 | 沙箱逃逸、DNS/元数据/symlink/Secret canary、SIGKILL/断网/磁盘满/进程 hang/Worker 崩溃。 |
| 回归 | React/Codex/Run/API/SSE、历史数据、既有凭据与 Workspace；未测 Phase 0 基线标阻断。 |

详细用例与出口准则见 `04-test-plan.md`。

## 上线与回滚

1. 先完成 Phase 0 基线和 Phase 1~5 验收，冻结攻击矩阵、故障点清单、事件保留与 RTO/RPO（基线后评审）。
2. 实施前重核 head；按实际依赖落地规划 0056，再 0057。使用 expand/backfill/validate/switch，执行存量副本升级、回填校验、锁/耗时与降级数据保护演练。
3. 部署顺序：只读新 schema 兼容代码 → Fencing/事务写入 → Outbox 重扫/发布 → usage 幂等 → SSE 新字段/缺口 → Vault/Broker → 沙箱/网络/文件；每一步默认不开放不可信租户。
4. 灰度先 trusted test tenant，再独立安全/SRE 对抗签字；所有硬门禁完成后才允许 `execution_untrusted_tenants_enabled=true`，并可按租户小批量开放。
5. 回滚关闭不可信新执行、吊销活动 grant、隔离并清理活动沙箱；保留新表/列/事件/usage/凭据记录。旧二进制兼容性和 Outbox 协调必须演练，禁止用 down migration 删数据作为常规回滚。
6. 任一 P0 泄露/逃逸/越权、Fencing 失效或终态/账务不一致立即关闭新执行并告警；安全校验不得通过功能开关降级。
