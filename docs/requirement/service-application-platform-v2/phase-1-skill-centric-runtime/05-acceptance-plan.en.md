# Phase 1 · Skill-Centric Application Runtime - Acceptance Plan

> Status: Implementation-level targeted acceptance passes; manual UAT, empty-volume quickstart and formal CI acceptance remain pending. Evidence: [06-test-report.en.md](06-test-report.en.md) and [07-acceptance-report.en.md](07-acceptance-report.en.md)
> Created: 2026-11-11
> Basis: [01-business-goals.md](01-business-goals.en.md) (G1-G6 and success metrics), [02-requirements.md](02-requirements.en.md) (AC-1-AC-12); execution evidence in [04-test-plan.md](04-test-plan.en.md)

The A1-A12 checks, business metrics and C1-C7 controls in this document remain the formal acceptance baseline. The current conclusion covers only implementation-level targeted verification that was actually executed; it does not mean manual UAT, a production-like environment or full CI has been signed off.

## 1. Acceptance objectives and organization

Confirm that Phase 1 simultaneously achieves:

- **Functional correctness**: AC-1-AC-12 can be reproduced in practice.
- **Business effectiveness**: application concepts converge and operators can move from an example copy to first preview.
- **Trustworthy isolation**: same-named skills and one Agent across applications do not cross wires; releases and channel versions are traceable.
- **Safe deployment**: credentials are not plaintext in storage/logs; releases roll back and failures are locateable.
- **Completed clean-break**: legacy concepts, routes and dual-track code no longer run.

| Role | Responsibility |
|---|---|
| Product owner | Host acceptance; judge concept convergence and operator experience; approve P2 carry-over |
| Engineering owner | Provide environment, release build, metric data and fixes |
| QA | Execute ACs, record evidence, regression and defect levels |
| Channel administrator representative | Validate channel binding, version switching and live message path |
| Security/operations representative | Review credentials, audit, migration, backup and deployment boundaries |

## 2. Acceptance environment and preconditions

| Environment | Purpose |
|---|---|
| Production-like environment (PostgreSQL + demo/mock external connections) | Functional acceptance, version/channel/audit evidence |
| Quickstart empty volume + demo model | Deployment promise, migration, seed idempotency and fresh-database closure |
| Frontend preview environment (Chinese/English) | Information architecture, table pagination, read-only examples and i18n |

**Preconditions**:

- All UT/IT/CM cases in `04-test-plan.md` pass.
- No P0/P1; P2/P3 have owner and proposed deadline.
- Acceptance uses an isolated tenant/business/workspace.
- Database backup is complete; destructive migration window and no-rolling-mixed-deployment constraints are confirmed.
- Dataset includes a standard example, one user copy and one Agent referenced by two applications.

## 3. Functional acceptance checklist

For each scenario record: executor, date, environment, preconditions, actual result, decision, screenshot/log/API evidence link.

| # | Acceptance steps | Pass criteria | AC / trace |
|---|---|---|---|
| A1 | Create an application, directly select an Agent and published version, save and open detail | Saves; Agent/version visible; no scenario/capability/Provider | AC-1 / FR-1 |
| A2 | Create `order_lookup` in A and B with different mock endpoints/credentials; run each | A/B receive own responses; editing A endpoint does not change B; no credentials in network/logs | AC-2 / FR-2/3/4/8 |
| A3 | Bind the same Agent to A/B and trigger tool selection in each conversation | A sees only A skills, B only B; global tools cannot be used to bypass | AC-3 / FR-8 |
| A4 | Publish A and record channel result; edit draft skill/connection without publishing; call through channel again | Live result remains the published version; UI shows unpublished; after publish and channel switch, new behavior applies | AC-4 / FR-6/9 |
| A5 | Roll A back to a historical version | New highest version with source target; new messages use rollback version; historical JSON unchanged | AC-5 / FR-7 |
| A6 | Bind a channel to a published A version, send inbound message, inspect outbox/conversation/run/trace | All records have same app/version; trace includes skill/connection/latency; no bare Agent routing | AC-6 / FR-9/10 |
| A7 | Try editing/deleting a standard example, then copy and edit the copy | Example rejects writes; copy editable; example unchanged | AC-7 / FR-11 |
| A8 | Edit the copied app and restart quickstart | Startup succeeds; user app retained; example not duplicated or overwritten | AC-8 / FR-11 |
| A9 | In Chinese and English, walk catalog -> six detail tabs -> skills Table/Drawer -> release checks | Only five primary concepts; default page size 10, bottom aligned; all copy localized | AC-9 / FR-12/13 |
| A10 | Try old Provider/Scenario/industry-upgrade APIs, `/service-apps/industry` and old navigation | Entry points absent/404; no redirects; no old frontend components/types | AC-10 / FR-15 |
| A11 | Start from an empty volume, wait for migration/seed, publish an app and receive a channel message | One startup succeeds; no manual DDL; publish and message work; health checks pass | AC-11 |
| A12 | Save credentials, publish, roll back and switch channel version; inspect API, DB, logs, audit and traces | Each action audited; credential API shows only configured; no plaintext evidence | AC-12 / FR-4/14 |

