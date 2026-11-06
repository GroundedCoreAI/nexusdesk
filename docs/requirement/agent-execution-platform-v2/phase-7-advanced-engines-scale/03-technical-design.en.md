# Phase 7 · Advanced Engine Capabilities and Scale — Technical Design

> Status: Planning (target design; no claim that modules, APIs, tables, or migrations exist; actual launch scope is reviewed per slice)
> Created: 2026-11-02
> Basis: `01-business-goals.en.md` (G1~G11), `02-requirements.en.md` (FR-1~FR-11, AC-1~AC-22), architecture §4~19 and §22, and current-code review
> Baseline statement: The latest reviewed migration head is `0052_memory_tasks_tenant_index`; behavioral/performance baselines are unmeasured pending Phase 0. Every `0058+` identifier here is a planning number; recheck head, renumber, and set real dependencies before implementation
> Constraint: This document defines logical models, flows, and file-level plans only, not implementation code or executable migrations

## Change Overview

### Current Code Facts and Design Constraints

| Current location | Fact reviewed on 2026-11-02 | Phase 7 constraint |
|---|---|---|
| `backend/src/agent_platform/core_platform/agent_runtime/engine.py` | LangGraph ReAct Runtime directly constructs the model/tool loop | Retain inside the React Provider; do not spread Engine-specific concepts into the Worker |
| `backend/src/agent_platform/core_platform/agent_runtime/worker.py` | Worker directly invokes `runtime.run`, claims Runs for configured `settings.tenant_id`, and collaborates on Lease, cancellation, and terminal state | Phase 2 should first switch to the Orchestrator; Phase 7 fair scheduling extends multi-tenant claim context, with no routing/vendor logic in Worker |
| `backend/src/agent_platform/core_platform/agent_runtime/repository.py` | Durable queue, FIFO claim, events, capacity counts, and conditional terminal updates | Reuse queue and transactions; fair scheduling and waiting require additive changes without weakening Lease/terminal protection |
| `backend/src/agent_platform/core_platform/agent_runtime/schemas.py` | Run states are only queued/running/completed/failed/cancelled | waiting is an explicit additive change requiring coordinated constraint, index, API, SDK, and UI updates |
| `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` | Builds a fixed ReAct Runtime and fixed model Profile from an Agent snapshot | Phase 1~2 should already move core resolution to Registry/Orchestrator; dynamic models extend only React model binding |
| `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | Composition root explicitly constructs Runtime, Repository, Worker, and platform services | Inject new services only here and in corresponding application entry points; Adapters do not acquire global services or cross-module repositories themselves |
| `backend/src/agent_platform/business_capabilities/agent_config/service.py` | `AgentConfig(extra="forbid")` uses fixed `model_profile_id/version` | New Engine/dynamic-model/Skill references must be typed, compatibly defaulted, and included in published snapshots |
| `backend/src/agent_platform/core_platform/platform_services/model_gateway/` | Already has versioned Profiles, model fallback, quotas, calls/attempts, usage, and estimated cost | Reuse model-call and cost facts; dynamic selection and Engine usage must neither reimplement nor double-charge them |
| `backend/src/agent_platform/business_capabilities/approval/service.py` | Already has tenant isolation, idempotent creation, revision, separation of duties, decisions, and audit | Associate Executions through a transactional port and reuse the approval state machine rather than creating a parallel business flow |
| `backend/src/agent_platform/core_platform/platform_services/storage/objects.py` | Only an S3 put wrapper for knowledge archive | Create an execution Artifact port with separate configuration; knowledge credentials/paths are not default execution storage |
| `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | `AGENT_` prefix and existing global/tenant active-capacity settings | All nine Phase 7 flags default false; sensitive configuration stores environment Secret references only |
| `frontend/src/shared/components/ui.tsx`, `frontend/src/features/models/GatewayReports.tsx` | Consume current SSE and model reports | Incrementally support waiting, Effective capabilities, Engine usage, and unknown states with all text in i18n |
| `backend/migrations/versions/0052_memory_tasks_tenant_index.py` | Highest migration number found in this review | Never describe the planning numbers below as existing; recheck current head for every slice |

