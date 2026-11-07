# Phase 6 · Security, Reliability, and Event Governance — Test Plan

> Status: Pending implementation (execute after this phase is developed; not currently executed or passed)
> Created: 2026-11-02
> Basis: `02-requirements.md` (FR-1–FR-16, AC-1–AC-16), `03-technical-design.md` (planned migrations 0056/0057, Fencing, Outbox, Vault/Broker, Sandbox)

## 1. Test Scope and Principles

**Scope**: Execution Vault/Broker, redaction, strong sandbox/network/file isolation, Fencing/Worker recovery, cancellation/cleanup/quota, retry side effects, event schema/sequence/dedup/Outbox, SSE replay, idempotent usage, parser diagnostics, migrations, and compatibility regressions.

**Principles**:

1. **Adversarial testing is mandatory**: Real untrusted tasks perform escape, egress, cross-tenant, Secret-exfiltration, and resource-exhaustion attacks; configuration inspection alone does not pass.
2. **Fault points must be precise**: Inject crashes at claim/takeover, before/after transaction commit, before/after Outbox publication, each cleanup stage, and the SSE catch-up window rather than relying on random restarts.
3. **Zero effective stale writes**: Fencing assertions cover state, events, usage, Sessions, Outbox, and resource operations, not Run state alone.
4. **Availability cannot replace safe failure**: Unavailable sandbox/Broker/key/policy must deny; never fall back to host execution, open networking, or skip redaction.
5. **Compatibility and empty states are mandatory**: Existing v1 events, empty new fields, transient deltas, historical Runs, and switch rollback retain defined behavior; unmeasured Phase 0 baselines cannot pass.
6. **Control time and scale**: Use controllable clocks for expiry/backoff; exercise sequence/dedup/replay with concurrency and more than one page rather than long sleeps.
7. **Isolate evidence**: All Secrets are dedicated canaries; attacks run in dedicated environments, followed by grant revocation, sandbox cleanup, and residue checks.

## 2. Test Environments and Data Construction

| Environment | Purpose |
|---|---|
| Unit (no DB) | scope/TTL, redaction, path/IP, schemas, retry matrix, usage corrections, and parser classification. |
| Integration (PG + pytest postgres fixture) | Migration/backfill, Fencing conditional writes, transactional Outbox, usage ledger, and Session/Run correlation. |
| Multi-Worker/Host fault environment | At least two Workers, independent recovery, and real process groups; SIGKILL, heartbeat stall, disconnection, and cleanup failure. |
| Strong-sandbox adversarial environment | Non-production host, disposable networks/volumes, attack samples, DNS/proxy/metadata decoys, and resource-limit observability. |
| SSE/Outbox environment | Multiple APIs/publishers, lost notifications, multipage events, reconnects, retention cursors, and publication failures. |
| React/Codex regression environment | Phase 0 baseline, existing DemoModel and Phase 5 controlled Codex, and historical Agent/Run/event fixtures. |

**Data construction conventions**: Use at least two tenants/Agents/Workspaces and multiple Runs/attempts/Sessions; construct v1 historical events, duplicate producer_event_id, page boundaries above 200 events, duplicate/corrected usage, Secret canaries, and malicious artifacts. Never commit real keys. If real sandbox/fault environments are unavailable, mark affected items `pending_env`; mocks cannot substitute for hard-gate acceptance.

