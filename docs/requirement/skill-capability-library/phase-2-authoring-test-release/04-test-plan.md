# Phase 2 · Skill Authoring, Testing, and Release — Test Plan

> Status: Test plan frozen; implementation complete; verification executed on 2026-11-27 (see `06-test-report.md`); acceptance pending.
> Created: 2026-11-27
> Basis: `02-requirements.md` (FR-1–FR-10, AC-1–AC-12), `00-ui-interaction-freeze.md` (U1–U13), and `03-technical-design.md` (global Skill domain, revision/test/release state machines).
> Revision: 2026-11-27 — performance, capacity, p50/p95/C11 latency, paired samples, CI provenance/double-run, real-history samples, and large-sample requirements are explicitly outside this phase's exit gate.

## 1. Scope and Principles

**Scope**

- `0076_skill_library` migration and the new `skill_library` backend domain.
- Tenant/business/workspace-scoped Skill catalog, draft, test, readiness, version, publish, and rollback APIs.
- API-backed Skill catalog, creation wizard, shared editor, two-pane test workbench, and release/version UI.
- Removal of in-scope static success paths, fixture test results, fixture version history, and fake analytics.
- Permission, empty/loading/error states, four locales, responsive layout, and keyboard accessibility.

**Principles**

1. **No fake success:** every mutation assertion proves persistence or a stable server error; no test may accept a toast alone.
2. **Revision-bound evidence:** any pass that is not tied to the exact saved draft revision is a failure.
3. **Atomicity first:** draft conflicts, publish, and rollback are tested for rollback of partial state.
4. **Isolation always:** every integration path includes a negative cross-tenant/workspace case.
5. **Switch completeness:** AI generation and live read-tool tests are tested with their off and controlled on states; write-action tests must always be blocked with no outbound mutation.
6. **No time sleeping:** revisions, stale timestamps, expired processing states, and version sequences are constructed directly in test fixtures.
7. **Empty is valid:** an empty catalog or analytics surface must be a truthful state, never replaced with fixtures to make a test green.
8. **Performance/CI/history samples are not gates:** these are outside the phase exit criteria and may be recorded only as optional context.

## 2. Environment and Data

| Environment | Purpose |
|---|---|
| Backend unit (`pytest`) | Pure validation, state-machine, semver, readiness, and error classification logic |
| Backend integration (PostgreSQL + pytest postgres fixture) | Migration, row locks, revision conflicts, test persistence, publish/rollback atomicity, scope isolation |
| Mock model/tool endpoints | Deterministic instruction, retrieval, query, error, timeout, and invalid-output responses |
| Frontend Playwright with `page.route` mocks | Loading/empty/error/permission, conflict, stale, publish/rollback, responsive, locale, and keyboard states |
| Frontend Playwright against local backend smoke path | Route and shell compatibility only; deterministic API mocks remain the primary UI test contract |

**Data construction**

- Use tenant `skill-test-a` and second tenant `skill-test-b`; never reuse production customer data.
- Create draft rows with explicit `draft_revision` and version rows with explicit sequence values.
- Construct stale-test states by changing `draft_revision` directly or by calling Save Draft; do not wait for clocks.
- Mock model/tool failures through fixed reason codes; do not depend on external network availability.
- Use no real write-effect external call. Write-action cases must assert a `blocked` result and absence of an outbound mutation.

