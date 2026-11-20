# Phase 5 · Stage A CLI Engine 启用 — 设计（启用轨道提案）

> 状态：**设计提案 — 未实施、未授权、不作为验收证据。**
> 创建：2026-11-20
> 语言：按 `08` R8，英文为权威新文本，见 `09-stage-a-cli-engine-enablement-design.en.md`；
> 本文为中文镜像，章节 / Gate / FR / PR 编号与英文版一一对应。
> 编号：`09` 仅属于 `phase-5-codex-integration/` 目录，与根目录
> `09-acceptance-execution-runbook.md` 无关。
> Stage B（`codex/app_server`）**保持锁定**，不在本设计范围内。

> 依据记录：`08-implementation-breakdown.md`（R1–R18、L147 协调规则）、
> `05-acceptance-plan.md` §5/§6.1（C1–C10、范围受限门禁重分类）、
> `07-acceptance-report.md` §9（历史结论逐字保留）、
> `12-scope-limited-acceptance-record-20261118-phase4-6.md`（PASS scope-limited，明确
> **不**授权 Codex 启用、生产路由或不可信租户）、
> `docs/architecture/agent-execution-platform-v2.md` §10.1–10.2（Credential Broker 与
> "Never" 清单）、`03-technical-design.md`、PR #147（quickstart 开关参数化），以及
> 2026-11-19 的宿主机独立验证。

## 0. 本文为何存在

Phase 5 交付的是一套 **fail-closed 的 Stage A 骨架**：类型化 `CodexConfig` +
`CodexStageGate`、一个注册了 `codex` Engine 与两个 Protocol 的注册表、把
`ExecutionRequest → ProcessSpec → RuntimeHost` 串起来的 `CodexCliAdapter`、有界原生
事件/用量映射，以及 R18 的有界 stdin prompt 通道。它**故意**没有让生产 Run 触达
Codex：`08` L141 列出了刻意未做项，`07` §9 与 `12` 号记录把它们保留为历史事实。因此
"Phase 5 通过（范围限定）"不等于"Codex CLI engine 可用"——见 `08` R11/R13/R15/R16/R17
与下文六道闸门。

`08` L147 要求：任何改变**公共契约或门禁**的发现，**必须在改代码前先更新 `08` 与
`03`**。本文即该更新。它只是设计/裁决提案：为未来的启用轨道翻转*工程*裁决、记录凭据
机制、排定代码 PR 顺序。它不打开任何开关、不改变任何运行时默认、不授予任何启用或
安全批准。

宿主机独立验证（2026-11-19，运维工作机，平台之外）：`codex` 0.169.0 + Node v22.23.5，
自定义 `[model_providers.*]` provider（`wire_api = "responses"`，密钥经 `env_key` 命名的
环境变量传入）连到真实 OpenAI-Responses 兼容端点；`codex exec --json` 完成了一个完整
`thread.started → item.completed(agent_message) → turn.completed(usage)` turn 与一个带
工具调用（`command_execution`）的 turn，均 exit 0。这证明 Gate 6 的前提（二进制 + 认证 +
可达 provider）在目标宿主机上可满足。它**没有**触碰 Gate 1–5，这些闸门仍按交付状态锁定。

## 1. 两套编号体系 — 不可混用

Phase 5 文档集使用了两套不同的 "C" 编号。翻转错的一套会豁免掉安全否决项。这是本提案
最重要的一处更正。

| 体系 | 定义位置 | 性质 | 举例 | 本提案 |
|---|---|---|---|---|
| **合规核对项 C1–C10** | `05-acceptance-plan.md` §5 | 验收合规；**C1/C2/C3/C4 为一票否决项** | C1 明文 Secret 不得进配置/日志/事件/SSE；C2 不得复制/挂载宿主 `~/.codex/auth.json`、不得跨租户共享凭据目录；C3 Phase 6 前不可信租户开放数为 0；C4 Workspace 穿越/symlink/跨租户拒绝 + Resume 重新鉴权 | **绝不翻转。** 下文每道闸门都必须满足 C1–C4；§4 将凭据设计逐条映射到它们。 |
| **实施期协调约束 C1/C2/C4/C5** | `08` §2（R10 "coordinator C2"、R11 "coordinator C1"、R13 "(C5)"、R15 "与 C4 冲突"） | fail-closed 实施轮次中作出的工程协调裁决 | C1 不动 Worker/Orchestrator 默认 selector；C2 不改 Host；C4 不给 `ExecutionConfig` 加 Codex block；C5 保持 `workspace_required=True` | **在 §5 翻转**，附明确条件与 PR 门禁。它们是设计决策，不是安全否决项。 |