### Target File-Level Plan

The `agent_execution` paths below follow architecture §16 and may be added/modified per slice only after Phase 1~6 establishes the corresponding boundaries.

| Layer/slice | File (planned) | Change |
|---|---|---|
| S7-01 contracts | `backend/src/agent_platform/core_platform/agent_execution/contracts/` | Reuse common Request/Handle/Result/Event/Error; add only necessary versioned extension points and no vendor fields |
| S7-01 Adapter | `backend/src/agent_platform/core_platform/agent_execution/adapters/testing/local_test_adapter.py` | Add deterministic faults, duplicate/late events, usage, and capability-matrix simulation |
| S7-01 tests | `backend/tests/agent_execution/contract/` | Build a parameterized contract suite shared by all Adapters plus dependency-boundary checks |
| S7-02 routing | `backend/src/agent_platform/core_platform/agent_execution/orchestration/route_planner.py`, `fallback_policy.py` | Generate trusted RoutePlans, classify side effects, and reauthorize every candidate |
| S7-02 capabilities | `backend/src/agent_platform/core_platform/agent_execution/capability/capability_resolver.py` | Emit Effective snapshots with reasons and policy versions; provide DTOs to the read-only UI projection |
| S7-03 Session | `backend/src/agent_platform/core_platform/agent_execution/session/session_manager.py`, `session_repository.py` | Lifecycle, binding checks, expiry cleanup, resume reauthorization, and idempotent Run creation |
| S7-04 interaction | `backend/src/agent_platform/core_platform/agent_execution/interaction/interaction_manager.py`, `interaction_repository.py`, `approval_port.py` | Durable waiting, approval transaction port, Schema input, expiry/cancellation, and recovery |
| S7-05 models | `backend/src/agent_platform/core_platform/agent_execution/models/model_selection.py` | Bounded deterministic rules, Profile eligibility filtering, and selection snapshots |
| S7-06 usage | `backend/src/agent_platform/core_platform/agent_execution/usage/usage_contracts.py`, `usage_repository.py`, `usage_reporting.py` | Normalization, idempotency, additive/informational data, unknown values, and per-currency aggregation |
| S7-07 scheduling | `backend/src/agent_platform/core_platform/agent_runtime/worker.py`, `admission.py`, `repository.py`; `agent_execution/scheduling/fair_claim.py` | Wire multi-tenant fair-claim context, atomic queued/running admission, fair candidate selection, and fresh admission for wait recovery; Worker holds no Engine logic |
| S7-08 Skills | `backend/src/agent_platform/core_platform/agent_execution/skills/skill_store.py`, `skill_adapter.py` | Version/hash/source/permissions, shared read-only mounts, and Engine-format conversion |
| S7-08 Artifacts | `backend/src/agent_platform/core_platform/agent_execution/artifacts/artifact_store.py`, `object_store.py` | Authorized metadata, object write/download, retention, scan state, and cleanup |
| S7-09 Profiles | `backend/src/agent_platform/core_platform/agent_execution/host/runtime_profile.py`, `health_monitor.py`, `circuit_breaker.py` | Versioned configuration snapshots, active/passive health, distributed state, and half-open recovery |
| Common orchestration | `backend/src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py` | Wire routing, Sessions, interactions, models, Workspace, usage, and Profiles without implementing Engine reasoning |
| Common persistence | `backend/src/agent_platform/core_platform/agent_runtime/repository.py`, `schemas.py` | Add waiting/execution correlation and fair claim while retaining legacy reads, event cursors, and conditional terminal updates |
| Configuration | `backend/src/agent_platform/business_capabilities/agent_config/service.py`; `platform_settings/settings.py` | Typed optional policies, nine flags, limits, and Secret-reference validation |
| API | `backend/src/agent_platform/applications/platform_runtime/execution_routes.py`, `runtime_composition.py` | Planned Resume, interaction, Effective, usage, Artifact, and Profile-management endpoints plus composition wiring |
| Frontend | `frontend/src/shared/api/client.ts`, `shared/components/ui.tsx`, `features/execution/`, `features/models/GatewayReports.tsx` | Effective/waiting/health/Artifact/unified-report UI without unauthorized controls |
| Deployment | `deploy/`, `.env.example` (only when implementing the corresponding slice) | Add non-sensitive placeholders and health/storage settings; Secrets remain only in untracked environment files |

