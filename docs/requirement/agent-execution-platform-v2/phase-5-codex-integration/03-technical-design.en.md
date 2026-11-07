# Phase 5 · Codex Integration — Technical Design

> Status: Pending review (planning only, not implemented; target paths must be rechecked against actual Phase 1–4 deliverables before development)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G6), `02-requirements.md` (FR-1–FR-12, AC-1–AC-12), and architecture Sections 4, 8–10, 12–13, and 16–17

> Current code, tests, migrations, credentials, and SSE precedents were audited before this document was written; later revisions must record date and reason in the affected section.

## Current-state Audit and Constraints

| Area | Facts as of 2026-11-02 | Constraint for this phase |
|---|---|---|
| Engine path | `backend/src/agent_platform/core_platform/agent_runtime/worker.py` runs the Runtime directly; `applications/platform_runtime/runtime_factory.py` constructs the ReAct Runtime. | Integrate at the actual Phase 1–2 Orchestrator/Registry; do not add Codex branches to the Worker. |
| Codex | Searches of `backend/`, `frontend/src`, and `deploy/` found no Codex CLI/App-Server/JSON-RPC/Session implementation. | Every Codex capability is new planned work; never describe it as existing support. |
| RuntimeHost/Workspace | `core_platform/agent_execution/` does not currently exist; logical Workspace/tool directories are not an external-Engine sandbox. | Depend on the actual Phase 4 RuntimeHost, Process Supervisor, and Workspace Provider rather than duplicating process management. |
| Credentials | `platform_services/secrets/vault.py` provides Fernet encryption with an installation key; `model_gateway/catalog.py` binds tenant/connection/address/protocol, but there is no Execution Broker. | Phase 5 uses controlled references and minimal exposure only; complete Broker, short-lived grants, and strong sandbox belong to Phase 6. |
| Events/SSE | `agent_runtime/repository.py` increments `runtime_runs.event_seq` and writes `runtime_events` in one transaction; `customer_service/runtime_routes.py` supports `after` and `Last-Event-ID`, with NOTIFY only as a wakeup. | Reuse durable events and the SSE envelope rather than creating a Codex-specific channel; Outbox/deduplication/idempotent usage belong to Phase 6. |
| Terminal state/Lease | Repository checks owner, lease, and terminal state; `test_runtime_postgres.py` covers cancellation races, Worker loss, and late results. | Preserve these precedents; do not claim cross-Worker Epoch/Fencing is complete in Phase 5. |
| Migrations | Current head is `0052_memory_tasks_tenant_index`. | `0055_agent_engine_sessions` is only a reserved planning number, added conditionally for Stage B; recheck head and dependencies before implementation and never modify historical migrations. |

## Change Overview

| Layer | File | Change | Traceability |
|---|---|---|---|
| New module | `backend/src/agent_platform/core_platform/agent_execution/adapters/codex/cli_exec.py` | Stage A Adapter for request mapping, launch, event stream, result, and cancellation, exclusively through RuntimeHost. | FR-1–FR-4 |
| New module | `.../adapters/codex/app_server.py` | Stage B Protocol Adapter; reuse common Codex configuration/event models, not the CLI stdio state machine. | FR-1, FR-7–FR-10 |
| New module | `.../adapters/codex/jsonrpc.py` | Provider-private JSON-RPC framing, ID correlation, version negotiation, timeout, backpressure, and disconnection state machine. | FR-7, FR-11 |
| New module | `.../adapters/codex/events.py` | CLI/App-Server native-event normalization, stable platform mapping, bounded payloads, and usage extraction. | FR-4, FR-11 |
| New module | `.../adapters/codex/config.py` | Typed configuration and version/capability intersection validation; never trust client-supplied Effective capabilities. | FR-1, FR-2, FR-12 |
| New module | `.../agent_execution/session/{models,manager,repository}.py` | Stage B Session mapping, expiration, and Resume reauthorization; CLI has no such dependency. | FR-8, FR-10 |
| Migration | `backend/migrations/versions/0055_agent_engine_sessions.py` | Planning number; conditionally add `agent_engine_sessions`, with actual `down_revision` determined by the implementation-time head. | FR-8 |
| Entry point | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | Register Codex Protocols, Host, Workspace, Session, and policy dependencies at the actual Phase 1–4 composition root. | FR-1, FR-12 |
| Configuration | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | Add default-off, version-allowlist, trusted-tenant, and Session switches; sensitive values remain deployment Secrets. | FR-6, FR-12 |
| API | Actual Phase 3 common capability/approval routes (recheck paths before implementation) | Expose only common capability and approval/input contracts; add no public Codex JSON-RPC route. | FR-7, FR-9 |
| Deployment | `backend/.env.example`, `deploy/production/.env.example`, and actual RuntimeHost configuration | Add only Secret-free placeholders and switch examples; write no real Tokens and mount no host Codex auth directory. | FR-6, FR-12 |
| Tests | `backend/tests/test_codex_{contract,cli,app_server,session}.py` and protocol fixtures | Common contracts, controlled real binaries, fault injection, Workspace/credential adversarial cases, and React regressions. | AC-1–AC-12 |

