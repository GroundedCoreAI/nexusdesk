# Phase 5 · Codex Integration — Requirements

> Status: Pending review (planning only, not implemented)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G6); `docs/architecture/agent-execution-platform-v2.md`, Sections 4, 5, 8–10, 12–13, and 17 (Phase 5)

## User Stories

**US-1 (Platform administrator)**: As a platform administrator, I want to enable Codex CLI/App-Server by verified version and independent switch so that I can gradually integrate an external Engine and roll back quickly.

**US-2 (Trusted-tenant user)**: As a trusted-tenant user, I want Codex to complete tasks in an authorized Workspace and return streaming progress and final results so that I can use its native coding capabilities without changing existing Run usage.

**US-3 (Platform developer)**: As a platform developer, I want both Protocols to implement the same Adapter contract and share the Codex Engine identity so that I can extend protocols without modifying the Worker.

**US-4 (Operator)**: As an operator, I want cancellation, timeout, crash, and disconnection to clean up real processes and connections so that orphaned processes, resource leaks, and incorrect terminal states are avoided.

**US-5 (Security owner)**: As a security owner, I want credentials exposed only under Execution and policy control, with untrusted tenants denied by default, so that the attack surface does not grow before the complete Phase 6 security capabilities land.

**US-6 (Conversation user and auditor)**: As a conversation user and auditor, I want App-Server Sessions to resume securely with end-to-end traceability so that context continues without reusing cross-tenant or expired authorization.

## Functional Requirements

### FR-1 Staged registration and stability gate

| Item | Description |
|---|---|
| Trigger | When deployment registers an Adapter, resolves Agent Engine configuration, or requests Stage B enablement. |
| Input | `engine_id`, `protocol_id`, `adapter_version`, Codex version, Stage A gate evidence, and deployment switches. |
| Output | Independent availability of `codex/cli_exec` and `codex/app_server`; shared Engine identity; rejection of locked or incompatible combinations. |
| Execution mode | Synchronous registration and validation at startup and asynchronous resolution during execution; React registration is not blocked. |
| Failure handling | Unverified versions, unknown Protocols, and an unmet Stage A gate all fail closed; record reason codes and audit without Secrets. |

### FR-2 CLI request mapping and version compatibility

| Item | Description |
|---|---|
| Trigger | When a Stage A Worker starts a Codex Run through the orchestrator. |
| Input | Validated ExecutionRequest, typed Codex configuration, instructions/context, Workspace, and Effective capability snapshot. |
| Output | A CLI invocation specification containing only allowed arguments and an internal ExecutionHandle; public responses contain no host details. |
| Execution mode | Asynchronous, non-blocking API launch; RuntimeHost manages the actual process. |
| Failure handling | Missing binary, incompatible version, and invalid arguments/configuration map to distinct stable error codes; never silently switch to an unverified version. |

### FR-3 RuntimeHost launch, cancellation, and timeout

| Item | Description |
|---|---|
| Trigger | When a CLI process or App-Server child process/connection starts, a user cancels, a deadline expires, or a Worker stops. |
| Input | Internal handle, process group, cancellation request, timeout, and termination grace period. |
| Output | Running/Terminating/Exited state, actual exit evidence, stable Run terminal state, and cleanup result. |
| Execution mode | Asynchronous supervision; request graceful termination first, then forcibly terminate the entire process tree according to policy. |
| Failure handling | If exit cannot be confirmed, report cleanup failure and alert rather than falsely reporting completed/cancelled; retain bounded diagnostics without exposing PIDs to clients. |

### FR-4 Native events, final results, and usage

| Item | Description |
|---|---|
| Trigger | When CLI output or App-Server notifications arrive and when execution finishes. |
| Input | stdout/stderr, JSON-RPC notifications/responses, native completion, and usage data. |
| Output | Platform events in the common envelope, bounded native events with `source=engine_native`, ExecutionResult, and available usage. |
| Execution mode | Streaming asynchronous mapping; stable and native semantics coexist without conversion into ReAct internal reasoning. |
| Failure handling | Unknown events may be retained within bounds and marked; malformed output produces ProtocolError and redacted diagnostics; missing usage is unknown, never zero-filled. |

### FR-5 Workspace and file policy

| Item | Description |
|---|---|
| Trigger | When preparing an Execution, mounting Workspace/Skills, collecting artifacts, and cleaning up. |
| Input | Trusted tenant context, Workspace ID, Execution ID, read-only/read-write mounts, and retention policy. |
| Output | Per-Execution Workdir, authorized mounts, controlled artifacts, and cleanup records. |
| Execution mode | Phase 4 Workspace Provider prepares resources asynchronously; the Adapter never chooses host paths itself. |
| Failure handling | Path traversal, symlink escape, cross-tenant access, and unauthorized writes are denied; Codex does not start if preparation fails. |

