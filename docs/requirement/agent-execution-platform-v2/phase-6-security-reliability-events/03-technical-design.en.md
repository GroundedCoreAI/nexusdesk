# Phase 6 · Security, Reliability, and Event Governance — Technical Design

> Status: Pending review (planning only, not implemented; migration numbers and target paths require implementation-time rechecks)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G7), `02-requirements.md` (FR-1–FR-16, AC-1–AC-16), and architecture Sections 7–10, 12, and 16–18

> Current code, tests, migrations, credentials, and SSE precedents were audited before this document was written; later revisions must record date and reason in the affected section.

## Current-state Audit and Constraints

| Area | Facts as of 2026-11-02 | Constraint for this phase |
|---|---|---|
| Run/Lease | `agent_runtime/repository.py` uses owner, lease_until, terminal checks, and conditional updates; `worker.py` cancels a Task when heartbeat ownership is lost. | Reuse the queue, add monotonic lease_epoch, and cover every write/resource operation rather than protecting finish alone. |
| Worker recovery | `reap()` marks expired running Runs failed/worker_lost; `test_runtime_postgres.py` covers late results. | Preserve terminal-state precedents and add takeover, cleanup, retry side effects, and Host liveness evidence. |
| Event source of truth | `runtime_runs.event_seq` and `runtime_events(run_id,seq)` update in one transaction; the PK guarantees Run-local ordering. | Extend with event_id/schema/source/dedup/Outbox without replacing or renumbering historical seq. |
| SSE | `customer_service/runtime_routes.py` reads the Event Store in batches, supports `after`/`Last-Event-ID`, uses SSE id=seq and NOTIFY only as wakeup; model.delta is transient. | Preserve wire compatibility and transient-delta semantics while adding event_id deduplication, retention gaps, and catch-up race tests. |
| Credentials | `platform_services/secrets/vault.py` uses installation-key Fernet; `0016_gateway_credentials` and model Catalog provide tenant/address binding, but no Execution grant/Broker exists. | Reuse encryption/binding lessons with new Engine Execution records and Broker; do not treat a public model-connection ID as Execution authorization. |
| Network/files | `tool_gateway/egress.py` has HTTP-tool host/IP protection; logical Workspace has scope. | Reuse normalization/IP lessons, but arbitrary child-process networking and mounts require Sandbox/OS enforcement, not only an HTTP client. |
| Codex/Host | No Codex or `agent_execution` implementation currently exists; Phases 4/5 are prerequisite plans. | Recheck target files against actual Phase 4/5 deliverables and do not reimplement Adapters or RuntimeHost in this phase. |
| Migrations | Current head is `0052_memory_tasks_tenant_index`; 0055 is a conditional Phase 5 planning number. | 0056/0057 are reserved planning numbers only; actual down_revision follows implementation-time head, does not assume 0055 exists, and never changes historical migrations. |

## Change Overview

