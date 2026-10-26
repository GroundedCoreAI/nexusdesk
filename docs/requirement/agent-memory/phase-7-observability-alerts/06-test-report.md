# Phase 7 · 生产观测与告警 — 测试报告

> 状态：**复测通过**（首轮 3 个 P1 缺陷已全部修复并复测转绿；出口准则达成，仅验收阶段项诚实保留）
> 执行：2026-10-27，Task 5a（真实 PostgreSQL 全量功能测试）；复测同日（修复回合后）
> 依据：`04-test-plan.md`（P7-UT-01~11、P7-IT-01~13、P7-API-01~04、P7-FE-01~04、§8 出口准则）

## 1. 执行环境

| 项 | 值 |
|---|---|
| 分支 | `feat/memory-observability-alerts` |
| 首轮 commit | `b0fe1cd`（Phase 7 范围 `849d053..HEAD`）+ 性能测试 `0abed55` |
| 复测 commit | `87f0d50`（修复回合：`cfe550c` 测试 INSERT 补列、`4655a22` 租户索引 + 查询调整、`87f0d50` 性能测试种子改造） |
| 数据库 | PostgreSQL 17.11（Debian，aarch64），Docker 容器 `nexusdesk-pg17`（`pgvector/pgvector:pg17`），pgvector 0.8.7 |
| 测试库 | `nexusdesk_test`（复测时已迁移至 alembic head `0043_memory_tasks_tenant_index`）；迁移用例用 `nexusdesk_migtest` 派生随机库 |
| 后端运行时 | Python 3.11.9，pytest 9.1.1，pytest-asyncio 1.4.0（`backend/.venv`，uv 管理） |
| 前端 | Vite 7 dev server（:5173），Playwright Chromium headless |
| 环境变量 | `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nexusdesk_test`；`MIGRATION_TEST_DATABASE_URL=.../nexusdesk_migtest` |

说明：Phase 7 全部 PG 套件（`*_postgres.py`、迁移）在首轮系**首次在真实 PG 上执行**（此前无 `TEST_DATABASE_URL` 一律 skip）；pgvector 在场，vector 门控用例（检索 vector 腿、embedding 重试审计）实际运行。

## 2. 范围与原则对照

| 原则（04-test-plan §1） | 执行情况 |
|---|---|
| 1 数值对账 | 首轮对账主用例被缺陷 D1 阻塞；修复后复测 `test_p7_it_memory_summary_health_sections_reconcile` 通过——十类区段与库直查逐值一致，含 168h 窗口变体 |
| 2 时间类用例不等待 | 已落实：超龄/超期全部改库构造，告警手动触发单轮；复测 PG 套件 27 例 12.4s |
| 3 告警宁漏不误 | R3 重启重采样、R4 小样本门、R5/R6 豁免、R8 内嵌豁免单测全绿；PG 侧 R3 三周期上升、R4 超率触发、R5 心跳证据排除复测全部通过 |
| 4 告警零敏感数据 | 静态扫描零发现（§5）；动态专用用例 `test_alert_details_never_carry_content` 复测通过——种子明文"敏感内容样本"不出现在任何告警 details |
| 5 既有观测不破坏 | Phase 1-6 回归零非 Phase-7 失败（首轮 642 通过、复测回合全量 649 通过）；Phase 4 观测页前端 spec 通过 |

## 3. 结果总表（测试方案 ID 映射）

### 3.1 单元测试（P7-UT）

执行命令：`uv run pytest tests/test_memory_alerting.py tests/test_memory_observability_summary.py tests/test_memory_search_tool.py` → **36 passed in 0.29s**（含 search_tool 既有 9 例；首轮与复测结果一致）。

