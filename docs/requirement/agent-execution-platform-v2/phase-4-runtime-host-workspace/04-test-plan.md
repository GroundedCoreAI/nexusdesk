# Phase 4 · Runtime Host、进程监管与 Workspace — 测试方案

> 状态：待实施（本阶段开发完成后执行；当前无测试结果）
> 创建：2026-11-02
> 修订：2026-11-11（小团队轻量验收：复用自动化证据，移除多角色签字要求）
> 修订：2026-11-14（08 R-1/R-3/R-5：复核真实 head 为 `0058_agent_execution_metadata` 后迁移由 `0054` 改号 `0059_execution_runtime_host`；新增 §2.1，登记当前 darwin 执行主机的 macOS 开发子集与 `pending_env` 规范性划分；测试文件命名遵循 `test_agent_execution_phase4_*`）
> 修订：2026-11-14（协调裁定 08 R-11/R-12：P4-IT-13 增加同 Run 并发 prepare 收敛预期；P4-IT-15/P4-IT-21 断言"最近一次成功观测"磁盘记账——超限观测必须持久化并发结构化超限告警，删除前重观测一次）
> 修订：2026-11-14（协调裁定 08 R-13/R-14：§2.1 登记 macOS `RLIMIT_AS` 近似以探针判定适用性，及平台无关的资源超额证据契约）
> 依据：`02-requirements.md`（FR-1–FR-10、AC-1–AC-12）、`03-technical-design.md`（Host、进程组、恢复、Workdir、资源矩阵与回滚）

## 1. 测试范围与原则

**范围**：RuntimeHost/Adapter 解耦、Process Runner/Supervisor/Registry、有界 I/O、取消与超时、孤儿恢复、Workspace/Execution Workdir、安全路径与清理、资源限制、Sandbox Provider、健康观测、迁移 `0059_execution_runtime_host`、部署和回滚。

**原则**：

1. **基线先行**：React、Worker 调度和监督开销基线以 Phase 0 实测为准；未完成前标“待 Phase 0”，不得用本阶段新实现反写预期。
2. **真实进程验证**：进程组、TERM/KILL、退出、输出洪泛与资源边界必须运行仓库内置可信测试目标，不能只用 mock 协程宣称通过。
3. **失败关闭必测**：spawn/管道/DB/身份/资源/清理故障不能留下无主进程、伪成功或绕过拒绝的路径。
4. **恶意输入必测**：路径穿越、编码绕过、跨租户、链接/挂载点和检查使用竞态均验证目录外读/写/删成功数为 0。
5. **身份优先于 PID**：恢复测试覆盖 PID 复用与启动身份缺失；任何不匹配都禁止发信号，不按进程名或命令行模糊清理。
6. **状态分别核验**：Run 终态、进程退出、资源释放和 Workdir 删除分别断言，不能以一个状态替代另一个。
7. **破坏性测试隔离**：只操作专用临时执行根、容器和哨兵文件；禁止在开发者宿主根目录、生产卷或真实客户目录做递归删除/挂载试验。
8. **环境能力如实记录**：Linux 完整矩阵与 macOS 开发子集分开报告；缺失项标 `pending_env`，不得将 rlimit/监测近似写成 cgroup 等价能力。
9. **秘密不入证据**：测试目标不接收真实模型/平台密钥；日志、DB metadata、事件与证据附件均做敏感扫描。
10. **证据复用**：UT/IT/CM 的自动化结果及进程、资源、DB、文件系统证据直接供 A/C 验收引用，不为验收重复手工执行整套测试；人工只补无法自动化的关键检查。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 纯单测 + fake clock | 状态机、路径规范化、恢复决策、支持矩阵、设置边界与幂等分支，无需 OS 进程 |
| Linux 真实进程集成环境 | 进程组、嵌套后代、信号、有界 I/O、退出、超时、取消和资源监督 |
| Linux cgroup v2 专用资源环境 | 每 Execution CPU/内存/PID 硬限额与资源释放；只运行内置可信负载 |
| macOS 明确支持的开发子集 | POSIX rlimit/监督器的非等价行为与不支持能力拒绝；不据此签完整资源验收 |
| 专用 PostgreSQL + pytest fixture | 进程/Workdir 记录、锁、并发、崩溃恢复、DB 故障与跨租户核对 |
| 可重启 Worker/容器环境 | 同执行根、稳定 host_id、新 host_instance_id 的孤儿恢复与停止排空 |
| 隔离文件系统/挂载命名空间 | 软链、硬链、挂载点、替换竞态、配额与安全删除；外部目标均为测试哨兵 |
| 两个 Phase 1 测试 Adapter + Phase 2/3 编排 | Host 复用、ExecutionRequest/Effective 前置、事件/终态和 Sandbox 替换 |
| disposable 迁移库与存量副本 | 从实际前驱升级、旧 React、并发读写、应用回滚及配对 downgrade |
| quickstart/production 部署检查环境 | 默认关闭、执行卷、单 Host、停止期限、非秘密配置与回滚 |

