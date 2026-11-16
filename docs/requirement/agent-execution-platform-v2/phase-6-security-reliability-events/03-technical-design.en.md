# Phase 6 · Security, Reliability, and Event Governance — Technical Design

> Status: Approved design baseline for direct-continue implementation; code-reality checked on 2026-11-16, not implemented and not accepted. Untrusted execution remains disabled.
> Created: 2026-11-02
> Revised: 2026-11-16 (revalidated Phase 4/5 code, tests, composition, CI, and migration graph; selected an additive staged approach; replaced stale paths and migration numbers)
> Basis: `01-business-goals.en.md` (G1–G7), `02-requirements.en.md` (FR-1–FR-16, AC-1–AC-16), architecture Sections 7–10, 12, and 16–22, and `08-implementation-breakdown.en.md` R-1–R-15

The user’s direct-continue instruction authorizes development against the existing 01–05 scope; it does not invent upstream acceptance, real environments, independent approvals, or measured baselines. Final Phase 6 acceptance still requires every applicable gate in 04/05.

## 1. Current-state Audit and Constraints

| Area | Verified facts on 2026-11-16 | Binding design consequence |
|---|---|---|
| Migration graph | `0067_merge_heads` is the single head, joining `0066_hosted_web` and `0059_execution_runtime_host`. Planned `0056`/`0057` are already occupied. | Plan `0068_execution_fencing` (file `0068_execution_fencing_event_outbox.py`) with `down_revision="0067_merge_heads"`, then `0069_execution_credential` with `down_revision="0068_execution_fencing"`; revalidate immediately before T-02. |
| Run/lease | `agent_runtime/repository.py` conditionally checks `owner`, `lease_until`, cancellation, and terminal state. `claim` does not increment an epoch; `reap` fails or cancels expired rows rather than taking over ownership. | Add a database-owned monotonic `lease_epoch` and propagate `(run_id, owner, lease_epoch)` through every Worker/Host/Workspace/replay mutation. Preserve Run=one attempt and the existing queue. |
| Worker/orchestrator | `worker.py` owns the Worker UUID and heartbeat task. `ExecutionContext` already carries `owner`. `ExecutionOutcome.usage` exists, but `RuntimeWorker.finish` does not persist it. | Extend these seams; do not add Engine branches to the Worker and do not put fencing tokens in client DTOs or AgentConfig. |
| Event contract | `contracts/events.py` already defines `AgentEvent.event_id`, `schema_version="v1"`, execution identity, adapter-local sequence, source, timestamp, payload, and trace ID. `orchestrator.py` currently passes only `event_type` and `payload` to the Worker. | Preserve the existing envelope and carry it to persistence. Adapter-local sequence is not the Run-local durable `runtime_events.seq`; the database remains the sequence authority. |
| Event writes | `RunRepository._event` increments `runtime_runs.event_seq` and inserts `runtime_events` in one transaction. `tool_gateway/replay.py` has a second production insert path. Seed code also inserts historical/demo rows directly. | Use database defaults plus an Outbox insert trigger/reconciler so old and direct writers cannot silently bypass publication for publishable events. Add fencing to the tool-replay path; its internal payload is never published. Do not renumber history or bulk-republish pre-migration rows. |
| Outbox/delivery | No runtime Outbox exists. `platform_services/events.py` already provides `DurableEventBus` over `memory_tasks` with idempotency keys and at-least-once delivery. | Add only the runtime transactional Outbox and dispatcher. Reuse the durable bus through an explicit enqueue-acknowledgement port; do not add a broker or claim network-level exactly-once. SSE still reads `runtime_events`. |
| SSE | `runtime_routes.py` authorizes first, merges `after`/`Last-Event-ID`, pages by 200, keeps `id=seq`, treats NOTIFY as wakeup, and leaves `model.delta` transient. No retention floor or replay-gap response exists. | Preserve these semantics. Add additive envelope metadata, explicit 400/409 gap handling, and a monotonic per-Run retention floor. |
| Usage | React/Codex results can carry usage. Codex preserves unknown fields rather than zero-filling. Existing `gateway_costs` is a separate model-gateway accounting path keyed by attempt. | Add an Execution usage ledger keyed by stable source identity. Do not repurpose or double-count `gateway_costs`; corrections form traceable chains and old epochs cannot write. |
| Parser | Codex parsing is bounded and maps malformed lines to static protocol errors; payload filtering/truncation exists. It does not emit classified, correlated, rate-limited diagnostic records. | Extend the existing mapper/parser and common redaction; do not create a second native protocol or raw-sample event stream. |
| Credentials | `platform_services/secrets/vault.py` provides Fernet encryption bound to a model connection/address. It can provision a key during model-credential creation; there is no Execution grant or Broker. | Create Execution-specific records, binding, grant hashes, and audit. Runtime key reads never auto-create a missing key; model-gateway credentials remain separate. |
| Host/sandbox | Phase 4 provides `RuntimeHost`, process supervision, resource management, durable process records, and Workdir cleanup. `LocalSandboxProvider` deliberately rejects arbitrary/uploaded/untrusted execution and provides no user/mount/network namespace or syscall isolation. | Extend the existing Host and Sandbox Provider port. A strong provider must control the actual launch/network/mount boundary; renaming Local or adding preexec checks is not a strong sandbox. |
| Workspace | `ExecutionWorkspaceManager` and `execution_workdir.py` already enforce platform-generated paths, restrictive modes, no-follow operations, link/race checks, scoped persistence, retention, and cleanup. | Reuse and ownership-guard these operations. Add only missing mount/artifact policy and strong-provider integration. |
| Codex/Stage B | Phase 5 Stage A CLI exists over the real Host. Production selection remains `react/native/v1`, the production trusted-target registry is empty, and App-Server transport, Session persistence, approvals, and Resume are locked/unimplemented. Phase 5 07 is only a scoped conditional pass. | Do not complete Phase 5B or change production routing in Phase 6. Test generic seams with controlled adapters; real Session/Resume and production Codex release evidence remain upstream blockers. |
| Composition/settings | Authoritative settings are `core_platform/platform_services/platform_settings/settings.py`; composition is `applications/platform_runtime/runtime_composition.py`; runtime API registration is `applications/customer_service/application.py`. | Extend these exact locations and existing `.env.example` files. New rollout controls stay out of the runtime fingerprint. |
| CI | CI runs ruff + architecture, all non-PG tests, two PostgreSQL 17 shards after `alembic upgrade head`, and frontend checks. Real Codex and strong-sandbox evidence is not supplied by default CI. | Put deterministic unit/PG coverage into the existing lanes. Do not convert unavailable real-provider/sandbox/fault environments into passes or require repeated unchanged suites locally. |

