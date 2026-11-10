# Phase 5 · Codex Integration — Acceptance Plan

> Status: Pending implementation (execute before this phase goes live; not currently accepted)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G6 and success metrics), `02-requirements.md` (AC-1–AC-12); test execution is governed by `04-test-plan.md`

## 1. Acceptance Objectives and Organization

Accept and unlock Stage B only after Stage A proves stable on controlled real Codex CLI. Confirm **functional correctness** (every AC reproduced), **business effectiveness** (metrics achieved), and **safe release** (trusted-tenant hard gate, cleanable processes, and switch rollback) for both Protocols, then record a signed conclusion.

| Role | Responsibility |
|---|---|
| Product owner | Chairs acceptance; judges common Run/streaming experience; signs P2 residual disposition. |
| QA | Executes AC/A scenarios and evidence; owns Stage A gate and regression conclusions; classifies defects. |
| Engineering lead | Provides Codex/Host/Session environments, metric data, fixes, and rollback drills. |
| Security owner | Accepts trusted-tenant, Workspace, credential, and Secret adversarial cases; has veto over untrusted-tenant exposure. |
| SRE/operations lead | Judges real process/connection cleanup, monitoring/alerts, canary rollout, and rollback. |
| Trusted-tenant business representative | Performs coding-task UAT and judges native-event and final-result usability. |

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Production-like controlled Codex environment | Pinned real CLI/App-Server versions, dedicated low-privilege accounts, functional and metric acceptance. |
| Phase 4 RuntimeHost/Workspace environment | Process-tree, mount, cancellation/timeout/crash, and cleanup evidence. |
| PG migration and regression environment | Conditional Session migration, Run/event persistence, and React/SSE regressions. |
| Quickstart (no real Secrets) | Verifies default-off, deployment placeholders, and React compatibility; does not substitute for real Codex acceptance. |

**Prerequisites**: Phases 0–4 accepted; Phase 0 baseline completed; all applicable `04-test-plan.md` cases pass with no P0/P1; Stage B acceptance additionally requires P5-IT-18 and three consecutive pre-release regression evidence sets. Use at least two dedicated tenants and Workspaces isolated from other test data; real credentials are Secret-managed and revoked after acceptance.

## 3. Functional Acceptance Checklist (AC-1–AC-12)

| # | Acceptance steps | Pass criterion | Traceability |
|---|---|---|---|
| A1 | Submit a CLI task as a trusted tenant on a pinned version; inspect Orchestrator, Host, Run, and public response. | Task completes with correctly correlated output/artifacts; Host manages the process and public APIs expose no PID/host path. | AC-1; FR-2 |
| A2 | Query Engine/Protocol registration; attempt App-Server enablement without and then with complete Stage A evidence. | Both share the `codex` Engine with independent Protocols; no evidence means denial, and complete evidence plus approval unlocks. | AC-2; FR-1 |
| A3 | Run CLI/App-Server tasks producing messages, commands, file changes, and usage, then a task without usage. | Platform and native events are retained and correlated; usage is accurate or explicitly unknown, never zero-filled. | AC-3; FR-4 |
| A4 | Cancel and time out both execution types with child processes, then simulate cleanup failure. | Normal cases actually exit and release resources within the grace period; abnormal cases explicitly fail/alert without false cancelled/completed. | AC-4; FR-3 |
| A5 | Run a valid Workspace task, then submit traversal, symlink, and cross-tenant read/write attacks. | Valid restricted access succeeds; every attack is denied/safely terminated and audited, with no unauthorized file changes. | AC-5; FR-5 |
| A6 | Execute with a Secret canary and controlled reference; inspect host auth paths, logs/events/API; launch as an untrusted tenant. | The canary does not leak, host auth is invisible, only the target Execution can use it, and untrusted tenants are denied. | AC-6; FR-6 |
| A7 | In Stage B, perform JSON-RPC initialization, concurrent Turns, disconnection, and unknown/late responses; inspect public APIs. | IDs do not cross-wire, anomalies reach terminal states with diagnostics, and no private-protocol public endpoint or field exists. | AC-7; FR-7 |
| A8 | Create an App-Server Session, execute multiple Turns/Runs, expire it, and repeat cleanup. | Mapping/metadata versions are correct, expired Sessions cannot Resume, cleanup is idempotent, and CLI is unaffected. | AC-8; FR-8 |
| A9 | Request streaming, approval, and interactive input under Effective allow/deny policies, then cancel waiting. | Allowed flows use the common contract; denied flows have no side effects/auto-approval; waits are bounded and cancellable. | AC-9; FR-9 |
| A10 | Resume legitimately, then retry with different tenant, Conversation, Workspace, credential, and Adapter. | Only attempts passing full reauthorization resume; all others are denied and audited without reusing old authorization. | AC-10; FR-10 |
| A11 | Inject unknown version, bad CLI output, invalid JSON-RPC, and missing usage; inspect errors and telemetry. | Stable errors/unknown appear without raw exceptions or Secrets; issues are locatable by Run/Protocol/version. | AC-11; FR-11 |
| A12 | Disable all Codex switches; run React, historical configuration, Run/API/SSE regressions, and rollback. | New Codex execution is denied; Phase 0 diff is zero; rollback drops no tables and rewrites no historical Runs. | AC-12; FR-12 |

