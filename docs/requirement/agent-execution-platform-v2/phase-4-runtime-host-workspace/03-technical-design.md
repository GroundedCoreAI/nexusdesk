# Phase 4 · Runtime Host、进程监管与 Workspace — 技术落地文档

> 状态：待评审（未开始实施；以下模块、表与部署变更均为规划）
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1–G5）、`02-requirements.md`（FR-1–FR-10、AC-1–AC-12）、架构文档第 3、7～10、15～17、19～22 节
> 现状核查：2026-11-02 对 `integration` 工作树；Phase 3 规划前驱为 `0053_agent_execution_metadata`

## 1. 现状映射与设计裁定

| 现状证据 | 核查结论 | 本阶段裁定 |
|---|---|---|
| `core_platform/agent_runtime/worker.py` | 管理 asyncio 任务、Lease/Heartbeat、取消与 Run 终态，没有 OS 进程概念 | 保留 Worker/Repository 职责；Orchestrator 调 Host，Supervisor 独立管理进程事实与清理 |
| `core_platform/agent_runtime/repository.py` | `finish` 有 owner/lease/终态保护，失租 reaper 只更新 Run | 复用终态保护，新增进程记录不替代 Run；Run 终态不能作为 OS 资源已释放的证明 |
| `applications/platform_runtime/runtime_factory.py` | 仅构造进程内 ReAct Runtime | React 路径不变；外部测试进程经 Phase 1–3 Adapter/Orchestrator 与 Host 契约接入 |
| `platform_settings/settings.py` | 有 Run 超时、队列/并发和业务存储限制，没有外部进程资源策略 | 沿用 `AGENT_` Settings，新增 Host/Workdir/Resource 配置，默认关闭且要求失败关闭 |
| `tool_gateway/workspace.py`、知识/模型存储 | 已有相对路径校验、大小限制与租户查询先例，但没有可抗链接竞态的执行目录实现 | 复用租户/大小治理思路，不复用字符串拼接做执行文件安全；采用目录句柄与 no-follow |
| `deploy/quickstart/compose.yaml` | app 已有 `/data` 持久卷与 45s stop grace | Workdir 放 `/data/execution`，默认 TERM/KILL 时间小于 stop grace，不新增共享宿主路径 |
| `deploy/production/compose.yaml` | 独立 runtime-worker，当前只挂 credentials 卷 | 仅 runtime-worker 增加专用 execution 卷与稳定 host_id；API/其他 Worker 不挂执行卷 |
| Phase 1–3 规划 | Adapter、ExecutionRequest、Orchestrator、能力/策略/Workdir 需求是前置 | Host 只接受服务端已解析请求；若 Effective 不要求外部进程则不启动，未知能力/路径失败关闭 |

## 2. 改动总览

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移 | `backend/migrations/versions/0054_execution_runtime_host.py` | 规划新增 `execution_workdirs` 与 `runtime_host_processes` 两表及必要索引；实施前重验前驱 |
| Host 模型 | `backend/src/agent_platform/core_platform/agent_execution/host/host_models.py` | ProcessSpec、ResourcePolicy、ManagedProcess、ProcessResult、HostHealth 内部模型 |
| Host 接口 | `backend/src/agent_platform/core_platform/agent_execution/host/runtime_host.py` | start/cancel/wait/reconcile/health/close 契约与组合入口 |
| Runner | `backend/src/agent_platform/core_platform/agent_execution/host/process_runner.py` | 可信目标启动、新进程组、有界 I/O、启动身份采集 |
| Supervisor | `backend/src/agent_platform/core_platform/agent_execution/host/process_supervisor.py` | TERM/KILL、超时、退出收集、幂等清理与资源释放 |
| Registry | `backend/src/agent_platform/core_platform/agent_execution/host/process_registry.py` | 进程记录、锁、孤儿核对、重启恢复与人工处置 |
| 资源 | `backend/src/agent_platform/core_platform/agent_execution/host/resource_manager.py` | 支持探测、每 Execution 限额、采样与释放 |
| Workspace 接口 | `backend/src/agent_platform/core_platform/agent_execution/workspace/workspace_provider.py` | Workdir 准备/激活/保留/清理契约 |
| Workspace 管理 | `backend/src/agent_platform/core_platform/agent_execution/workspace/workspace_manager.py` | 持久记录、保留扫描、重启恢复与清理重试 |
| Workdir | `backend/src/agent_platform/core_platform/agent_execution/workspace/execution_workdir.py` | 唯一布局、权限、磁盘统计与安全目录句柄 |
| 路径策略 | `backend/src/agent_platform/core_platform/agent_execution/workspace/workspace_policy.py` | 相对路径/挂载白名单、no-follow、链接/竞态和清理边界 |
| Sandbox | `backend/src/agent_platform/core_platform/agent_execution/host/sandbox_provider.py`、`local_sandbox_provider.py` | 可替换接口、Local Provider、能力矩阵与不可信执行门槛 |
| 编排 | `backend/src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py` | Workdir→Sandbox/资源→Host.start→事件→清理的顺序与异常屏障 |
| 组合 | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | 组装 Host/Supervisor/Workspace/Resource/Sandbox，管理启动与停止 |
| 配置 | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | FR-10 配置、边界与启用时交叉校验 |
| 部署 | `deploy/quickstart/compose.yaml`、`deploy/production/compose.yaml`、`deploy/production/.env.example` | 执行卷、稳定 host_id、非秘密限额与停止策略 |
| 测试 | `backend/tests/test_runtime_host.py`、`test_process_supervisor.py`、`test_execution_workdir.py`、`test_runtime_host_postgres.py`、`test_execution_runtime_host_migrations.py` | 规划真实进程、故障、恶意路径、资源与迁移测试；辅助程序仅测试内置可信目标 |

