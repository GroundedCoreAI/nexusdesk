# Phase 1 · Skill-Centric Application Runtime - Acceptance Report

> Status: Implementation-level targeted acceptance passes; formal acceptance incomplete
> Created: 2026-11-12
> Basis: [05-acceptance-plan.en.md](05-acceptance-plan.en.md), [06-test-report.en.md](06-test-report.en.md)
> Conclusion: core implementation and targeted automated evidence are sufficient to enter PR/CI; manual UAT for A1-A12, empty-volume quickstart and formal sign-off remain pending

## 1. Acceptance scope

This round only determines whether the implemented service-application v2 code and targeted evidence meet the minimum bar for opening a pull request:

- The five-primary-concept service-application model has landed.
- Application-level Agent binding, skills, connections, releases and channel version pinning are implemented.
- Legacy Provider/Scenario/Industry frontend and backend composition are removed by clean-break.
- Migration `0058_service_application_v2` reaches head.
- The selected frontend E2E tests for the main service-application flow pass.

This report does not replace product UAT, formal security acceptance, deployment acceptance or GitHub CI.

## 2. AC status

| AC | Current evidence | Targeted result | Formal acceptance |
|---|---|---|---|
| AC-1 Application binds Agent/version | v2 contracts and service tests | Pass | A1 manual pending |
| AC-2 Same-named skills isolated across applications | Service and runtime-contract tests | Pass | A2 production-like pending |
| AC-3 One Agent across applications isolated | Contract tests | Pass | A3 production-like pending |
| AC-4 Draft and release isolation | Release and fixed-release preview tests | Pass | A4 manual pending |
| AC-5 Rollback appends a version | Service tests and frontend E2E | Pass | A5 manual pending |
| AC-6 Channel/conversation/run/trace provenance | Service tests and channel E2E | Pass | A6 channel integration pending |
| AC-7 Immutable examples and copying | Service tests and frontend E2E | Pass | A7 manual pending |
| AC-8 Restart/seed idempotency | Example-copy tests cover part of the logic | Partial | A8 quickstart pending |
| AC-9 Five concepts, pagination and i18n | Frontend type/i18n/build/E2E | Pass | A9 manual pending |
| AC-10 Legacy route/concept clean-break | Targeted search, build and route checks | Pass | A10 manual pending |
| AC-11 Empty-DB migration/seed/channel loop | Migration tests and `alembic current` | Partial | A11 quickstart pending |
| AC-12 Credential and audit safety | Service tests cover write-only credentials and secret-free digests | Partial | A12 security review pending |

## 3. Compliance status

| # | Current conclusion | Notes |
|---|---|---|
| C1 No plaintext credentials | Targeted pass | Service tests verify no API echo and release digests contain no secrets; CI secret scan and manual review remain |
| C2 Tenant/application isolation | Partial | Runtime skill isolation is tested; the full cross-tenant/workspace matrix remains for formal acceptance |
| C3 Clean-break | Targeted pass | Legacy frontend entry points and composition are removed; targeted search, typecheck and build pass; manual confirmation of legacy-route 404 remains |
| C4 Breaking migration | Partial | `0058` is head and migration tests pass; empty-volume quickstart, backup and reset window remain |
| C5 Permissions and audit | Partial | Key service behavior is implemented and partly tested; the full Reader/Admin matrix remains |
| C6 Release/rollback/channel version switching | Targeted pass | Append-only rollback, fixed versions and channel binding are tested; production-like exercise remains |
| C7 Chinese/English and document consistency | Targeted pass | i18n check passes; formal UAT still requires page-by-page verification |

## 4. Outstanding acceptance gates

1. GitHub PR CI is fully green.
2. Empty-volume quickstart starts once and completes migration, seed, publish and channel-message flow.
3. A1-A12 manual UAT and evidence are archived.
4. Formal security, permission, migration and documentation review for C1-C7.
5. No open P0/P1; P2/P3 have owners and deadlines.

## 5. Conclusion

The implementation currently meets the targeted acceptance state for "ready to open a pull request and enter CI", with automated evidence for the core design boundaries and primary flows. Formal acceptance remains **incomplete**; the phase must not be marked release-ready until CI, quickstart and manual UAT all pass.