| 编号 | 实现用例 | 结果 |
|---|---|---|
| P7-UT-01 R1 任务失败 | `test_memory_alerting.py::test_r1_task_failed_truth_table` | PASS |
| P7-UT-02 R2 积压年龄 | `test_r2_pending_task_age_truth_table` | PASS |
| P7-UT-03 R3 embedding 增长 | `test_r3_rising_across_two_consecutive_scans_fires_on_third`、`test_r3_not_rising_or_zero_backlog_stays_quiet`、`test_r3_restart_resamples_from_scratch` | PASS |
| P7-UT-04 R4 降级率 | `test_r4_minimum_calls_gate`（率 25%/调用 25 触发；调用 15 不触发；率 10% 不触发） | PASS |
| P7-UT-05 R5 维护静默 | `test_r5_exemptions_and_fire` | PASS |
| P7-UT-06 R6 规则扫描漏跑 | `test_r6_exemptions_and_fire`、`test_scanner_interval_zero_disables` | PASS |
| P7-UT-07 R7 pending 积压 | `test_r7_pending_backlog_threshold`（恰等阈值不触发） | PASS |
| P7-UT-08 R8 worker 心跳 | `test_r8_standalone_only`（quickstart 内嵌豁免） | PASS |
| P7-UT-09 冷却 | `test_cooldown_active_pure_logic`（PG 端到端见 P7-IT-07） | PASS |
| P7-UT-10 duration_ms 记录 | 由 PG 用例 `test_memory_observability_postgres.py::test_p7_it_duration_ms_written_for_done_and_failed` 覆盖（done/failed/重试 requeue 三态均写耗时）；单测层无用例——worker 需真实引擎 | PASS（PG 层） |
| P7-UT-11 降级口径选择（D3） | `test_memory_observability_summary.py` 5 例：detail 四段拆分、无 run 无均值、events 降级合并 profile/preference 等 | PASS |

### 3.2 集成测试（P7-IT，真实 PG）

复测执行命令：`uv run pytest tests/test_memory_observability_postgres.py tests/test_memory_alerting_postgres.py tests/test_memory_observability_summary_postgres.py tests/test_memory_observability_migrations.py` → **27 passed in 12.42s**，零失败零跳过（首轮：20 passed / 5 failed；失败的 5 例根因均为测试代码原生 SQL 缺 NOT NULL 列，修复后全部转绿，见 §7）。