## 2. Implementation Approach and Alternatives

### Selected: extend current modules in three vertical slices

1. **Reliability/event foundation**: migration 0068, ownership/fencing, durable event identity/dedup/Outbox, SSE gaps, usage, and diagnostics.
2. **Execution security**: migration 0069, Vault/Broker/redaction, strong launch/network/mount enforcement, and Host/Workspace integration.
3. **Integrated recovery and release**: cancellation confirmation, retry/quota reconciliation, composition/deployment, focused regressions, real drills, and honest reports.

This is the smallest approach that preserves the current queue, Run/API/SSE contracts, Host, Workspace, Adapter boundaries, durable event bus, and modular monolith. Each slice is testable without enabling untrusted tenants.

### Alternative considered: parallel security/reliability/event subsystems

New Event Store, process supervisor, Workspace store, and scheduler-like ownership services would isolate new code initially, but would duplicate current transaction boundaries and create two sources of truth. It is rejected because migration, rollback, fencing coverage, and regression cost are higher without a required architectural benefit.

### Alternative considered: one horizontal big-bang implementation

Implementing every schema and interface first, then wiring all sixteen FRs together, would maximize the time before a vertical behavior can be tested. It is rejected. Staged vertical slices expose fencing, event, credential, and sandbox defects earlier while keeping all final hard gates unchanged.