`05` 的 C 集与 `08` 的 C 集互不相关。启用请求中的"翻转 C4/C5"指的是 `08` 的协调约束，
**不是** `05` 的一票否决项。否决项恰恰是凭据设计的承重墙：架构 §10.2 "Never" 清单
（Agent Configuration 不得存明文 API key、token 不得写入日志/普通 Runtime Events、不得把
宿主 `~/.codex/auth.json` 复制进租户执行环境、不得跨租户共享凭据目录）逐字保留并强制
执行，不放宽。

## 2. 目标与非目标

**目标**

- G-E1 让 `codex/cli_exec/v1` 成为**按 Run 可选**、由已发布 Agent 配置决定的 Engine，
  仅面向显式可信租户，全局默认仍为 `react/native/v1`。
- G-E2 以契合现有契约的最小改动关闭六道闸门（`08` 范围规则 L6），**消费** Phase 6 的
  `ExecutionCredentialBroker` 接缝，而不是另造一条凭据路径。
- G-E3 保留全部 fail-closed 默认：不设置开关时容器行为与今天字节级一致（PR #147
  不变量、`test_agent_execution_phase4_deployment.py`）。
- G-E4 产出可给客户演示的 quickstart 路径与诚实的 Stage A 解锁记录。

**非目标**

- Stage B：`app_server` 保持 `enabled=False`、factory 仍抛错，Session/Turn/Resume/审批/
  交互输入/传输均未实现；解锁仍需 `P5-IT-18` 与独立批准记录（05 §6.1、08 §1）。
- Phase 6 完整 Broker + 强沙箱落地前，不向不可信多租户开放代码执行。
- 用模型网关作为凭据来源。网关是基于 `gateway_credentials`（Fernet）的**进程内 HTTP
  客户端**，既无 OpenAI 兼容入站端点，也无为 CLI 进程写 `OPENAI_API_KEY` /
  `CODEX_HOME/auth.json` 的路径。`03` §"模型调用路径"已记录 Codex 不假定经过它。
- 改写历史验收结论、数字或证据（07 §9、05 §6）。

## 3. 逐闸门设计

六道闸门当前把"descriptor 已启用"与"一个 Run 真正执行并完成 Codex 认证"隔开。目标
宿主机上 Gate 0 已打开；Gate 1–5 是代码级。

| 闸门 | 当前锁点 | 代码接缝（2026-11-20 核实） | 本轨道改动 |
|---|---|---|---|
| G0 descriptor | `CodexStageGate` fail-closed | `adapters/codex/config.py`；`runtime_composition.py` `_codex_adapters` | 在设置 PR #147 开关处**已打开**：gate 通过、Host 装配、`codex/cli_exec/v1` descriptor 已是 `enabled=True`。无需新工作。 |
| G1 发布 + UI | R15 + 协调约束 C4 | `contracts/config.py:73` `ExecutionConfig`（仅 `engine`/`react`）；`registry/adapter_registry.py::validate_config` 恒喂 `normalized.react`；`platform_routes.py` 字段投影；`frontend/.../ExecutionConfigSection.tsx`（engine 只读、`SUPPORTED_ENGINES` 仅 react） | 加 `codex: CodexConfig \| None`；`validate_config` 按 engine 分发；`react_matches_engine` 改为互斥；扩展 DTO/SDK/normalizer；加 engine 选择器 + Codex 表单。公共契约变更 → P1。 |
| G2 路由 | R11 + 协调约束 C1 | `orchestration/execution_context.py` `PRODUCTION_ADAPTER_SELECTOR = ("react","native","v1")`；`orchestrator.py` 约 10 处 `resolve(*self._selector)`/`metadata(*...)`；`runtime_composition.py` 构造与非生产 selector 标记 | 把全局常量改为**按 Run 从已发布 engine 身份解析**；能力解析、快照屏障、事件映射、workdir provider 按 engine 分支。最大改动 → P2。 |
| G3 workspace | R13 + 协调约束 C5 | `NoTrustedWorkspaceGeneration` → `workspace_unavailable`；屏障在 `adapter.start()` 前拒绝；`orchestrator.py` 已预留 seam | 在现有端口后接真实 `WorkspaceProvider`。**绝不**设 `workspace_required=False`（R13）。→ P3。 |
| G4 可信目标 | R16 | `runtime_composition.py` `ProcessRunner(TrustedTargetRegistry(()))`；描述符形状见 `host/process_runner.py` | 以容器内绝对 `executable_path`、`fixed_prefix`、`max_parameters`、`parameter_pattern` 注册 `CODEX_CLI_EXECUTABLE_ID`，与 Gate 6 挂载路径绑定。→ P4。 |
| G5 凭据 | R17 / FR-6 / 架构 §10.2 | `adapters/codex/adapter.py` 存了 `credential_broker`/`credential_ref` 但 `start()` 未把 `credential_ref` 传给 `_host.start()`；`host/runtime_host.py:180-280` `start(credential_ref: UUID \| None)` → `issue`→`consume`→`secret_env["EXECUTION_CREDENTIAL"]`；`CodexConfig.credential_ref: str \| None` 仅占位；`ProcessSpec.environment` 只有类型化 `PATH`（R17） | 消费 Phase 6 Broker：把 `credential_ref` 解析为凭据 UUID、传给 `host.start`，把消费出的 Secret 映射到 provider 的 **`env_key` 变量名**，置于每 Execution 私有 `CODEX_HOME`。完整设计见 §4。→ P6，需安全签字。 |
| G6 二进制 + 认证 | 部署 | PR #147 参数化了 `AGENT_CODEX_PATH_ENV`、`AGENT_EXECUTION_RUNTIME_HOST_ID`、Codex Stage A 开关；2026-11-19 宿主验证 | 保持绝对路径的窄只读卷挂载（`~/.npm-global`、Node 运行时、无密钥 `config.toml`），绝不挂整个 `/home/nexus`。不增加镜像复杂度。→ P5。 |

