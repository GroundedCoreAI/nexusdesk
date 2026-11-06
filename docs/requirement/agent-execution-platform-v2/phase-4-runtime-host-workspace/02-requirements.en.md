# Phase 4 · Runtime Host, Process Supervision, and Workspace — Requirements

> Status: Pending review (implementation has not started)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G5); architecture Sections 3, 7–10, 17 Phase 4, 20, and 22

## User Stories

**US-1 (Engine Adapter developer)**: As an Adapter developer, I want one Host contract to start and cancel managed processes, so I implement only Engine/Protocol concerns without duplicating signals, process groups, and resource release.

**US-2 (Execution platform developer)**: As an execution platform developer, I want Run and OS-process lifecycles correlated but separately owned, so late results, lease loss, and cancellation cannot corrupt terminal states.

**US-3 (Operator)**: As an operator, I want Worker restart to discover, verify, and recover orphaned processes and stale directories, so resources do not leak indefinitely and new processes are not killed by mistake.

**US-4 (Security engineer)**: As a security engineer, I want every Workdir operation confined to its platform-assigned directory and resistant to link/race attacks, so cross-tenant and host files are unreachable.

**US-5 (QA)**: As QA, I want controlled cancellation, crash, limit, and malicious-path injection, so tests verify actual processes and resource boundaries rather than only coroutine state.

**US-6 (Security/platform owner)**: As a security or platform owner, I want a replaceable Sandbox and an explicit ban on untrusted multi-tenant execution in this phase, so partial resource controls are not mistaken for complete isolation.

**US-7 (SRE)**: As an SRE, I want Host health, active processes, cleanup failures, and Workdir usage, so I can alert before resource exhaustion and roll back safely.

## Functional Requirements

### FR-1 Runtime Host decoupled from Adapters

| Item | Description |
|---|---|
| Trigger | A process-capable Adapter prepares start/cancel/wait/reconcile |
| Input | Server-built ProcessSpec, Execution/Run ID, tenant/scope, Workdir, ResourcePolicy, and SandboxProvider |
| Output | Internal ManagedProcess handle, process state, and structured result; public APIs expose no PID/PGID/host path |
| Execution | Adapters call only the Host contract and handle protocols; Host neither parses Engine events nor commits Run terminal states, and Worker makes no direct process syscalls |
| Failure | Reject unregistered executables, untrusted commands, and unsupported platforms before spawn; Adapters cannot bypass Host to spawn |
| Traceability | G1; US-1, US-2 |

### FR-2 Process Runner and bounded I/O

| Item | Description |
|---|---|
| Trigger | Host starts, reads output from, and waits for a trusted ProcessSpec |
| Input | Fixed executable, allowlisted argv, minimal environment, isolated Workdir, output limits, and resource policy |
| Output | New process group/session, bounded stdout/stderr streams, exit code/signal, and start identity; sensitive environments enter neither DB nor logs |
| Execution | Asynchronous nonblocking reads; independent byte limits and backpressure per stream, with internal PID/PGID/start identity for Supervisor |
| Failure | Spawn, pipe, read, or start-identity failure cleans all created resources and fails closed; output excess terminates the group with a stable error code |
| Traceability | G1, G2; US-1, US-5 |

### FR-3 Cancellation, timeout, and process-group cleanup

| Item | Description |
|---|---|
| Trigger | User cancellation, Run/process wall timeout, Worker stop, Adapter exception, or resource-limit excess |
| Input | ManagedProcess, cancellation reason, termination grace, kill timeout, and current Run state |
| Output | Actual TERM → grace → KILL group exit, cleanup result, and `cancelled`/`run_timeout`/resource errors |
| Execution | Signal the whole process group and wait for observable descendants to release; coroutine cancellation also triggers Host cleanup rather than only cancelling await |
| Failure | Ignored TERM escalates to KILL; continued failure or unknown identity produces `cleanup_failed`/manual remediation and an alert, never a cleanup-success claim; late success cannot override cancellation |
| Traceability | G2; US-2, US-5 |