## 3. Change Overview

| Layer | Concrete file(s) | Change | Traceability |
|---|---|---|---|
| Migration | `backend/migrations/versions/0068_execution_fencing_event_outbox.py` (new) | Epoch/cancellation/cleanup/retry/retention metadata, event identity/dedup, Outbox trigger/table, usage ledger. | FR-7–FR-14, FR-16 |
| Migration | `backend/migrations/versions/0069_execution_credential_security.py` (new) | Execution credential versions, short-lived grant metadata, and revocation indexes. | FR-1, FR-2, FR-16 |
| Ownership/recovery | `core_platform/agent_execution/reliability/{ownership,recovery,retry}.py` (new); `agent_runtime/{repository,worker}.py`; `tool_gateway/replay.py` | Internal ownership value object, conditional-write coordination, recovery/retry decisions; Repository remains SQL authority. | FR-7–FR-10 |
| Event persistence | `core_platform/agent_execution/events/{envelope,outbox,replay}.py` (new); `agent_runtime/repository.py`; `orchestration/orchestrator.py` | Carry the existing AgentEvent, distinguish adapter/durable sequence, deduplicate, dispatch Outbox, and calculate replay gaps. | FR-11–FR-13 |
| Existing durable bus | `core_platform/platform_services/events.py` | Add an explicit acknowledged enqueue operation for runtime Outbox; existing `publish` behavior remains compatible. | FR-12 |
| Usage/diagnostics | `core_platform/agent_execution/events/{usage,diagnostics}.py` (new); `adapters/{react,codex}`; `orchestration/execution_lifecycle.py`; `agent_runtime/worker.py` | Stable source identity, correction chains, bounded classified diagnostics, and terminal usage persistence. | FR-14, FR-15 |
| SSE/API | `applications/customer_service/runtime_routes.py` | Preserve existing fields and `id=seq`; add reserved envelope metadata and 400/409 replay behavior. | FR-13 |
| Credentials | `core_platform/agent_execution/credentials/{models,vault,broker,repository}.py` (new) | Fernet-compatible installation-key primitive with Execution AAD/binding, one-time grant handling, rotation/revocation, and audit. | FR-1, FR-2 |
| Credential API | `applications/customer_service/execution_credential_routes.py` (new); `application.py` | Admin-only create/rotate/revoke/metadata operations; no Secret read endpoint. | FR-1, FR-16 |
| Redaction | `core_platform/agent_execution/security/redaction.py` (new); existing Host/Adapter/API boundaries | Registered-Secret/canary/pattern redaction, bounded diagnostics, disclosure response hook. | FR-3, FR-15 |
| Strong sandbox | `core_platform/agent_execution/host/{docker_sandbox_provider,network_policy,egress_proxy}.py` (new); `{sandbox_provider,process_runner,runtime_host,resource_manager}.py` | Provider-generated internal launch plan, unprivileged container, cgroup limits, minimal mounts, default-deny actual network, and managed allowlist proxy. | FR-4–FR-6 |
| Workspace/Host ownership | `agent_execution/workspace/{workspace_provider,workspace_manager,execution_workdir}.py`; `host/process_registry.py` | Accept internal ownership/recovery authority and enforce it in SQL for process/Workdir mutations and releases. | FR-6–FR-9 |
| Composition | `applications/platform_runtime/runtime_composition.py` | Assemble Outbox, credentials, redaction, selected sandbox, and recovery loops in startup/shutdown order; fail closed. | FR-1–FR-16 |
| Configuration | `core_platform/platform_services/platform_settings/settings.py`; `backend/.env.example`; `deploy/production/.env.example`; relevant Compose files | Secure bounded defaults, Secret-file paths/placeholders, Docker sandbox topology, retention, and rollout controls. | FR-16 |
| Tests | `backend/tests/test_execution_{migration,fencing,events,outbox,sse,usage,diagnostics,credentials,redaction,sandbox,recovery}.py` (new); affected existing suites | Unit, PostgreSQL, multi-Worker, real process, migration, adversarial, and fault-point evidence mapped to 04. | AC-1–AC-16 |

