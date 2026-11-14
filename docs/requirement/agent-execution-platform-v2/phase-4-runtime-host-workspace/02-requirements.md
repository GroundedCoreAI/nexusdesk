# Phase 4 · Runtime Host、进程监管与 Workspace — 需求文档

> 状态：待评审（未开始实施）
> 创建：2026-11-02
> 修订：2026-11-14（08 R-1：复核真实 head 为 `0058_agent_execution_metadata` 后，AC-12 的规划迁移由 `0054` 改号 `0059_execution_runtime_host`）
> 依据：`01-business-goals.md`（G1–G5）、架构文档第 3、7～10、17 节 Phase 4、20、22 节

## 用户故事

**US-1（Engine Adapter 研发）**：作为 Adapter 研发，我希望通过统一 Host 启动和取消受管进程，以便只实现 Engine/Protocol 而不重复处理信号、进程组和资源释放。

**US-2（执行平台研发）**：作为执行平台研发，我希望 Run 生命周期与 OS 进程生命周期可关联但职责分离，以便迟到结果、失租和取消不会破坏终态。

**US-3（运维人员）**：作为运维人员，我希望 Worker 重启后能发现、核实并回收孤儿进程和滞留目录，以便资源不会无限泄漏且不会误杀新进程。

**US-4（安全工程师）**：作为安全工程师，我希望所有 Workdir 操作都限制在平台分配的目录内并抵御链接/竞态攻击，以便跨租户文件与宿主文件不可达。

**US-5（QA）**：作为 QA，我希望可控地注入取消、崩溃、超限与恶意路径，以便验证真实进程和资源边界而非只验证协程状态。

**US-6（安全/平台负责人）**：作为安全或平台负责人，我希望 Sandbox 可替换且本阶段明确禁止不可信多租户执行，以便不把局部资源控制误认为完整隔离。

**US-7（SRE）**：作为 SRE，我希望看到 Host 健康、活跃进程、清理失败和 Workdir 用量，以便在资源耗尽前告警并安全回滚。

## 功能需求

### FR-1 Runtime Host 与 Adapter 解耦

| 项 | 说明 |
|---|---|
| 触发时机 | 支持外部进程的 Adapter 准备 start/cancel/wait/reconcile 时 |
| 输入 | 服务端构造的 ProcessSpec、Execution/Run ID、tenant/scope、Workdir、ResourcePolicy 和 SandboxProvider |
| 输出 | ManagedProcess 内部句柄、进程状态与结构化结果；公共 API 不返回 PID/PGID/宿主路径 |
| 执行方式 | Adapter 只调用 Host 契约并处理协议；Host 不解析 Engine 事件或提交 Run 终态，Worker 不直接执行进程系统调用 |
| 失败处理 | 未注册可执行目标、非可信命令或不支持平台在 spawn 前拒绝；不得由 Adapter 绕过 Host 自行 spawn |
| 溯源 | G1；US-1、US-2 |

### FR-2 Process Runner 与有界 I/O

| 项 | 说明 |
|---|---|
| 触发时机 | Host 接受可信 ProcessSpec 后启动、读取输出和等待退出 |
| 输入 | 固定可执行目标、argv 白名单、最小环境、独立 Workdir、输出上限与资源策略 |
| 输出 | 新进程组/会话、stdout/stderr 有界流、exit code/signal 与启动身份；敏感环境不入库/日志 |
| 执行方式 | 异步非阻塞读取；每个流独立限制字节数与背压，平台记录内部 PID/PGID/启动标识供 Supervisor 使用 |
| 失败处理 | spawn、管道、读取或启动身份获取失败时清理已创建资源并失败关闭；输出超限终止进程组并返回稳定错误码 |
| 溯源 | G1、G2；US-1、US-5 |

### FR-3 取消、超时与进程组清理

| 项 | 说明 |
|---|---|
| 触发时机 | 用户取消、Run/进程 wall timeout、Worker 停止、Adapter 异常或资源超限 |
| 输入 | ManagedProcess、取消原因、终止宽限期、强制杀死期限和 Run 当前状态 |
| 输出 | TERM→宽限→KILL 进程组的实际退出状态、清理结果与 `cancelled`/`run_timeout`/资源错误 |
| 执行方式 | 向整个进程组发信号并等待所有可观察后代释放；协程取消同时触发 Host 清理，不能仅取消 await |
| 失败处理 | TERM 忽略后必须升级 KILL；仍无法退出或身份不明时标 `cleanup_failed`/人工处置并告警，不得宣称已清理；迟到成功不得覆盖取消终态 |
| 溯源 | G2；US-2、US-5 |