### 3.1 G5 与 G6 相互耦合，这是关键

Codex 通过 `codex login --with-api-key`（写 `CODEX_HOME/auth.json`）或
`[model_providers.<id>].env_key` 命名的环境变量认证；其 `config.toml` 只带 `base_url`、
`env_key`、`wire_api`，**不含明文密钥**。0.169.0 上 `wire_api = "chat"` 已移除，只接受
`"responses"`（宿主机实测）。而平台 Host 按 R17 只给子进程一个类型化环境变量（`PATH`），
Secret 没有字段可承载。天真地"把 `~/.codex/.env` 挂进容器"会：(a) 因把宿主认证材料复制进
租户执行环境而越过架构 §10.2 Never 红线，(b) 跨租户共享凭据目录，(c) 与 R17 冲突。
该做法明确否决。

## 4. 凭据设计（Gate 5）— 安全关键部分

### 4.1 已测量的现状

- Phase 6 已有 `ExecutionCredentialVault` + `ExecutionCredentialBroker` +
  `execution_credentials` 表 + 管理 API `/api/v1/execution-credentials`（create/rotate/
  revoke，**无读 Secret 端点**）。记录带 `credential_ref`、`allowed_engines`、
  `allowed_workspaces`、`credential_type`、`public_metadata`；Secret 只存于 vault
  （安装密钥），绝不进 Agent 配置。
- `RuntimeHost.start(..., credential_ref: UUID | None)` 已实现正确生命周期：spawn 前
  `issue`、`consume` 成短期 token、注入 `secret_env["EXECUTION_CREDENTIAL"]`、退出时
  revoke/清理、issue/consume 任一失败即 fail closed、Secret 不进
  `command_digest`/记录（`runtime_host.py:242-343`）。
- `CodexCliAdapter` **当前没用它**：存了 broker/ref 却调 `_host.start()` 时不带
  `credential_ref`；`CodexConfig.credential_ref` 是未强制的 `str` 占位符。
  `ProcessSpec.environment` 只有 `PATH`（R17）。
- 模型网关不在这条链路上（§2、`03` §"模型调用路径"）。

### 4.2 目标机制（提案）

1. **只存引用，不存值。** 已发布 Agent 只存 `credential_ref`（指向
   `execution_credentials` 行的 UUID）与类型化 `credential_env_key`（白名单内的环境变量
   名，如 `OPENAI_API_KEY` 或部署方 provider 专用 key）。明文密钥不进
   `ExecutionConfig`、DTO、快照、事件、日志、argv、stdin payload、`command_digest`
   —— C1、R18。
