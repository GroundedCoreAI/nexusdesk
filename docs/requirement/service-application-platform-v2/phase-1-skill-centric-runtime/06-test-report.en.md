# Phase 1 · Skill-Centric Application Runtime - Test Report

> Status: Targeted tests complete; full CI, empty-volume quickstart and manual UAT not executed
> Created: 2026-11-12
> Scope: service-application v2, application connections, skills, releases, channel version pinning, migration and the related frontend changes only
> Conclusion: directly related backend tests, static checks, frontend gates and E2E tests pass; this report does not claim a green repository-wide suite or release readiness

## 1. Execution policy

At the user's request, this run did not execute unrelated repository-wide regression, Memory tests or tests for other modules. Resources were limited to the five backend test files for service-application v2, the related frontend service-application E2E suite, frontend build gates and backend static/architecture checks.

Cases that were not executed are not assumed to pass. Repository-wide regression and CI results must still be confirmed by the pipeline after the pull request is created.

## 2. Results

| Check | Command/scope | Result |
|---|---|---|
| Backend service-application v2 targeted tests | `test_service_application_v2_contracts.py`, `test_service_application_v2_migrations.py`, `test_service_application_v2_preview_api.py`, `test_service_application_v2_preview_runtime.py`, `test_service_application_v2_services.py` | 34 passed, 1 skipped in 21.18s |
| Backend static checks | `uv run ruff check src tests migrations` | Passed |
| Architecture boundary check | `python scripts/check_architecture.py` | `architecture gate passed` |
| Migration state | `alembic current` | `0058_service_application_v2 (head)` |
| Frontend type check | `npm run typecheck` | Passed |
| Frontend i18n check | `npm run check:i18n` | Passed, 2114 translations |
| Frontend build | `npm run build` | Passed; existing main-bundle size warning remains |
| Targeted frontend E2E | service-application and channel-navigation suites | 9 passed |
| Patch integrity | `git diff --check` | Passed |

## 3. Coverage

### 3.1 Backend contracts and migration

- The v2 contract rejects legacy `scenarios/capabilities` fields and requires an application to bind a published Agent.
- Application rules cover fallback, handoff, human confirmation, draft write preview and result validation, while normalizing the legacy `reply` value.
- Release-snapshot digests are stable and contain no plaintext credentials.
- When one Agent is bound to two applications, runtime authorization includes only each application's own skills.
- `0058_service_application_v2` implements the clean-break schema, channel application-version fields and trace/audit contracts.

### 3.2 Services, channels and preview

- Standard examples are immutable; a copy belongs to the user and is not overwritten by restart or seeding.
- An unpublished Agent cannot be bound to an application; publish readiness checks Agent version, connections and credentials.
- Credentials are write-only; APIs return only `credentials_configured`, never plaintext or ciphertext.
- Rollback appends a new version while preserving historical version contents.
- Channel ingress pins an application release version; conversations, runs and traces retain application context.
- Draft preview uses the current Agent; fixed-release preview strictly uses the Agent and rules from the release snapshot.
- Write-skill preview requires both the application rule and platform setting gates; HTTP skills use MockTools and make no real upstream call.

### 3.3 Frontend

- The service-application catalog uses the v2 contract with a default page size of 10; connection lists send real server-side pagination parameters.
- The detail page exposes only the six v2 tabs, and the rules model matches backend fields.
- Release/rollback, immutable-example copy and Agent usage links have targeted E2E coverage.
- The channel page only allows a published application version to be bound.
- i18n, type checking and the production build pass.

## 4. Not executed or verified

- Full backend pytest was not run.
- Memory and unrelated repository-wide regression suites were not run.
- The empty-volume quickstart bootstrap, migration and seed deployment smoke test was not run.
- Manual UAT for A1-A12, the full role/permission matrix and a production-like environment exercise were not run.
- GitHub CI was not run; final merge must use the PR CI result.

## 5. Known minor risks

- In-application version history and in-application channel lists still use frontend pagination, with API limits of 50/100 items. This does not block the current flow but will require server-side pagination at larger scale.
- The frontend build retains an existing warning that the main bundle exceeds 500 kB.
- The complete backend suite and CI have not run, so this report is not a formal release-acceptance record.

## 6. Conclusion

Targeted implementation verification for service-application v2 passes with no P0/P1 blocker introduced by this change. The change is ready to enter a pull request for CI validation; until CI, quickstart and manual UAT complete, it must not be described as fully tested or release-ready.