## Data Model

### Migration Planning Table

| Planning number (none is an existing file) | Slice | Logical change | Mandatory pre-implementation checks |
|---|---|---|---|
| `0058_phase7_engine_sessions` (conditional) | S7-03 | Reuse Phase 5 `agent_engine_sessions` when present and extend it only with nullable columns/indexes for generic Sessions; review table creation only if Phase 5 did not create it | Recheck head, actual Phase 5 Session/Execution fields and whether `0055` was implemented, existing indexes, and real `down_revision`; never recreate the table |
| `0059_phase7_execution_waits` | S7-04 | Add `agent_execution_waits`; allow waiting Run state; include waiting in the same-conversation active index | Recheck head, every Run-state consumer, public API/SDK/UI, and approval association constraints |
| `0060_phase7_engine_usage` | S7-06 | Add `engine_usage_records` plus idempotency/reporting indexes | Recheck head, Phase 6 event Outbox, gateway fact tables, and report volume |
| `0061_phase7_fair_scheduling` | S7-07 | Add `runtime_tenant_fairness` and necessary queue indexes | Recheck head, current capacity semantics, EXPLAIN, multi-Worker lock order, and online migration behavior |
| `0062_phase7_skills_artifacts` | S7-08 | Add Skill/version and Artifact metadata tables plus scope/retention indexes | Recheck head, Workspace/Object Store ports, and retention/scan state machine |
| `0063_phase7_runtime_profiles` | S7-09 | Add Profile/version/health tables plus tenant-binding and state indexes | Recheck head, actual Registry/Host identifiers, distributed locking, and configuration-version patterns |

The numbers are not exclusive reservations and need not remain contiguous. If another requirement takes one, use the next available number at implementation time and update documents 01~05. Every migration is expand-only: add tables/nullable columns/indexes first, keep code compatible with the old shape, then enable after flag verification. Rollback disables flags/removes code without deleting historical data.

### Reused and Extended Model `agent_engine_sessions` (S7-03)

This is the target field view for generic Sessions, not a request to create the table again. If Phase 5 Stage B implemented `0055`, S7-03 must reuse existing records with compatible reads and migrate only fields genuinely missing for generic capabilities; review a new table only if Phase 5 did not create one.

| Field group | Content | Invariant |
|---|---|---|
| Identity and scope | `id`, `tenant_id`, `business_id`, `workspace_id`, `conversation_id` | Every read/write uses trusted scope; a native Session ID is not a cross-tenant authorization credential |
| Execution binding | `engine_id`, `protocol_id`, `adapter_version`, `provider_session_id` | Native ID is unique within scope/Adapter; Resume does not automatically change the tuple |
| Policy snapshot | Current binding hash, Agent/Workspace binding, Runtime Profile reference, metadata schema version | Old snapshots support compatibility checks and audit; resume still loads current policy and reauthorizes |
| Lifecycle | `status=active|expired|closed|failed`, `expires_at`, created/updated/closed timestamps | Non-active or expired Sessions cannot resume; cleanup retains necessary audit |

`metadata` contains only Adapter-versioned non-Secret data. Native tokens, sensitive host paths, and complete process environments must not be persisted.

### Planned Model `agent_execution_waits` (S7-04)