All `core_platform/...` paths above are under `backend/src/agent_platform/`. Existing modules are modification points, not invitations to create duplicate implementations.

## 4. Data Model and Migration 0068

### 4.1 `runtime_runs` expansion

| Field | Type/default | Purpose |
|---|---|---|
| `lease_epoch` | BIGINT NOT NULL DEFAULT 0 | Increment in every new claim/takeover transaction; current claims receive epoch 1. |
| `cancel_requested_at` / `cancel_confirmed_at` | TIMESTAMPTZ NULL | Separate cancellation intent from actual Host/Workdir confirmation; keep existing boolean for wire compatibility. |
| `cleanup_status` / `cleanup_updated_at` | TEXT / TIMESTAMPTZ | `not_started/in_progress/completed/failed`; terminal historical rows backfill to `completed`, others to `not_started`. |
| `retry_of_run_id` / `attempt_no` | UUID self-FK NULL / INT NOT NULL DEFAULT 1 | Correlate manual/safe retries without a Task table. |
| `side_effect_policy` | JSONB NULL | Server-owned retry/side-effect snapshot; clients cannot supply it. |
| `event_retention_floor_seq` | INTEGER NOT NULL DEFAULT 0 | Highest sequence known removed by retention; advances only in the same transaction as eligible deletion. |

### 4.2 `runtime_events` expansion

| Field | Type/default | Purpose |
|---|---|---|
| `event_id` | UUID; deterministic backfill, then NOT NULL + global UNIQUE; new-row default `gen_random_uuid()` | Stable reconnect, Outbox, and consumer identity. Backfill uses a documented UUID derived from `run_id:seq`, not random per rerun. |
| `schema_version` | TEXT NOT NULL DEFAULT `v1` | Existing rows and old writers remain v1. Unknown major versions fail closed. |
| `source` | TEXT NOT NULL DEFAULT `platform` with CHECK | `platform` or `engine_native`. |
| `producer_id` / `producer_event_id` | TEXT NULL | Optional stable native/producer deduplication key; partial unique index on `(run_id, producer_id, producer_event_id)`. |
| `engine_session_id` / `trace_id` | TEXT NULL | Match the existing OpaqueString contract; Session absence is valid. |

The `(run_id,seq)` primary key, `type/data/created_at`, and historical sequence remain unchanged. `AgentEvent.sequence` stays adapter-local metadata and is never written over durable `seq`. T-01 adds optional `producer_id`/`producer_event_id` metadata to the existing v1 AgentEvent/persistence seam; this is additive, existing producers remain valid, and React’s envelope-collision guard is updated to cover the two reserved names.

### 4.3 `runtime_event_outbox`

| Field | Type/constraint | Purpose |
|---|---|---|
| `(run_id, seq)` | Composite PK/FK to `runtime_events` ON DELETE CASCADE | One Outbox row per publishable durable event. |
| `event_id` | UUID NOT NULL UNIQUE | Publisher and consumer idempotency identity. |
| `status` | TEXT CHECK `pending/published` | Publication to the existing durable bus, not subscriber completion. |
| `attempts` / `available_at` | INT / TIMESTAMPTZ | Bounded retry/backoff and rescan. |
| `created_at` / `published_at` | TIMESTAMPTZ | Lag and recovery evidence. |
| `last_error` | TEXT NULL | Bounded redacted stable diagnostic; no event payload. |