## 3. Unit Tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P2-UT-01 | Create AI mode without prompt | Validation rejects with `skill_prompt_required`; no draft service call | FR-2, AC-1 |
| P2-UT-02 | Create template mode with zero or two templates | Exactly one template is required; server rejects both invalid shapes | FR-2, AC-1 |
| P2-UT-03 | Create professional mode with empty defaults | Valid draft skeleton is produced; mandatory fields remain publish-blocking | FR-2, FR-3, AC-1 |
| P2-UT-04 | Generate stable Skill key from a name | Key satisfies the route regex and collision suffix is deterministic | FR-1, FR-2 |
| P2-UT-05 | Validate Basic fields | Name/description/category/tags/visibility accept valid values and reject boundary violations | FR-3, AC-2 |
| P2-UT-06 | Validate parameter rows | Blank/duplicate names, wrong default types, and unsupported types are rejected | FR-3, AC-2 |
| P2-UT-07 | Generate input schema from ordered parameters | Schema order/properties/required arrays are deterministic and preserve reorder intent | FR-3, AC-2 |
| P2-UT-08 | Validate JSON output schema | Invalid Draft 2020-12 schema is rejected; valid closed object schema is accepted | FR-3, FR-5, AC-2 |
| P2-UT-09 | Validate cross-field Skill types | Instruction needs instructions/profile; Knowledge needs KB; Query needs read tool; Action needs write tool/confirmation; Handoff needs queue | FR-3, FR-7, AC-2 |
| P2-UT-10 | Validate runtime bounds | Timeout 1–60 accepted; retries/error/idempotency enums reject unknown values | FR-3, AC-2 |
| P2-UT-11 | Validate test input | Missing required, wrong type, unknown extra property, and valid payload are classified correctly | FR-5, AC-5 |
| P2-UT-12 | Classify model schema mismatch | Valid transport + invalid output maps to `failed`, never `passed` | FR-5, FR-6, AC-6 |
| P2-UT-13 | Classify model/tool transport errors | Timeout/unavailable credentials/backend failure map to `error` with stable reason state | FR-5, FR-9, AC-6 |
| P2-UT-14 | Block write-action live test | Write effect returns `blocked/skill_write_test_unsafe` and emits no tool call | FR-5, FR-5 failure, AC-6 |
| P2-UT-15 | Evaluate live-tool switch | Disabled switch blocks query live test; enabled switch permits mock read call and validates output | FR-5, FR-9, AC-6 |
| P2-UT-16 | Build readiness with all checks passing | `ready=true`; all mandatory check codes are `pass` | FR-7, AC-8 |
| P2-UT-17 | Build readiness with a stale test | Latest test revision differs from saved draft revision → `latest_test_passed=fail` | FR-6, FR-7, AC-7, AC-8 |
| P2-UT-18 | Build readiness with latest failed/error test | A prior pass on the same revision cannot override the latest failed/error run | FR-6, FR-7, AC-7, AC-8 |
| P2-UT-19 | Build readiness with unavailable dependency | Missing/disabled model, KB, tool, collection, or queue names the exact failed check/destination | FR-7, FR-9, AC-8 |
| P2-UT-20 | Calculate semver bumps | Initial release is `1.0.0`; major/minor/patch produce the expected next semver | FR-8, AC-9 |
| P2-UT-21 | Calculate next monotonic version | `max(version)+1` is used for publish and rollback regardless of semver | FR-8, AC-9, AC-10 |
| P2-UT-22 | Canonicalize immutable definition | Key ordering/whitespace produce one stable sha256 digest; content change changes digest | FR-8, AC-9 |
| P2-UT-23 | Validate rollback target | Current version and unknown version are rejected; older target accepted | FR-8, AC-10 |
| P2-UT-24 | Permission mapping | Admin gets read/manage/test/publish; operator read/test; viewer read | FR-9, FR-10, AC-11 |
| P2-UT-25 | AI generation schema guard | Generated Secrets/roles/endpoint escalation fields are rejected or normalized out | FR-2, FR-3, AC-1 |
| P2-UT-26 | Map server error codes to UI copy | Every stable code in `03` has a localized reason and no raw exception fallback | FR-9, FR-10, AC-11 |

