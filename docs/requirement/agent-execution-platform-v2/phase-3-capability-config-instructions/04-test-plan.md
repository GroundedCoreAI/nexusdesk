# Phase 3 · 能力、配置与指令 — 测试方案

> 状态：待实施（开发完成后执行；当前无测试结果、未创建 06）
> 创建：2026-11-02
> 修订：2026-11-13（第三批收口：T7/T8 设计裁定落测试——新增 P3-UT-27/28 与 P3-IT-21/22，并扩展 P3-IT-03/08/11/19、P3-UT-21/22 判据（含 P3-IT-08 的 5 类×列负控矩阵与 `declared_capabilities_snapshot` 列重复项结构性不可表达的例外登记）；对应 R-42～R-52）
> 修订：2026-11-13（第二批收口判据登记，本轮新增裁定 R-40/R-41（其判据落 P3-UT-16/17）：P3-UT-17 写明 parity 比较面（消息序列＋Engine 返回值＋事件 `(kind, data)`，仅排除 Engine 自计 `duration_ms`）、P3-UT-18 的"业务渲染一次"改由结构性保证承载并废弃计数端口式断言、P3-UT-19 登记两快照码唯一字面量定义点与 `_ERROR_MAP` 未登记的 T7 硬门禁、并写明 `prepare_instructions` 的 DTO 违规不回泄 `ValidationError`）
> 修订：2026-11-13（T6/T9 收口：修订头失败注入口径改准确、§2 增 PG skip 按机制归因、P3-UT-14 双向负控与 P3-UT-19 错误映射判据、P3-IT-08 写屏障清洗闸负控、P3-IT-19 由 08 T7/T8 认领、P3-CM-08 写死 zh-* 文案判据与范围外例外、§6.1 登记 P3-FE 编号与映射；对应 R-27/R-28/R-29/R-30/R-31/R-33/R-34/R-36/R-37/R-38）
> 修订：2026-11-13（T5 返工冻结点写入 P3-UT-13/15、P3-IT-06/07/08/18、P3-CM-06：决定性单类限额断言、序列化二次校验、写屏障受控 outcome、失败注入点为"UPDATE 已在服务端执行、异常发生在 COMMIT 之前"（before_execute 注入不算）、全文 SQL 静态门禁）
> 修订：2026-11-13（新增 P3-UT-26/P3-IT-20 与 §6.1 M3 声明式门控场景，对应 03 §7.4/R-25）
> 修订：2026-11-13（T4 返工裁定 R-17～R-22：受信 policy revision 入口、capability settings 落点与 TTL 下界、Effective 唯一投影、Available 收窄不可旁路）
> 修订：2026-11-13（T4 规格评审澄清 required capability missing 语义边界，新增 P3-UT-23，对应 R-16）
> 修订：2026-11-12（小团队证据复用、真实 PG、启动屏障、422 审计、四语言与 C11）
> 依据：`02-requirements.md`（FR-1–FR-9、AC-1–AC-11）、`03-technical-design.md`

## 1. 测试范围与原则

**范围**：AgentConfig 兼容/canonical diff、Registry metadata、类型化配置、Declared/Available/Policy/Effective、可信 probe/policy/cache、只读预览、五快照、Instruction Provider、React Summary/Memory、迁移 `0058_agent_execution_metadata`、双开关与回滚。

**原则**：

1. 以 Phase 0 实测和当前代码为基线；focused baseline 163 passed / 5 skipped 只是开发入口，不代表上游正式验收或全量通过。
2. Phase 3 off 必须保持部署原 Phase 2 on/off 行为；on+orchestrator off 失败关闭；任何 off 非 React 均明确拒绝。
3. 历史 NULL、无 Engine、无 Summary/Memory、默认等价 diff 均有独立回归。
4. 伪造能力/策略、额外字段、跨租户、嵌套秘密、超限与 DB 故障必须覆盖；**422 本身不等于安全审计**。
5. 快照屏障中的 start 指 `Adapter.start`/runner/Runtime 副作用，不改变公开 `run.started` 顺序。
6. probe 过期、缓存失效和 Run 超时使用 fake clock/可控替身，不靠长时间等待；决策重放不调用真实模型/工具。
7. UT/IT/CM、CI、PG、Playwright 原始证据直接供 A/C 引用；环境不可用保持 `pending_env`，不删除硬门禁。

## 2. 环境、数据与命令约定

