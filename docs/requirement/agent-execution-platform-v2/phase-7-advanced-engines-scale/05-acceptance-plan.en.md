# Phase 7 · Advanced Engine Capabilities and Scale — Acceptance Plan

> Status: Deferred (early-stage project; acceptance is not starting, and this document is neither launch approval nor an acceptance result)
> Deferral decision: 2026-11-07; see “Deferral and Requirement Tracking” in `02-requirements.en.md` for the FR-1~FR-11 P4 issues; acceptance runs independently per slice only after the phase is reactivated
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence; remove standalone UAT, duplicate metrics, and multi-role sign-off; phase remains deferred)
> Basis: `01-business-goals.en.md` (G1~G11 and success metrics), `02-requirements.en.md` (AC-1~AC-22), `03-technical-design.en.md` (S7-01~S7-09), and `04-test-plan.en.md` (P7-UT/IT/CM)
> Baseline statement: Business and performance baselines are unmeasured pending Phase 0; comparative metrics without baselines remain pending and cannot pass

## 1. Acceptance Scope and Responsibility

After the phase is reactivated, verify applicable ACs, reauthorization, no duplicate side effects, and flag-rollback evidence independently for each slice. Passing one slice approves neither other slices nor any specific vendor Adapter. For each slice, the acceptance owner confirms scope and records the decision while the executor prepares environments, performs supplementary checks, and organizes evidence; one person may hold both responsibilities. Do not invent independent product, QA, business, finance, SRE, or Adapter-reviewer roles. Developer self-verification proves conformance to this document, not real-user acceptance or an independent security audit. Approval separation of duties, tenancy, Secrets, usage, quotas, and rollback remain technical hard gates even when one person holds multiple responsibilities.

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Production-like dedicated tenants (approved real dependencies) | Applicable functional A scenarios, capacity/performance/fairness metrics, and real fault drills |
| At least two API/Worker processes + PostgreSQL | Concurrent quota, fair scheduling, Session/waiting recovery, Worker restart, and distributed health |
| LocalTestAdapter + demo/mock models | Vendor-independent common contracts, error/side-effect matrix, and basic-execution degradation |
| Controlled object storage/temporary volume | Skill hashes/read-only mounts, large Artifacts, download authorization, Secret scans, and retention |
| quickstart two-container stack (demo model) | Default configuration, all-off compatibility, deployment, and rollback commitments; not production-performance evidence |

**Common prerequisites**:

1. Phase 0 baselines are accepted and the slice's Phase 1~6 dependencies have acceptance evidence. A missing dependency makes the slice `blocked_dependency`; mocks cannot substitute for production launch acceptance.
2. All applicable UT/IT/CM cases in `04-test-plan.en.md` pass with no open P0/P1. Skips do not count as passes and have retest plans.
3. Current migration head is rechecked; statements that 0058+ are planning numbers are replaced by real migration information, with upgrade/old-code compatibility/rollback evidence.
4. Acceptance uses at least two dedicated tenants and separate business/workspace data, never production customer data. Fake Secrets are identifiable and real credentials remain with authorized staff.
5. Actual slice launch scope, thresholds, canary tenants, monitoring, capacity, and rollback owner are frozen. Vendor or advanced capabilities outside that scope are not covered by this acceptance.
6. All new user-visible text passes i18n checks; API/SDK/UI version compatibility for waiting, Effective, and unknown is verified.

## 3. Functional Acceptance Checklist (AC-1~AC-22)

