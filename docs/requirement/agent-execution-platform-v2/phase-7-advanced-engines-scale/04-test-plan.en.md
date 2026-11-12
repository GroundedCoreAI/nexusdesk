# Phase 7 · Advanced Engine Capabilities and Scale — Test Plan

> Status: Deferred (early-stage project; this test plan is not being executed, no cases have run, and none may be recorded as passed)
> Deferral decision: 2026-11-07; see “Deferral and Requirement Tracking” in `02-requirements.en.md` for the FR-1~FR-11 P4 issues; run applicable cases only after the phase is reactivated and the corresponding slice is developed
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence and remove multi-role sign-off requirements; phase remains deferred)
> Basis: `02-requirements.en.md` (FR-1~FR-11, AC-1~AC-22), `03-technical-design.en.md` (S7-01~S7-09, planned migrations, and core flows), architecture §19 and §22
> Baseline statement: Current behavioral, coverage, performance, and capacity baselines are unmeasured pending Phase 0; every comparative test must first cite accepted Phase 0 data

## 1. Test Scope and Principles

**Scope**: S7-01 Adapter contracts, S7-02 routing/degradation, S7-03 Sessions, S7-04 human interaction, S7-05 dynamic models, S7-06 usage/cost, S7-07 fairness/quota, S7-08 Skills/Artifacts, S7-09 Runtime Profile health, and each slice's API/UI/migrations/flags. A real vendor Adapter adds instance tests only when separately approved; it is not a substitute for the unified suite.

**Principles**:

1. **Execute per slice**: Every slice runs its traced cases, all applicable CM items, and affected regressions. Do not pretend unreviewed slices were tested or use one passed slice as Phase 7-wide success.
2. **Flag fallback is mandatory**: All flags default false. With all flags off and after each individual disable, API, event, model-selection, and terminal-state behavioral diff against Phase 0 is zero.
3. **Authorization fails closed**: Routing, Resume, recovery, dynamic models, downloads, and health recovery include revocation, cross-tenant, and binding-change cases. No error may widen Effective permissions.
4. **Side effects come first**: Timeout, disconnection, Worker restart, duplicate/late events, and late results must prove no duplicate external side effect; final success cannot conceal duplicate execution.
5. **Async and multiprocess are mandatory**: waiting releases Lease/quota. Quota/fairness/health tests use at least two API/Worker processes rather than single-process mocks.
6. **No waiting in time-based cases**: Construct Session, interaction, health, and Artifact retention times directly or use a controlled clock; do not use long sleeps for backoff/expiry.
7. **Cost semantics are mandatory**: Assert duplicate events, additive/informational, unknown, multiple currencies, and gateway overlap separately; never classify unknown cost as 0.
8. **Empty states and compatibility are mandatory**: No optional policy, advanced capability, usage, or health data and historical Run/Agent snapshots must remain readable and degradable.
9. **Reuse evidence**: A/C acceptance directly references automated UT/IT/CM results and multiprocess, capacity, reporting, and storage evidence instead of manually repeating the full suite; manual work is limited to key checks that cannot be automated.

## 2. Test Environments and Data Construction

| Environment | Purpose |
|---|---|
| Pure unit tests (controlled clock, fake policy/repositories) | Route classification, Effective capabilities, state machines, model rules, usage/cost, health, and configuration validation |
| PostgreSQL + pytest postgres fixture | Migrations, tenant scope, Run/Session/waiting, idempotency, event cursors, quota, and fairness transactions |
| At least two API/Worker processes | Concurrent submit/claim, global quota, fairness cursor, circuit/half-open coordination, and Worker restart |
| LocalTestAdapter | Deterministic success, failure, streaming, long runs, timeout, cancellation, process failure, duplicate/late events, resource exhaustion, and usage |
| demo/mock models with real model-gateway persistence | Fixed-Profile compatibility, dynamic selection, version snapshots, model fallback, and call-cost correlation |
| Controlled temporary volume or S3-compatible test service | Read-only Skill mounts, large Artifacts, authorized downloads, scan states, and retention cleanup |
| quickstart demo stack | Default-off behavior, deployment configuration, basic ReAct regression, and rollback rehearsal; not proof of production performance |
| Production-like dedicated tenant (per-slice acceptance) | Agreed capacity, P95, report volume, and real-dependency acceptance; no other tenant's business data |

**Data conventions**: Use at least two tenants, two business/workspace scopes, and two Worker owners. Each case creates independent published Agent snapshots, Profile versions, Execution/Run, and policy versions. Construct expired/stale/retention states directly in the database; release concurrent operations with a barrier. Count side effects through fake tool/command ledgers with unique operation IDs. Reuse the same Adapter event ID for duplicates and different hashes for different decisions. Every Secret is a recognizable fake value asserted absent from logs, events, audits, metadata, and reports.

