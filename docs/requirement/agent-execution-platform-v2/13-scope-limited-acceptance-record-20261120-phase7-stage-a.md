# 阶段 7 Stage A 端到端验收记录（范围限定，2026-11-20）

> 状态：**验收通过（范围限定 / scope-limited PASS），已由单一验收负责人签署确认**；签署日期 2026-11-20 18:49（GMT+8，即 2026-11-20T10:49Z）。
> 本记录只追加执行证据，不改写 `11`/`12` 的历史结论与数字；不授权任何高风险能力启用；Stage B 保持锁定。
> 权威上游：`09-acceptance-execution-runbook.md`、`12-scope-limited-acceptance-record-20261118-phase4-6.md`（阶段 4–6）、
> `phase-5-codex-integration/08-implementation-breakdown.md` §3.7/§3.8、PR #155（D-1…D-4）。

## 1. 执行边界

| 项 | 值 |
|---|---|
| 目标 SHA | `63221a1fd3bad7562b351b7bbbd23e0c95500cb6`（`integration`，PR #155 merge） |
| 镜像 tag | `ghcr.io/groundedcoreai/nexusdesk-quickstart:63221a1fd3ba`（CD run `44716695070`，3/3 job success） |
| 上游 CI | `44715956443`，`63221a1` push → success（5/5 checks） |
| 执行日期 (UTC) | 2026-11-19 – 2026-11-20；干净镜像重跑 2026-11-20 10:12Z–10:2x Z |
| 主机 | 受控测试主机 `nexus@120.78.135.217`（x86_64, Alibaba Cloud Linux） |
| 运行容器 | `nexusdesk-quickstart-app-1`（compose project `nexusdesk-quickstart`），health `healthy` |
| 数据库 | `nexusdesk-quickstart-postgres-1`，`pgvector/pgvector:pg17` |
| Codex CLI | `0.169.0`，`/opt/nexusdesk/codex/bin/bin/codex.js` |
| Node 运行时 | `v22.14.0`，`/home/nexus/nexusdesk-acceptance/node/bin` |
| `CODEX_HOME` | run-scoped，仅含免密钥 `config.toml` + Codex 自身状态文件 |
| 凭据 | Vault key `/data/credentials/execution.key`（32B base64，`0600`，owner `nexusdesk`，位于持久化卷）；API key 只经 `ProcessSpec.environment` 的 typed slot 投递 |

**关键前提：本轮证据来自干净 CI 镜像。** `docker diff nexusdesk-quickstart-app-1` 在 `/app` 下无任何可写层改动；镜像内 D-1…D-4 四处修复与 `home_config.py` 均存在，占位符 `_codex_config` 计数为 0。上一轮的人工源码覆盖层已随容器重建完全丢弃。

## 2. 开关状态（显式开启，默认仍为关闭）

`/home/nexus/nexusdesk/deploy/quickstart/.env`（主机本地，不随仓库提交）：

```
NEXUSDESK_VERSION=63221a1fd3ba
NEXUSDESK_IMAGE_REGISTRY=ghcr.io/groundedcoreai/
NEXUSDESK_CODEX_BIN_DIR=/home/nexus/.npm-global/lib/node_modules/@openai/codex
NEXUSDESK_CODEX_NODE_DIR=/home/nexus/nexusdesk-acceptance/node/bin
AGENT_CODEX_CLI_EXECUTABLE_PATH=/opt/nexusdesk/codex/bin/bin/codex.js
AGENT_CODEX_PATH_ENV=/opt/nexusdesk/codex/node:/usr/local/bin:/usr/bin:/bin
AGENT_EXECUTION_RESOURCE_MEMORY_BYTES=2147483648
```

实测容器内：`AGENT_EXECUTION_PHASE3_ENABLED / ORCHESTRATOR_ENABLED / RUNTIME_HOST_ENABLED = true`，
`RUNTIME_HOST_ID=quickstart-runtime`，`AGENT_CODEX_CLI_ENABLED / STAGE_A_VERIFIED = true`，
`ALLOWED_VERSIONS=["0.169.0"]`，`TRUSTED_TENANTS=["local"]`，`CREDENTIAL_ENV_KEY=DEEPSEEK_API_KEY`（仅键名，值不落盘、不打印）。
**Stage B（`codex/app_server/v1`）保持锁定。**

## 3. 端到端证据（干净镜像，三轮 Run）