| # | Slice/trace | Acceptance steps | Pass criteria |
|---|---|---|---|
| A1 | S7-01; AC-1; G1/US-1/FR-1 | Register a new LocalTestAdapter Engine/Protocol combination and run common contracts plus new Protocol resolution | All applicable architecture §19.1 items pass; results/events/usage correlate; Worker-core diff is 0 and the common Engine contract has no vendor field |
| A2 | S7-01; AC-2; G1/US-1/FR-1 | Submit an unknown combination, incompatible version, invalid configuration, and capability overclaim separately | Each is rejected before tenant business execution with a stable reason and no route/side-effect record |
| A3 | S7-02; AC-3; G2/US-2/FR-2 | Make the preferred candidate return EngineUnavailable before output, then select an authorized second candidate | Exactly one subsequent effective attempt; both policy/Effective/quota checks and reasons are auditable; Run has one terminal state |
| A4 | S7-02; AC-4; G2/US-2/FR-2 | Inject an unauthorized candidate and request fallback after output, tool, approval, Artifact, and unknown timeout separately | Unauthorized candidates never execute; no automatic fallback after side effects/unknown outcome and the operation-ledger count does not increase |
| A5 | S7-02; AC-5; G3/US-3/FR-3 | Execute with a basic Adapter lacking Session/approval/interaction/streaming and open the UI | Basic result completes; Effective false values match reasons; no simulated buttons and missing usage is unknown |
| A6 | S7-02; AC-6; G3/US-3/FR-3 | Explicitly request terminal or Resume absent from Effective | `capability_unavailable` before startup, no Engine start/side effect, and no silent security weakening |
| A7 | S7-03; AC-7; G4/US-4/FR-4 | Resume a valid Session, retry with the same idempotency key, and restart one Worker | Current authorization is rerun; exactly one new Run retains native context with complete new snapshots/events |
| A8 | S7-03; AC-8; G4/US-4/FR-4 | Resume after expiry, revocation, Agent/Workspace/Engine binding change, and from another tenant | None creates a Run/side effect or switches Engines; no Session-existence/Secret leak and audit has stable reasons |
| A9 | S7-04; AC-9; G5/US-5/FR-5 | Request approval, inspect waiting resources, then concurrently run other-person approval, self-approval, duplicate approval, and Worker restart | waiting holds no running Lease/quota; only valid other-person approval resumes once; approval/wait/Run/Outbox agree with no duplicate side effect |
| A10 | S7-04; AC-10; G5/US-5/FR-5 | Submit valid input, invalid Schema, unauthorized input, expired input, and cancellation separately | Only valid unexpired input resumes once; none of the others resumes; ordinary logs/events contain no input Secret |
| A11 | S7-05; AC-11; G6/US-6/FR-6 | Execute one bounded-policy Agent and one legacy no-policy Agent, then trigger in-Profile fallback | New Agent pins allowed Profile/version/reason; legacy Agent matches Phase 0; gateway fallback permissions stay unchanged |
| A12 | S7-05; AC-12; G6/US-6/FR-6 | Make the preferred model tool-incompatible, unauthorized, or unpinned, then provide/withhold an eligible candidate | Only an eligible authorized entry is selected; with none, startup fails without an unauthorized model call |
| A13 | S7-06; AC-13; G7/US-7/FR-7 | Report the same Engine event twice and an Engine aggregate overlapping a gateway model call | Records are idempotent; overlap is informational, totals do not double count, and source/Execution/model correlations are complete |
| A14 | S7-06; AC-14; G7/US-7/FR-7 | Create unpriced usage and two-currency records, then query as another tenant | Unknown is not zero and counts are accurate; currencies remain separate; no cross-tenant data/existence leak |
| A15 | S7-07; AC-15; G8/US-8/FR-8 | Concurrently submit, claim, finish, cancel, and reap through multiple API/Worker processes at limit boundaries | Global/tenant queued/running never exceed hard limits; 429 is stable, release is accurate, and no deadlock/stale count occurs |
| A16 | S7-07; AC-16; G8/US-8/FR-8 | Keep one tenant saturated, submit intermittently from a light tenant, and create/resume waiting Runs | Light tenant progresses every batch with P95≤2× same-environment idle baseline; waiting uses no running quota and recovery readmits |
| A17 | S7-08; AC-17; G9/US-9/FR-9 | Publish a shared Skill and execute under two test-Engine layouts, then tamper and reference cross-tenant | Valid version/hash is pinned and read-only; conversion is deterministic; tampering/unauthorized access fails before startup without path leaks |
| A18 | S7-08; AC-18; G9/US-9/FR-9 | Write small/large Artifacts and test valid download, path escape, unauthorized/expired download, scanning, and cleanup | Valid content/hash/size are correct; dangerous/unauthorized/expired access fails; scan/cleanup outcomes are truthful and failures retry/alert |
| A19 | S7-09; AC-19; G10/US-10/FR-10 | Publish a Profile, verify its execution snapshot, and inject consecutive health failures to threshold | Resource/egress/Secret references follow the version; closed→open occurs; candidate is skipped or fails explicitly without wider Effective |
| A20 | S7-09; AC-20; G10/US-10/FR-10 | After cooldown, run half-open success/failure, create stale/unknown health, and manually disable | Multi-Worker probes are bounded; transitions are correct; stale is unhealthy, manual disable wins, and recovery still reauthorizes routing |
| A21 | Release governance; AC-21; G11/US-11/FR-11 | For each slice, verify implemented flags default false, toggle only the target slice, and replay Phase 0 with all implemented flags off; overall acceptance then covers all nine flags and individual toggles | The target slice rolls back independently with explicit dependency validation; legacy Agent/Run/API/SSE/model/terminal behavioral diff is zero; unimplemented slices are not launch prerequisites |
| A22 | Release governance; AC-22; G11/US-11/FR-11 | Take any slice through scope review, head verification, canary, flag-off rollback, and re-enablement | Only that slice is approved; no down migration occurs and history remains readable; re-enablement reauthorizes/checks expiry/health/backlog |