## 4. UAT decision

Product owner and channel administrator representative jointly judge:

1. Whether application detail is easier to understand than the old scenario/capability model.
2. Whether copy example -> configure connection -> preview/publish can be completed without product/engineering verbal explanation.
3. Whether example vs application, draft vs live and application vs channel versions are clear in the UI.
4. Whether skill drawer density is acceptable and safety rules do not imply code authoring.
5. Whether removing the standalone industry-capability entry while exposing standard examples as an application-origin filter matches daily work.

Any "requires engineering explanation to complete basic configuration" issue is at least P2; anything affecting publishing or channel correctness is P1.

## 5. Business metric acceptance

| Metric | Baseline | Target | Measurement |
|---|---|---|---|
| Five-concept convergence | Old UI showed scenario/capability/Provider | 0 legacy intermediates in new UI/API/runtime | Product page walkthrough + P1-CM-05 search |
| Cross-application isolation of same-named skills | No application connections; unprovable | AC-2/AC-3 pass 100% | P1-IT-02/03 evidence |
| Channel version trace coverage | Agent only | 100% inbound/conversation/run | P1-IT-07 database snapshot |
| Draft/release isolation | Channel bypassed application versions | Live diff 0 | A4 response comparison |
| Safe example reuse | Installation/upgrade could edit/merge | 0 successful direct edits; 0 restart overwrites | A7/A8 |
| Copy-to-first-preview time | No baseline | Five-operator median <= 10 minutes | UAT timing sheet |
| Main component size | 2,384 lines | Route orchestration <= 300 lines; independent tab component <= 800 lines | Line-count report |

## 6. Compliance checks

| # | Check | Decision |
|---|---|---|
| C1 | Credentials, Authorization, Cookie and tokens never appear in plaintext in APIs, release JSON, run snapshots, traces, audit, logs or git content | Veto |
| C2 | Tenant/business/workspace/application isolation; cross-application/tenant access impossible | Veto |
| C3 | True clean-break: no runtime entry for legacy Provider/Scenario/industry upgrade/`service-apps/industry` | Mandatory |
| C4 | Breaking migration has backup, explicit reset window, fresh-database success and no rolling mixed deployment | Mandatory |
| C5 | Permissions: Reader read-only; Admin only edits/credentials/publish/channel switch; key actions audited | Mandatory |
| C6 | Publishing/rollback append history; channel version switch is explicit; failures are locateable and never corrupt live version | Mandatory |
| C7 | Chinese/English docs and user copy stay in sync; no untranslated new main-flow copy | Mandatory |

## 7. Pass standard and sign-off

- **Pass**: A1-A12 pass; structural/security metrics met; C1-C7 pass; no P0/P1.
- **Conditional pass**: only P2/P3 remain, each with owner/deadline and business approval; security/isolation/migration/clean-break all pass.
- **Fail**: any veto, application-isolation failure, ineffective release/channel version, migration failure or incomplete clean-break. Fix, re-test affected items and regression.

Output the Phase 1 Acceptance Report (`07-acceptance-report.md` / `.en.md`): AC records, metric measurements, compliance results, carry-over list, conclusion and signatures from Product / QA / Engineering / Channel representative.