2. **启动期解析。** `CodexCliAdapter.start` 校验 gate 后，检查 `allowed_engines` /
   `allowed_workspaces` / 租户绑定，把 `credential_ref` 解析成凭据 UUID，并传给
   `_host.start(credential_ref=...)`。
3. **由 Broker 完成注入。** 原样复用 `issue → consume → secret_env`。给 Host 增加**一个
   类型化、白名单化**的环境槽，把消费出的 Secret 从通用 `EXECUTION_CREDENTIAL` 映射到
   声明的 `credential_env_key`。这是类型化字段，不是自由 env map —— R17 的注入面论证
   得以保留。Secret 上 `repr=False, exclude=True`（R18 纪律），绝不持久化。
4. **每 Execution 私有 `CODEX_HOME`。** Workspace Provider（G3）为每次 Execution 创建
   租户隔离的私有目录；平台在其中写**无密钥** `config.toml`（`model`、
   `model_provider`、`[model_providers.*]` 带 `base_url`、
   `env_key = <credential_env_key>`、`wire_api = "responses"`），并通过类型化 Host 槽把
   `CODEX_HOME` 指向它。不挂宿主 `~/.codex`、不复制 `auth.json`、不共享目录、Secret 不落盘
   —— C2、C4、架构 §10.2。
5. **生命周期 = 进程生命周期。** Secret 只在该进程组的子进程环境中存在；Host 在取消/
   超时/退出时 revoke grant，并把每 Execution `CODEX_HOME` 随 workdir 一起清理
   （FR-3、`03` §"取消与超时"）。
6. **无 Secret 审计。** 只记 `(tenant, execution, credential_ref, engine, decision)`，
   不记值。复用现有无读 Secret 管理 API。

### 4.3 映射到否决项（§1）

| 否决项 | 要求 | §4.2 如何满足 |
|---|---|---|
| 05 C1 | 明文 Secret 不进配置/日志/事件/SSE/错误 | 配置里只有 `credential_ref`（UUID）+ `credential_env_key`（名字）；Secret 只在子进程环境；`exclude=True`；无读 Secret 端点。 |
| 05 C2 | 不复制宿主 `auth.json`、不共享凭据目录 | 每 Execution `CODEX_HOME` + 生成的无密钥 `config.toml`；宿主 home 从不挂载；目录不跨租户共享。 |
| 05 C3 | Phase 6 前不可信租户开放数为 0 | Stage A 开关 + `codex_trusted_tenants` 白名单保持 fail-closed（PR #147）；默认关闭；解析时校验租户绑定。 |
| 05 C4 | Workspace 穿越/symlink/跨租户拒绝 | G3 的真实 `WorkspaceProvider` 拥有每 Execution `CODEX_HOME`；workspace 校验不变。 |
| 架构 §10.2 "Never" | AgentConfig 无明文 key；日志/事件无 token；不复制 `~/.codex/auth.json`；不共享目录 | 四条全部覆盖。§10.2 明确允许"受控环境变量注入或 secret 挂载……接口应可演进到专用 Credential Broker" —— §4.2 用的是**已存在**的 Broker，是更强的形式。 |

### 4.4 明确否决的替代方案

- 把宿主 `~/.codex`、`auth.json` 或 `~/.codex/.env` 挂进容器。
- 从部署 `.env` 把 `DEEPSEEK_API_KEY`/`OPENAI_API_KEY` 直接注入 app 容器环境（绕过
  租户/Execution 作用域、残留在 `docker inspect`、容器内所有进程可见）。
- 把 `ProcessSpec.environment` 放宽成自由 `dict[str, str]`（R17）。
- 把 Codex 指向模型网关当 OpenAI 兼容端点（不存在该入站端点）。

### 4.5 安全评审清单（阻断 P6）

以下必须由安全负责人在**任何凭据 lane 代码合并前**签字。本提案不构成该签字。

1. Secret 传输：`issue → consume → 子进程环境 → revoke` 全程没有窗口让值被记录、快照、
   序列化进 Run/Event/Outbox，或从 `runtime_host_processes` 恢复。
2. `credential_env_key` 白名单是闭集、不可由客户端控制；`env_key`/`config.toml` 不匹配
   时 fail closed。
3. 每次启动重新校验租户/Execution/Workspace/Engine 绑定；凭据轮换或吊销后立即拒绝新
   Execution。
4. 每 Execution `CODEX_HOME` 在取消、超时、崩溃、清理失败路径上的清理均有证据；无
   孤儿目录残留带有效 `env_key` 的 `config.toml`。