> Ellipses above denote the same `backend/src/agent_platform/core_platform/agent_execution/` root. All paths are planned targets; if Phases 1–4 choose a different structure, revise this document before implementation.

## Data Model

### Planned migration `0055_agent_engine_sessions.py` (only if required by Stage B)

| Field | Planned type/constraint | Purpose |
|---|---|---|
| `id` | UUID PK | Platform Engine Session ID, the internal identifier used for Resume. |
| `tenant_id` | TEXT NOT NULL + index | Trusted tenant boundary; every query is tenant-scoped. |
| `conversation_id` | UUID NOT NULL, references `runtime_conversations(id)` | Binds the business Conversation and prevents cross-conversation recovery. |
| `engine_id` / `protocol_id` / `adapter_version` | TEXT NOT NULL | Pins compatible `codex/app_server` Adapter identity; CLI does not reuse App-Server Sessions. |
| `provider_session_id` | TEXT NOT NULL | Native Codex Session identifier, never sufficient authorization by itself. |
| `workspace_id` | Type rechecked against the actual Phase 4 model, NOT NULL | Binds the Workspace, which must match during Resume. |
| `status` | TEXT CHECK: `active/suspended/expired/closed/failed` | Explicit lifecycle and expiration cleanup. |
| `metadata` / `metadata_schema_version` | JSONB NOT NULL / TEXT NOT NULL | Adapter-owned bounded versioned native metadata, with no Secrets. |
| `created_at` / `updated_at` / `last_used_at` | TIMESTAMPTZ | Audit and cleanup evidence. |
| `expires_at` | TIMESTAMPTZ NULL + index | Denies Resume after expiration and releases associated resources. |

Design points:

- Plan a unique constraint on `(tenant_id, protocol_id, adapter_version, provider_session_id)` and an index on `(tenant_id, conversation_id, status)`; recheck final fields, FKs, and Workspace type against the implementation-time model.
- A Conversation may have multiple Engine Sessions and a Session may correlate with multiple Runs; Runs store `engine_session_id` through Phase 1–3 execution metadata, and this phase adds no Task table.
- `metadata` must not contain credentials, complete host environments, or unbounded native logs; native IDs remain Provider-internal.
- Stage A neither creates nor depends on this migration; if the Stage B design review proves persistent Sessions unnecessary, cancel this planned migration and record the decision.
- The online migration only adds a table and changes no historical tables; if data exists before downgrade, require explicit export according to repository convention rather than silently losing data.

## Core Flows

### 1. Stage A: CLI execution (`cli_exec.py` + Phase 4 RuntimeHost)

```text
Run creation (Codex denied while switched off)
→ Worker/Orchestrator resolves (codex, cli_exec, adapter_version)
→ Validate trusted tenant, version, typed configuration, and Effective capabilities
→ Workspace Provider creates Execution Workdir and authorized mounts
→ Resolve credential references minimally for this Execution; never read host ~/.codex/auth.json
→ RuntimeHost starts a process group and returns an internal Handle
→ CLI Adapter reads stdout/stderr with bounds, maps platform events, and preserves native events
→ Collect final output/artifacts/usage (missing usage is unknown)
→ Orchestrator commits the result; Host confirms process exit and resource cleanup
```

- The Adapter never invokes `subprocess` directly, manipulates the queue, or commits Run terminal state; arguments are built from an allowlist and sensitive arguments are excluded from logs.
- stderr may contain diagnostics or Secrets and must not become a public error unconditionally; raw output is bounded and redacted.
- The Stage A stability gate is mandatory under FR-1/AC-2: Stage B can merge/enable only after test reports, consecutive pre-release regressions, and mixed-scenario evidence are complete.

### 2. Cancellation and timeout (RuntimeHost / Process Supervisor)

```text
Cancellation or deadline
→ Persist cancel_requested/timeout intent
→ Host requests graceful Codex termination
→ Wait for process-group and connection exit within the grace period
→ Forcibly terminate the entire process tree if still running
→ Clean mounts, temporary directories, connections, and resources
→ Commit cancelled/failed from actual exit and cleanup evidence; late success cannot overwrite
```