An `AFTER INSERT` trigger creates the Outbox row in the same transaction for **every publishable** new event, including old binaries and direct production writers. The internal `tool.replay` type is explicitly excluded because its idempotency payload is not a public extension event; it still receives event identity and Fencing. Application code may use `ON CONFLICT DO NOTHING`, not replace the trigger. Migration does not create Outbox rows for pre-migration history; it records a rollout watermark and reconciles only missing publishable rows at/after that watermark. This prevents direct-writer gaps, internal-payload leakage, and historical event floods. Retention may delete an event only after its Outbox is published; the cascade then removes that publication row while usage/audit remain.

### 4.4 `runtime_usage_ledger`

| Field | Type/constraint | Purpose |
|---|---|---|
| `id` | UUID PK | Source record identity. |
| `run_id` / `tenant_id` / `lease_epoch` | UUID FK / TEXT / BIGINT | Scope and ownership evidence; tenant is duplicated deliberately for bounded scoped queries. |
| `source` / `source_event_id` / `usage_schema_version` | TEXT | Unique source and versioned parsing. Terminal result usage uses a deterministic source such as `engine_terminal:result`; corrected reports use new source IDs. |
| `usage` | JSONB NOT NULL | Validated measured values; unknown markers remain explicit. |
| `cost` / `is_estimate` | NUMERIC NULL / BOOLEAN NOT NULL | Missing cost stays NULL; estimates are marked. |
| `supersedes_id` | UUID self-FK NULL | Provider correction chain; only effective leaves enter aggregates. |
| `created_at` / `updated_at` | TIMESTAMPTZ | Rebuild and audit. |

Use `UNIQUE(run_id, source, source_event_id)`. Duplicate delivery returns the original row without consuming event sequence or changing aggregates. Model-gateway `gateway_costs` remains a separate ledger and is neither copied nor summed implicitly.

### 4.5 Migration execution rules

- T-02 must revalidate the single head. If it changed, register an R-n ruling and revise 01/03/04/05/08 bilingually before creating files; never edit 0001–0067 or another merged revision.
- Use expand → deterministic batched backfill → validate → read/write switch. Measure lock duration on a populated replica before adding NOT NULL/check/unique constraints. Keep old-row defaults compatible during expansion.
- Old Workers must be drained before epoch enforcement is switched on. Mixed old/new enforcement is not a supported writer configuration. Rollback likewise stops admission and drains new Writers before running old code; old code never deletes new columns/tables.
- Normal rollback is expansion-preserving. A populated downgrade requires explicit export/protection and is not routine rollback.

## 5. Data Model and Migration 0069

### 5.1 `execution_credentials`

| Field | Type/constraint | Purpose |
|---|---|---|
| `id` / `credential_ref` / `tenant_id` | UUID version-row PK / UUID + index / TEXT + index | Immutable version-row ID, stable public credential reference, and tenant boundary. Add `UNIQUE(credential_ref, version)`. |
| `name` / `credential_type` | TEXT | Administrative identity and typed Secret handling. |
| `encrypted_secret` / `key_version` | TEXT | Installation-key encryption with Execution binding; plaintext is never stored. |
| `version` / `status` | INT / TEXT CHECK `active/superseded/revoked` | Rotation inserts a new version row and supersedes the old one; revocation applies to every version. |
| `allowed_engines` / `allowed_workspaces` | JSONB | Maximum scope; Broker narrows again per grant. |
| `created_at` / `updated_at` / `rotated_at` / `revoked_at` | TIMESTAMPTZ | Lifecycle audit. |

### 5.2 `execution_credential_grants`

| Field | Type/constraint | Purpose |
|---|---|---|
| `id` / `grant_hash` | UUID PK / TEXT UNIQUE | Internal grant identity and irreversible verification; no replayable token plaintext. |
| `credential_id` / `credential_version` | UUID FK / INT | Pin the issued Secret version. |
| `run_id` / `tenant_id` | UUID FK / TEXT + index | Execution and tenant binding. |
| `engine_id` / `protocol_id` / `workspace_id` | TEXT | Audience and Workspace binding; Workspace is TEXT in current code. |
| `scopes` | JSONB NOT NULL | Minimal allowed environment/mount/operation scopes. |
| `issued_at` / `expires_at` / `revoked_at` / `last_used_at` | TIMESTAMPTZ | TTL, revocation, and use audit. |