| Field group | Content | Invariant |
|---|---|---|
| Identity and scope | `id`, `tenant_id`, `business_id`, `workspace_id`, `run_id`, `execution_id` | Run/Execution must have the same scope; same-conversation mutual exclusion includes waiting |
| Interaction | `kind=approval|input`, Adapter request ID, nullable `approval_id`, bounded request and JSON Schema | Only one active wait per Execution/Adapter request ID; no Secret input is stored |
| Decision | `status=pending|resolved|expired|cancelled`, `revision`, decision type, request/decision hashes, idempotency key | Conditional updates prevent concurrency errors; identical retry returns the original result and a different decision conflicts |
| Time | `expires_at`, created/decision timestamps | Expired waits or terminal Runs cannot resume; recovery requires fresh admission and authorization |

Approval state remains owned by `approval_requests`; this table links it to Execution wait state. Approval decision, wait closure, Run waiting→queued, and Outbox writes share one database transaction, preventing “approved but not resumed” and duplicate recovery.

### Planned Model `engine_usage_records` (S7-06)

| Field group | Content | Invariant |
|---|---|---|
| Correlation | `id`, tenant scope, Run/Execution/internal attempt, Engine/Protocol/Adapter identity | All correlations come from server context; clients cannot rewrite tenant or Execution |
| Idempotency and source | `source`, `adapter_event_id`, `metric_version`, `usage_kind`, `aggregation_mode` | Tenant + Execution + Adapter identity + event ID + metric version is unique, preventing local event-ID collisions across Executions; duplicate reports do not double count |
| Quantities | Allowlisted `quantities`, units, occurred/received timestamps | Accept only nonnegative finite numbers; quarantine unknown units and exclude them from totals |
| Cost | Nullable `amount`, `currency`, `cost_status=known|unknown|not_applicable`, pricing snapshot | Missing cost is not 0; no cross-currency sum without exchange rates; every amount is labelled estimated |

The model gateway remains authoritative through `gateway_calls/attempts/costs`. Unified reports use a source view: gateway model calls come only from gateway facts; Engine `informational` records are display-only and only `additive` records enter Engine totals. Any Engine aggregate containing model usage already charged by the gateway must be informational or split into nonoverlapping increments.

### Planned Model `runtime_tenant_fairness` (S7-07)

| Field | Content | Invariant |
|---|---|---|
| `tenant_id` | Fair-scheduling subject | Do not disclose business/workspace identifiers to other tenants |
| `last_served_at`, `last_run_id` | Fairness cursor for the latest successful claim | Update only in the same transaction as selected queued→running |
| `revision`, `updated_at` | Concurrency and audit information | Never rely on a process-local cursor across Workers |

Quota decisions use valid Run states inside short transactions, not potentially drifting process counters. waiting and running are counted separately; global/tenant queued and running each have hard limits. Compatibility mapping for existing `queue_capacity`/`tenant_capacity` must be frozen in S7-07 design review without silently changing flag-off behavior.

### Planned Skill and Artifact Models (S7-08)

| Model | Key fields | Invariant |
|---|---|---|
| `agent_skills` | ID, `scope_type=tenant|platform`, owner scope, name, source, permissions, status | Only trusted publication creates platform-shared entries; tenants can read only authorized shared entries |
| `agent_skill_versions` | Skill ID, version, content/object reference, SHA-256, format version, created time | Published versions are immutable; execution snapshots pin version/hash and mounts are read-only |
| `execution_artifacts` | ID, tenant scope, Run/Execution, internal object key, MIME, size, SHA-256, retention deadline, scan status | Object keys are not public; downloads reauthorize; expiry/scan rejection blocks according to policy |

Object content stays out of ordinary events and large relational fields. The Artifact Store uses an independent port over a controlled local volume or S3-compatible object storage. Streaming for large files, size limits, and cleanup-failure metrics are launch gates.

### Planned Runtime Profile Models (S7-09)

