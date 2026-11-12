# Phase 6 · Security, Reliability, and Event Governance — Acceptance Plan

> Status: Pending implementation (execute before this phase goes live; not currently accepted, and untrusted execution remains disabled)
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence while retaining independent security and SRE approval for untrusted execution)
> Basis: `01-business-goals.md` (G1–G7 and success metrics), `02-requirements.md` (AC-1–AC-16); test execution is governed by `04-test-plan.md`

## 1. Acceptance Scope and Responsibility

Confirm every AC, zero successful real attacks, consistent data/terminal state/resources at precise fault points, and evidence for compatibility and rollback. For routine acceptance, the acceptance owner organizes and records decisions while the executor prepares isolated environments, performs supplementary checks, and organizes evidence; one person may hold both responsibilities. Do not invent independent product, QA, business, or finance roles. Usage idempotency, correction chains, aggregate rebuilding, and zero duplicate billing remain proven by A14, C6, C9, and automated reconciliation rather than a finance signature replacing technical evidence.

**Independent-approval exception**: Enabling untrusted multi-tenant code execution is outside single-person lightweight acceptance and requires separate independent security and SRE/operations approvals grounded in real adversarial, fault-recovery, and rollback evidence. Without personnel holding those responsibilities or with insufficient evidence, `execution_untrusted_tenants_enabled` must remain `false`; removing process or signature requirements cannot authorize exposure. Developer self-verification is not an independent security audit.

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Production-like strong-sandbox adversarial environment | Real untrusted tasks, network/file/resource attacks, Secret canaries, and disclosure response. |
| Multi-Worker/Host fault environment | SIGKILL, lease/heartbeat, late results, cancellation/timeout/cleanup, and quota recovery. |
| PG migration and event environment | 0056/0057 replica upgrade/backfill, Outbox fault points, usage ledger, and audit. |
| Multi-API/SSE environment | Multipage replay, lost notifications, reconnects, expired cursors, and terminal catch-up. |
| React/Codex regression environment | Phase 0 baseline, historical Runs/events/configuration, and existing execution paths. |

**Prerequisites**: Phases 0–5 accepted; Phase 0 baseline completed; all applicable `04-test-plan.md` cases pass with no P0/P1; real sandbox, multi-Worker, and fault-point environments have no pending_env; migrations rehearsed on a production-data replica. Use disposable dedicated hosts/networks/volumes and at least two dedicated tenants. Real Secrets are prohibited; only revocable canaries are allowed.

## 3. Functional Acceptance Checklist (AC-1–AC-16)

