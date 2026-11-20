# Phase 5 · Stage A CLI Engine Enablement — Design (enablement-track proposal)

> Status: **enablement-track design baseline — P0–P3 merged (PRs #148–#151),
> P4–P7 proceed under this file. This file is neither acceptance evidence nor a
> security sign-off.**
> Created: 2026-11-20
> Language: English is the authoritative new text per `08` R8; the Chinese mirror is
> `09-stage-a-cli-engine-enablement-design.md` and carries the same section/Gate/FR IDs.
> Numbering: `09` is local to `phase-5-codex-integration/` and is unrelated to the
> root-level `09-acceptance-execution-runbook.md`.
> Stage B (`codex/app_server`) **stays locked** and is out of scope.

> Governing records: `08-implementation-breakdown.md` (R1–R18, L147 coordination rule),
> `05-acceptance-plan.md` §5/§6.1 (C1–C10, scope-limited gate reclassification),
> `07-acceptance-report.md` §9 (historical verdicts retained verbatim),
> `12-scope-limited-acceptance-record-20261118-phase4-6.md` (PASS scope-limited, which
> explicitly does **not** authorize Codex enablement, production routing, or untrusted
> tenants), `docs/architecture/agent-execution-platform-v2.en.md` §10.1–10.2 (Credential
> Broker and the "Never" list), `03-technical-design.en.md`, PR #147 (parameterized
> quickstart switches), and the host-side independent verification of 2026-11-19.

## 0. Why this document exists

Phase 5 shipped a **fail-closed Stage A skeleton**: a typed `CodexConfig` + `CodexStageGate`,
a registered `codex` Engine with two Protocols, a `CodexCliAdapter` that maps
`ExecutionRequest → ProcessSpec → RuntimeHost`, bounded native-event/usage mapping, and the
R18 bounded stdin prompt channel. It deliberately did **not** make Codex reachable from a
production Run. `08` L141 lists the deliberate omissions; `07` §9 and the `12` record keep
them as historical facts. Consequently "Phase 5 passed (scope-limited)" does not mean "a
Codex CLI engine is usable" — see `08` R11, R13, R15, R16, R17 and the six gates below.

`08` L147 requires that any discovery changing a public contract or a gate **updates `08`
and `03` before code changes**. This document is that update. It is a design/decision
proposal only: it reverses the *engineering* rulings for a future enablement track, records
the credential mechanism, and sequences the code PRs. It flips no switch, changes no
runtime default, and grants no enablement or security approval.

Host-side independent verification (2026-11-19, operator workstation, outside the platform):
`codex` 0.169.0 + Node v22.23.5, a custom `[model_providers.*]` provider with
`wire_api = "responses"` and an `env_key`-named environment variable, reached a real
OpenAI-Responses-compatible endpoint; `codex exec --json` completed a full
`thread.started → item.completed(agent_message) → turn.completed(usage)` turn and a
tool-using (`command_execution`) turn, both exit 0. This proves Gate 6's premise (binary +
authentication + reachable provider) is satisfiable on the target host. It does **not**
touch Gates 1–5, which remain locked exactly as shipped.

## 1. Two numbering systems — do not conflate

The Phase 5 corpus uses two distinct "C" numbering systems. Reversing the wrong one would
waive a security veto. This distinction is the single most important correction in this
proposal.

| System | Defined in | Nature | Examples | This proposal |
|---|---|---|---|---|
| **Compliance checks C1–C10** | `05-acceptance-plan.md` §5 | Acceptance compliance; **C1, C2, C3, C4 are VETO items (一票否决)** | C1 no plaintext Secret in config/logs/events/SSE; C2 no copying/mounting host `~/.codex/auth.json`, no cross-tenant credential dirs; C3 untrusted-tenant exposure = 0 before Phase 6; C4 Workspace traversal/symlink/cross-tenant denied + Resume reauthorization | **Never reversed.** Every Gate below must satisfy C1–C4; §4 maps the credential design onto them. |
| **Implementation-time coordinator constraints C1/C2/C4/C5** | `08` §2 (R10 "coordinator C2", R11 "coordinator C1", R13 "(C5)", R15 "contradict C4") | Engineering coordination rulings made during the fail-closed implementation round | C1 don't touch the Worker/Orchestrator default selector; C2 don't modify the Host; C4 don't add a Codex block to `ExecutionConfig`; C5 keep `workspace_required=True` | **Reversed in §5**, with explicit conditions and PR gates. These are design decisions, not safety vetoes. |