| # | run_id | 终态 | output | 事件 |
|---|---|---|---|---|
| 1 | `99563a82-cd9c-40b9-9b81-651b1b61ea08` | `completed`, `error_code=None` | `OK` | 8 行 / 7 类 |
| 2 | `d8c72fd7-affe-4f4e-883a-c707b5c9f4e9` | `completed`, `error_code=None` | `OK` | 8 行 / 7 类 |
| 3（工具调用） | `aa9ab8f2-aa4b-4714-9a1d-4e295db768db` | `completed`, `error_code=None` | 自述沙箱无法启动（见 §5.1） | 10 行 / 8 类 |

第 1 轮事件按序（`runtime_events.seq`）：
`1 run.queued → 2 run.started → 3 codex.thread.started → 4 codex.item.completed → 5 codex.turn.started → 6 codex.item.completed → 7 codex.turn.completed → 8 run.completed`。
第 2 轮为同一已发布 Agent 的连续第二轮，事件形状一致 → 链路可重复。

其余：

| 断言 | 实测 |
|---|---|
| 凭据审计 | `grant_issued:success ×1`，`grant_used:success ×1`（`created` 为早前建凭据时写入）；一次性 grant hash |
| Workdir | `retained`，`25bf8e1a2393f110/99563a82-cd9c-40b9-9b81-651b1b61ea08`，无 `last_error_code` |
| Usage ledger | `runtime_usage_ledger` 1 行，`source=engine_terminal`（**有落账**） |
| 密钥隔离 | `CODEX_HOME` 无 `auth.json`，无宿主 `~/.codex` / `.env` 拷贝 |

即：**发布 → 编排（Phase 3 barrier）→ Runtime Host 进程 → 凭据 Broker 发券/用券 → Codex CLI 真实轮次 → 事件与终态 → usage 落账** 在干净 CI 镜像上全线贯通。

## 4. 本轮修复的 4 个阻断缺陷（PR #155）

| 编号 | 症状 | 根因 | 修复 |
|---|---|---|---|
| D-1 | 每个 Codex Agent 发布返回 `409 agent_model_required` | `validate_model()` 无条件要求 Gateway model profile，而 CLI 引擎本就应把 legacy 别名归一为 `None` | `MODEL_PROFILE_ENGINES={"react"}`，只对 React 解析 profile，React 行为不变 |
| D-2 | 每次 Run 25–30ms 内 `execution_error` | Phase 3 barrier 拿到 `RuntimeFactory` 实例却按 callable 调用 → `TypeError: 'RuntimeFactory' object is not callable`，`Adapter.start` 从未到达（React 同样中招） | preparer 在构造函数里绑定 `prepare_instructions`；未配置时显式 `TypeError` |
| D-3 | `engine_unavailable`，宿主 `exit_code=-5`（SIGTRAP） | Node/V8 启动即预留大段虚拟地址，512 MiB `RLIMIT_AS` 触发 `Failed to reserve virtual memory for CodeRange` | `CODEX_CLI_MIN_MEMORY_BYTES=1 GiB` + 配置期校验；compose 参数化、默认值不变，示例 2 GiB。实测 512 MiB 失败 / 1 GiB 通过 |
| D-4 | Run 到达宿主但 `engine_unavailable`(`exit_code=1`)，凭据审计 0 条 grant | 适配器由部署级占位 `ExecutionConfig` 字面量构造，而非 Agent 修订上发布的 `codex` 块 → 无 `credential_ref`、无 `home_config`，Broker 从未被调用 | 工厂改读 `execution_config_from_context(context).codex`，缺失即 `RuntimeError` 失败关闭；删除占位字面量 |

D-1…D-3 见 `08` §3.7/§3.8；D-4 见 PR #155。回归：`test_agent_model_gate_engines.py`（3 nodes）、`test_agent_execution_stage_a_preflight.py`（7 nodes）、compose 断言。

## 5. CD「镜像/源码不一致」调查结论

**不存在 CD 构建或发布缺陷；上一轮异常由一次人工操作引起，已消解。**

- `.deployed-versions` 显示 CD 于 `2026-11-20T08:22:29Z` 部署 `c08921e1fd1c`；`c08921e1fd1c` 镜像内确有 `adapters/codex/home_config.py` 与 `ExecutionConfig.codex`。
- 上一轮为应用带 Codex 挂载的新 compose，在未 `export NEXUSDESK_VERSION` 的情况下执行了
  `docker compose ... up -d --force-recreate --no-deps app`。Compose 因而读取
  `deploy/quickstart/.env` 里**过期的** `NEXUSDESK_VERSION=98688f1d7343`（11‑19 的镜像，无 `home_config.py`），
  把运行中容器静默回滚到旧镜像；随后为推进验收又向该旧容器人工同步了源码，形成「源码有、镜像无」的错层。
