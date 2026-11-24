# Phase 1 · UI-managed model egress hosts — Test Report

> Status: implementation tests executed (2026-11-24); acceptance not run yet
> Basis: `04-test-plan.md` (P1-UT/IT/CM), `02-requirements.md` (AC-1..AC-8)
> Environment: macOS local; temporary `pgvector/pgvector:pg17` container on
> 127.0.0.1:55433 (removed after the run)

## 1. Execution Summary

| Layer | Command / location | Result |
|---|---|---|
| Backend lint | `uv run ruff check src tests` | pass |
| Architecture gate | `python scripts/check_architecture.py` | pass |
| Host unit tests | `tests/test_model_gateway_hosts.py` | 28 passed |
| Gateway regression | `tests/test_model_gateway.py` (Postgres) | 27 passed |
| Full unit suite | `uv run pytest -q -m "not postgres"` | 2483 passed, 6 skipped |
| Migration chain | `alembic heads` | `0075_gateway_allowed_hosts` |
| Migration round-trip | `upgrade head → downgrade 0074 → upgrade head` | pass on pgvector pg17 |
| Frontend i18n | `npm run check:i18n` | 2734 translations verified |
| Frontend typecheck | `npm run typecheck` | pass |
| Frontend build | `npm run build` | pass |
| Compose render | `docker compose config` | both allowlist variables present |
| CI (push, 674b8ad) | [run 45406197775](https://github.com/GroundedCoreAI/nexusdesk/actions/runs/45406197775) | all five jobs success |

## 2. Case Results

| ID | Case | Result | Evidence |
|---|---|---|---|
| P1-UT-01..06 | Normalization, URL extraction, private/metadata/IP rejection, resolution success/failure | pass | `test_model_gateway_hosts.py` |
| P1-UT-07 | Switch off: effective set empty; add/remove disabled | pass | `test_store_rejects_mutation_when_disabled` |
| P1-UT-08 | Cache hit, TTL reload, write invalidation | pass | `test_store_caches_managed_hosts_and_invalidates_on_write` |
| P1-IT-01 | Add public host; save a channel using it | pass | Postgres integration test |
| P1-IT-02 | Non-admin list/add/delete | pass (viewer GET 403; mutations use the same `Admin` dependency) | Postgres integration test |
| P1-IT-03 | Tenant isolation | pass | Postgres integration test (`another-tenant` cannot resolve/use the host) |
| P1-IT-04 | Remove host used by a channel | pass | Postgres integration test (`model_address_not_allowed` afterwards) |
| P1-IT-05 | Env host remains allowed | pass | Unit + Postgres tests |
| P1-IT-06 | Duplicate host | pass | `model_host_exists` conflict |
| P1-IT-07 | Disabled switch with rows | pass | Disabled mutation/list semantics |
| P1-IT-08 | Audit content secret-free | pass (audit call asserted by store path; no secrets exist in the table) | Store unit test + schema review |
| P1-CM-01 | Migration online + downgrade | pass | Temporary Postgres round-trip |
| P1-CM-02 | Default configuration | pass | `Settings(_env_file=None)` default `false`; compose renders `false` |
| P1-CM-03 | Audit/observability | pass | Audit actions `model_gateway.allowed_host.added/removed` |
| P1-CM-04 | Tenant isolation | pass | Postgres integration test |
| P1-CM-05 | Secret scan | pass | No secret columns or payloads introduced |

## 3. Defects Found and Fixed During Implementation

| ID | Found by | Issue | Fix |
|---|---|---|---|
| D-1 | Unit test `test_managed_host_does_not_bypass_shape_checks` | Managed-host path could bypass the plain-http rejection because the allowlist check hid the scheme check | Split `_parse_address` (shape) from `validate_address` (deployment list) so shape checks always run first |
| D-2 | Migration invariant tests | Two suites pinned the previous migration head | Updated both to `0075_gateway_allowed_hosts` |

## 4. Residual Risks

- **R-1 (DNS rebinding, HTTP gateway)**: call-time resolution is checked, but the
  HTTP client re-resolves when connecting. Full IP pinning remains a follow-up.
- **R-2 (Codex CLI)**: the CLI resolves the host in its child process; Phase 1
  applies the allowlist and save-time resolution only.
- **R-3 (multi-process TTL)**: a worker may keep using a removed host for up to
  the 15-second cache TTL; removal is fail-closed after that window.

## 5. Not Executed

- Browser end-to-end flows (Playwright) were not run; the UI was validated by
  typecheck/build and code review only.
- Phase 1 acceptance (`05`) is pending.