| 环境 | 用途 |
|---|---|
| 纯单测 | normalizer、schema、能力求交、cache key、denylist、Provider 与 preview DTO |
| 独立 pgvector PostgreSQL + pytest fixture | 草稿/发布/Run/快照、并发、跨租户、迁移和终态；默认起容器实测 |
| Phase 1 LocalTestAdapter + Phase 2 测试编排器 | 无外部 Engine 的 fresh Adapter、屏障、事件、ack 与终态 |
| mock/demo 模型 + MemoryInjection 替身 | React 消息、Summary/Memory、单次渲染和写回兼容 |
| disposable 迁移库 | 从动态确认前驱 upgrade/downgrade；不连接生产 |
| 前端现有工具链 | typecheck、`check:i18n`、build、targeted Playwright；无组件测试 runner |

数据使用 Phase 0 授权脱敏样本和版本化 fixture，另建两个 tenant 与多个 business/workspace scope。声明、probe、policy、Provider 均为确定性替身；持久化失败在 Adapter mock 前注入。每个用例清理 Run/版本/审计，不共享可变策略。

当前协调环境已启动 `nexusdesk-phase3-pg`（127.0.0.1:55433）且基线 `0057_industry_pack_runtime` upgrade 成功；实施子代理必须自行重验容器、head 和目标提交。随机凭据只在权限 600 的 `/tmp/nexusdesk-phase3-pg.env`，禁止复制到仓库/文档/报告。Alembic 使用 `AGENT_DATABASE_URL`，pytest 使用 `TEST_DATABASE_URL`：先加载 env，再显式 `AGENT_DATABASE_URL="$TEST_DATABASE_URL"` 并设置临时 `AGENT_API_TOKEN`；此前只设 TEST 导致默认 5432 拒绝属于已纠正环境错误，不是产品缺陷。

**PG skip 归因口径（06 直接引用，禁止照抄 skip 文案）**：`-m postgres` 选择下的每个 skip 必须按**机制**归类。①凡复用 `backend/tests/test_ticket_migrations.py` 的 `migration_database` fixture 的迁移用例（现有 18 个 `*_migrations.py` 通过 `from test_ticket_migrations import migration_database` 复用），其文案 `Requires a test PostgreSQL role with CREATEDB` 只代表 **opt-in 变量 `MIGRATION_TEST_DATABASE_URL` 未提供**，不代表角色缺 `CREATEDB`（协调环境实测 `rolcreatedb=true, rolsuper=true`）；记为 `pending_env`（环境选择缺口），不得写成产品缺陷，也不得写成"角色权限不足"。②文案含 `Set TEST_DATABASE_URL ...` 的 skip 同理归因于 `TEST_DATABASE_URL` 未提供。③`needs the pgvector-migrated database`/`embedding column` 类归因于目标库缺 pgvector/embedding 列。④Milvus、seeded quickstart 等显式 opt-in 用例归因于对应开关未开。⑤必须登记的不对称：`backend/tests/test_agent_execution_phase3_migration.py` 自带 fixture 读 `TEST_DATABASE_URL` 且不做角色能力探测，若角色真缺 `CREATEDB` 它会在 `CREATE DATABASE` 处 **ERROR 而非 skip**；该文件报 error 时既不得按 skip 归因，也不得据此反推角色权限。

命令从仓库根执行（具体受影响测试路径由 T2–T10 补齐）：

```bash
uv run --directory backend ruff check src tests
uv run --directory backend ruff format --check <仅Phase3新增/修改的Python文件>
uv run --directory backend python ../scripts/check_architecture.py
uv run --directory backend alembic heads
uv run --directory backend pytest <受影响测试>
cd frontend && npm run typecheck && npm run check:i18n && npm run build
cd frontend && npx playwright test tests/agent-execution-config.spec.ts
```