### FR-4 持久 Process Registry、孤儿与重启恢复

| 项 | 说明 |
|---|---|
| 触发时机 | spawn/状态变化时写记录；Host 启动、定期 reconcile、Worker 崩溃/容器重启后 |
| 输入 | run_id、稳定 host_id、boot 级 host_instance_id、PID/PGID、进程启动标识、命令摘要、Workdir 与状态时间戳 |
| 输出 | 可锁定的进程记录、孤儿判定、TERM/KILL 回收、cleanup_failed 与恢复审计 |
| 执行方式 | 启动时仅扫描同一 host_id/执行根的未结束记录；核对宿主命名空间、启动标识、组与命令摘要后回收，不恢复 Engine 会话 |
| 失败处理 | PID 复用或任何身份不匹配禁止发信号并标人工处置；Run 已终态但进程存活仍清理；DB 不可用不得转为盲目扫描/kill 全宿主 |
| 溯源 | G2、G5；US-3、US-5、US-7 |

### FR-5 Workspace Provider 与 Execution Workdir 生命周期

| 项 | 说明 |
|---|---|
| 触发时机 | Adapter 启动前准备；运行中激活；完成/失败/取消后保留或清理；Host 重启时恢复记录 |
| 输入 | 可信 tenant/business/workspace/run ID、平台执行根、保留策略和磁盘配额 |
| 输出 | 每次 Execution 唯一 Workdir（workdir/temp/logs）、0700 目录及持久状态 `preparing→ready→active→retained/cleaning→deleted` |
| 执行方式 | 目录名由平台从安全 ID/摘要生成，客户端不可给宿主路径；逻辑 Workspace 与 Execution Workdir 不混用 |
| 失败处理 | 创建/权限/磁盘检查失败则不启动；清理失败保留记录并重试/告警，禁止通过重新指向其他目录假装成功 |
| 溯源 | G3、G5；US-3、US-4 |

### FR-6 路径、挂载与安全清理

| 项 | 说明 |
|---|---|
| 触发时机 | 任何文件/目录创建、读写、导出、挂载解析与递归清理前及操作中 |
| 输入 | 相对路径、平台允许的挂载源/目标、目录句柄和 Workdir 记录 |
| 输出 | 限制在所属 Workdir 内的文件操作与安全删除；拒绝绝对路径、`..`、NUL、反斜杠/编码绕过、跨租户和未批准挂载 |
| 执行方式 | 以受信根目录句柄逐组件 no-follow 打开并验证归属；清理不跟随软链，硬链/挂载点按拒绝或平台白名单处理，检查与使用同一安全句柄 |
| 失败处理 | 路径/链接/竞态异常立即失败关闭，不修改目录外目标；无法证明删除范围时停止清理并告警，不执行宿主级递归 rm |
| 溯源 | G3；US-4、US-5 |

### FR-7 资源限制与支持矩阵

| 项 | 说明 |
|---|---|
| 触发时机 | ProcessSpec 校验、spawn 前 Sandbox 准备、运行采样与 Workdir 写入/清理 |
| 输入 | CPU 时间、内存、最大进程数、Workdir 总字节/单文件字节、wall time、输出上限与资源策略 |
| 输出 | 每 Execution 的资源控制句柄、当前用量、超限终止/拒绝原因和释放结果 |
| 执行方式 | 优先按 Execution 的 cgroup/等价机制；开发可用明确标注的 POSIX rlimit+监督器；磁盘使用单文件限制与总量监测/可用配额，逐项声明能力强弱 |
| 失败处理 | `execution_resource_enforcement_required=true` 时任一要求不支持即拒绝启动；不得静默忽略、提高上限或用宿主机总量替代每 Execution 限制 |
| 溯源 | G4；US-5、US-6 |

### FR-8 Sandbox Provider 与不可信执行门槛