## 3. 数据模型

### 3.1 为什么需要持久记录

Worker 重启后内存中的 asyncio Task、PID 和目录句柄全部消失。若没有持久记录，就无法区分已完成、待清理和身份待核实的进程，也无法安全恢复滞留 Workdir。因此本阶段确有必要持久化**进程**与**Workdir**两类执行事实。

不建立通用 RuntimeHost 服务表：稳定 `host_id` 来自部署，boot 级 `host_instance_id` 由进程生成，Host 健康可由进程记录的观测时间与结构化健康状态推导。除非后续出现多 Host 调度需求，不提前增加控制面实体。

### 3.2 迁移 `0054_execution_runtime_host.py`

> 规划编号：以 Phase 3 的 `0053_agent_execution_metadata` 为规划前驱。实施前必须重验真实 head/down_revision；若中间已有迁移，使用新链接并修订文档，禁止修改历史迁移。

#### 表 `execution_workdirs`

| 字段 | 类型/约束 | 用途 |
|---|---|---|
| `id` | UUID PK | 平台 Workdir ID |
| `run_id` | UUID NOT NULL UNIQUE REFERENCES `runtime_runs` ON DELETE CASCADE | 每 Run 一个执行目录 |
| `tenant_id/business_id/workspace_id` | TEXT NOT NULL | 可信租户与逻辑 scope，清理前复核 |
| `relative_path` | TEXT NOT NULL UNIQUE | 相对配置执行根的平台生成路径，不接受客户端值 |
| `status` | TEXT NOT NULL CHECK | `preparing/ready/active/retained/cleaning/deleted/cleanup_failed` |
| `quota_bytes/size_bytes` | BIGINT NOT NULL | 配置总量上限与最近观测用量，size 默认 0 |
| `file_count` | INTEGER NOT NULL DEFAULT 0 | 观测文件数与清理诊断 |
| `expires_at` | TIMESTAMPTZ NULL | 保留到期时间 |
| `last_error_code` | TEXT NULL | 稳定清理/准备错误，不含原始路径或异常秘密 |
| `created_at/updated_at/cleaned_at` | TIMESTAMPTZ | 生命周期与幂等清理 |

索引：`(status,expires_at)`、`(tenant_id,status)`。物理目录删除后保留 Tombstone 记录；不跟随 `relative_path` 之外的链接或改由请求指定新路径。

#### 表 `runtime_host_processes`

