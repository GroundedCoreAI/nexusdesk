# Phase 4 · Runtime Host, Process Supervision, and Workspace — Technical Design

> Status: Pending review (implementation has not started; all modules, tables, and deployment changes below are planned)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G5), `02-requirements.md` (FR-1–FR-10, AC-1–AC-12), architecture Sections 3, 7–10, 15–17, and 19–22
> Current-state review: `integration` working tree on 2026-11-02; planned Phase 3 predecessor is `0053_agent_execution_metadata`

## 1. Current-State Mapping and Design Decisions

| Current evidence | Verified finding | Decision for this phase |
|---|---|---|
| `core_platform/agent_runtime/worker.py` | Manages asyncio tasks, Lease/Heartbeat, cancellation, and Run terminal states, with no OS-process concept | Preserve Worker/Repository ownership; Orchestrator calls Host, while Supervisor independently owns process facts and cleanup |
| `core_platform/agent_runtime/repository.py` | `finish` protects owner/lease/terminal state, and lease-loss reaper updates only the Run | Reuse terminal-state protection; process records do not replace Runs, and a Run terminal state does not prove OS resources were released |
| `applications/platform_runtime/runtime_factory.py` | Constructs only the in-process ReAct Runtime | React remains unchanged; external test processes use Phase 1–3 Adapter/Orchestrator and Host contracts |
| `platform_settings/settings.py` | Has Run timeout, queue/concurrency, and business-storage limits but no external-process resource policy | Follow `AGENT_` Settings for Host/Workdir/Resource configuration, off by default with fail-closed behavior |
| `tool_gateway/workspace.py`, knowledge/model storage | Provide relative-path validation, size limits, and tenant-query precedents, but no link-race-safe execution-directory implementation | Reuse tenant/size governance concepts, not string concatenation for execution-file safety; use directory handles and no-follow |
| `deploy/quickstart/compose.yaml` | App already has a `/data` persistent volume and 45s stop grace | Place Workdirs under `/data/execution`; default TERM/KILL fits stop grace, with no shared host path |
| `deploy/production/compose.yaml` | Has a standalone runtime-worker currently mounting only the credentials volume | Add a dedicated execution volume and stable host_id only to runtime-worker; API/other Workers get no execution volume |
| Phase 1–3 plans | Adapter, ExecutionRequest, Orchestrator, and capability/policy/Workdir requirements are prerequisites | Host accepts only server-resolved requests; no external process starts without Effective requirements, and unknown capabilities/paths fail closed |

## 2. Change Overview

| Layer | File | Change |
|---|---|---|
| Migration | `backend/migrations/versions/0054_execution_runtime_host.py` | Plan `execution_workdirs` and `runtime_host_processes` tables with necessary indexes; revalidate predecessor before implementation |
| Host models | `backend/src/agent_platform/core_platform/agent_execution/host/host_models.py` | Internal ProcessSpec, ResourcePolicy, ManagedProcess, ProcessResult, and HostHealth models |
| Host interface | `backend/src/agent_platform/core_platform/agent_execution/host/runtime_host.py` | start/cancel/wait/reconcile/health/close contracts and composition entry |
| Runner | `backend/src/agent_platform/core_platform/agent_execution/host/process_runner.py` | Trusted-target start, new process group, bounded I/O, and start-identity capture |
| Supervisor | `backend/src/agent_platform/core_platform/agent_execution/host/process_supervisor.py` | TERM/KILL, timeout, exit collection, idempotent cleanup, and resource release |
| Registry | `backend/src/agent_platform/core_platform/agent_execution/host/process_registry.py` | Process records, locking, orphan verification, restart recovery, and manual remediation |
| Resources | `backend/src/agent_platform/core_platform/agent_execution/host/resource_manager.py` | Support probes, per-Execution limits, sampling, and release |
| Workspace interface | `backend/src/agent_platform/core_platform/agent_execution/workspace/workspace_provider.py` | Workdir prepare/activate/retain/cleanup contract |
| Workspace management | `backend/src/agent_platform/core_platform/agent_execution/workspace/workspace_manager.py` | Durable records, retention scans, restart recovery, and cleanup retry |
| Workdir | `backend/src/agent_platform/core_platform/agent_execution/workspace/execution_workdir.py` | Unique layout, permissions, disk accounting, and safe directory handles |
| Path policy | `backend/src/agent_platform/core_platform/agent_execution/workspace/workspace_policy.py` | Relative-path/mount allowlists, no-follow, link/race handling, and cleanup bounds |
| Sandbox | `backend/src/agent_platform/core_platform/agent_execution/host/sandbox_provider.py`, `local_sandbox_provider.py` | Replaceable interface, Local Provider, capability matrix, and untrusted-execution gate |
| Orchestration | `backend/src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py` | Enforce Workdir → Sandbox/resources → Host.start → events → cleanup and exception barriers |
| Composition | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | Assemble Host/Supervisor/Workspace/Resource/Sandbox and manage startup/shutdown |
| Configuration | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | FR-10 settings, bounds, and enabled-state cross-validation |
| Deployment | `deploy/quickstart/compose.yaml`, `deploy/production/compose.yaml`, `deploy/production/.env.example` | Execution volume, stable host_id, non-secret limits, and stop policy |
| Tests | `backend/tests/test_runtime_host.py`, `test_process_supervisor.py`, `test_execution_workdir.py`, `test_runtime_host_postgres.py`, `test_execution_runtime_host_migrations.py` | Planned real-process, failure, malicious-path, resource, and migration tests; helpers are built-in trusted test targets only |