## 3. Unit Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P6-UT-01 | Vault ciphertext binding, rotation, and revocation | Tenant/Engine/Workspace/version mismatch and revocation deny; missing keys are never recreated automatically. | FR-1 |
| P6-UT-02 | Broker grant scope/audience/TTL | Only the original Run/Engine/scope works; expiry, replay, cross-Execution, and scope expansion deny. | FR-2 |
| P6-UT-03 | Resume issues a new grant | Old grants cannot be reused, the new Run receives a new short-lived grant, and revocation applies immediately. | FR-2 |
| P6-UT-04 | Structured/text/nested redaction | Registered Secrets, canaries, Token patterns, and sensitive fields are replaced; output length is bounded. | FR-3 |
| P6-UT-05 | Untrusted policy cannot expand | Agent/client cannot disable sandbox or expand resources, network, mounts, or grant scope. | FR-4–FR-6, FR-16 |
| P6-UT-06 | Network host/IP/redirect decisions | Private/link-local/metadata addresses, changed DNS results, and unauthorized redirects deny. | FR-5 |
| P6-UT-07 | File canonicalization and link/TOCTOU | Traversal, absolute paths, symlink/hardlink, devices, and sensitive host paths deny. | FR-6 |
| P6-UT-08 | Claim/takeover epoch monotonicity | Takeover receives a larger epoch; stale owner/epoch/lease conditional updates affect zero rows with no partial writes. | FR-7 |
| P6-UT-09 | Fencing operation coverage matrix | finish/append/usage/session/outbox/resource operations all validate ownership, with no omitted path. | FR-7 |
| P6-UT-10 | Worker-loss recovery decision | Heartbeat/Host/side-effect evidence selects recovery or failure without two effective Workers. | FR-8 |
| P6-UT-11 | Cancellation request/confirmation state machine | No cancelled state before exit; confirmed cleanup yields one terminal state, and duplicate requests are idempotent. | FR-9 |
| P6-UT-12 | Cleanup and two quota types | Run-active slots and Host reservations release separately on evidence; cleanup retries do not double-release. | FR-9 |
| P6-UT-13 | Retry classification matrix | Pre-launch side-effect-free failures may auto-retry; timeout/disconnection/external writes never blindly retry. | FR-10 |
| P6-UT-14 | Event schema v1/new-version compatibility | Versions route correctly, unknown major versions/invalid payloads deny, and historical field meanings remain unchanged. | FR-11 |
| P6-UT-15 | Concurrent sequence allocation and deduplication | Concurrent new events have unique monotonic seq; duplicate producer keys return the original without consuming seq. | FR-11, FR-12 |
| P6-UT-16 | Outbox state and backoff | pending/published transitions are idempotent, failures retry, and last_error is bounded/redacted. | FR-12 |
| P6-UT-17 | SSE cursor merge and retention gap | The greater of after/Last-Event-ID wins; invalid returns 400 and expired returns 409 without silent page skips. | FR-13 |
| P6-UT-18 | Usage source uniqueness and correction chain | Duplicate sources do not recount, corrections remain traceable, missing is unknown, and aggregates rebuild. | FR-14 |
| P6-UT-19 | Old-epoch usage denial | Late usage writes no ledger, changes no aggregate, and creates no Outbox. | FR-7, FR-14 |
| P6-UT-20 | Parser classification, samples, and rate limiting | malformed/unknown/size/critical categories are correct; samples are redacted/bounded and diagnostics do not recurse. | FR-15 |
| P6-UT-21 | Secure default configuration | Untrusted defaults false, sandbox/default-deny network true, raw parser samples false, and TTL/retention are bounded. | FR-16 |
| P6-UT-22 | Rollback compatibility policy | Disabling the publisher does not disable source-of-truth/Fencing/redaction; untrusted execution has no security-degradation switch. | FR-16 |

