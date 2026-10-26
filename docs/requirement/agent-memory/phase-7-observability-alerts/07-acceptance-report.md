# Phase 7 · 生产观测与告警 — 验收报告

> 状态：已完成（AI 代理执行，待四方人工签字生效）
> 执行日期：2026-10-27
> 执行人：AI 验收代理（Claude Code）
> 依据：`05-acceptance-plan.md`（A1~A12、演练 1~3、C1~C5、§7 通过标准）；测试结论见 `06-test-report.md`（649 全绿，P1 缺陷 D1/D2/D3 已闭环）
> 分支：`feat/memory-observability-alerts`

## 1. 验收环境与替代声明

| 组件 | 形态 | 说明 |
|---|---|---|
| PostgreSQL | Docker 容器 `nexusdesk-pg17`（PG 17 + pgvector） | 验收库 `nexusdesk_accept`，Alembic head `0043` |
| API + 内嵌 Worker | 本地 uvicorn（127.0.0.1:8765），`AGENT_EMBEDDED_WORKER=true` | **quickstart 内嵌形态等效替代**：同一进程内嵌 Worker 与 quickstart 双容器中的 API 容器运行同一代码路径与同一告警扫描器 |
| 独立 Worker | 本地进程 `python -m agent_platform.apps.worker.memory`（`AGENT_EMBEDDED_WORKER=false`） | 演练 1 专用，对应 quickstart/compose 的独立 worker 容器形态 |
| 前端 | vite dev（localhost:5199，代理至真实 API）+ Playwright | 对**真实后端**执行 live-UI 校验（非 mock） |
| Mock 服务 | embedding mock（127.0.0.1:9871）、webhook mock（127.0.0.1:9872） | 演练 2 / A8 专用 |

**替代声明（诚实记录）**：本机 Docker 网络受限，`sh nexusdesk quickstart` 双容器形态不可用，按任务授权以「本地 uvicorn + 内嵌 Worker」替代 quickstart 内嵌形态、以「本地独立 Worker 进程」替代独立容器形态。两者与被替代形态共享全部告警/观测代码路径，差异仅在进程封装方式。A12 的 1 小时连续浸泡以约 40 分钟多轮重启观察替代（见遗留 L-2）。

**非默认验收参数**（均为缩短观察窗的验收调参，非默认值变更）：`AGENT_MEMORY_ALERT_SCAN_INTERVAL_MINUTES=1`（默认 15）、`AGENT_MEMORY_ALERT_WEBHOOK_URL`（仅 A8）、`AGENT_MEMORY_ALERT_ENABLED=false`（仅 A9）、`AGENT_MEMORY_EMBEDDING_PROFILE_ID/VERSION`（仅演练 2）、`AGENT_MEMORY_VECTOR_ENABLED=false`（仅演练 3）、`AGENT_EMBEDDED_WORKER=false`（仅演练 1 独立 Worker）。

**时间类用例执行原则**：所有时间条件（61 分钟积压、24h 静默、冷却过期、心跳超窗等）均通过 `UPDATE` 数据库时间字段构造老化状态实现，未做任何真实等待；数值结论均以「库直查 vs API 响应」对账为准。

## 2. AC 执行记录表（A1~A12）

以下所有场景：执行人 = AI 验收代理（Claude Code）；日期 = 2026-10-27；环境 = §1 所述验收栈。