**Test-slice mapping**: S7-01→UT01~03/IT01~05; S7-02→UT04~09/IT06~09; S7-03→UT10~12/IT10~11; S7-04→UT13~15/IT12~14; S7-05→UT16~17/IT15~17; S7-06→UT18~20/IT18~19; S7-07→UT21~23/IT20~22; S7-08→UT24~26/IT23~26; S7-09→UT27~29/IT27~28; release governance (FR-11)→UT30/IT29~30. Execute CM items as applicable.

## 3. Unit Tests

| ID | Case | Expected result | Trace |
|---|---|---|---|
| P7-UT-01 | Versioned Adapter registration and resolution | A valid tuple resolves to the correct implementation with complete metadata/Declared capabilities and no Worker vendor dependency | FR-1/AC-1 |
| P7-UT-02 | Unknown combination, incompatible version, and invalid configuration | All fail before business execution with stable codes and never enter routing | FR-1/AC-2 |
| P7-UT-03 | Declared-capability and contract-result truthfulness | Capabilities without passed advanced contracts cannot be available; basic capabilities pass independently | FR-1/AC-1, AC-2 |
| P7-UT-04 | Declared, Available, and Policy intersection | Effective retains only the intersection with reason/policy version; health adds no permission | FR-3/AC-5 |
| P7-UT-05 | Missing required capabilities and optional degradation | Optional entries become false while basic execution remains; required entries fail before startup with `capability_unavailable` | FR-3/AC-5, AC-6 |
| P7-UT-06 | RoutePlan comes only from trusted policy | Client candidates are ignored; ordering is stable and every candidate belongs to tenant/Agent allowlists | FR-2/AC-3 |
| P7-UT-07 | Retryable error classification without side effects | A subsequent attempt is selected only for allowed classes with zero output/side effects, with reason recorded | FR-2/AC-3 |
| P7-UT-08 | Fallback after output/tool/approval/Artifact/unknown timeout | Every marker forbids automatic fallback and no subsequent attempt is created | FR-2/AC-4 |
| P7-UT-09 | Candidate reauthorization and monotonically narrowing permissions | Unauthorized candidates fail; post-fallback Effective contains no extra permissions from the previous candidate | FR-2/AC-4 |
| P7-UT-10 | Valid Session binding and resume snapshot | Same scope/tuple and active state pass; the snapshot uses current policy rather than old authorization | FR-4/AC-7 |
| P7-UT-11 | Resume revocation, binding change, and cross-tenant access | All fail closed with no Run and no automatic Engine switch | FR-4/AC-8 |
| P7-UT-12 | Session expiry and Resume idempotency | Expiry is rejected; same key/body returns the original Run and same key/different body conflicts | FR-4/AC-7, AC-8 |
| P7-UT-13 | Run waiting transitions and resource release | running→waiting is valid; waiting→queued needs decision/authorization; terminal and late transitions fail | FR-5/AC-9 |
| P7-UT-14 | Approval separation of duties and revision | Self-approval, unauthorized actor, non-pending state, and revision conflict fail; an eligible reviewer succeeds only once | FR-5/AC-9 |
| P7-UT-15 | Input Schema, expiry, cancellation, and decision idempotency | Only valid unexpired input passes; identical duplicate decisions have no side effect and different decisions conflict | FR-5/AC-10 |
| P7-UT-16 | Deterministic dynamic-model rules and legacy configuration | First matching rule wins with pinned version/reason; no policy strictly follows the legacy fixed Profile | FR-6/AC-11 |
| P7-UT-17 | Dynamic Profile eligibility filtering | Any mismatch in operation, tools, input limits, enablement, version, or tenant authorization excludes a Profile | FR-6/AC-12 |
| P7-UT-18 | usage numeric allowlist and cost state | Negative/nonfinite/unknown units are quarantined; missing pricing is unknown and produces no zero amount | FR-7/AC-14 |
| P7-UT-19 | usage idempotency and additive/informational modes | An event is stored once; only additive data enters totals and overlapping Engine aggregates do not double count | FR-7/AC-13 |
| P7-UT-20 | Multi-currency reports and source correlation | Currencies and unknown counts stay separate; Run/Execution/Engine/model correlations are complete | FR-7/AC-13, AC-14 |
| P7-UT-21 | Atomic queued/running admission boundaries | At-limit rejects and below-limit allows; either full global or tenant cell returns 429 | FR-8/AC-15 |
| P7-UT-22 | Fair candidate ordering and tie-breaks | Never-served first, then last_served, created_at, and ID; a light tenant is not perpetually ordered last | FR-8/AC-16 |
| P7-UT-23 | waiting and recovery quota semantics | waiting is neither running nor claimable queued; recovery readmits and waiting count is separately bounded | FR-8/AC-16 |
| P7-UT-24 | Skill version, source, permissions, and hash | Published entries are immutable; tampering, unauthorized sharing, and version drift fail before execution | FR-9/AC-17 |
| P7-UT-25 | Skill adapter paths and read-only constraints | Layouts are deterministic per Engine; `..`, absolute paths, and symlink escapes fail closed | FR-9/AC-17 |
| P7-UT-26 | Artifact metadata, download authorization, and retention | Hash/size are correct; cross-tenant, expired, and scan-rejected content does not download and cleanup state is truthful | FR-9/AC-18 |
| P7-UT-27 | Runtime Profile configuration validation | Published versions are immutable; arbitrary commands, plaintext Secrets, out-of-range resources, and invalid probes fail | FR-10/AC-19 |
| P7-UT-28 | Circuit closed/open/half_open state machine | Thresholds, cooldown, success/failure counts, and bounded probes strictly match configuration | FR-10/AC-19, AC-20 |
| P7-UT-29 | Stale health, unknown, and manual disable | stale/unknown is unhealthy; manual disabled is not overridden by automatic recovery | FR-10/AC-20 |
| P7-UT-30 | Nine flag defaults, environment overrides, and dependency validation | All default false; `AGENT_` overrides work; enabling with missing dependencies is rejected | FR-11/AC-21 |