| Model | Key fields | Invariant |
|---|---|---|
| `runtime_profiles` | ID, tenant/platform scope, name, current published version, status | Only allowed scopes may reference it; manual disabled overrides health recovery |
| `runtime_profile_versions` | Profile ID, version, Engine/Protocol/Adapter, resource/timeout/egress/Secret references, probe policy | Published versions are immutable; arbitrary client commands, host paths, and plaintext Secrets are rejected |
| `runtime_profile_health` | Profile ID/version, Adapter, health state, circuit state, consecutive counts, last success/failure, open deadline, revision | State updates use atomic revision/locking; stale data is unhealthy; half-open probe count is bounded |

## Core Flows

### 1. Adapter Registration and Contract Verification (S7-01)

Trusted composition root registers metadata → Registry validates Engine/Protocol/version compatibility and configuration Schema → Declared capabilities are read → the same parameterized contract runs against LocalTestAdapter and the candidate Adapter → only eligible versions become resolvable. At runtime the Orchestrator depends only on the common Adapter port; Worker does not import vendor packages.

Optional health checks use a separate operations port rather than vendor fields in the common ExecutionRequest. An Adapter without optional advanced ports can still perform basic tasks after passing the basic contract.

### 2. Routing, Effective Capabilities, and Safe Fallback (S7-02)

1. Generate a RoutePlan from the published Agent and tenant policy; ignore unauthorized client candidates.
2. For every candidate, reload version, health, Workspace/credential scope and compute `Effective = Declared ∩ Available ∩ Policy`.
3. If required capabilities are absent, record the reason and evaluate the next candidate; if none qualifies, fail before startup.
4. After startup, the Phase 6 side-effect ledger tracks streamed output, tools/commands, Session, approvals, Artifacts, and external writes.
5. Select another attempt only when the error is retryable, side-effect count is zero, no output or Session mutation occurred, and outcome is not unknown. Each attempt has its own ID, sequence, and immutable snapshot; Repository alone commits Run terminal state.

Basic degradation removes optional experience only; it never relaxes required capabilities, sandbox, network, or authorization. Health changes Available only and cannot grant Policy permission.

### 3. Session Resume (S7-03)

API authentication and scope validation → lock-read Session and idempotency record → validate active/unexpired state and conversation, Workspace, Engine tuple bindings → load current published Agent, credential references, Runtime Profile, and policy → recompute Effective → create a new Run linked to the same native Session → Orchestrator invokes Adapter Resume after commit.

The same idempotency key/body returns the original Run; a different body conflicts. Failed authorization, changed bindings, or unsupported Session creates no queued record and never switches Engines automatically. A separate maintenance task expires Sessions and records reasons.

### 4. Approval/Input Waiting and Recovery (S7-04)

Engine emits a bounded request → Orchestrator validates Effective and Schema → one transaction creates the wait, marks Run waiting, and writes event/Outbox → Worker finishes this execution and releases Lease/running quota → operator decides through a revisioned API → approval port and wait repository validate actor/separation of duties/expiry/idempotency in one transaction → reauthorize and readmit quota → Run becomes queued → Worker resumes from durable wait context.

The Adapter must resume from a checkpoint/protocol cursor rather than blindly replaying side-effecting nodes. An Engine that cannot safely pause/resume must not declare the capability; keeping a running execution blocked is outside this slice's contract. Cancellation and late decisions are rejected by both Run terminal state and waiting revision.

### 5. Dynamic Model Selection (S7-05)

AgentConfig gains optional typed `model_selection`: ordered rules, allowed Profile references, and pinned-version constraints. Fixed `model_profile_id/version` retains its original path. The selector filters tenant-available, enabled, operation-compatible, tool-compatible, input-limit-compatible, pinned Profiles → selects the first matching rule → writes Profile ID/version, rule ID, reason, and catalog version into the Execution snapshot → existing `GatewayChatModel` uses that fixed snapshot.

Gateway `fallback_model_ids` remains model routing inside the published Profile and cannot bypass that Profile's existing tenant/key constraints. Dynamic-selection failure does not silently return to the legacy fixed Profile unless typed Agent policy explicitly declares that fallback and the fixed entry is also eligible.