| # | Acceptance steps | Pass criterion | Traceability |
|---|---|---|---|
| A1 | Create, rotate, and revoke credentials; tamper bindings, read cross-tenant, and remove the master key. | Public views/storage contain no plaintext; versions/revocation work, every anomaly fails closed with audit. | AC-1; FR-1 |
| A2 | Issue a short-lived grant, then use it cross-Run, with expanded scope, after expiry, replayed, and as an old grant during Resume. | Only original Run/Engine/scope works; all others deny, Resume issues a new grant, and audit contains no Secrets. | AC-2; FR-2 |
| A3 | Inject canaries into every output surface and simulate one real disclosure response. | Ordinary output is redacted/quarantined; credentials revoke, new executions stop, forensics contain no plaintext, and no secondary disclosure occurs. | AC-3; FR-3 |
| A4 | Attempt escape, privilege escalation, fork bomb, and memory/disk exhaustion; launch after removing the sandbox. | Attacks are contained/terminated without host/other-Execution impact; no sandbox means launch denial. | AC-4; FR-4 |
| A5 | Attempt unauthorized egress, DNS rebinding, metadata access, redirects, and proxy bypass. | Actual network boundaries deny everything unauthorized, minimal allowlists apply, and no decoy hits or credential disclosures occur. | AC-5; FR-5 |
| A6 | Attempt traversal, links, devices, host paths, cross-tenant access, and malicious-artifact attacks. | Every escalation denies, valid files remain controlled, and no suspicious artifact publication or cleanup residue occurs. | AC-6; FR-6 |
| A7 | After A expires and B takes over, let A attempt every write and resource-release type. | B has a larger epoch; A has zero effective writes/partial commits, with complete Fencing audit. | AC-7; FR-7 |
| A8 | Inject Worker SIGKILL, heartbeat stall, lease expiration, and late success from the old Worker. | Recovery path is explicit, terminal state is unique, old results do not overwrite, and no dual Workers/terminal states occur. | AC-8; FR-8 |
| A9 | Cancel/time out with exit, hang, cleanup failure, and Worker loss injected separately; reconcile resources/quotas. | Report cancelled only after confirmed exit/cleanup; anomalies alert explicitly, with no orphaned resources or quota leaks. | AC-9; FR-9 |
| A10 | Request retry after pre-launch failure, ambiguous timeout, post-external-write disconnection, and Outbox retry. | Only side-effect-free scenarios auto-retry; ambiguous/side-effecting cases do not replay blindly, attempts remain traceable, and effects do not duplicate. | AC-10; FR-10 |
| A11 | Mix v1/new-version events, inject invalid schemas, and allocate sequence concurrently. | History remains compatible, versions are explicit, seq is monotonic without conflicts; invalid input is diagnosed without renumbering history. | AC-11; FR-11 |
| A12 | Resend native events and crash before/after transaction commit and Outbox publication. | No duplicate seq/usage/business effects or partial terminal state; recovery rescans and event_id consumers are idempotent. | AC-12; FR-12 |
| A13 | Produce multiple event pages, drop notifications, disconnect/reconnect, and use invalid/expired cursors to catch terminal state. | No silent gaps within retention, event_id deduplicates and SSE id remains compatible; 400/409 are correct and final event agrees. | AC-13; FR-13 |
| A14 | Duplicate/replay usage, submit old-epoch usage, provider corrections, and missing fields, then rebuild aggregates. | One source counts once, old epochs deny, corrections remain traceable, unknown is not zero-filled, and rebuilds agree. | AC-14; FR-14 |
| A15 | Inject malformed/unknown/oversized/continuous errors and Secret samples. | Classification, correlation, redaction, rate limiting, and skip/quarantine/fail behave correctly without event storms/disclosure. | AC-15; FR-15 |
| A16 | Upgrade planned migrations on a data replica, roll out/roll back capabilities, and run React/Codex/API/SSE regressions. | Online expansion/backfill is correct, security does not degrade, data is retained, Outbox loses nothing, and Phase 0 diff is zero. | AC-16; FR-16 |

Record for every scenario: executor, date, environment, versions, attack/fault point, prerequisite data, actual result, verdict, and log/DB/Host/network evidence links. Mark unavailable hard-gate environments `pending_env`; neither the phase nor untrusted exposure may pass.

**Evidence reuse**: A1–A16 directly reference the corresponding UT/IT/CM, CI, adversarial, fault-point, DB, Host, network, and Outbox/SSE evidence in `06-test-report.md` wherever possible instead of manually repeating the full suite. Disclosure, escapes, stale writes, duplicate events/usage/billing, and regression diff are assessed directly from A/C criteria without a second business-metric acceptance round; evidence reuse does not reduce the attack matrix, fault points, or independent-approval exception.

## 4. Key Manual Checks

Use these only to supplement client semantics and messaging that automation does not fully cover. Record executor, target SHA, result, and evidence for each; do not create client or business-representative roles.

| # | Check | Pass criterion |
|---|---|---|
| M1 | Exercise disconnect/reconnect, reset beyond retention, and transient-delta loss in the client | Business events are neither duplicated nor silently lost; reset messaging is explicit and safe; final answers, historical events, and existing Run API behavior remain consistent |
| M2 | Request cancellation and observe request, confirmation, and abnormal states | Request and confirmation semantics are clear, with no false success where the UI says cancelled while the process still runs |
| M3 | Inspect security-denial, credential-expiry, cleanup-failure, and manual-retry messages | Messages contain no Secrets/host details and retain correlation information needed for operational diagnosis |