| 字段 | 类型/约束 | 用途 |
|---|---|---|
| `id` | UUID PK | 平台受管进程 ID |
| `run_id` | UUID NOT NULL UNIQUE REFERENCES `runtime_runs` ON DELETE CASCADE | 每 Run 初版一个主进程组 |
| `workdir_id` | UUID NULL REFERENCES `execution_workdirs` ON DELETE SET NULL | 关联目录；目录记录 Tombstone 不影响进程审计 |
| `tenant_id` | TEXT NOT NULL | 租户隔离与运维查询 |
| `host_id` | TEXT NOT NULL | 稳定部署身份，限定重启扫描范围 |
| `host_instance_id` | TEXT NOT NULL | 当前 boot 所有者，区分新旧 Host 实例 |
| `sandbox_provider` | TEXT NOT NULL | Provider id/version 的内部标识 |
| `status` | TEXT NOT NULL CHECK | `starting/running/terminating/exited/orphaned/cleanup_failed` |
| `pid/process_group_id` | INTEGER NULL | 内部 OS 标识，不公开、不设全局 UNIQUE（会复用） |
| `process_start_token` | TEXT NULL | OS 启动时间/等价 opaque 身份，防 PID 复用误杀 |
| `command_digest` | TEXT NOT NULL | 可信可执行目标与规范 argv 的摘要，不保存秘密 argv |
| `cancel_requested_at/cleanup_deadline_at` | TIMESTAMPTZ NULL | 取消与升级清理期限 |
| `exit_code` | INTEGER NULL | 实际退出码/约定信号值 |
| `last_observed_at` | TIMESTAMPTZ NOT NULL | reconcile/健康观测时间 |
| `last_error_code` | TEXT NULL | 稳定启动/清理/恢复错误 |
| `metadata` | JSONB NOT NULL DEFAULT `{}` | 有界非秘密资源/退出元数据，禁止环境变量与完整路径 |
| `created_at/updated_at/started_at/exited_at` | TIMESTAMPTZ | 生命周期与恢复判断 |

索引：`(host_id,status)`、`(status,last_observed_at)`、`(tenant_id,status)`。两表只包含恢复/清理所需字段，不复制 AgentConfig、能力快照或新增 RuntimeHost 服务记录；`runtime_runs` 不再加列。

## 4. 核心契约与流程

### 4.1 RuntimeHost 与 Adapter 边界

| 操作 | Host 职责 | Adapter/ Orchestrator 职责 |
|---|---|---|
| `start` | 校验可信 ProcessSpec、准备 Sandbox/资源、启动进程组并登记 | Adapter 提供协议所需可信目标；Orchestrator 提供 Run/tenant/Effective/Workdir 上下文 |
| `wait/observe` | 收集退出、输出背压、资源用量与实际状态 | Adapter 解析协议输出；Orchestrator 持久化平台事件 |
| `cancel` | 记录原因、TERM→KILL 整组、等待并释放资源 | Adapter 发起协议取消（如支持）；Orchestrator/Repository 决定 Run 终态 |
| `reconcile` | 核对持久记录与 OS 事实、回收孤儿、重试清理 | 不恢复 Engine 会话、不重新执行有副作用请求 |
| `health/close` | 报告支持矩阵/活跃/失败；停止接纳并排空 | 组合根管理生命周期；Worker 不直接调用 OS |

公共 ExecutionHandle 不包含 PID/PGID、启动 token、完整路径或环境。测试必须用至少两个 Adapter 验证 Host 无 Engine 条件分支。

### 4.2 正常启动与退出

```
Orchestrator 校验 Phase 3 Effective 与可信目标
→ Workdir preparing/ready（持久化）→ Sandbox/资源支持检查
→ Process starting 记录 → 新进程组启动并采集 PID/PGID/start token/command digest
→ running + Workdir active → 有界 I/O / 协议事件
→ wait 收集 exit → exited + 资源释放 → Run 结果提交 → Workdir retained/cleaning
```

- 任一步失败按逆序清理；Process 已启动但记录失败时，以同一受管句柄终止整组，不能因 DB 异常留下无主进程。
- Run 完成/失败/取消与 Workdir retained/deleted 分开提交；`cleanup_failed` 必须可见并可重试。
- stdout/stderr 分流有界，达到上限即停止读取并终止进程组；不将完整输出或环境写日志。

### 4.3 取消、超时与停止

```
cancel/timeout/resource_exceeded/worker_stop
→ 条件更新 cancel_requested_at/status=terminating
→ TERM 进程组 → 等待 grace
→ 仍存活则 KILL 进程组 → 等待 kill timeout
→ 核对退出与后代 → exited 或 cleanup_failed
→ 幂等释放 Sandbox/资源 → Repository 按既有规则提交终态
```