### FR-6 Credential policy and trusted-tenant hard gate

| Item | Description |
|---|---|
| Trigger | When resolving Codex configuration, starting a process, resuming a Session, or changing tenant trust. |
| Input | Server-side credential reference, tenant/Agent/Execution/Engine authorization, trust registration, and policy snapshot. |
| Output | Controlled environment variables or Secret mounts available only to the current Execution, plus audit without plaintext. |
| Execution mode | Authorize synchronously before launch and inject on demand; never inherit the host Codex login directory. |
| Failure handling | Missing references, authorization mismatch, insufficient trust, or unavailable isolation denies launch; copying `~/.codex/auth.json` is forbidden and Secrets never enter logs/events. |

### FR-7 App-Server JSON-RPC encapsulation and connection lifecycle

| Item | Description |
|---|---|
| Trigger | When Stage B is unlocked and execution selects `app_server`. |
| Input | Negotiated protocol version, initialization parameters, request IDs, notifications, responses, and connection state. |
| Output | Provider-internal typed calls, response routing, reconnect/close results, and platform-contract events. |
| Execution mode | Asynchronous full-duplex communication; request IDs correlate with Runs/Turns, with bounded timeout and backpressure. |
| Failure handling | Negotiation failure, unknown/duplicate/late responses, and disconnection follow protocol-error semantics; private JSON-RPC is not exposed as a public API. |

### FR-8 Native Session persistence and Session/Turn/Run mapping

| Item | Description |
|---|---|
| Trigger | When App-Server creates, uses, completes, expires, or closes a native Session. |
| Input | Conversation, Run, Engine Session, provider_session_id, Protocol/Adapter, Workspace, and metadata version. |
| Output | Platform Session records and traceable associations of one Session to many Runs and one Turn to one execution attempt. |
| Execution mode | Asynchronous transactional persistence; enable the planned migration only when persistent Sessions are actually required. |
| Failure handling | Mapping conflicts, incompatible metadata versions, or persistence failures stop Resume; the Session-free CLI path is unaffected. |

### FR-9 Streaming, approvals, and interactive input

| Item | Description |
|---|---|
| Trigger | When App-Server emits streaming notifications, approval requests, or interactive-input requests. |
| Input | Effective capabilities, native request, approval/input response, and request correlation ID. |
| Output | Common platform events and authorized internal responses; public clients use only the NexusDesk common contract. |
| Execution mode | Asynchronous streaming; waiting for input has timeout, cancellation, and backpressure bounds. |
| Failure handling | Declared but non-Effective capabilities are denied; unknown requests are never auto-approved; disconnection cannot wait forever. |

### FR-10 Session Resume reauthorization

| Item | Description |
|---|---|
| Trigger | When a user or system requests resumption of a persisted App-Server Session. |
| Input | Platform Session ID, current trusted identity, Agent/Conversation/Workspace, current policy, and credential scope. |
| Output | Reauthorized Resume or explicit denial, with updated audit and last-used time. |
| Execution mode | Reauthorize synchronously on every Resume, then execute asynchronously; never cache prior authorization decisions. |
| Failure handling | Cross-tenant, cross-Conversation/Workspace, expired/revoked, or incompatible Protocol/Adapter attempts are denied and audited; native IDs alone never authorize recovery. |

### FR-11 Error classification, audit, and observability

| Item | Description |
|---|---|
| Trigger | On any failure or key state change during launch, parsing, execution, cancellation, resume, or cleanup. |
| Input | Stable error class, Run/Session/Protocol correlation, version, duration, exit, and usage metadata. |
| Output | Public error code, internal redacted diagnostics, metrics, structured logs, and audit events. |
| Execution mode | Asynchronous recording does not block the event path; critical security denials require reliable audit. |
| Failure handling | Raw Provider exceptions are not returned directly; diagnostics have size/rate bounds, while complete parser diagnostics and idempotent usage governance are deepened in Phase 6. |

### FR-12 Configuration switches and compatible rollout

| Configuration item | Level | Default | Description |
|---|---|---|---|
| `codex_cli_enabled` | Global settings | `false` | Stage A master switch; only verified versions and trusted tenants are allowed. |
| `codex_app_server_enabled` | Global settings | `false` | Stage B master switch; configuration and runtime both check the Stage A gate. |
| `codex_allowed_versions` | Global settings | `[]` | Allowlist of verified versions; an empty list denies Codex launch. |
| `codex_trusted_tenants` | Deployment policy | `[]` | Explicit trusted-tenant allowlist before Phase 6; clients cannot set it. |
| `codex_session_persistence_enabled` | Global settings | `false` | Enabled only in Stage B after the Session migration is ready. |
| `codex.timeout_seconds` | AgentConfig | `1800`, bounded by deployment limit | Typed execution deadline; cannot exceed the platform limit. |
| `codex.sandbox_mode` / `approval_mode` | AgentConfig | Strictest deployment-allowed value | Can only narrow, never expand, Effective capabilities. |