| 编号 | 实现用例 | 首轮 | 复测 | 备注 |
|---|---|---|---|---|
| P7-IT-01 任务健康指标 | `test_p7_it_memory_summary_health_sections_reconcile`（对账主用例）；`test_p7_it_duration_ms_written_for_done_and_failed` | FAIL / PASS | **PASS** | 对账主用例首轮被 D1 阻塞；复测各计数、最老年龄、by_kind avg/P95 与直查一致 |
| P7-IT-02 embedding 指标 | 同上对账用例；`test_p7_it_embedding_retry_audit_counts_outcomes` | FAIL / PASS | **PASS** | 重试审计 {scanned:2,succeeded:1,failed:1} 与汇总区段均对账一致 |
| P7-IT-03 检索模式与质量 | `test_p7_it_search_event_modes` | PASS | **PASS** | text/keyword_fallback/vector 三种 mode 实跑（pgvector 镜像，vector 腿未跳过），hits/returned 对账一致 |
| P7-IT-04 维护健康 | `test_p7_it_maintenance_audits_ttl_and_injection_purge`、`test_p7_it_maintenance_quiet_pass_writes_no_audit`、`test_p7_it_maintenance_failure_writes_failed_audit_and_reraises`、`test_p7_it_rule_scan_audit`、`test_p7_it_rule_scan_not_overdue_when_scan_disabled` | PASS | **PASS** | 逐 job 审计形状、静默 pass 零审计、失败审计 + 重抛、超期列表口径全部符合 |
| P7-IT-05 Agent 维度 | 对账主用例内 agents 区段 | FAIL | **PASS** | 首轮被 D1 阻塞；复测两 Agent 差异化流量注入率分别对账正确（写入量/失败量按既定降级口径为 None） |
| P7-IT-06 告警端到端 | `test_alert_task_failed_writes_audit_and_cooldown_suppresses` | PASS | **PASS** | R1 条件→单轮扫描→`memory.alert.task_failed` 落库，details 恰为 {value:1,threshold:0,window:"15m"} |
| P7-IT-07 告警冷却 | 同上用例冷却段（第二轮扫描零新增） | PASS | **PASS** | 冷却窗过期再触发由单测真值表覆盖 |
| P7-IT-08 R4/R5/R6 触发 | R4：`test_r4_vector_fallback_fires_above_rate_with_min_calls`；R5：`test_r5_maintenance_silent_fires_with_activity_and_is_exempt_when_idle`、`test_r5_heartbeat_rows_are_not_maintenance_evidence`；R6：`test_r6_exempt_without_overdue_tickets`、`test_r6_fires_with_overdue_tickets_and_no_evidence`；附 R3 PG：`test_r3_rising_backlog_across_three_scans_fires` | R4 FAIL / R3 FAIL；R5、R6 PASS | **全部 PASS** | R4 首轮被 D1、R3 被 D2 阻塞；复测 R4 值 0.25/阈值 0.2、R3 三周期值 3 均落库正确 |
| P7-IT-09 webhook | `test_webhook_payload_shape_and_failure_isolated` | PASS | **PASS** | 载荷恰为 {rule,tenant,value,threshold,window,at}、timeout=5；发送方抛 TimeoutError 扫描照常完成、审计仍落库 |
| P7-IT-10 总开关 | `test_master_switch_off_writes_nothing`（+ 单测 `test_scanner_master_switch_off_never_touches_db`） | PASS | **PASS** | 关闭后不扫描、无审计、无心跳；指标接口回归通过 |
| P7-IT-11 告警无敏感数据 | 动态：`test_alert_details_never_carry_content`；静态：全量告警/webhook 载荷代码路径扫描（§5） | 动态 FAIL（D2 阻塞）/ 静态 PASS | **PASS** | 复测动态用例通过：种子明文不出现在任何告警 details，且 details 键集合恰为 {value,threshold,window} |
| P7-IT-12 迁移回填 | `test_memory_observability_migrations.py`：`test_0042_adds_duration_ms_and_downgrade_drops_it`；复测新增 `test_0043_adds_tenant_indexes_and_downgrade_drops_them` | PASS | **PASS** | 0042 仅加 `duration_ms`（D1 调整：created_at 自 0030 已在，无需回填 run_after）；0043 三个索引 upgrade/downgrade 随机库往返通过 |
| P7-IT-13 观测接口性能 | `test_memory_observability_perf_postgres.py::test_p7_it13_observability_performance_at_10k_scale`（本报告交付物，`0abed55` 新增、`4655a22`/`87f0d50` 随修复演进） | FAIL（EXPLAIN 腿） | **PASS** | 复测响应时间与 EXPLAIN 双腿均达标，数据见 §4 |

### 3.3 API 测试（P7-API）

| 编号 | 实现用例 | 结果 | 备注 |
|---|---|---|---|
| P7-API-01 `/observability/memory` 扩展 | `test_p7_it_memory_summary_empty_tenant`（新增十类字段结构与默认值）+ 复测对账主用例（字段值）；既有字段契约由 Phase 4 回归套件与前端 spec 守护 | PASS | 首轮字段值对账受 D1 阻塞，复测解除 |
| P7-API-02 `/observability/memory/alerts` | `test_p7_it_memory_alerts_endpoint`、`test_p7_it_memory_endpoint_window_validation` | PASS | 倒序、window_hours 过滤、1-168 校验 422、未认证 401、非告警审计不混入 |
| P7-API-03 无 Phase 6 形态 | 单元 D3 用例（`test_injection_events_degrade_lumps_profile_and_preference` 等，`source=="events"` 口径） | PASS（单元级） | 服务层 `to_regclass` 探测分支有单元覆盖；无 PG 级"物理删表"用例 |
| P7-API-04 租户隔离 | 结构性覆盖：Phase 7 全部 SQL 带 `tenant_id` 过滤；共享库存在其他租户残留数据时 empty-tenant/精确计数断言通过 | 部分覆盖 | 无专门跨租户负向用例，建议后续补一例（P3 建议项，不计缺陷） |

### 3.4 前端测试（P7-FE，Playwright，dev server :5173）

执行命令：`npx playwright test tests/memory-observability.spec.ts tests/memory.spec.ts` → **14 passed (22.6s)**。前置：`npm run typecheck`、`npm run check:i18n`（1658 条译文四语言齐全）、`npm run build` 全绿。

