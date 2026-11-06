# Phase 3 · Capabilities, Configuration, and Instructions — Acceptance Plan

> Status: Pending implementation (execute before launch; no acceptance results currently exist)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G4, success metrics), `02-requirements.md` (AC-1–AC-11); test execution follows `04-test-plan.md`

## 1. Acceptance Objectives and Organization

Confirm that the phase is **functionally correct** (every AC reproduced), **commercially effective** (compatibility, performance, and snapshot targets met), and **safe to launch** (no client elevation or sensitive disclosure, with reversible flags), then record a signed conclusion.

| Role | Responsibility |
|---|---|
| Product owner | Chairs acceptance; judges configuration/preview experience and signs P2 residual decisions |
| QA | Executes A1–A11 and evidence; owns Phase 0 baseline comparisons, regressions, and defect severity |
| Engineering lead | Provides environments, migration/rollback drills, metric data, and fixes |
| Security lead | Judges elevation, cross-tenant access, snapshot sensitivity, policy provenance, and veto security gates |
| Operations lead | Validates flag canary, observability, rollback operation, and production readiness |
| Tenant administrator representative | Performs UAT for seamless legacy Agents, new configuration, and read-only Effective view |

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Production-like (React + controlled model/tools) | Functional acceptance, real configuration/performance metrics, and Summary/Memory regression |
| Dedicated PostgreSQL + LocalTestAdapter | Capability layers, start barrier, failure/cancellation/timeout, cross-tenant access, and snapshots |
| Quickstart two-container stack (demo model) | Verify default-off, legacy React execution, and deployment rollback promises |
| Disposable production-like database copy | Online migration, concurrent reads/writes, and application rollback; downgrade only on disposable data |
| Frontend acceptance build | Engine configuration, read-only preview, i18n, and error experience |

**Prerequisites**: Phase 0 baseline and Phase 1–2 acceptance complete; all `04-test-plan.md` cases pass with no P0/P1; actual migration head/down_revision revalidated during implementation; at least two dedicated tenants and independent scopes, isolated from production customer data; all snapshot/log evidence scanned for secrets first.

## 3. Functional Acceptance Checklist (AC-1–AC-11)

| # | Criterion | Acceptance steps | Pass standard | Traceability |
|---|---|---|---|---|
| A1 | AC-1 | Import valid Phase 0 legacy fixtures, read drafts/versions, execute React, then save and publish once normally | Default triple is correct; model/tool/Summary/Memory diff is zero; reads do not alter history and saves create only a new version | FR-1; G1; US-1 |
| A2 | AC-2 | Save valid React configuration, then submit unknown triples, latest, type/boundary errors, extra fields, and unequal aliases | Valid input resolves exactly; 100% of invalid inputs are consistently rejected with no Adapter start | FR-2; G1; US-2 |
| A3 | AC-3 | Simulate missing deployment, incompatible version, probe timeout, and missing Workspace | Available never exceeds Declared, reason codes are clear, and unavailable required capabilities block start | FR-3; G2; US-2, US-3 |
| A4 | AC-4 | Deny the same capability at platform, tenant, Agent, and Execution layers and attempt lower-layer allow | Effective always denies; snapshots explain every source, version, and reason | FR-4; G2; US-3 |
| A5 | AC-5 | Forge all capability layers, policy versions, and host fields through raw HTTP, then access tenant A as tenant B | Zero elevations and cross-tenant successes; stable 4xx/domain errors and security audits exist with no sensitive reflection | FR-5; G2; US-3 |
| A6 | AC-6 | Inspect five snapshot types for completed/failed/cancelled/timed-out Runs, then inject oversized and secret-containing candidates | Normal snapshots are complete before start and immutable; invalid candidates never start; historical NULL and public allowlists behave correctly | FR-6; G4; US-5 |
| A7 | AC-7 | Replay Phase 0 empty, Summary, Memory, combined, disabled, and history-truncation fixtures | React message order, wording, budgets, logs, and write-back have zero diff and no duplicate/empty messages | FR-7; G3; US-4 |
| A8 | AC-8 | Pass identical InstructionInput to React and test Providers and inspect call counts and output | Native formats are independent, business rendering runs once, and neither forced ReAct conversion nor Provider fallback occurs | FR-7; G3; US-4 |
| A9 | AC-9 | Edit and preview as an administrator, change platform/tenant policy, and switch every supported language | Effective is read-only and server-recomputed; forms/errors are fully internationalized with no internal snapshots or elevation path | FR-4, FR-5, FR-8; G1, G2; US-1, US-3 |
| A10 | AC-10 | Drill master-flag off, legacy React, non-React, historical reads, and application rollback | React returns to Phase 2; non-React returns `execution_phase3_disabled` without calling React; history remains readable without downgrade | FR-8, FR-9; G4; US-6 |
| A11 | AC-11 | Verify the implemented migration chain, upgrade a production-like copy under concurrent reads/writes, and test downgrade on disposable data | Exactly five nullable columns are added; old rows are NULL, new rows work, historical migrations are unchanged, and application rollback needs no downgrade | FR-6; G1, G4; US-5, US-6 |

