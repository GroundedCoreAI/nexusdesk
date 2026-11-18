# 阶段 0–3 范围限定验收记录（2026-11-18）

> 状态：**验收通过（范围限定 / scope-limited PASS），已由单一验收负责人签署确认**；签署日期 2026-11-18。
> 目标 SHA：`5170e140f10b117549cf54ba400131f5d7f95f69`（`integration`，PR #143 merge 提交）
> 执行环境：受控共享生产 Linux 主机 `iZwz9hk5o1f6h2hs6kfetpZ`（Alibaba Cloud Linux 3，kernel 5.10.134，x86_64）
> 证据包：`/home/nexus/nexusdesk-acceptance/evidence/20261118T125822Z.tar.gz`
> SHA256：`109989c3c0a0ee4f9aa1bcc49b7ebc3b382f697de98461f4a6b3ee366e9a9d23`
> 依据：`09-acceptance-execution-runbook.md`（2026-11-18 修订）、`10-remote-linux-acceptance-appendix-20261117.md`、各阶段 `05-acceptance-plan*.md`

## Abstract (English)

A scope-limited acceptance run for phases 0–3 was executed on the current shared production Linux host
at the pinned SHA. Under the 2026-11-18 revision, performance, CI provenance, real/authorized historical
samples and large-sample data-volume requirements are **out of stage scope**; the gates are functional
correctness, switch completeness, tenant isolation, Secret handling, data integrity, migration correctness,
terminal-state semantics, side effects/cleanup, no open P0/P1, and a single acceptance-owner record.
All 13 lanes passed with exit code 0; 5,464 JUnit tests, 0 failures, 0 errors, 55 declared skips.
Switch completeness was proven at the pinned SHA by a dedicated 913-test automated lane plus read-only
default-off inspection. Technical verdict: **PASS (scope-limited)**. The single acceptance owner confirmed
and signed on 2026-11-18 (see §7), so no signature item remains outstanding; high-risk capability
enablement is not authorized by this record.

## 1. 验收范围与排除项

按 2026-11-18 修订，**不作为阶段 0–3 验收门禁**：

| 排除项 | 处置 |
|---|---|
| 性能 / 容量 / p50 / p95 / C11 延迟 / ≤5% / ≤50ms | 范围外，仅历史记录 |
| 配对样本（30 / 100 对）、样本计数、多样本 / 大数据量 | 范围外 |
| CI provenance、最终 PR head CI 双跑、CI run URL | 范围外，仅历史记录 |
| 真实 / 经授权历史样本、历史基线兼容分母 | 范围外；用户确认现阶段不存在历史样本数据问题 |
| 人工验收签字、人工介入 case | 已由单一验收负责人于 2026-11-18 确认签署（见 §7）；按最小核心团队标准不要求多角色签字 |

**仍为门禁**：功能正确性（A 场景）、开关完备性（默认关闭、显式开启、off/on/rollback 矩阵、无静默回退、开关不泄漏到公开面/指纹）、租户隔离、Secret 处理、数据完整性、迁移正确性、终态语义、副作用/清理、无开放 P0/P1、单一验收负责人记录。高风险能力启用仍须独立安全与运维批准。

## 2. 环境与隔离

| 项 | 值 |
|---|---|
| 主机 | 共享生产机（同机运行 ERP Java / MySQL / 既有 `nexusdesk-quickstart` 栈） |
| 架构 | x86_64（生产/CI 等价） |
| 验收资源 | `nd-accept-pg` 容器仅绑定 `127.0.0.1:55432`；证据目录 run-scoped；无 18080/18010 占用 |
| 同机服务变更 | **无**；执行前后 `docker ps` 与端口清单一致（见 `01-environment.txt`、`d11-final-host-state.txt`） |
| 凭据 | 合成凭据，`accept.env` mode 0600，未提交仓库 |
| 在线生产镜像 | `ghcr.io/groundedcoreai/nexusdesk-quickstart:345eb09aaabd`，digest `sha256:023a53b2…a32354`，源提交 `345eb09aaabd`，落后目标 SHA 37 个提交 |