Rotation inserts rather than overwrites, so grants retain the exact credential version row they pinned. Only the latest active version can issue new grants; superseded versions cannot issue, while existing grants expire normally unless explicitly revoked. Grants do not cross Runs. A future Session Resume must create/reauthorize a new grant through the same Broker port; Phase 6 does not add the absent Stage B Session store. Secret material exists only in the controlled launch channel. FK deletion and retention must preserve audit evidence and follow current Run retention; no cascade may erase required security history.

## 6. Core Flows

### 6.1 Claim, fencing, and resource ownership

```text
Claim/takeover transaction locks Run
→ lease_epoch += 1; owner + lease_until are replaced
→ Worker builds internal ExecutionOwnership(run_id, owner, lease_epoch)
→ snapshot/append/finish/usage/replay/Host/process/Workdir writes assert the tuple in SQL
→ stale tuple matches zero rows and rolls back the whole mutation
→ a separate post-denial transaction records bounded Fencing audit/metrics
```

Read-then-write checks are diagnostic only. Host/process and Workdir updates join or otherwise constrain against current `runtime_runs` ownership; independent recovery uses an explicit recovery authority obtained by fencing the old epoch, never an impersonated old Worker. The token remains internal to Worker/ExecutionContext/Adapter/Host ports.

### 6.2 Durable event, deduplication, Outbox, and usage

```text
Adapter emits existing AgentEvent
→ Orchestrator passes the envelope to the Worker event sink
→ Repository validates current epoch, schema, source, size, and dedup key in one transaction
→ duplicate event_id/producer key returns the original durable result without incrementing event_seq
→ new event atomically increments runtime_runs.event_seq and inserts runtime_events
→ AFTER INSERT trigger inserts runtime_event_outbox for publishable types in that transaction (never tool.replay)
→ required usage is inserted by source uniqueness in the same transaction
→ after commit, NOTIFY wakes SSE and Outbox dispatcher scans pending rows
→ acknowledged enqueue into existing DurableEventBus using event_id as idempotency_key
→ mark Outbox published; crash before/after is safe to retry
```

For publication, the dispatcher joins the Run tenant and maps to the existing `EventEnvelope` with the same `event_id`, `event_type`, `event_version=1`, `aggregate_type="runtime_run"`, `aggregate_id=run_id`, redacted business payload/metadata, and `idempotency_key=str(event_id)`; `correlation_id` is set only when trace_id is a valid UUID. The durable bus then provides at-least-once subscriber delivery. Outbox `published` means accepted by that durable transport, not that every subscriber committed. SSE remains independent of publisher health. Platform events created through `RunRepository._event` receive the same v1 identity/default/trigger behavior.

### 6.3 SSE replay and retention

```text
Authorize Run/tenant/scope
→ merge after and Last-Event-ID by maximum; malformed input = 400
→ if cursor < event_retention_floor_seq: 409 event_replay_gap + safe reset floor
→ read durable events by seq in 200-row batches
→ emit id=seq, event=type, and legacy data fields plus reserved _execution metadata
→ _execution contains event_id/schema_version/source/trace_id; existing keys are not moved or renamed
→ transient model.delta remains outside the durable cursor
→ finish only after terminal Run and cursor >= event_seq
```

Retention cleanup is disabled by default during rollout. When enabled, it deletes only eligible rows and advances the floor in the same transaction. It never deletes usage/audit records required for accounting or security. Additive `_execution` metadata is the only sanctioned Phase 0 wire diff; all historical fields and SSE `id` semantics remain unchanged.

### 6.4 Vault/Broker, redaction, and launch

```text
Admin creates/rotates/revokes by credential reference; no Secret read API
→ Broker validates tenant/agent/run/engine/protocol/workspace/version/scopes before Host start
→ transaction stores grant hash/metadata and Secret-free audit
→ strong Sandbox prepares launch, network, mounts, and resource limits
→ Broker materializes only allowlisted Secret values into that Execution channel
→ common redaction covers logs/events/SSE/errors/audit/diagnostics/artifact metadata
→ expiry/revocation/terminal cleanup revokes grants and destroys channels
```

