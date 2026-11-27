# Phase 2 · Skill Authoring, Testing, and Release — Acceptance Plan

> Status: Acceptance plan frozen; implementation in progress; acceptance not yet performed.
> Created: 2026-11-27
> Basis: `01-business-goals.md` (G1–G4), `02-requirements.md` (AC-1–AC-12), `00-ui-interaction-freeze.md` (U1–U13), and `04-test-plan.md` (P2-UT/IT/CM cases).
> Revision: 2026-11-27 — acceptance is limited to functional correctness, safety, isolation, data integrity, migration, permissions, safe defaults, and existing-path regression. Performance, capacity, latency percentiles, paired/large samples, CI provenance/double-run, and real-history samples are outside this phase's acceptance gate.

## 1. Scope and Responsibility

Confirm that the Phase 2 delivery implements the frozen Skill authoring, testing, and release interaction contract, that every AC is reproducible with direct evidence, and that the applicable safety and data hard gates pass. The result must be traceable to a target SHA and must not rely on a static success state, fixture data, or an optimistic client mutation.

Acceptance uses the minimum core-team standard: there is one **acceptance owner**, who may execute the checks and issue the single conclusion. If assistance is needed, one executor may be named; the executor may be the same person as the acceptance owner. No product/QA/engineering/security/SRE/business role matrix, independent UAT round, or multi-role signature table is created. Developer self-verification is evidence only for the written requirements and is not represented as independent user or business acceptance.

**Phase acceptance is not high-risk capability enablement.** Passing Phase 2 confirms that the implementation is correct and safe with AI-assisted generation and live read-tool tests defaulted off. Enabling those capabilities in a real deployment, or any future live write-action execution, requires a separate approval record bound to target SHA, tenant scope, rollout batch, evidence, and revocation conditions. A missing enablement approval does not make phase acceptance fail, but the corresponding switch must remain `false`.

Acceptance reuses `06-test-report.md`, CI, PostgreSQL, browser automation, and direct operational evidence. It does not repeat the full automated suite merely to populate the acceptance table. Missing, skipped, or environment-blocked evidence is recorded as `pending_env` with the required environment and follow-up owner; it is never converted to pass.

## 2. Environment and Prerequisites

| Environment | Purpose |
|---|---|
| PostgreSQL-backed integration environment | Migration, scope isolation, revision conflicts, test persistence, publish/rollback atomicity, permissions, audit privacy |
| Backend test runtime with deterministic mock model/tool adapters | AI draft generation off/on, live read-tool off/on, blocked write test, timeout/error classification |
| Frontend acceptance build with Playwright API mocks | Six detail tabs, creation handoff, shared editor, test workbench, readiness, publish/rollback, async and permission states |
| Local browser against the acceptance build | Visual hierarchy, keyboard behavior, responsive widths, and four-locale spot checks that cannot be fully established from assertions alone |

**Entry prerequisites**

- The implementation and `08-implementation-breakdown.md` (if used) identify a target SHA and all files changed.
- All applicable P2-UT, P2-IT, and P2-CM cases in `04-test-plan.md` have been executed and reported in `06-test-report.md`; no P0 or P1 defect remains open.
- The dynamic migration graph has one head: `0076_skill_library` descends from `0075_gateway_allowed_hosts`.
- Acceptance uses dedicated tenants such as `skill-test-a` and `skill-test-b`; production customer data and real write-effect tools are excluded.
- AI generation and live read-tool tests are defaulted off. Any controlled on-state evidence uses mock profiles/tools and does not create an external mutation.
- The evidence set has been checked for Secrets, raw prompts, customer content, credentials, and model/tool tokens before being linked.

If an integration or browser environment is unavailable, the affected hard gate is recorded as `pending_env` with the missing environment and responsible follow-up. Performance, capacity, CI provenance, and historical-sample evidence are not prerequisites and must not be written as environment blockers.