| 编号 | 实现用例 | 结果 | 备注 |
|---|---|---|---|
| P7-FE-01 分组卡片 | `memory-observability.spec.ts` "renders grouped health sections" + "window switch refetches" | PASS | 七组卡片（任务健康/Embedding/检索/维护任务/Agent 维度/记忆注入/记忆质量）渲染、百分比/小数格式化、窗口切换带 `window_hours=168` 重取 |
| P7-FE-02 维护超期强调 | 同上首个用例 | PASS | 超期横幅"以下维护任务已超期：规则扫描" + 红色单元格断言 |
| P7-FE-03 告警列表 | "memory alerts list renders rule labels and em dash for null values" | PASS | 规则中文标签、当前值/阈值渲染、null 值 em dash；空态为弱覆盖（alerts=[] 时页面正常渲染无报错，无专门空态元素断言） |
| P7-FE-04 quickstart 形态 | — | **DEFERRED** | 属 Task 5b 验收范围（quickstart 双容器 TSVECTOR 形态），本阶段不执行 |

另：容器化故障演练类条目（worker 宕机心跳告警、内嵌 Worker 周期执行等，04-test-plan §2 "quickstart 双容器"行）同属 Task 5b 验收范围。

## 4. P7-IT-13 性能数据（复测实测）

数据规模（`87f0d50` 起为多租户生产形态：目标租户 + 40 个小诱饵租户，使租户过滤的选择性接近生产分布；种子后 `ANALYZE`）：

| 表 | 目标租户 | 诱饵（40 租户合计） | 合计 |
|---|---|---|---|
| `memory_tasks` | 12,000 | 30,000（750/租户） | 42,000 |
| `runtime_runs` | 500 | 25,000（625/租户，目标约占 2%） | 25,500 |
| `runtime_events` | 12,000（500 runs × 24） | 600,000 | 612,000 |
| `audit_records` | 50（memory.alert.*） | 20,000（500/租户） | 20,050 |

(a) 响应时间：每接口 1 次热身后连续 20 次计时调用，全部 ≤ 2s 上限（复测实测）：

| 接口 | median | max | 判定 |
|---|---|---|---|
| `memory_summary`（24h 窗） | 12.8 ms | 19.2 ms | PASS |
| `memory_summary`（168h 窗） | 28.9 ms | 31.7 ms | PASS |
| `memory_alerts`（24h 窗） | 1.5 ms | 1.9 ms | PASS |

（修复回合验证-run 的最大值同为毫秒级：22.5 / 35.9 / 2.4 ms；两回合均远优于 2s 上限。）

(b) EXPLAIN（六条关键聚合逐条断言大表无 Seq Scan）：**复测全部达标**——0043 迁移补 `memory_tasks(tenant_id,created_at)`、`memory_tasks(tenant_id,status)`、`runtime_events(type,created_at)` 三个索引，且活动探测 EXISTS 拆分为两个可走索引的分支：

| 查询 | 复测计划 | 判定 |
|---|---|---|
| tasks 区段主聚合 | Bitmap Index Scan `memory_tasks_tenant_status` | PASS |
| tasks by_kind（窗口 + 状态过滤） | Bitmap Index Scan `memory_tasks_tenant_created` | PASS |
| maintenance 活跃度 EXISTS | 两个 Index Only Scan（`memory_tasks_tenant_created` + `memory_tasks_tenant_status`） | PASS |
| search_modes/quality 联表 | Bitmap Index Scan `runtime_events_type_created` + Index Only Scan `runtime_runs_tenant_id_key` | PASS |
| maintenance 区段（audit_records） | Bitmap Index Scan `audit_tenant` | PASS |
| alerts 列表（audit_records） | Bitmap Index Scan `audit_tenant` | PASS |

对照首轮：tasks 三条聚合为 (Parallel) Seq Scan on memory_tasks、检索联表为 Parallel Seq Scan on runtime_events（详见 §7 缺陷 D3 闭环记录）。首轮响应时间其实亦达标（median ≤ 39ms），缺陷在于计划形状违反设计准则；修复后六条查询全部索引服务，万级规模 median ≤ 29ms。

## 5. 敏感数据扫描（P7-IT-11 / 原则 4 证据）

静态扫描范围（告警与载荷全部代码路径）：