> 部署镜像滞后是环境事实，不是代码缺陷，也不是本阶段门禁；本次自动化 lane 全部直接从目标 SHA 的检出树运行。

## 3. 执行结果

| Lane | 命令 / 范围 | JUnit | Exit |
|---|---|---|---|
| d0-migrations / heads / current | `alembic upgrade head`、`heads`、`current` | — | 0 / 0 / 0 |
| d1-non-pg | `-m 'not postgres'` 全量 | 2329 tests, 0 failed, 0 errors, 4 skipped | 0 |
| d2-postgres | `-m postgres` 全量 | 660 tests, 0 failed, 0 errors, 47 skipped | 0 |
| d3-execution-focused | 执行平台专项 60+ 文件 | 1547 tests, 0 failed, 0 errors, 4 skipped | 0 |
| d8-migrations | 迁移链专项 | 15 tests, 0 failed, 0 errors, 0 skipped | 0 |
| **d9-switch-completeness** | 开关/编排/回滚/默认关闭专项 | **913 tests, 0 failed, 0 errors, 0 skipped** | 0 |
| d4-typecheck / d4-i18n / d4-build | 前端三门禁 | — | 0 / 0 / 0 |
| d10-production-default-off | 只读检查在线生产栈 | — | 0 |

**合计：5,464 tests，0 failures，0 errors，55 skipped；13 个 lane 全部 exit 0。**

所有 skip 均为声明式环境跳过（Codex CLI 缺失、cgroup v2 硬限缺席、pgvector/embedding 列缺失、`CREATEDB` 受限），未改写为 pass。

## 4. 开关完备性判定（保留门禁）

| 判据 | 证据 | 判定 |
|---|---|---|
| 默认关闭 | `d10-code-defaults.txt`：`execution_orchestrator_enabled`、`execution_phase3_enabled`、`execution_runtime_host_enabled`、`execution_untrusted_tenants_enabled`、`execution_outbox_enabled`、`execution_event_cleanup_enabled`、`execution_parser_raw_sample_enabled`、`codex_cli_enabled`、`codex_app_server_enabled` 均为 `False`；`execution_sandbox_required` / `execution_network_default_deny` 为 `True` | 通过 |
| 在线生产栈默认关闭 | `d10-production-default-off.txt`：容器未声明任何 `AGENT_EXECUTION_*` / `CODEX_*` 环境变量，`AGENT_EXECUTION_RUNTIME_HOST_ID` 缺席，全部回落到代码默认值 | 通过 |
| off 路径只走 legacy、on 路径不触碰 legacy、on 无编排器时安全失败不回退 | `d9-switch-completeness.xml` 中 `test_worker_off_with_injected_orchestrator_uses_only_legacy`、`test_worker_on_never_touches_legacy_factory_or_runtime`、`test_worker_on_without_orchestrator_fails_safely_without_legacy_fallback` | 通过 |
| 指纹 / 公开面不泄漏开关 | `test_worker_fingerprint_check_precedes_both_execution_paths`、`test_p2_it20_public_run_view_and_observability_exclude_private_fields` | 通过 |
| off/on/rollback 矩阵与无静默降级 | `test_runtime_baseline.py` 全矩阵、Phase 3 flags/config/settings/wiring、Phase 4 settings/deployment/orchestration/runtime_host、`test_execution_phase6_settings.py` | 通过 |
| 迁移 head 单一且可升级 | `alembic heads` = `0071_execution_credential`；空库 `upgrade head` 成功 | 通过 |

## 5. 逐阶段结论

