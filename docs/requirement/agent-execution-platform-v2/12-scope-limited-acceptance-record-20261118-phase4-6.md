# 阶段 4–6 远程 Linux 验收记录（范围限定，2026-11-18）

> 状态：**验收通过（范围限定 / scope-limited PASS），已由单一验收负责人签署确认**；签署日期 2026-11-19（GMT+8，即 2026-11-18T16:36Z）。
> 本记录只追加执行证据，不改写 `06`/`07` 的历史结论与数字；不授权任何高风险能力启用。
> 权威上游：`09-acceptance-execution-runbook.md`（2026-11-18 范围限定修订）、`11-scope-limited-acceptance-record-20261118.md`（阶段 0–3）。

## 1. 执行边界

| 项 | 值 |
|---|---|
| 目标 SHA | `80fac6056682a7835c61dab4678c5772b8689d1f`（`integration`，PR #144 merge） |
| 执行日期 (UTC) | 2026-11-18 14:23Z–15:18Z |
| 证据 run id | `20261118T150343Z` |
| 主机 | 受控共享生产 Linux 主机 `nexusdesk-accept`（x86_64, kernel 5.10.134, Alibaba Cloud Linux 8） |
| 隔离方式 | run-scoped 容器/端口/路径/凭据；验收 PG 仅绑定 `127.0.0.1:55432`；生产 `8080` 服务未启停/改配；Node 22 用户态安装 |
| 代码来源 | 本地浅克隆 bundle（服务器端 GitHub 大对象 clone 超时）；SHA 与 `git ls-remote` 一致 |
| 数据库 | `postgres:17-alpine`（缓存镜像替代 `pgvector/pgvector:pg17`，DockerHub 不可达）；`alembic heads` 单头 `0071_execution_credential` |

## 2. 测试结果

**12 个 lane 全部 exit 0；JUnit 合计 6,103 tests / 0 failures / 0 errors / 62 declared skips。**

| Lane | tests | failures | errors | skipped |
|---|---:|---:|---:|---:|
| d1-non-pg | 2329 | 0 | 0 | 4 |
| d2-postgres | 660 | 0 | 0 | 47 |
| d3-execution-focused | 1547 | 0 | 0 | 4 |
| d5-phase6-docker | 21 | 0 | 0 | 0 |
| d5-phase6-core | 108 | 0 | 0 | 0 |
| d6-codex-unit | 103 | 0 | 0 | 1 |
| d7-phase4 | 344 | 0 | 0 | 3 |
| d8-migrations | 15 | 0 | 0 | 0 |
| d9-switch-456（开关完备性专项） | 976 | 0 | 0 | 3 |
| d4-typecheck / d4-i18n / d4-build | — | — | — | —（npm 门禁，均 exit 0） |

62 个 skip 全部为声明式/环境占位，与阶段 0–3 已接受基线一致：`MIGRATION_TEST_DATABASE_URL` 未设的迁移占位 22、pgvector/embedding 能力占位 16、cgroup/quota `pending_env` 12、channel `propose_ticket` 声明 7、无 Codex CLI 3、Milvus opt-in 1、seeded quickstart opt-in 1。**无任何 `TEST_DATABASE_URL` 自跳过**（错误运行 `20261118T142322Z`/`20261118T144036Z` 保留为历史，不作为证据）。

## 3. 门禁判定（范围限定口径）

| 阶段 | 保留门禁 | 本轮证据 | 判定 |
|---|---|---|---|
| Phase 4 Runtime Host/Workspace | A1–A12/C1–C14 功能、开关完备性（默认关、显式开、关/开/回退、无静默降级）、租户隔离、Secret、进程/清理、迁移、终态 | D1/D2/D3/D7/D8/D9 + 代码级默认关闭核对 | **通过（范围限定）** |
| Phase 5 Codex Stage A | A1–A6/A11–A12、开关/Secret/隔离/清理/终态；Stage B 锁定 | D6 deterministic unit（Codex CLI 真二进制 lane `pending_env`，非阶段门禁）+ D1/D2/D9 | **通过（范围限定）**；Stage B 仍锁定 |
| Phase 6 安全/可靠性/事件 | A1–A16/C1–C12 功能、事件语义、故障隔离、Secret、迁移、终态；C12 不可信启用一票否决 | D5 docker/core、D8 迁移、D2/D9；不可信开关保持 false | **通过（范围限定）**；不可信启用未授权 |