## 3. Data Model

### 3.1 Why Durable Records Are Necessary

After a Worker restart, in-memory asyncio Tasks, PIDs, and directory handles are gone. Without durable records, the platform cannot distinguish completed, cleanup-pending, and identity-unverified processes or safely recover stale Workdirs. Persisting **process** and **Workdir** execution facts is therefore necessary.

Do not create a generic RuntimeHost service table: stable `host_id` comes from deployment, boot-scoped `host_instance_id` is generated by the process, and Host health derives from observation timestamps and structured state. Avoid a control-plane entity until multi-Host scheduling is a real requirement.

### 3.2 Migration `0054_execution_runtime_host.py`

> Planned identifier: planned predecessor is Phase 3 `0053_agent_execution_metadata`. Revalidate actual head/down_revision before implementation; if intervening migrations exist, use a new linkage and revise this document without editing history.

#### Table `execution_workdirs`

| Field | Type/constraint | Purpose |
|---|---|---|
| `id` | UUID PK | Platform Workdir ID |
| `run_id` | UUID NOT NULL UNIQUE REFERENCES `runtime_runs` ON DELETE CASCADE | One execution directory per Run |
| `tenant_id/business_id/workspace_id` | TEXT NOT NULL | Trusted tenant and logical scope, rechecked before cleanup |
| `relative_path` | TEXT NOT NULL UNIQUE | Platform-generated path relative to configured execution root; never client-supplied |
| `status` | TEXT NOT NULL CHECK | `preparing/ready/active/retained/cleaning/deleted/cleanup_failed` |
| `quota_bytes/size_bytes` | BIGINT NOT NULL | Configured total ceiling and latest observed usage; size defaults to 0 |
| `file_count` | INTEGER NOT NULL DEFAULT 0 | Observed file count and cleanup diagnostics |
| `expires_at` | TIMESTAMPTZ NULL | Retention expiry |
| `last_error_code` | TEXT NULL | Stable prepare/cleanup error, without raw paths or secret exception text |
| `created_at/updated_at/cleaned_at` | TIMESTAMPTZ | Lifecycle and idempotent cleanup |

Indexes: `(status,expires_at)` and `(tenant_id,status)`. Retain a Tombstone after physical deletion; never follow links outside `relative_path` or accept a replacement path from a request.

#### Table `runtime_host_processes`

