# Phase 2 · Skill Authoring, Testing, and Release — Implementation Breakdown

> Status: Implementation complete; verification executed (see `06-test-report.md`); acceptance pending.
> Created: 2026-11-27
> Basis: `01`–`05`, `00-ui-interaction-freeze.md`, and current repository inspection at `feat/login-responsive-scale`.
> Constraints: Two agents run in parallel with disjoint write ownership; the existing 228px console shell and application-owned Skill tables remain unchanged; PostgreSQL changes run only through Alembic/Docker.

## 1. Task Breakdown (Dependency Order)

Critical path: T1 → T2 → T4 → T6 (backend lifecycle), while T3 can establish frontend contracts and editor structure after the frozen API contract and then consumes T2/T4/T6 as they land. T5 and T7 are frontend integration gates, not static UI milestones.

| # | Task | Files (new/modified) | Depends | Trace | Owner |
|---|---|---|---|---|---|
| T1 | Restore the two missing upstream migrations for the live graph, then add the additive global Skill migration, domain contracts, permission catalog entries, safe settings defaults, and composition skeleton. | `backend/migrations/versions/{0074_codex_wire_api_backfill,0075_gateway_allowed_hosts,0076_skill_library}.py`; `backend/src/agent_platform/business_capabilities/skill_library/{__init__,models,service,testing,templates,assistant,routes}.py`; `backend/src/agent_platform/core_platform/platform_services/identity/permissions.py`; `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`; `backend/.env.example` | — | FR-1–FR-10; `03` §§2–4, 9–10 | Main thread restores graph files; Backend agent owns `0076` and domain code |
| T2 | Implement scoped catalog, template list, mode-based draft creation, detail read, revision-checked draft save, and duplicate-key conflict resolution. | Skill backend module; focused backend unit tests | T1 | FR-1–FR-4, FR-9; `03` §§5.1–5.2, 6.1–6.2; P2-UT-01–10, P2-IT-02–09 | Backend agent |
| T3 | Establish typed frontend contracts, API client, hooks, shared sectioned editor, generic Skill routes, and shell wiring without fabricated success paths. | `frontend/src/features/skills/{contracts,api,useSkills,SkillEditor}.ts(x)`; `frontend/src/app/{hashRouter.ts,App.tsx}`; Skill workflow styles | T1 contract shape; iterates against T2 | FR-1–FR-4, FR-10; `03` §§5, 11; U1–U6 | Frontend agent |
| T4 | Implement the bounded test executor, pass/fail/error/blocked classification, revision binding, idempotent persistence, and test history/detail reads. | Skill backend module; focused backend unit and PostgreSQL integration tests | T2 | FR-5–FR-6; `03` §§6.3, 7–8; P2-UT-11–15, P2-IT-11–13 | Backend agent |
| T5 | Build the two-pane test workbench and integrate it into the detail Test Records tab, including stale evidence and honest loading/history states. | `frontend/src/features/skills/TestWorkbench.tsx`; detail integration; styles and locales | T3, T4 | FR-5–FR-7, FR-9; U7–U8 | Frontend agent |
| T6 | Add evaluator-owned readiness, atomic immutable publish, version history/detail, rollback lineage, permission checks, and audit privacy. | Skill backend module; focused backend unit and PostgreSQL integration tests | T4 | FR-7–FR-9; `03` §§5.3–5.4, 6.4–6.5, 9; P2-UT-16–24, P2-IT-14–23 | Backend agent |
| T7 | Replace static catalog, creation, and detail behavior with API-backed lifecycle integration; build release/publish/rollback surfaces; remove fake analytics/test/version data; complete four-locale responsive accessibility work. | `frontend/src/features/skills/{SkillsPage,CreateSkillPage,SkillDetailPage,ReleasePanel}.tsx`; styles; `frontend/src/i18n/locales/*.json`; `frontend/tests/skills.spec.ts` | T5, T6 | FR-1–FR-10; U1–U13; AC-1–AC-12 | Frontend agent |
| T8 | Run migration/upgrade checks on the permitted Docker PostgreSQL instance, execute affected backend tests and required static checks, and run frontend typecheck/i18n/build plus affected Playwright tests. Record actual results; do not create `06`/`07` until testing and acceptance actually occur. | Verification only; defect fixes in owning files | T1–T7 | `04` full scope; P2-CM-01–14 | Main thread with both agents |

## 2. Parallel Execution and Write Ownership

### Backend agent

- Owns `backend/migrations/versions/0076_skill_library.py`, the new
  `backend/src/agent_platform/business_capabilities/skill_library/` package, Skill
  permission/settings additions, backend composition/route mounting, `backend/.env.example`,
  and new/affected backend tests.
- Must not edit frontend files, documentation files, application-owned
  `service_application_skills` behavior, or revert unrelated user changes.
- Executes stages T1 → T2 → T4 → T6 and reports after each stage with changed files and evidence.

### Frontend agent

- Owns the new Skill frontend module files, Skill page integration, Skill styles,
  `frontend/src/app/hashRouter.ts`, `frontend/src/app/App.tsx`, locale JSON files, and
  `frontend/tests/skills.spec.ts`.
- Must reuse `ConsoleSidebar`, `shared/api/client.ts`, Ant Design, and i18next; must not
  create a Skill-specific sidebar or add a new state-management library.
- Executes stages T3 → T5 → T7 against the frozen contracts. Until backend endpoints are
  available, completed UI may use deterministic test doubles only in test infrastructure,
  never fixture success inside production components.