已按 2026-11-18 修订移出阶段门禁（仅历史背景/高风险启用前置）：性能/容量/p50/p95、Outbox lag、恢复时间、迁移锁预算、配对与样本量；CI provenance / 最终 PR head 运行；真实或授权历史样本/基线；真实 Codex 发布环境、20 场景×3 批次（Stage B 解锁条件）、代表性生产副本迁移、双 Worker 混合故障、独立安全/SRE 审批。

## 4. 残留与边界

- `pending_env`：D6 Codex 真二进制（无 CLI/凭据）；D9 live Compose off/on/rollback（共享生产机无书面变更审批、缓存镜像落后目标 SHA）；E1–E5（cgroup/quota/mount/PID/生产镜像演练，无 passwordless sudo、cgroup 控制器为空、`mountns=FAIL`）；E6/E7/E9/E10/E11（新测试/数据/授权/独立审批）。逐项登记见仓库内 [05-pending-env.md](05-pending-env.md)（2026-11-21 归档的登记清单，非原始执行证据）；原始证据包 `20261118T150343Z.tar.gz`（SHA256 `bbc979e7d999a274fb689dbc458367dcca3c61610006c0339207ebe7e9e8050c`，见本记录 §5）位于远程验收主机 `nexusdesk-accept` 的证据目录，此前未纳入本仓库版本控制。
- 真实 API key/凭据未使用；所有 `AGENT_EXECUTION_*`/`CODEX_*` 保持默认关闭；`sandbox_required=true`、`network_default_deny=true`。
- #133/#134/#136 等历史问题维持原状态；性能/样本/CI 类不再作为阶段门禁。
- 高风险启用（Runtime Host、生产 Codex 路由、Stage B、不可信租户）需独立安全与运维审批，本记录不授权。

## 5. 单一验收记录（人工验收签署）

| 字段 | 值 |
|---|---|
| 验收负责人 | **JackChow**（用户本人；仓库配置 `git user.name`，作为最小核心团队的单一验收负责人） |
| 签署确认 | **已确认签署**：用户于 2026-11-19 00:36（GMT+8，即 2026-11-18T16:36Z）在对话中明确确认“阶段 4–6 验收通过”，据此填写本单一验收记录；无未完成签署项 |
| 执行人 | WorkBuddy 自动化验收执行 + 独立回归子代理 |
| 日期 (UTC) | 2026-11-18 |
| 目标 SHA | `80fac6056682a7835c61dab4678c5772b8689d1f` |
| 环境 | 受控共享生产 Linux 主机，run-scoped；x86_64；同机生产服务零改动 |
| 结论 | **通过（范围限定 / PASS scope-limited）** |
| 证据 | `20261118T150343Z.tar.gz`，SHA256 `bbc979e7d999a274fb689dbc458367dcca3c61610006c0339207ebe7e9e8050c` |
| 残留 | E 类 `pending_env` 与高风险启用单独审批；均非当前阶段门禁 |
| 高风险启用 | 未请求、**未授权** |

> 签署范围说明：本签署确认的是**阶段 4–6 范围限定验收通过**，不含高风险能力启用、生产发布授权或后续阶段放行。按最小核心团队标准，阶段验收只要求单一验收负责人记录，不要求产品/QA/研发/安全等多角色签字；各 `07` 报告中保留的历史多角色签字表为历史背景，其 `pending` / `unsigned` 状态不再作为阶段 4–6 验收门禁，以本记录及各 `07` 的 2026-11-18 执行补记为准。

## 6. English summary

Scope-limited phases 4–6 acceptance at SHA `80fac60` on the governed shared production Linux host: 12 lanes, all exit 0; 6,103 JUnit tests with 0 failures / 0 errors and 62 declared skips (no `TEST_DATABASE_URL` self-skips). Phase 4/5 Stage A/6 kept gates (functional correctness, switch completeness, tenant isolation, Secret handling, data integrity, migration, terminal-state semantics, cleanup, no P0/P1) are satisfied; Stage B remains locked and high-risk enablement is not authorized. Performance/CI/historical-sample/real-Codex-environment items are out of stage scope under the 2026-11-18 revision. Verdict: **PASS (scope-limited)**. The single acceptance owner (JackChow) confirmed and signed on 2026-11-19 (GMT+8), so no signature item remains outstanding; high-risk capability enablement is not authorized. Evidence: `20261118T150343Z.tar.gz` (SHA256 `bbc979e7d999a274fb689dbc458367dcca3c61610006c0339207ebe7e9e8050c`).