| Layer | File | Change | Traceability |
|---|---|---|---|
| Credentials | `backend/src/agent_platform/core_platform/agent_execution/credentials/{vault,broker,models,repository}.py` | Execution credential versions, short-lived grants, scope/audience binding, rotation/revocation/audit. | FR-1, FR-2 |
| Redaction | `.../agent_execution/security/redaction.py` (or the actual Phase 4 security package) | Common log/event/error/diagnostic/artifact-metadata redaction and disclosure-response interface. | FR-3 |
| Sandbox | `.../agent_execution/sandbox/{provider,policy,network,filesystem}.py` | Engine-independent strong-sandbox policy, network/file boundaries, and resource limits. | FR-4–FR-6 |
| Host integration | `.../agent_execution/host/{runtime_host,process_supervisor,resource_manager}.py` | Add sandbox, grants, actual exit/cleanup confirmation, and epoch to the Phase 4 implementation. | FR-2, FR-4, FR-7, FR-9 |
| Reliability | `.../agent_execution/reliability/{fencing,recovery,cancellation,retry}.py` | Ownership validation, Worker takeover, cleanup/quota coordination, and side-effect-aware retry classification. | FR-7–FR-10 |
| Run persistence | `backend/src/agent_platform/core_platform/agent_runtime/repository.py` | Add epoch, cancellation/cleanup, and transactional Outbox/usage to claim/heartbeat/append/finish/reap. | FR-7–FR-12, FR-14 |
| Events | `.../agent_execution/events/{schema,store,dedup,outbox,dispatcher,replay}.py` | Versioned envelope, deduplication, Outbox publication/rescan, cursors, and retention gaps. | FR-11–FR-13 |
| Usage/diagnostics | `.../agent_execution/events/{usage,diagnostics}.py` | Source-unique usage ledger, aggregate rebuilding, and parser classification/rate limiting/redaction. | FR-14, FR-15 |
| Adapter integration | Actual Phase 1/5 Adapter base and Codex Provider | Propagate native dedup keys, schemas, usage, and parser diagnostics without adding Engine branches to the Worker. | FR-11, FR-14, FR-15 |
| SSE/API | `backend/src/agent_platform/applications/customer_service/runtime_routes.py` | Keep `id=seq`, add event_id/schema, 409 replay gap, and reconnect/terminal consistency. | FR-13 |
| Composition root | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | Assemble Vault/Broker/Sandbox/Recovery/Outbox/Usage; fail closed when security components are unavailable. | FR-1–FR-16 |
| Configuration | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | Bounded grant TTL, retention/cleanup/retry, default-deny network, and untrusted-execution master switch. | FR-16 |
| Migration | `backend/migrations/versions/0056_execution_fencing_event_outbox.py` | Planned epoch/cancellation-cleanup/retry metadata, event identity/dedup, Outbox, and usage ledger. | FR-7–FR-14 |
| Migration | `backend/migrations/versions/0057_execution_credential_security.py` | Planned Execution credential and short-lived grant tables; sandbox policy remains configuration/Run snapshots. | FR-1, FR-2 |
| Deployment | `backend/.env.example`, `deploy/production/.env.example`, and actual sandbox deployment configuration | Secret-free placeholders and network/mount/resource policies only; deployment Secrets manage real keys. | FR-1–FR-6, FR-16 |
| Tests | `backend/tests/test_execution_{security,fencing,recovery,outbox,sse,usage,diagnostics}.py` | Unit/Postgres/multi-Worker/fault-point/sandbox adversarial and migration regressions. | AC-1–AC-16 |

> Ellipses above denote the same `backend/src/agent_platform/core_platform/` root. Module paths are planning boundaries; if Phases 1–5 already provide equivalent modules, extend them rather than creating parallel implementations.

## Data Model

### Planned migration `0056_execution_fencing_event_outbox.py`

**A. `runtime_runs` expansion**

| Field | Planned type/constraint | Purpose |
|---|---|---|
| `lease_epoch` | BIGINT NOT NULL, existing rows backfilled to 0 | Incremented monotonically at claim/takeover; together with owner forms Fencing evidence. |
| `cancel_requested_at` / `cancel_confirmed_at` | TIMESTAMPTZ NULL | Distinguishes cancellation request from actual exit/cleanup confirmation. |
| `cleanup_status` / `cleanup_updated_at` | TEXT / TIMESTAMPTZ | `not_started/in_progress/completed/failed` for reentrant recovery and alerts. |
| `retry_of_run_id` / `attempt_no` | UUID self-reference NULL / INT | Run=one attempt, correlating retries without a Task table. |
| `side_effect_policy` | TEXT/JSONB, rechecked against the Phase 1 configuration model | Snapshots automatic-retry/manual-confirmation policy and prevents client expansion. |

**B. `runtime_events` expansion**

| Field | Planned type/constraint | Purpose |
|---|---|---|
| `event_id` | UUID, NOT NULL after backfill + global UNIQUE | Stable deduplication identity across reconnect/Outbox/usage; backfill existing rows deterministically from Run+seq. |
| `schema_version` | TEXT, existing rows backfilled to `v1` | Explicit version routing and compatibility. |
| `source` | TEXT, existing rows backfilled to `platform` | `platform` or `engine_native`. |
| `producer_id` / `producer_event_id` | TEXT NULL | Native/producer deduplication key; unique with run_id when non-null. |
| `engine_session_id` / `trace_id` | UUID/TEXT NULL, rechecked against actual models | Correlates Sessions and traces without changing public historical events. |

Retain the `(run_id,seq)` primary key, existing `type/data/created_at`, and SSE id=seq; do not add NOT NULL payload rewrites that conflict with historical semantics.