Record for every scenario: executor, date, environment, Codex/Adapter versions, prerequisite data, actual result, verdict, and screenshot/log/Host-cleanup evidence links. Mark unavailable real-environment items `pending_env` with an assigned acceptor; never record them as passed.

## 4. UAT Decision (Trusted-tenant Business Representative)

- Common Run submission, streaming progress, approvals/input, and final results follow existing usage patterns without requiring knowledge of the Codex private protocol.
- Native command/file events explain task progress, and malformed/failure messages are understandable without exposing host details or Secrets.
- Session Resume preserves the correct business context; denied recovery fails safely rather than silently creating a new Session and pretending recovery succeeded.
- Before Stage A is stable, product UI and configuration must not advertise App-Server as available to ordinary users.

## 5. Business Metric Acceptance

| Metric | Baseline | Target | Measurement method | Traceability |
|---|---|---|---|---|
| Number of Codex Protocols | 0 | Stage A=1, Stage B=2 | Compare registry evidence and real executions, checking shared Engine ID. | G1, G2 |
| Contract and end-to-end pass rate | Pending Phase 0 | 100%, no P0/P1 | Aggregate UT/IT/CM, A1–A12, and the defect register. | G1–G6 |
| Stage A stability gate | Pending Phase 0 | Three consecutive regressions + ≥20 mixed scenarios with no P0/P1 | Inspect test reports, run links, and unlock sign-off. | G5 |
| Event/usage correlation completeness | Pending Phase 0 | 100%, missing values explicitly unknown | Cross-check events, results, and usage for the Run inventory; never replace missing values with zero. | G3 |
| Cancellation/timeout cleanup rate | Pending Phase 0 | 100% of applicable scenarios | Compare Host process-tree/connection/mount evidence with terminal states item by item. | G1, G6 |
| Disclosure and untrusted exposure | Security baseline pending Phase 0 | Disclosure=0, untrusted exposure=0 | Secret canaries, cross-tenant adversarial cases, and configuration/audit scans. | G4 |
| React regression differences | Pending Phase 0 | diff=0 | Compare switch-off behavior with Phase 0 snapshots and existing suites. | G6 |
| Startup/execution latency | Pending Phase 0 | Record p50/p95; freeze budgets after review | Measure pinned versions and task sets; publish sample size/environment with the report. | G1, G2 |

## 6. Compliance Checks

| # | Check | Verdict | Traceability |
|---|---|---|---|
| C1 | Credentials never enter plaintext Agent configuration, command-line logs, ordinary events, SSE, or public errors. | Veto item | FR-6, FR-11; G4 |
| C2 | Host `~/.codex/auth.json` is never copied/mounted, and credential directories are not shared across tenants. | Veto item | FR-6; G4 |
| C3 | Zero untrusted tenants are enabled before the complete Phase 6 Broker/strong sandbox is finished. | Veto item | FR-6; G4 |
| C4 | Workspace traversal, symlinks, and cross-tenant access are denied, and Session Resume fully reauthorizes. | Veto item | FR-5, FR-10 |
| C5 | CLI and App-Server share an Engine with independent Protocols; public APIs expose no private JSON-RPC protocol. | Must pass | FR-1, FR-7 |
| C6 | Cancellation/timeout relies on real process and connection cleanup, and failures are not falsely reported as terminal success. | Must pass | FR-3 |
| C7 | Stage B cannot merge/enable or advertise availability before the Stage A stability gate passes. | Must pass | FR-1; G5 |
| C8 | Planned 0055 is added only when needed; head is rechecked before implementation, historical migrations remain unchanged, and rollback drops no tables. | Must pass | FR-8, FR-12 |
| C9 | React, existing Run/API/SSE, and historical configuration have no regressions; an unmeasured Phase 0 baseline cannot pass. | Must pass | FR-12; G6 |
| C10 | Tests/acceptance include adversarial and fault injection; every real-environment skip is pending_env with an owner. | Must pass | G1, G4, G6 |

## 7. Pass Criteria and Sign-off

- **Stage A pass / Stage B unlock**: A1–A6, A11–A12, and Stage A-applicable C items pass, P5-IT-18 evidence is complete, and no P0/P1 remains; Stage B being locked does not constitute overall phase acceptance.
- **Pass**: A1–A12 all pass, hard metrics are achieved, C1–C10 all pass, no P0/P1 remains, and no real-Codex environment item is pending_env.
- **Conditional pass**: Only non-security, non-Stage-gate P2/P3 residuals remain, each with owner and deadline; hard metrics and every veto item pass.
- **Fail**: Any veto item, Stage ordering, hard metric, or real-environment coverage fails; after fixes, rerun affected items and regressions.

Produce the Phase 5 Acceptance Report containing Stage A unlock evidence, AC/A execution records, metric data, compliance results, residuals, conclusion, and signatures (product / QA / engineering / security / SRE).
