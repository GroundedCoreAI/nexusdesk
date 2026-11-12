# Phase 6 · 安全、可靠性与事件治理 — 需求文档

> 状态：待评审（仅规划，未实施）
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1~G7）；`docs/architecture/agent-execution-platform-v2.md` 第 7~10、12、17（Phase 6）、18.2/18.4 节

## 用户故事

**US-1（安全管理员）**：作为安全管理员，我希望按租户、Agent、Execution 和 Engine 签发短期凭据授权并可即时吊销，以便将凭据暴露限制在最小时间与范围。

**US-2（平台运维）**：作为平台运维，我希望不可信命令在强沙箱中运行且网络/文件默认拒绝，以便即使 Engine 被提示注入或恶意输入控制也不能访问宿主和其他租户。

**US-3（Worker/运行时研发）**：作为 Worker/运行时研发，我希望每次认领携带单调 Fencing Token 且所有写入校验所有权，以便过期 Worker 无法污染新尝试。

**US-4（SRE）**：作为 SRE，我希望 Worker 崩溃、进程 hang、取消和超时都可恢复并释放资源/配额，以便故障不会形成永久 running、孤儿进程或容量泄漏。

**US-5（客户端研发）**：作为客户端研发，我希望事件具有稳定版本、顺序与去重标识，SSE 断线后可重放并显式处理缺口，以便构建可靠且不重复的用户体验。

**US-6（财务与审计人员）**：作为财务与审计人员，我希望 usage 同源重复不重复计费且所有纠正可追踪，以便用量数据可信。

**US-7（Adapter 研发）**：作为 Adapter 研发，我希望 malformed/未知原生事件有有界脱敏诊断且不拖垮事件流，以便定位协议升级问题而不泄露 Secret。

## 功能需求

### FR-1 Execution 凭据 Vault 与生命周期

| 项 | 说明 |
|---|---|
| 触发时机 | 创建、读取、轮换、吊销、删除或恢复 Engine 凭据时。 |
| 输入 | 可信租户/管理员身份、凭据类型、Secret、允许 Engine/Workspace 范围、版本与安装密钥/KMS 接口。 |
| 输出 | 密文凭据记录、不可回读的 Secret 引用、版本/状态和不含明文的审计。 |
| 执行方式 | 管理操作同步事务；运行时仅按引用获取，公共配置永不返回 Secret。 |
| 失败处理 | 缺密钥、解密/绑定不匹配、吊销或版本过期均 fail closed；禁止自动重建丢失主密钥。 |

### FR-2 Credential Broker 短期授权

| 项 | 说明 |
|---|---|
| 触发时机 | Execution 启动、Session Resume、凭据轮换/吊销或授权到期时。 |
| 输入 | 当前认证上下文、tenant/agent/run、Engine/Protocol、Workspace、凭据版本、scopes、expires_at。 |
| 输出 | 与 Execution/受众/范围绑定的短期 grant 或 Secret 挂载，以及授权/拒绝/使用审计。 |
| 执行方式 | 启动前同步授权，运行时最小暴露；grant 不可跨 Execution 转移。 |
| 失败处理 | 跨租户、跨 Engine、过期、吊销、重放或 scope 扩大全部拒绝；Resume 必须重新授权，旧 grant 不作为权限凭证。 |

### FR-3 全链路 Secret 脱敏与泄露处置

| 项 | 说明 |
|---|---|
| 触发时机 | 写日志、事件、SSE、错误、审计、parser 诊断、产物元数据或告警前。 |
| 输入 | 注册 Secret 指纹/canary、结构化敏感字段、通用 Token 模式和输出大小限制。 |
| 输出 | 稳定占位符、脱敏诊断与泄露安全事件；原始 Secret 不进入普通存储。 |
| 执行方式 | 在信任边界同步脱敏；产物内容按策略扫描、隔离或拒绝发布。 |
| 失败处理 | 无法安全判定的诊断默认不公开；发现泄露立即吊销相关凭据、停止新执行并保留无 Secret 的取证引用。 |