**数据构造约定**：至少两个 tenant、多个 business/workspace scope 和并发 Run；可执行目标及 argv 白名单固定，子进程/CPU/内存/磁盘/输出负载由测试参数控制但不接受用户代码。外部链接目标均为隔离哨兵。PID 复用优先用身份决策替身确定性构造，再用独立 OS 试验佐证；禁止为“复用 PID”杀无关进程。每例独立清理进程组、资源句柄、Workdir 和 DB 行，清理失败必须作为结果发现。

### 2.1 macOS 开发子集与 `pending_env` 划分（规范性，2026-11-14，08 R-3）

当前执行主机为 macOS（darwin），PostgreSQL 通过 Docker 可用（独立 pgvector 容器，`TEST_DATABASE_URL`）。在 Linux 完整验收环境就绪前，以下划分管辖 §3–§5 全部用例，用例文字有歧义时以本表为准。本机实测项只有在附带环境标注时才可记 pass；`pending_env` 项继续阻断其对应启用承诺（原则 8、05 C14），绝不允许用近似实现冒充通过。

| 划分 | 用例（半边） |
|---|---|
| macOS 可实测 | 除 cgroup/配额/真实 mount 半边外的全部 P4-UT；P4-IT-01–08、10（身份替身半边）、11–18（非 mount 半边）、21（单文件半边）、22、23（macOS 列）、24–27；P4-CM-02–06、08–13；进程组 TERM/KILL 及后代、标注为非等价的 rlimit CPU/地址空间/单文件近似、输出上限、墙钟/截止期竞态、APFS 上路径/链接/替换竞态安全、Workdir 生命周期、注册表 reconcile 与进程级 SIGKILL+重启恢复、docker PG 上迁移 0059 升降级、默认关闭的 React 一致性、本地 Docker 上 quickstart 画像容器演练 |
| `pending_env`（需 Linux） | P4-IT-19（cgroup memory 硬限半边与 CPU 组计量硬顶）、P4-IT-20（cgroup pids 每执行硬限）、P4-IT-21（文件系统/项目配额半边）、P4-IT-17 / P4-UT-13（真实 mount 命名空间半边）、P4-IT-10（确定性 OS PID 复用佐证半边）、P4-IT-09（生产镜像容器重启/停止期限半边）、P4-IT-29（生产运行时核查半边）、P4-IT-30（同时 `not_measured`：Phase 0 基线缺口，08 R-2）、P4-CM-07（完整支持矩阵签署） |