| Field | Type/constraint | Purpose |
|---|---|---|
| `id` | UUID PK | Platform managed-process ID |
| `run_id` | UUID NOT NULL UNIQUE REFERENCES `runtime_runs` ON DELETE CASCADE | One main process group per Run in the initial version |
| `workdir_id` | UUID NULL REFERENCES `execution_workdirs` ON DELETE SET NULL | Directory association; Workdir Tombstone does not erase process audit |
| `tenant_id` | TEXT NOT NULL | Tenant isolation and operational queries |
| `host_id` | TEXT NOT NULL | Stable deployment identity bounding restart scans |
| `host_instance_id` | TEXT NOT NULL | Current boot owner, distinguishing old and new Host instances |
| `sandbox_provider` | TEXT NOT NULL | Internal Provider id/version identity |
| `status` | TEXT NOT NULL CHECK | `starting/running/terminating/exited/orphaned/cleanup_failed` |
| `pid/process_group_id` | INTEGER NULL | Internal OS identifiers, never public or globally UNIQUE because they are reused |
| `process_start_token` | TEXT NULL | OS start time/equivalent opaque identity preventing PID-reuse kills |
| `command_digest` | TEXT NOT NULL | Digest of trusted executable and normalized argv, without secret argv |
| `cancel_requested_at/cleanup_deadline_at` | TIMESTAMPTZ NULL | Cancellation and cleanup-escalation deadlines |
| `exit_code` | INTEGER NULL | Actual exit code/agreed signal value |
| `last_observed_at` | TIMESTAMPTZ NOT NULL | Reconcile/health observation time |
| `last_error_code` | TEXT NULL | Stable start/cleanup/recovery error |
| `metadata` | JSONB NOT NULL DEFAULT `{}` | Bounded non-secret resource/exit metadata, with no environment values or full paths |
| `created_at/updated_at/started_at/exited_at` | TIMESTAMPTZ | Lifecycle and recovery decisions |

Indexes: `(host_id,status)`, `(status,last_observed_at)`, and `(tenant_id,status)`. The tables contain only recovery/cleanup fields, copy neither AgentConfig nor capability snapshots, add no RuntimeHost service record, and add no columns to `runtime_runs`.

## 4. Core Contracts and Flows

### 4.1 RuntimeHost and Adapter boundary

| Operation | Host responsibility | Adapter/Orchestrator responsibility |
|---|---|---|
| `start` | Validate trusted ProcessSpec, prepare Sandbox/resources, start a process group, and register it | Adapter supplies the trusted protocol target; Orchestrator supplies Run/tenant/Effective/Workdir context |
| `wait/observe` | Collect exit, output backpressure, resource usage, and actual state | Adapter parses protocol output; Orchestrator persists platform events |
| `cancel` | Record reason, TERM→KILL the group, wait, and release resources | Adapter initiates protocol cancellation if supported; Orchestrator/Repository owns Run terminal state |
| `reconcile` | Compare durable records with OS facts, recover orphans, and retry cleanup | Never resumes Engine sessions or re-executes side-effecting requests |
| `health/close` | Report support matrix/active/failures; stop admission and drain | Composition root owns lifecycle; Worker makes no direct OS calls |

Public ExecutionHandle excludes PID/PGID, start tokens, full paths, and environment. Tests must use at least two Adapters to prove Host has no Engine-specific branches.

### 4.2 Normal start and exit

```
Orchestrator validates Phase 3 Effective and trusted target
→ Workdir preparing/ready (durable) → Sandbox/resource support checks
→ Process starting record → new process group with PID/PGID/start token/command digest
→ running + Workdir active → bounded I/O / protocol events
→ wait collects exit → exited + resource release → Run result commit → Workdir retained/cleaning
```

- Every failure cleans in reverse order; if a process started before record failure, terminate the group through the same managed handle rather than leaving it unowned after a DB error.
- Run completion/failure/cancellation and Workdir retained/deleted commit separately; `cleanup_failed` remains visible and retryable.
- Bound stdout/stderr independently; at the limit, stop reading and terminate the group, without logging complete output or environment.

### 4.3 Cancellation, timeout, and stop

```
cancel/timeout/resource_exceeded/worker_stop
→ conditionally update cancel_requested_at/status=terminating
→ TERM process group → wait grace
→ KILL process group if alive → wait kill timeout
→ verify exit and descendants → exited or cleanup_failed
→ idempotently release Sandbox/resources → Repository applies existing terminal-state rules
```