The `05` C-set and the `08` C-set are unrelated. In particular, "flip C4/C5" in the
enablement request refers to the `08` coordinator constraints, **not** to the `05` veto
items. The veto items are load-bearing for the credential design: the architecture §10.2
"Never" list (no plaintext API keys in Agent Configuration, no tokens in logs/ordinary
Runtime Events, no copying the host `~/.codex/auth.json` into tenant execution
environments, no shared credential directories across tenants) is preserved verbatim and
enforced, not relaxed.

## 2. Goals and non-goals

**Goals**

- G-E1 Make `codex/cli_exec/v1` a **per-Run selectable Engine** chosen from the published
  Agent configuration, for explicitly trusted tenants only, with the global default still
  `react/native/v1`.
- G-E2 Close all six gates with the smallest change that fits the existing contracts
  (`08` scope rule L6), consuming the Phase 6 `ExecutionCredentialBroker` seam rather than
  inventing a second credential path.
- G-E3 Preserve every fail-closed default: with no switches set, container behavior is
  byte-identical to today (PR #147 invariant, `test_agent_execution_phase4_deployment.py`).
- G-E4 Produce a customer-demoable quickstart path and an honest Stage A unlock record.

**Non-goals**

- Stage B: `app_server` stays `enabled=False`, its factory still raises, and
  Session/Turn/Resume/approval/interactive-input/transport remain unimplemented. Unlocking
  it still requires `P5-IT-18` and a separate approval record (05 §6.1, 08 §1).
- Untrusted multi-tenant code execution before Phase 6's complete Broker + strong sandbox.
- Using the Model Gateway as a credential source. The gateway is an in-process HTTP client
  over `gateway_credentials` (Fernet) and has **no OpenAI-compatible inbound endpoint** and
  **no path that writes an `OPENAI_API_KEY`/`CODEX_HOME/auth.json` for a CLI process**.
  `03` §"Model Invocation Path" already records that Codex does not pass through it.
- Rewriting historical acceptance verdicts, numbers, or evidence (07 §9, 05 §6).

## 3. Gate-by-gate design

Six gates currently separate "descriptor enabled" from "a Run actually executes and
authenticates Codex". Gate 0 is already open on the target host; Gates 1–5 are code-level.

| Gate | Lock today | Code seam (verified 2026-11-20) | Change in this track |
|---|---|---|---|
| G0 descriptor | `CodexStageGate` fail-closed | `adapters/codex/config.py`; `runtime_composition.py` `_codex_adapters` | **Open** where PR #147 switches are set: gate passes, Host assembled, `codex/cli_exec/v1` descriptor already becomes `enabled=True`. No new work. |
| G1 publish + UI | R15 + coordinator C4 | `contracts/config.py:73` `ExecutionConfig` (only `engine`/`react`); `registry/adapter_registry.py::validate_config` always feeds `normalized.react`; `platform_routes.py` field projection; `frontend/.../ExecutionConfigSection.tsx` (engine read-only, `SUPPORTED_ENGINES` = react only) | Add `codex: CodexConfig \| None`; dispatch `validate_config` by engine; make `react_matches_engine` mutually exclusive; extend DTO/SDK/normalizer; add an engine picker + Codex form. Public-contract change → P1. |
| G2 routing | R11 + coordinator C1 | `orchestration/execution_context.py` `PRODUCTION_ADAPTER_SELECTOR = ("react","native","v1")`; `orchestrator.py` ~10 `resolve(*self._selector)`/`metadata(*...)` call sites; `runtime_composition.py` construction + non-production-selector markers | Replace the global constant with **per-Run resolution from the published engine identity**; branch capability resolution, snapshot barrier, event mapping and workdir provider by engine. Largest change → P2. |
| G3 workspace | R13 + coordinator C5 | `NoTrustedWorkspaceGeneration` → `workspace_unavailable`; barrier refuses before `adapter.start()`; seam already reserved at `orchestrator.py` | Wire a real `WorkspaceProvider` behind the existing port. **Never** set `workspace_required=False` (R13). → P3. |
| G4 trusted target | R16 | `runtime_composition.py` `ProcessRunner(TrustedTargetRegistry(()))`; target descriptor shape in `host/process_runner.py` | Register `CODEX_CLI_EXECUTABLE_ID` with an in-container absolute `executable_path`, `fixed_prefix`, `max_parameters`, `parameter_pattern`; bind to the Gate-6 mount path. → P4. |
| G5 credential | R17 / FR-6 / architecture §10.2 | `adapters/codex/adapter.py` stores `credential_broker`/`credential_ref` but `start()` never passes `credential_ref` to `_host.start()`; `host/runtime_host.py:180-280` `start(credential_ref: UUID \| None)` → `issue`→`consume`→`secret_env["EXECUTION_CREDENTIAL"]`; `CodexConfig.credential_ref: str \| None` is a placeholder; `ProcessSpec.environment` carries only typed `PATH` (R17) | Consume the Phase 6 Broker: resolve `credential_ref` to the stored credential UUID, pass it to `host.start`, and map the consumed Secret to the **provider's `env_key` variable name** inside a per-Execution private `CODEX_HOME`. Full design in §4. → P6, gated on security sign-off. |
| G6 binary + auth | deployment | PR #147 parameterized `AGENT_CODEX_PATH_ENV`, `AGENT_EXECUTION_RUNTIME_HOST_ID`, Codex Stage A switches; host verification 2026-11-19 | Narrow read-only volume mounts preserving absolute paths (`~/.npm-global`, the Node runtime, a key-free `config.toml`), never the whole `/home/nexus`. No image bloat. → P5. |

### 3.1 G5 and G6 are coupled, and this is the crux

Codex authenticates through `codex login --with-api-key` (writes `CODEX_HOME/auth.json`) or
through the environment variable named by `[model_providers.<id>].env_key`; its
`config.toml` carries `base_url`, `env_key`, `wire_api` and **no plaintext key**. On 0.169.0
`wire_api = "chat"` is removed and only `"responses"` is accepted (verified on host). The
platform's Host, by R17, deliberately gives a child process exactly one typed environment
variable (`PATH`) and no field for a Secret to travel in. A naive "mount `~/.codex/.env`
into the container" would (a) cross the architecture §10.2 Never line by copying host
auth material into a tenant execution environment, (b) share a credential directory across
tenants, and (c) conflict with R17. It is explicitly rejected.

## 4. Credential design (Gate 5) — the security-critical part

### 4.1 Measured current state

- `ExecutionCredentialVault` + `ExecutionCredentialBroker` + `execution_credentials` table
  and admin API `/api/v1/execution-credentials` (create/rotate/revoke, **no read-Secret
  endpoint**) exist from Phase 6. A record carries `credential_ref`, `allowed_engines`,
  `allowed_workspaces`, `credential_type`, `public_metadata`; the Secret lives only in the
  vault (installation key), never in Agent configuration.
- `RuntimeHost.start(..., credential_ref: UUID | None)` already implements the correct
  lifecycle: `issue` before any spawn, `consume` into a short-lived token, inject into
  `secret_env["EXECUTION_CREDENTIAL"]`, revoke/cleanup on exit, fail closed on any
  issue/consume failure, and keep the Secret out of `command_digest`/records (`runtime_host.py:242-343`).
- `CodexCliAdapter` currently **does not use it**: it stores the broker/ref but calls
  `_host.start()` without `credential_ref`; `CodexConfig.credential_ref` is an unenforced
  `str` placeholder. `ProcessSpec.environment` has only `PATH` (R17).
- The model gateway is not part of this path (§2, `03` §"Model Invocation Path").

### 4.2 Target mechanism (proposed)

1. **Reference, not value.** The published Agent stores only `credential_ref` (a UUID
   pointing at an `execution_credentials` row) and a typed `credential_env_key` (an
   allowlisted environment-variable name such as `OPENAI_API_KEY`, or the deployment's
   provider-specific key). No plaintext key in `ExecutionConfig`, DTO, snapshot, event,
   log, argv, stdin payload, or `command_digest` — C1, R18.
2. **Resolve at start.** `CodexCliAdapter.start` validates the gate, resolves
   `credential_ref` to the credential UUID after checking `allowed_engines` /
   `allowed_workspaces` / tenant binding, and passes it to `_host.start(credential_ref=...)`.
3. **Broker does the injection.** Reuse `issue → consume → secret_env` exactly as shipped.
   Extend the Host with **one typed, allowlisted** environment slot that maps the consumed
   Secret from the generic `EXECUTION_CREDENTIAL` to the declared `credential_env_key`.
   This is a typed field, not a free-form env map — R17's injection-surface argument is
   preserved. `repr=False, exclude=True` on the Secret (R18 discipline); never persisted.
4. **Per-Execution `CODEX_HOME`.** The Workspace Provider (G3) creates a private,
   tenant-scoped directory for each Execution. The platform writes a **key-free**
   `config.toml` there (`model`, `model_provider`, `[model_providers.*]` with `base_url`,
   `env_key = <credential_env_key>`, `wire_api = "responses"`) and sets `CODEX_HOME` to it
   through the typed Host slot. No host `~/.codex` mount, no `auth.json` copy, no shared
   directory, no Secret on disk — C2, C4, architecture §10.2.
5. **Lifecycle = process lifetime.** The Secret exists only in the child environment for
   the process group; Host cleanup on cancel/timeout/exit revokes the grant and removes the
   per-Execution `CODEX_HOME` together with the workdir (FR-3, `03` §"Cancellation").
6. **Audit without the Secret.** Record `(tenant, execution, credential_ref, engine,
   decision)` — never the value. Reuse the existing no-read-Secret admin API.

### 4.3 Mapping onto the veto items (§1)

| Veto | Requirement | How §4.2 satisfies it |
|---|---|---|
| 05 C1 | no plaintext Secret in config/logs/events/SSE/errors | Only `credential_ref` (UUID) + `credential_env_key` (name) in config; Secret only in child env; `exclude=True`; no read-Secret endpoint. |
| 05 C2 | no host `auth.json` copy, no shared credential dir | Per-Execution `CODEX_HOME` with a generated key-free `config.toml`; host home never mounted; no directory shared across tenants. |
| 05 C3 | untrusted-tenant exposure = 0 before Phase 6 | Stage A switches + `codex_trusted_tenants` allowlist remain fail-closed (PR #147); default off; tenant binding checked at resolve. |
| 05 C4 | Workspace traversal/symlink/cross-tenant denied | G3's real `WorkspaceProvider` owns the per-Execution `CODEX_HOME`; workspace validation unchanged. |
| architecture §10.2 "Never" | no plaintext key in AgentConfig; no token in logs/events; no `~/.codex/auth.json` copy; no shared dirs | All four covered above. §10.2 explicitly permits "controlled environment-variable injection or secret mounts ... interface should allow evolution to a dedicated Credential Broker" — §4.2 uses the **already-existing** Broker, which is the stronger form. |

### 4.4 Explicitly rejected alternatives

- Mounting host `~/.codex`, `auth.json`, or `~/.codex/.env` into the container.
- Directly injecting `DEEPSEEK_API_KEY`/`OPENAI_API_KEY` from a deployment `.env` into the
  app container's environment (bypasses tenant/Execution scoping, persists in
  `docker inspect`, and is visible to every process in the container).
- Widening `ProcessSpec.environment` into a free-form `dict[str, str]` (R17).
- Pointing Codex at the Model Gateway as an OpenAI-compatible endpoint (no such inbound
  endpoint exists).

### 4.5 Security review checklist (blocking P6)

The following must be signed off by a security owner **before** any credential-lane code
merges. This proposal does not constitute that sign-off.

1. Secret transport: `issue → consume → child env → revoke` has no window where the value
   is logged, snapshotted, serialized into a Run/Event/Outbox, or recoverable from
   `runtime_host_processes`.
2. `credential_env_key` allowlist is a closed set and cannot be client-controlled; a
   mismatched `env_key`/`config.toml` fails closed.
3. Tenant/Execution/Workspace/Engine binding is revalidated on every start; a rotated or
   revoked credential denies new Executions immediately.
4. Per-Execution `CODEX_HOME` cleanup is proven on cancel, timeout, crash, and
   cleanup-failure paths; no orphan directory retains a `config.toml` with a live `env_key`.
5. Adversarial cases from 05 C1/C2 and AC-6 (host-auth copy, Secret output, cross-tenant
   start) are re-run and pass with the lane enabled.

## 5. Proposed reversal of implementation rulings (for `08` §3)

`08` §2 (R1–R18) is retained **verbatim** as the historical decision record (07 §9). The
table below registers proposed reversals for the enablement track only; each takes effect
only when its PR lands and its gate is signed off. Nothing here is authorized by this
document.

| Ruling / constraint | Original (fail-closed) | Proposed reversal | Condition / PR |
|---|---|---|---|
| R11 + coordinator C1 | Production selector is a hard-wired constant; Worker/Orchestrator defaults untouched; "reaching Codex from a production Run is impossible today". | Replace with per-Run resolution from the published engine identity; keep `react/native/v1` as the global default and preserve off-state byte-identity. | P2; G2; off/on/rollback tests. |
| R13 + coordinator C5 | Accept the `workspace_unavailable` barrier; never set `workspace_required=False`. | Wire a real `WorkspaceProvider` behind the existing port. **The "never `workspace_required=False`" clause is retained**, not reversed. | P3; G3; C4 adversarial cases. |
| R15 + coordinator C4 | Keep React-block-only `validate_config`; adding a Codex block to `ExecutionConfig` "would contradict C4". | `ExecutionConfig.codex` + engine-dispatched validation + DTO/SDK/UI. Coordinator C4 is retired for this track; public-contract change documented first (L147). | P1; G1. |
| R16 | `TrustedTargetRegistry(())` stays empty; registering a real executable is a deployment decision. | Register `CODEX_CLI_EXECUTABLE_ID` with a fixed argv prefix and parameter grammar, bound to the Gate-6 mount. | P4; G4. |
| R17 | `ProcessSpec.environment` carries exactly one typed `PATH`; credentials/proxy/host secrets have no field to travel in. | Keep the typed, non-free-form discipline; add one typed, allowlisted slot that maps the Broker-consumed Secret to `credential_env_key`. R17's anti-injection rationale is preserved. | P6; G5; §4.5 security sign-off. |
| coordinator C2 | "do not modify the Host" (R10 context). | No Host signature/contract change is proposed: `RuntimeHost.start(credential_ref=...)` and `secret_env` already exist (R-18(a) Phase 6). C2 therefore needs no reversal — the lane consumes the existing seam. | P6; no Host rewrite. |

R10/R18 (stdin prompt channel), R12, R14, R6, R7, R8, R9, and the Stage B lock are
**unchanged**. R7 ("Phase 6 security capabilities are out of scope") is narrowed only in
the sense that the enablement track *consumes* the Phase 6 Broker framework that now
exists; it does not add new Phase 6 capabilities.

## 6. PR sequencing (each stage independently reviewable and revertible)

| Stage | PR | Content | Gate / sign-off |
|---|---|---|---|
| P0 | **this PR** | Design + ruling addendum (`03`, `08`, `09`), no code | `08` L147 satisfied before any code |
| P1 | contract | `ExecutionConfig.codex`, engine-dispatched `validate_config`, `react_matches_engine`, DTO/SDK/normalizer, frontend engine picker + Codex form | G1 |
| P2 | routing | per-Run adapter resolution, engine-branched capability/snapshot/event/workdir, warm targets | G2; default-off regression |
| P3 | workspace | real `WorkspaceProvider` + per-Execution `CODEX_HOME` scaffolding | G3; C4 |
| P4 | trusted target | `CODEX_CLI_EXECUTABLE_ID` descriptor + tests | G4 |
| P5 | deployment | narrow read-only volume mounts, `AGENT_CODEX_PATH_ENV`, key-free `config.toml` template; quickstart demo docs | G6; PR #147 switches |
| P6 | credential lane | Broker resolve/inject/revoke, `credential_env_key` allowlist, audit | **G5 + §4.5 security sign-off (blocking)** |
| P7 | acceptance | end-to-end per-Run Codex turn (dialogue + tool use), 05/06/07 addenda, Stage A unlock record | full Stage A acceptance; Stage B still locked |

P6 must not merge before §4.5 is signed. P1–P5 are individually useful and leave the
deployment fail-closed until P6 + the PR #147 switches are combined.

## 7. Test baseline

- **Preserve** every fail-closed default test, including
  `test_agent_execution_phase4_deployment.py` (fixed in PR #147) and
  `test_quickstart_execution_switches_default_fail_closed` (added in PR #147). With all
  switches unset, behavior must remain byte-identical.
- **Add** enabled-path assertions per stage: Codex publish accepted with a valid
  `CodexConfig`; per-Run `resolve` returns the Codex descriptor; trusted target registered
  only when its switch is on; `credential_env_key` allowlist rejection; Secret absent from
  repr/dump/digest/events/logs; cross-tenant credential denial; off/on/rollback.
- Real-binary cases remain `pytest.skip`-guarded `pending_env` in CI (no Codex binary in
  CI); host evidence from 2026-11-19 is local evidence, recorded with owner (05 §6.1).
- 05 C1–C4 veto items and AC-1–AC-12 remain the acceptance gate; no P0/P1.

## 8. Rollout and rollback

1. Deploy all stages with switches off; confirm the PR #147 default-off diff is zero.
2. Enable for one trusted tenant with `codex_allowed_versions` + `codex_trusted_tenants`
   allowlists; verify a per-Run Codex turn through the common API (no host details in the
   public response).
3. Roll back by disabling switches (P5/P6) → stopping new Codex Runs → Host cleanup of
   active processes → optionally reverting P1–P4. No down migration, no table drop, no
   historical Run rewrite (`03` §"Rollout and Rollback").
4. Any Secret disclosure, cross-tenant access, or uncontrolled orphan process stops new
   executions and disables the switches; never restore availability by weakening the
   sandbox or credential policy.

## 9. Open decisions requiring owner sign-off

1. **Design-baseline change**: authorize reversing the written `08` rulings R11/R13/R15/R16
   and coordinator C1/C4/C5 for this track (§5). This is the gate for P1.
2. **Credential source**: which provider / API key / `base_url` / model and who owns the
   key rotation; the Model Gateway cannot supply it (§2).
3. **Scope tier**: quickstart demo-only vs. production multi-tenant (the latter additionally
   requires Phase 6's complete Broker + strong sandbox and is out of scope here).
4. **Stage B**: confirm it stays excluded from this track (recommended).

## 10. Owner decision record (2026-11-20, JackChow)

All four items in §9 have been answered by the owner and are recorded below. This record
settles the **scope of this enablement track only**; it is **not** the §4.5 security
sign-off.

1. **Design-baseline change: all reversals authorized** (the P1 gate is satisfied). The
   §5 table entries R11/R13/R15/R16/R17 and coordinator C1/C4/C5 proceed under their
   stated conditions and PR gates. The `05` veto items C1–C4, the architecture §10.2
   "Never" list, and R13's "never `workspace_required=False`" clause are **not**
   reversed.
2. **Credential source: reuse the validated DeepSeek provider**. `deepseek-flash`,
   `base_url=https://api.deepseek.com/v1`, `wire_api=responses` (`chat` was removed in
   0.169.0, measured on the host). The key is demo-only. P6 must register it through
   `/api/v1/execution-credentials` as a `credential_ref`; it must **not** mount the host
   `~/.codex/.env` nor inject a deployment key into the app container environment.
   Rotation/revocation is owned by the deployer (JackChow); new Executions must fail
   closed after rotation or revocation.
3. **Scope tier: quickstart demo only**. A single trusted tenant (`local`) plus narrow
   read-only mounts. Production multi-tenant enablement is outside this track and needs
   Phase 6 strong sandboxing (pinned image, daemon probe, egress allowlist) and separate
   security/operations approval in a new design track.
4. **Stage B: excluded**. `app_server` stays `enabled=False` with a throwing factory;
   the Session table, Resume reauthorization, approval/interactive input, P5-IT-18 and
   the separate unlock record are all outside this track.

**Gate still open**: the five §4.5 security-review checklist items must be signed before
the P6 credential lane merges. The signatory is **JackChow (the owner, repository
`git user.name`)**. Every prior signature on this track — the P0 design rulings and the
single-owner phases 4–6 acceptance record — is also signed by JackChow; no separate
product/QA/security roles are added. The signature must cite item-by-item evidence from
the implemented lane and cannot be substituted by this design file.