| 阶段 | 结论 | 依据 |
|---|---|---|
| Phase 0 基线与盘点 | **通过（范围限定）** | 全量后端/前端自动化绿灯、迁移 head 验证、无 P0/P1；CI 双跑与真实历史样本已按修订移出门禁 |
| Phase 1 执行契约与注册中心 | **通过（范围限定）** | D3 契约/Registry/第二 Adapter/错误矩阵绿灯；CI run URL 已移出门禁 |
| Phase 2 React Provider | **通过（范围限定）** | `test_runtime_baseline.py` off/on parity、双 emit、SSE/终态、D4 前端门禁、D9 开关矩阵全绿；C11 性能已移出门禁 |
| Phase 3 能力/配置/指令 | **通过（范围限定）** | D3、D9、迁移链 0058/0059/0070/0071 绿灯；性能 C11 已替换为开关完备性功能门槛并满足 |

## 6. 残留与边界

| ID | 项 | 状态 |
|---|---|---|
| A-1 | 单一验收负责人签署 | **已签署 / 已关闭**：JackChow 于 2026-11-18 确认（见 §7） |
| A-2 | 在线 live Compose off/on/rollback 演练 | `pending_env`：DockerHub 不可达、`node:22-alpine` 未缓存、无目标 SHA 对应镜像；开关完备性已由 D9 在目标 SHA 自动化证明，不构成门禁 |
| A-3 | 部署镜像落后 37 个提交 | 环境事实；建议后续发布时对齐 `integration` |
| A-4 | 55 个声明式 skip | 保持 skip，不改写为 pass |
| A-5 | #127 / #128（示例 seed、quickstart 接线） | 按 Phase 3 `05` 记录为 deferred，不写完成 |
| A-6 | 高风险能力启用 | **未授权**；`execution_*` / `codex_*` 开关保持默认关闭，须独立安全与运维批准 |

## 7. 单一验收记录（人工验收签署）

| 字段 | 值 |
|---|---|
| 验收负责人 | **JackChow**（用户本人；仓库配置 `git user.name`，作为最小核心团队的单一验收负责人） |
| 签署确认 | **已确认签署**：用户于 2026-11-18（GMT+8）在对话中明确确认“阶段 0–3 验收通过”，据此填写本单一验收记录并关闭 A-1 |
| 执行人 | WorkBuddy 自动化验收执行（可与负责人同人） |
| 日期 (UTC) | 2026-11-18 |
| 目标 SHA | `5170e140f10b117549cf54ba400131f5d7f95f69` |
| 环境 | 受控共享生产 Linux 主机；run-scoped、loopback 绑定；x86_64 |
| 结论 | **通过（范围限定 / PASS scope-limited）** |
| 证据 | `20261118T125822Z.tar.gz`，SHA256 `109989c3c0a0ee4f9aa1bcc49b7ebc3b382f697de98461f4a6b3ee366e9a9d23` |
| 残留 | A-2～A-6（均非门禁或已被修订移出）；A-1 已关闭 |
| 高风险启用 | 未请求、**未授权**；如启用须单独安全与运维审批并填写审批链接 |

> 签署范围说明：本签署确认的是**阶段 0–3 范围限定验收通过**，不含高风险能力启用、生产发布授权或后续阶段放行。按最小核心团队标准，阶段验收只要求单一验收负责人记录，不要求产品/QA/研发/安全等多角色签字；各 `07` 报告中保留的历史多角色签字表为历史背景，其 `pending` / `unsigned` 状态不再作为阶段 0–3 验收门禁，以本记录及各 `07` 的 2026-11-18 执行补记为准。

## 8. 复现

证据包包含 `00-pin.txt`、`01-environment.txt`、`03-logs/<lane>.{command,log,exit}`、`04-junit/*.xml`、
`d9-switch-assertions.txt`、`d10-code-defaults.txt`、`d10-production-default-off.txt`、
`d9-live-drill-scope.txt`、`d11-final-host-state.txt`、`manifest.json`。逐条命令见 `.command` 文件。