- Must not edit backend files, documentation files, or revert unrelated user changes.

### Main thread

- Owns this breakdown document and status synchronization.
- Resolves any contract mismatch between the workstreams, performs DB migration verification
  on the existing Docker PostgreSQL service, and runs final integration checks after both
  agents return.
- Does not duplicate either agent's implementation while they are running.

No shared file is intentionally edited by both agents. If a contract change requires a file
outside an agent's ownership, the agent reports it to the main thread; the main thread records
an R item and makes the change after the current stage.

## 3. Document vs. Reality Conflicts and Decisions

### R1 Generic Skill routes

`02`/`00` require `/skills/:skillKey` and `/skills/:skillKey/edit`, but the current
`frontend/src/app/hashRouter.ts:30` accepts only `/skills/create` and a fixed identifier list.
**Decision:** replace the fixed list with a URL-safe generic Skill-key matcher plus the `/edit`
suffix. Existing named keys continue to work; unknown keys reach an API-backed not-found state.

### R2 Route mount and template path

`03` describes the router prefix as `/api/v1/skills` but also specifies
`GET /skill-templates`, which would be `/api/v1/skill-templates`. **Decision:** implement the
Skill router with an explicit `/api/v1` prefix and expose both `/skills` and `/skill-templates`
inside that router. No frontend path is invented outside the frozen contract.

### R3 Existing application-scoped Skills

The repository already has `service_application_skills` and application release/version logic.
**Decision:** reuse their patterns for scope, audit, locking, canonical JSON, and error handling,
but do not read or mutate those tables from the new global Skill domain. Phase 2 is additive.

### R4 Test cancellation

`00-ui-interaction-freeze.md` shows a Run/Cancel header, while `03` deliberately persists no
`running` row and uses one bounded in-flight request. **Decision:** implement honest in-flight
Running state and disable duplicate Run actions. Do not display a Cancel action unless the
backend can actually cancel the model/tool operation and confirm that no durable run was created.
Navigation away may abandon the browser request but must not claim completion.

### R5 Frontend fallback while backend stages land

The current frontend files are static. **Decision:** production components must never retain
static fixture success after integration. Temporary deterministic API mocks are allowed only in
Playwright test infrastructure. The catalog may honestly show loading/empty/error while the
backend stage is incomplete.

### R6 Permission baseline

`permissions.py` defines admin as `frozenset(PERMISSIONS)` evaluated at import time. **Decision:**
add `skill.read`, `skill.manage`, `skill.test`, and `skill.publish` to the catalog before the role
sets are constructed; map operator to read/test and viewer to read only. Add a direct mapping test.

### R7 Database execution environment

Project rules require PostgreSQL through Docker/Compose and migrations through Alembic.
**Decision:** inspect the running container/port without deleting volumes; apply additive
`upgrade head` and migration tests only after the migration exists. A destructive downgrade
check uses an empty disposable schema/database, never the existing development volume.

### R8 Analytics and AI/test switches

The reference UI implies live metrics and broad test execution, while the frozen design excludes
fabricated analytics and defaults AI/live tool testing off. **Decision:** Runtime Analytics shows
an honest empty state; write-action tests remain blocked; deployment switches remain `false`
unless a separate controlled mock-environment test explicitly turns them on.

### R9 Database migration graph is ahead of the checked-out branch

The permitted development database is stamped at `0075_gateway_allowed_hosts`, and the files
`0074_codex_wire_api_backfill.py` and `0075_gateway_allowed_hosts.py` exist in upstream commits
`be0b696` and `1f202fe`. The current branch's working tree only reaches
`0073_execution_parser_diag`, so `alembic current` cannot resolve the database revision.
**Decision:** restore the two missing upstream migration files without rewriting their behavior,
retain the existing database and volume, and make Phase 2 migration `0076_skill_library` descend
from `0075_gateway_allowed_hosts`. No Alembic restamp, manual DDL, downgrade, or data-volume reset
is used. `03`, `04`, `05`, and this breakdown are synchronized to this numbering.

## 4. Stage Exit Evidence

| Stage | Minimum exit evidence |
|---|---|
| T1 | Migration graph remains single-head and descends from `0075_gateway_allowed_hosts` through `0076_skill_library`; `alembic current` resolves the existing database; permission/settings unit tests pass; composition imports pass architecture checks. |
| T2 | Unit tests prove mode validation, key generation, revision conflict, and scoped reads; a PostgreSQL integration path demonstrates persistence when the test DB is available. |
| T3 | Typecheck passes for the new contracts/editor; generic routes resolve; no Skill-specific sidebar; production pages make no fake success claim. |
| T4 | Unit tests prove outcome classification, revision binding, blocked write execution, and idempotency; persistence/history expectations are explicit. |
| T5 | UI test covers empty/running/pass/fail/error/blocked/stale states using API mocks; active results survive history failure. |
| T6 | Tests prove readiness invalidation, atomic publish, immutable versions, rollback lineage, permission enforcement, and safe audit fields. |
| T7 | Full lifecycle Playwright scenarios pass with mocked backend contracts; four locales and required widths are checked; static fixtures are absent from production files. |
| T8 | Recorded command outputs for migration, affected pytest suites, Ruff/format/architecture, typecheck/i18n/build, and affected Playwright suites. Any skipped check is recorded as not run, not passed. |