- `modules/memory/alerting.py`：`Alert` 仅 {name,value,threshold,window}；审计写入 kwargs 仅 value/threshold/window；webhook 载荷固定 6 键 {rule,tenant,value,threshold,window,at}；`collect()` 全为 count/EXISTS 窗口聚合，不 SELECT 任何 content/payload 列。
- `modules/memory/worker.py`：`memory.maintenance.completed` details 为 {job,result,stats}（stats 全计数：expired/purged/scanned/succeeded/failed/marked/flags_removed）；`.failed` 为 {job,error=str(exc)[:500]}（截断；异常源自 gateway/存储层，不含记忆明文——embedding 重试读取 content 仅用于嵌入计算，不写入任何审计）；心跳审计 stats 为空 dict。
- `modules/observability/service.py`：`memory_alerts` 仅回读 details 的 value/threshold/window 三键。
- 动态断言（复测通过）：`test_alert_details_never_carry_content` 断言种子明文"敏感内容样本"不出现在任何告警 details、details 键集合恰为 {value,threshold,window}；R1 审计 details 恰等于 {"value":1,"threshold":0,"window":"15m"}；webhook 载荷键集合恰为上述 6 键。

结论：**零敏感数据，动态 + 静态双重确认**（首轮动态专用用例受 D2 阻塞，复测已闭环）。

## 6. 回归结果（Phase 1-6 全量 + Phase 7）

| 回合 | 命令 | 结果 |
|---|---|---|
| 首轮（`b0fe1cd` + `0abed55`，DB head 0042） | 全量 `uv run pytest`（带两个环境变量） | 642 passed, 5 failed, 3 skipped，195.9s（共 650 项；性能测试另计） |
| 复测（`87f0d50`，DB head 0043） | 同上（修复回合执行） | **649 passed, 0 failed, 3 skipped，207s** |
| 复测（本报告执笔时复核） | Phase 7 PG 四件套 | **27 passed in 12.42s** |
| 复测（同上） | 性能测试 `-s` | **1 passed in 52.63s**（多租户种子造数占主要耗时） |

- Phase 7 用例总数 54 例（alerting 19、summary 5、search_tool 新增 3、observability_postgres 7、alerting_postgres 12、summary_postgres 6、migrations 2、perf 1）。
- 首轮 5 个失败全部位于 Phase 7 新增测试文件（缺陷 D1/D2），**全程零非 Phase-7 失败**——Phase 1-6 无回归。
- 3 个 skip 均为既有约定，与 Phase 7 无关：`test_knowledge_workspace.py`（opt-in 真实 Milvus）、`test_memory_events_postgres.py` ×2（降级腿要求无 embedding 列的 plain PG 库，Phase 3 双形态矩阵惯例；本库有 pgvector，反向腿已实跑）。
- `uv run ruff check src tests`：All checks passed（首轮与复测均绿）。
- 已知的前端 e2e 既有失败（tickets-antd 2 例、login 布局 1 例、E2E_CHROME_PATH 问题）未在本次范围执行；本次目标两个 spec 文件 14 例全绿。

## 7. 缺陷清单（全部闭环）