## 3. Functional Acceptance (AC-1–AC-12)

Each A item maps one-to-one to the corresponding AC. The evidence source column identifies reusable automated or operational evidence; the final acceptance report must record the actual command/test node, environment, target SHA, result, and evidence link rather than copying this plan's expectation as a result.

| # | AC | Acceptance steps | Pass criteria | Evidence source | Trace |
|---|---|---|---|---|---|
| A1 | AC-1 | Open `/skills/create`; confirm default-off AI behavior when no profile is configured; then, in a controlled mock on-state, exercise AI with no prompt and a valid prompt; exercise template with zero/two selections and exactly one; exercise professional mode. Follow each successful path into the editor and inspect the mode label. | Default-off AI fails closed with a concrete reason and creates no draft while template/professional remain usable; in controlled mock on-state AI blocks until a prompt exists and then creates a draft; template blocks unless exactly one template is selected; professional opens directly; every successful mode reaches the same shared editor with an accurate mode label. No mode creates a draft on card click alone or leaves a static success screen. | P2-UT-01–04, P2-IT-02–04, P2-CM-04, creation-mode UI scenario; direct API/database read to confirm one draft row | FR-2; US-1; G1; U1–U4 |
| A2 | AC-2 | Reach Basic, Capability, Parameters, Dependencies, and Runtime/Safety; edit each; submit missing/wrong/duplicate values and then valid values; inspect inline errors and generated input/output schema summaries. | All five sections are reachable and editable; required fields and cross-field rules identify the exact field; parameters can be added, removed, and reordered; valid JSON output schema and dependency selections are accepted; no invalid definition can be saved. | P2-UT-05–10, P2-IT-09, editor UI scenario; API validation evidence | FR-3; US-1, US-2; G1 |
| A3 | AC-3 | Load a clean draft, change fields, leave and return; save with the current revision; save with a stale revision; inspect success, dirty-navigation, conflict, and reload behavior. | Dirty navigation prompts and does not silently discard; Save shows in-flight state rather than a local success; a confirmed save increments the revision exactly once and persisted values reload; a stale revision returns `skill_revision_conflict` without overwrite and offers reload or duplicate. | P2-UT-26, P2-IT-07–08, dirty-editor UI scenario; database row before/after | FR-4; US-2; G4; U5–U6 |
| A4 | AC-4 | Open a published Skill, record its current immutable version, edit the draft, save a new revision, and return to the detail/version surface. | The live version and its snapshot remain unchanged; the draft receives a new revision label; `has_unpublished_changes` is accurate; the UI visually separates draft revision from current published version. | P2-IT-10, P2-IT-14, P2-CM-10, published-edit UI scenario; version row digest comparison | FR-4; US-2; G3, G4 |
| A5 | AC-5 | Open Test Records for a saved draft; observe empty state; enter empty, invalid, and valid inputs; start a valid run and attempt a duplicate submission while it is in flight. | Empty state guides the first run; invalid input is blocked before execution; valid input enters Running with elapsed/progress state and Run disabled; no duplicate request is sent; only the backend result can end Running. | P2-UT-11, P2-IT-11–13, test-workbench UI scenario; network-request count | FR-5; US-3; G2; U7 |
| A6 | AC-6 | Run a passing case, a failed-contract case, an infrastructure/error case, and a blocked write/live-tool case; inspect result panes and history after each. | Passed, Failed, Error, and Blocked are distinguishable using backend status and reason; input is preserved for retry; output/duration/diagnostics are safe; every completed run appends to reverse-chronological history against the exact draft revision. | P2-UT-12–15, P2-IT-11–12, P2-CM-13, test-workbench UI scenario; persisted run rows | FR-5, FR-6; US-3; G2, G4; U7 |
| A7 | AC-7 | Obtain a passing test for saved draft rN, make a local edit, save rN+1, then open readiness. Also construct a newer failed/error run for rN+1. | The prior pass becomes Stale immediately on edit and remains stale after save; readiness reports the current revision, not an older pass; publish is blocked and points to Test Records; a latest failed/error run cannot be overridden by an older pass. | P2-UT-17–18, P2-IT-14, P2-IT-15, readiness UI scenario | FR-6, FR-7; US-4; G3, G4; U8–U9 |
| A8 | AC-8 | Open Version Management for an unprepared draft; inspect each failed/warning check; resolve missing fields, rerun the test, resolve dependencies, and refresh readiness; force a client-green/readiness race and confirm server enforcement. | Every blocker names its stable code, reason, and relevant destination; publish becomes enabled only after all mandatory checks pass; server-side readiness wins over stale/green client state; no client can force publish past blockers. | P2-UT-16–19, P2-IT-15, P2-IT-20, P2-IT-23, readiness UI scenario and server 409 evidence | FR-7; US-4; G3, G4; U9 |
| A9 | AC-9 | Open Publish for a ready draft; try missing release notes and every bump choice; confirm; inspect version history and current marker; simulate failure and retry. | Confirmation is required; validation blocks incomplete metadata; success creates one immutable current version with correct semver, monotonic sequence, digest, test evidence, author, and notes; failed publish creates no version and preserves dialog input; current marker updates only after confirmation. | P2-UT-20–22, P2-IT-16–18, P2-CM-10, publish UI scenario; version table and audit query | FR-8; US-4; G3, G4; U10 |
| A10 | AC-10 | Select an older historical version, enter required rollback notes, confirm, and compare both versions and the current pointer before/after. | A new higher version is created by copying the target snapshot byte-for-byte, `rollback_from` records the target, current marker moves to the new version, and the target/other history rows are unchanged. Dependency failure leaves the current pointer unchanged. | P2-UT-23, P2-IT-19–20, rollback UI scenario; digest/lineage and current-pointer evidence | FR-8; US-4; G3, G4; U11–U12 |
| A11 | AC-11 | Exercise catalog/detail/editor/test/readiness/versions under loading, empty, network-error, not-found/cross-scope, and insufficient-permission conditions. Inspect analytics for the absence of runtime data. | Each surface shows a truthful skeleton, empty, retryable error, not-found, or read-only/disabled state; failed loads preserve unsaved edits and active results where specified; in-scope actions do not end with a "later phase" placeholder; Runtime Analytics has an honest empty state and no fabricated metrics. | P2-UT-24, P2-UT-26, P2-IT-06, P2-IT-21–24, P2-CM-07, P2-CM-13, async/permission UI scenarios | FR-9, FR-10; US-5; G4; U13 |
| A12 | AC-12 | Inspect 1672×941, 1024×768, and 390×844; confirm the existing 228px sidebar/header behavior and route selection; operate tabs, dialogs, forms, and icon actions by keyboard; switch through `en`, `hi`, `zh-CN`, and `zh-TW`. | No document-level horizontal overflow; the shared console shell and other tab selection remain unchanged; Skill pages use the established blue/white visual language; test panes stack where required; tab/dialog/form keyboard behavior and accessible names work; all new copy is present and usable in all four locales. | P2-CM-07–09, P2-CM-11–12, shell/locale UI scenario; browser screenshots and `check:i18n`/build output | FR-10; US-5; G1 |