- CD 的 `deploy` job 通过 `export NEXUSDESK_VERSION="${IMAGE_TAG}"` 只对当次 shell 生效，从不写回 `.env`，
  因此 `.env` 会长期滞留旧 tag —— 这是**真实的运维陷阱**：任何不带 export 的手工 `docker compose up -d` 都会静默回滚。
- 本轮处置：#155 合并 → CI `44715956443` success → CD `44716695070` 构建并部署 `63221a1fd3ba`；
  随后把主机 `.env` 的 `NEXUSDESK_VERSION` 修正为 `63221a1fd3ba`，`docker compose config` 复核解析出的 image 一致。
  容器从干净镜像重建，`/app` 零可写层改动。

**建议后续（不在本阶段修复）**：在 CD `deploy` job 于 `up -d` 成功后把 `NEXUSDESK_VERSION` 写回
`deploy/quickstart/.env`（或从该文件移除该键使其必须显式提供），否则下一次部署后该陷阱仍会复现。

## 6. 残留与边界

1. **容器内 Codex 工具执行被 Docker 默认 seccomp 阻断 —— 记录为阶段边界（已确认）。**
   干净镜像上第 3 轮输出：`bwrap: No permissions to create a new namespace...`，
   且 `Approval policy is set to never, so I can't retry unsandboxed`；容器内 `unshare -Ur true` → `Operation not permitted` (exit 1)。
   宿主 `kernel.unprivileged_userns_clone=1`、`max_user_namespaces=14170` 均正常，故为容器 seccomp profile 限制，
   **与源码覆盖层无关**。轮次执行、事件流、凭据链路、usage 落账均不受影响，仅「需要沙箱的工具调用」不可用。
   属部署加固决策（seccomp profile / sandbox 模式），本阶段不改默认安全姿态。
2. **`runtime_host_processes` 行收在 `cleanup_failed` / `runtime_host_identity_mismatch`。**
   第 1 轮 pid 175，`process_start_token=linux:1297623818:4ae919bebc9b53c1`，
   `metadata={"recovery":"identity-unverified","executable_id":"codex"}`。
   按 `03 §4.4` 的 `orphan_decision`：进程在核对时仍判为 alive 且 start token 无法匹配 → `no_signal`
   （**禁止启发式 kill**），故保守记为 `cleanup_failed`。复查容器内无任何残留 codex 进程 / pid 175，
   **无孤儿进程、无凭据与 workdir 泄漏**。建议后续专项：让 CLI lane 的进程身份可验证，使该行能收在正常终态。
3. 失败/成功 Run 的 `/observability/runs/{id}/trace` 均不含事件列表 —— **非缺陷**：该接口按设计只投影
   `runtime_runs` + `gateway_calls` + `tool_calls`（见 `observability/service.py::trace`），
   事件日志由独立的 `/events` 端点提供。上一轮把它记为「读路径缺口」系探针误判，此处更正。
4. Usage ledger 对 Codex run **有** `engine_terminal` 行；上一轮「无落账」系查询表名/时窗误判，此处更正。
5. 真实 API key 未写入仓库、提交、文档或日志；所有 `AGENT_EXECUTION_*` / `AGENT_CODEX_*` 默认仍为 false；
   `sandbox_required=true`、`network_default_deny=true`。高风险启用（生产 Codex 路由、Stage B、不可信租户）**未请求、未授权**。

## 7. 门禁判定

| 项 | 结论 |
|---|---|
| 修复正确性 | **通过**：本地 `pytest -m "not postgres"` 2368 passed / 6 skipped / 661 deselected；ruff、architecture gate、`git diff --check` 干净 |
| CI | **通过**：#155 head `b228570` 5/5 success；merge `63221a1` push CI `44715956443` success |
| 干净镜像可复现 | **通过**：CD `44716695070` 3/3 success；`docker diff` 零 `/app` 改动；D-1…D-4 与 `home_config.py` 均在镜像内 |
| 真实 Stage A 轮次 | **通过**：两轮 `completed` / `output=OK`，8 事件/轮；凭据 `grant_issued → grant_used`；usage 落账 |
| 工具执行 / 沙箱 | **范围边界**：见 §6.1，不属本阶段门禁 |
| Stage B | **保持锁定**，本轮未触碰 |