## 4. Integration Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P6-IT-01 | Credential lifecycle and binding tampering | Reproduce AC-1; ciphertext/public API/logs contain no plaintext, and rotation/revocation/anomalies behave correctly. | AC-1 |
| P6-IT-02 | Grant cross-Run/expiry/replay/Resume adversarial cases | Reproduce AC-2; only original scope succeeds, all others deny with Secret-free audit. | AC-2 |
| P6-IT-03 | Secret canary across every output and disclosure response | Reproduce AC-3; logs/events/SSE/errors/diagnostics/artifacts contain no plaintext, and revocation/stop-new-execution works. | AC-3 |
| P6-IT-04 | Sandbox escape/privilege/resource-exhaustion attacks | Reproduce AC-4; host and other Executions remain unaffected, and no sandbox means no launch. | AC-4 |
| P6-IT-05 | DNS rebinding/metadata/proxy egress attacks | Reproduce AC-5; actual network boundaries deny all unauthorized traffic and decoys record no hits. | AC-5 |
| P6-IT-06 | File link/host/cross-tenant/malicious-artifact attacks | Reproduce AC-6; no unauthorized I/O or residue occurs, and suspicious artifacts are not published. | AC-6 |
| P6-IT-07 | Every stale-write type after two-Worker takeover | Reproduce AC-7; A performs zero effective state/event/usage/Session/Outbox/resource writes. | AC-7 |
| P6-IT-08 | Worker SIGKILL/heartbeat stall/late success | Reproduce AC-8; execution recovers or reaches one terminal state without old overwrite or dual terminal states. | AC-8 |
| P6-IT-09 | Takeover versus heartbeat/finish concurrency race | Only the new epoch is effective, old finish/append rolls back, and final event agrees with state. | AC-7, AC-8 |
| P6-IT-10 | Cancellation/timeout with normal exit and hang | Reproduce normal/forced AC-9 paths; process trees/connections/mounts clean up and terminal state/quota are correct. | AC-9 |
| P6-IT-11 | Reentrant recovery after cleanup failure and Worker loss | Unconfirmed execution is not cancelled; cleanup_failed/alert is visible, and recovery leaves no duplicate release or orphans. | AC-9 |
| P6-IT-12 | Retry after pre-launch failure and ambiguous disconnection | Reproduce AC-10; only safe cases auto-retry, new attempts correlate, and side effects do not duplicate. | AC-10 |
| P6-IT-13 | Disconnection after external write and manual rerun | No automatic replay; a manual new Run still requires idempotency/authorization, with at most one external effect. | AC-10 |
| P6-IT-14 | Mixed event versions and concurrent sequence | Reproduce AC-11; history remains compatible, concurrency has no conflicts, and invalid schemas are diagnosed. | AC-11 |
| P6-IT-15 | Duplicate native-event delivery and concurrent deduplication | Reproduce the AC-12 dedup portion; one key yields only one event/seq/Outbox/usage. | AC-12 |
| P6-IT-16 | State+event+Outbox commit fault points | Pre-commit crash leaves no partial state; post-commit crash rescans, and terminal state agrees with final event. | AC-12 |
| P6-IT-17 | Crash before/after Outbox publication and duplicate publication | Under at-least-once transport, event_id consumers are idempotent, pending recovers, and business effects do not duplicate. | AC-12 |
| P6-IT-18 | SSE multipage disconnect/lost notification/reconnect | Reproduce AC-13; no silent gaps beyond one page, event_id deduplicates, and transient deltas do not affect the factual stream. | AC-13 |
| P6-IT-19 | SSE invalid/expired cursor and terminal catch-up | 400/409 semantics are correct; subscribe/query races lose no final event, and terminal state agrees. | AC-13 |
| P6-IT-20 | Duplicate/replayed/old-Worker/corrected usage | Reproduce AC-14; one source counts once, old epochs deny, and corrections/rebuilds agree. | AC-14 |
| P6-IT-21 | Continuous parser failure/oversize/Secret samples | Reproduce AC-15; classification/rate limiting/redaction and skip/quarantine/fail work without event storms. | AC-15 |
| P6-IT-22 | 0056 online expansion/backfill/validation | Upgrade from actual head; existing seq/event_id/schema/source are correct without duplication/renumbering, and lock budget is recorded. | AC-16; FR-7–FR-14 |
| P6-IT-23 | 0057 credential migration and data protection | Upgrade from actual head succeeds; public queries contain no plaintext, and populated downgrade follows protection policy. | AC-16; FR-1, FR-2 |
| P6-IT-24 | Rollout/rollback and React/Codex/API/SSE regressions | Reproduce AC-16; security checks do not degrade, Outbox reconciliation loses nothing, and Phase 0 diff is zero. | AC-16 |
| P6-IT-25 | Full resource/quota/accounting reconciliation after failures | After mixed SIGKILL, network loss, disk full, and process hangs, Run/Host/usage/Outbox reconciliation leaves no residue. | AC-8–AC-10, AC-12, AC-14 |

## 5. General Checks (Applicable to This Phase)