**C. New table `runtime_event_outbox`**

| Field | Planned type/constraint | Purpose |
|---|---|---|
| `(run_id, seq)` | Composite PK/FK to `runtime_events` | One Outbox per event, linked to the source of truth. |
| `event_id` | UUID NOT NULL UNIQUE | Correlates publication and consumer deduplication. |
| `status` | TEXT CHECK: `pending/published` | Publication state; failures remain pending with bounded errors. |
| `attempts` / `available_at` | INT / TIMESTAMPTZ | Bounded backoff and recovery scans. |
| `created_at` / `published_at` | TIMESTAMPTZ | Lag, recovery, and audit metrics. |
| `last_error` | TEXT NULL | Bounded redacted publication diagnostics without payload/Secrets. |

**D. New table `runtime_usage_ledger`**

| Field | Planned type/constraint | Purpose |
|---|---|---|
| `id` | UUID PK | Usage source-record ID. |
| `run_id` / `lease_epoch` | UUID FK / BIGINT | Run correlation and write-ownership evidence. |
| `source` / `source_event_id` / `usage_schema_version` | TEXT | Source uniqueness and versioned parsing. |
| `usage` | JSONB NOT NULL | Validated typed token/call and other usage without Secrets. |
| `cost` / `is_estimate` | NUMERIC NULL / BOOLEAN | Nullable cost and estimate marker; missing values are not zero-filled. |
| `supersedes_id` | UUID self-reference NULL | Provider-correction chain rather than blind accumulation. |
| `created_at` / `updated_at` | TIMESTAMPTZ | Aggregate rebuilding and audit. |

Plan `UNIQUE(run_id, source, source_event_id)`; aggregate views/queries count only the currently effective correction chain, and old-epoch writes are denied after same-transaction Run-ownership validation.

Design points:

- Use expand → deterministic batched backfill → validate → read/write switch. Review online steps for large-table defaults, indexes, and NOT NULL against the actual PostgreSQL version/data volume to avoid long locks.
- Commit state+event+Outbox+required usage in one transaction; Outbox provides at-least-once delivery plus event_id idempotent consumers, not network-level exactly-once claims.
- Do not backfill Outbox to republish all historical events unless migration review explicitly requires it; establish a publication starting point and avoid historical event floods.
- Follow repository convention for explicit export/protection before populated downgrades; normal rollback retains new columns/tables, and old code must not delete or renumber data.

### Planned migration `0057_execution_credential_security.py`

**A. New table `execution_credentials`**

| Field | Planned type/constraint | Purpose |
|---|---|---|
| `id` / `tenant_id` | UUID PK / TEXT + index | Credential reference and tenant boundary. |
| `name` / `credential_type` | TEXT | Administrative identity and typed parsing. |
| `encrypted_secret` / `key_version` | TEXT | Installation-key/KMS-interface encryption, never plaintext at rest. |
| `version` / `status` | INT / TEXT CHECK: `active/revoked` | Rotation version and immediate revocation. |
| `allowed_engines` / `allowed_workspaces` | JSONB | Maximum credential binding scope; Broker still authorizes each use. |
| `created_at` / `updated_at` / `rotated_at` / `revoked_at` | TIMESTAMPTZ | Lifecycle audit. |

**B. New table `execution_credential_grants`**

| Field | Planned type/constraint | Purpose |
|---|---|---|
| `id` / `grant_hash` | UUID PK / TEXT UNIQUE | Grant identity and irreversible verification without storing replayable Token plaintext. |
| `credential_id` / `credential_version` | UUID FK / INT | Pins the credential version at issuance. |
| `run_id` / `tenant_id` | UUID FK / TEXT + index | Usable only by the specified Execution/tenant. |
| `engine_id` / `protocol_id` / `workspace_id` | TEXT (Workspace type rechecked) | Audience and Workspace binding. |
| `scopes` | JSONB NOT NULL | Minimal permission set that execution cannot expand. |
| `issued_at` / `expires_at` / `revoked_at` / `last_used_at` | TIMESTAMPTZ | Short validity, revocation, and use audit. |

Design points:

- Grants never transfer across Runs/Session Resume; Resume creates a new Run and issues a new grant. Secret mounts/environment exist briefly only inside the controlled sandbox, while the database stores metadata and irreversible verification values.
- Reuse existing audit facilities for actor/action/resource/revision correlation; audit never records `encrypted_secret`, grant Tokens, environment values, or complete mount contents.
- Deletion/downgrade must not cascade away records needed for audit; freeze FK deletion policy and retention during implementation review under existing Run-retention rules.

## Core Flows

### 1. Vault/Broker and sandbox launch (`credentials/` + `sandbox/`)

```text
Trusted API/Worker requests launch
→ Broker validates tenant/agent/run, Engine/Protocol, Workspace, credential version/scopes
→ Record short-lived grant metadata and Secret-free audit in one transaction
→ Sandbox Provider creates unprivileged, default-deny-network, minimal-mount, resource-limited environment
→ Broker materializes credentials only into that Execution's controlled Secret channel
→ Host starts the Engine; log/event/diagnostic exits use common redaction
→ Expiry/cancellation/completion/revocation revokes grants and destroys channels/sandbox
```

- If sandbox or grant is unavailable, do not launch; never fall back to direct host execution or long-lived shared environment.
- Existing `ToolEgressPolicy` offers host/IP normalization lessons but cannot replace OS/sandbox network enforcement.

### 2. Claim/Takeover and Fencing on every write (`repository.py`, `reliability/fencing.py`)

```text
Claim/takeover transaction locks the Run
→ Validate claimable/takeover state
→ lease_epoch = lease_epoch + 1; write owner/lease_until
→ Return (run_id, owner, lease_epoch) to Worker/Host
→ Every append/finish/usage/session/outbox/resource operation validates the same tuple and lease in DB conditions
→ Mismatch updates zero rows, rolls back the transaction, and records Fencing denial
```

- Heartbeat validates the same tuple; never SELECT first and then UPDATE without constraints. If an independent recovery actor may clean resources, use separately authorized recovery ownership rather than impersonating the old Worker epoch.
- Late old-epoch events/usage do not enter dedup ledgers or Outbox; terminal state and final event commit in one transaction.

### 3. Worker loss, cancellation/timeout, cleanup, and retry (`recovery.py`, `cancellation.py`, `retry.py`)

```text
Failure/cancellation/timeout
→ Pin cancel/timeout intent and block new business writes
→ Recovery obtains a new epoch or authorized cleanup ownership, fencing the old Worker
→ Host inspects process trees/connections/mounts and performs graceful→forced cleanup
→ After actual exit/resource-release confirmation, write one terminal state+final event+Outbox
→ If unconfirmed, use failed/cleanup_failed or explicit pending-cleanup recovery and alert; never false-cancel
→ Reconcile and release Run-active quota and Host resource reservations
```

- Automatic retry is limited to pre-launch, side-effect-free errors; new Runs use `retry_of_run_id`, a new attempt/epoch, and idempotent correlation. Timeout, disconnection, or completed external writes default to manual handling.
- Current admission counts queued/running rows for capacity, so the unique-terminal-state precedent can release active slots; Host resource quotas separately require actual release confirmation, and the two must not be conflated.

### 4. State, events, deduplication, Outbox, and Usage transaction (`events/`)

```text
Receive a native/platform event with Run/epoch
→ Validate ownership, schema/version, and payload bounds in a transaction
→ Deduplicate by (run_id, producer_id, producer_event_id)
→ Duplicate returns the original result; only new events atomically increment event_seq
→ Insert runtime_events(event_id, seq, ...) and runtime_event_outbox
→ For usage, write runtime_usage_ledger by source uniqueness
→ Commit state/event/Outbox/usage together; NOTIFY wakes readers after commit
→ Dispatcher reads pending, publishes at least once, and marks published idempotently by event_id
→ Rescan pending after crashes; the database Event Store always remains replayable
```

- Duplicate events consume no new seq and produce no duplicate audit side effects or usage. Terminal event and Run terminal state commit together, and the durable SSE stream ends only after the final event is visible.
- Publisher failure does not change the factual Run terminal state; monitor Outbox lag and recover from the database rather than relying on NOTIFY for data recovery.

### 5. SSE reconnect and retention gaps (`runtime_routes.py`, `events/replay.py`)