5. 05 C1/C2 与 AC-6 的对抗用例（宿主 auth 复制、Secret 输出、跨租户启动）在 lane 启用
   状态下重跑并通过。

## 5. 拟翻转的实施裁决（供 `08` §3 登记）

`08` §2（R1–R18）**逐字保留**为历史裁决记录（07 §9）。下表只登记启用轨道的拟翻转项；
每项仅在其 PR 落地且对应门禁签字后生效。本文不授权其中任何一项。

| 裁决 / 约束 | 原内容（fail-closed） | 拟翻转 | 条件 / PR |
|---|---|---|---|
| R11 + 协调约束 C1 | 生产 selector 是硬连线常量；Worker/Orchestrator 默认不动；"目前从生产 Run 触达 Codex 不可能"。 | 改为按 Run 从已发布 engine 身份解析；保留 `react/native/v1` 全局默认与关闭态字节级一致。 | P2；G2；off/on/回滚测试。 |
| R13 + 协调约束 C5 | 接受 `workspace_unavailable` 屏障；绝不设 `workspace_required=False`。 | 在现有端口后接真实 `WorkspaceProvider`。**"绝不 `workspace_required=False`" 条款保留**，不翻转。 | P3；G3；C4 对抗用例。 |
| R15 + 协调约束 C4 | 保持仅 React block 的 `validate_config`；给 `ExecutionConfig` 加 Codex block"与 C4 冲突"。 | `ExecutionConfig.codex` + 按 engine 分发校验 + DTO/SDK/UI。协调约束 C4 在本轨道退役；公共契约变更先文档化（L147）。 | P1；G1。 |
| R16 | `TrustedTargetRegistry(())` 保持为空；注册真实可执行文件是部署决策。 | 以固定 argv 前缀与参数文法注册 `CODEX_CLI_EXECUTABLE_ID`，与 Gate 6 挂载绑定。 | P4；G4。 |
| R17 | `ProcessSpec.environment` 只带一个类型化 `PATH`；凭据/代理/宿主密钥无字段可承载。 | 保留类型化、非自由 map 纪律；增加一个类型化、白名单化槽，把 Broker 消费出的 Secret 映射到 `credential_env_key`。R17 的防注入论证保留。 | P6；G5；§4.5 安全签字。 |
| 协调约束 C2 | "不改 Host"（R10 上下文）。 | 本提案不改任何 Host 签名/契约：`RuntimeHost.start(credential_ref=...)` 与 `secret_env` 已存在（R-18(a) Phase 6）。故 C2 无需翻转 —— lane 消费现有接缝。 | P6；不重写 Host。 |

R10/R18（stdin prompt 通道）、R12、R14、R6、R7、R8、R9 与 Stage B 锁定**不变**。R7
（"Phase 6 安全能力不在范围内"）仅在本轨道*消费*现已存在的 Phase 6 Broker 框架这一意义上
收窄，不新增 Phase 6 能力。

## 6. PR 排期（每阶段可独立评审、独立回退）

| 阶段 | PR | 内容 | 门禁 / 签字 |
|---|---|---|---|
| P0 | **本 PR** | 设计 + 裁决附录（`03`、`08`、`09`），无代码 | 在任何代码前满足 `08` L147 |
| P1 | 契约 | `ExecutionConfig.codex`、按 engine 分发的 `validate_config`、`react_matches_engine`、DTO/SDK/normalizer、前端 engine 选择器 + Codex 表单 | G1 |
| P2 | 路由 | 按 Run 解析 adapter、按 engine 分支的能力/快照/事件/workdir、warm targets | G2；默认关闭回归 |
| P3 | workspace | 真实 `WorkspaceProvider` + 每 Execution `CODEX_HOME` 脚手架 | G3；C4 |
| P4 | 可信目标 | `CODEX_CLI_EXECUTABLE_ID` 描述符 + 测试 | G4 |
| P5 | 部署 | 窄只读卷挂载、`AGENT_CODEX_PATH_ENV`、无密钥 `config.toml` 模板；quickstart 演示文档 | G6；PR #147 开关 |
| P6 | 凭据 lane | Broker 解析/注入/吊销、`credential_env_key` 白名单、审计 | **G5 + §4.5 安全签字（阻断）** |
| P7 | 验收 | 端到端按 Run Codex turn（对话 + 工具）、05/06/07 附录、Stage A 解锁记录 | 完整 Stage A 验收；Stage B 仍锁定 |