## 4. Integration Tests

| ID | Case | Expected result | Trace |
|---|---|---|---|
| P7-IT-01 | Full Adapter start, streamed events, result, and usage path | Events are ordered/replayable, result is unique, usage correlates to Run/Execution, and Worker sees no vendor semantics | FR-1/AC-1 |
| P7-IT-02 | Adapter cancellation, timeout, and long run | Cancellation/timeout terminal states and process cleanup are correct; late results do not overwrite terminal state | FR-1/AC-1; architecture §19.1 |
| P7-IT-03 | Engine unavailable, invalid configuration, and protocol error | Classification is stable with no raw sensitive errors; invalid configuration does not start and fallback classification is correct | FR-1/AC-1, AC-2 |
| P7-IT-04 | Duplicate/late events and disconnected replay | Event ID/cursor deduplication works, late events do not corrupt state, and SSE reconnect repeats no business side effect | FR-1/AC-1; architecture §19.1 |
| P7-IT-05 | Dependency-boundary proof for a new LocalTestAdapter combination | Common contract passes; Worker-core diff is 0 and a new Protocol needs no vendor field in the common Engine contract | FR-1/AC-1; architecture §22 decoupling |
| P7-IT-06 | Safe fallback after pre-start EngineUnavailable | The second candidate reauthorizes and performs effective work only once; both snapshots and fallback events are complete | FR-2/AC-3 |
| P7-IT-07 | Unauthorized candidate and fallback attempts after each side-effect class | No privilege amplification or repeated tool/command/Artifact; unknown outcome fails explicitly rather than rerunning | FR-2/AC-4 |
| P7-IT-08 | End-to-end basic-only Engine execution and UI | Results complete without advanced controls; Effective/reasons come from the server, UI text has i18n, and absent usage is unknown | FR-3/AC-5 |
| P7-IT-09 | Explicit requirement for unsupported capability | API rejects before startup, no Execution/side effect is persisted, and security requirements are not disabled | FR-3/AC-6 |
| P7-IT-10 | Valid Session Resume, same-key retry, and Worker restart | Reauthorization creates only one new Run; native context continues, events/snapshots are complete, and restart creates no duplicate | FR-4/AC-7 |
| P7-IT-11 | Expired, revoked, binding-changed, and cross-tenant Resume | None creates a Run/side effect or leaks Session existence/native metadata | FR-4/AC-8 |
| P7-IT-12 | Human-approval waiting, resource release, approval, and recovery | waiting holds no Lease/running; valid other-person approval atomically queues and recovery continues from the correct cursor | FR-5/AC-9 |
| P7-IT-13 | Approval concurrency, self-approval, duplicate decisions, and Worker restart | Only one valid decision/recovery occurs; approval, wait, Run, and Outbox states agree with no duplicate side effect | FR-5/AC-9 |
| P7-IT-14 | Valid/invalid/unauthorized/expired/cancelled interactive input | Only the valid path resumes once; other states are auditable and ordinary events contain no input Secret | FR-5/AC-10 |
| P7-IT-15 | Legacy fixed Profile and no-policy compatibility with dynamic flag on | With the flag on but no policy, Profile/version/invocation path match Phase 0 | FR-6/AC-11 |
| P7-IT-16 | Dynamic selection and in-Profile model fallback | Snapshot pins selected Profile/version/reason; gateway fallback retains original Profile authorization and correct cost correlation | FR-6/AC-11, AC-12 |
| P7-IT-17 | Unauthorized dynamic model or no eligible candidate | No out-of-allowlist model is selected, no model call occurs, and startup fails with a stable reason | FR-6/AC-12 |
| P7-IT-18 | Combined gateway/Engine usage report and duplicate reporting | Model charges come only from gateway facts; additive/informational modes work and duplicate events do not change totals | FR-7/AC-13 |
| P7-IT-19 | Unknown cost, two currencies, and cross-tenant reports | Unknown is not zero, currencies are not mixed, unknown counts are accurate, and other tenants' records are invisible | FR-7/AC-14 |
| P7-IT-20 | Multiple API/Worker processes submit and claim at limits | Global/tenant queued/running exceed no hard limit; 429/Retry-After are stable and no deadlock occurs | FR-8/AC-15 |
| P7-IT-21 | Capacity release after finish/cancel/reap and fail-closed faults | State changes release according to contract; coordination DB failure admits nothing and counts remain correct after recovery | FR-8/AC-15 |
| P7-IT-22 | Noisy neighbor, fair progress, and waiting recovery | The light tenant progresses every batch and meets the agreed P95; waiting uses no running quota and recovery requeues | FR-8/AC-16 |
| P7-IT-23 | Shared Skill publication, snapshot, and two test-Engine layouts | Version/hash match and mounts are read-only; platform model is unchanged, Adapter conversion is deterministic, and basic execution succeeds | FR-9/AC-17 |
| P7-IT-24 | Skill tampering, cross-tenant references, and path/symlink escape | All fail before startup, no untrusted content enters Workdir, and no other tenant's path leaks | FR-9/AC-17 |
| P7-IT-25 | Small/large Artifact writes, hashes, authorized downloads, and events | Streamed size limits work, content/hash match, events contain no object body/Secret, and authorized download succeeds | FR-9/AC-18 |
| P7-IT-26 | Unauthorized/expired Artifact download, scan rejection, and cleanup retry | All are blocked by policy; failed object deletion is not reported cleaned and retries/alerts are observable | FR-9/AC-18 |
| P7-IT-27 | Runtime Profile snapshot and circuit opening after consecutive failures | Resource/egress/Secret references execute by version; after closed→open the candidate is skipped or fails explicitly without wider Effective | FR-10/AC-19 |
| P7-IT-28 | Multi-Worker half-open recovery, stale health, and manual disable | Global half_open probes stay within limit; failure reopens and success closes; stale is unavailable and manual disable wins | FR-10/AC-20 |
| P7-IT-29 | Phase 0 regression with all nine flags off and after each slice is disabled | Legacy Agent/Run/API/SSE/model/terminal behavioral diff is zero and no new path causes a new side effect | FR-11/AC-21 |
| P7-IT-30 | Single-slice canary, rollback, historical-data reads, and re-enablement | Only that slice stops new execution; old/new data remain readable without down migration; re-enablement reauthorizes/checks expiry/health | FR-11/AC-22 |

