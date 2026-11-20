# Phase 5 - Codex Integration Implementation Breakdown

> Status: implementation baseline (2026-11-13); reality rulings updated after implementation (2026-11-14); round-5 addition R18/T10 closes the prompt-delivery blocker
> Revised 2026-11-18 (scope-limited acceptance): the Stage B gate tied to P5-IT-18 (§1, line 22), the "no mock-only unlock" wording, and CI/real-binary/Phase 0-baseline/perf `pending_env` notes are reclassified — P5-IT-18 remains the separate high-risk Stage B unlock condition and CI/perf/baseline items are historical context, not stage-acceptance blockers (05 §6.1). Stage B stays locked; all measured facts and rulings are unchanged.
> Basis: `01`-`05`, and inspection of the Phase 1-4 execution contracts and runtime host.
> Scope rule: implement the smallest Stage A/B seams that fit the existing contracts; do not replace the worker or runtime host.

## 1. Ordered tasks

| ID | Task | Files / seam | Depends on | Traceability |
|---|---|---|---|---|
| T1 | Freeze Codex settings and gate evaluation (disabled by default, version and trusted-tenant checks). | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`; registry composition root | - | FR-1, FR-6, FR-12 |
| T2 | Add typed Codex configuration, stable errors, and adapter contract fixtures. | `backend/src/agent_platform/core_platform/agent_execution/adapters/codex/config.py` (no new error codes were needed) | T1 | FR-1, FR-2, FR-11 |
| T3 | Implement CLI adapter through the existing `RuntimeHost` and workspace ports; never call `subprocess` from the adapter. | `.../adapters/codex/cli_exec.py`, `.../adapters/codex/adapter.py`, adapter registry/composition root | T2 | FR-2-FR-6 |
| T4 | Implement bounded native event and usage mapping. | `.../adapters/codex/events.py` and fixtures | T2 | FR-4, FR-11 |
| T5 | Implement App-Server JSON-RPC framing, request correlation, bounded disconnect/timeout handling, and protocol adapter. | `.../adapters/codex/jsonrpc.py`, `.../adapters/codex/app_server.py` | T2, T3, Stage-A evidence | FR-7, FR-9 |
| T6 | Add Session/Turn/Run mapping and re-authenticated resume only if the existing persistence model and Stage-B gate are available. | `.../agent_execution/session/{models,manager,repository}.py`, conditional migration from the actual Alembic head | T5 | FR-8, FR-10 |
| T7 | Wire adapters into the actual composition root and preserve React as the default. | `applications/platform_runtime/runtime_composition.py`, registries | T1-T5 | FR-1, FR-12 |
| T8 | Add focused UT/IT fixtures first; run existing RuntimeHost/Run/SSE regression once, reusing passed evidence. | `backend/tests/agent_execution/test_codex_*.py` and existing affected tests | T2-T7 | 04, AC-1-AC-12 |
| T9 | Produce test and acceptance reports with honest pending-environment entries. | `06-test-report.md`, `07-acceptance-report.md` | T8 | 04, 05 |
| T10 | Deliver the prompt through the Host stdin channel so the Stage A CLI lane can execute a real prompt (closes the R10 blocker without changing argv, digests, the RuntimeHost signature, or any persistence). | `host/host_models.py`, `host/process_runner.py`, `adapters/codex/{adapter,cli_exec}.py`, `tests/agent_execution/test_host_stdin_delivery.py`, the Codex fixtures | T3, R18 | FR-2, FR-3, FR-4, AC-1, AC-3 |

Stage B (T5-T6) is not enabled until Stage A test evidence satisfies the gate in `04-test-plan.md`; no mock-only evidence can unlock it.

Implementation status (2026-11-14): T1-T5 (pure protocol half), T7-T10 are implemented. T5's transport/connection half and T6 are **not** implemented: Stage B remains locked. The App-Server modules ship codec/state-machine primitives plus unit tests only. T10 (`08` R18) is the last change in this phase: the Stage A CLI lane now delivers a real prompt through the Host and executes the real binary end to end.

## 2. Reality discrepancies and rulings

### R1 - RuntimeHost already exists

The design document describes a new `core_platform/agent_execution` host, but Phase 4 already provides `RuntimeHost`, `ProcessSpec`, workspace ports, process supervision, and cleanup. **Ruling:** adapters depend on these existing contracts; no second process supervisor or direct subprocess implementation is permitted.

### R2 - Registry/composition locations differ from the draft

The repository has separate engine, protocol, and adapter registries under `core_platform/agent_execution/registry`, and composition roots under `applications/*/runtime_composition.py`. **Ruling:** the platform composition root is `applications/platform_runtime/runtime_composition.py`; its registries were extended in place, and no parallel registry was created.

### R3 - Settings location is not the draft path

The draft names `core_platform/platform_services/platform_settings/settings.py`, while the current tree may expose settings through the application/platform settings package. **Ruling (confirmed by implementation):** the authoritative model is `core_platform/platform_services/platform_settings/settings.py`. All `codex_*` defaults are fail-closed and the whole family is excluded from the runtime fingerprint.

### R4 - No Codex implementation or Session table exists yet

Repository inspection found no Codex adapter and no `agent_engine_sessions` model/migration. **Ruling:** Stage A proceeds without persistence and **no migration is created in this phase**. Reality check performed 2026-11-14: the Alembic head is `0059_execution_runtime_host`, and the planning number `0055` is already occupied by `0055_service_applications`. If Stage B later needs the Session table, its number is the head at that time + 1; no historical migration is modified now.

### R5 - Public API must remain generic

Existing runtime events/SSE and Run persistence are the platform boundary. **Ruling:** Codex-native method names, request IDs, PIDs, absolute paths, and secrets remain provider-internal; reuse existing event and SSE contracts. The public event types are normalized to `codex.<native>` and carry no JSON-RPC identifiers.

### R6 - Real Codex environment may be unavailable (measured)

Reality check performed 2026-11-14: a local `codex-cli 0.169.0` binary is installed and **does** execute outside the platform (`codex exec --json ...` exits 0 and returns a real `item.completed` answer plus a real `turn.completed` usage block). `codex login status` reporting `Not logged in` is therefore an auth label, not an availability verdict, and is no longer cited as a blocker. What originally blocked an adapter-mediated provider run was three measured seams, **all three now closed**: (1) `ProcessRunner` fixed `stdin=asyncio.subprocess.DEVNULL` and the argv parameter token rejects spaces, so no prompt could be delivered (`codex exec` exits 1 with "No prompt provided via stdin.") — **closed by R18**; (2) `ProcessSpec.environment` was empty while `/usr/bin/env`-style launchers need `PATH` (`env -i /usr/local/bin/codex --version` exits 127 with `env: node: No such file or directory`) — **closed by R17**; (3) the native event grammar was nested (`item.completed` → `item.{type,text}`) rather than flat, which the adapter now parses — **closed by D6** (see `06-test-report.md`). With (1)-(3) closed, the full Host chain executes the real binary end to end (see R18 for the measured result). The repository's deterministic fake Codex fixture is *not* a provider implementation. **Ruling:** Stage A integration remains proven in CI against the fake fixture through the real `RuntimeHost`, because CI has no Codex binary; the real-binary execution is local evidence recorded in `06` Appendix A and skips with `pending_env` in CI. Credentials, tenant isolation and App-Server connectivity remain `pending_env` and are never reported as passed.

### R7 - Phase 6 security capabilities are out of scope

Broker, strong sandboxing, fencing, deduplication, and billing-grade usage idempotency are not present in Phase 5. **Ruling:** keep trusted-tenant allowlisting and fail-closed behavior; track deeper capabilities as follow-up issues rather than widening this phase.

### R8 - Documentation language and synchronization

`docs/` requires English as the authoritative new text; existing `.md` and `.en.md` pairs must not receive contradictory IDs. **Ruling:** update the English planning/report files and mirror IDs in the paired file only when a factual change is made. This round only the `.en.md` files and the report pair carry changes; the Chinese `03-technical-design.md` was left untouched to avoid a numbering mismatch, and that omission is recorded in `06-test-report.md`.

### R9 - The contracts expose no streaming port

`AgentEngineAdapter` has exactly six methods (`get_capabilities`, `start`, `stream_events`, `cancel`, `collect_result`, plus identity properties) and there is no incremental chunk callback. **Ruling:** the Stage A adapter reads the Host's already-bounded `ProcessResult.stdout` after the process exits and yields the mapped events from `stream_events`. Chunked/streaming fidelity inside one Turn is therefore not measured; the event contract (`sequence`, identity, bounded payload) is.

### R10 - `stdin` is fixed to `DEVNULL` in the Host

> **Superseded by R18 (round 5).** The ruling below is retained for history only: the Host now carries an opt-in bounded stdin payload, the `promptless_target` bypass was deleted, and a prompt-carrying run is no longer refused.

`ProcessSpec` has no `stdin` field and `process_runner.py` calls `create_subprocess_exec(..., stdin=asyncio.subprocess.DEVNULL)`. **Ruling (coordinator C2):** do not modify the Host. A real prompt cannot be delivered, so `CodexCliAdapter.start` refuses with the existing `ENGINE_UNAVAILABLE` code unless the adapter was explicitly constructed for a prompt-free target (`promptless_target=True`, used only by the fake-fixture integration test). Silently sending an empty prompt is forbidden. Tracking reference: `cli_exec.PROMPT_DELIVERY_ISSUE`.

### R11 - The production selector is a hard-wired constant

`PRODUCTION_ADAPTER_SELECTOR = ("react", "native", "v1")` is read by the Worker, the Registry and the warm targets alike. **Ruling (coordinator C1):** Codex is registered and tested through an injected selector; the Worker and the Orchestrator default selector are untouched. Reaching Codex from a production Run is therefore impossible today and is recorded as a real limitation, not papered over.

### R12 - `CodexConfig` must satisfy the registry schema contract

`AdapterRegistry.register` rejects any `config_schema` whose `model_config` is not `strict=True`, `frozen=True`, `extra="forbid"`. The planning model was `extra="forbid"` only. **Ruling:** the model was upgraded to the full triple; the protocol enum accepts its bare string value through a `before` validator so deployment files stay usable under strict mode.

### R13 - The workspace availability port is always `None`

`NoTrustedWorkspaceGeneration` returns no generation, so the Platform Default Policy Provider short-circuits the workspace dimension to `workspace_unavailable`. Because the Stage A declaration keeps `workspace_required=True` (C5), the production capability barrier refuses Codex before `adapter.start`. **Ruling:** accept the fail-closed refusal; never declare `workspace_required=False` to bypass it.

### R14 - `timeout_seconds` 1800 conflicts with the Run deadline ceiling

`settings.run_timeout_seconds` is `le=600`, so a 1800-second Codex default would outlive every Run. **Ruling:** `CodexConfig.timeout_seconds` defaults to and is capped at 600; the effective ceiling is `min(config, Run deadline, Host wall)`.

### R15 - The publish path validates non-React engines against the React block

`AdapterRegistry.validate_config` always passes `normalized.react` (which is `{}` for a non-React engine) to the registered `config_schema`. A `CodexConfig` that requires `version` therefore rejects every Codex publish attempt with `invalid_request`, even when the descriptor is enabled. Measured 2026-11-14 with the gate open. **Ruling:** keep it as-is this round. Adding a Codex block to `ExecutionConfig` would contradict C4, and the production Run path cannot reach Codex anyway (R11). Tracked as issue I7 in `06-test-report.md`.

### R17 - The Codex binary is a `/usr/bin/env node` launcher and `ProcessSpec.environment` is empty

Measured 2026-11-14: `/usr/local/bin/codex` starts with `#!/usr/bin/env node`, and `env -i /usr/local/bin/codex --version` exits **127** with `env: node: No such file or directory`. The adapter never populated `ProcessSpec.environment`, and the C2 ruling forbids changing the Host. **Ruling (round 5): fix inside the adapter, not the Host.** `ProcessSpec.environment` already exists, so the lane supplies exactly one variable through a new typed `CodexConfig.path_env` (default `/usr/local/bin:/usr/bin:/bin`, rejected if any entry is relative, empty, or a parent segment), wired from the deployment setting `codex_path_env`. A typed `PATH` is deliberately chosen over a free-form map: credentials, proxy settings and host secrets have no field to travel in, so the fix cannot become an injection surface (C1/C2). Verified through the real `ProcessRunner` against the real binary: `environment={}` → exit 127; `environment={"PATH": …}` → exit 0 (`codex-cli 0.169.0`). **R17 is closed.** It did not unblock a real run on its own: with `PATH` supplied the CLI launched but `codex exec … -` exited **1** with `No prompt provided via stdin.` — that remaining half was **closed by R18** (round 5), after which the full chain executes the real binary end to end.

### R16 - The production trusted-target allowlist stays empty

`_build_execution_runtime_subsystem` composes `ProcessRunner(TrustedTargetRegistry(()))`. Even with the CLI gate open, a real Run's `Host.start` would refuse the `codex` executable as untrusted and fail closed with `ENGINE_UNAVAILABLE`. **Ruling:** intentional per the coordination rules; registering a real executable is a deployment decision tracked with R11.

### R18 - Prompt delivery through a bounded Host stdin channel (closes R10)

Measured 2026-11-14 (round 5): with `PATH` supplied (R17) the real binary launches but `codex exec … -` still exits **1** with `No prompt provided via stdin.`, because `ProcessRunner` pins `stdin=DEVNULL` and `ProcessSpec` has no payload field. The argv token validator (`_PARAMETER_TOKEN`) also rejects tokens containing spaces, so an inline prompt cannot be smuggled through argv. **Ruling (round 5, requirements agent): add one opt-in, bounded, internal stdin payload to the Host — do not deliver the prompt any other way, and do not widen anything else.**

**Field.** `host/host_models.py`:

```python
MAX_STDIN_PAYLOAD_BYTES = 800_000
StdinPayload = Annotated[bytes, Field(min_length=1, max_length=MAX_STDIN_PAYLOAD_BYTES)]

class ProcessSpec(ExecutionContractModel):
    ...
    stdin_payload: StdinPayload | None = Field(default=None, repr=False, exclude=True)
```

- `None` means "no payload", and the Runner keeps `stdin=DEVNULL` — the pre-R18 behaviour is therefore byte-identical for every existing target (React and the Phase 4 workload cases).
- The field is `bytes`, not `str`: encoding happens exactly once, in the adapter, where a failure has a defined error semantic (`INVALID_REQUEST`). The Host is not the place to decide character encodings.
- `repr=False, exclude=True`: the payload carries user prompt text. It must not appear in `repr()`, `model_dump()`, logs, events or DTOs. Prompt text is still never persisted: `runtime_host_processes` stores only `command_digest`, `workdir_id` and `{"executable_id": …}` metadata.
- **Upper bound is 800_000 bytes because the request bound is expressed in characters**: `ExecutionRequest.input` is `max_length=200_000` *characters*, and a UTF-8 code point can take 4 bytes. 4 × 200_000 is the worst-case byte size of any valid request, so a byte-level cap of 800_000 can never reject a prompt the public contract accepted. A cap of 200_000 bytes would reject legitimate Chinese prompts (1 character = 3 bytes).

**Write ordering (each point is load-bearing; measured):**

1. **The Runner's `StartedProcess` handle is assigned *before* the payload write.** `hard_cleanup` only closes the output pumps when `started is not None`; if delivery failed before that assignment, the pumps would leak.
2. **`pump.start()` runs before the payload is written.** Otherwise a child that writes more than a pipe buffer (~64 KiB on Darwin) of stdout blocks on a full pipe while the Host blocks writing stdin — a mutual deadlock.
3. **`stdin.close()` is mandatory.** `codex exec … -` reads until EOF before it starts the turn; a write without a close hangs the run.
4. **`stdin.wait_closed()` is never awaited.** Measured: awaiting it after the process exits produces `ERROR asyncio: Exception in callback SubprocessStreamProtocol.pipe_connection_lost` noise with no benefit.

Delivery is bounded by the module constant `STDIN_DELIVERY_TIMEOUT_SECONDS = 10.0` (injectable as a keyword-only Runner argument for tests; a value `<= 0` raises `ValueError`). One deadline covers write+drain, **capped by the remaining `ProcessSpec.resource_policy.wall_seconds` budget**: the effective deadline is `min(configured timeout, wall - elapsed)`, measured from the start of `ProcessRunner.start`. Thus a tighter wall cannot be exceeded by the 10-second default (D22). No Run/Host public signature is changed.

**The two failure modes, and how each is handled (fail closed, never a silent partial run):**

| # | Failure | Handling |
|---|---|---|
| R1 (refusal) | The child exits or closes its end before consuming the payload (`EPIPE`/`BrokenPipeError`/`ECONNRESET` on write or drain) | `ProcessSpawnError(REASON_PIPE_SETUP_FAILED)`. The already-spawned group is killed through the existing `hard_cleanup` path, so no process survives a failed delivery. |
| R2 (starvation) | The child never reads stdin (deadlock / wrong binary), so `drain()` would block forever | The same bounded deadline aborts the drain and raises the same `ProcessSpawnError`. Total wall time stays inside the Host ceiling instead of hanging the Worker. |

**Failure code reuse.** Both cases raise the existing `REASON_PIPE_SETUP_FAILED = "runtime_host_pipe_setup_failed"` (`host_models.py:35`). No new reason code is added: the vocabulary is frozen for metrics and `last_error_code`, and a delivery failure *is* a pipe setup failure. `RuntimeHost.start` already maps it through `_stable_code` and persists it on the record it just created. `CodexCliAdapter.start` translates the resulting internal `HostStartError` to the public `ENGINE_UNAVAILABLE` `AdapterExecutionError`, so the Host exception and its internal reason never escape the adapter vocabulary (D21); the durable Host row retains the precise reason.

**Digest and persistence semantics are unchanged.** `compute_command_digest` hashes `executable_id + argv` only, and `policy_digest` hashes `resource_policy` only; neither is touched. The payload is therefore deliberately *outside* the recovery verification chain: `command_digest` keeps answering "was this the same trusted command line?", which is the question recovery, audit and the registry column ask. No migration is needed because `runtime_host_processes.command_digest` keeps its meaning and no new column is introduced.

**Adapter side.** `CodexCliAdapter.start` encodes `request.input` to UTF-8 after the gate and **before** `_workdir_relative()` (which creates a directory — a rejected request must not leave an empty adhoc Workdir behind). `UnicodeEncodeError` and a payload above the byte ceiling both raise `INVALID_REQUEST` through the existing `ConfigurationError` path. `argv` stays `CODEX_CLI_FIXED_ARGV` (trailing `-`), the one code-constant command line. The `promptless_target` constructor argument, its `ENGINE_UNAVAILABLE` refusal and `cli_exec.PROMPT_DELIVERY_ISSUE` are **deleted**, not deprecated: there is no remaining configuration in which the adapter pretends to run a prompt it cannot deliver.

**Not done in this round (deliberately):** Stage B stays locked (`codex_app_server_enabled` still requires `stage_a_verified`, the App-Server descriptor is still a literal `enabled=False`); production routing is untouched (`PRODUCTION_ADAPTER_SELECTOR` and `ProcessRunner(TrustedTargetRegistry(()))` are unchanged); no new settings key is added (the delivery deadline is a module constant plus Runner injection); no migration, `ManagedProcess`, `ProcessResult`, sandbox provider or `RuntimeHost.start` signature change.

**Measured result (local, 2026-11-14).** The real `/usr/local/bin/codex` driven through the complete Host chain (`environment={"PATH": …}`, `argv=CODEX_CLI_FIXED_ARGV`, `stdin_payload=prompt`) exits **0** and emits `thread.started` → `item.completed{item.type=error}` → `turn.started` → `item.completed{item.type=agent_message,text}` → `turn.completed{usage, 5 fields, no total_tokens}`, in about six seconds. The full command and output snapshot are in `06-test-report.md` Appendix A. CI has no Codex binary, so the real-binary case is `pytest.skip`-guarded and reported `pending_env`; the deterministic fixture coverage (which now *reads* stdin, so a prompt that is merely buffered is not mistaken for one that was consumed) runs everywhere.



Any implementation discovery that changes a file path, migration dependency, public contract, or gate updates this file and `03` before code changes. Coordination is limited to five rounds; after the fifth unresolved disagreement, retain the smallest fail-closed implementation and record the deferred item as a follow-up issue.

## 3. Stage A CLI Engine Enablement — proposed ruling addendum (2026-11-20)

> **Status: DESIGN PROPOSAL — not implemented, not authorized, not acceptance evidence.**
> This section is the "follow-up issue" contemplated by the L147 coordination rule above:
> it is a new enablement track, **not a sixth coordination round**. Section 1 (T1–T10)
> and Section 2 (R1–R18) above, and every historical verdict/number in `05`, `06`, `07`
> and `12`, are retained **verbatim** (`07` §9). Nothing below changes a runtime default,
> flips a switch, merges code, or grants enablement/security approval. The authoritative
> design is `09-stage-a-cli-engine-enablement-design.en.md` (Chinese mirror: `...design.md`).

### 3.1 What Phase 5 shipped, and what is still locked

Phase 5 shipped a fail-closed Stage A skeleton (typed `CodexConfig` + `CodexStageGate`, a
registered `codex` Engine with two Protocols, `CodexCliAdapter` over `RuntimeHost`, bounded
native-event/usage mapping, and the R18 stdin channel). It deliberately did **not** make
Codex reachable from a production Run (§1 L141, R11/R13/R15/R16/R17). `07` §9 and the
`12` scope-limited record keep those omissions as historical facts and explicitly do not
authorize Codex enablement, production routing, or untrusted tenants. Six gates still
separate "descriptor enabled" from "a Run actually executes and authenticates Codex";
they are enumerated with verified code seams in `09` §3. This section registers the
proposed reversals only.

### 3.2 Numbering correction — two distinct "C" sets

`08` §2 cites "coordinator C1/C2" (R10/R11), "(C5)" (R13) and "contradict C4" (R15).
Those are **implementation-time coordination rulings** and are the object of §3.3 below.
They are unrelated to the **compliance checks C1–C10** in `05` §5, where C1/C2/C3/C4 are
**VETO items** (no plaintext Secret, no host `~/.codex/auth.json` copy, zero untrusted-tenant
exposure, Workspace/cross-tenant denial). The veto items are **never reversed**; the
credential design in `09` §4 is constrained by them and maps onto each one. Conflating the
two sets would waive a security veto.

### 3.3 Proposed reversal of engineering rulings (effective only per PR + sign-off)

| Ruling / constraint | Original (fail-closed) | Proposed reversal | Condition / PR |
|---|---|---|---|
| R11 + coordinator C1 | Hard-wired production selector; "reaching Codex from a production Run is impossible today". | Per-Run resolution from the published engine identity; keep `react/native/v1` default and off-state byte-identity. | P2; G2; off/on/rollback. |
| R13 + coordinator C5 | Accept `workspace_unavailable`; never `workspace_required=False`. | Wire a real `WorkspaceProvider`. The "never `workspace_required=False`" clause is **retained**. | P3; G3; C4 adversarial cases. |
| R15 + coordinator C4 | Keep React-block-only `validate_config`; a Codex `ExecutionConfig` block "would contradict C4". | `ExecutionConfig.codex` + engine-dispatched validation + DTO/SDK/UI; coordinator C4 retires for this track. | P1; G1; public-contract change documented first (L147). |
| R16 | `TrustedTargetRegistry(())` stays empty. | Register `CODEX_CLI_EXECUTABLE_ID` with fixed argv prefix + parameter grammar, bound to the Gate-6 mount. | P4; G4. |
| R17 | `ProcessSpec.environment` carries exactly one typed `PATH`. | Keep the typed discipline; add one typed, allowlisted slot mapping the Broker-consumed Secret to `credential_env_key`. | P6; G5; `09` §4.5 security sign-off. |
| coordinator C2 | "Do not modify the Host" (R10 context). | **No reversal needed**: `RuntimeHost.start(credential_ref=...)` and `secret_env` already exist (R-18(a), Phase 6). The lane consumes the existing seam; no Host rewrite. | P6. |

R10/R18, R12, R14, R6, R7, R8, R9 and the **Stage B lock are unchanged**. R7 is narrowed
only in that the enablement track consumes the now-existing Phase 6 Broker framework; it
adds no new Phase 6 capability. Stage B (`app_server`) stays `enabled=False` and still
requires `P5-IT-18` plus a separate unlock record (05 §6.1).

### 3.4 Credential lane — the security-critical seam

`CodexCliAdapter` currently stores `credential_broker`/`credential_ref` but never passes
`credential_ref` to `_host.start()`; `CodexConfig.credential_ref` is an unenforced `str`
placeholder. `RuntimeHost.start(credential_ref: UUID | None)` already implements
`issue → consume → secret_env["EXECUTION_CREDENTIAL"] → revoke` with fail-closed semantics
(`host/runtime_host.py:242-343`). The proposed lane (`09` §4) reuses that Phase 6 Broker,
maps the consumed Secret to the provider's `env_key` variable inside a per-Execution private
`CODEX_HOME` containing a **key-free** `config.toml`, and keeps the Secret out of
config/argv/stdin/logs/events/`command_digest`. Explicitly rejected: mounting host
`~/.codex`/`auth.json`/`.env`, injecting a deployment key into the container environment,
widening `ProcessSpec.environment` into a free-form map, and pointing Codex at the Model
Gateway (it has no OpenAI-compatible inbound endpoint). `09` §4.5 is a **blocking security
review checklist**; P6 must not merge before it is signed.

### 3.5 Ordered follow-up tasks (proposed — not yet implemented)

| ID | Task | Depends on | Gate / sign-off |
|---|---|---|---|
| T11 | `ExecutionConfig.codex`, engine-dispatched `validate_config`, `react_matches_engine`, DTO/SDK/normalizer, frontend engine picker. | T2, R15 reversal | P1 / G1 |
| T12 | Per-Run adapter resolution; engine-branched capability/snapshot/event/workdir; warm targets. | T11, R11 reversal | P2 / G2 |
| T13 | Real `WorkspaceProvider` + per-Execution `CODEX_HOME` scaffolding (never `workspace_required=False`). | T12, R13 reversal | P3 / G3 / C4 |
| T14 | `CODEX_CLI_EXECUTABLE_ID` trusted-target descriptor + tests. | T3, R16 reversal | P4 / G4 |
| T15 | Narrow read-only volume mounts, `AGENT_CODEX_PATH_ENV`, key-free `config.toml` template, quickstart demo docs. | PR #147 switches | P5 / G6 |
| T16 | Broker resolve/inject/revoke, `credential_env_key` allowlist, Secret-free audit. | T13, T15, R17 reversal | **P6 / G5 / `09` §4.5 sign-off (blocking)** |
| T17 | End-to-end per-Run Codex turn (dialogue + tool use), `05`/`06`/`07` addenda, Stage A unlock record. | T11–T16 | P7; full Stage A acceptance; Stage B still locked |

P0 (this design PR) satisfies L147 before any of T11–T17 begins. P1–P5 keep the deployment
fail-closed until P6 and the PR #147 switches are combined. Test baseline (preserve all
default-off tests including `test_agent_execution_phase4_deployment.py` and
`test_quickstart_execution_switches_default_fail_closed` from PR #147; add enabled-path
assertions per stage) is in `09` §7.

Status (2026-11-20): T11–T13 landed as PRs #149, #150 and #151; T14–T16 are implemented
in the P4–P6 PRs beginning with #152; **T17 is closed on a scope-limited basis** — see
§3.9 and the authoritative, owner-signed record
`../13-scope-limited-acceptance-record-20261120-phase7-stage-a.md`. Every signatory on this track is JackChow (the
owner/user). The `09` §4.5 security sign-off for T16/P6 is recorded in
`10-stage-a-cli-credential-lane-security-signoff.md` and is scoped to the quickstart
demo credential lane.

### 3.6 Host-side independent verification (context, not acceptance evidence)

On 2026-11-19, outside the platform, host `codex` 0.169.0 + Node v22.23.5 reached a real
OpenAI-Responses-compatible provider via a custom `[model_providers.*]` block
(`wire_api = "responses"`, key through an `env_key`-named environment variable) and
completed both a plain turn and a tool-using (`command_execution`) turn with exit 0. This
satisfies Gate 6's premise on the target host. It does not open Gates 1–5 and is local
evidence with an owner (05 §6.1), not CI or acceptance evidence.

### 3.7 P7 验收发现 D-1：CLI 引擎仍被要求平台模型档案

真实端到端验收第一次真正发布 Codex Agent 时，`POST /agents/{id}/publish` 返回
`409 agent_model_required`，P7 无法继续。根因是 `AgentService.validate_model()` 的
平台模型档案校验对所有引擎无条件生效，而 `AgentConfig.normalize_execution` 对非
React 引擎会把 legacy 的 `model_profile_id` / `model_profile_version` 归一化为
`None`（CLI 引擎的模型由引擎自身配置决定，见 `09` §3）。两者叠加使任何 Codex
引擎 Agent 都无法发布、回滚或生成快照，P1/T11 的“可选引擎”在发布环节实际不可用。

修复（本 PR）：新增显式集合 `MODEL_PROFILE_ENGINES = {"react"}`，`validate_model()`
只对该集合内的引擎解析平台模型档案；集合外引擎直接返回，不做目录查询。默认
React 路径行为不变（缺档案仍为 `agent_model_required`，绑定档案仍解析并校验
`chat`/`tool_calling`），并有 `backend/tests/test_agent_model_gate_engines.py`
三个节点锁定两侧行为。该缺陷不影响 P1–P6 的 fail-closed 默认值。

### 3.8 P7 验收发现 D-2 / D-3：编排屏障与 Node 资源上限

D-1 修好后发布通了，但每个 Run 仍在 25–30 ms 内以 `execution_error` 结束。在运行容器
内加临时堆栈日志后定位到两处与引擎无关的部署级缺陷：

- **D-2（编排屏障）**：`runtime_composition.RuntimeFactoryInstructionPreparer` 期望一个
  可调用对象，而组装点传入的是 `RuntimeFactory` 实例本身，于是 Phase 3 屏障在
  `prepare_instructions` 处抛 `TypeError: 'RuntimeFactory' object is not callable`，
  被屏障分类为 `execution_error`。任何启用 orchestrator 的 Run（含 React）都会在
  `Adapter.start` 之前失败。修复：该适配器在构造时把工厂绑定为其
  `prepare_instructions` 方法（保留接受裸可调用对象的测试接缝），未配置时抛出显式
  `TypeError`，不再退化成不透明的 `NoneType` 错误。
- **D-3（资源上限）**：Codex CLI 目标是 Node 进程，V8 启动需预留大段虚拟地址空间；
  沿用通用 `AGENT_EXECUTION_RESOURCE_MEMORY_BYTES=536870912`（512 MiB 的
  `RLIMIT_AS`）会让 CLI 在第一轮之前崩溃（实测 `Fatal process out of memory: Failed
  to reserve virtual memory for CodeRange`，宿主记为 exit_code `-5`/SIGTRAP），Host
  只能报 `engine_unavailable`。实测 1 GiB 可完成一轮。修复：新增
  `CODEX_CLI_MIN_MEMORY_BYTES = 1 GiB` 与启动期校验——`AGENT_CODEX_CLI_ENABLED=true`
  且内存上限低于该下限时直接拒绝启动；同时在 quickstart compose、两份 `.env.example`
  与 `deploy/README.md` 写明抬升方式（演示用 2 GiB）。Codex 关闭时该校验不生效，
  默认 512 MiB 部署行为不变。

两处修复的回归在 `backend/tests/test_agent_execution_stage_a_preflight.py`：工厂方法绑定、
裸可调用对象、未配置即报错、内存下限拒绝/接受、以及 Codex 关闭时校验失效共 5 个节点。
两者都不改变 Stage B 锁定状态，也不放宽任何凭据或沙箱边界。

### 3.9 P7 / T17 收口结论（2026-11-20，范围限定）

权威记录：`../13-scope-limited-acceptance-record-20261120-phase7-stage-a.md`（单一验收负责人
JackChow 已签署，结论 **PASS scope-limited**）。本节只登记收口状态与证据索引，不改写
§3.5 的任务表和上文历史结论。

**补齐 D-4**：D-1…D-3 见 §3.7/§3.8。第四个阻断缺陷是适配器由部署级占位
`ExecutionConfig` 字面量构造，而非 Agent 修订上发布的 `codex` 块，因而没有
`credential_ref` / `home_config`，凭据 Broker 从未被调用（`engine_unavailable`、
宿主 exit 1、grant 审计 0 条）。修复：工厂改读
`execution_config_from_context(context).codex`，缺失即 `RuntimeError` 失败关闭，
删除占位字面量；回归见 `test_agent_execution_stage_a_preflight.py`。四项修复合入
PR #155（`b228570`），merge 后 CI 5/5、CD `44716695070` 3/3 成功。

**T17 逐项核对**：

| T17 条目 | 结论 | 证据 |
|---|---|---|
| 端到端按 Run Codex 对话 turn | **通过**：两轮连续 `completed` / `output=OK` / 每轮 8 条有序事件 | `13` §3 |
| 工具调用 turn（平台容器内） | **范围内未完成，登记为部署边界**：Docker 默认 seccomp 阻断 `bwrap` 创建 user namespace（`unshare -Ur` → EPERM），工具调用 Run 虽 `completed` 但自述沙箱无法启动 | `13` §6.1；第 3 轮 `aa9ab8f2-…` |
| 工具调用 turn（平台外主机独立验证） | **通过**：`command_execution` turn exit 0；属本地证据、非验收证据 | §3.6 |
| `05` / `06` / `07` 附录 | **已补齐**（本 PR） | 三份报告末尾的 2026-11-20 补记 |
| Stage A 解锁记录 | **已落地**（范围限定，仅 `cli_exec/v1` quickstart 演示） | `07` 末章；`13` §8 |

链路证据（干净 CI 镜像 `63221a1fd3ba`，`docker diff` 零 `/app` 可写层改动）：发布 →
Phase 3 编排屏障 → Runtime Host → 凭据 Broker `grant_issued → grant_used` → Codex CLI
真实轮次 → 事件与终态 → `engine_terminal` usage 落账。本地门禁 2368 passed / 6 skipped
（PR #155 时点），PR #157 追加 1 条部署回归后为 2369 passed / 6 skipped。

**闭环说明**：`13` §5 记为「建议后续（不在本阶段修复）」的 CD `.env` 版本号回写陷阱，
已由 PR #157 落地，并在 CD run `44725578236` 的部署日志实测生效
（`Pinned deploy/quickstart/.env to NEXUSDESK_VERSION=2c03528cd7b6`）；该条建议至此关闭。

**边界不变**：工具调用的沙箱限制属部署加固决策，本阶段不改默认安全姿态；Stage B
（`codex/app_server/v1`）保持锁定；生产 Codex 路由、不可信多租户与高风险能力启用
未请求、未授权。T17 因此以范围限定口径收口，不宣称「完整 Stage A 验收」。