| 编号 | 级别 | 缺陷 | 首轮证据 | 修复与复测 |
|---|---|---|---|---|
| D1 | P1 | Phase 7 PG 测试 3 处原生 `INSERT INTO runtime_runs` 漏写 NOT NULL 列 `queue_expires_at`（0001 迁移即存在）：`test_memory_alerting_postgres.py:97`、`test_memory_observability_summary_postgres.py:81`、`:370` | `NotNullViolationError: null value in column "queue_expires_at"`；psql 最小复现同错；阻塞 3 例 | **已关闭**——`cfe550c` 补齐 INSERT（参照 `test_memory_injection_postgres.py:89` 惯例）；复测 `test_r4_vector_fallback_*`、两个 summary 对账用例转绿 |
| D2 | P1 | `test_memory_alerting_postgres.py::make_pending_item` `INSERT INTO memory_items` 漏写 NOT NULL 列 `customer_id`（0035 迁移引入） | `NotNullViolationError: null value in column "customer_id"`；psql 最小复现同错；阻塞 2 例 | **已关闭**——`cfe550c` 同 commit 修复（先建 `memory_customers` 行再引用）；复测 `test_alert_details_never_carry_content`、`test_r3_rising_backlog_*` 转绿 |
| D3 | P1 | 观测聚合在 `memory_tasks` 上结构性全表扫描（tasks 主聚合、by_kind、maintenance 活跃度 EXISTS；告警 `collect()` 同型），`runtime_events` 联表 planner 自选 Seq Scan；根因：无 tenant/created_at 索引 | 首轮 EXPLAIN：Parallel Seq Scan on memory_tasks ×3、on runtime_events ×1；响应时间万级 ≤ 50ms 未达"拖垮库"，故定 P1 不定 P0 | **已关闭**——`4655a22` 新增迁移 0043（`memory_tasks(tenant_id,created_at)`、`(tenant_id,status)`、`runtime_events(type,created_at)`）并拆分活动探测 EXISTS 为两个索引可走分支；`87f0d50` 将性能测试种子改为 40 小诱饵租户的生产形态消除计划器硬币翻转。复测六条 EXPLAIN 全索引服务（§4），性能测试转绿 |

定级说明：D1/D2 为测试代码缺陷（生产逻辑无涉），但首轮阻塞数值对账与敏感数据专用用例，按 P1 处理；D3 违反技术设计明确的 explain 准则，同按 P1。三者均不涉及敏感数据泄露与主循环阻塞（P0 两项专项核查均为阴性）。**当前无开放缺陷。**

## 8. 出口准则核对（04-test-plan §8）

| 准则 | 结论 | 说明 |
|---|---|---|
| 全部用例通过 | **达成** | 复测：单元 36 + PG 27 + 性能 1 全绿；全量回归 649 passed / 0 failed |
| AC-1~AC-12 复现通过 | 达成（测试范围内） | AC-1/2/3/4/5/6/7/8/9/10 均有通过用例支撑（AC-1 对账主用例、AC-4 R2、AC-7 R4 含小样本门、AC-10 agents 区段复测均绿）；AC-11 单元级通过；**AC-12 属 Task 5b 验收**（quickstart 双容器） |
| 告警零敏感数据（阻断项） | **达成** | 静态扫描零发现 + 动态专用用例复测通过（§5） |
| 不阻塞主循环（阻断项） | 达成 | webhook 失败仅记日志（PG 用例实跑）；扫描/心跳均有 due 闸门与 attempt 戳 |
| 指标对账一致（阻断项） | **达成** | 复测对账主用例 + 168h 窗口变体通过，逐值与库直查一致 |
| Phase 1-6 回归套件全绿 | 达成 | 649 passed，零非 Phase-7 失败，3 skip 均为既有环境约定 |
| 无 P0/P1 未关闭 | **达成** | D1/D2/D3 全部修复并复测闭环（§7） |

**总结论**：出口准则全部达成。唯一诚实保留项为验收阶段（Task 5b）范围：P7-FE-04 quickstart TSVECTOR 形态与容器化故障演练（AC-12 等），非本轮测试缺陷。本阶段可进入 Task 5b 验收。

## 9. 附录：执行命令速查

```bash
# Phase 7 单元套件（36 passed）
uv run pytest tests/test_memory_alerting.py tests/test_memory_observability_summary.py tests/test_memory_search_tool.py
# Phase 7 PG 套件 + 迁移（复测 27 passed；首轮 20 passed / 5 failed）
uv run pytest tests/test_memory_observability_postgres.py tests/test_memory_alerting_postgres.py \
  tests/test_memory_observability_summary_postgres.py tests/test_memory_observability_migrations.py
# 全量回归（首轮 642 passed / 5 failed / 3 skipped；复测 649 passed / 0 failed / 3 skipped）
uv run pytest
# 性能（P7-IT-13；首轮 EXPLAIN 腿 FAIL，复测 1 passed）
uv run pytest tests/test_memory_observability_perf_postgres.py -s
# Lint
uv run ruff check src tests
# 前端
cd frontend && npm run typecheck && npm run check:i18n && npm run build
npx playwright test tests/memory-observability.spec.ts tests/memory.spec.ts   # 14 passed
```