## 5. Common Checks (Applicable to This Phase)

| ID | Check | Pass standard | Trace |
|---|---|---|---|
| P7-CM-01 | Phase 0 baseline prerequisite | Behavioral, coverage, performance, capacity, and release/rollback baselines include environment/samples/evidence; comparative metrics cannot pass while absent | G11/AC-21, AC-22; architecture §17 Phase 0 |
| P7-CM-02 | Migration head and planning-number verification | List head again before implementation; 0058+ is not treated as existing; real number/down_revision and documents agree | FR-11/AC-22 |
| P7-CM-03 | Online migration and compatibility | Upgrade from current head succeeds; expand-only with no long business-table locks; waiting/index/new tables remain old-code compatible and rollback needs no down | FR-4~FR-11/AC-22 |
| P7-CM-04 | Configuration loading and dependencies | Defaults false, environment overrides and bounded numbers work; enabling fails with missing Phase dependencies or unfrozen quotas | FR-11/AC-21 |
| P7-CM-05 | Common Adapter contract completeness | Every launched Adapter runs all applicable architecture §19.1 items and the LocalTestAdapter fault matrix, with no unrecorded vendor exemption | FR-1/AC-1; architecture §19.1~19.2 |
| P7-CM-06 | Tenant and resource scope | Session/wait/usage/Skill/Artifact/Profile/report/scheduling resources are cross-tenant unreachable with no missing scope filter | FR-2~FR-10/AC-4, AC-8, AC-14, AC-17~19 |
| P7-CM-07 | Secret, sandbox, and path safety | Logs/events/audits/metadata/reports contain no Secret; untrusted execution has sandbox, egress, resource, and path isolation; dangerous cases fail closed | FR-2, FR-4, FR-5, FR-8~FR-10/AC-4, AC-8, AC-10, AC-18~20; architecture §22 security |
| P7-CM-08 | Audit and observability | route/fallback/resume/decision/quota/usage/artifact/health records include correlation IDs, versions, and stable reasons without bodies/Secrets; alerts fire | FR-2~FR-10; architecture §22 operability |
| P7-CM-09 | Effective UI and i18n | UI relies only on server Effective; waiting/unknown/health/rejection reasons are correct; all new user text passes i18n checks | FR-3, FR-5, FR-7, FR-10/AC-5, AC-9, AC-14, AC-20 |
| P7-CM-10 | Performance, capacity, and lock evidence | Record P95, throughput, EXPLAIN, lock waits, and samples under agreed load; routing, reports, quota, and fairness meet 01/02 metrics | G2, G7, G8, G10/AC-15, AC-16 |
| P7-CM-11 | Regression and all-off diff | Affected existing suites are green; all-off diff against Phase 0 is zero; every skip has a reason and does not count as passed | G3, G11/AC-21 |
| P7-CM-12 | Small PRs, document/code reality, and vendor boundary | Each slice is independently scoped and document paths/status match code; Worker remains decoupled and no unapproved vendor delivery is described as complete | G1, G11/AC-1, AC-22; architecture §19.4, §22 |