### FR-4 强沙箱与资源限制

| 项 | 说明 |
|---|---|
| 触发时机 | 任何可执行不可信代码/命令的 Engine Execution 启动前及运行中。 |
| 输入 | 不可信级别、Sandbox Provider、非特权身份、只根/挂载策略、CPU/内存/PID/磁盘/时间限制。 |
| 输出 | 隔离 RuntimeHost 实例、有效策略快照、资源指标和销毁证据。 |
| 执行方式 | 启动前同步创建并验证沙箱，执行中异步监管；安全策略不能由 Agent 配置放大。 |
| 失败处理 | 沙箱不可用、权限过高、限制无法执行或检测到逃逸时拒绝/终止并告警；不得降级为宿主直接执行。 |

### FR-5 沙箱网络出口策略

| 项 | 说明 |
|---|---|
| 触发时机 | Engine 或其子进程发起 DNS、连接、重定向或代理请求时。 |
| 输入 | 默认拒绝策略、目标 host/IP/port、DNS 解析结果、租户/Execution 允许清单。 |
| 输出 | 仅授权连接的放行结果、脱敏网络审计和拒绝指标。 |
| 执行方式 | 在沙箱网络边界同步判定；校验每一跳与实际连接 IP，不只校验 URL 字符串。 |
| 失败处理 | 私网/链路本地/元数据地址、DNS rebinding、未授权重定向、隧道/代理绕过均拒绝；失败不自动放开。 |

### FR-6 文件系统、挂载与产物隔离

| 项 | 说明 |
|---|---|
| 触发时机 | 创建 Workdir、挂载、读写、导出产物和清理时。 |
| 输入 | tenant/workspace/execution、规范化路径、只读/读写策略、文件类型/大小与产物授权。 |
| 输出 | 单次 Execution 文件视图、授权产物、完整清理与越权审计。 |
| 执行方式 | 在沙箱和 Workspace Provider 双层校验；路径解析防 TOCTOU，挂载最小化。 |
| 失败处理 | 穿越、symlink/hardlink、设备文件、宿主敏感路径、跨租户和未授权覆盖均拒绝；失败不导出可疑产物。 |

### FR-7 Lease Epoch / Fencing Token 全覆盖

| 项 | 说明 |
|---|---|
| 触发时机 | claim、续租、接管及任何 Worker/Host 代表 Execution 写入或释放资源时。 |
| 输入 | run_id、owner、单调 lease_epoch、lease 有效期和操作幂等键。 |
| 输出 | 仅当前 epoch 可成功的条件写入；过期操作稳定拒绝并审计。 |
| 执行方式 | epoch 在数据库认领/接管事务中递增；状态、事件、usage、Session、Outbox 和资源操作使用同一所有权证据。 |
| 失败处理 | owner/epoch/lease 不匹配不得产生部分写入；不能靠应用先查后写替代数据库条件更新/约束。 |

### FR-8 Worker 丢失、迟到结果与终态保护

| 项 | 说明 |
|---|---|
| 触发时机 | heartbeat 失败、lease 过期、Worker 崩溃、旧结果/事件迟到或恢复器接管时。 |
| 输入 | Run/epoch、最后 heartbeat、Host 存活证据、当前终态与恢复策略。 |
| 输出 | 明确可恢复状态或唯一终态、Fencing 拒绝记录、清理/告警与最终事件。 |
| 执行方式 | 检测与接管事务化；先 fence 旧 epoch，再决定恢复或失败，不允许双有效 Worker。 |
| 失败处理 | 无法证明外部副作用或进程状态时不盲目重试/完成；迟到成功不得覆盖 cancelled/failed/新 epoch。 |

### FR-9 取消确认、超时清理与配额释放