### FR-4 Durable Process Registry, orphans, and restart recovery

| Item | Description |
|---|---|
| Trigger | Persist on spawn/state changes; reconcile at Host start, periodically, and after Worker crash/container restart |
| Input | run_id, stable host_id, boot-scoped host_instance_id, PID/PGID, process-start identity, command digest, Workdir, and state timestamps |
| Output | Lockable process records, orphan decisions, TERM/KILL recovery, cleanup_failed, and recovery audit |
| Execution | At startup scan only unfinished records for the same host_id/execution root; recover after verifying host namespace, start identity, group, and command digest, without resuming Engine sessions |
| Failure | PID reuse or any identity mismatch forbids signals and enters manual remediation; processes outliving terminal Runs are still cleaned; DB failure never triggers blind host-wide scanning/killing |
| Traceability | G2, G5; US-3, US-5, US-7 |

### FR-5 Workspace Provider and Execution Workdir lifecycle

| Item | Description |
|---|---|
| Trigger | Prepare before Adapter start, activate during execution, retain/clean after completion/failure/cancellation, and recover records after Host restart |
| Input | Trusted tenant/business/workspace/run IDs, platform execution root, retention policy, and disk quota |
| Output | Unique Workdir per Execution (workdir/temp/logs), 0700 directories, and durable `preparing→ready→active→retained/cleaning→deleted` states |
| Execution | Platform generates directory names from safe IDs/digests; clients cannot provide host paths; logical Workspace and Execution Workdir remain separate |
| Failure | Creation/permission/disk-check failure prevents start; cleanup failure retains records for retry/alert and never pretends success by pointing elsewhere |
| Traceability | G3, G5; US-3, US-4 |

### FR-6 Paths, mounts, and safe cleanup

| Item | Description |
|---|---|
| Trigger | Before and during every file/directory create, read, write, export, mount resolution, and recursive cleanup |
| Input | Relative paths, platform-approved mount sources/destinations, directory handles, and Workdir records |
| Output | File operations and safe deletion confined to the owning Workdir; reject absolute paths, `..`, NUL, backslash/encoding bypasses, cross-tenant paths, and unapproved mounts |
| Execution | Open component-wise with no-follow from a trusted root handle and verify ownership; cleanup follows no symlinks, hardlinks/mount points are denied or explicitly allowlisted, and check/use share one safe handle |
| Failure | Path/link/race anomalies fail closed without modifying external targets; if deletion scope cannot be proven, stop and alert rather than running host-level recursive rm |
| Traceability | G3; US-4, US-5 |

### FR-7 Resource limits and support matrix

| Item | Description |
|---|---|
| Trigger | ProcessSpec validation, pre-spawn Sandbox preparation, runtime sampling, and Workdir write/cleanup |
| Input | CPU time, memory, maximum process count, Workdir total/per-file bytes, wall time, output limit, and resource policy |
| Output | Per-Execution resource-control handle, current usage, excess termination/rejection reason, and release result |
| Execution | Prefer per-Execution cgroups/equivalents; development may use explicitly qualified POSIX rlimits+supervisor; disk combines per-file limits with total monitoring/available quota, declaring each capability's strength |
| Failure | With `execution_resource_enforcement_required=true`, any unsupported requirement rejects start; never silently ignore, raise a limit, or substitute host-wide totals for per-Execution limits |
| Traceability | G4; US-5, US-6 |

### FR-8 Sandbox Provider and untrusted-execution gate

| Item | Description |
|---|---|
| Trigger | Host composition, ProcessSpec start, deployment enablement, and API-exposure review |
| Input | Sandbox Provider id/version, resource policy, trusted executable target, and deployment mode |
| Output | Replaceable Sandbox contract and Phase 4 Local Provider; only built-in trusted test targets can run |
| Execution | Host depends on the interface rather than a concrete Adapter; Local Provider supplies only declared process/resource controls, with no network, credential, or strong-kernel-isolation promise |
| Failure | Arbitrary commands, user-uploaded code, and untrusted multi-tenant execution are always rejected; configuration cannot bypass strong-sandbox/network/credential gates |
| Traceability | G4, G5; US-6 |