## 6. Regression Scope

- Existing Runtime: `backend/tests/test_runtime_engine.py`, `test_runtime_postgres.py`, `test_runtime_scope.py`, `test_runtime_availability.py`, focusing on the five states, cancellation/timeout, leases, same-conversation exclusion, SSE cursors, and terminal protection.
- Models and quotas: `test_model_gateway.py`, `test_gateway_governance.py`, `test_gateway_credentials.py`, `test_gateway_migrations.py`, ensuring fixed Profiles, model fallback, calls/cost, and existing quotas are not bypassed.
- Approval and scope: `test_runtime_scope.py` plus existing approval tests; waiting, recovery, and decisions must not widen tenant/business/workspace scope.
- Workspace/storage: existing `test_tool_workspace.py`, `test_agent_workspace.py`, `test_knowledge_workspace.py`, and corresponding migration tests; new execution storage must not alter knowledge/tool boundaries.
- All migrations: Upgrade from the real current head and verify old-code compatibility. Run 0058+ tests only after their slices create them; do not currently claim those migration tests exist or pass.
- Frontend: Run typecheck, i18n, build, and existing Playwright for affected pages; verify the legacy five states, fixed-model reports, and no-advanced-capability empty states.
- Phase 0~6: Include applicable contract, React/Codex, Runtime Host, Workspace, credential, event/fencing regressions once created. Current unmeasured baselines remain pending Phase 0.

## 7. Defect Severity and Exit Criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocking | Cross-tenant leak; unauthorized execution/fallback/recovery; repeated confirmed external side effect; data loss; sandbox escape | Stop slice canary immediately; fix and complete all security/regression tests before continuing |
| P1 critical | Terminal/Lease/idempotency error; quota overrun; duplicate waiting recovery; duplicate charges; flag failure; circuit causes global outage | No slice acceptance or canary expansion before a fix |
| P2 major | Non-security policy deviation, incomplete report display, or nonblocking performance target missed | Only non-hard-gate items may proceed after owner/deadline are recorded and the acceptance owner confirms conditional acceptance in the single acceptance record |
| P3 minor | Text, noncritical logging, or documentation-link issue | Schedule a fix without hiding i18n or traceability failures |

**Single-slice exit criteria**: All applicable UT/IT/CM cases pass with individual evidence; applicable AC scenarios pass in integration; affected regressions are green; no P0/P1 remains open; migration, canary, rollback, and all-off diff gates pass; Phase 0 comparative baselines are accepted. Every skip states environment, impact, and retest owner and is excluded from the pass rate.

**Phase 7 overall exit criteria**: Claim overall completion only when every slice approved for the final scope meets single-slice exit and architecture §22 decoupling, security, extensibility, and operability items have evidence. Vendor counts, unit-test counts, or one demo are not substitutes.
