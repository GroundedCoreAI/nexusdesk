# Phase 5 · Codex Integration — Test Plan

> Status: Pending implementation (execute after this phase is developed; not currently executed or passed)
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence and remove multi-role sign-off requirements)
> Basis: `02-requirements.md` (FR-1–FR-12, AC-1–AC-12), `03-technical-design.md` (Stages A/B, RuntimeHost, Sessions, planned migration 0055)

## 1. Test Scope and Principles

**Scope**: Codex CLI Adapter, App-Server Adapter, JSON-RPC, native events/usage, RuntimeHost integration, Workspace/credential policy, Sessions/Resume, configuration switches, conditional Session migration, and React regressions.

**Principles**:

1. **Stage order is mandatory**: Stage B enablement tests first verify gate denial, then unlock with complete Stage A pass evidence; product gates cannot be bypassed with mocks.
2. **Switch fallback is mandatory**: With CLI/App-Server/Session independently disabled, React and existing behavior match the Phase 0 baseline point by point.
3. **Real processes are mandatory**: Assert process exit, process-tree cleanup, and connection closure using OS/Host evidence, not coroutine cancellation alone.
4. **Security adversarial cases are mandatory**: Include path traversal, symlinks, cross-tenant access, host auth files, Secret canaries, and untrusted tenants as negative cases.
5. **Fault injection is mandatory**: Crash, hang, disconnection, malformed/duplicate/late messages, and missing usage must not become false success or permanent waits.
6. **Time cases do not wait**: Use a controllable clock or direct state construction for Session expiration, timeout, and grace periods; retain bounded timeouts for real-process tests.
7. **Record baselines honestly**: Mark unmeasured performance, React behavior, and regression baselines “pending Phase 0”; never record skip as pass.
8. **Reuse evidence**: A/C acceptance directly references automated UT/IT/CM results and real Codex, Host, PG, and SSE evidence instead of manually repeating the full suite; manual work is limited to key checks that cannot be automated.

## 2. Test Environments and Data Construction

| Environment | Purpose |
|---|---|
| Unit (no DB) | Configuration/version, argument allowlist, event fixtures, JSON-RPC state machine, error mapping, and Session policy. |
| Integration (PG + pytest postgres fixture) | Run/event persistence, conditional Session migration and Repository, and tenant/Conversation binding. |
| Controlled Codex environment | Pinned verified CLI/App-Server versions with dedicated low-privilege accounts and non-production credentials. |
| RuntimeHost/sandbox prerequisite environment | Actual Phase 4 Host, process groups, mounts, resources, and cleanup observability; no untrusted-tenant exposure before Phase 6. |
| React/SSE regression environment | Existing DemoModel, Run API, `after`/`Last-Event-ID`, historical Agent configuration, and event fixtures. |

**Data construction conventions**: Use at least two tenants and two Conversations/Workspaces; use Secret canaries and controllable tasks containing child processes and file writes, plus valid/malformed/unknown-version protocol fixtures. Real Codex test credentials are injected as deployment Secrets and never committed. If a controlled real version is unavailable, mark related IT `pending_env`; all-mock runs cannot substitute for acceptance.

