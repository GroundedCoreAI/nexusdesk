# Phase 5 · Codex Integration — Acceptance Plan

> Status: Pending implementation (execute before this phase goes live; not currently accepted)
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence; remove standalone UAT, duplicate metrics, and multi-role sign-off)
> Revised: 2026-11-17 (aligned to the minimal-core-team acceptance standard: single acceptance owner, phase acceptance separated from high-risk capability enablement; technical criteria and hard gates unchanged)
> Revised: 2026-11-18 (scope-limited acceptance revision: startup/execution p50/p95, sample sizes, matched pairs, CI provenance and final-PR-head CI runs/URLs, real or authorized historical samples, multi-sample/large-sample data-volume requirements, a missing Phase 0 baseline, and controlled real-Codex release-environment `pending_env` items are no longer stage-acceptance gates and remain only as historical context or explicit out-of-scope notes; Stage B unlock conditions are retained separately. Retained gates are Stage A switch completeness, tenant isolation, Secret/credential handling, process cleanup, data integrity and migration, terminal-state semantics, no P0/P1, and a single acceptance-owner record; Stage B stays locked. See §6.1)
> Basis: `01-business-goals.md` (G1–G6 and success metrics), `02-requirements.md` (AC-1–AC-12); test execution is governed by `04-test-plan.md`

## 1. Acceptance Scope and Responsibility

Unlock Stage B only after Stage A proves stable on controlled real Codex CLI, with evidence for both Protocols' ACs, trusted-tenant boundaries, process cleanup, and switch rollback. By default, the acceptance owner organizes, confirms Stage unlock records, and records decisions while the executor prepares environments, performs supplementary checks, and organizes evidence; one person may hold both responsibilities. Do not invent independent product, QA, business, security, or SRE roles, create no multi-role sign-off sheet, and run no independent UAT round. Developer self-verification proves conformance to this document, not real trusted-tenant user acceptance or an independent security audit. Phase acceptance does not constitute authorization to enable high-risk capabilities such as untrusted multi-tenant code execution or production engine routing; such enablement requires a separate independent security and operations approval record.

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Production-like controlled Codex environment | Pinned real CLI/App-Server versions, dedicated low-privilege accounts, functional and metric acceptance. |
| Phase 4 RuntimeHost/Workspace environment | Process-tree, mount, cancellation/timeout/crash, and cleanup evidence. |
| PG migration and regression environment | Conditional Session migration, Run/event persistence, and React/SSE regressions. |
| Quickstart (no real Secrets) | Verifies default-off, deployment placeholders, and React compatibility; does not substitute for real Codex acceptance. |