- User cancellation wins over late success; Host cannot bypass existing owner/lease/TERMINAL protection.
- Earlier of Run and process wall deadlines wins; cancellation/timeout races enter one cleanup state machine and repeated calls return the same progress.
- cleanup_failed is not exited; metrics/alerts continue until manual remediation closes the record.
- Application stop blocks new admissions first; default 5s+5s fits the existing 45s stop grace, and larger settings require deployment stop-timeout changes.

### 4.4 Orphan recovery and restart restoration

```
New Host starts (recovery runs even when new admission is disabled)
→ query small batches of starting/running/terminating/orphaned/cleanup_failed records for the same host_id
→ SELECT ... FOR UPDATE SKIP LOCKED / conditional state updates
→ verify execution root, host namespace, PID/PGID, start token, and command digest
→ match: mark orphaned and TERM/KILL; mismatch: no signal, cleanup_failed + manual alert
→ verify Workdir ownership and clean/retain → recovery audit and metrics
```

- Recovery only terminates and cleans; it does not adopt stdin/stdout, resume protocol Sessions, or automatically replay Runs.
- An existing PID with different start token or command digest is PID reuse, with zero mistaken kills; unavailable identity also counts as mismatch.
- DB outage only retries the connection; never scan all host processes or kill by fuzzy command name.
- One execution root has one stable host_id; multi-replica deployment must stop the old Host and finish recovery, with no concurrent sharing.

### 4.5 Workdir and safe file operations

The logical layout is `<execution_root>/<tenant-digest>/<run-id>/{workdir,temp,logs}`; tenant-digest and run-id are server-generated and display names are untrusted. Directories default to 0700 and files to 0600. At startup, verify execution-root owner, type, and permissions, and reject a symlinked root.

Every path operation follows these rules:

1. Accept only normalized relative paths; reject absolute paths, NUL, `.`/`..`, backslashes, repeated/encoded separator bypasses, and excessive length.
2. Open component-wise from a verified execution-root/Workdir directory handle using no-follow and exclusive-create semantics; never use “realpath check, then string open” as the security boundary.
3. Recheck DB tenant/scope/run/status for every mount/export/cleanup; mount sources are platform-allowlisted and no host source is available by default.
4. Deny symlinks by default; deny hardlinks and mount points when ownership cannot be proven. Recursive cleanup uses directory handles without following links and stops on races.
5. Clean only the recorded Run-specific directory; one Execution can never recursively delete the root, tenant parent, or another Run directory.

### 4.6 Resource management and Sandbox support matrix

| Capability | Preferred full-acceptance mechanism | Development fallback | Fail-closed behavior and boundary |
|---|---|---|---|
| CPU time | Per-Execution managed resource-group accounting + supervisor termination, assisted by CPU rlimit | Per-process rlimit is approximate and not a group hard ceiling | Reject when a required group limit cannot be supplied |
| Memory | cgroup v2 memory.max/equivalent per Execution | Address-space rlimit covers one process only and is labeled non-equivalent | Reject unsupported required limits; OOM produces a resource error |
| PID | cgroup v2 pids.max/equivalent per Execution | Supervisor descendant counting is reactive, not hard isolation | Never substitute host-wide same-UID NPROC for a per-Execution limit |
| Disk | Filesystem/project quota where available + Workdir total supervision | Per-file rlimit + periodic total monitoring, with a sampling window | Terminate/reject and clean on excess; monitoring is not escape prevention |
| Wall time | Supervisor monotonic deadline | Same implementation | Earlier Run deadline wins; timeout cleans the group |
| Output | Runner hard per-stream byte limit and backpressure | Same implementation | Excess terminates to prevent memory/log floods |

Local Sandbox Provider wraps only these managed-process/resource operations. It supplies no mount/user/network namespace, syscall filtering, network egress, credential isolation, or untrusted-code safety guarantee. Complete strong sandboxing and the untrusted multi-tenant gate belong to Phase 6; this phase exposes no such public entry, and test targets are repository-fixed and accept no user code.

## 5. Configuration and Deployment

### 5.1 Settings cross-validation

Every FR-10 number uses bounded Pydantic Fields; when enabled, additionally require:

- Nonempty `execution_runtime_host_id`, with no other Host assigned to the execution root; `execution_workdir_root` is platform-owned, trusted, and not a symlink.
- Positive bounded grace, kill, reconcile, sample, and cleanup intervals; nonzero nonnegative wall timeout, CPU/memory/PID/disk/output limits.
- With `execution_resource_enforcement_required=true`, compute the support matrix before start and admit no process missing any requested capability.
- `execution_runtime_host_enabled=false` does not stop recovery/cleanup for existing records; only zero active processes permits full Supervisor shutdown.

### 5.2 Deployment precedents and changes

| Environment | Planned change | Constraint |
|---|---|---|
| quickstart | Reuse `app_data:/data`, with execution root `/data/execution`; set non-secret Host/limits and keep Host off by default | Controlled demo/test only, no untrusted execution; stop grace covers cleanup |
| production runtime-worker | Add dedicated `execution_data:/data/execution` and stable `AGENT_EXECUTION_RUNTIME_HOST_ID` | API and channel/knowledge/memory workers do not mount it; one Host per execution root |
| production `.env.example` | Add FR-10 non-secret placeholders and support-matrix documentation | No tokens, credentials, arbitrary commands, or user host paths |
| Multiple replicas | Shared execution root is unsupported in this phase | Scaling requires a new durable-lock/remote-Host/dedicated-volume design, not simply adding replicas |

## 6. Model Invocation Path

Phase 4 adds no model-invocation or credential path. React remains in-process through Model Gateway, and external test processes receive no real model keys. Future Engine model/CLI credentials must use controlled Phase 5/6 interfaces and cannot enter persisted ProcessSpec metadata, Workdirs, logs, or public events.

## 7. Test Plan Summary

| Layer | Cases |
|---|---|
| Unit | Host contracts, state machines, cancellation/timeout races, recovery decisions, path normalization, link policy, support matrix, and settings bounds |
| Real-process integration | Normal/nested children, TERM ignoring, output floods, crashes, Worker/container restart, PID reuse, and repeated cleanup |
| Workdir adversarial | Traversal, encoding bypass, cross-tenant paths, symlinks/hardlinks/mount points, check-use races, and safe deletion |
| Resource boundaries | CPU/memory/PID/disk/time/output excess within the support matrix and startup rejection on unsupported environments |
| PostgreSQL/migration | Table constraints/indexes, locking/idempotency, legacy React, default-off, application rollback, and disposable downgrade |
| Regression | Phase 0 React/Worker/Repository/SSE, Phase 3 capabilities/configuration/snapshots, and quickstart/production deployment checks |

See `04-test-plan.md`; unavailable resource environments are `pending_env`, and development approximations must not be reported as full support.

## 8. Rollout and Rollback

1. **Entry**: Phase 0–3 accepted; revalidate actual migration predecessor; Linux full support matrix, dedicated resource environment, and security review pass.
2. **Migration**: add two tables/indexes online with no historical rewrite; verify locks, constraints, and existing Run reads/writes on a production-like copy. Production rollback does not downgrade.
3. **Default-off deployment**: add volume/host_id/settings first, with no new process admission; recovery can still process existing records. React baseline diff must be zero.
4. **Controlled canary**: use only test tenants and built-in trusted processes, exercising cancellation/timeout/restart/Workdir/resources while observing cleanup failures and disk.
5. **Enablement boundary**: Phase 4 completion still does not enable untrusted multi-tenant code execution; real Codex remains Phase 5, and strong-sandbox/network/credential gates remain Phase 6.
6. **Normal rollback**: stop admission → cancel/drain all active processes → verify process groups, resources, and Workdirs → stop Host/Supervisor → roll back the application. Retain both tables and Tombstones.
7. **Emergency rollback**: immediately block new admissions while keeping recovery/cleanup alive; never kill Worker and roll directly back to code that does not understand process records. cleanup_failed blocks complete rollback pending manual remediation.
8. **Data rollback**: on disposable environments, downgrade drops `runtime_host_processes` before `execution_workdirs`; production table removal requires separate review and zero active processes.