```text
Authorize Run/tenant/scope
→ Parse after and Last-Event-ID, take the greater cursor, and validate
→ If cursor predates the retention floor: 409 event_replay_gap + safe reset information
→ Read Event Store in seq batches; send id=seq, event/type/data (data contains event_id/schema_version)
→ Subscribe to live wakeups and reread the database to close subscribe/query races
→ Clients deduplicate by event_id; transient model.delta has no durable cursor and cannot affect the final answer
→ End when Run is terminal and cursor >= event_seq
```

- Complete replay is not promised beyond retention, and silently starting at “earliest available” must never masquerade as gap-free delivery. Retention cleanup must not delete data still required for audit/accounting.

### 6. Usage corrections and parser diagnostics (`usage.py`, `diagnostics.py`)

- Usage writes idempotently by `(run_id, source, source_event_id)`; duplicates return the original record, provider corrections form a `supersedes_id` chain, aggregates rebuild from the ledger, and old epochs are always denied.
- Parser errors classify as malformed/unknown_schema/unknown_type/size_limit/critical_terminal and correlate with Run/Protocol/Adapter version; diagnostics contain only bounded redacted samples and are rate-limited.
- Skippable events and unparseable critical terminal events use different policies; diagnostic-write failure cannot recursively generate diagnostic events, and security disclosure follows independent alerting and credential-revocation flows.

## Configuration

Plan to add the untrusted master switch (default false), sandbox-required/network-default-deny (default true), grant-TTL hard limit, cleanup/retry/backoff, event retention, Outbox batch/interval, usage aggregation, and parser sample/rate-limit settings to `platform_settings/settings.py`.

- `execution_sandbox_required` and default-deny policies are not availability switches; legacy compatibility applies only to existing trusted React/controlled execution and cannot let untrusted tasks bypass them.
- `execution_outbox_enabled` controls only the rollout publisher; it cannot disable Event Store persistence, Fencing, redaction, or security audit, and rollback requires rescan/reconciliation of old/new writes.
- Secrets, master keys, and grant Tokens come only from deployment Secret files/environment or controlled mounts; `.env.example` contains placeholders only.

## Model Invocation Path

This phase does not change React/Codex model selection or reasoning paths. Existing Model Gateway credentials remain managed by their Catalog/Vault, while Engine Execution credentials use the new Broker; the two are never implicitly interchangeable. All model/Engine usage follows Adapter → ExecutionResult/native usage → `runtime_usage_ledger` → idempotent aggregation; missing values are unknown, estimated cost is marked, and repeated events never accumulate again.

## Test Plan Summary

| Layer | Cases |
|---|---|
| Unit | Grant scope/TTL, redaction, network/IP/path, Fencing conditions, retry matrix, schema/dedup/usage/parser. |
| Integration | Multi-Worker takeover, fault-point transactions, Outbox rescan, SSE multipage reconnect, migration backfill, and real Vault/Broker. |
| Adversarial/fault drills | Sandbox escape, DNS/metadata/symlink/Secret canary, SIGKILL/network loss/disk full/process hang/Worker crash. |
| Regression | React/Codex/Run/API/SSE, historical data, existing credentials and Workspace; unmeasured Phase 0 baselines remain blockers. |

See `04-test-plan.md` for detailed cases and exit criteria.

## Rollout and Rollback

1. Complete the Phase 0 baseline and Phase 1–5 acceptance; freeze the attack matrix, fault-point list, event retention, and RTO/RPO after baseline review.
2. Recheck head before implementation; land planned 0056 and then 0057 according to actual dependencies. Use expand/backfill/validate/switch and rehearse replica upgrade, backfill validation, locking/duration, and downgrade data protection.
3. Deployment order: read-compatible new schema → Fencing/transactional writes → Outbox rescan/publication → idempotent usage → SSE new fields/gaps → Vault/Broker → sandbox/network/files; no step opens untrusted tenants by default.
4. Canary with a trusted test tenant, then obtain independent security/SRE adversarial sign-off; enable `execution_untrusted_tenants_enabled=true` only after every hard gate passes, and open tenants in small batches.
5. Rollback disables new untrusted executions, revokes active grants, and isolates/cleans active sandboxes; retain new tables/columns/events/usage/credential records. Rehearse old-binary compatibility and Outbox reconciliation; never use a data-deleting down migration as routine rollback.
6. Any P0 disclosure/escape/escalation, Fencing failure, or terminal/accounting inconsistency immediately stops new executions and alerts; feature switches must never degrade security checks.