**Prerequisites**: Phases 0–4 accepted; all applicable `04-test-plan.md` cases pass with no P0/P1. Use at least two dedicated tenants and Workspaces isolated from other test data; real credentials are Secret-managed and revoked after acceptance. (Scope-limited revision 2026-11-18: the former "Phase 0 baseline completed" prerequisite is no longer a stage-acceptance gate, see §6.1; P5-IT-18 and three consecutive pre-release regressions remain a separate high-risk Stage B unlock condition and do not block Stage A / this phase's switch and functional acceptance; Stage B stays locked.)

## 3. Functional Acceptance Checklist (AC-1–AC-12)

| # | Acceptance steps | Pass criterion | Traceability |
|---|---|---|---|
| A1 | Submit a CLI task as a trusted tenant on a pinned version; inspect Orchestrator, Host, Run, and public response. | Task completes with correctly correlated output/artifacts; Host manages the process and public APIs expose no PID/host path. | AC-1; FR-2 |
| A2 | Query Engine/Protocol registration; attempt App-Server enablement without and then with complete Stage A evidence. | Both share the `codex` Engine with independent Protocols; no evidence means denial, and unlock requires complete evidence plus the acceptance owner's confirmation of the unlock record. | AC-2; FR-1 |
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

**Prompt delivery (implementation-time addition, 2026-11-14, `08` R18).** A1's real half additionally requires the prompt to reach the CLI on stdin: the Stage A lane encodes the request input to a bounded `stdin_payload` that the Host writes and EOF-closes, and the real binary must complete its Turn from it (exit 0, a `turn.completed` usage block) rather than exiting 1 with `No prompt provided via stdin.`. A child that closes early or never reads must fail the start closed with `runtime_host_pipe_setup_failed` and leave no process group. The prompt must never appear in argv, the environment, a filename, a log line, an event payload, or `command_digest`. Where no Codex binary exists the real half stays `pending_env`; the deterministic fixture half is mandatory everywhere.

Record for every scenario: executor, date, environment, Codex/Adapter versions, prerequisite data, actual result, verdict, and screenshot/log/Host-cleanup evidence links. Mark unavailable real-environment items `pending_env` with an assigned acceptor; never record them as passed.

**Evidence reuse**: A1–A12 directly reference the corresponding UT/IT/CM, CI, real Codex, Host, PG, and SSE evidence in `06-test-report.md` wherever possible instead of manually repeating the full suite. Protocol count, Stage gates, event/usage correlation, cleanup, disclosure, and React diff are assessed directly from A/C criteria without a second business-metric acceptance round.

## 4. Key Manual Checks

Use these only to supplement common UI and error behavior that automation does not fully cover. Record executor, target SHA, result, and evidence for each; do not create a trusted-tenant business-representative role.

| # | Check | Pass criterion |
|---|---|---|
| M1 | Submit a task in the common UI and inspect streaming progress, approvals/input, and the final result | No Codex private-protocol knowledge is required; native command/file events explain progress, and the UI does not advertise App-Server before Stage A is stable |
| M2 | Inspect malformed/failure messages and perform valid and denied Session Resume attempts | Messages are understandable without host details or Secrets; valid Resume preserves context, while denial fails safely without silently creating a Session and claiming recovery |

## 5. Security, Data, and Release Hard Gates

| # | Check | Verdict | Traceability |
|---|---|---|---|
| C1 | Credentials never enter plaintext Agent configuration, command-line logs, ordinary events, SSE, or public errors. | Veto item | FR-6, FR-11; G4 |
| C2 | Host `~/.codex/auth.json` is never copied/mounted, and credential directories are not shared across tenants. | Veto item | FR-6; G4 |
| C3 | Zero untrusted tenants are enabled before the complete Phase 6 Broker/strong sandbox is finished. | Veto item | FR-6; G4 |
| C4 | Workspace traversal, symlinks, and cross-tenant access are denied, and Session Resume fully reauthorizes. | Veto item | FR-5, FR-10 |
| C5 | CLI and App-Server share an Engine with independent Protocols; public APIs expose no private JSON-RPC protocol. | Must pass | FR-1, FR-7 |
| C6 | Cancellation/timeout relies on real process and connection cleanup, and failures are not falsely reported as terminal success. | Must pass | FR-3 |
| C7 | Stage B stays locked: App-Server cannot merge/enable or advertise availability without a separate unlock record confirmed by the acceptance owner (revision 2026-11-18: P5-IT-18's "at least 20 scenarios × three consecutive regressions" is a separate high-risk Stage B unlock condition and is no longer a gate for this phase's acceptance, see §6.1). | Must pass (Stage B locked; unlock requires separate approval) | FR-1; G5 |
| C8 | Planned 0055 is added only when needed; head is rechecked before implementation, historical migrations remain unchanged, and rollback drops no tables. | Must pass | FR-8, FR-12 |
| C9 | React, existing Run/API/SSE, and historical configuration have no regressions (revision 2026-11-18: the "unmeasured Phase 0 baseline cannot pass" clause is superseded; the Phase 0 baseline is historical context, see §6.1). | Must pass (functional regressions; a missing baseline does not block) | FR-12; G6 |
| C10 | Tests/acceptance include adversarial and fault injection; every real-environment skip is pending_env with an owner. | Must pass | G1, G4, G6 |

**Engineering measurement (not a separate business-acceptance round)**: Record startup/execution p50/p95, sample size, and environment for pinned versions and task sets to inform release-budget review. Record `not_measured` when unmeasured; never prefill targets or present an observational measurement as a pass. (Revision 2026-11-18: p50/p95, sample sizes, and similar are recording context, not stage-acceptance gates, see §6.1.)

## 6. Pass Criteria and Acceptance Record

> Scope-limited revision 2026-11-18: this section is the authoritative statement of this revision and overrides any contrary wording in this document or in `06`/`07`/`08`; it rewrites no historical execution number or conclusion. The full gate reclassification is in §6.1.

- **Stage A pass**: A1–A6, A11–A12, and the Stage-A-applicable C items all pass on switch completeness, functional correctness, tenant isolation, Secret/credential handling, cleanup, terminal-state, and data-integrity criteria, with no P0/P1 (P5-IT-18 multi-sample batch and controlled real-Codex release-environment evidence are no longer Stage A gates; Stage B unlock conditions are retained separately, see §6.1).
- **Pass**: A1–A12 and C1–C10 all pass; M1–M2 are complete or have equivalent automated evidence; no P0/P1 remains (controlled real-Codex environment / sample-class `pending_env` no longer blocks stage acceptance, see §6.1).
- **Conditional pass**: only non-security, non-Stage-gate, non-hard-gate P2/P3 residuals remain, each with owner/deadline and an explanation from the acceptance owner in the record below; every veto item still passes.
- **Fail**: any veto item, A/C criterion, or switch/function/isolation/Secret/cleanup/migration/terminal-state gate fails (a missing Phase 0 baseline, unmeasured performance samples, absent CI, or incomplete real-environment coverage no longer alone cause a fail); after fixes, rerun affected items and regressions.
- **Enablement note**: phase acceptance does not automatically authorize high-risk capability enablement; Stage B stays locked, and its unlock (including P5-IT-18 and the unlock record), production Codex routing, and untrusted multi-tenant enablement all require a separate approval record.

### 6.1 2026-11-18 Scope-Limited Gate Reclassification

- **No longer stage-acceptance blockers (retained only as historical context or explicit out-of-scope notes)**: startup/execution p50/p95, sample sizes, matched pairs, CI provenance and final-PR-head CI runs/URLs, real or authorized historical samples, multi-sample/large-sample data-volume requirements, a missing Phase 0 baseline (including "unmeasured baseline cannot pass"), controlled real-Codex release-environment `pending_env`, and the P5-IT-18 "at least 20 scenarios × three consecutive regressions" reading as a phase gate. These may be kept as records or as Stage B unlock conditions but no longer block Stage A / this phase's switch and functional acceptance.
- **Still gates**: Stage A switch completeness (default off, explicit on, off/on/rollback, no silent fallback); Engine/Protocol registration and no private JSON-RPC on public APIs; real-process cancellation/timeout cleanup without false terminal success; tenant isolation and Workspace traversal/symlink/cross-tenant denial; no Secret/credential leakage and no visible host auth; CLI prompt delivered over stdin and absent from argv/logs/events; data integrity and migration (head revalidation, no table drop, no rewrite of historical Runs); error/usage terminal-state semantics; no P0/P1; a single acceptance-owner record.
- **Stage B stays locked and separate**: App-Server transport, JSON-RPC end-to-end, Session persistence/Resume, and approvals/interactive input are unimplemented; Stage B unlock (including P5-IT-18 and the unlock record) is a high-risk enablement requiring separate approval and is never auto-unlocked by a phase pass. Production Codex routing and untrusted multi-tenancy are the same.

Produce the Phase 5 Acceptance Report with the Stage A unlock record, A/C evidence links, key manual checks, engineering measurements, residuals, and the single record below; multi-role signatures are not required.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence/residuals |
|---|---|---|---|---|---|
| JackChow (confirmed by the user, 2026-11-19 GMT+8) | WorkBuddy automated acceptance execution | 2026-11-18 | `80fac6056682a7835c61dab4678c5772b8689d1f` | **PASS (scope-limited)** | `../12-scope-limited-acceptance-record-20261118-phase4-6.md` §5; evidence `20261118T150343Z.tar.gz` |


---

## 2026-11-20 P7 Stage A Closure Addendum (Scope-Limited)

Under §6.1 this addendum only appends evidence and a conclusion; it rewrites no historical
criterion, gate definition, or the 2026-11-18 single record. P7 / T17 end-to-end acceptance
was executed on the clean CI image `63221a1fd3ba`. The authoritative record is
`../13-scope-limited-acceptance-record-20261120-phase7-stage-a.md`; verdict
**PASS (scope-limited)**, signed by the single acceptance owner JackChow on
2026-11-20 18:49 (GMT+8).

- **A1 (dialogue turn)**: two consecutive `completed` / `output=OK` runs, eight ordered
  `runtime_events` each; credential `grant_issued → grant_used`, `retained` workdir, and an
  `engine_terminal` usage-ledger row.
- **Tool-use turn**: blocked inside the platform container by Docker's default seccomp
  (`bwrap` cannot create a user namespace, `unshare -Ur` → EPERM). Per the 2026-11-18
  revision it is registered as an **explicit out-of-scope note** — not rewritten as a pass
  and not a stage gate. A host-side `command_execution` turn outside the platform verified
  exit 0, but per `08` §3.6 that is local evidence, not acceptance evidence.
- **A2 / C7 unaffected**: this addendum records the unlock of Stage A (`cli_exec/v1`) for
  the single-tenant quickstart demo; it is **not** the Stage B unlock record referenced by
  A2 / C7 / `04` P5-IT-18. Stage B stays locked; P5-IT-18 and the separate Stage B unlock
  record remain absent and unrequested, requiring independent approval.
- **Gate effect**: §3 / §6 criteria and the 2026-11-18 single record remain the historical
  decision. This addendum appends a new, evidence-bound scope-limited acceptance record
  under that policy. It does not retroactively complete Phase 0/1 formal acceptance and
  does not rewrite any `pending_env` / unmeasured item as a pass.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence / residuals |
|---|---|---|---|---|---|
| JackChow (confirmed by the user, 2026-11-20 GMT+8) | WorkBuddy automated acceptance execution | 2026-11-20 | `63221a1fd3bad7562b351b7bbbd23e0c95500cb6` | **PASS (scope-limited)** | `../13-scope-limited-acceptance-record-20261120-phase7-stage-a.md`; 2026-11-20 addenda in `06` / `07`; residuals: in-container bwrap sandbox boundary, `cleanup_failed` conservative terminal state |