| 项 | 说明 |
|---|---|
| 触发时机 | 用户取消、队列/执行超时、Worker 停止、崩溃恢复和清理重试时。 |
| 输入 | cancel_requested、epoch、Host 进程树、连接、挂载、资源预留与清理截止时间。 |
| 输出 | 取消请求事件、真实退出/清理确认、唯一终态、资源释放与审计。 |
| 执行方式 | 请求与确认分离；优雅终止后强制清理，清理操作可重入且仍受 Fencing/策略约束。 |
| 失败处理 | 未确认退出不得伪报 cancelled；标记 cleanup_failed/cancellation_unconfirmed、保持隔离并告警；Run 活跃配额与 Host 资源配额分别按真实状态释放。 |

### FR-10 重试分类与副作用治理

| 项 | 说明 |
|---|---|
| 触发时机 | 启动失败、协议/网络错误、超时、Worker 丢失、Outbox 重试或人工重跑时。 |
| 输入 | 错误类别、执行阶段、幂等键、已知副作用、attempt/retry_of_run、退避与预算。 |
| 输出 | 可安全重试、延迟重试、需人工处理或禁止重试的决定及审计。 |
| 执行方式 | Run 仍表示一次 Execution 尝试；新尝试关联旧 Run 并获得新 epoch，不引入 Task 双表。 |
| 失败处理 | 未启动且无侧效应才可自动重试；超时/断连等模糊结果默认不自动重放副作用请求，Outbox 重试不得重复业务效果。 |

### FR-11 事件 Schema 与 Sequence 治理

| 项 | 说明 |
|---|---|
| 触发时机 | 产生、持久化、迁移或消费平台/原生事件时。 |
| 输入 | event_id、schema_version、run/execution、engine_session、sequence、type、source、timestamp、payload。 |
| 输出 | 版本化公共外层、Run 内严格单调 sequence、兼容的存量事件视图。 |
| 执行方式 | sequence 与事件在同一数据库事务分配；schema 解析遵循显式版本和大小限制。 |
| 失败处理 | 未知主版本、非法 payload、非授权 source 或 sequence 冲突拒绝/诊断；不得静默重排或重编号历史事件。 |

### FR-12 事件去重与事务性 Outbox

| 项 | 说明 |
|---|---|
| 触发时机 | Adapter 重发原生事件、Worker 重试、Run 状态/事件提交和 Outbox 发布时。 |
| 输入 | 全局 event_id、producer/native_event_id、Run/epoch、事件记录与发布游标。 |
| 输出 | 单次持久业务事件、同事务 Outbox 记录、可重试发布状态和去重审计。 |
| 执行方式 | 状态+事件+Outbox+必要 usage 在同一事务；提交后发布，NOTIFY 仅唤醒，数据库事实源可恢复。 |
| 失败处理 | 重复输入返回原结果不占新 sequence；发布失败有界退避；崩溃可重扫未发布记录，不产生部分终态。 |

### FR-13 SSE 重连、游标重放与缺口处理

| 项 | 说明 |
|---|---|
| 触发时机 | 新建事件流、断线重连、分页追赶、保留期清理或 Run 终态时。 |
| 输入 | 可信租户/scope、Run、`after`/`Last-Event-ID`、保留游标与 live 通知。 |
| 输出 | 有序持久事件、兼容 SSE `id=sequence`、payload 中 event_id/schema_version、心跳和明确终态。 |
| 执行方式 | 先鉴权再从 Event Store 分批重放并追赶 live；通知丢失可轮询恢复。 |
| 失败处理 | 非法游标返回 400；游标早于可用保留期返回明确 409/重置指令，不静默跳事件；瞬时 delta 仍不冒充可重放事件。 |

### FR-14 Usage 幂等聚合与纠正