- 用户取消优先于迟到成功；既有 owner/lease/TERMINAL 保护不被 Host 绕过。
- Run deadline 与 process wall deadline 取较早者；取消和超时竞态只执行一个清理状态机，重复调用返回同一进展。
- cleanup_failed 不等于 exited；指标与告警持续，人工处理后才可关闭记录。
- 应用停止先停止新接纳；默认 5s+5s 小于现有 45s stop grace，若调大配置必须同步调整部署停止期限。

### 4.4 孤儿回收与重启恢复

```
新 Host 启动（即使禁止新接纳也先执行恢复）
→ 只查询同 host_id 且 starting/running/terminating/orphaned/cleanup_failed 的小批次记录
→ SELECT ... FOR UPDATE SKIP LOCKED / 条件状态更新
→ 核对执行根、host 命名空间、PID/PGID、start token、command digest
→ 匹配：标 orphaned 并 TERM/KILL；不匹配：禁止信号，cleanup_failed + 人工告警
→ 核对 Workdir 归属并清理/保留 → 记录恢复审计与指标
```

- 恢复只“终止与清理”，不接管 stdin/stdout、不恢复协议 Session、不自动重放 Run。
- PID 存在但 start token 或 command digest 不同视为 PID 复用，误杀必须为零；无法获得身份也按不匹配处理。
- DB 不可用只重试连接，不扫描全宿主进程，不根据命令名模糊 kill。
- 一个执行根只允许一个稳定 host_id；多副本部署需先停止旧 Host 并完成回收，不支持并发共享。

### 4.5 Workdir 与安全文件操作

逻辑布局为 `<execution_root>/<tenant-digest>/<run-id>/{workdir,temp,logs}`；tenant-digest 和 run-id 由服务端生成，不信任显示名称。目录默认 0700、文件默认 0600，执行根启动时校验所有者、类型和权限，禁止根自身为软链。

所有路径操作遵循：

1. 仅接受规范化相对路径；拒绝绝对路径、空字节、`.`/`..`、反斜杠、重复/编码分隔符绕过和超长路径。
2. 从已验证的执行根/Workdir 目录句柄逐组件打开，使用 no-follow 与创建时排他语义；不以“先 realpath 检查、再按字符串打开”作为安全边界。
3. 每次挂载/导出/清理重新核对 DB tenant/scope/run/status；挂载源仅平台白名单，默认不开放任何宿主源。
4. 软链默认拒绝；硬链和挂载点无法证明归属时拒绝。递归清理基于目录句柄且不跟随链接，发现竞态即停止。
5. 清理只针对记录的 run 专属目录；根目录、tenant 父目录和其他 run 目录绝不由单次 Execution 清理递归删除。

### 4.6 资源管理与 Sandbox 支持矩阵

| 能力 | 完整验收首选 | 开发降级 | 失败关闭与边界 |
|---|---|---|---|
| CPU 时间 | 每 Execution 受管资源组统计+监督终止，辅以 CPU rlimit | 每进程 rlimit 仅作近似，不宣称整组硬上限 | 要求整组限额而无法提供时拒绝 |
| 内存 | cgroup v2 memory.max/等价每 Execution 限制 | 地址空间 rlimit 只限单进程，标为非等价 | 不支持必需限制则拒绝，OOM 记资源错误 |
| PID | cgroup v2 pids.max/等价每 Execution 限制 | Supervisor 后代计数是反应式监测，不是硬隔离 | 不用同 UID 的宿主机总 NPROC 冒充每 Execution 限额 |
| 磁盘 | 文件系统/项目配额（若可用）+ Workdir 总量监督 | 单文件 rlimit + 周期总量监测，存在采样窗口 | 超量终止/拒绝并清理；监测不宣称防逃逸 |
| Wall time | Supervisor monotonic deadline | 同一实现 | 与 Run deadline 取早者，超时清理整组 |
| 输出 | Runner 每流硬字节上限与背压 | 同一实现 | 超限终止，避免内存/日志洪泛 |

Local Sandbox Provider 只封装上述受管进程与资源操作，不提供 mount/user/network namespace、系统调用过滤、网络出口、凭据隔离或不可信代码安全保证。完整强沙箱与不可信多租户执行门槛属于 Phase 6；本阶段没有相应公共入口，测试目标由仓库固定且不接受用户代码。

## 5. 配置与部署

### 5.1 Settings 交叉校验