## 3. Unit Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P5-UT-01 | Register two Protocols for one Engine | Both use Engine ID `codex`, Adapters/Protocols resolve independently, and unknown combinations are denied. | FR-1 |
| P5-UT-02 | Stage A gate state machine | Stage B cannot enable without evidence, can enable with complete evidence, and disabling Stage A blocks new Stage B executions. | FR-1, FR-12 |
| P5-UT-03 | Codex version compatibility matrix | Supported versions pass; empty allowlist and unknown/incompatible high/low versions fail closed. | FR-1, FR-2 |
| P5-UT-04 | Typed configuration and capability narrowing | Invalid fields/timeout limits are denied; Agent configuration cannot expand deployment Effective capabilities. | FR-2, FR-12 |
| P5-UT-05 | CLI argument and environment allowlist | Only allowed arguments are generated; arbitrary client arguments, sensitive host environment, and auth paths never enter the invocation. | FR-2, FR-6 |
| P5-UT-06 | CLI valid/chunked/malformed output fixtures | Chunks reassemble correctly; platform/native events correlate with the Run, and malformed input produces bounded ProtocolError. | FR-4, FR-11 |
| P5-UT-07 | Usage extraction and absence | Supported fields normalize correctly; missing/partial fields are unknown, not zero-filled, and model names are not invented. | FR-4 |
| P5-UT-08 | Error and cancellation mapping | EngineUnavailable, AuthenticationError, Timeout, Cancelled, and others map stably without exposing raw exceptions. | FR-3, FR-11 |
| P5-UT-09 | Workspace path and link validation | Traversal, absolute paths, symlinks, and cross-tenant mounts are denied before launch. | FR-5 |
| P5-UT-10 | Credential reference and trust boundary | Missing references, cross-tenant use, and untrusted tenants are denied; logs and serialized exceptions contain no Secrets. | FR-6 |
| P5-UT-11 | JSON-RPC framing and version negotiation | Chunking, concurrent IDs, error responses, and negotiation failures behave correctly; method schemas stay out of public models. | FR-7 |
| P5-UT-12 | Duplicate/unknown/late JSON-RPC responses | Turns do not complete incorrectly, side-effecting requests are not replayed automatically, and waiters exit within bounds. | FR-7, FR-11 |
| P5-UT-13 | Approval/input capability gate | Non-Effective capabilities are denied; unknown requests are not auto-approved, and responses match only the original request. | FR-9 |
| P5-UT-14 | Session/Turn/Run mapping and metadata version | Multiple Turns correlate with one Session and independent Runs; incompatible metadata denies Resume. | FR-8 |
| P5-UT-15 | Full Session Resume reauthorization | Any change to tenant, Conversation, Workspace, state, credential, Protocol, or Adapter causes denial. | FR-10 |
| P5-UT-16 | Reentrant Session expiration cleanup | Repeated expiration/closure does not duplicate release or fail unexpectedly, and expired Sessions cannot resume. | FR-8, FR-10 |
| P5-UT-17 | Log/event diagnostic bounds | Oversized stderr, JSON-RPC payloads, and Secret canaries are truncated/redacted, with no host details in public responses. | FR-11, FR-6 |
| P5-UT-18 | Codex switches and React default | React resolves by default; every Codex switch defaults false and disabled execution cannot be constructed. | FR-12 |

## 4. Integration Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P5-IT-01 | Controlled real CLI successful execution | Complete AC-1 through Orchestrator/Host with correct Workdir, output, artifacts, terminal state, and Run correlation. | AC-1 |
| P5-IT-02 | Two-Protocol registration and Stage unlock | Reproduce AC-2; App-Server is denied at both configuration and runtime before the gate is met. | AC-2 |
| P5-IT-03 | CLI native events and usage end to end | Message/command/file events retain fidelity and ordered correlation, with correct final usage or unknown. | AC-3 |
| P5-IT-04 | App-Server native stream and usage end to end | Notifications and stable events coexist, and Turn results correlate with the same Run. | AC-3 |
| P5-IT-05 | CLI user cancellation with grandchild process | Process group actually exits, mounts/temp resources are released, and late success cannot overwrite the Run. | AC-4 |
| P5-IT-06 | CLI/App-Server timeout and hang | Graceful/forced termination follows the deadline, and cleanup failure produces explicit error and alert. | AC-4 |
| P5-IT-07 | Codex process crash and App-Server disconnection | No connection/process remains, the Run reaches a diagnosable terminal state, and nothing waits forever. | AC-4, AC-7 |
| P5-IT-08 | Valid Workspace I/O and escape adversarial cases | Valid tasks succeed; traversal, symlinks, and cross-tenant reads/writes are denied and audited. | AC-5 |
| P5-IT-09 | Minimal credential exposure and Secret canary | Only the target Execution can use the credential; logs, events, and APIs contain no canary, and host auth files are invisible. | AC-6 |
| P5-IT-10 | Untrusted tenant and trust revocation | Deny by default; trust revoked before execution prevents launch, and new Resume cannot reuse old trust. | AC-6, AC-10 |
| P5-IT-11 | JSON-RPC concurrency, disconnection, and abnormal responses | Reproduce AC-7 without request crossover or public private-protocol routes, with diagnosable anomalies. | AC-7 |
| P5-IT-12 | Session persistence, multiple Turns, and expiration | After conditional migration upgrade, reproduce AC-8; CLI remains unaffected when Sessions are disabled. | AC-8 |
| P5-IT-13 | Approval/input allow, deny, and wait cancellation | Reproduce AC-9; denial has no file/command side effects, and waits can time out/cancel. | AC-9 |
| P5-IT-14 | Valid Session Resume and cross-boundary adversarial cases | Reproduce AC-10; every attempt reauthorizes and produces an independent Run/audit trail. | AC-10 |
| P5-IT-15 | Unsupported version, bad output, and missing-usage fault injection | Reproduce AC-11 with stable errors/unknown, no Secrets, and correlated diagnostics. | AC-11 |
| P5-IT-16 | Switch-off React/API/SSE/historical-configuration regression | Reproduce AC-12; diff is zero when a Phase 0 baseline exists, otherwise mark blocked pending baseline rather than passed. | AC-12 |
| P5-IT-17 | Conditional Session migration upgrade/downgrade protection | Upgrade from the implementation-time head succeeds; populated downgrade requires export, and historical migration checksums remain unchanged. | FR-8, G6 |
| P5-IT-18 | Stage A pre-release stability batch | At least 20 mixed scenarios have no P0/P1, and three consecutive applicable regressions pass before the acceptance owner confirms the Stage B unlock record. | FR-1; G5 |