| 项 | 说明 |
|---|---|
| 触发时机 | 收到原生/终态 usage、事件重放、Worker 重试或供应商修正时。 |
| 输入 | Run/epoch、source、source_event_id、usage schema、数量/成本、收到时间和修正关联。 |
| 输出 | 唯一来源记录、幂等聚合视图、缺失/估计标记与可追踪纠正。 |
| 执行方式 | 来源唯一约束+事务 upsert；同一来源重复返回既有记录，不重复计数。 |
| 失败处理 | 未知不填零；迟到 usage 以修正/版本处理而非盲加；旧 epoch 不得写入，聚合失败可重建。 |

### FR-15 原生事件 Parser Diagnostics

| 项 | 说明 |
|---|---|
| 触发时机 | 原生事件无法解析、未知类型/schema、字段越界或 payload 超限时。 |
| 输入 | Adapter/Protocol 版本、Run、原生事件标识、解析位置、分类与有界样本。 |
| 输出 | 脱敏结构化诊断、计数/率限指标、明确 skip/quarantine/fail 策略和安全告警。 |
| 执行方式 | 诊断不阻塞可继续的独立事件；原始样本默认不公开且有大小/频率上限。 |
| 失败处理 | 连续错误或关键终态不可解析时按策略失败并告警；诊断自身不得造成无限递归事件或 Secret 泄露。 |

### FR-16 配置、迁移、观测与兼容发布

| 配置项 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `execution_untrusted_tenants_enabled` | 全局 settings | `false` | 只有全部硬门禁通过且独立安全与 SRE/运维批准完成才能开启，不能单独绕过子策略；人员或证据不足时保持关闭。 |
| `execution_sandbox_required` | 全局 settings | `true` | 不可信执行必须沙箱；禁止用配置降级为宿主执行。 |
| `execution_network_default_deny` | 部署策略 | `true` | 默认无出口，按 Execution 最小放行。 |
| `execution_credential_grant_ttl_seconds` | 全局 settings | 有界短默认值，评审冻结 | grant 到期即不可用，不得超过部署硬上限。 |
| `execution_outbox_enabled` | 全局 settings | 兼容灰度，目标常开 | 灰度期可控制发布器；Event Store 轮询始终可恢复，不回退安全校验。 |
| `execution_event_retention_days` | 部署策略 | 评审后确定 | 仅清理允许保留的数据；游标缺口显式返回。 |
| `execution_parser_raw_sample_enabled` | 全局 settings | `false` | 默认不保留原始样本；临时启用仍有脱敏和大小/期限限制。 |

## 非功能需求

- **性能**：Fencing/Outbox/脱敏不得造成无界锁等待或事件积压；p50/p95、Outbox lag、恢复时间目标在 Phase 0 基线后冻结。
- **兼容**：既有 Run 状态、事件类型、SSE `id`、React/Codex 公共契约与历史配置保持兼容；新增字段采用扩展/回填，不改历史迁移。
- **多租户**：凭据、grant、Workspace、事件、usage、诊断和审计全部绑定可信 tenant/scope，跨租户默认拒绝。
- **安全**：不可信执行没有“关闭沙箱以提高可用性”的模式；Secret 不明文落库/日志/事件，网络与文件默认拒绝。
- **可靠性**：所有多步写入具备事务边界和可重入恢复；终态唯一、最终事件一致、资源与配额可核对。
- **可运维性**：提供 Fencing 拒绝、Worker 丢失、清理失败、Outbox lag、重放缺口、usage 冲突、parser 错误和吊销的指标/告警/审计。

## 验收标准