**判定：通过（范围限定 / PASS scope-limited）。** 本记录确认的是 P7 Stage A 端到端链路的范围限定验收，
不含高风险能力启用、生产发布授权或 Stage B 放行。

## 8. 单一验收记录（人工验收签署）

| 字段 | 值 |
|---|---|
| 验收负责人 | **JackChow**（用户本人；本轨道所有签字人均为同一人，单一验收负责人） |
| 签署确认 | **已确认签署**：用户于 2026-11-20 18:49（GMT+8，即 2026-11-20T10:49Z）在对话中明确确认「验收记录结论为通过（范围限定 / PASS scope-limited），单一签字人 JackChow，确认签署」，据此填写本单一验收记录；无未完成签署项 |
| 执行人 | WorkBuddy 自动化验收执行 |
| 日期 (UTC) | 2026-11-20 |
| 目标 SHA | `63221a1fd3bad7562b351b7bbbd23e0c95500cb6` |
| 镜像 tag | `ghcr.io/groundedcoreai/nexusdesk-quickstart:63221a1fd3ba` |
| 证据 run id | `99563a82-…`（clean turn 1）、`d8c72fd7-…`（clean turn 2）、`aa9ab8f2-…`（seccomp boundary） |
| 结论 | **通过（范围限定 / PASS scope-limited）** |
| 残留 | §6.1 沙箱边界（已确认记录）、§6.2 `cleanup_failed` 保守终态；均非当前阶段门禁 |
| 高风险启用 | 未请求、**未授权** |

> 签署范围说明：按最小核心团队标准，阶段验收只要求单一验收负责人记录，不要求产品/QA/研发/安全等多角色签字；
> 各 `07` 报告中保留的历史多角色签字表为历史背景，其 `pending` / `unsigned` 状态不再作为门禁，以 `12` 与本记录为准。

## 9. English summary

Scope-limited P7 Stage A acceptance at merge SHA `63221a1` on a **clean CI-built image**
(`ghcr.io/...:63221a1fd3ba`, CD run `44716695070`, `docker diff` shows zero `/app` overlay changes). PR #155 fixed four
blocking defects between "publish works" and "a real Codex turn runs": D-1 (model-profile gate wrongly required for CLI
engines), D-2 (`RuntimeFactory` passed where a callable was expected, breaking the Phase 3 barrier for React too),
D-3 (512 MiB `RLIMIT_AS` killed Node/V8 with SIGTRAP; 1 GiB floor), D-4 (adapter built from a deployment placeholder
instead of the published `codex` block, so the credential Broker was never invoked and grants were zero).

On the clean image with Codex CLI 0.169.0: two consecutive turns `completed` with `output="OK"` and eight ordered
`runtime_events` each (`run.queued → run.started → codex.thread.started → codex.item.completed → codex.turn.started →
codex.item.completed → codex.turn.completed → run.completed`), credential audit `grant_issued → grant_used`, workdir
`retained`, and an `engine_terminal` usage-ledger row. Local gates: 2368 passed / 6 skipped, ruff + architecture gate
+ `git diff --check` clean; CI 5/5 on `b228570` and success on the merge.

The earlier "CD image/source mismatch" is **fully explained and not a CD defect**: CD did deploy `c08921e1fd1c`
correctly, but a manual `docker compose up -d --force-recreate` without `export NEXUSDESK_VERSION` read the stale
`.env` pin (`98688f1d7343`, an 11‑19 image) and silently rolled the container back; a hand-synced source overlay into
that old container produced the observed split. The `.env` pin is now corrected to `63221a1fd3ba`. Two earlier findings
are retracted as probe artefacts: `/trace` is by design a `runtime_runs`/`gateway_calls`/`tool_calls` projection (events
come from `/events`), and the usage ledger does have a row.

Remaining scope boundaries: Docker's default seccomp blocks Codex's `bwrap` sandbox, so tool calls needing it fail
(`unshare -Ur` → EPERM) while turns, events, credentials and usage are unaffected — confirmed on the clean image and
recorded as a deployment-hardening boundary, not a code defect. The host-process row ends `cleanup_failed` /
`runtime_host_identity_mismatch` as a deliberate fail-closed `no_signal` outcome (`03 §4.4`, no heuristic kill); no
orphan process remains. Stage B stays locked and high-risk enablement is not authorized. Verdict: **PASS (scope-limited)**.