### 6. Usage and Cost (S7-06)

Adapter usage event → validate common envelope and event ID → normalize allowlisted numbers, units, source, and aggregation_mode → idempotent write → Phase 6 Outbox/retry provides recovery → reports separately read gateway facts and Engine additive records.

A write failure does not revoke a completed business result, but must leave a retryable task, metric, and alert. Report responses include at least `coverage`, `unknown_cost_records`, `currency`, and source filters. Totals never combine informational, unknown, or different currencies into one amount. Cost APIs retain the existing “estimated” semantics and do not issue supplier invoices.

### 7. Global Quotas and Fair Claim (S7-07)

Submission: short transaction takes the fixed quota-coordination lock → count valid global/tenant queued and running → reject with 429 if any cell is full → insert queued. Wait recovery uses the same admission and cannot bypass the queue.

Claim: reap expired records first → coordinate global running in a short transaction → take each tenant's oldest runnable queued candidate → select by never-served first, oldest last_served, then candidate created_at/ID tie-break → conditionally update the selected row and verify global/tenant running → update fairness cursor and event in the same transaction. Lock order is quota-coordination lock, fairness row, Run row; actual SQL and EXPLAIN require implementation review.

finish/cancel/reap release capacity through state changes rather than Worker-local counters. Coordination-query failure fails closed; availability never justifies skipping limits. Waiting counts are separately bounded and included in storage-capacity monitoring.

### 8. Skills and Artifacts (S7-08)

Skill: trusted publisher uploads → compute hash and validate source/permissions/size → publish immutable version → Agent references ID/version/hash in its published snapshot → Workspace Provider creates the execution directory → Engine Skill Adapter converts to that Engine's read-only layout → recheck mount hash/path before startup. Any symlink/path escape or tampering fails closed.

Artifact: Engine writes through controlled Workspace → Artifact Store streams to independent object storage → compute size/hash and write metadata → perform policy-driven Secret scan and emit `artifact.created` → download API rechecks tenant/Workspace/retention/scan state before controlled content or short-lived authorization → expiry task deletes objects and retains necessary audit. Failed object deletion retries and alerts; metadata is not marked cleaned prematurely.

### 9. Runtime Profile Health and Circuit Breaking (S7-09)

Publish immutable Profile → routing resolves the version and pins resource, egress, Adapter, and Secret references → active side-effect-free probes or passive startup results update timestamped health → consecutive failures in closed reach threshold and open with open_until → open candidates are excluded from Available → bounded global half_open probes run after cooldown → enough successes close the circuit and failure reopens it.

Probes carry no tenant input, execute no business tools, and write no Workspace Artifacts. Manual disabled cannot be overridden by probes; stale/unknown health is unavailable. If no healthy candidate remains, S7-02 may select another authorized candidate before side effects, otherwise it returns explicit unavailability rather than hiding the failure behind indefinite queued Runs.

## Configuration

`backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` is planned to add FR-11's nine Boolean flags, all default `false`, with automatic `AGENT_` environment prefixes. Each slice adds only its own bounded numeric settings. Defaults below are review contracts, not current settings.

| Configuration | Default/enablement condition | Purpose |
|---|---|---|
| `phase7_session_ttl_seconds` | `86400`; S7-03 review may tighten | Default expiry ceiling for new Sessions; never extends an expired Session |
| `phase7_interaction_ttl_seconds` | `3600`; S7-04 review may tighten | Expiry ceiling for approval/input waits |
| `phase7_tenant_waiting_limit` | `100`; joint S7-04/S7-07 review | Bounds durable waits per tenant |
| `phase7_artifact_max_bytes` | `104857600`; S7-08 review adjusts to storage capacity | Hard per-Artifact limit with streamed validation |
| `phase7_artifact_retention_days` | `7`; S7-08 review adjusts to compliance | Default retention that cannot override stricter tenant policy |
| `phase7_health_failure_threshold` | `3`; S7-09 review | Consecutive failures for closed→open |
| `phase7_health_open_seconds` | `30`; S7-09 review | Open cooldown duration |
| `phase7_health_stale_seconds` | `60`; S7-09 review | Maximum age of a usable health result |
| `phase7_health_half_open_probes` | `1`; S7-09 review | Global concurrent half-open probe limit |