全量 pytest 统一由 CI 在 push/PR 执行。全树 `ruff format --check src` 当前受无关 Memory seed 既有差异影响，06 必须记录该基线边界；Phase 3 只保证本阶段 Python 文件 format，不修改无关文件，也不冒称全树 format 成功。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P3-UT-01 | 缺少 `engine/react` 的旧配置规范化 | 得到 `react/native/v1`，旧字段等值，输入不变 | FR-1；AC-1 |
| P3-UT-02 | 新旧 React 别名同值 | 接受并输出单一 canonical 值 | FR-1、FR-2；AC-1、AC-2 |
| P3-UT-03 | 新旧 React 别名异值 | 拒绝并指出冲突字段，不静默选择 | FR-2；AC-2 |
| P3-UT-04 | 未知三元组、latest、额外字段与自由字典 | 全部拒绝，Registry 不被绕过 | FR-2；AC-2 |
| P3-UT-05 | Profile ID/version 单独出现、轮次越界、disabled 未知/重复 | 严格拒绝或按明确规则去重，边界不放宽 | FR-2、FR-4；AC-2 |
| P3-UT-06 | Declared=true 但部署缺失/版本不兼容 | Available=false 且有稳定原因，Declared 不改写 | FR-3；AC-3 |
| P3-UT-07 | probe 超时、异常与缓存命中/失效 | 有界不可用；键完整，声明变化旧值失效，无异常原文 | FR-3；AC-3 |
| P3-UT-08 | `workspace_required=true` 且无 Workspace | Available=false，必需能力缺失阻止启动 | FR-3；AC-3 |
| P3-UT-09 | 任一层拒绝后下层允许 | Effective=false，记录全部决定，单调收窄 | FR-4；AC-4 |
| P3-UT-10 | 未知能力、未知策略版本、缺失策略源 | 不默认授权；最小权限或配置错误拒绝 | FR-4；AC-4 |
| P3-UT-11 | ExecutionRequest/公开 RunRequest 伪造能力层 | 严格拒绝，服务端对象不采用客户端值 | FR-5；AC-5 |
| P3-UT-12 | tenant/actor 与认证上下文不一致 | 不信请求字段，使用可信上下文并记录越权 | FR-5；AC-5 |
| P3-UT-13 | 快照缺字段、不可序列化或单类超限；`model_copy` 绕过验证器 | 校验失败，屏障不通过；五类分别限 64KiB 默认（决定性断言：预算＝最大单类时整体成功且五者之和＞预算，只有超限那一类被拒）；序列化对 canonical 文本二次严格校验，缺项/重复项/乱序/available↔reason 矛盾均拒 | FR-6；AC-6 |
| P3-UT-14 | 快照嵌套 Token/API Key/raw Memory/宿主路径 | 任意深度写入前拒绝，日志/错误无原文；**双向负控**：合法形态必须全部通过（本仓真实 tenant/workspace 标识形态 `local` 与 slug 形、URL、相对路径、中文业务文本、全角标点），非法形态逐类被拒（凭据前缀、内嵌口令的 URL、`~/`、以 `/` 或 `./`/`../` 开头、Windows 盘符）；非 slug 且以分隔符开头的 tenant_id 使五快照整批 `snapshot_denied_host_path`（path 末段 `tenant_id`）并导致 `Adapter.start=0`，该部署前置须有显式用例（03 §5.2、R-33） | FR-6；AC-6 |
| P3-UT-15 | 重复序列化与只读决策重放 | 键/版本/原因稳定，不改快照、不调用 Engine；重放提供语义级保证（严格再校验＋身份一致），美化格式但语义相同按设计接受，不承诺逐字节防篡改；入口接受 `str \| Mapping`，类型误用与载荷缺失的错误码可区分 | FR-6；AC-6 |
| P3-UT-16 | React 空 Summary/Memory 与开关关闭 | 不生成空消息，保持基线序列 | FR-7；AC-7 |
| P3-UT-17 | Summary、Memory、组合及历史截断 | System→Summary→Memory→history→user 完全一致；parity 比较面为**消息序列 + Engine 返回值 `(output, history, dropped)` + 事件 `(kind, data)` 全等**，其中事件 data 仅排除 Engine 自计的 `duration_ms`（`round`/`usage`/`first_token_ms`/`tool_calls`/`gateway_call_id` 均参与比较，prepared 路径不得在消息序列相同的前提下改变一次 Run 的对外报告面） | FR-7；AC-7 |
| P3-UT-18 | 测试 Provider 使用不同格式 | "业务渲染一次"由**结构性保证**承载，计数端口式断言（如 `summary_calls == 1`，其计数不可能变化）已废弃：Memory 端口无法进入 `InstructionInput` 或 `prepare_instructions`（传入即失败）、两种 payload 递归扫描均不含活动对象、`InstructionInput` 字段集合钉死为 03 §6 的九项；同一输入两次 `prepare` 产出相等 payload，原生格式不强制 ReAct 化 | FR-7；AC-8 |
| P3-UT-19 | 未知 Provider、重复上下文或契约错误 | start 前失败，不降级 Provider；`details` 只含稳定 `operation/field` 标识符、不回显被拒值；契约保持同步签名且 payload 为 JSON 原生结构（`tuple`/`set` 在 strict 下即拒）；`agent_snapshot_required`/`agent_snapshot_invalid` 经 `error_mapper` 归 INVALID_REQUEST 类，不得出现 `internal_error`（T7 接线后由本项与 P3-IT-13 同族用例断言）；两码的唯一字面量定义点是 `runtime_factory.AGENT_SNAPSHOT_REQUIRED`/`AGENT_SNAPSHOT_INVALID` 常量，测试只引用常量并按触发条件钉住取值，且**当前仍未登记** `adapters/react/error_mapper.py` 的 `_ERROR_MAP`——未登记即经 `_ERROR_MAP.get(code, _INTERNAL_ERROR)` 降级为 `internal_error`，属 T7 硬门禁（R-30）；`prepare_instructions` 的 DTO 违规不再外泄 pydantic `ValidationError`，统一为 `ConfigurationError(operation="instruction_prepare", field=<被拒字段>)`、丢弃 `__cause__` 且不回显被拒值 | FR-7；AC-7、AC-8 |
| P3-UT-20 | FR-9 settings 默认、覆盖与非法边界（含 R-18 新增字段与 R-19 严格下界） | 默认关闭，覆盖生效，非法超时/缓存/大小/并发/容量/重试/刷新/部署身份拒绝；两个 `*_cache_seconds=0` 被拒，Phase 3 on 时 `warm_refresh ≥ min(TTL)` 被拒 | FR-9；AC-10 |
| P3-UT-21 | canonical diff 与 Registry metadata 校验 | 默认补齐无 diff；真实变化保留；factory 调用计数证明草稿不实例化 Adapter；standalone 与 production 镜像按 R-45 改为"除 `policy_version` 外逐字段相等 + 两侧派生来源各自钉住（生产==settings 值、standalone==settings 字段默认值）"，其余 14 字段强度不降 | FR-1、FR-2；AC-1、AC-2 |
| P3-UT-22 | preview 白名单、cache key 与 warmer 生命周期 | 无内部快照；key 完整；未预热/过期不可用，后台成功才可用，hot path 不 probe（指 `resolver.resolve()`；Run 屏障的一次有界 `warm()` 不违反本条），preview 永不 `await` warm，关闭无任务泄漏；off 时 composition 不构造子系统（返回 None）故端口调用计数恒 0 | FR-3～FR-5；AC-3～AC-5 |
| P3-UT-23 | 原因码归类：基础设施不可用类 vs 策略收窄类（R-16） | missing/准入阻断仅含 probe_unavailable/probe_timeout/probe_stale/workspace_unavailable/policy_unavailable；仅 not_declared 或仅 platform/tenant/agent/execution 收窄时准入放行、Effective=false 且快照留痕 | FR-3、FR-4；AC-3、AC-4 |
| P3-UT-24 | policy revision 受信来源与回显（R-17） | key/context 的 revision 来自 provider 自身 `current_revision`，前进即换 key；provider 回显不一致记为 error→`policy_unavailable`；读取异常映射 `execution_policy_unavailable`，绝不默认 0；请求 DTO 不含 `policy_revision` | FR-3、FR-4；AC-3、AC-4 |
| P3-UT-25 | Effective 唯一投影与 Available 收窄不可旁路（R-21/R-22） | `effective_capability_flags` 恒 11 键、False 不省略；`effective_capability_views` 三元组齐全且按 `CAPABILITY_ORDER`；缓存条目 `workspace_required=true` 而端口 None/不可用时 `resolution.available` 该项 false+`workspace_unavailable`；快照构造只接受 `CapabilityResolution` | FR-3、FR-5、FR-6；AC-3、AC-5、AC-6 |
| P3-UT-26 | `GET /agents/execution-config-flags` strict DTO 与零副作用（03 §7.4） | 响应恰含 `execution_phase3_enabled/execution_orchestrator_enabled` 两布尔且逐字匹配 settings、`extra=forbid`；调用只读 settings，probe/Adapter/Run/缓存读取调用计数恒为 0；全 off 与 on+orchestrator-off 两态均正常返回而非 `execution_phase3_disabled` | FR-8、FR-9；AC-9、AC-10 |
| P3-UT-27 | 生产受信端口单元形态（`capability/production.py`，R-42/R-44） | probe 只读 `registry.metadata().declared` 且不调 factory/`adapter.get_capabilities()`；回显 probe_id/probe_version 与三元组；`observed_at` 来自注入时钟且年份合理；`deployment_digest` 稳定且非 `UNOBSERVED_DIGEST`；`PlatformDefaultPolicyProvider.current_revision` 在同一作用域两次读取相等、不抛、无 I/O；`layer_versions` 四项齐全；`NoTrustedWorkspaceGeneration` 恒返回 None | FR-3、FR-4；AC-3、AC-4 |
| P3-UT-28 | composition 子系统接线与生命周期（R-46/R-49） | `ports=` 是唯一注入缝（settings/env 不能选择端口）；off 时子系统构造函数返回 None 且端口调用计数恒 0；warm targets 数==生产 Registry 中 enabled 注册数且每个 target 可被 `metadata()` 命中、scope 只到部署级；`warmer.start()` 紧随 `extensions.start_all`、`finally` 内第一个 aclose，次序 warmer→resolver→contributions→extensions→engine→listener/notifier；时钟为单一 POSIX wall-clock，`time.monotonic` 进该路径即失败；ready 不等 probe | FR-9；AC-10 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P3-IT-01 | 旧草稿读取→正常编辑发布→React Run | 读取无 UPDATE；canonical diff 无默认噪声；行为与基线一致 | AC-1；FR-1、FR-2 |
| P3-IT-02 | 合法/未知/不可用配置发布 | 合法精确解析；非法在发布/admission 前拒绝，Adapter 未启动 | AC-2；FR-2 |
| P3-IT-03 | 组合声明、probe、多层策略后执行 | 五类数据一致，Effective 单调收窄，preview/Run 同 resolver；**取证边界（R-42/R-43）**：部署缺失/版本不兼容/probe 超时三信号只能由注入的 probe/policy 替身证明，生产实现必须证明 cold→一次有界 warm 成功→available 与实例声明偏差（`resolve` 后、`prepare` 前比较 `adapter.get_capabilities()` 与注册声明，不符即 `execution_configuration_invalid` 且 `Adapter.start=0`）；disabled 三元组仍失败关闭 | AC-3、AC-4；FR-3、FR-4 |
| P3-IT-04 | Run/Agent/preview 注入伪造字段 | 4xx/领域错误、提权为 0；**直接查询安全审计**，含可信主体/route/脱敏路径且无 body/字段值/秘密 | AC-5；FR-5 |
| P3-IT-05 | tenant B 访问 tenant A 配置、preview、Run 快照与审计 | 查询层全部不可达，沿用 404，不只隐藏字段 | AC-5；FR-5 |
| P3-IT-06 | 完成 Run 检查 Adapter.start 屏障 | 五列非空且一次 commit（写屏障返回 `written`）；`Adapter.start` 晚于 commit；公开 `run.started` 仍在 claim 原位置 | AC-6；FR-6 |
| P3-IT-07 | Adapter 失败、取消、超时后检查快照 | 启动快照保留，既有终态正确，迟到结果不改写（断言须逐字段比较写入后的完整存储载荷，不得只看 `execution_id`/`schema_version`） | AC-6；FR-6 |
| P3-IT-08 | 注入序列化/denylist/DB commit 失败 | Run 失败关闭，`Adapter.start=0`，无 runner/模型/工具副作用；commit 失败注入必须在 UPDATE **已执行**之后失败（before_execute 注入等于语句没跑，不构成原子性证据），并证明随后同一屏障仍可正常落库；**另含"绕过序列化器"负控**：形状合法的 JSON 字符串载荷分别注入被禁键、凭据形态值、以 `/` 开头的值、缺项与重复项，五列各自单独触发，写屏障入口清洗闸必须在语句执行前抛 `ExecutionSnapshotError` 且该行五列仍为 NULL，且该闸必须是 strict 再校验形态（逐列复用 `deserialize_execution_snapshots` 或等价的逐列 `model_validate_json`+clean 扫描）——只做 `assert_snapshot_payload_clean` 无法拒绝缺项与重复项（R-34/R-51）；**负控矩阵登记**：5 类注入（被禁键、凭据形态值、`/` 开头值、缺项、重复项）× 5 列各自单独触发，其中 `declared_capabilities_snapshot` 列的"重复项"结构性不可表达（该列由定形 DTO 承载、重复 JSON 键在解析时塌缩），故矩阵实际为 24/25 可表达，由矩阵完备性测试钉住这一例外、不得静默失踪 | AC-6；FR-6 |
| P3-IT-09 | MemoryInjection 贯通 Summary/Memory/开关/写回 | 文案、顺序、budget、日志、写回 diff 为 0，业务渲染一次 | AC-7；FR-7 |
| P3-IT-10 | 同一上下文经 React 与测试 Provider | 格式独立、渲染一次、公开事件不被原生格式破坏 | AC-8；FR-7 |
| P3-IT-11 | preview 后改变平台/租户策略再执行 | preview 只读；执行重新计算，不沿用旧授权，原因更新；**实现形态登记**："policy revision 前进使条目失效"的用例只能由**非 PG 的真 resolver + 注入的假 provider**（revision 可控前进）证明，因为本阶段生产 provider 恒返回作用域常量 0（R-44）；PG 面另行断言 preview 与 Run **共享同一 resolver 实例**（同一 `RuntimeServices.execution_subsystem`），而非各建一套 | AC-4、AC-9；FR-4、FR-8 |
| P3-IT-12 | Phase 3 off 分别遍历 Orchestrator off/on | 两者精确保持部署原 Phase 2 路径，五列 NULL，无 Phase 3 probe/快照副作用 | AC-10；FR-8、FR-9 |
| P3-IT-13 | off 非 React 与 on+orchestrator off | off 非 React=`execution_phase3_disabled` 且 React start=0；on+orchestrator off 配置失败关闭，不走 legacy | AC-10；FR-8、FR-9 |
| P3-IT-14 | 动态前驱升级 `0058` 并旧/新 Run 并发读写 | 仅五列新增，旧行 NULL，新行可写，现有语句不受阻 | AC-11；FR-6 |
| P3-IT-15 | 回滚 Phase 2 二进制但不 downgrade | 可空列不阻碍旧代码，React 正常，历史完整 | AC-10、AC-11；FR-8 |
| P3-IT-16 | 新旧 React 经 Model Gateway/工具校验 | Profile/版本/权限/Run 关联不变，无通用配置绕过或密钥快照 | AC-1、AC-2、AC-6；FR-2、FR-6 |
| P3-IT-17 | preview 未保存草稿与已发布 Agent | 支持 `agent_id=null`；不建 Run/Conversation/Adapter/快照；scope 正确；OpenAPI 与白名单响应一致 | AC-5、AC-9；FR-5、FR-8 |
| P3-IT-18 | 快照并发重试与缓存 Runtime 开关切换 | 复用 execution_id 且无第六列；相同启动可校验复用（`reused`，判据为 jsonb 语义相等）、不同决策返回 `audit_conflict`；**foreign execution_id 写入空行必须返回 `audit_conflict` 且不访问数据库**；失租/非 running 分别返回 `lease_lost`/`not_claimed` 而非配置错误；off→on/on→off 与已 claim 行路径固定、不重写策略 | AC-6、AC-10；FR-6、FR-9 |
| P3-IT-19 | 真实 composition 接线一致性（R-18/R-20/R-21） | resolver/cache/warmer 参数全部来自 settings 且无硬编码；`execution_capability_policy_version` == 注册 descriptor.policy_version == provider 回显；连续解析 0 次身份校验失败；preview 与 Run 用同一投影函数、11 项逐字节一致；生产 descriptor 的 `instruction_provider_id/provider_version` 引用 contracts 常量而非字面量，且该二元组可被 `resolve_instruction_provider` 命中（descriptor↔Provider 注册集合一致性断言，R-31）；断言一律走公开面：availability key 的部署身份等于 settings 值、`warmer.next_refresh_delay` 等于 `execution_capability_warm_refresh_seconds`、TTL 在 settings 值处按 fake clock 变 stale、descriptor 的 probe/policy/instruction 三元与 provider 回显同源；warm targets 数等于生产 Registry 中 enabled 注册数且每个 target 可被 `metadata()` 命中（R-46）；ExecutionConfig 快照载荷与 `AgentConfig.execution_config()` 语义相等（旧根别名与 react 两种形态各一例，R-52）；`serialize_execution_snapshots` 显式传 `execution_snapshot_max_bytes`，上限低于载荷时必拒（R-52）；observed_at/resolved_at 年份合理（R-49） | AC-3～AC-6、AC-10；FR-3～FR-6、FR-9 |
| P3-IT-20 | Reader 于 internal management 面读取 execution-config-flags | 未认证 401/403；Reader 得到部署真实值对且对所有 tenant 一致、跨 scope 无差异；OpenAPI 含该路由且响应白名单无内部 ID/digest/policy/probe 原文；前端据此声明式隐藏 Phase 3 专属入口（Playwright 证据入 §6.1） | FR-8、FR-9；AC-9、AC-10 |
| P3-IT-21 | 生产受信端口实现形态与最小权限分层 | probe 只读注册声明且绝不调用 `adapter.get_capabilities()`，回显 probe_id/probe_version 与三元组，observed_at 由注入时钟且非 1970，deployment_digest 为稳定 64 位十六进制且非 UNOBSERVED_DIGEST；policy provider 的 platform 层等于 allow-list（四项 allowed、七项 `platform_denied`），tenant/execution 层 allowed 且 Effective 六元 AND 不能放大，agent 层由已发布 disabled 派生，`layer_versions` 四项齐全且 revision 取现读值；**ceiling 负控**：以测试注册的 Engine 声明 ceiling 外能力，证明该项得 `platform_denied` 而非 `not_declared`（React 下被拒七项因 declared=false 被 `not_declared` 短路，故只有测试 Engine 可观察）；`current_revision` 在同一作用域两次读取相等（常量平凡单调）且绝不因每轮前进；Workspace 端口恒 None；端口只由 composition 的 `ports=` 代码级注入，settings/env 不能选择端口 | AC-3、AC-4；FR-3、FR-4、FR-9 |
| P3-IT-22 | 四态矩阵与 Run 侧失败码 | off/off 与 off/on 与基线逐字段全等且 `ExecutionRequest.config`/`effective_capabilities` 仍为 `{}`、probe 与写屏障调用计数恒 0、五列 NULL；on/off 失败关闭且 `runtime.for_run` 调用计数恒 0、终态码 `execution_configuration_invalid`；on/on 五列一次写（written/reused）、`Adapter.start=1`、公开事件序列与 off/on 全等；published 非 React 三元组（直接写入 `agent_versions` 的测试行）在 off 态得 `execution_phase3_disabled`、on 态得 `execution_engine_unavailable`，两者 React start 恒 0；**错误分类十行表逐项给码**：registry `ConfigurationError`（UNKNOWN_ENGINE/ADAPTER_DISABLED…）→`execution_engine_unavailable`、required-missing→`execution_engine_unavailable`、policy cold 且一次有界 warm 仍失败→`execution_policy_unavailable`、实例声明偏差→`execution_configuration_invalid`、ExecutionConfig 规范化失败→`execution_configuration_invalid`、序列化/denylist/缺项/超限→`execution_configuration_invalid`、`audit_conflict`→`execution_configuration_invalid`、`not_claimed`→`worker_lost`、`lease_lost`→`worker_lost`、失租/非 running→既有 `worker_lost` 路径；`execution_error` **永不**作为已分类屏障失败的终态（被宽 `except Exception` 降级即缺陷）；**声明偏差闸零副作用**：拒绝发生在快照序列化/写屏障与 `Adapter.start` 之前，故五列仍 NULL 且 start=0；`RuntimeEngine` Protocol 与 `engine.py` 实现签名一致（R-32）；错配态进程仍启动、flags 端点在该态可读且 `/ready` 不读两开关（本阶段不加 503） | AC-10；FR-8、FR-9 |