| 项 | 说明 |
|---|---|
| 触发时机 | Host 组合、ProcessSpec 启动、部署启用与 API 暴露评审 |
| 输入 | Sandbox Provider id/version、资源策略、受信任可执行目标和部署运行模式 |
| 输出 | 可替换 Sandbox 契约及 Phase 4 Local Provider；仅有平台内置受信任测试目标可运行 |
| 执行方式 | Host 依赖接口不依赖具体 Adapter；Local Provider 只做本阶段声明的进程/资源控制，不提供网络、凭据或强内核隔离承诺 |
| 失败处理 | 任意命令、用户上传代码、不可信多租户执行请求始终拒绝；没有强沙箱/网络/凭据门槛不得以配置打开 |
| 溯源 | G4、G5；US-6 |

### FR-9 健康、审计与可观测性

| 项 | 说明 |
|---|---|
| 触发时机 | Host 启动/停止、spawn/exit/cancel/reconcile、资源采样、Workdir 创建/清理与失败 |
| 输入 | 内部进程/Workdir 状态、host_id、Run/tenant 关联、原因码与耗时/用量 |
| 输出 | 结构化日志/指标/健康状态：活跃数、启动失败、孤儿、清理失败、恢复批次、退出原因、磁盘用量和滞留年龄 |
| 执行方式 | 以 Run ID/host_id/稳定错误码关联，指标低基数；内部运维读取走认证与 scope，公共 Run API 不暴露 OS 细节 |
| 失败处理 | 清理失败、反复孤儿、资源压力或 reconcile 停止须告警；日志/事件不记录 argv 秘密、环境变量、Token 或完整宿主路径 |
| 溯源 | G5；US-3、US-7 |

### FR-10 配置、部署与回滚

| 配置项 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `execution_runtime_host_enabled` | 全局 settings | `false` | 新 Host 总开关；关闭不接纳新外部进程，恢复/清理解耦完成前不得停用 |
| `execution_runtime_host_id` | 全局 settings / deployment | 空字符串 | 启用时必填且每执行根唯一稳定；不能与另一 Host 共用 |
| `execution_workdir_root` | 全局 settings / volume | `data/execution` | 平台执行根，生产指向独立持久卷；客户端不可设置 |
| `execution_sandbox_provider` | 全局 settings | `local` | Phase 4 本地进程/资源 Provider，不代表强沙箱 |
| `execution_resource_enforcement_required` | 全局 settings | `true` | 要求的能力不支持时拒绝启动 |
| `execution_process_cancel_grace_seconds` | 全局 settings | `5.0` | TERM 到 KILL 的宽限 |
| `execution_process_kill_timeout_seconds` | 全局 settings | `5.0` | KILL 后等待与升级人工处置期限 |
| `execution_process_reconcile_interval_seconds` | 全局 settings | `5.0` | 活跃/孤儿记录核对周期 |
| `execution_process_wall_timeout_seconds` | 全局 settings | `900` | 外部进程硬 wall-time 上限；与 Run deadline 取更早者 |
| `execution_process_output_max_bytes` | 全局 settings | `1048576` | 每个 stdout/stderr 流上限，超限终止 |
| `execution_resource_cpu_seconds` | 全局 settings | `600` | 每 Execution CPU 时间上限 |
| `execution_resource_memory_bytes` | 全局 settings | `536870912` | 每 Execution 内存上限 |
| `execution_resource_max_processes` | 全局 settings | `64` | 每 Execution 进程数上限 |
| `execution_workdir_max_bytes` | 全局 settings | `1073741824` | 每 Execution Workdir 总量上限 |
| `execution_workdir_max_file_bytes` | 全局 settings | `134217728` | 单文件写入上限 |
| `execution_resource_sample_interval_seconds` | 全局 settings | `1.0` | 用量/后代/磁盘监督采样周期，不作为安全隔离承诺 |
| `execution_workdir_retention_seconds` | 全局 settings | `86400` | 成功/取消 Workdir 默认保留时长 |
| `execution_workdir_failed_retention_seconds` | 全局 settings | `604800` | 失败 Workdir 保留时长，过期安全清理 |
| `execution_workdir_cleanup_interval_seconds` | 全局 settings | `60` | 到期与 cleanup_failed 重试扫描周期 |

## 非功能需求