## 4. Integration Tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P2-IT-01 | Upgrade fresh DB to `0076_skill_library` | Three tables/constraints/indexes exist; Alembic remains single-head | FR-1, AC-12 |
| P2-IT-02 | AI draft creation with configured mock model | Exactly one persisted draft; mode/key/revision returned; no static catalog mutation | FR-2, G4, AC-1 |
| P2-IT-03 | AI draft creation with AI disabled/no profile | 503 `skill_ai_generation_unavailable`; no row inserted; template/professional still create | FR-2, FR-9, AC-1, AC-11 |
| P2-IT-04 | Template and professional draft creation | Template applies defaults; professional creates blank defaults; both reach same saved-draft shape | FR-2, AC-1 |
| P2-IT-05 | Catalog reads persisted rows | Search/category/status/pagination return only rows in trusted scope; no fixture cards | FR-1, FR-4, AC-2 |
| P2-IT-06 | Catalog mixed tenant/workspace probe | Second-scope Skill key is absent/404; no metadata disclosure | NFR multi-tenancy, AC-11 |
| P2-IT-07 | Save Draft revision success | Revision increments exactly once; fields persist; response includes `has_unpublished_changes` | FR-4, AC-3, AC-4 |
| P2-IT-08 | Save Draft stale revision | 409 `skill_revision_conflict`; no update occurs; current revision returned safely | FR-4, AC-3 |
| P2-IT-09 | Save invalid definition | 422 with field/check details; stored prior revision remains unchanged | FR-3, FR-4, AC-2, AC-3 |
| P2-IT-10 | Publish own draft does not mutate live version | Published row is stored; `skills.published_version/published_revision` updates; immutable snapshot matches validated draft | FR-4, FR-8, AC-4, AC-9 |
| P2-IT-11 | Test pass persists against saved revision | Run row has correct revision/status/output/duration/executor; history includes it | FR-5, FR-6, AC-5, AC-6 |
| P2-IT-12 | Test failed and error runs persist | Distinct failed/error rows; input preserved; safe diagnostics stored | FR-5, FR-6, AC-6 |
| P2-IT-13 | Duplicate client request id | Unique constraint/API returns same result or stable conflict; only one run row exists | NFR reliability, AC-6 |
| P2-IT-14 | Edit after passing test | New saved revision makes readiness stale and blocks publish | FR-4, FR-6, FR-7, AC-7, AC-8 |
| P2-IT-15 | Release readiness blocked then resolved | Checklist reasons/destinations are exact; publish becomes enabled only after retest + dependencies valid | FR-7, AC-8 |
| P2-IT-16 | Publish with invalid release notes/bump | No version row and no current pointer change; metadata error returned | FR-8, AC-9 |
| P2-IT-17 | Publish success | One immutable row created; monotonic version/semver/digest/test link correct; audit recorded | FR-8, AC-9 |
| P2-IT-18 | Concurrent publish requests | Row/advisory lock yields one success and one conflict/in-progress response; never two versions for one intent | NFR reliability, FR-8, AC-9 |
| P2-IT-19 | Rollback creates a higher version | Target snapshot copied byte-for-byte; `rollback_from` set; new current pointer updates; old history unchanged | FR-8, AC-10 |
| P2-IT-20 | Rollback dependency failure | No new version and no current pointer change; dialog-safe error returned | FR-8, FR-9, AC-10 |
| P2-IT-21 | Permission matrix on API | Viewer can read; operator can test but not manage/publish; admin can all routes | FR-9, NFR multi-tenancy, AC-11 |
| P2-IT-22 | Audit privacy | Audit rows contain revision/version/reason/digest but no Secret, raw prompt/customer content, credential, or model token | NFR data integrity, AC-11 |
| P2-IT-23 | Unknown Skill/version/run | Stable 404 codes; no fallback fixture and no other-scope data | FR-1, FR-9, AC-11 |
| P2-IT-24 | Empty catalog/test history/versions | APIs return empty collections; UI-facing `total=0` is truthful | FR-9, AC-11 |

## 5. Common Checks

| ID | Check | Pass standard |
|---|---|---|
| P2-CM-01 | Migration chain | Exactly one Alembic head; `0076` descends from `0075_gateway_allowed_hosts`; upgrade on a fresh and existing schema succeeds |
| P2-CM-02 | Additive migration | No change/backfill/drop of `service_application_skills`, `service_application_versions`, Agent, channel, or runtime tables |
| P2-CM-03 | Downgrade guard | Empty new tables may drop; populated tables refuse downgrade with an explicit export/cleanup requirement |
| P2-CM-04 | Default settings | AI generation and live tool tests default off; test bounds and profile version defaults load correctly; env overrides work |
| P2-CM-05 | Scope query audit | Every new read/write SQL contains tenant/business/workspace predicates; no client field can override them |
| P2-CM-06 | Permission migration | Permission catalog, role mapping, route dependencies, and `/me` permission exposure agree |
| P2-CM-07 | i18n completeness | `npm run check:i18n` passes; every new string exists in `en`, `hi`, `zh-CN`, `zh-TW`; no hardcoded user-visible literal remains |
| P2-CM-08 | Shell compatibility | 228px sidebar, Resource Center selection, collapsed mobile behavior, Skill header, and other console tabs remain unchanged |
| P2-CM-09 | Route compatibility | `/skills`, `/skills/create`, generic `/skills/:skillKey`, `/skills/:skillKey/edit` work; unknown keys show not-found, not redirect/fixture |
| P2-CM-10 | Static residue | In-scope pages contain no fixed success toast, fixed test output, fixed version rows, or fixed analytics counts |
| P2-CM-11 | Responsive layout | 1672×941, 1024×768, and 390×844 have no document horizontal overflow; test panes stack; tables scroll inside panels |
| P2-CM-12 | Accessibility | Tab arrow keys, dialog focus trap/return, form labels, `aria-live`, validation focus, and icon accessible names pass keyboard inspection |
| P2-CM-13 | Honest analytics | Runtime Analytics shows empty/no-data state or real data; no fabricated sparkline/count remains |
| P2-CM-14 | Regression commands | Backend `uv run ruff check src tests` and affected pytest suites pass; frontend typecheck, i18n, build, and affected Playwright suites pass |