## 5. 通用核对项

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P3-CM-01 | 迁移在线性与编号 | 动态重验 head/down_revision；当前 `0058→0057`；只加五列、无回填、不改历史；disposable downgrade | AC-11；FR-6 |
| P3-CM-02 | 配置加载 | 默认、覆盖、非法边界与缓存失效符合 FR-9，秘密不入示例 | AC-10；FR-9 |
| P3-CM-03 | 审计与观测 | Engine/provider/policy 版本和原因齐全；422 伪造有真实审计；无 body/Token/Memory/宿主细节 | AC-5、AC-6；FR-5、FR-6 |
| P3-CM-04 | 租户与 scope 隔离 | 配置、preview、快照、策略与审计均按 tenant/business/workspace 隔离 | AC-5；FR-5 |
| P3-CM-05 | 历史兼容 | 合法样本按裁定通过；无 UPDATE/批量改写/默认 diff；失败样本有缺陷记录 | AC-1；FR-1 |
| P3-CM-06 | 快照不可变与空值 | Adapter.start 前一次 commit，之后不更新；历史 NULL 不回填，公开不暴露；静态门禁须扫描 repository 全文所有 `UPDATE runtime_runs`（不得只检查写屏障方法之前的语句），断言五个快照列只出现在 `write_execution_snapshots` 一处；该静态测试不得标 postgres 标记，需在全量非 PG 路径也执行 | AC-6；FR-6 |
| P3-CM-07 | 能力授权边界 | Declared/Available/Effective 非客户端授权源；上层拒绝不可恢复，Workspace 缺失不放开 | AC-3～AC-5；FR-3～FR-5 |
| P3-CM-08 | 前端 i18n 与只读 | `zh-CN/zh-TW/en/hi` 完整，typecheck/check:i18n/build 与 Playwright 通过；Effective 无编辑/提交授权。`check:i18n` 的 zh-* 文案判据（冻结）：zh-* 值内禁天城文区段 U+0900–U+097F；zh-* 句末禁半角 `. ! ? : ;`（全角 `：？！（）` 属合法收尾）；句末字符若属自然语言书写系统则拒，判据取 `frontend/scripts/check-i18n.mjs` 的 `languageScripts` 显式 Unicode `Script` 清单，**禁以"非 CJK 区间"反推**，`Script=Common` 的符号/单位/数学符号（℃ ° ½ ™ ® ↑ ↓ ✔ Ω π …）与全角标点放行，Han/Bopomofo/Tangut 与 Greek 有意排除（技术文案用 Ω/π，可经 `neutralFinal` 豁免单字）；`hi` 以 `।`(U+0964) 收尾合法；以上对现有 zh-CN/zh-TW 各 2075 键语料零回归（2026-11-13 实测）。既有例外：`model_not_configured` 的 errorText 句子未进四语言字典（en/hi 显示整句中文），属 Phase 3 范围外既有缺陷，登记于 08 §5/R-38，不计入本项通过/不通过；前端用例以显式白名单钉"不得新增第二个未翻译码" | AC-9；FR-8 |
| P3-CM-09 | 整体回滚 | 双开关矩阵和应用回滚符合 03，无需 downgrade；非 React 不降级，历史不丢 | AC-10；FR-8、FR-9 |
| P3-CM-10 | 阶段边界 | 无真实 Host/Workdir/Sandbox、Codex、通用策略后台、自动跨 Engine fallback、新测试框架 | AC-2、AC-10；FR-2、FR-8 |