### FR-9 Health, audit, and observability

| Item | Description |
|---|---|
| Trigger | Host start/stop, spawn/exit/cancel/reconcile, resource sampling, and Workdir create/cleanup/failure |
| Input | Internal process/Workdir state, host_id, Run/tenant correlation, reason codes, and duration/usage |
| Output | Structured logs/metrics/health for active count, start failures, orphans, cleanup failures, recovery batches, exit reasons, disk usage, and retention age |
| Execution | Correlate by Run ID/host_id/stable error code with low-cardinality metrics; internal operational reads require authentication and scope, while public Run APIs expose no OS details |
| Failure | Alert on cleanup failure, repeated orphans, resource pressure, or stalled reconcile; logs/events contain no secret argv, environment values, tokens, or full host paths |
| Traceability | G5; US-3, US-7 |

### FR-10 Configuration, deployment, and rollback

| Configuration | Level | Default | Description |
|---|---|---|---|
| `execution_runtime_host_enabled` | Global settings | `false` | New Host master switch; off admits no new external processes, and recovery/cleanup must finish before shutdown |
| `execution_runtime_host_id` | Global settings / deployment | Empty string | Required when enabled, stable and unique per execution root; cannot be shared with another Host |
| `execution_workdir_root` | Global settings / volume | `data/execution` | Platform execution root backed by a dedicated production volume; clients cannot set it |
| `execution_sandbox_provider` | Global settings | `local` | Phase 4 local process/resource Provider, not a strong sandbox |
| `execution_resource_enforcement_required` | Global settings | `true` | Reject start when a required capability is unsupported |
| `execution_process_cancel_grace_seconds` | Global settings | `5.0` | Grace from TERM to KILL |
| `execution_process_kill_timeout_seconds` | Global settings | `5.0` | Wait after KILL before manual remediation |
| `execution_process_reconcile_interval_seconds` | Global settings | `5.0` | Active/orphan record reconciliation period |
| `execution_process_wall_timeout_seconds` | Global settings | `900` | Hard external-process wall-time ceiling; earlier of this and Run deadline wins |
| `execution_process_output_max_bytes` | Global settings | `1048576` | Limit per stdout/stderr stream; excess terminates |
| `execution_resource_cpu_seconds` | Global settings | `600` | CPU-time ceiling per Execution |
| `execution_resource_memory_bytes` | Global settings | `536870912` | Memory ceiling per Execution |
| `execution_resource_max_processes` | Global settings | `64` | Process-count ceiling per Execution |
| `execution_workdir_max_bytes` | Global settings | `1073741824` | Total Workdir ceiling per Execution |
| `execution_workdir_max_file_bytes` | Global settings | `134217728` | Per-file write ceiling |
| `execution_resource_sample_interval_seconds` | Global settings | `1.0` | Usage/descendant/disk supervisor sample period, not a security-isolation promise |
| `execution_workdir_retention_seconds` | Global settings | `86400` | Default successful/cancelled Workdir retention |
| `execution_workdir_failed_retention_seconds` | Global settings | `604800` | Failed Workdir retention before safe cleanup |
| `execution_workdir_cleanup_interval_seconds` | Global settings | `60` | Scan period for expired and cleanup_failed retries |

## Non-Functional Requirements

- **Performance**: isolate process/directory operations asynchronously or through threads without blocking Worker scheduling; bound I/O, metric labels, and reconcile batches, and measure supervision overhead against a Phase 0 baseline.
- **Reliability**: record Run terminal state, process exit, resource release, and directory deletion separately; all cleanup is idempotent, and repeated cancel/reconcile cannot cause duplicate-signal kills or duplicate deletion.
- **Security**: deny arbitrary commands and host paths by default; untrusted multi-tenant code execution is hard-disabled, and Local Provider/cgroups/rlimits do not constitute a strong sandbox.
- **Multi-tenancy**: bind DB records and directories to tenant/business/workspace/run; cross-tenant access is unreachable and ownership is rechecked before cleanup.
- **Portability**: Linux is the full acceptance target; macOS runs only an explicitly supported development subset, and Windows/unsupported capabilities fail closed rather than reporting false passes.
- **Observability**: correlate health, resources, and cleanup by Run/host without exposing PID/path publicly; logs, events, DB metadata, and artifacts contain no secrets.
- **Reversibility**: new Host is off by default and React is unchanged; stop admission → cancel/drain → verify zero active → disable → roll back the application while retaining new tables.

