# Phase 6 · 安全、可靠性与事件治理 — 测试方案

> 状态：待实施（本阶段开发完成后执行；当前未执行、未通过）
> 创建：2026-11-02
> 依据：`02-requirements.md`（FR-1~FR-16、AC-1~AC-16）、`03-technical-design.md`（规划迁移 0056/0057、Fencing、Outbox、Vault/Broker、Sandbox）

## 1. 测试范围与原则

**范围**：Execution Vault/Broker、脱敏、强沙箱/网络/文件隔离、Fencing/Worker 恢复、取消/清理/配额、重试副作用、事件 schema/sequence/dedup/Outbox、SSE replay、usage 幂等、parser diagnostics、迁移与兼容回归。

**原则**：

1. **对抗不是可选项**：真实不可信任务执行逃逸、外联、跨租户、Secret 外泄和资源耗尽攻击；仅检查配置不算通过。
2. **故障点必须精确**：在 claim/takeover、事务提交前后、Outbox 发布前后、清理各阶段和 SSE 追赶窗口注入崩溃，不只随机重启。
3. **零有效过期写入**：Fencing 同时断言状态、事件、usage、Session、Outbox 和资源操作，不能只断言 Run 状态。
4. **安全失败不可用降级替代**：沙箱/Broker/密钥/策略不可用必须拒绝，不得回退宿主执行、开放网络或跳过脱敏。
5. **兼容与空态必测**：存量 v1 事件、空新字段、瞬时 delta、历史 Run 和开关回滚均保持定义行为；Phase 0 未测基线不得记通过。
6. **时间与规模可控**：过期/退避用可控时钟；sequence/去重/重放使用并发和大于单页数据，不依赖长时间 sleep。
7. **证据隔离**：所有 Secret 均为专用 canary；攻击在专用环境，测试后吊销 grant、清理沙箱并核对无残留。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 单测（无 DB） | scope/TTL、脱敏、路径/IP、schema、重试矩阵、usage 修正、parser 分类。 |
| 集成（PG + pytest postgres fixture） | 迁移/回填、Fencing 条件写入、事务 Outbox、usage 台账、Session/Run 关联。 |
| 多 Worker/Host 故障环境 | 两个以上 Worker、独立 recovery、真实进程组；SIGKILL、heartbeat 停顿、断连和清理失败。 |
| 强沙箱对抗环境 | 非生产宿主、可销毁网络/卷、攻击样本、DNS/代理/元数据诱饵、资源限制观测。 |
| SSE/Outbox 环境 | 多 API/发布器、通知丢失、多页事件、断线重连、保留期游标和发布故障。 |
| React/Codex 回归环境 | Phase 0 基线、现有 DemoModel 与 Phase 5 受控 Codex、历史 Agent/Run/事件 fixtures。 |