Every scenario record includes executor, date, environment/version, applicable slice and flag, prerequisite data, actual result, verdict, test-run link, and screenshot/log/read-only database evidence. Items that cannot execute locally are marked `pending_env` with required environment and proposed reviewer; they cannot be omitted or marked passed.

**Evidence reuse**: A1–A22 directly reference the corresponding UT/IT/CM, CI, multiprocess, capacity, reporting, and storage evidence in the slice's `06-test-report.md` wherever possible instead of manually repeating the full suite. Contract, authorization, recovery, usage, quota, fairness, Skill/Artifact, health, and rollback criteria are assessed directly from their A/C evidence without a second business-metric acceptance round; comparative items without baselines remain `pending` and cannot pass.

## 4. Key Manual Checks

Perform only checks relevant to the current slice that automation does not fully cover. Record executor, target SHA, result, and evidence for each; do not create business, finance, or operations-representative roles. Mark items unrelated to the slice `not_applicable` with a reason.

| # | Applicable slices | Check and pass criterion |
|---|---|---|
| M1 | S7-02, S7-03 | Missing advanced capabilities produce clear results or rejections without unauthorized/unsupported controls; waiting, unknown, and circuit text is understandable; Resume causes no wrong-tenant context or revival of revoked capabilities, and failures expose no native Engine sensitive details |
| M2 | S7-04 | Pending items contain sufficient but minimal request context, revision/expiry, and decision results; repeated clicks do not repeat recovery |
| M3 | S7-05 | Dynamic model reasons, versions, and legacy compatibility are explainable, and the UI cannot select an unauthorized Profile |
| M4 | S7-06 | Reports clearly show “estimated,” coverage, unknown, and currency; informational and additive values are never combined, and estimates are not treated as invoices |
| M5 | S7-07–S7-09, release governance | Quota rejection, open circuit, half-open recovery, rollback, and re-enablement have traceable events/alerts without exposing Secrets or sensitive host paths |

## 5. Security, Data, and Release Hard Gates

