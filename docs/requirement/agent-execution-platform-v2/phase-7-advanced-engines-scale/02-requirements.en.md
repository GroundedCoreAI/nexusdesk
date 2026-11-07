# Phase 7 · Advanced Engine Capabilities and Scale — Requirements

> Status: Deferred (early-stage project; FR/AC remain deferred requirement contracts and are not entering implementation, testing, or acceptance)
> Deferral decision: 2026-11-07; FR-1~FR-11 are tracked as lowest-priority P4 issues under “Deferral and Requirement Tracking” below
> Created: 2026-11-02
> Basis: `01-business-goals.en.md` (G1~G11), architecture §17 Phase 7, §18 continuous backlog, §19 quality gates, and §22 architecture acceptance; current-code findings are in `03-technical-design.en.md`
> Baseline statement: Current performance and behavioral baselines are unmeasured pending Phase 0; targets here are not current test results

## Deferral and Requirement Tracking

Because NexusDesk is in its early stage, all Phase 7 requirements are deferred as of 2026-11-07 and assigned the lowest priority, P4. These issues preserve the requirements for future scheduling only. Until the phase is explicitly reactivated, no implementation, testing, or acceptance will start, and nothing here represents delivered functionality.

| Requirement | Topic | Slice | P4 issue |
|---|---|---|---|
| FR-1 | Adapter ecosystem and common contracts | S7-01 | [#110](https://github.com/GroundedCoreAI/nexusdesk/issues/110) |
| FR-2 | Policy routing and safe fallback | S7-02 | [#111](https://github.com/GroundedCoreAI/nexusdesk/issues/111) |
| FR-3 | Effective capabilities and basic-execution degradation | S7-02 | [#112](https://github.com/GroundedCoreAI/nexusdesk/issues/112) |
| FR-4 | Engine Session Resume and reauthorization | S7-03 | [#113](https://github.com/GroundedCoreAI/nexusdesk/issues/113) |
| FR-5 | Human approval, interactive input, and durable waiting | S7-04 | [#114](https://github.com/GroundedCoreAI/nexusdesk/issues/114) |
| FR-6 | Dynamic model selection | S7-05 | [#115](https://github.com/GroundedCoreAI/nexusdesk/issues/115) |
| FR-7 | Unified Engine usage and cost | S7-06 | [#116](https://github.com/GroundedCoreAI/nexusdesk/issues/116) |
| FR-8 | Tenant fairness and global quotas | S7-07 | [#117](https://github.com/GroundedCoreAI/nexusdesk/issues/117) |
| FR-9 | Skills and Artifacts | S7-08 | [#118](https://github.com/GroundedCoreAI/nexusdesk/issues/118) |
| FR-10 | Runtime Profiles, health checks, and circuit breaking | S7-09 | [#119](https://github.com/GroundedCoreAI/nexusdesk/issues/119) |
| FR-11 | Configuration flags and slice-by-slice release | S7-01~S7-09 | [#120](https://github.com/GroundedCoreAI/nexusdesk/issues/120) |

## User Stories

**US-1 (Engine contributor)**: As an Engine contributor, I want to integrate through a versioned Adapter and common contract tests so that I need neither Worker-core changes nor vendor distortions of the common protocol.

**US-2 (Platform operator)**: As a platform operator, I want routed fallback to preserve tenant policy and side-effect boundaries so that availability improves without privilege amplification or duplicate execution.

**US-3 (Business user)**: As a business user, I want an Engine without advanced capabilities to complete basic tasks so that missing Session, approval, or native-event support does not make it wholly unusable.

**US-4 (Conversation operator)**: As a conversation operator, I want to resume a bound Engine Session for which authorization still holds so that I retain context without inheriting revoked permissions.

**US-5 (Human reviewer)**: As a human reviewer, I want to approve or provide validated input while execution is suspended so that long tasks resume safely without repeated side effects.

**US-6 (Agent administrator)**: As an Agent administrator, I want deterministic selection from allowed model Profiles with a recorded reason so that task needs, cost, and auditability can be balanced.

**US-7 (Finance and operations user)**: As a finance and operations user, I want unified usage and estimated cost by Run, Engine, model, and tenant so that I can analyze spend without double counting or treating unknown as zero.

**US-8 (SRE)**: As an SRE, I want global quotas and fair scheduling to apply across Workers so that one large tenant cannot exhaust platform capacity or starve other tenants.

**US-9 (Workspace administrator)**: As a Workspace administrator, I want shared read-only, versioned, hashed Skills and securely retained/downloadable Artifacts so that reuse does not leak cross-tenant data.

**US-10 (Runtime operator)**: As a Runtime operator, I want versioned Runtime Profiles with health checks and circuit breaking so that failures are isolated, recovery is controlled, and basic execution remains available.

**US-11 (Release owner)**: As a release owner, I want each capability slice to have an independent default-off flag and rollback evidence so that I can review, canary, and withdraw slices without a Big Bang.

## Functional Requirements

### FR-1 Adapter Ecosystem and Common Contracts

| Item | Description |
|---|---|
| Trigger | Registering, upgrading, or contract-testing an Engine/Protocol/Adapter combination. |
| Input | Trusted Adapter implementation, `(engine_id, protocol_id, adapter_version)`, declared capabilities, protocol compatibility range, configuration Schema, and contract-test results. |
| Output | Resolvable versioned registration, Declared capabilities, compatibility matrix, and rejection reasons; a deterministic LocalTestAdapter for tests. |
| Execution mode | Registration is explicit in the composition root; runtime resolution is synchronous, while external Engine calls are asynchronous and do not block the Worker scheduling loop. |
| Failure handling | Unknown, incompatible, invalidly configured, or contract-failing Adapters receive no business execution. Errors use stable codes and do not leak sensitive raw vendor errors. |

The contract covers start, streamed events, result collection, cancellation, timeout, Engine unavailable, invalid configuration, protocol errors, duplicate/late events, and usage collection. An Adapter must not operate the queue, decide tenant authorization, commit platform Run terminal state, or bypass Runtime Host. A new Protocol must not force vendor-specific fields into the common Engine contract. Vendor names are examples only, not this FR's delivery list.

### FR-2 Policy Routing and Safe Fallback

| Item | Description |
|---|---|
| Trigger | Creating an Execution, selecting a candidate, or encountering a classified failure early in startup. |
| Input | Platform-generated ordered RoutePlan, published Agent configuration, tenant allowlists, candidate health, required capabilities, Workspace/credential policy, and current side-effect marker. |
| Output | Selected Adapter, immutable route/policy snapshot, and `execution.route_selected` / `execution.fallback` audit events. |
| Execution mode | The orchestrator decides synchronously per candidate and starts asynchronously. One Run may record ordered internal attempts without introducing first-class Task dual tables. |
| Failure handling | Only EngineUnavailable, pre-start ProtocolError, or a policy-approved startup timeout with no visible output may select the next candidate; other errors terminate or await human handling. |

Every candidate must recompute Declared ∩ Available ∩ Policy and revalidate tenant, Agent, Workspace, credential, quota, and Engine/Protocol authorization. Clients cannot inject arbitrary candidates. Automatic fallback is forbidden after streamed output, tools/commands, approval, Artifacts, Session mutation, or other external side effects; timeout or unknown outcome forbids fallback by default.

### FR-3 Effective Capabilities and Basic-Execution Degradation

| Item | Description |
|---|---|
| Trigger | Route selection, Resume, wait recovery, or UI query of task-available functions. |
| Input | Adapter Declared, deployment/health Available, tenant and Agent Policy, slice flags, and request-required capabilities. |
| Output | Server-computed Effective capabilities with unsupported reasons, persisted in the execution snapshot; UI consumes only this projection. |
| Execution mode | Resolve synchronously before execution. Capability or policy changes cannot widen an already snapshotted Execution; recovery must resolve again. |
| Failure handling | Set unavailable optional advanced capabilities to false while retaining basic execution. Missing required capabilities return `capability_unavailable` before startup with no side effects. |

Basic execution consists of start, streaming where supported, collect_result, and cancellation where supported. Without streaming, returning only the terminal result is allowed. Missing Session/approval/interaction/native events must not be simulated as successful. Unavailable usage is explicitly unknown; UI hides or disables affected operations with an i18n reason.

### FR-4 Engine Session Resume and Reauthorization

| Item | Description |
|---|---|
| Trigger | Creating, updating, or expiring a Session, or when an operator starts a new Run through planned API `POST /engine-sessions/{session_id}/resume`. |
| Input | Platform Session ID, trusted tenant/business/Workspace context, current conversation and Agent, idempotency key, new input, and current authorization context. |
| Output | New Run/Execution, Session binding snapshot, and `engine.session.resumed` event; no host-process details or native credentials. |
| Execution mode | Authorization and snapshot complete synchronously; Engine resume executes asynchronously. The same idempotency key and body create only one Run. |
| Failure handling | Missing, expired, terminal, cross-tenant, conversation/Workspace/Engine-binding-changed, or policy-incompatible Sessions fail closed; never switch Engines to continue a native Session. |

Resume must reload the currently published Agent, tenant policy, valid credential references, Runtime Profile, and Effective capabilities. Old policy snapshots are for audit only and cannot restore revoked permissions. Adapter-versioned code interprets native metadata; the platform does not rewrite it arbitrarily. An Adapter without Resume returns explicit unsupported rather than simulating a persistent Session.

### FR-5 Human Approval, Interactive Input, and Durable Waiting

| Item | Description |
|---|---|
| Trigger | Effective capabilities allow and the Engine/orchestrator requests approval or structured input; an operator decides, cancels, or the wait expires. |
| Input | Execution/Run, interaction type, size/Schema-bounded request, expiry, reviewer authorization, revision, and idempotent decision. |
| Output | waiting Run, pending interaction, `approval.required`/`approval.resolved` or `input.required`/`input.resolved` events, and one controlled recovery. |
| Execution mode | Persist the wait and Run state in one transaction, then release running Lease/quota. After a decision, reauthorize and transition to queued for asynchronous Worker recovery. |
| Failure handling | Self-approval, unauthorized actor, revision conflict, a different duplicate decision, Schema mismatch, cancellation, or expiry must not resume. Repeating the identical request returns its original result without another side effect. |

Approval reuses the existing `ApprovalService` tenant isolation, separation of duties, revision, and audit through a platform port linked to the Execution; it does not duplicate the approval state machine. Interactive input accepts only declared non-Secret structured types. Secrets must use credential references and cannot enter ordinary events. waiting is a new public state; the existing five states and SSE terminal semantics remain compatible, and same-conversation mutual exclusion includes waiting.

### FR-6 Dynamic Model Selection

| Item | Description |
|---|---|
| Trigger | A React Execution supporting dynamic selection resolves its model before startup. |
| Input | Agent versioned selection policy, allowed Profile IDs/version constraints, operation type, tool/input constraints, tenant gateway authorization, and available model catalog. |
| Output | One model Profile ID, immutable version, selection rule/reason, and actual model-call correlation; fixed Profile remains in use when no policy exists. |
| Execution mode | Deterministic rule selection and snapshot before startup. Selection policy does not change within an Execution; gateway model-route fallback follows its existing contract. |
| Failure handling | No eligible Profile, unpinned version, incompatible operation/tools, or unauthorized access fails before startup; never select outside the allowlist to improve success rate. |

Dynamic model selection and Engine fallback are separate decisions, each independently authorized and audited. A non-React Engine participates only if it declares and adapts the capability; do not assume every Engine uses the platform model gateway. Selection uses bounded rules, not arbitrary client Profile IDs or unreviewed automatic learning.

### FR-7 Unified Engine Usage and Cost

| Item | Description |
|---|---|
| Trigger | An Adapter reports incremental/aggregate usage, a gateway model call completes, an Execution finishes, or a report is queried. |
| Input | Usage with Adapter event ID, source, metric version, numeric units, Execution/Run correlation, pricing snapshot, and currency. |
| Output | Idempotent usage records and reports grouped by tenant/time/Run/Engine/Protocol/Adapter/model; an Execution may emit `usage.updated`. |
| Execution mode | Usage persistence is idempotent and decoupled from main execution; reports aggregate read-only. Missing usage does not block an already completed basic result. |
| Failure handling | Reject/quarantine nonnumeric, negative, nonfinite, or unknown units. Mark incalculable cost unknown, record and alert on persistence failures, and never fabricate zero. |

Reuse existing `gateway_calls`, `gateway_attempts`, and `gateway_costs`; do not copy model charges into a second total. Each Engine record declares `aggregation_mode=additive|informational`. Only additive records enter totals, and Engine aggregates overlapping gateway calls must be informational. Report currencies separately, label all charges as estimates rather than invoices, and retain unknown-record counts.

### FR-8 Tenant Fairness and Global Quotas

| Item | Description |
|---|---|
| Trigger | Run submission, Worker claim/finish/cancel/reap, waiting, and recovery. |
| Input | Global/tenant queued and running limits, current valid execution records, tenant fairness cursor, and trusted tenant scope. |
| Output | Atomic admission or stable 429, cross-Worker-consistent claim ordering, quota events, and observable counters. |
| Execution mode | Retain the PostgreSQL durable queue, `FOR UPDATE SKIP LOCKED`, and Lease/Heartbeat; use short transactions and database coordination for cross-process limits and starvation-resistant selection. |
| Failure handling | Return `execution_quota_exceeded` with bounded Retry-After when full. Database coordination failures fail closed rather than admitting through approximate process-local counters. |

waiting consumes no running quota and is not immediately claimable as queued; recovery requires fresh admission. Bound waiting counts separately to prevent unlimited storage consumption. Scheduling guarantees only the fairness and global limits defined here, not task priorities or hard real-time SLAs.

### FR-9 Skills and Artifacts

| Item | Description |
|---|---|
| Trigger | Publishing/referencing a Skill, preparing an Execution Workdir, collecting an Artifact, downloading, or retention cleanup. |
| Input | Tenant/shared scope, Skill version/source/permissions/content hash, Engine adapter type, Artifact content/size/MIME/retention policy, and authorization context. |
| Output | Read-only Skill mount and snapshot, `artifact.created` event, Artifact metadata, and authorized download; no host paths exposed to clients. |
| Execution mode | Validate and pin Skills before startup. Write Artifacts asynchronously through Workspace/Object Store ports with verifiable metadata and content hashes. |
| Failure handling | Reject hash/source/permission mismatch, path or symlink escape, size overflow, cross-tenant access, and expired retention. Never mount untrusted content after failure. |

Shared Skills are read-only, and the platform format is not tied to a vendor directory. Engine Skill Adapters perform deterministic conversion. Artifacts use separate execution-storage configuration and authorized downloads, do not reuse knowledge-base keys as default credentials, and have no permanent anonymous URLs. Large objects, Secret scanning, and cleanup failures are observable.

### FR-10 Runtime Profiles, Health Checks, and Circuit Breaking

| Item | Description |
|---|---|
| Trigger | Publishing/resolving a Runtime Profile, routing an execution, scheduled health probes, consecutive failures/successes, or manual disablement. |
| Input | Versioned Engine/Protocol/Adapter binding, resource/timeout/egress/Secret references, tenant allowlist, health-probe configuration, and timestamped results. |
| Output | Immutable Profile snapshot, Available state, closed/open/half_open circuit state, audit events, and alerts. |
| Execution mode | Side-effect-free probes run asynchronously with timeouts. Routing reads the latest valid state; half_open permits only bounded probe executions. |
| Failure handling | Reject invalid configuration at publish. Stale or unknown health is not healthy. While open, skip the candidate or return explicit unavailability rather than queueing indefinitely. |

Health participates only in Available and cannot increase Policy/Effective permissions. Manual disabled overrides automatic recovery. A circuit key includes at least Runtime Profile ID/version and Adapter identity. Multiple Workers require consistent state or a demonstrated equivalent; process-local counters cannot masquerade as global health.

### FR-11 Configuration Flags and Slice-by-Slice Release

| Configuration | Level | Default | Description |
|---|---|---|---|
| `phase7_adapter_sdk_enabled` | Global settings | `false` | Enables only S7-01 Adapter SDK/test entry points; no vendor Adapter is enabled automatically. |
| `phase7_safe_routing_enabled` | Global settings | `false` | Enables S7-02 routing, fallback, and Effective capability enhancements. |
| `phase7_session_resume_enabled` | Global settings | `false` | Enables S7-03 Session Resume; no resume execution is created while off. |
| `phase7_human_interaction_enabled` | Global settings | `false` | Enables S7-04 durable waiting, approval, and input recovery. |
| `phase7_dynamic_model_enabled` | Global settings | `false` | Enables S7-05; fixed Profile remains when no Agent policy exists. |
| `phase7_engine_usage_enabled` | Global settings | `false` | Enables S7-06 Engine usage collection; existing gateway records are not backfilled with fabricated data. |
| `phase7_fair_scheduling_enabled` | Global settings | `false` | Enables the S7-07 fair/global-quota path. |
| `phase7_skill_artifact_enabled` | Global settings | `false` | Enables S7-08 Skill mounts and execution Artifact services. |
| `phase7_runtime_profile_enabled` | Global settings | `false` | Enables S7-09 Profiles and health/circuit-aware routing. |

Environment variables retain the `AGENT_` prefix. Flags independently limit blast radius but do not bypass slice dependencies; configuration validation must reject enablement when dependencies are absent. Persisted Sessions, waits, usage, Artifacts, and health history remain readable/cleanable under authorization while their flag is off, but cannot continue through the new execution path. Rollback must not depend on a down migration.

## Non-Functional Requirements

- **Performance**: Phase 0 measures current execution and database baselines first. New routing/capability resolution excluding external I/O targets ≤50 ms added P95 overhead; reports target P95 ≤2 s at an agreed 30-day data volume; quota stress must not exceed global/tenant hard limits. Numbers without environment and sample evidence are not acceptance results.
- **Compatibility**: Legacy Agent configuration defaults to ReAct/fixed Profile. Existing Run states, event cursors, and terminal semantics remain unchanged. New fields are nullable or have compatible defaults; waiting and new events require coordinated API/SDK/UI changes. All-flags-off behavioral diff against Phase 0 is zero.
- **Multi-tenancy**: Every Session, interaction, usage, Skill/Artifact, Profile binding, and scheduling operation uses trusted tenant/business/workspace scope. Cross-tenant identifiers are not enumerable; 404/403 behavior is consistent and does not leak existence.
- **Security**: Fallback, Resume, recovery, and dynamic selection reauthorize and may only narrow permissions. Untrusted code launch requires accepted sandbox, Workspace, network, resource, and credential isolation. Ordinary events, logs, audits, and reports contain no Secrets.
- **Reliability**: Run terminal state, Lease/Heartbeat, event cursors, and idempotency constraints remain authoritative. Waiting/recovery, duplicate events, late results, Worker restart, and process crash have contract tests. No automatic retry may repeat an unknown side effect.
- **Observability**: Audit includes actor, tenant scope, run/execution, route/profile/policy versions, and stable reason codes, but no input body or credentials. Critical failures, quota denials, circuit transitions, and unknown usage/cost have metrics and alerts.
- **UI/i18n**: UI shows server Effective capabilities, waiting/health/unknown states, and reasons. All user-visible text uses i18n; technical Declared capability is never presented as authorized capability.
- **Delivery**: Each slice uses small PRs limited to necessary modules and retains applicable lint/typecheck/contract/migration/integration/security gates. Unimplemented vendor Adapters cannot substitute for unified-contract acceptance.

## Acceptance Criteria

| # | Scenario | Expected result | Trace |
|---|---|---|---|
| AC-1 | Register a new Engine/Protocol combination with LocalTestAdapter and run the common contract | Start, streaming, result, cancellation, timeout, errors, duplicate/late events, and usage all pass; no Worker-core change or vendor field in the common contract | G1/US-1/FR-1 |
| AC-2 | Register an unknown combination, incompatible version, invalid configuration, and capability-overclaiming Adapter | Each is rejected before business execution with a stable reason; none enters routing or touches tenant data | G1/US-1/FR-1 |
| AC-3 | The preferred candidate returns retryable EngineUnavailable before any output/side effect; the second candidate is authorized and compatible | Exactly one ordered subsequent attempt is created, both policy/capability checks and the fallback reason are recorded, and the Run has one final semantic outcome | G2/US-2/FR-2 |
| AC-4 | Attempt fallback to an unauthorized candidate and separately after output, a tool, approval, Artifact, or unknown timeout | Unauthorized candidates are rejected. No automatic fallback occurs after side effects or unknown outcome; no duplicate execution occurs and events explain why | G2/US-2/FR-2 |
| AC-5 | An Adapter lacks Session, approval, interaction, and streaming but supports basic execution; none is required | Effective entries are false and a basic result completes. UI shows no simulated controls and missing usage is unknown | G3/US-3/FR-3 |
| AC-6 | A request explicitly requires terminal, Resume, or another capability absent from Effective | Return `capability_unavailable` before startup; do not start the Engine, silently weaken security, or persist side effects | G3/US-3/FR-3 |
| AC-7 | Resume a valid Session under the same tenant/conversation/Workspace and compatible policy, then retry with the same idempotency key | Reauthorization creates exactly one new Run, retains the native Session, pins a new execution snapshot, and correlates events | G4/US-4/FR-4 |
| AC-8 | Resume after expiry, revocation, Agent/Workspace/Engine binding change, or from another tenant | All cases fail closed with no Run, Engine switch, or reuse of old authorization; audit contains no native Secret | G4/US-4/FR-4 |
| AC-9 | An Engine requests human approval and another eligible reviewer approves while concurrent duplicate approval, self-approval, and Worker restart occur | Run enters waiting and releases running resources. Only one valid approval causes one reauthorized recovery; self-approval/duplicate conflicts do not alter the result or repeat side effects | G5/US-5/FR-5 |
| AC-10 | An Engine requests structured input; submit valid input, wrong Schema, unauthorized input, expired input, and cancellation | Only valid unexpired input resumes once. Other cases do not resume, and events/audit contain no Secret or unauthorized content | G5/US-5/FR-5 |
| AC-11 | An Agent has a bounded dynamic-model policy while a legacy Agent has no policy | The new Agent selects an allowed pinned version and records a reason; the legacy Agent's Profile/version and gateway behavior match Phase 0 | G6/US-6/FR-6 |
| AC-12 | The preferred model lacks required tools, is unauthorized, or has no pinned version, while another eligible model exists | Evaluate only authorized candidates and select an eligible one; fail before startup if none exists, without unauthorized fallback | G6/US-6/FR-6 |
| AC-13 | Report the same Adapter event twice, with Engine aggregate usage overlapping gateway model calls | Idempotent deduplication occurs; additive and informational data are distinguished; totals do not double count and source/Run/Execution links remain complete | G7/US-7/FR-7 |
| AC-14 | Usage lacks pricing, contains two currencies, and a cross-tenant report query is attempted | Unknown cost stays unknown rather than 0; currencies remain separate without direct summation; no cross-tenant data leaks | G7/US-7/FR-7 |
| AC-15 | Multiple API/Worker processes concurrently submit and claim as global and tenant queued/running approach limits | Atomic admission exceeds no hard limit; 429 semantics are stable; finish/cancel/reap release capacity according to the contract | G8/US-8/FR-8 |
| AC-16 | A busy tenant submits continuously, a light tenant submits intermittently, and waiting Runs exist | The light tenant progresses in every batch and meets the agreed P95 target; waiting consumes no running quota and recovery readmits | G8/US-8/FR-8 |
| AC-17 | Publish a shared Skill, then tamper with content or reference a cross-tenant/unauthorized version before execution | Valid execution pins version/hash and mounts read-only. Tampering and unauthorized references fail before startup; vendor format does not replace platform format | G9/US-9/FR-9 |
| AC-18 | Create small and large Artifacts, attempt path escape and cross-tenant/expired downloads, then run retention cleanup | Valid content hashes and authorized downloads work; dangerous paths, unauthorized and expired access are denied; cleanup and Secret scanning are auditable | G9/US-9/FR-9 |
| AC-19 | Publish a Runtime Profile with resource/egress/Secret references and inject enough consecutive health failures to reach the threshold | Execution pins the Profile snapshot; circuit moves closed→open; the candidate is skipped or fails explicitly; health never expands permissions | G10/US-10/FR-10 |
| AC-20 | After cooldown, run bounded half-open probes that succeed/fail, make health stale, and manually disable before recovery | half_open transitions and probe counts match the contract; stale data is unhealthy, manual disable wins, and recovery never bypasses route authorization | G10/US-10/FR-10 |
| AC-21 | Enable/disable each of the nine slices independently, then replay Phase 0 regressions with all flags off | Every default is false and dependency validation is explicit. With all off, API, event, model-selection, and terminal-state behavioral diff is zero | G11/US-11/FR-11 |
| AC-22 | Perform design review, migration-head verification, canary, rollback, and evidence review for any one slice | Only that slice's scope is approved. Rollback needs no down migration and historical authorized data remains; unmet gates block production | G11/US-11/FR-11 |