**数据构造约定**：至少两个租户/Agent/Workspace、多个 Run/attempt/Session；构造 v1 历史事件、重复 producer_event_id、超过 200 条的事件页边界、同源/修正 usage、Secret canary 和恶意产物。真实密钥不写入仓库；缺少真实沙箱/故障环境的相关项标 `pending_env`，不得以 mock 代替硬门禁验收。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P6-UT-01 | Vault 密文绑定、轮换与吊销 | 租户/Engine/Workspace/版本不匹配及吊销均拒绝；缺密钥不自动重建。 | FR-1 |
| P6-UT-02 | Broker grant scope/audience/TTL | 仅原 Run/Engine/scope 可用；过期、重放、跨 Execution 和 scope 扩大拒绝。 | FR-2 |
| P6-UT-03 | Resume 重新签发 grant | 旧 grant 不可复用，新 Run 获得新短期 grant，吊销即时生效。 | FR-2 |
| P6-UT-04 | 结构化/文本/嵌套脱敏 | 注册 Secret、canary、Token 模式和敏感字段均替换；输出长度有界。 | FR-3 |
| P6-UT-05 | 不可信策略不能放大 | Agent/客户端不能关闭沙箱、扩大资源、网络、挂载或 grant scope。 | FR-4~FR-6、FR-16 |
| P6-UT-06 | 网络 host/IP/重定向判定 | 私网/链路本地/元数据、DNS 结果变化及未授权重定向均拒绝。 | FR-5 |
| P6-UT-07 | 文件规范化与链接/TOCTOU | 穿越、绝对路径、symlink/hardlink、设备与宿主敏感路径均拒绝。 | FR-6 |
| P6-UT-08 | claim/takeover epoch 单调性 | 接管得到更大 epoch；旧 owner/epoch/lease 条件更新零行且无部分写。 | FR-7 |
| P6-UT-09 | Fencing 操作覆盖矩阵 | finish/append/usage/session/outbox/resource 每类操作都有所有权校验，无遗漏路径。 | FR-7 |
| P6-UT-10 | Worker 丢失恢复决策 | 按 heartbeat/Host/副作用证据选择恢复或失败，不产生双有效 Worker。 | FR-8 |
| P6-UT-11 | 取消请求与确认状态机 | 未退出不能 cancelled；确认清理后仅一个终态，重复请求幂等。 | FR-9 |
| P6-UT-12 | 清理与两类配额释放 | Run 活跃槽位与 Host 资源预留分别按证据释放；清理重试不重复释放。 | FR-9 |
| P6-UT-13 | 重试分类矩阵 | 未启动无副作用可自动重试；超时/断连/已写外部系统禁止盲重试。 | FR-10 |
| P6-UT-14 | 事件 schema v1/新版本兼容 | 版本路由正确，未知主版本/非法 payload 拒绝，历史字段不改义。 | FR-11 |
| P6-UT-15 | sequence 并发分配与去重 | 并发新事件 seq 唯一单调；重复 producer 键返回首次结果不占 seq。 | FR-11、FR-12 |
| P6-UT-16 | Outbox 状态与退避 | pending/published 转换幂等，失败可重试，last_error 有界脱敏。 | FR-12 |
| P6-UT-17 | SSE 游标合并与保留缺口 | after/Last-Event-ID 取大值；非法 400、过旧 409，不静默跳页。 | FR-13 |
| P6-UT-18 | usage 来源唯一与修正链 | 同源重复不计数，修正可追溯，缺失 unknown，聚合可重建。 | FR-14 |
| P6-UT-19 | 旧 epoch usage 拒绝 | 迟到 usage 不写台账、不改聚合、不产生 Outbox。 | FR-7、FR-14 |
| P6-UT-20 | parser 分类、样本与率限 | malformed/unknown/size/critical 分类正确；样本脱敏有界，无递归诊断。 | FR-15 |
| P6-UT-21 | 安全默认配置 | 不可信默认 false，沙箱/默认拒绝网络 true，原始 parser 样本 false，TTL/保留有界。 | FR-16 |
| P6-UT-22 | 回滚兼容策略 | 关闭发布器不关闭事实源/Fencing/脱敏；不可信执行无安全降级开关。 | FR-16 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P6-IT-01 | 凭据全生命周期与绑定篡改 | 复现 AC-1；密文/公共 API/日志无明文，轮换/吊销/异常行为正确。 | AC-1 |
| P6-IT-02 | grant 跨 Run/过期/重放/Resume 对抗 | 复现 AC-2；仅原范围成功，其余拒绝并有无 Secret 审计。 | AC-2 |
| P6-IT-03 | Secret canary 全出口与泄露处置 | 复现 AC-3；日志/事件/SSE/错误/诊断/产物无明文，吊销和停止新执行生效。 | AC-3 |
| P6-IT-04 | 沙箱逃逸/提权/资源耗尽对抗 | 复现 AC-4；宿主和其他 Execution 不受影响，无沙箱时拒绝启动。 | AC-4 |
| P6-IT-05 | DNS rebinding/元数据/代理外联对抗 | 复现 AC-5；实际连接边界拒绝所有未授权流量，诱饵无命中。 | AC-5 |
| P6-IT-06 | 文件链接/宿主/跨租户/恶意产物对抗 | 复现 AC-6；无越权读写和残留，可疑产物不发布。 | AC-6 |
| P6-IT-07 | 双 Worker 接管后的全类型过期写入 | 复现 AC-7；A 的状态/事件/usage/Session/Outbox/资源写均零有效。 | AC-7 |
| P6-IT-08 | Worker SIGKILL/heartbeat 停顿/迟到成功 | 复现 AC-8；恢复或唯一终态，旧结果不覆盖，无双终态。 | AC-8 |
| P6-IT-09 | takeover 与 heartbeat/finish 并发竞态 | 新 epoch 唯一有效，旧 finish/append 回滚，最终事件与状态一致。 | AC-7、AC-8 |
| P6-IT-10 | 取消/超时正常退出与 hang | 复现 AC-9 正常/强制路径；进程树/连接/挂载清理，终态和配额正确。 | AC-9 |
| P6-IT-11 | 清理失败与 Worker 丢失后重入恢复 | 未确认不 cancelled；cleanup_failed/告警可见，恢复后无重复释放或孤儿。 | AC-9 |
| P6-IT-12 | 启动前失败与模糊断连重试 | 复现 AC-10；仅安全场景自动重试，新 attempt 关联且不重复副作用。 | AC-10 |
| P6-IT-13 | 外部写入后断连与人工重跑 | 不自动重放；人工新 Run 仍需幂等/授权，外部效果最多一次。 | AC-10 |
| P6-IT-14 | 混合事件版本与并发 sequence | 复现 AC-11；历史兼容、并发无冲突、非法 schema 有诊断。 | AC-11 |
| P6-IT-15 | 原生事件重复投递与并发去重 | 复现 AC-12 去重部分；同键仅一事件/seq/Outbox/usage。 | AC-12 |
| P6-IT-16 | 状态+事件+Outbox 提交故障点 | 提交前崩溃无部分状态；提交后崩溃可重扫，终态与最终事件一致。 | AC-12 |
| P6-IT-17 | Outbox 发布前后崩溃与重复发布 | 至少一次传输下 event_id 消费幂等，pending 可恢复，无重复业务效果。 | AC-12 |
| P6-IT-18 | SSE 多页断线/通知丢失/重连 | 复现 AC-13；大于单页数据无静默缺口，event_id 去重，瞬时 delta 不影响事实流。 | AC-13 |
| P6-IT-19 | SSE 非法/过旧游标与终态追赶 | 400/409 语义正确；订阅查询竞态不漏最终事件，终态一致。 | AC-13 |
| P6-IT-20 | usage 重复/重放/旧 Worker/修正 | 复现 AC-14；同源一次、旧 epoch 拒绝、修正与重建一致。 | AC-14 |
| P6-IT-21 | parser 连续失败/超限/Secret 样本 | 复现 AC-15；分类/率限/脱敏和 skip/quarantine/fail 正确，无事件风暴。 | AC-15 |
| P6-IT-22 | 0056 在线扩展/回填/校验 | 从实际 head 升级；存量 seq/event_id/schema/source 正确，无重复/重编号，锁预算有记录。 | AC-16；FR-7~FR-14 |
| P6-IT-23 | 0057 凭据迁移与数据保护 | 从实际 head 升级成功；公共查询无明文，有数据降级按策略保护。 | AC-16；FR-1、FR-2 |
| P6-IT-24 | 灰度/回滚与 React/Codex/API/SSE 回归 | 复现 AC-16；安全校验不降级、Outbox 协调无遗漏、Phase 0 diff 为零。 | AC-16 |
| P6-IT-25 | 故障后资源/配额/账务全量对账 | 混合 SIGKILL、断网、磁盘满和进程 hang 后，Run/Host/usage/Outbox 对账无残留。 | AC-8~AC-10、AC-12、AC-14 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P6-CM-01 | 迁移 head 与历史保护 | 0056/0057 仅规划号；实施前重核实际 head/依赖，0001~0052 及已合入迁移不修改。 | FR-16；G7 |
| P6-CM-02 | 在线迁移与回填 | expand/backfill/validate/switch 证据完整；存量事件确定性 ID、无重编号、无长锁失控。 | FR-11、FR-16 |
| P6-CM-03 | Secret 与审计扫描 | DB 公共视图、日志、事件、SSE、错误、诊断、产物、审计无明文 Secret/grant Token。 | FR-1~FR-3 |
| P6-CM-04 | 不可信开放门禁 | 默认关闭；任一安全/可靠性硬项未过均无法启用，配置不能绕过。 | FR-4、FR-16 |
| P6-CM-05 | 租户与 Workspace 隔离 | 凭据/grant/文件/事件/usage/诊断所有查询和操作均带可信 tenant/scope。 | FR-1~FR-6、FR-13~FR-15 |
| P6-CM-06 | Fencing 覆盖静态/动态核查 | 所有 Worker 写入口和资源操作都有 epoch 条件；故障注入零过期有效写。 | FR-7 |
| P6-CM-07 | Outbox/SSE/终态一致性 | Event Store 为事实源；无通知不丢数据，保留缺口显式，终态与最终事件一致。 | FR-12、FR-13 |
| P6-CM-08 | 清理、配额与告警 | 进程/FD/挂载/卷/grant/预留无残留；cleanup_failed、Outbox lag、Fencing、泄露有告警。 | FR-9、FR-16 |
| P6-CM-09 | 双语与需求溯源 | 中英结构/ID/表格行一致，UT/IT/CM、A/C 与 FR/AC/G 可追踪。 | G7 |
| P6-CM-10 | 性能与恢复基线 | p50/p95、Outbox lag、恢复时间与锁耗时如实记录；待 Phase 0 项不得判通过。 | FR-16；G7 |