### 3.1 Evidence recording rules

- Automated evidence must name the test/build command, test node or UI scenario, environment, target SHA, timestamp, and result. A screenshot alone is insufficient for a persistence or permission claim when a database/API assertion is available.
- A/C judgments must cite `06-test-report.md` or a direct operational artifact. The acceptance plan's expected result is not evidence of execution.
- A UI success toast is insufficient evidence of create/save/test/publish/rollback. The corresponding persisted row, revision, version, pointer, or stable server error must be observed.
- If a required environment is absent, the A or C row remains `pending_env`; the final report must state what remains unproven and who will rerun it. Do not mark the row "conditionally passed" merely because automated tests cover a nearby path.

## 4. Key Manual Checks

Manual checks are limited to judgments not fully established by automated assertions. They are linked to A/AC and do not create an independent UAT round.

| # | Check | Pass criteria | Link |
|---|---|---|---|
| M1 | Open the catalog, creation wizard, editor, and detail at 1672×941 after using other console tabs. | Skill pages visibly retain the same 228px business sidebar, active selection, header, breadcrumb, and blue/white hierarchy; no Skill-specific sidebar or divergent shell appears. | A12 / AC-12 |
| M2 | In the acceptance browser, inspect each Skill async surface with mocked loading, empty, network-error, and viewer-permission responses. | States are visually and semantically distinct; actions show a concrete disabled reason; no fixture card, fixed test result, fixed version, or fabricated analytics remains; an active test result is not erased by a history-load error. | A11 / AC-11; A5–A6 / AC-5–AC-6 |
| M3 | Spot-check the four locales on the editor, test result, readiness, publish, and rollback dialogs at 390px and desktop width. | Required labels, blockers, reason codes, buttons, validation, and confirmation copy are translated and do not truncate critical actions; pass/fail/stale/permission meaning does not rely on colour alone. | A12 / AC-12; A9–A10 / AC-9–AC-10 |