## 5. Security, Data, and Release Hard Gates

| # | Check | Verdict | Traceability |
|---|---|---|---|
| C1 | Credentials/grant Tokens never appear in plaintext in databases, logs, events, SSE, diagnostics, artifacts, or audit. | Veto item | FR-1–FR-3; G1 |
| C2 | Untrusted execution requires a strong sandbox and never degrades to host execution when sandbox is disabled/fails. | Veto item | FR-4; G2 |
| C3 | Network denies by default, and private/metadata/DNS/proxy bypass plus cross-tenant file attacks all pass adversarial tests. | Veto item | FR-5, FR-6; G2 |
| C4 | Every Worker write and resource operation uses Epoch/Fencing, with zero effective stale commits. | Veto item | FR-7; G3 |
| C5 | Worker loss, late results, cancellation, cleanup, and terminal/final events remain consistent, with no false cancelled state. | Veto item | FR-8, FR-9; G3, G4 |
| C6 | Retries never blindly replay ambiguous side effects, quota/resources/grants leave no residue, and duplicate billing is zero. | Veto item | FR-9, FR-10, FR-14 |
| C7 | State+event+Outbox+required usage commit atomically, and Event Store is the source of truth. | Must pass | FR-12; G5 |
| C8 | SSE has no silent gaps within retention, expired cursors return explicit 409, event_id deduplicates, and id=seq remains compatible. | Must pass | FR-13; G5 |
| C9 | Parser diagnostics are bounded/redacted/rate-limited, and usage source idempotency/corrections are traceable. | Must pass | FR-14, FR-15; G6 |
| C10 | Recheck head before implementing 0056/0057, expand/backfill online, never modify historical migrations, and retain data on rollback. | Must pass | FR-16; G7 |
| C11 | React/Codex, Run/API/SSE, and historical configuration have no regressions; baselines pending Phase 0 cannot pass. | Must pass | FR-16; G7 |
| C12 | The untrusted master switch remains false until independent security and SRE/operations approvals complete; no role may waive it. Usage/accounting hard gates remain proven by A14, C6, C9, and reconciliation evidence and are not waived by removing finance sign-off. | Veto item | FR-16; G1–G7 |

**Engineering measurement (not a separate business-acceptance round)**: Record p50/p95, Outbox lag, recovery and migration-lock durations, sample size, and environment under fixed load and fault sets for capacity and release-budget review. Record `not_measured` when unmeasured and never prefill improvements. These records replace no correctness, security, or recovery hard gate.

## 6. Pass Criteria and Acceptance Record

- **Phase pass**: A1–A16 and C1–C12 all pass; M1–M3 are complete or have equivalent automated evidence; no P0/P1 remains, and real adversarial/fault environments have no `pending_env`. Phase pass alone does not authorize untrusted exposure.
- **Conditional pass**: only non-security, non-reliability, non-event/accounting-correctness, non-hard-gate P2/P3 residuals remain, each with owner/deadline and an explanation from the acceptance owner in the record below; even conditional pass does not authorize untrusted exposure.
- **Fail**: any veto item, successful attack, effective stale write, duplicate billing, silent data gap, A/C criterion, or real-environment coverage fails; after fixes, rerun affected items and full adversarial/fault regressions.
- **Separate untrusted-exposure approval**: after phase pass, attach independent security and SRE/operations approval records specifying target SHA, tenant scope, small-batch plan, evidence links, and revocation conditions. Without the required personnel or evidence, keep `execution_untrusted_tenants_enabled=false`.

Produce the Phase 6 Acceptance Report with A/C evidence links, attack/fault matrices, automated reconciliation data, migration/rollback evidence, key manual checks, engineering measurements, residuals, and the single acceptance record below; routine multi-role signatures are not required. Link independent untrusted-exposure approvals separately rather than letting the acceptance owner self-approve them.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence/residuals |
|---|---|---|---|---|---|
| To be filled | To be filled (may be the acceptance owner) | To be filled | To be filled | Pending acceptance | To be filled; untrusted exposure remains off by default |