## Non-functional Requirements

- **Performance**: Event parsing and forwarding are bounded and do not block the Worker; record startup, event, and cancellation p50/p95. Unmeasured baselines are pending Phase 0, and budgets are frozen after baseline review.
- **Compatibility**: React remains the default Engine; existing Runs, event types, SSE cursors, and historical Agent configuration remain unchanged, and Protocol-private fields stay out of public models.
- **Multi-tenancy**: Tenant identity comes from trusted authentication; Sessions, Workspaces, credential references, and caches are tenant-bound, with cross-tenant access denied by default.
- **Security**: Before the complete Broker/strong sandbox in Phase 6, only explicitly trusted tenants are enabled; Secrets, host auth files, and sensitive command-line arguments never enter logs, events, or public responses.
- **Reliability**: Process exit, connection closure, and Run terminal state are correlated; duplicate/late protocol messages cannot duplicate approvals or incorrectly complete execution. General event deduplication/Fencing is completed in Phase 6.
- **Operability**: CLI and App-Server expose independent health, version, error rate, event lag, and cleanup metrics; switches can disable each path immediately.

## Acceptance Criteria

| # | Scenario | Expected | Traceability |
|---|---|---|---|
| AC-1 | A trusted tenant starts a CLI coding task using a pinned supported version. | It completes through the common orchestration path; the RuntimeHost handle is internal, final output correlates with the Run, and public APIs expose no host details. | FR-2; G1 |
| AC-2 | Resolve both Protocols separately and attempt to enable App-Server before the Stage A gate is met. | Both use `engine_id=codex` with independent Protocols; Stage B is denied until the gate is met and can then be enabled. | FR-1; G2, G5 |
| AC-3 | CLI/App-Server produces messages, commands, file changes, and usage where supported. | Platform events and bounded native events are retained and correlated with the Run; usage is collected with normalized meaning, and missing usage is explicitly unknown. | FR-4; G3 |
| AC-4 | Cancel and time out long-running CLI and App-Server executions separately, with injected child processes. | Process trees/connections terminate and resources are released within the grace period, with correct terminal state; unconfirmed cleanup is an explicit failure with alert. | FR-3; G1, G6 |
| AC-5 | Submit a valid Workspace, then attempt path traversal, symlink escape, and cross-tenant reads/writes. | Valid tasks access only authorized directories; every escape is denied before launch or safely terminated, with Secret-free audit. | FR-5; G4 |
| AC-6 | Launch with a controlled credential reference, then attempt host auth-file copying, Secret output, and untrusted-tenant launch. | Only the authorized Execution receives controlled credentials; host files are not copied, plaintext is not disclosed, and untrusted tenants are denied by default. | FR-6; G4 |
| AC-7 | In Stage B, complete JSON-RPC initialization, concurrent requests, disconnection, and unknown/late responses. | Requests correlate correctly, disconnection reaches a terminal state, private protocol stays out of public APIs, and anomalies remain bounded and diagnosable. | FR-7; G2 |
| AC-8 | Create an App-Server Session in one Conversation, execute multiple Turns/Runs, and then expire it. | Session/Turn/Run mapping is accurate, metadata is versioned, expired resources are released, and CLI does not depend on the Session table. | FR-8; G5 |
| AC-9 | Request streaming output, approval, and interactive input with Effective permission allowed and denied. | Allowed flows use the common contract; denied flows do not execute or auto-approve, and waiting can time out or be cancelled. | FR-9; G3, G4 |
| AC-10 | Resume a Session legitimately, then retry with the wrong tenant, Workspace, expired credential, or incompatible Adapter. | Legitimate Resume succeeds after reauthorization; all other attempts are denied and audited without reusing old authorization decisions. | FR-10; G4, G5 |
| AC-11 | Inject an unsupported version, malformed CLI output, invalid JSON-RPC, and missing usage. | Stable errors/unknown are returned without raw Provider exceptions or Secrets; logs and metrics locate the issue by Run/Protocol. | FR-11; G1, G3 |
| AC-12 | Disable both Codex switches and run existing React, Run/API/SSE, and historical-configuration regressions. | Codex cannot start; behavioral diff from the Phase 0 baseline is zero, applicable existing tests are green, and rollback requires no table drop. | FR-12; G6 |