- **性能**：进程与目录操作异步化/线程隔离，不阻塞 Worker 调度；I/O、指标标签和 reconcile 批量有上限，资源监督开销需测量，基线待 Phase 0。
- **可靠性**：Run 终态、进程退出、资源释放和目录删除分别记录；所有清理幂等，重复 cancel/reconcile 不产生重复信号误杀或重复删除。
- **安全**：默认拒绝任意命令和宿主路径；不可信多租户代码执行为硬禁用，Local Provider 与 cgroup/rlimit 不构成强沙箱。
- **多租户**：DB 记录和目录均绑定 tenant/business/workspace/run；跨租户访问不可达，清理前重新核对归属。
- **可移植性**：Linux 为完整验收目标；macOS 仅运行明确支持的开发子集，Windows/不支持能力失败关闭，不伪造通过。
- **可观测**：健康、资源与清理状态可由 Run/host 关联但不公开 PID/路径；日志、事件、DB metadata 和产物不含秘密。
- **可回滚**：新 Host 默认关闭，React 不变；停止新接纳→取消/排空→核对零活跃→关闭→应用回滚，新增表保留。

## 验收标准

| # | 场景 | 预期 | 溯源 |
|---|---|---|---|
| AC-1 | 两个不同测试 Adapter 使用同一 RuntimeHost，并检查依赖与公共 API | 无需修改 Host/Worker 即可复用；Adapter 无直接 spawn/信号/资源分支，公共响应无 PID/路径 | FR-1；G1；US-1、US-2 |
| AC-2 | 启动正常测试进程，传输有界 I/O 并等待退出；再注入管道错误和输出洪泛 | 正常 exit/结果正确；I/O 不阻塞 Worker；故障清理完整，输出超限终止进程组且无秘密日志 | FR-2；G1、G2；US-1、US-5 |
| AC-3 | 进程派生忽略 TERM 的子进程后取消；重复取消并发送迟到成功 | 宽限后 KILL 整组，实际后代均退出；Run 为 cancelled，迟到成功不覆盖，清理幂等 | FR-3；G2；US-2、US-5 |
| AC-4 | 分别触发 Run deadline、进程 wall timeout 与取消竞态 | 较早 deadline 生效；进程组/资源释放，错误/终态稳定，无重复终态或遗留 | FR-3；G2；US-2、US-5 |
| AC-5 | 杀死 Worker/重启容器留下进程，再模拟 PID 复用、身份不匹配和 DB 不可用 | 身份匹配的孤儿被回收；不匹配误杀为 0；DB 故障不盲杀，人工处置与告警明确 | FR-4；G2、G5；US-3、US-5 |
| AC-6 | 并发创建多个 Execution Workdir，完成/失败/取消后到期清理并重启恢复 | 目录唯一、权限正确、记录状态可恢复；保留策略生效，清理幂等且失败可重试/告警 | FR-5；G3、G5；US-3、US-4 |
| AC-7 | 提交绝对路径、`..`、编码/分隔符绕过、跨租户路径及未批准挂载源 | 全部在触及目录外资源前拒绝；合法相对路径可用，公共 API 不接受宿主路径 | FR-6；G3；US-4、US-5 |
| AC-8 | 构造指向外部文件的软链、硬链、挂载点及检查后替换竞态，再执行读写/清理 | 目录外内容读/写/删成功数为 0；无法证明范围时停止并告警，无宿主级递归删除 | FR-6；G3；US-4、US-5 |
| AC-9 | 在支持矩阵内分别越过 CPU、内存、PID、Workdir 总量/单文件、wall time 和输出边界，并在不支持环境启动 | 超限按规定时间拒绝/终止并释放资源；所需能力不支持时启动拒绝，静默忽略为 0 | FR-7；G4；US-5、US-6 |
| AC-10 | 替换 Sandbox 测试 Provider，并尝试任意命令、上传代码与不可信多租户执行 | Host 无需改 Adapter 即可替换 Provider；所有不可信执行入口保持拒绝，Local Provider 无强沙箱声明 | FR-8；G4、G5；US-6 |
| AC-11 | 观察正常、崩溃、孤儿、清理失败和资源压力，并尝试公共读取内部字段 | 指标/日志/告警覆盖全部状态且可关联 Run/host；秘密和 PID/PGID/完整路径不进入公共面 | FR-9；G5；US-3、US-7 |
| AC-12 | 升级 `0059_execution_runtime_host`（实际前驱 `0058_agent_execution_metadata`；由规划号 `0054` 改号，见 08 R-1），验证旧 React、默认关闭、停止接纳→排空→关闭→应用回滚 | 仅新增进程/Workdir 必要表；React 无回归；回滚后零活跃孤儿、记录保留且无需 downgrade | FR-4、FR-5、FR-10；G1、G5；US-2、US-3、US-7 |