Record for every scenario: executor, date, environment, target commit, setup data, actual operations, expected/actual result, decision, and screenshot/log/database evidence links. Failures or missing environments must not be rewritten as passes.

## 4. UAT Decision (Tenant Administrator Representative)

- Legacy Agents show no forced field completion, changed meaning, or mandatory republication prompt.
- New Engine configuration distinguishes shared fields, React fields, and read-only capabilities; unknown/conflicting errors are actionable and fully internationalized.
- Capability preview distinguishes “unsupported,” “environment unavailable,” and “policy denied,” without implying that declaration means authorization.
- After rollback, stale Phase 3 editing controls disappear and historical published versions and Runs remain visible.

## 5. Business Metric Acceptance

| Metric | Baseline | Target | Measurement method |
|---|---|---|---|
| Legacy configuration compatibility | Pending Phase 0 measurement | 100% load/normalize/republish/execute for valid fixtures | Execute A1 for every fixed Phase 0 fixture and record fixture version and failure reasons |
| Invalid configuration rejection | Pending Phase 0 inventory | 100% for all specified invalid classes, with stable error codes | Count A2 against P3-UT-04/05 and P3-IT-02 |
| Successful client capability elevations | Pending Phase 0 trust-boundary inventory | 0 | Cross-check A5 raw-request matrix, audits, and security tests |
| Phase 3 Run snapshot completeness | Pending Phase 0 measurement | 100% across all four terminal states, with zero starts on missing snapshots | Query completed/failed/cancelled/timed-out samples and compare start-event timing |
| React instruction compatibility diff | Pending Phase 0 message baseline | 0 | Compare roles, order, wording, budgets, switches, and write-back for fixed fixtures |
| Added resolution latency | Pending Phase 0 admission/claim p95 | At most 50ms added with caches | After warmup, sample at least 100 times under identical environment/load; separate configuration, probe-cache, and policy timing from external model time |

## 6. Compliance Checks

| # | Check | Decision | Traceability |
|---|---|---|---|
| C1 | Clients, UI, and Adapter declarations cannot grant Effective; the entire forgery matrix has zero elevations | Veto | AC-3–AC-5; G2; FR-3–FR-5 |
| C2 | Policy sources are trusted and versioned; lower layers cannot reverse denial and no automatic cross-Engine fallback exists | Veto | AC-4, AC-10; G2; FR-4, FR-8 |
| C3 | Snapshots, logs, events, audits, and public APIs contain no tokens, keys, raw customer memory, or host secrets | Veto | AC-5, AC-6; G4; FR-5, FR-6 |
| C4 | Tenant and business/workspace scope isolation covers configuration, preview, policy, snapshots, and audits | Veto | AC-5; G2; FR-5 |
| C5 | Snapshots are complete before Adapter start and immutable, with no invented backfill for historical NULLs | Mandatory | AC-6; G4; FR-6 |
| C6 | React Summary/Memory reuses existing rendering and switches with no Phase 0 baseline difference | Mandatory | AC-7; G3; FR-7 |
| C7 | Legacy Agent JSONB is not bulk-rewritten, invalid configuration cannot publish, and unregistered Engines remain closed | Mandatory | AC-1, AC-2; G1; FR-1, FR-2 |
| C8 | User text is fully internationalized, Effective is read-only, and internal snapshots are not directly exposed | Mandatory | AC-9; G1, G2; FR-8 |
| C9 | Master-flag and application rollback drills succeed without migration changes; non-React never silently falls back | Veto | AC-10; G4; FR-8, FR-9 |
| C10 | Migration identifiers are revalidated before implementation, exactly five columns are added, history is unchanged, and no Phase 4/5/6 scope leaks in | Mandatory | AC-11; G1, G4; FR-6 |

## 7. Pass Criteria and Sign-Off

- **Pass**: A1–A11 all pass; all six metrics meet targets; C1–C10 pass; no P0/P1 remains; rollback evidence is complete.
- **Conditional pass**: only P2/P3 residuals unrelated to security, compatibility, snapshots, or rollback, each with an owner and deadline; veto items are never eligible for conditional pass.
- **Fail**: any AC, hard metric, or veto item fails; missing Phase 0 baselines make compatibility undecidable; or any elevation, cross-tenant access, secret disclosure, or silent non-React fallback occurs. Revalidate affected items and full regressions after fixes.

Produce the Phase 3 Acceptance Report with AC records, raw metric data, compliance results, migration/rollback evidence, residual list, conclusion, and signatures (product / QA / engineering / security / operations).