## 6. UI / E2E Scenario Matrix

These scenarios are implemented in `frontend/tests/skills.spec.ts` and trace to the UI transition table.

| Scenario | Required assertions | Trace |
|---|---|---|
| Creation modes | AI prompt gate, template single-select, professional handoff, common editor/mode label | U1–U4, AC-1 |
| Dirty editor | Save success updates revision; Cancel/Back prompts; failed save preserves fields; conflict offers reload/duplicate | U5–U6, AC-3, AC-4 |
| Test workbench | Empty, invalid input, Running, Passed, Failed, Error, Blocked, Stale; Run disabled in flight; history appends | U7–U8, AC-5, AC-6, AC-7 |
| Readiness | Every blocker names a reason/destination; resolving all enables Publish; server 409 overrides client green state | U9, AC-8 |
| Publish | Dialog validation, progress, success version row/current marker, failure preserves metadata | U10, AC-9 |
| Rollback | Target selection, warning, progress, new higher current version, unchanged old history | U11–U12, AC-10 |
| Async states | Loading/empty/network/not-found/permission for catalog, detail, editor, history, readiness, versions | U13, AC-11 |
| Shell/width/locale | Desktop/tablet/390 layouts, no page overflow, keyboard operation, all four locales | AC-12 |

## 7. Regression Scope

- `frontend/tests/skills.spec.ts`: replace fixed eight-card and fixed test/version expectations with API-mock-backed lifecycle expectations.
- Existing sidebar/routing tests: all other console routes preserve active navigation and guard behavior.
- `frontend/tests/*.spec.ts` related to service applications: application Skill tabs and release actions remain unchanged.
- Backend service-application tests: `service_application_skills`, application publish/version/rollback, and previews remain green.
- Agent execution and permissions tests: added permission codes do not remove existing role access.
- Backend migration tests: all pre-existing migration heads and upgrade paths remain green with the new single head.
- Frontend build/type/i18n checks and backend lint/unit/integration checks.

## 8. Defect Severity and Exit Criteria

| Level | Definition | Handling |
|---|---|---|
| P0 Blocker | Data loss/corruption, cross-tenant disclosure, live write side effect during test, broken migration | Stop; fix and rerun affected path before any acceptance |
| P1 Severe | False Passed/published result, stale test allows publish, rollback rewrites history, permission bypass, fixture data shown as live | Fix before acceptance |
| P2 Normal | Non-hard-gate UX inconsistency, missing noncritical state, copy/layout defect | Record owner and due date; acceptance owner may approve a conditional result |
| P3 Minor | Cosmetic spacing, non-blocking wording, low-impact accessibility polish | Schedule fix; record if it remains |

**Exit criteria**

- All applicable UT/IT/CM cases pass.
- No P0/P1 defect remains open.
- UI E2E matrix passes with deterministic API mocks; no assertion depends on a fixed sample dataset.
- Scope isolation, data integrity, immutable versions, rollback atomicity, permission mapping, audit privacy, and migration/downgrade checks have direct evidence.
- Typecheck, i18n check, build, affected Playwright suites, Ruff, and affected pytest suites are green.
- Performance, capacity, latency percentiles, paired/large samples, CI provenance, and historical-sample metrics are not exit criteria for this phase.
