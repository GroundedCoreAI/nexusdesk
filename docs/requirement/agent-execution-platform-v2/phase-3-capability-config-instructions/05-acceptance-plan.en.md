# Phase 3 · Capabilities, Configuration, and Instructions — Acceptance Plan

> Status: Pending implementation (execute before launch; no acceptance results currently exist)
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence; remove standalone UAT, duplicate metrics, and multi-role sign-off)
> Basis: `01-business-goals.md` (G1–G4, success metrics), `02-requirements.md` (AC-1–AC-11); test execution follows `04-test-plan.md`

## 1. Acceptance Scope and Responsibility

Confirm every AC, retain evidence for compatibility, performance, and snapshot criteria, and verify that clients cannot elevate privileges, sensitive data is not disclosed, and flags can roll back. By default, the acceptance owner organizes and records the decision while the executor prepares environments, performs supplementary checks, and organizes evidence; one person may hold both responsibilities. Do not invent independent product, QA, business, security, or operations roles. Developer self-verification proves conformance to this document, not real-user acceptance or an independent audit.

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

**Evidence reuse**: A1–A11 directly reference the corresponding UT/IT/CM, CI, database, and frontend automation results in `06-test-report.md` wherever possible instead of manually repeating the full suite. Records may link test nodes and raw evidence. Merged code, skip, or `pending_env` alone is not a pass.

## 4. Key Manual Checks

Use these only to supplement actual UI and rollback behavior that automation does not fully cover. Record executor, target SHA, result, and evidence for each; do not create a user-representative role or standalone UAT round.

| # | Check | Pass criterion |
|---|---|---|
| M1 | Open a legacy Agent and new Engine configuration | Legacy Agents require no forced field completion, changed meaning, or republication; shared fields, React fields, and read-only capabilities are clearly distinguished |
| M2 | Submit unknown/conflicting configuration and inspect capability preview | Errors are actionable and fully internationalized; “unsupported,” “environment unavailable,” and “policy denied” are distinct, and declaration clearly does not imply authorization |
| M3 | Perform one application rollback and inspect the UI | Stale Phase 3 editing controls disappear while historical published versions and Runs remain visible |

## 5. Security, Data, and Release Hard Gates

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
| C11 | With caches warm, added resolution latency over the Phase 0 admission/claim p95 is at most 50ms; after warmup, collect at least 100 samples under identical environment/load and separate configuration, probe-cache, and policy timing from external model time | Mandatory; record `not_measured` when unmeasured rather than passing | G1; performance success metric |

## 6. Pass Criteria and Acceptance Record

- **Pass**: A1–A11 and C1–C11 all pass; M1–M3 are complete or have equivalent automated evidence; no P0/P1 remains; rollback evidence is complete.
- **Conditional pass**: only non-hard-gate P2/P3 residuals unrelated to security, compatibility, snapshots, the performance hard gate, or rollback, each with an owner/deadline and an explanation from the acceptance owner in the record below; veto items are never eligible.
- **Fail**: any AC or hard gate fails; missing Phase 0 baselines make compatibility undecidable; or any elevation, cross-tenant access, secret disclosure, or silent non-React fallback occurs. Revalidate affected items and full regressions after fixes.

Produce the Phase 3 Acceptance Report with A/C evidence links, raw C11 measurements, key manual checks, migration/rollback evidence, residuals, and the single record below; multi-role signatures are not required.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence/residuals |
|---|---|---|---|---|---|
| To be filled | To be filled (may be the acceptance owner) | To be filled | To be filled | Pending acceptance | To be filled |