FR-10 数值均使用有界 Pydantic Field；启用时额外要求：

- `execution_runtime_host_id` 非空且执行根未分配给另一 Host；`execution_workdir_root` 为平台所有、非软链的受信路径。
- grace、kill、reconcile、sample、cleanup interval 均大于 0且有上限；wall timeout、CPU/memory/PID/disk/output 限额不得为 0 或负数。
- `execution_resource_enforcement_required=true` 时启动前计算支持矩阵，缺少任一请求所需能力则不接纳新进程。
- `execution_runtime_host_enabled=false` 不阻止已有记录恢复/清理；只有零活跃后才允许完全停止 Supervisor。

### 5.2 部署先例与变更

| 环境 | 规划变更 | 约束 |
|---|---|---|
| quickstart | 复用 `app_data:/data`，执行根 `/data/execution`；设置非秘密 Host/限额，默认 Host 关闭 | 仅为受控演示/测试，不开放不可信执行；stop grace 覆盖清理 |
| production runtime-worker | 新增专用 `execution_data:/data/execution` 与稳定 `AGENT_EXECUTION_RUNTIME_HOST_ID` | API、channel/knowledge/memory worker 不挂卷；单 Host/单执行根 |
| production `.env.example` | 增加 FR-10 非秘密占位与支持矩阵说明 | 不放 Token、凭据、任意命令或用户宿主路径 |
| 多副本 | 本阶段不支持共享执行根 | 扩容前需新设计持久锁/远程 Host/独立卷，不能直接加 replica |

## 6. 模型调用路径

Phase 4 不新增模型调用或凭据路径。React 继续进程内 Model Gateway；外部测试进程不使用真实模型密钥。未来 Engine 的模型/CLI 凭据必须由 Phase 5/6 的受控接口注入，不能放入 ProcessSpec 持久 metadata、Workdir、日志或公共事件。

## 7. 测试方案

| 层 | 用例 |
|---|---|
| 单测 | Host 契约、状态机、取消/超时竞态、记录恢复决策、路径规范化、链接策略、支持矩阵和配置边界 |
| 真实进程集成 | 正常/多层子进程、TERM 忽略、输出洪泛、崩溃、Worker/容器重启、PID 复用和重复清理 |
| Workdir 对抗 | 穿越、编码绕过、跨租户、软链/硬链/挂载点、检查使用竞态与安全删除 |
| 资源边界 | CPU/内存/PID/磁盘/时间/输出在支持矩阵内超限；不支持环境拒绝启动 |
| PostgreSQL/迁移 | 两表约束/索引、锁与幂等、旧 React、默认关闭、应用回滚和 disposable downgrade |
| 回归 | Phase 0 React/Worker/Repository/SSE、Phase 3 能力/配置/快照，以及 quickstart/production 部署检查 |

详细用例见 `04-test-plan.md`；资源专项环境不可用时标 `pending_env`，不得把开发近似能力写成完整支持。

## 8. 上线与回滚

1. **入口**：Phase 0–3 验收；重验真实迁移前驱；Linux 完整支持矩阵、资源专项环境和安全评审通过。
2. **迁移**：两表及索引在线新增，无历史重写；从存量副本验证锁、约束和现有 Run 读写。生产回滚不 downgrade。
3. **默认关闭部署**：先加卷/host_id/settings，Host 不接纳新进程；已有记录恢复器仍可运行。React 基线必须零 diff。
4. **受控灰度**：仅测试 tenant 与内置可信进程，逐项启用取消/超时/重启/Workdir/资源测试，观察清理失败与磁盘。
5. **开放边界**：Phase 4 完成也不开放不可信多租户代码执行；真实 Codex 仍待 Phase 5，强沙箱/网络/凭据门槛待 Phase 6。
6. **正常回滚**：停止新接纳→取消/排空所有活跃进程→核对进程组、资源和 Workdir 状态→关闭 Host/Supervisor→回滚应用。保留两表和 Tombstone。
7. **紧急回滚**：立即关闭新接纳但保持恢复/清理服务；不得直接杀 Worker 后回滚到不理解进程记录的旧代码。存在 cleanup_failed 时阻断完整回滚并人工处置。
8. **数据回滚**：disposable 环境验证 downgrade 先删 `runtime_host_processes` 再删 `execution_workdirs`；生产删表必须另行评审且仅在零活跃后。