## Acceptance Criteria

| # | Scenario | Expected result | Traceability |
|---|---|---|---|
| AC-1 | Two different test Adapters use the same RuntimeHost; inspect dependencies and public APIs | Host/Worker need no changes for reuse; Adapters contain no direct spawn/signal/resource branches, and public responses expose no PID/path | FR-1; G1; US-1, US-2 |
| AC-2 | Start a normal test process, exchange bounded I/O, and wait for exit; then inject pipe errors and output floods | Normal exit/result is correct; I/O does not block Worker; failures clean up completely, output excess kills the group, and logs contain no secrets | FR-2; G1, G2; US-1, US-5 |
| AC-3 | Cancel after the process spawns a TERM-ignoring child; repeat cancellation and deliver late success | After grace, KILL reaches the whole group and all descendants exit; Run is cancelled, late success cannot override it, and cleanup is idempotent | FR-3; G2; US-2, US-5 |
| AC-4 | Trigger Run deadline, process wall timeout, and a cancellation race separately | Earlier deadline wins; process group/resources are released, error/terminal state is stable, and no duplicate terminal state or leak remains | FR-3; G2; US-2, US-5 |
| AC-5 | Kill Worker/restart its container with live processes, then simulate PID reuse, identity mismatch, and DB outage | Matching orphans are recovered; mismatch kills are zero; DB failure causes no blind kill, and manual remediation/alerts are explicit | FR-4; G2, G5; US-3, US-5 |
| AC-6 | Create Execution Workdirs concurrently, expire/clean after completion/failure/cancellation, and recover after restart | Directories are unique with correct permissions and recoverable states; retention works and cleanup is idempotent with retry/alert on failure | FR-5; G3, G5; US-3, US-4 |
| AC-7 | Submit absolute paths, `..`, encoding/separator bypasses, cross-tenant paths, and unapproved mount sources | All are rejected before touching external resources; valid relative paths work and public APIs accept no host paths | FR-6; G3; US-4, US-5 |
| AC-8 | Create symlinks, hardlinks, mount points, and check-then-replace races targeting external files, then read/write/clean | Successful external reads/writes/deletes are zero; uncertain scope stops with an alert and no host-level recursive deletion | FR-6; G3; US-4, US-5 |
| AC-9 | Exceed CPU, memory, PID, Workdir total/per-file, wall-time, and output boundaries within the support matrix, then start on an unsupported environment | Excess is rejected/terminated within specified time and resources are released; unsupported required capabilities reject start, with zero silent ignores | FR-7; G4; US-5, US-6 |
| AC-10 | Replace the Sandbox test Provider and attempt arbitrary commands, uploaded code, and untrusted multi-tenant execution | Host swaps Providers without Adapter changes; every untrusted-execution entry remains denied and Local Provider makes no strong-sandbox claim | FR-8; G4, G5; US-6 |
| AC-11 | Observe normal, crash, orphan, cleanup-failure, and resource-pressure states, then attempt public reads of internal fields | Metrics/logs/alerts cover every state and correlate Run/host; secrets and PID/PGID/full paths stay out of public surfaces | FR-9; G5; US-3, US-7 |
| AC-12 | Upgrade planned `0054`, verify legacy React and default-off, then drill stop admission → drain → disable → application rollback | Only necessary process/Workdir tables are added; React has no regression; rollback leaves zero active orphans, retains records, and needs no downgrade | FR-4, FR-5, FR-10; G1, G5; US-2, US-3, US-7 |