If automation fully covers an item, the manual check may cite that automation and record only the residual visual or accessibility judgment; it must not be duplicated as an independent acceptance pass.

## 5. Safety, Data, and Release Hard Gates

Only hard gates applicable to this phase are listed. Each is all-or-nothing and reuses automated, database, audit, or browser evidence rather than repeating the full test suite.

| # | Check | Pass criteria and evidence source | Trace |
|---|---|---|---|
| C1 | Additive/online migration | `0076_skill_library` is the single new head descending from `0075_gateway_allowed_hosts`; fresh and existing-schema upgrades create the three new tables/constraints/indexes without altering, backfilling, or dropping application Skill, application version, Agent, channel, or runtime tables. A populated-table downgrade refuses destructive loss and requires export/cleanup; an empty-table downgrade succeeds. Evidence: P2-IT-01, P2-CM-01–03, dynamic Alembic/DB output. | AC-12; FR-1; G4 |
| C2 | Tenant/business/workspace isolation | Every catalog, detail, draft, test, version, readiness, duplicate, and rollback read/write is bound to trusted scope predicates. A second tenant/workspace cannot see or mutate another scope's Skill, version, run, or metadata; cross-scope identifiers return the stable not-found path without confirming existence. Evidence: P2-IT-06, P2-IT-23, P2-CM-05, negative API/database probes. | AC-11; FR-9; NFR multi-tenancy |
| C3 | Secret and audit privacy | Test outputs, diagnostics, logs, audit records, and public API responses contain no Secret, raw customer content, full model prompt, credential, token, or endpoint secret. Audit records contain only the approved revision/version/reason/digest/test-summary fields. Scoped test input is retained only for the test history/retry contract and is not emitted as public diagnostic or audit content. Evidence: P2-IT-12, P2-IT-22, direct response/audit/log scan. | AC-6, AC-11; FR-5, FR-9; G4 |
| C4 | Draft, test, and publish data integrity | Draft saves are revision-checked and atomic; one successful save increments exactly once; invalid/stale saves do not update stored content; test evidence is persisted only against the exact saved revision, completed outcomes are truthful, and duplicate request IDs create at most one run; publish rechecks readiness under the same lock, creates no version/pointer change on failure, and concurrent publishes never create two versions for one intent. Evidence: P2-UT-16–19, P2-IT-07–15, P2-IT-17–18, P2-CM-04, DB assertions. | AC-3–AC-9; FR-4–FR-8; G4 |
| C5 | Immutable versions and rollback lineage | Published version rows are never updated or deleted; a publish copies the validated draft snapshot with a stable digest; rollback inserts a new higher version from the selected historical definition, records `rollback_from`, and leaves the target and all prior rows unchanged; the current pointer changes only after the insert succeeds. Evidence: P2-UT-20–23, P2-IT-10, P2-IT-17–20, digest and row-lineage comparison. | AC-4, AC-9, AC-10; FR-4, FR-8; G3 |
| C6 | Permission enforcement | The server enforces `skill.read`, `skill.manage`, `skill.test`, and `skill.publish` independently of UI visibility: viewer reads only, operator reads/tests but cannot manage or publish, admin can perform all mapped actions. Permission denial returns a stable error and does not disclose cross-scope data; disabled UI controls are not the only control. Evidence: P2-UT-24, P2-IT-21, P2-CM-06, direct API permission matrix. | AC-11; FR-9; NFR multi-tenancy |
| C7 | Safe defaults and blocked write execution | `skill_ai_generation_enabled` and `skill_live_tool_tests_enabled` default `false`; missing AI profile fails closed with `skill_ai_generation_unavailable` without creating a draft; live tool off returns `blocked` without an outbound call; write-action tests are always `blocked/skill_write_test_unsafe` and emit no external mutation in this phase. Controlled on-state tests use mocks only. Enabling live capabilities requires the separate approval described in §1. Evidence: P2-UT-14–15, P2-IT-03, P2-CM-04, outbound-call/mutation assertions. | AC-1, AC-6, AC-11; FR-2, FR-5, FR-9; G4 |
| C8 | Existing-path regression and shell compatibility | The 228px business sidebar, route selection, mobile collapse, catalog/detail headers, and all other console tabs remain consistent; existing service-application Skill and application publish/version/rollback paths remain green; no global Skill change mutates Agent, channel, runtime, or application ownership semantics. Evidence: P2-CM-08–09, P2-CM-14, affected Playwright/pytest regression results and shell screenshots. | AC-12; FR-1, FR-10; compatibility NFR; G1 |

