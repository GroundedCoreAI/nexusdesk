# Phase 4 · Runtime Host、进程监管与 Workspace — 业务目标

> 状态：待评审（未开始实施）
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 3、7～10、15～17 节 Phase 4、19、20、22 节；Phase 0–3 规划文档
> 预估工期：~3–4 周（Phase 0 基线与支持矩阵核验后重估）
> 依赖：Phase 0–3 已验收；Linux/POSIX 与 PostgreSQL 测试环境；资源控制专项环境可用性已确认

## 要解决的问题

### 问题 1：外部 Engine 缺少与 Adapter 解耦的进程生命周期边界

当前 `core_platform/agent_runtime/worker.py` 只管理 asyncio 任务，`runtime_factory.py` 固定构造进程内 ReAct Runtime，没有 Runtime Host、Process Runner 或 Supervisor。若各 Adapter 自行创建子进程，取消、信号、进程组、输出上限和资源释放会随 Engine 分叉。

### 问题 2：协程取消不能证明实际进程及其后代已停止

现有 Worker 的取消与失租路径会取消 Runtime 协程，但没有 OS 进程树可清理。外部 Engine 一旦派生子进程，仅取消等待协程会留下孤儿；Worker 崩溃或容器重启后，没有持久记录可安全识别并回收旧进程，也不能贸然按 PID 杀进程。

### 问题 3：单次执行没有受控且可恢复的 Workdir

架构区分长期 Workspace 与 Execution Workdir，但当前没有 `agent_execution/workspace` 实现或执行目录持久记录。若允许客户端给宿主路径，或仅用字符串 `resolve()` 做检查，会产生路径穿越、软链/硬链逃逸、跨租户覆盖及清理误删风险。

### 问题 4：资源限制、Sandbox 边界与宿主健康缺少统一契约

现有 settings 有 Run 超时、并发和业务存储上限，但没有外部进程的 CPU、内存、PID、Workdir 磁盘及输出限制，也没有 Sandbox Provider 或 Runtime Host 健康指标。不同 OS/容器能力不一致，若静默忽略不支持的限额会制造虚假安全承诺。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：建立 Engine 无关的 Runtime Host | Adapter 只处理 Engine/Protocol，Host 统一管理进程、Workdir、Sandbox 和资源；Worker 不承担进程系统调用 |
| G2：保证可验证的进程终态与恢复 | 正常退出、取消、超时、崩溃和 Worker 重启均能清理进程组/子进程；孤儿回收必须校验身份，避免 PID 复用误杀 |
| G3：提供单次执行隔离 Workdir | 每次 Execution 获得平台生成的独立目录与持久生命周期记录，阻断路径穿越、链接逃逸、跨租户访问和越界清理 |
| G4：建立可配置资源边界与 Sandbox 接口 | CPU、内存、PID、磁盘、wall time 和输出有明确限额及支持矩阵；不支持时失败关闭，强沙箱留待 Phase 6 |
| G5：可观测、可回滚且不影响 React | 提供宿主/进程/Workdir 健康与清理观测；新 Host 默认关闭，回滚不遗弃活跃进程或删除审计记录 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| 外部测试进程及后代清理率 | 待 Phase 0 盘点现有取消/重启覆盖；当前无外部进程基线 | 正常、取消、超时、崩溃、重启五类规定场景清理率 100%，无托管后代遗留 |
| 取消/超时到实际进程组停止的时延 | 待 Phase 0 测量现有取消时延；OS 进程场景无基线 | 在配置 grace + kill timeout 后再加 2s 观测余量内完成；未能停止必须告警且不得报告清理成功 |
| 孤儿识别安全性 | 待 Phase 0 盘点 Worker 恢复语义 | 可回收孤儿识别率 100%；PID 复用/身份不匹配误杀数为 0；无法确认的进程进入人工处置状态 |
| Workdir 隔离与恶意路径阻断率 | 待 Phase 0 盘点文件路径安全覆盖 | 合法 Execution 目录唯一率 100%；规定穿越、绝对路径、软链/硬链及竞态用例逃逸成功数为 0 |
| 资源限额有效执行率 | 待 Phase 0 盘点部署资源控制能力 | 支持矩阵内 CPU/内存/PID/磁盘/时间/输出超限均被终止或拒绝；不支持且被要求的能力静默忽略数为 0 |
| Host 健康与回滚可观测覆盖率 | 待 Phase 0 盘点 Worker 健康/指标 | 活跃进程、孤儿、清理失败、Workdir 用量/滞留与恢复批次 100% 有结构化观测；回滚后活跃孤儿数为 0 |

## 范围

**包含**：

- Runtime Host、Process Runner、Process Supervisor、持久 Process Registry 与 Adapter 解耦契约。
- 进程组/子进程清理、stdin/stdout/stderr 有界处理、取消、超时、崩溃与重启恢复。
- Workspace Provider、Execution Workdir、挂载/保留/清理策略及安全路径操作。
- 规划迁移 `0054_execution_runtime_host`：为跨重启回收确有必要，新增进程与 Workdir 两类持久记录，不建通用 RuntimeHost 服务表。
- 可配置资源限制、Local Sandbox Provider 与可替换 Sandbox 接口、明确支持矩阵及失败关闭。
- 宿主健康、进程/Workdir 指标、部署卷、故障/恶意/资源边界测试和回滚。

**不包含**（属于后续阶段 / 明确不做）：

- Codex 或其他真实外部 Engine Adapter、协议解析与 Session Resume（Phase 5）。
- 完整强沙箱、容器/VM 隔离、网络出口、不可信凭据代理、Secret 全链路治理（Phase 6）。
- **不开放不可信多租户代码执行**，不提供任意命令/任意宿主路径 API，不将本地 rlimit/cgroup 控制宣传为安全沙箱。
- 跨宿主共享执行卷、多副本抢占同一进程、自动恢复有副作用的外部 Engine 会话。
- 长期 Workspace 快照、共享 Skill Store、Artifact 对象存储、全局租户公平调度（后续按需求评审）。

## 风险与约束

- **本地隔离不等于强沙箱**：同 UID、同内核的进程仍可能越权；Phase 4 只运行平台内置的受信任测试进程，外部不可信执行保持关闭。
- **PID/PGID 复用**：重启后仅按 PID 发信号可能误杀；必须校验宿主、进程启动标识、组与命令摘要，不匹配则禁止发信号并告警。
- **路径竞态**：检查后再打开可能被软链替换；必须使用基于目录句柄、逐组件 no-follow 的安全操作，清理不得跟随链接。
- **资源能力差异**：rlimit、cgroup、文件系统配额在 OS/容器上支持不同；按 Execution 必须满足的限额逐项探测，不满足则拒绝启动。
- **清理一致性**：Run 终态、进程退出与 Workdir 删除可能不同时完成；分别持久化状态并记录 `cleanup_failed`，禁止以 Run 终态冒充资源已释放。
- **共享卷风险**：Phase 4 一个执行根目录只归属一个稳定 host_id；不支持多个 Host 同时管理同一根目录。
- **兼容性**：React 进程内路径不变，新 Host 默认关闭；`0054` 是规划号，实施前须重验真实 head/down_revision，禁止修改 `0053` 规划实现或任何历史迁移。