| # | 前置数据 | 实际结果（关键 SQL/响应摘录） | 判定 |
|---|---|---|---|
| A1 | 基线种子：2 客户、5 条 memory_items（含哨兵文本）、7 条 memory_tasks、2 个 Agent 的 runs/events、11 条 injection_log、extract/maintenance/confirm 审计 | 观测端点返回全部十类指标分组；对账脚本 42/42 项一致（24h 与 168h 双窗口），摘录：`tasks.pending=1`、`by_kind.conversation_summary done=2/failed=1/avg=500ms`、`agents: alpha 2/5=0.4, beta 6/6=1.0`、`injection source=detail, by_section flag/profile/preference/event=1/1/1/8`；前端 live 校验 7 个分组标题 + 告警面板 + 168h 窗口切换重新取数全部通过（截图 `fe_live_observability.png`） | 通过 |
| A2 | 构造 `max_attempts=1` 的必失败任务（错误 payload），19:08:21Z 置 failed | 内嵌扫描器 19:09:08Z 落审计 `memory.alert.task_failed`（约 47s，≤ 2 个检查周期），`details={"value":1,"window":"15m","threshold":0}`；告警列表端点可见 `{"rule":"task_failed","value":1.0,"threshold":0.0,"window":"15m"}` | 通过 |
| A3 | A2 后保持失败条件，再次制造失败 | 冷却窗（60min）内第二次失败被抑制：80s 观察期告警计数恒为 1；将首条告警 `created_at` 老化 61min 后再次触发，新审计 `value=2` | 通过 |
| A4 | pending 任务 `created_at` 老化 61min、`run_after` 后移 2h（不可被 claim） | 触发 `memory.alert.pending_task_age`，`details={"value":3682,"window":"now","threshold":3600}`，含最老年龄与阈值；场景后清理构造任务 | 通过 |
| A5 | 停 API；2 张超期工单（`due_at<now`）；规则扫描证据审计老化超 2×周期 | 手动扫描 0.049s 触发 `memory.alert.rule_scan_missed`（`value=2, window=30m`）；恢复 API 后启动首扫补写扫描证据并将工单标记 `complaint_risk`；告警老化过冷却后复扫 `fired=[]`，无残留误报 | 通过 |
| A6 | 全部维护审计老化 25h（有业务活动、无维护记录） | 触发 `memory.alert.maintenance_silent`；观测端点 `maintenance.overdue=[ttl_purge, decay, embedding_retry, rule_scan]` 列表正确；场景后恢复审计时间 | 通过 |
| A7 | 先构造 10 次检索 30% fallback（小样本）；再补足 20 次其中 5 次 fallback（25%） | 小样本 75s 观察期不触发（≥20 次门控生效，宁漏不误）；达标后触发 `memory.alert.vector_fallback`，`details={"value":0.25,"threshold":0.2,"window":"24h"}` | 通过 |
| A8 | 配置 `AGENT_MEMORY_ALERT_WEBHOOK_URL` 指向 mock（9872） | mock 收到合规 JSON：`{"rule":"pending_task_age","tenant":"local","value":3719,"threshold":3600,"window":"now","at":"2026-10-26T19:24:59Z"}`；停掉 mock 后告警审计仍落库（19:26:00 R1），日志仅 `Memory alert webhook delivery failed` warning，19:27:05 下一周期扫描正常 | 通过 |
| A9 | `AGENT_MEMORY_ALERT_ENABLED=false` 重启，重复 A2 失败构造 | 任务 19:31:12Z 置 failed 后 150s 观察期告警审计计数恒为 10（零新增）；指标端点 17 个 section 照常返回（`tasks.failed_15m=2`） | 通过 |
| A10 | agent-alpha 5 次运行注入 2 次；agent-beta 6 次运行注入 6 次；写入/失败量差异化 | `agents` 维度分列正确：alpha 注入率 0.4、beta 1.0，写入量/失败量与库直查一致（含于 A1 的 42 项对账） | 通过 |
| A11 | 字面值方案（库迁移至 0040 无 `memory_injection_log`）因代码/模式版本耦合不可执行（`duration_ms` 列属 0042），如实记录；替代：head 模式下 `DROP TABLE memory_injection_log` | 注入指标按事件计数口径降级：`{"source":"events","avg_items":7.0,"by_section":{"flag":1,"profile":null,"preference":null,"event":2}}`，端点无报错（D3 探针 `to_regclass` 生效） | 通过（替代执行，见遗留 L-1） |
| A12 | 内嵌形态扫描周期 1min，多场景连续运行 | 19:09~19:42 间 8 条告警全部由 API 内嵌扫描器按周期自动落库；启动首扫（rule_scan）审计可见；心跳审计仅独立形态写入（设计如此）；时长以约 40 分钟多轮重启观察替代 1 小时连续浸泡（见遗留 L-2） | 通过 |

## 3. 故障演练计时记录