The default grant TTL is 300 seconds with a deployment hard maximum of 3600 seconds. Missing key, binding mismatch, expiry, replay outside the original Run, and unavailable sandbox deny before launch. A disclosure response revokes affected credentials and closes new admissions; forensic records contain identifiers and stable codes only.

### 6.5 Strong sandbox, network, and files

`LocalSandboxProvider` remains the controlled/trusted development provider and keeps rejecting untrusted execution. `DockerSandboxProvider` is the initial strong-provider implementation candidate, selected only when its real support probe passes. It must:

- generate a server-owned launch plan through the existing Sandbox Provider/Runner seam; no client argv or Docker socket enters the Execution;
- use an unprivileged user, read-only root, capability drop, no-new-privileges, seccomp, PID/CPU/memory limits, and only the per-Execution Workdir/Secret mounts;
- use `--network=none` when no allowance exists; any allowance requires a managed per-Execution egress proxy/network with DNS/IP/port validation and actual connected-IP pinning on every hop;
- deny private/link-local/metadata addresses, DNS rebinding, unauthorized redirects, tunnels, and direct connections that bypass the proxy;
- export artifacts only through Workspace authorization and leave no container, network, mount, or Secret residue.

A Docker daemon that can create unprivileged sibling containers/networks is a real-environment prerequisite, not evidence supplied by mocks. If this provider cannot enforce a required dimension, admission fails closed and `execution_untrusted_tenants_enabled` remains false.

### 6.6 Recovery, cancellation, retry, and quotas

```text
Cancel/timeout/Worker-loss intent is persisted
→ recovery fences old epoch before new business writes
→ existing Supervisor confirms process-group exit or cleanup_failed
→ Workspace/Host/grant/network cleanup completes or leaves an explicit retryable failure
→ only confirmed cancellation commits cancelled + final event + Outbox
→ Run-active capacity and Host reservations release independently from their actual evidence
```

Automatic retry is limited to proven pre-launch, side-effect-free failure. A new attempt uses `retry_of_run_id`, `attempt_no+1`, and a fresh claim epoch. Ambiguous timeout/disconnection/external-write outcomes require manual handling. Existing Phase 4 process/Workdir recovery is reused; Phase 6 coordinates it with Run ownership and terminal/event transactions.

### 6.7 Usage corrections and parser diagnostics

- Terminal `ExecutionOutcome.usage` is passed into `RunRepository.finish` with deterministic source identity; duplicate finish/replay cannot recount it.
- Native usage uses stable producer/native identity where available. Missing values remain unknown; provider corrections use `supersedes_id`; aggregates rebuild from effective ledger leaves.
- Parser diagnostics classify `malformed`, `unknown_schema`, `unknown_type`, `size_limit`, and `critical_terminal`; include Run/protocol/adapter correlation and are rate-limited per Run.
- Raw samples are disabled by default. If temporarily enabled, they are redacted, capped at 1024 bytes, private, and retention-bound. Diagnostic failure never recursively emits diagnostics.
- Codex malformed/oversized behavior and payload filtering are regression inputs, not replaced behavior.

## 7. Configuration

Add the following to `platform_settings/settings.py`, excluding rollout values from the runtime fingerprint:

| Setting | Default and bound | Meaning |
|---|---|---|
| `execution_untrusted_tenants_enabled` | `false` | Master exposure gate; cannot bypass any sub-policy or independent approval. |
| `execution_sandbox_required` | `true` | Untrusted execution has no host fallback. |
| `execution_sandbox_provider` | existing `local`; add `docker` only with T-08 | Local remains non-strong; Docker requires support probes. |
| `execution_network_default_deny` | `true` | No direct egress by default. |
| `execution_credential_grant_ttl_seconds` | `300`, range 30–3600 | Short grant lifetime and hard ceiling. |
| `execution_outbox_enabled` | `false` during rollout | Controls dispatcher only; persistence, trigger, Fencing, and redaction stay on. |
| `execution_outbox_batch_size` / `execution_outbox_poll_seconds` | `100` / `1.0` | Bounded scan/retry cadence. |
| `execution_event_retention_days` | `30`, range 1–3650 | Retention policy used only when cleanup is enabled. |
| `execution_event_cleanup_enabled` | `false` | Prevents immediate historical deletion during rollout. |
| `execution_parser_raw_sample_enabled` | `false` | Raw samples are off. |
| `execution_parser_sample_max_bytes` / `execution_parser_max_diagnostics_per_minute` | `1024` / `10` | Bounded private diagnostics. |
| `execution_credential_key_file` | `data/credentials/execution.key` locally; production sets its Secret mount path | Missing/unreadable key fails closed; real key comes from deployment Secret storage and examples contain no generated Secret. |

Existing process cancellation, wall, resource, and Workdir settings remain the source for those limits. New settings receive `.env.example` placeholders only; no key, token, password, or host home directory is committed.

## 8. Model Invocation and Existing Accounting

This phase does not change React/Codex model selection, Stage A/B gates, production adapter selection, reasoning loops, or model-gateway profile behavior. Execution credentials and model-connection credentials are not interchangeable. Execution usage follows Adapter/ExecutionOutcome → Run ownership validation → `runtime_usage_ledger`; existing model-gateway `gateway_costs` continues to account for gateway attempts independently.

## 9. Test Plan Summary

| Layer | Cases |
|---|---|
| Unit | Ownership/retry matrices, envelope/dedup, Outbox state, cursor gaps, usage corrections, diagnostics, grant binding/TTL, redaction, launch/network/path policy, secure settings. |
| PostgreSQL integration | Migration/backfill/trigger, two-Worker fencing, direct-writer coverage/internal replay exclusion, state+event+Outbox+usage faults, Outbox rescan, multipage SSE, credential audit. |
| Real process/adversarial | Strong-container escape/resource limits, DNS/metadata/proxy attacks, links/mounts/artifacts, Secret canaries, SIGKILL/hang/timeout/cleanup failure. |
| Focused regression | Only affected existing runtime, Orchestrator, Host, Workspace, Codex, credential/egress, and migration cases per `08` §3; full suites run once in CI, not repeatedly unchanged. |

Detailed IDs remain in `04-test-plan.en.md`; unavailable real environments stay `pending_env` and block the corresponding final gate.

## 10. Rollout and Rollback

1. Preserve the direct-continue development entry while recording that Phase 0 and full Phase 5 acceptance are not complete. Code readiness cannot be presented as final phase acceptance.
2. Revalidate head, land 0068, backfill/validate, drain old Writers, then enable epoch enforcement. Enable Outbox persistence first and dispatcher later; reconcile pending/missing rows before and after each switch.
3. Deploy SSE additive metadata and disabled retention cleanup, then usage/diagnostics. Rehearse old-binary reads and explicit replay gaps before enabling deletion.
4. Land 0069 and credential management with untrusted execution off. Roll out Broker/redaction to controlled test Runs before any Secret-bearing real provider case.
5. Enable the strong provider only after its support probe and real attack matrix pass. `execution_untrusted_tenants_enabled=true` additionally requires every A/C gate and separate independent security and SRE/operations approvals.
6. Rollback closes new admissions, revokes grants, isolates/cleans active sandboxes, drains Writers, and disables new publishers while preserving tables/events/usage/credentials. Reconcile Outbox before old-binary operation; never use data-deleting downgrade as routine rollback.
7. Any Secret disclosure, successful escape, effective stale write, duplicate billing, silent event gap, or terminal/accounting inconsistency stops new execution and blocks acceptance. Five coordination rounds are a rework limit, not permission to waive a hard gate.