| # | Check | Verdict requirement | Trace |
|---|---|---|---|
| C1 | Every new resource/report is tenant/business/workspace isolated and cross-tenant identifiers are not enumerable | Veto | FR-2~FR-10; AC-4, AC-8, AC-14, AC-17~19; architecture §22 security |
| C2 | Every fallback candidate reauthorizes, no automatic fallback follows side effects/unknown outcome, and permissions only narrow | Veto | G2/FR-2; AC-3, AC-4; architecture §17 Phase 7 |
| C3 | Session Resume and waiting recovery reload current policy, credential references, and Effective | Veto | FR-3~FR-5; AC-7~AC-10; architecture §18.3 |
| C4 | Approval retains separation of duties/revision/audit; self-approval, unauthorized, expired, and different duplicate decisions fail | Veto | FR-5; AC-9, AC-10 |
| C5 | Logs, events, audits, configuration, Skill/Artifact metadata, and reports contain no plaintext Secret; untrusted execution has sandbox/egress/resource isolation | Veto | FR-2, FR-4, FR-5, FR-9, FR-10; AC-8, AC-10, AC-18~20; architecture §22 security |
| C6 | Skill source/version/hash/permissions and read-only mounts work; Artifact downloads reauthorize and retention/scan states are truthful | Must pass | FR-9; AC-17, AC-18; architecture §18.5 |
| C7 | Model/Engine usage is not duplicated; unknown is not 0; currencies are not mixed; amounts are estimates, not invoices | Must pass | FR-7; AC-13, AC-14; architecture §22 operability |
| C8 | Multi-Worker quota is atomic/fail-closed; fairness cursor is not process-local; waiting uses no running quota | Must pass | FR-8; AC-15, AC-16; architecture §18.2 |
| C9 | All nine flags default false; per-slice rollback needs no down migration and authorized history remains readable/cleanable | Must pass | FR-11; AC-21, AC-22 |
| C10 | New Engines do not change Worker core, new Protocols do not pollute the common Engine contract, and Adapter evidence is complete | Must pass | FR-1; AC-1, AC-2; architecture §19 and §22 decoupling/extensibility |
| C11 | Phase 0 baselines, applicable tests, performance samples, and CI evidence are complete; skip/pending is not presented as passed | Must pass | G11; AC-21, AC-22; architecture §17 Phase 0 and §19.4 |
| C12 | Actual launch scope is confirmed per slice in its single acceptance record; no vendor delivery is promised and multiple core capabilities are not combined into a Big Bang PR | Must pass | G1, G11; AC-1, AC-22; architecture §17 Phase 7 and §19.4 |

## 6. Slice-by-Slice Acceptance Evidence Requirements

| Slice | Mandatory A scenarios | Evidence focus |
|---|---|---|
| S7-01 | A1, A2, A21, A22 | Common contracts, LocalTestAdapter fault matrix, and Worker/Protocol decoupling |
| S7-02 | A3~A6, A21, A22 | Routing policy, side-effect ledger, Effective UI, and basic degradation |
| S7-03 | A7, A8, A21, A22 | Current authorization, Session binding/expiry, idempotency, and Worker recovery |
| S7-04 | A9, A10, A21, A22 | Approval separation of duties, waiting resources, transaction consistency, and input safety |
| S7-05 | A11, A12, A21, A22 | Legacy fixed-Profile compatibility, allowlists, snapshots, and cost correlation |
| S7-06 | A13, A14, A21, A22 | Idempotency, additive/informational, unknown, currencies, and tenant reports |
| S7-07 | A15, A16, A21, A22 | Multi-Worker atomic quota, fairness P95, locks/EXPLAIN, and fail closed |
| S7-08 | A17, A18, A21, A22 | Skill hash/read-only behavior and Artifact authorization/retention/scanning/large objects |
| S7-09 | A19, A20, A21, A22 | Distributed health, circuit/half-open behavior, stale data, and manual disable |

Every slice also executes all applicable C1~C12. A21/A22 are shared release gates for each slice and do not require other slices to launch simultaneously.

## 7. Pass Criteria and Acceptance Record

- **Single-slice pass**: All applicable A/C criteria pass; relevant M items are complete, have equivalent automated evidence, or are explicitly `not_applicable`; no P0/P1 remains; canary, rollback, monitoring, and evidence are complete.
- **Single-slice conditional pass**: only non-hard-gate P2/P3 residuals remain, each with owner, deadline, impact, and an explanation from the acceptance owner in the record below; security, tenancy, side-effect, usage/double-charge, and other hard gates all pass, and canary scope is explicitly limited.
- **Fail**: any veto or A/C criterion fails, a Phase dependency/baseline is missing, rollback fails, or pending/skip is recorded as passed. Reverify affected A/C and regressions after fixes.
- **Phase 7 overall pass**: every slice in the final approved scope has an independent pass record. One slice's decision or a vendor Adapter count cannot establish overall success. Lightweight acceptance does not change the current deferred status.

Each slice produces a “Phase 7 / S7-xx Acceptance Report” with scope and flag, A/C evidence links, key manual checks, necessary raw performance/lock/EXPLAIN data, migration/CI/canary/rollback evidence, residuals, and the single record below; multi-role signatures are not required.

| Slice/flag | Acceptance owner | Executor | Date | Target SHA | Decision | Evidence/residuals |
|---|---|---|---|---|---|---|
| To be filled | To be filled | To be filled (may be the acceptance owner) | To be filled | To be filled | Pending acceptance (phase deferred) | To be filled |