- Coroutine cancellation is a trigger, not completion evidence; unconfirmed cleanup ends in explicit failure and alert.
- This phase preserves existing owner/lease/terminal protection and does not claim Phase 6 Lease Epoch/Fencing.

### 3. Stage B: JSON-RPC and Turns (`app_server.py`, `jsonrpc.py`)

```text
Stage A gate + app_server switch + version negotiation
→ Establish/reuse a Host-supervised connection
→ Initialize and pin protocol capabilities for this execution
→ Correlate Run/Turn with an internal request_id and send typed requests
→ Convert notifications to events; route responses/errors by ID
→ Approvals/input use the common platform contract only when Effective policy allows
→ Collect result/usage at turn completion; close, disconnect, and timeout all release waiters and clean up
```

- JSON-RPC schemas, method names, and errors exist only inside the Provider; public APIs expose no `jsonrpc`, method names, or native request IDs.
- Unknown, duplicate, or late responses never automatically replay side-effecting requests; retry classification and side-effect governance are completed in Phase 6.

### 4. Session Resume reauthorization (`session/manager.py`)

```text
Platform Session ID + current authentication context
→ Query Session by tenant and check active/expires_at
→ Revalidate Conversation, Agent, Workspace, Protocol/Adapter, credential scope, and Effective policy
→ Verify the native Session remains usable, failing closed when necessary
→ Provider resumes; record audit/last_used_at
→ Each new Turn still creates an independent Run/Execution attempt
```

- Never reuse launch-time authorization caches; trust revocation, credential expiration, or Workspace changes deny Resume.
- Session expiration cleanup and Workspace unbinding are reentrant; complete Fencing and cross-Worker recovery are guaranteed in Phase 6.

## Configuration

Plan to add `codex_cli_enabled=false`, `codex_app_server_enabled=false`, `codex_allowed_versions=[]`, `codex_trusted_tenants=[]`, and `codex_session_persistence_enabled=false` to `platform_settings/settings.py`, plus bounded output, connection, Session, and cancellation-grace settings.

- Sensitive configuration stores only `credential_ref`; actual values live in deployment Secret environments/mounts, and `.env.example` contains placeholders only.
- `codex.timeout_seconds` has a planned default of 1800 seconds but remains bounded by a deployment hard limit; recheck the current global `run_timeout_seconds` limit and Phase 3 configuration merge rules before implementation.
- Agent-side `sandbox_mode`, `approval_mode`, and capability values can only narrow deployment policy; before Phase 6, an empty trust allowlist denies execution.

## Model Invocation Path

Codex is an external Engine: model selection, reasoning loops, and tool execution are native to Codex. They are not assumed to pass through the NexusDesk Model Gateway, and no branch is added to ReAct `RuntimeFactory.bound_model()`. The platform only injects authorized Engine configuration/credential references and collects usage returned by Codex; usage correlates with Run and Protocol, missing usage is unknown, and duplicate aggregation/billing idempotency belongs to Phase 6.

## Test Plan Summary

| Layer | Cases |
|---|---|
| Unit | Version/configuration, CLI argument allowlist, event and usage fixtures, JSON-RPC ID/disconnection state machine, Session authorization/expiration, and error redaction. |
| Integration | Controlled real Codex CLI/App-Server, RuntimeHost process trees, cancellation/timeout/crash, Workspace adversarial cases, credentials/trusted tenants, and Session Resume. |
| Regression | React/Run/API/SSE, historical configuration, migrations, and switch-off diff; an unmeasured Phase 0 baseline cannot be recorded as passed. |

See `04-test-plan.md` for detailed cases, adversarial/fault injection, and exit criteria.

## Rollout and Rollback

1. Confirm Phase 0–4 acceptance and the Phase 0 baseline; pin Codex versions, test accounts, trusted tenants, and audit-retention policy.
2. Execute planned `0055` only if Stage B requires it; recheck migration head, online locking, and downgrade data protection before implementation, and never modify historical migrations.
3. Deploy code with switches off, enable CLI for one trusted tenant, permit App-Server canary only after the Stage A gate, and then enable Sessions as needed.
4. Roll back by disabling Sessions → disabling App-Server → stopping new CLI Runs → cleaning active processes under Host policy; retain new tables and historical events, with no down migration required.
5. Any Secret disclosure, cross-tenant access, accidental untrusted-tenant exposure, or uncontrolled orphaned process stops new executions and disables the switches; never restore availability by weakening sandbox or credential policy.