协调裁定注记（2026-11-14，08 R-13/R-14）：macOS 地址空间（`RLIMIT_AS`）近似一行以 fork 适用性探针判定——探针不适用时按 `execution_resource_enforcement_required=true` fail-closed 拒绝启动、不记 pass，属对本表的细化而非矛盾（每执行内存硬限仍属 Linux `pending_env`）。跨平台资源超额证据断言稳定原因码 `runtime_host_resource_exceeded` 与 mechanism/strength 标签，不断言各平台原始信号/退出码数值。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P4-UT-01 | 两个测试 Adapter 调用同一 Host 接口 | Host 无 Engine 分支，公共句柄只含平台字段，Adapter 不直接 spawn/signal | FR-1；AC-1 |
| P4-UT-02 | 未注册可执行目标、任意 argv/命令和敏感环境 | spawn 前拒绝；命令摘要可审计但无秘密 argv/env | FR-1、FR-2；AC-1、AC-2 |
| P4-UT-03 | stdout/stderr 分别接近和超过字节上限 | 各流独立背压；超限触发整组清理和稳定错误，不无限缓冲 | FR-2；AC-2 |
| P4-UT-04 | 取消状态机 TERM→宽限→KILL | 转换顺序、期限和原因稳定，重复取消不重启状态机 | FR-3；AC-3 |
| P4-UT-05 | Run deadline、process wall deadline 与取消竞态 | 取较早期限，仅一个清理所有者，错误/终态确定 | FR-3；AC-4 |
| P4-UT-06 | 迟到成功、重复退出和重复清理 | 取消终态不覆盖，exited/cleanup 状态幂等，不重复释放 | FR-3；AC-3、AC-4 |
| P4-UT-07 | host/实例/PID/PGID/start token/command digest 匹配决策 | 仅完整匹配记录可标 orphaned 并进入受管清理 | FR-4；AC-5 |
| P4-UT-08 | PID 复用、身份缺失/不匹配和跨 Host 记录 | 发信号数为 0，标 cleanup_failed/人工处置，不扫描无关记录 | FR-4；AC-5 |
| P4-UT-09 | reconcile 遇到 DB 不可用 | 有界重试并告警，不降级为全宿主扫描或按命令名 kill | FR-4；AC-5 |
| P4-UT-10 | Workdir 路径生成、权限与状态转换 | 每 Run 唯一，客户端路径不生效，合法状态单调且 cleanup_failed 可重试 | FR-5；AC-6 |
| P4-UT-11 | 保留到期、重复清理与 Tombstone | 成功/失败保留期分别生效，重复调用不删他人目录，记录保留 | FR-5；AC-6 |
| P4-UT-12 | 绝对路径、`..`、NUL、反斜杠、编码/重复分隔符和超长路径 | 全部在打开外部目标前拒绝，合法相对路径保持可用 | FR-6；AC-7 |
| P4-UT-13 | 软链、硬链、挂载点及逐组件 no-follow 策略 | 默认拒绝或仅平台显式白名单，检查与使用同一目录句柄 | FR-6；AC-8 |
| P4-UT-14 | 清理范围无法证明或发生替换竞态 | 立即停止、保留外部哨兵并告警，不执行宿主级递归删除 | FR-6；AC-8 |
| P4-UT-15 | CPU/内存/PID/磁盘支持矩阵组合 | 明确声明硬限额/近似/不支持；必需能力缺失时启动拒绝 | FR-7；AC-9 |
| P4-UT-16 | 资源超额原因、采样期限与幂等释放 | 超限原因稳定，资源句柄只释放一次，监测不被宣称为隔离 | FR-7；AC-9 |
| P4-UT-17 | Local Sandbox 与替换 Provider 契约 | Host 不依赖具体实现；Local 能力不含网络/凭据/强隔离承诺 | FR-8；AC-10 |
| P4-UT-18 | 任意命令、上传代码与不可信多租户开关绕过 | 所有入口硬拒绝，配置不能把 Local Provider 变成不可信执行许可 | FR-8；AC-10 |
| P4-UT-19 | FR-10 默认值、环境覆盖与非法边界 | 默认关闭；非法超时/限额/host_id/root/interval 在启动前拒绝 | FR-10；AC-12 |
| P4-UT-20 | spawn 后登记失败及资源准备部分失败 | 逆序清理同一受管句柄，不留下无主进程或资源引用 | FR-2、FR-4、FR-7；AC-2、AC-5 |
| P4-UT-21 | 公共结果、日志、指标和 DB metadata 序列化 | 不含 PID/PGID、完整宿主路径、Token、环境值或秘密 argv | FR-2、FR-9；AC-2、AC-11 |
| P4-UT-22 | 健康汇总、低基数标签和 stalled reconcile | 活跃/孤儿/失败/磁盘状态可关联，异常触发告警且无高基数标签 | FR-9；AC-11 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P4-IT-01 | 两个不同测试 Adapter 经 Orchestrator 使用同一 Host | 不改 Host/Worker 即复用；协议处理独立，公共 API 无 OS 内部字段 | AC-1；FR-1 |
| P4-IT-02 | 正常内置测试进程启动、双向有界 I/O、退出与结果提交 | exit/结果正确，事件顺序合法，进程/资源/Workdir 状态分别完成 | AC-2；FR-2、FR-5 |
| P4-IT-03 | 注入 spawn、管道读、启动身份和登记失败 | 已创建资源全部清理，Run 稳定失败，无未登记存活进程 | AC-2；FR-2、FR-4 |
| P4-IT-04 | stdout/stderr 持续洪泛并观察 Worker 调度 | 各流按上限终止进程组，内存/日志有界，Worker 心跳不饿死 | AC-2；FR-2 |
| P4-IT-05 | 父进程派生多层忽略 TERM 的子进程后取消 | 宽限后 KILL 整组，全部可观察后代退出，资源与目录进入后续清理 | AC-3；FR-3 |
| P4-IT-06 | 重复取消、协程取消和迟到 Adapter 成功 | 只清理一次，Run 为 cancelled，迟到结果不能覆盖 | AC-3；FR-3 |
| P4-IT-07 | 分别触发 Run deadline、process wall timeout 和并发取消 | 较早者生效，组/资源释放，无重复终态、僵尸或遗留 | AC-4；FR-3 |
| P4-IT-08 | 进程存活时强杀 Worker 并以同 host_id 重启 | 新实例只处理匹配记录，孤儿终止并清理，不恢复协议或重放 Run | AC-5；FR-4 |
| P4-IT-09 | 容器重启、持久卷保留与停止期限演练 | 记录和 Workdir 可恢复，停止先排空，默认清理在 stop grace 内完成 | AC-5、AC-12；FR-4、FR-10 |
| P4-IT-10 | 构造 PID 复用、start token/digest 不匹配和身份不可读 | 新进程误杀为 0，记录转人工处置并告警，目录不盲目删除 | AC-5；FR-4、FR-6 |
| P4-IT-11 | 恢复期间 DB 断连、锁冲突和部分批次失败 | 不盲扫/盲杀；有界重试，其他批次不越权， stalled 状态可观测 | AC-5；FR-4、FR-9 |
| P4-IT-12 | Run 已终态但进程仍存活，以及进程 exited 但资源清理失败 | 两者仍按真实状态清理/告警，不以 Run 或 exited 冒充资源释放 | AC-3、AC-5、AC-11；FR-3、FR-4 |
| P4-IT-13 | 并发创建同 tenant/跨 tenant 多 Run Workdir | 路径唯一、0700/0600 权限正确，scope 不串用，启动前记录完整；**同 Run** 并发/重复 prepare 收敛为唯一 `ready` 记录，绝不返回 `preparing`（08 R-11） | AC-6；FR-5 |
| P4-IT-14 | 完成/失败/取消后的保留到期与 Host 重启恢复 | 各保留策略正确，状态可恢复，过期清理不提前删除失败证据 | AC-6；FR-5 |
| P4-IT-15 | 清理中权限/磁盘/DB 故障并重复重试 | cleanup_failed 可见可告警，修复后幂等完成，Tombstone 保留且携带物理删除前重观测得到的最后一次成功用量（08 R-12） | AC-6；FR-5、FR-9 |
| P4-IT-16 | 原始 API/内部调用提交穿越、编码、跨租户路径和未批准挂载 | 触及外部资源前全部拒绝，合法相对路径成功，无客户端宿主路径入口 | AC-7；FR-6 |
| P4-IT-17 | 构造指向外部哨兵的软链/硬链/挂载点并读写/导出/清理 | 外部读/写/删成功数为 0，拒绝原因稳定，无外部内容进入产物 | AC-8；FR-6 |
| P4-IT-18 | 检查后把目录/文件替换为链接并并发清理 | 句柄/no-follow 阻断竞态；范围不明即停，哨兵不变且有告警 | AC-8；FR-6 |
| P4-IT-19 | 在完整支持环境分别超过 CPU 时间与内存上限 | 按支持矩阵及时终止并释放整组，稳定资源错误，不影响相邻 Execution | AC-9；FR-7 |
| P4-IT-20 | 派生进程超过 PID 上限 | 在配置边界拒绝/终止，不用宿主总量替代，资源记录完整 | AC-9；FR-7 |
| P4-IT-21 | 分别超过 Workdir 单文件与总量上限 | 拒绝/终止并安全清理；磁盘用量与其他 Run/tenant 隔离；retain/清理中观测到的超限用量必须持久化到 `size_bytes` 并发结构化超限告警，不得只告警而留陈旧记录（08 R-12） | AC-9；FR-5、FR-7 |
| P4-IT-22 | 越过 wall time 与输出上限并叠加资源采样延迟 | 有界时间内终止，背压有效，无无限缓冲或监督协程泄漏 | AC-4、AC-9；FR-2、FR-3、FR-7 |
| P4-IT-23 | 在 macOS 开发子集/禁用 cgroup/不支持平台启动 | 仅明确支持项运行；required=true 时缺失能力启动拒绝，静默忽略为 0 | AC-9；FR-7、FR-10 |
| P4-IT-24 | 替换 Sandbox 测试 Provider 并尝试不可信执行入口 | 不改 Adapter/Host 契约即可替换；任意命令/上传代码/不可信多租户均拒绝 | AC-10；FR-8 |
| P4-IT-25 | 观察正常、崩溃、孤儿、清理失败、资源压力和 stalled reconcile | 指标/日志/告警完整可关联；公开读取不含秘密、PID/PGID 或完整路径 | AC-11；FR-9 |
| P4-IT-26 | 从实际前驱 `0058_agent_execution_metadata` 升级 `0059_execution_runtime_host` 并并发读写旧/新 Run | 只新增两表及索引，约束/锁正确，现有 Repository/React 读写不受阻 | AC-12；FR-4、FR-5、FR-10 |
| P4-IT-27 | 默认关闭运行 React，再执行停止接纳→排空→关闭→应用回滚 | React 与 Phase 0 基线一致；回滚零活跃孤儿，保留两表，无 downgrade 需求 | AC-12；FR-10 |
| P4-IT-28 | 有活跃或 cleanup_failed 进程时尝试完整回滚 | 完整回滚被阻断；新接纳停止但恢复/清理继续，人工处置路径明确 | AC-5、AC-12；FR-4、FR-10 |
| P4-IT-29 | 检查 quickstart/production 卷、Host 身份和 stop grace | 生产仅 runtime-worker 挂执行卷，无共享执行根；秘密不进入示例配置 | AC-12；FR-10 |
| P4-IT-30 | 高并发短进程与慢 I/O 下测量 Worker/Repository 延迟 | 进程操作不阻塞心跳/调度；开销相对 Phase 0 基线记录，目标未测前不判通过 | AC-2、AC-11；FR-1、FR-9 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P4-CM-01 | 迁移在线性与编号 | 实施前重验 head/down_revision；只加必要两表/索引，无历史迁移修改；disposable downgrade 顺序正确 | AC-12；FR-4、FR-5 |
| P4-CM-02 | Host/Adapter 边界 | 至少两个 Adapter 复用；Worker/Adapter 不直接管理 OS，公共模型无 PID/路径 | AC-1；FR-1 |
| P4-CM-03 | 进程组与 I/O 有界性 | TERM/KILL 覆盖后代，stdout/stderr/内存/日志有上限，清理幂等 | AC-2～AC-4；FR-2、FR-3 |
| P4-CM-04 | 重启身份与孤儿恢复 | host/boot/start token/digest 全核对；PID 复用误杀为 0，DB 故障不盲杀 | AC-5；FR-4 |
| P4-CM-05 | Workdir 状态与归属 | 每 Run 唯一、权限正确、tenant/scope 复核，保留/重试/Tombstone 可审计 | AC-6；FR-5 |
| P4-CM-06 | 文件系统对抗安全 | 穿越/编码/链接/挂载/竞态矩阵外部读/写/删成功数为 0，范围不明失败关闭 | AC-7、AC-8；FR-6 |
| P4-CM-07 | 资源支持矩阵 | Linux 完整能力实测；开发近似明确标注，required 能力缺失启动拒绝，无静默忽略 | AC-9；FR-7 |
| P4-CM-08 | Sandbox 与不可信执行禁令 | 可替换 Provider 不削弱边界；任意命令/上传代码/不可信多租户执行始终拒绝 | AC-10；FR-8 |
| P4-CM-09 | 健康与敏感信息 | 活跃/孤儿/失败/资源/磁盘可观测；公开面、日志、事件和 metadata 无秘密或 OS 内部细节 | AC-11；FR-9 |
| P4-CM-10 | 配置与部署 | FR-10 默认/边界正确；单 Host/执行根、生产独立卷、停止期限覆盖清理，示例无秘密 | AC-12；FR-10 |
| P4-CM-11 | 生命周期独立与幂等 | Run 终态不等于进程/资源/目录释放；重复 cancel/reconcile/cleanup 无误杀或误删 | AC-3～AC-6；FR-3～FR-5 |
| P4-CM-12 | 整体回滚 | 停止接纳后排空并核对零活跃再回滚应用；保留新表；cleanup_failed 阻断完整回滚 | AC-12；FR-10 |
| P4-CM-13 | 旧路径回归 | Phase 0 React/Worker/Repository/SSE 与 Phase 3 能力/配置/快照回归全绿，默认关闭无副作用 | AC-12；FR-1、FR-10 |
| P4-CM-14 | 环境限制与证据真实性 | 缺 Linux/cgroup/挂载/容器环境的相关项标 `pending_env` 并阻断对应上线承诺，不写成通过 | AC-5、AC-8、AC-9、AC-12；FR-4、FR-6、FR-7、FR-10 |
| P4-CM-15 | 阶段边界 | 未开放真实 Codex、通用不可信执行、强网络/凭据隔离或共享执行根多副本 | AC-10、AC-12；FR-8、FR-10 |