## 6. 前端、性能与回归证据

### 6.1 前端

Playwright 以 mock `/api/v1/**` 覆盖：旧 Agent 默认无 dirty；合法新配置保存；冲突/未知错误；preview 只读和 probe unavailable；disabled 只收窄；viewer 只读；M1–M3 或等效自动化证据。逐一切换 `zh-CN`、`zh-TW`、`en`、`hi`，断言新增控件/错误/reason 都有翻译且无硬编码回退；保存截图/trace 与网络请求，证明 preview 不创建 Run。M3 场景必须 mock `GET /api/v1/agents/execution-config-flags`：`execution_phase3_enabled=false` 时断言 preview 按钮与收窄勾选不在 DOM、全程无 `/agents/execution-preview` 请求、React 模型/轮次编辑与历史查看仍可用；`true+orchestrator=false` 时断言"部署配置错误"提示存在且无假成功展示。

**P3-FE 编号登记**：`frontend/tests/agent-execution-config.spec.ts` 使用 `P3-FE-01…21`，另含 `05b/10b/10c/16b` 四个变体，共 **25 个编号**；`P3-FE-10c/12/17/18` 各按 `zh-CN/zh-TW/en/hi` 参数化，展开为 **37** 个用例。与本文/本阶段判据的对应：M1＝01、09；M2＝03、04、06、10b、11（不支持/环境不可用/策略拒绝/422 字段路径可定位）＋05、05b、07（preview 只读与收窄）；M3＝10、14、15、16、16b、19、20、21；P3-CM-08 四语言与键完整性＝10c、12、13、17、18；P3-CM-05（历史兼容/dirty）＝02；preview 不建 Run 的前端侧证据＝08。纪律：新增前端用例必须取未占用的新编号，已登记编号不得复用或改义；06 直接引用本表，不再另建映射表。