| # | 场景 | 预期 | 溯源 |
|---|---|---|---|
| AC-1 | 创建/轮换/吊销 Execution 凭据，并模拟主密钥缺失、绑定篡改和跨租户读取。 | 密文存储且公共视图无明文；轮换按版本生效，吊销后新使用拒绝，异常全部 fail closed 并审计。 | FR-1；G1 |
| AC-2 | 为指定 Run/Engine/scope 签发短期 grant，再跨 Execution、扩大 scope、过期、重放和 Resume 使用。 | 仅原授权范围可用；其余拒绝，Resume 重新授权，审计不含 Secret。 | FR-2；G1 |
| AC-3 | 将 Secret canary 注入日志、stdout、事件、SSE、异常、诊断和产物并模拟泄露。 | 普通输出全部脱敏/隔离；泄露处置吊销凭据并停止新执行，不保存明文取证。 | FR-3；G1、G2 |
| AC-4 | 在不可信任务中尝试宿主/容器逃逸、提权、fork bomb、内存/磁盘耗尽，并禁用沙箱启动。 | 沙箱不可用时拒绝；攻击被限制/终止，宿主与其他 Execution 不受影响，有资源和告警证据。 | FR-4；G2 |
| AC-5 | 尝试未授权外联、DNS rebinding、私网/元数据、重定向和代理绕过。 | 所有未授权连接在实际网络边界拒绝；允许清单最小生效，审计无凭据。 | FR-5；G2 |
| AC-6 | 尝试 `../`、绝对路径、symlink/hardlink、设备文件、宿主路径、跨租户及恶意产物导出。 | 全部越权拒绝；合法文件限定在 Execution 视图，清理无残留，可疑产物不发布。 | FR-6；G2 |
| AC-7 | Worker A 过期后由 B 接管，A 再提交状态、事件、usage、Session、Outbox 和资源释放。 | B 获得更大 epoch；A 的所有有效写入均为 0，无部分提交，有 Fencing 审计。 | FR-7；G3 |
| AC-8 | 注入 Worker 崩溃、heartbeat 停顿、lease 过期与旧 Worker 迟到成功。 | 进入定义的可恢复状态或唯一终态；旧结果不覆盖，无双 Worker/双终态，恢复可诊断。 | FR-8；G3 |
| AC-9 | 对运行中任务取消/超时并分别注入正常退出、hang、清理失败和 Worker 丢失。 | 确认退出与清理后才 cancelled；异常明确失败/告警；无孤儿资源或配额泄漏。 | FR-9；G3、G4 |
| AC-10 | 在启动前失败、超时后结果不明、外部写入后断连及 Outbox 重试场景请求重试。 | 仅证明无副作用的场景自动重试；模糊/有副作用请求不盲放，新 attempt 关联且不重复效果。 | FR-10；G4 |
| AC-11 | 混合写入 v1/新版本平台与原生事件，并制造非法 schema 和并发 sequence 分配。 | 版本可识别、历史兼容、sequence 严格单调无冲突；非法输入有诊断且不重编号历史。 | FR-11；G5 |
| AC-12 | 重发相同原生事件，并在状态+事件+Outbox 提交及发布前后注入崩溃。 | 重复不占新 sequence/不重复效果；事务无部分终态，恢复后 Outbox 以至少一次投递和幂等消费完成发布，不宣称网络层恰好一次。 | FR-12；G5 |
| AC-13 | SSE 在大于单页事件量下断线重连、丢通知、非法/过旧游标和终态追赶。 | 保留期内无静默缺口，event_id 去重、SSE id 兼容；过旧游标明确 409，终态与最终事件一致。 | FR-13；G5 |
| AC-14 | 重复/重放同一 usage，旧 Worker 迟到 usage，供应商发送修正和缺失字段。 | 同源只计一次，旧 epoch 拒绝，修正可追溯，未知不填零，聚合可重建。 | FR-14；G6 |
| AC-15 | 注入 malformed、未知类型、超限 payload、连续解析失败和含 Secret 样本。 | 诊断分类/关联/率限正确，样本脱敏；按策略 skip/quarantine/fail，无事件风暴或 Secret 泄露。 | FR-15；G6 |
| AC-16 | 灰度启用/回滚各能力，升级规划迁移并运行 React/Codex、Run/API/SSE 与历史数据回归。 | 安全校验不可被开关绕过；迁移可在线扩展/回填，回滚不删数据；Phase 0 diff 为零。 | FR-16；G7 |
