# Phase 3 · Capabilities, Configuration, and Instructions — Acceptance Plan

> Status: pending implementation (execute before launch; no acceptance results or 07 currently exist)
> Created: 2026-11-02
> Revised: 2026-11-13 (third close-out batch: the T7/T8 rulings land in acceptance - A3 gains the evidence boundary and production-observable signals, A4 gains the platform ceiling and constant-revision notes, A6/C5 pin that `execution_error` is never the terminal code of a classified barrier failure, A10 gains the fingerprint exclude set, that the misconfigured process still boots, and `runtime.for_run==0`, and C2/C9 gain the production-port shapes and Run-side code discipline; per R-42–R-52)
> Revised: 2026-11-13 (§6 and the environment table register that T12/T13 moved out of this phase to issues #127/#128 (08 R-39), and the acceptance scope narrows accordingly)
> Revised: 2026-11-13 (M3 criterion anchored to the 03 §7.4 execution-config-flags declarative gating, per R-25)
> Revised: 2026-11-13 (T4 rework rulings R-17–R-22: trusted policy-revision entry point, capability settings home and TTL floor, single Effective projection, non-bypassable Available narrowing)
> Revised: 2026-11-13 (A4 clarifies the start-blocking boundary between required-capability missing and policy narrowing, per R-16)
> Revised: 2026-11-12 (development entry versus final gates, real C11, flag matrix, and post-acceptance seed)
> Basis: `01-business-goals.md` (G1–G4, success metrics), `02-requirements.md` (AC-1–AC-11), `04-test-plan.md`

## 1. Scope and Lightweight Responsibility

Verify actual evidence for AC-1–AC-11, C1–C11, and M1–M3 across compatibility, security, snapshots, performance, four locales, and rollback. The acceptance owner organizes and records one conclusion; the executor prepares environments, performs supplemental checks, and organizes evidence. They may be the same person. Invent no independent product/QA/business/security/operations roles or multi-role sign-off. Developer self-verification is neither real-user acceptance nor independent audit.

## 2. Development Entry, Acceptance Preconditions, and Final Launch Gates

**Development entry is sufficient for planning/implementation**: baseline `3969258` contains Phase 1/2 code and focused baseline 163 passed / 5 skipped. Phase 0/1 formal acceptance is incomplete; Phase 2 is conditionally passed with production performance, CI/real deployment, human UAT/sign-off, and durable-evidence gaps. Never claim all upstream phases are formally accepted.

| Environment | Purpose |
|---|---|
| Production-like React + controlled model/tools | Functional, real configuration/performance, and Summary/Memory regression |
| Independent pgvector PostgreSQL + LocalTestAdapter | Capabilities, Adapter.start barrier, failure/cancel/timeout, cross-tenant, migration |
| Quickstart dual containers (demo model) | Post-acceptance seed wiring, default off, on, and rollback verification (**not executed in this phase; deferred to issue #128**, see §6 and 08 R-39) |
| Disposable populated database copy | Online migration, concurrency, old-binary rollback, and downgrade |
| Frontend acceptance build + existing Playwright | Engine configuration, read-only preview, four locales, M1–M3 equivalent evidence |

**Before A/C acceptance**: T2–T9 complete; actual `06-test-report.md/.en.md` exists with all P3-UT/IT/CM passed; no P0/P1; target-SHA full CI available; migration chain dynamically revalidated; at least two dedicated tenants/independent scopes; evidence sensitive-scanned. C11 has at least 100 valid paired samples meeting the target; missing environment remains `pending_env` and cannot pass.

**Final launch gates**: A1–A11 and C1–C11 pass, with M1–M3 complete or equivalent automated evidence. Upstream real-history samples, CI/real deployment, production performance, and human-acceptance gaps affecting this phase's commitments must close or explicitly block the corresponding launch scope. Merged code substitutes for none of these; conditional passage cannot override a veto or C11.

## 3. Functional Acceptance (A1–A11)

| # | Criterion | Steps | Pass standard | Trace |
|---|---|---|---|---|
| A1 | AC-1 | Import valid legacy fixtures, read/run React, then save/publish normally | Correct default triple; zero model/tool/Summary/Memory diff; no read UPDATE or default diff noise | FR-1; G1; US-1 |
| A2 | AC-2 | Save valid React and submit unknown triple/latest/type/extra/unequal aliases | Valid exact resolution; 100% stable invalid rejection; zero factory/Adapter calls during metadata validation | FR-2; G1; US-2 |
| A3 | AC-3 | Simulate missing/incompatible deployment, cold/stale probe, timeout, and missing Workspace | Cold/stale unavailable until background success; Available never exceeds Declared; required capabilities block; `policy_revision` is read from the trusted policy source rather than supplied by the caller (R-17), and all six R-18 settings values have real composition consumers (no hardcoded constants); **evidence boundary (R-42/R-43)**: missing-deployment/incompatible-version/probe-timeout are structurally unreachable in this phase's production implementation and provable only through injected probe/policy doubles, while the production implementation must make cold→one bounded awaited warm→available observable plus the instance-versus-registered declaration divergence (compared after `resolve` and before prepare, with React start always 0) | FR-3; G2; US-2, US-3 |
| A4 | AC-4 | Deny one capability at each layer and allow below | Effective remains denied; snapshots explain each source/version/reason; configurations narrowed only by policy layers remain startable (required-capability missing excludes policy denial; see R-16); production observability (R-44): the Phase 3 platform ceiling is a code-constant allow-list and the seven denied names are declared=false, so they short-circuit as `not_declared`, hence `platform_denied` is observable only through a test-registered Engine (reachable in production once Phase 4/5 registers an engine declaring terminal_execution); the tenant/execution layers genuinely have no source this phase and are registered honestly as a completeness gap rather than a defect | FR-4; G2; US-3 |
| A5 | AC-5 | Forge layered fields via raw HTTP and cross tenant/scope preview | Zero elevation/cross-scope; besides 422/domain errors, security audit exists without body/values/secrets; preview creates no Run; preview triples match the same-scope resolver output byte-for-byte with no reason-code loss (R-21) | FR-5; G2; US-3 |
| A6 | AC-6 | Inspect four terminal-state snapshots; inject excess size, nested secrets, and DB failure | Five snapshots commit once before Adapter.start and remain immutable; failures mean start=0; public `run.started` order unchanged; historical NULL/public allowlists correct; a classified barrier failure never terminates as `execution_error` (serialization/denylist/missing-item/oversize/`audit_conflict` yield `execution_configuration_invalid`, lost lease and unclaimed rows yield the existing `worker_lost`) | FR-6; G4; US-5 |
| A7 | AC-7 | Replay empty, Summary, Memory, combined, disabled, and truncation cases | Zero React order/text/budget/log/write-back diff; no duplicate/empty messages | FR-7; G3; US-4 |
| A8 | AC-8 | Give the same InstructionInput to React/test Providers | Independent native formats, one business-rendering pass, no ReAct conversion or Provider fallback | FR-7; G3; US-4 |
| A9 | AC-9 | Edit/preview unsaved draft, change policy, and switch four locales | Effective read-only/recomputed, disabled only narrows, four locales complete, no internal snapshots/elevation, preview grants no Run | FR-4, FR-5, FR-8; G1, G2; US-1, US-3 |
| A10 | AC-10 | Exercise both flags, cached Runtime off→on/on→off, non-React, history, and application rollback | Off preserves original Phase 2 paths; on+orchestrator-off fails closed with `runtime.for_run` call counts always 0; non-React fails explicitly; claimed-row path fixed; history readable without downgrade; `execution_phase3_enabled` and the `execution_capability_*`/`execution_snapshot_max_bytes` family stay out of the fingerprint (flipping the switch or tuning a parameter never makes an already-queued Run report `configuration_changed`, R-48); the misconfigured process still boots and `GET /agents/execution-config-flags` answers normally in that state (R-50) | FR-8, FR-9; G4; US-6 |
| A11 | AC-11 | Dynamically verify migration chain, upgrade populated copy/concurrently access, and downgrade disposable DB | `0058_agent_execution_metadata` currently follows `0057_industry_pack_runtime`; only five nullable columns, old rows NULL, no historical migration edits | FR-6; G1, G4; US-5, US-6 |

Record executor, date, environment, target SHA, fixtures, operations, expected/actual, verdict, and evidence links for every item. Reuse 06 UT/IT/CM, CI, PG, and Playwright raw results rather than repeating manual suites; merge, skip, and `pending_env` are not passes.

## 4. Few Critical Manual Checks

Only supplement actual UI/rollback checks not fully covered by automation. Record executor, SHA, result, and evidence; create no separate UAT round.

| # | Check | Pass standard |
|---|---|---|
| M1 | Open an old Agent and new Engine configuration | Old Agent has no forced fields/default dirty/republication prompt; shared, React, and read-only Effective areas are clear |
| M2 | Submit unknown/conflicting configuration and inspect preview | Errors are locatable in four locales; unsupported, environment-unavailable, and policy-denied are distinct; declaration is not authorization |
| M3 | Roll back the application and inspect UI | Phase 3 editing entries disable/hide as specified—the UI hides declaratively from `GET /agents/execution-config-flags` (03 §7.4), removing the preview entry and `disabled_capabilities` narrowing rather than inferring by click-to-error; `phase3=on + orchestrator=off` shows a misconfiguration hint without fake success; React model/round editing and historical publication/Run viewing stay outside flag gating; historical publications/Runs remain readable without internal-snapshot disclosure |

## 5. Security, Data, and Release Hard Gates

| # | Check | Verdict | Trace |
|---|---|---|---|
| C1 | Client, UI, and Adapter declarations cannot grant Effective; forged matrix has zero elevation | Veto | AC-3–AC-5; G2; FR-3–FR-5 |
| C2 | Policy is trusted/versioned; lower layers cannot restore denial; no automatic Engine fallback; the revision/version authority is the provider itself, and `execution_capability_policy_version` matches both the registered descriptor and the provider echo (R-17/R-20); the platform ceiling and the tenant/agent/execution values come from code constants and published configuration rather than from the caller (R-44), and `current_revision` is a per-scope constant that is monotonic within a scope, with clock- or DB-derived per-round advancement forbidden | Veto | AC-4, AC-10; G2; FR-4, FR-8 |
| C3 | Snapshots, logs, events, audit, and public APIs contain no body/Token/Key/raw Memory/host secrets | Veto | AC-5, AC-6; G4; FR-5, FR-6 |
| C4 | Tenant and business/workspace scope cover configuration, preview, policy, snapshots, and audit | Veto | AC-5; G2; FR-5 |
| C5 | Five snapshots commit once before Adapter.start and remain immutable; public event order unchanged; historical NULL not backfilled; a classified barrier failure never terminates as `execution_error` (the explicit R-50/R-51 classification may not be degraded by the broad `except Exception`) | Required | AC-6; G4; FR-6 |
| C6 | React reuses existing Summary/Memory rendering/switches with zero baseline diff | Required | AC-7; G3; FR-7 |
| C7 | No bulk old-JSONB rewrite/default diff noise; invalid config cannot publish; unregistered Engines unavailable | Required | AC-1, AC-2; G1; FR-1, FR-2 |
| C8 | Four locales complete; Effective read-only; preview exposes no internal snapshots or Run authorization | Required | AC-9; G1, G2; FR-8 |
| C9 | Flag/application rollback succeeds without downgrade; non-React never silently degrades (`runtime.for_run` call counts stay 0 under on+orchestrator-off); the Run side reuses only the four existing public codes execution_phase3_disabled/execution_configuration_invalid/execution_engine_unavailable/execution_policy_unavailable, adds no untranslated code, and lost-lease/non-running rows follow the existing `worker_lost` path and must never degrade to `execution_error` | Veto | AC-10; G4; FR-8, FR-9 |
| C10 | Migration dynamically revalidated, five columns only, no historical edits, no Phase 4/5/6 scope leakage | Required | AC-11; G1, G4; FR-6 |
| C11 | Real resolver/admission paired baseline, warmed/discarded warmups, same environment/load, at least 100 valid interleaved paired samples with raw data, p95 delta ≤50ms, external model excluded | Required; insufficient/unmeasured=`not_measured` or `pending_env`, never pass | G1; performance success metric |

## 6. Conclusions and Post-Acceptance Work

- **Pass**: A1–A11 and C1–C11 all pass; M1–M3 complete/equivalent; no P0/P1; rollback evidence complete; no final-launch blockers.
- **Conditional pass**: only non-hard-gate P2/P3 items unrelated to security, compatibility, snapshots, C11, or rollback, each with owner/deadline and acceptance-owner explanation; never for veto items.
- **Fail**: any AC/hard gate fails, missing real baseline prevents a compatibility verdict, elevation/cross-scope/disclosure/silent non-React degradation occurs, or C11 lacks valid measurements.

Only after actual acceptance create bilingual `07-acceptance-report.md/.en.md`, containing A/C evidence, raw C11 measurements, M checks, migration/rollback, open items, and this single record.

| Acceptance owner | Executor | Date | Target SHA | Conclusion | Evidence/open items |
|---|---|---|---|---|---|
| Fill during acceptance | Fill during acceptance (may be same person) | Fill during acceptance | Fill during acceptance | Pending acceptance | Fill during acceptance |

**Seed/quickstart strictly after real 06/07 (not executed in this phase, see below)**: first add an independent low-sensitivity, deterministic-ID, create-or-preserve idempotent Phase 3 example seed without fabricated execution snapshots. Then separately wire fresh quickstart to run it automatically and verify default off/on/rollback and real Run snapshots. Finally append this evidence only to existing 06/07; create no reports early and never auto-insert examples in production.

**Phase scope change (2026-11-13, 08 R-39)**: the maintainer decided to deliver the functional core first, so the seed and quickstart wiring above are **not executed in this phase** and move to separate low-priority iterations—issue **#127** (example seed) and **#128** (fresh-quickstart wiring with off/on/rollback verification, depending on #127). This phase's acceptance scope therefore narrows to the parts of A1–A11, C1–C11 and M1–M3 that **do not depend on seed/quickstart evidence**; the expectation that "the next quickstart ships Phase 3 example data" is not accepted in this phase, and 07 must record it honestly as **deferred (#127/#128) with its evidence gap**, never as complete, and never substituted by "the code is merged". The ordering is unchanged: #127/#128 still follow the real 06/07.