## 6. 回归范围

- Phase 0 锁定的 RuntimeEngine、Worker、Repository、取消/失租/超时、Run API 与 SSE 基线；尚无实测结果的兼容/性能结论保持“待 Phase 0”并阻断相应承诺。
- 既有 `test_runtime_engine.py`、`test_runtime_postgres.py`、模型/工具/知识访问与 Agent 配置/发布测试；Host 默认关闭时不得新增外部进程、目录或事件副作用。
- Phase 1 Adapter/Protocol、Phase 2 Orchestrator/ExecutionRequest、Phase 3 Effective/快照/Instruction Provider 回归；非外部进程 React 不经过 Host。
- 数据库迁移前后运行旧代码兼容、新代码空表与锁测试；disposable downgrade 后核对仅规划表被移除，生产库禁止试验。
- 后端 ruff、受影响 pytest 与 CI 全量；部署 compose 配置检查、容器停止/重启和卷权限检查。所有真实进程测试结束必须核对零测试后代与零临时执行根外修改。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 跨租户/宿主文件读写删；误杀无关进程；不可信代码执行入口；秘密泄露；无法控制的进程组或递归删除 | 立即停止验收并隔离环境，修复后完整重跑安全、恢复与回归套件 |
| P1 严重 | 后代/资源泄漏；取消/超时无效；孤儿恢复失败；必需资源限制被忽略；Run/进程状态破坏；回滚留下活跃孤儿 | 修复前不得进入验收或灰度 |
| P2 一般 | 非阻断清理重试、原因码、健康指标、保留策略或监督性能偏差 | 仅在无安全/可靠性影响且非硬门禁项时记录 owner、期限，由验收负责人在单一验收记录中确认带问题验收 |
| P3 轻微 | 非敏感日志、内部诊断或文档展示问题 | 排期修复，不得掩盖泄露、伪造支持矩阵或环境缺失 |

**出口准则**：P4-UT/IT/CM 全部通过；AC-1～AC-12 可复现；适用回归全绿；无 P0/P1 未关闭；目录外修改、无关进程误杀、不可信执行和静默忽略限额均为 0；默认关闭与 React 基线 diff 为 0；回滚零活跃孤儿。环境不可用项标 `pending_env` 并阻断其覆盖的上线承诺，禁止写成通过。