## 5. General Checks (Applicable to This Phase)

| ID | Check | Pass criterion | Traceability |
|---|---|---|---|
| P5-CM-01 | Migration planning number and historical protection | Recheck head before implementation; add 0055 only if Stage B needs it, with no historical migration changes. | FR-8, G6 |
| P5-CM-02 | Configuration loading and default denial | All switches default off and environment overrides work; empty version/trust allowlists cannot start Codex. | FR-12, FR-6 |
| P5-CM-03 | Secret and sensitive-argument scan | Logs, events, SSE, errors, audit, and tests contain no real Secret/canary/host auth content. | FR-6, FR-11 |
| P5-CM-04 | Tenant and Session isolation | Every Repository query and Resume includes trusted tenant and Conversation/Workspace constraints. | FR-5, FR-10 |
| P5-CM-05 | Native protocol boundary | Public OpenAPI/responses contain no JSON-RPC methods, host PIDs, sensitive arguments, or private errors. | FR-2, FR-7 |
| P5-CM-06 | Process and connection resources | No orphaned processes/FDs/temp mounts; cancellation, timeout, and crash all produce cleanup evidence. | FR-3 |
| P5-CM-07 | Observability and audit | Run/Protocol/Adapter/Session correlation, versions, exit codes, usage unknown, and security denials are queryable. | FR-11 |
| P5-CM-08 | Bilingual and requirement traceability | Chinese/English structure, IDs, and table rows match; UT/IT/CM, A, and AC remain traceable. | G6 |

## 6. Regression Scope

- `backend/tests/test_runtime_postgres.py`: claim, cancellation race, Worker loss, late results, durable events, and SSE replay.
- Applicable suites for React Runtime, RuntimeFactory, historical Agent configuration, Run API, SSE `after`/`Last-Event-ID`, and existing frontend event consumption.
- Workspace, tool credential/network, and model-gateway credential suites to confirm the new Codex path does not change existing boundaries.
- Full migration chain and upgrade from the actual implementation-time head; never rewrite 0001–0052 or other merged historical migrations.
- If the Phase 0 baseline is absent, mark performance, compatibility diff, and existing-behavior items “pending Phase 0” as exit blockers rather than waivers.

## 7. Defect Severity and Exit Criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocker | Secret/cross-tenant disclosure; accidental untrusted-tenant exposure; primary execution-path breakage; data loss; uncontrolled processes. | Disable relevant switches immediately; fix and run full regression before continuing. |
| P1 critical | Incorrect terminal state/cleanup; ineffective Stage gate; unauthorized Session access; public protocol disclosure; ineffective switch. | No acceptance or Stage B unlock before resolution. |
| P2 major | Non-core event/usage mapping deviations, bounded diagnostics, or quality deviations. | Only non-hard-gate items may proceed after owner/deadline are recorded and the acceptance owner confirms conditional acceptance in the single acceptance record; never conceal security items. |
| P3 minor | Wording, non-sensitive logging, and documentation issues. | Schedule fixes and retain traceability. |

**Exit criteria**: Stage B unlocks only after all applicable Stage A UT/IT/CM and AC-1–AC-6, AC-11–AC-12 pass and P5-IT-18 completes. Overall phase exit requires all applicable cases and ACs to pass, no unapproved skips in real-Codex environment items, green regressions, zero switch-off diff, and no open P0/P1 defects. Before Phase 6, “untrusted multi-tenant exposure” is not an acceptable pass scope.