| ID | Check | Pass criterion | Traceability |
|---|---|---|---|
| P6-CM-01 | Migration head and historical protection | 0056/0057 are planning numbers only; recheck actual head/dependencies before implementation and never modify 0001–0052 or merged migrations. | FR-16; G7 |
| P6-CM-02 | Online migration and backfill | expand/backfill/validate/switch evidence is complete; existing events receive deterministic IDs without renumbering or uncontrolled long locks. | FR-11, FR-16 |
| P6-CM-03 | Secret and audit scan | Public DB views, logs, events, SSE, errors, diagnostics, artifacts, and audit contain no plaintext Secrets/grant Tokens. | FR-1–FR-3 |
| P6-CM-04 | Untrusted-exposure gate | Default off; no failed security/reliability hard item can be bypassed by enablement or configuration. | FR-4, FR-16 |
| P6-CM-05 | Tenant and Workspace isolation | Every credential/grant/file/event/usage/diagnostic query and operation carries trusted tenant/scope. | FR-1–FR-6, FR-13–FR-15 |
| P6-CM-06 | Static/dynamic Fencing coverage | Every Worker write entry and resource operation checks epoch; fault injection produces zero effective stale writes. | FR-7 |
| P6-CM-07 | Outbox/SSE/terminal consistency | Event Store is the source of truth; lost notifications lose no data, retention gaps are explicit, and terminal state agrees with final event. | FR-12, FR-13 |
| P6-CM-08 | Cleanup, quota, and alerts | No residual processes/FDs/mounts/volumes/grants/reservations; cleanup_failed, Outbox lag, Fencing, and disclosure alert correctly. | FR-9, FR-16 |
| P6-CM-09 | Bilingual and requirement traceability | Chinese/English structure, IDs, and table rows match; UT/IT/CM, A/C, FR/AC/G remain traceable. | G7 |
| P6-CM-10 | Performance and recovery baselines | Record p50/p95, Outbox lag, recovery time, and lock duration honestly; items pending Phase 0 cannot pass. | FR-16; G7 |

## 6. Regression Scope

- `backend/tests/test_runtime_postgres.py`: claim, capacity, cancellation race, Worker loss, late results, Run API, and SSE replay.
- React/Codex common contracts, Session Resume, RuntimeHost/Workspace, approvals/input, and historical Agent configuration.
- `test_gateway_credentials.py`, tool credential/egress/Workspace suites: new Execution Broker/Sandbox must not weaken existing boundaries.
- Historical v1 event fixtures, transient model.delta, SSE `after`/`Last-Event-ID`, the 200-event page boundary, and existing client consumption.
- Full migration chain and replica upgrade from actual implementation-time head; 0056/0057 backfill, old-binary reads, rollback reconciliation, and data protection.
- Keep items with unmeasured Phase 0 baselines marked “pending Phase 0”; averages or samples cannot conceal P0/P1 scenarios.

## 7. Defect Severity and Exit Criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocker | Secret/cross-tenant disclosure; sandbox/network/file escape; accidental untrusted exposure; data loss; effective stale-Worker commit; duplicate billing. | Stop new executions immediately, revoke/isolate, fix, and rerun full adversarial/fault regressions. |
| P1 critical | Terminal/final-event inconsistency; cancellation/cleanup/quota errors; silent Outbox loss; silent replay gap; security-switch bypass. | No acceptance or new-tenant exposure before resolution. |
| P2 major | Non-core diagnostic/metric/compatibility quality deviation without security or correctness impact. | Only non-hard-gate items with owner/deadline may proceed with product, QA, and security sign-off. |
| P3 minor | Wording, non-sensitive logging, and documentation issues. | Schedule fixes and retain traceability. |

**Exit criteria**: All applicable UT/IT/CM and AC pass; real-sandbox, multi-Worker, fault-point, and real SSE/Outbox items have no unapproved skips; successful adversarial attacks=0; stale writes/duplicate usage/silent event gaps=0; regressions are green, Phase 0 diff is zero, and no P0/P1 remains. If any hard gate fails, `execution_untrusted_tenants_enabled` remains false and the phase cannot pass overall.