| 演练 | 执行过程与计时 | 判定 |
|---|---|---|
| 演练 1：Worker 宕机 | 独立 Worker（`AGENT_EMBEDDED_WORKER=false`）写入心跳审计 → kill 进程 → 心跳记录老化 31min → 独立形态扫描一轮（0.047s）同时触发 `pending_task_age`（value=3663s）与 `worker_heartbeat`（`value=31.0 > threshold=30, window=30m`）→ 重启 Worker 后 5min 内新心跳落库 → 清除条件并过冷却后复扫 `fired=[]`，无残留误报。真实形态时延上界 = 心跳间隔 300s + 30min 窗口 + 1 个扫描周期，满足 ≤30 分钟发现要求（构造老化即刻可判） | 通过 |
| 演练 2：embedding 服务异常 | 经真实管理 API 创建 embed profile（`11561124-61df-486e-88ef-0198edb51921` v1，base 指向 mock 9871）→ API 以向量形态重启（启动日志无降级告警）→ mock 下线，3 笔事件写入使 `embedding_failed` 积压 2→5→7→9 逐周期上升 → 19:41:34Z 触发 `memory.alert.embedding_growing`（`{"value":9,"window":"2 scans","threshold":7}`，连续两周期上升后第三读数触发）→ 恢复 mock 并重启，启动维护 `embedding_retry` 重试清零：积压 9→0，审计 `{"scanned":9,"succeeded":9,"failed":0,"result":"ok"}`，向量列回填 9 条 | 通过 |
| 演练 3：pgvector 不可用 | `AGENT_MEMORY_VECTOR_ENABLED=false` 下探针确认 `store impl: TsVectorStore / available(): text` → API 以强制文本形态重启 → 构造 5 笔 `mode=text` 检索事件 → 检索模式分布 `{"vector":14,"text":6,"keyword_fallback":5,"fallback_rate":0.2}` 正确展示降级构成。纯文本形态下 `keyword_fallback` 份额为 0，R4 构造型不触发（宁漏不误）；R4 触发路径已由 A7 演示 | 通过 |

## 4. 指标对账数据（A1 抽样 + 全量）

对账方式：库直查 SQL vs `GET /api/v1/observability/memory?window_hours={24,168}` 响应逐字段比对，共 **42 项全部一致**（双窗口）。抽样摘录：

| 指标 | 库直查 | API 响应 | 一致 |
|---|---|---|---|
| tasks.pending | 1 | 1 | ✓ |
| tasks.by_kind.conversation_summary (done/failed/avg_ms) | 2 / 1 / 500.0 | 2 / 1 / 500.0 | ✓ |
| extraction 24h runs/added/updated/pending/dropped/pii_masked | 3 / 6 / 3 / 2 / 1 / 3 | 同左 | ✓ |
| hit_rate customer_runs / injected_runs | 11 / 8 | 11 / 8 | ✓ |
| agents alpha 注入率 / beta 注入率 | 0.4 / 1.0 | 0.4 / 1.0 | ✓ |
| injection source / by_section | detail / 1,1,1,8 | detail / 1,1,1,8 | ✓ |
| governance 各 action 计数（4 类） | 2/2/1/4 | 2/2/1/4 | ✓ |
| search calls / empty | 10 / 2 | 10 / 2 | ✓ |

## 5. 业务指标验收

| 指标 | 目标 | 实测 | 判定 |
|---|---|---|---|
| 指标覆盖 | 十类全部可查且对账一致 | A1：十类分组齐全，42/42 对账一致（24h+168h） | 通过 |
| 告警发现时延 | ≤ 2 个检查周期 | A2：失败→告警约 47s（周期 1min）；演练 1/2 计时均达标 | 通过 |
| 告警误报率 | ≤ 20%（上线后首月观测期跟踪） | 验收期构造边界（小样本、冷却、纯文本形态、恢复后复扫）均零误报；首月跟踪留待上线后 | 通过（跟踪项） |
| 维护漏跑可发现 | 漏跑超 2 周期必告警 | A5（rule_scan_missed）、A6（maintenance_silent）均触发 | 通过 |
| 零新中间件 | compose 无新增服务 | `git diff main...HEAD -- compose.yaml deploy/ Dockerfile nexusdesk nexusdesk.ps1` 为空 | 通过 |

## 6. 合规核对（C1~C5）