§4.5 未签字前 P6 不得合并。P1–P5 各自有价值，且在 P6 + PR #147 开关组合之前部署始终保持
fail-closed。

## 7. 测试基线

- **保留**全部 fail-closed 默认测试，含 `test_agent_execution_phase4_deployment.py`
  （PR #147 修复）与 `test_quickstart_execution_switches_default_fail_closed`
  （PR #147 新增）。所有开关未设置时行为必须字节级一致。
- **新增**各阶段启用路径断言：合法 `CodexConfig` 的 Codex 发布被接受；按 Run `resolve`
  返回 Codex 描述符；可信目标仅在开关打开时注册；`credential_env_key` 白名单拒绝；Secret
  不出现在 repr/dump/digest/事件/日志；跨租户凭据拒绝；off/on/回滚。
- 真实二进制用例在 CI 中仍为 `pytest.skip` 守护的 `pending_env`（CI 无 Codex 二进制）；
  2026-11-19 宿主证据是本地证据，按 05 §6.1 记录 owner。
- 05 C1–C4 否决项与 AC-1–AC-12 仍为验收门禁；无 P0/P1。

## 8. 上线与回滚

1. 全阶段带开关关闭部署；确认 PR #147 默认关闭 diff 为零。
2. 用 `codex_allowed_versions` + `codex_trusted_tenants` 白名单对单个可信租户启用；
   经公共 API 验证一次按 Run 的 Codex turn（公共响应无宿主细节）。
3. 回滚顺序：关闭开关（P5/P6）→ 停止新 Codex Run → Host 清理活动进程 → 视需要回退
   P1–P4。无 down migration、不删表、不改写历史 Run（`03` §"上线与回滚"）。
4. 任一 Secret 泄露、跨租户访问、孤儿进程失控，立即停止新执行并关闭开关；绝不通过
   放宽沙箱或凭据策略恢复可用性。

## 9. 需负责人签字的待决事项

1. **设计基线变更**：授权为本轨道翻转 `08` 书面裁决 R11/R13/R15/R16 与协调约束
   C1/C4/C5（§5）。这是 P1 的门禁。
2. **凭据来源**：使用哪个 provider / API key / `base_url` / model，以及谁负责密钥轮换；
   模型网关无法提供（§2）。
3. **范围档位**：仅 quickstart 演示，还是生产多租户（后者还需 Phase 6 完整 Broker +
   强沙箱，不在本设计范围）。
4. **Stage B**：确认排除在本轨道之外（建议）。

## 10. 负责人决策记录（2026-11-20，JackChow）

§9 四项已由负责人明确答复，记录如下。本记录只确定本启用轨道的范围，**不构成 §4.5
的安全签字**。

1. **设计基线变更：授权全部翻转**（P1 门禁已满足）。§5 表中 R11/R13/R15/R16/R17
   与协调约束 C1/C4/C5 按所列条件与 PR 门禁执行；`05` 的一票否决项 C1–C4、架构
   §10.2 "Never" 清单、以及 R13 的「绝不 `workspace_required=False`」条款均**不翻转**。
2. **凭据来源：复用已验证的 DeepSeek**。`deepseek-flash`，`base_url=https://api.deepseek.com/v1`，
   `wire_api=responses`（0.169.0 实测 `chat` 已移除）。key 仅用于 quickstart 演示；
   P6 必须通过 `/api/v1/execution-credentials` 登记为 `credential_ref`，**不得**挂载
   宿主 `~/.codex/.env`，也不得把部署 key 直接注入 app 容器环境。密钥轮换/吊销由部署方
   （JackChow）负责；轮换或吊销后新 Execution 必须 fail closed。
3. **范围档位：仅 quickstart 演示**。单可信租户 `local` + 窄只读挂载。生产多租户不在
   本轨道授权内，须待 Phase 6 强沙箱（固定镜像 + daemon 探测 + egress allowlist）与
   独立安全/运维审批后另起设计轨道。
4. **Stage B：排除**。`app_server` 保持 `enabled=False`、factory 抛错；Session 表、
   Resume 重鉴权、审批与交互输入、P5-IT-18 与独立解锁记录均不在本轨道。

**仍未满足的门禁**：§4.5 安全评审清单（5 项）须在 P6 凭据 lane 合并前由安全负责人
签字，签字人待指定；P0（本设计 PR）须先合并，P1 才开工。