### 6.2 C11 真实性能测量

- 测量真实 Phase 3 resolver/admission 路径与配对 Phase 2 基线，不只测孤立 helper；排除模型/工具执行时间。
- 采集 C11 前记录并冻结 R-18 六项 settings 取值（policy/probe 超时、并发、容量、重试、刷新、部署身份）连同 SHA 写入 06；配对样本必须在同一取值下采集。
- 同机、同进程构建、同数据、同负载；先分别预热 config/probe/policy caches，再丢弃预热样本。
- 新旧路径交错采集至少 **100 个有效配对样本**（失败/超时/环境中断样本剔除并说明），保存原始每对耗时、时间戳、SHA、配置、cache 版本与负载。
- 分别汇总配置解析、probe cache、policy cache、总 admission；计算配对增量 p95，判据 ≤50ms。不能用平均数、单次 best effort 或纯 mock cache 冒充。
- 缺必需环境或样本不足保持 `pending_env` / `not_measured`，C11 不得通过；原始数据纳入 06，07 引用而非预写结果。

### 6.3 回归

- RuntimeEngine、Worker、Repository、取消/失租/超时、Run API/SSE、双 emit/ack/Outcome 与 Phase 2 focused tests。
- Agent 配置/发布/回滚、Model Gateway、工具/知识权限、Summary/Memory 配置/注入/日志/写回。
- 迁移后旧代码兼容、新代码 NULL；架构检查、ruff、前端三项和 targeted Playwright；全量由 CI。
- 不因新实现修改历史 fixture 预期，不将 skip 写成通过。

## 7. 缺陷分级、出口与报告

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 提权、跨租户、秘密泄露、未授权 Adapter.start、数据丢失 | 停止验收，修复并完整回归安全/兼容 |
| P1 严重 | 旧配置不兼容、Effective 错误、快照缺失、Provider 回归、开关/非 React 拒绝失效 | 修复前不得验收 |
| 一般 P2 | 非阻断原因码、预览或一般质量偏差 | 仅非硬门禁可带 owner/期限，由验收负责人记录 |
| 轻微 P3 | 文案、非敏感日志或展示问题 | 排期修复；i18n 缺失/泄露不能降格掩盖 |

**出口**：P3-UT/IT/CM 全通过；AC-1～AC-11 可复现；无 P0/P1；提权/跨租户为 0；快照和审计达标；双开关 diff 符合；C11 有效实测达标。环境缺口阻断其上线承诺。实际完成后才创建双语 `06-test-report.md/.en.md`，记录命令、SHA、环境、原始证据、skip/pending_env 和 format 基线边界；本方案不预写通过结论。