| # | 核对项 | 执行与结果 | 判定 |
|---|---|---|---|
| C1（一票否决） | 告警审计与 webhook 载荷无记忆明文/PII/连接串/密钥 | 正则扫描 15 个 blob（14 条 `memory.alert.*` 审计 + 1 条 webhook 载荷）：哨兵文本「敏感内容样本ACC1」、CN 手机号、邮箱、连接串、Bearer、token 值、password/secret 键**零命中**；结构核验 `details` 键集合严格为 `{value, threshold, window}` | 通过 |
| C2（一票否决） | 告警检查不阻塞 claim 主循环（单轮 ≤5s） | 单轮扫描实测 0.042~0.049s（含一轮触发 2 条规则的 0.047s），远低于 5s；扫描器活跃期间任务 claim+处理同秒完成（A2、演练 2 多次观察），主循环无阻塞 | 通过 |
| C3 | 指标聚合限时间窗，无全表扫描 | EXPLAIN 抽核 `nexusdesk_accept`：Index Scan `memory_tasks_tenant_status`、`runtime_events_type_created`，Index Only Scan `runtime_runs_tenant_id_key`，无 Seq Scan（全量证据见 `06-test-report.md` C3 节，0043 租户索引迁移） | 通过 |
| C4 | `memory_alert_enabled=false` 可整体关闭 | 见 A9：关闭后失败任务零告警、指标照常 | 通过 |
| C5 | 观测指标与告警按租户隔离 | 租户 `other` 种子（pending+failed 任务及告警审计）在 `local` 视图零泄漏：`tasks.pending=1`、`by_kind failed=0`、告警列表 `[]` | 通过 |

## 7. 阈值默认值确认记录

代码默认（`backend/src/agent_platform/settings.py`）对照 FR-4 要求逐项确认：

| 配置项 | 代码默认 | FR-4 要求 | 确认 |
|---|---|---|---|
| memory_alert_enabled | true | true | ✓ |
| memory_alert_scan_interval_minutes | 15 | 15 | ✓ |
| memory_alert_cooldown_minutes | 60 | 60 | ✓ |
| memory_alert_pending_task_max_age_minutes | 60 | 60 | ✓ |
| memory_alert_pending_backlog_threshold | 500 | 500 | ✓ |
| memory_alert_vector_fallback_threshold | 0.2 | 0.2 | ✓ |
| memory_alert_webhook_url | ""（空） | ""（空） | ✓ |
| memory_alert_webhook_timeout_seconds | 5 | —（需求外新增，实现 FR-3 webhook ≤5s 超时约束） | ✓（新增项，已标记） |

模块常量复核（`alerting.py` / `worker.py`）：R1 窗口 15min ✓；R3 连续 2 次扫描上升 ✓；R4 小样本门控 20 次/24h ✓；R5 静默窗口 24h ✓；R6 窗口 = 2×规则扫描周期 ✓；R8 心跳间隔 300s / 缺失窗口 30min ✓。全部与 `02-requirements.md` 一致。

## 8. 遗留清单

| # | 级别 | 事项 | Owner | 期限 |
|---|---|---|---|---|
| L-1 | P3 | A11 字面值形态（迁移至 0040 运行当前代码）因代码/模式版本耦合不可执行，本次以 head 模式 DROP 表演证 D3 降级契约；建议将「注入降级形态验证方法」补注入运维文档 | 研发负责人 | 2026-11-03 |
| L-2 | P3 | A12 的 1 小时连续浸泡以约 40 分钟多轮重启观察替代；quickstart 环境恢复后补做 1h 连续浸泡冒烟 | QA | 2026-11-10 |
| L-3 | P3 | 验收环境以本地 uvicorn 内嵌/独立进程替代 Docker quickstart 双容器（本机 Docker 网络受限），等效性声明见 §1；环境恢复后冒烟复核 | 平台运维 | 2026-11-10 |
| L-4 | P3 | 验收中批量老化 UPDATE 使多条 pending_task_age 告警 `created_at` 相同（展示层噪音）；证据按审计 id 解读，无需修复 | QA | 记录即可 |

无 P0/P1/P2 遗留。

## 9. 结论与签字

**结论：有条件通过。**

- A1~A12 全部通过（A11 为授权替代执行，A12 时长替代执行）；
- 三项故障演练全部达标；
- 一票否决项 C1/C2 清洁通过，C3~C5 通过；
- 阈值默认值与模块常量全部确认无误；
- 遗留仅 4 项 P3 级执行覆盖/文档事项，均含 owner 与期限；误报率指标按方案留待上线后首月观测期跟踪。

本报告由 AI 验收代理执行并生成，结论以四方人工签字为最终生效条件。

| 角色 | 签字 | 日期 |
|---|---|---|
| 产品负责人 | AI 代理执行，待人工签字 | — |
| QA | AI 代理执行，待人工签字 | — |
| 研发负责人 | AI 代理执行，待人工签字 | — |
| 平台运维 | AI 代理执行，待人工签字 | — |