## 6. 回归范围

- `backend/tests/test_runtime_postgres.py`：认领、容量、取消竞态、Worker 丢失、迟到结果、Run API 与 SSE replay。
- React/Codex 公共契约、Session Resume、RuntimeHost/Workspace、审批/输入和历史 Agent 配置。
- `test_gateway_credentials.py`、工具凭据/egress/Workspace 套件：新 Execution Broker/Sandbox 不削弱已有边界。
- 事件 v1 历史 fixtures、瞬时 model.delta、SSE `after`/`Last-Event-ID`、分页 200 条边界与现有客户端消费。
- 全迁移链路和实施时实际 head 的副本升级；0056/0057 的回填、旧二进制读取、回滚协调与数据保护。
- Phase 0 未测基线项保留“待 Phase 0”，不得通过平均性能或抽样结果掩盖 P0/P1 场景。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | Secret/跨租户泄露；沙箱/网络/文件逃逸；不可信误开放；数据丢失；过期 Worker 有效提交；重复计费。 | 立即停止新执行、吊销/隔离，修复并全量对抗与故障回归。 |
| P1 严重 | 终态/最终事件不一致；取消/清理/配额错误；Outbox 静默丢失；重放静默缺口；安全开关绕过。 | 修复前不得验收或开放任何新租户。 |
| P2 一般 | 非核心诊断/指标/兼容质量偏差，无安全与正确性影响。 | 仅在非硬门禁项且有 owner/期限时由产品、QA、安全共同签字。 |
| P3 轻微 | 文案、非敏感日志和文档问题。 | 排期修复并保留溯源。 |

**出口准则**：全部适用 UT/IT/CM 与 AC 通过；真实沙箱、多 Worker、故障点和真实 SSE/Outbox 项无未批准 skip；对抗攻击成功数为 0；过期写入/重复 usage/静默事件缺口为 0；回归全绿、Phase 0 diff 为零、无 P0/P1。任一硬门禁未过时，`execution_untrusted_tenants_enabled` 必须保持 false，阶段不得判整体通过。