**Explicitly outside the acceptance gate**

- Performance, response-time budgets, capacity, p50/p95, C11-style latency, paired samples, sample counts, large histories, and real-history datasets.
- CI provenance, final-PR-head double runs, CI run URLs, and deployment pipeline evidence as pass conditions. CI results may be cited as supporting history but do not determine the phase conclusion.
- Marketplace publishing, scheduled execution, batch evaluation, automatic scoring, A/B testing, gradual rollout, cross-tenant sharing, category administration, and live write-action enablement.
- A multi-role UAT round, business-signoff table, or independent signature workflow.

## 6. Pass Standard and Single Acceptance Record

- **Pass**: every applicable A1–A12 and C1–C8 has direct evidence and passes; no P0/P1 remains open; the evidence is bound to the recorded target SHA.
- **Conditional pass**: only non-hard-gate P2/P3 residuals remain, each has an owner and due date, and the acceptance owner records the residual in the single acceptance record. A safety, isolation, privacy, migration, data-integrity, immutable-version, permission, safe-default, or existing-path regression gap cannot be waived.
- **Fail**: any applicable AC or hard gate fails, or `pending_env`/skip/`not_measured` is written as a pass. Repair and rerun the affected item plus its related regression scope.
- **Release note**: Phase 2 acceptance does not authorize enabling AI-assisted generation, live tool tests, or future write execution in production. Those remain independently approved and defaulted off.

The acceptance report (`07-acceptance-report.md`) is created only after acceptance is actually performed. It records the scope and target SHA, A/C outcomes and evidence links, residuals, the conclusion, and the following single acceptance record:

| Acceptance owner | Executor | Date | Target SHA | Conclusion | Evidence / residuals |
|---|---|---|---|---|---|
| Pending | Pending (may be the acceptance owner) | Pending | Pending | Pending acceptance | Pending |