Before S7-07 is enabled, explicitly freeze global/tenant queued, running, and waiting limits and their mapping to existing `queue_capacity`, `tenant_capacity`, and `worker_concurrency`; default-value review is not a substitute for capacity review. Object-storage and Credential Broker Secrets come only from untracked environment files, with placeholders only in `.env.example`.

## Model Invocation Path (LLM-Related)

Legacy configuration: published Agent snapshot pins `model_profile_id/version` → React Provider → `GatewayChatModel` → Catalog resolves the same version → existing in-Profile model routing/fallback → `gateway_calls/attempts/costs` records usage/cost.

With S7-05 enabled and dynamic policy configured, select a pinned Profile snapshot from the allowlist before execution, then follow exactly the same gateway path. Do not bypass Gateway Governance, credentials, tool-capability checks, or version resolution. Native model calls from non-React Engines are reported through the Adapter usage contract and marked for overlap with gateway records.

Model fallback and Engine fallback do not share retryability conclusions. The former retains gateway rules for model errors before streamed output; the latter additionally requires Execution side-effect and policy conditions.

## Test Plan Summary

| Layer | Cases |
|---|---|
| Unit | P7-UT-01~30: registration/compatibility, routing/side effects, Effective, Sessions, waits, models, usage/cost, quota/fairness, Skills/Artifacts, health, and flags |
| Integration | P7-IT-01~30: common Adapter contracts, PostgreSQL multi-Worker, Worker restart, approval recovery, real gateway snapshots, object storage, circuit breaking, and all-off regression |
| Common | P7-CM-01~12: migration head/online behavior, configuration, i18n, tenancy, Secrets, dependency boundaries, observability, performance evidence, and slice release gates |
| Regression | Existing `test_runtime_engine.py`, `test_runtime_postgres.py`, `test_runtime_scope.py`, `test_runtime_availability.py`, model-gateway/approval/Workspace/migration suites, and Phase 0~6 regressions |

See `04-test-plan.en.md` for detailed steps, expectations, and traceability. Execute applicable cases for the reviewed slice only, but record every case result explicitly; unimplemented or unexecuted is not “passed.” Without the Phase 0 baseline, comparative metrics and the all-off diff gate cannot pass.

## Rollout and Rollback

- **Review per slice**: Each S7-01~09 submission states scope/non-goals, dependency evidence, files, migration if any, contract/integration tests, security review, canary tenant, monitoring thresholds, and rollback rehearsal. The unified documents are not blanket launch approval.
- **Small-PR order**: Establish Phase 0~6 dependencies first, then select a slice. Expand-only migrations and compatible code may merge with flags off. Never combine multiple vendor Adapters, core scheduling rewrites, and all persistence models in one PR.
- **Canary**: Start with a dedicated test tenant/LocalTestAdapter, then a controlled tenant. Any separately approved real vendor integration must pass the same common contract and cannot substitute for platform basic acceptance.
- **Rollback**: Disable the relevant flag to stop new work. In-flight basic Runs finish under Phase 0~6 terminal rules; Sessions/waits do not automatically resume; Artifacts/usage retain authorized reads and cleanup. Rolled-back code must still read new tables/states; never use destructive down migrations for rollback.
- **Re-enablement**: Recheck current policy, Session/wait expiry, health freshness, quotas, and backlog. Never treat an old authorization snapshot from the disabled period as currently valid.
- **Definition of done**: Launching one slice means only its applicable A/C checks passed. Do not claim Phase 7 complete until every slice approved for the final scope has an independent acceptance report and relevant architecture §22 items have evidence.
