# Phase 4 · Runtime Host, Process Supervision, and Workspace — Business Goals

> Status: Pending review (implementation has not started)
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 3, 7–10, 15–17 Phase 4, 19, 20, and 22; Phase 0–3 planning documents
> Estimated effort: ~3–4 weeks (re-estimate after the Phase 0 baseline and support-matrix review)
> Dependencies: Phase 0–3 accepted; Linux/POSIX and PostgreSQL test environments; availability of a dedicated resource-control environment confirmed

## Problems to Solve

### Problem 1: External Engines lack a process-lifecycle boundary decoupled from Adapters

The current `core_platform/agent_runtime/worker.py` manages only asyncio tasks, while `runtime_factory.py` always constructs the in-process ReAct Runtime. No Runtime Host, Process Runner, or Supervisor exists. If every Adapter creates its own subprocesses, cancellation, signals, process groups, output bounds, and resource release will diverge by Engine.

### Problem 2: Coroutine cancellation does not prove that the actual process and descendants stopped

Existing Worker cancellation and lease-loss paths cancel the Runtime coroutine, but there is no OS process tree to clean. Once an external Engine forks children, cancelling only the waiting coroutine leaves orphans. After a Worker crash or container restart, no durable record safely identifies old processes for recovery, and signaling by PID alone is unsafe.

### Problem 3: An execution has no controlled, recoverable Workdir

The architecture separates long-lived Workspace from Execution Workdir, but no `agent_execution/workspace` implementation or execution-directory persistence exists. Allowing clients to provide host paths, or relying on string `resolve()` checks alone, enables traversal, symlink/hardlink escape, cross-tenant overwrite, and unsafe cleanup.

### Problem 4: Resource limits, Sandbox boundaries, and host health lack unified contracts

Existing settings include Run timeout, concurrency, and business-storage limits, but no external-process CPU, memory, PID, Workdir disk, or output limits, Sandbox Provider, or Runtime Host health metrics. OS/container support varies; silently ignoring unsupported limits would create a false security promise.

## Business Goals

| Goal | Description |
|---|---|
| G1: Establish an Engine-independent Runtime Host | Adapters handle only Engine/Protocol concerns; Host centrally manages processes, Workdirs, Sandbox, and resources; Worker performs no process syscalls |
| G2: Guarantee verifiable process terminal states and recovery | Normal exit, cancellation, timeout, crash, and Worker restart clean process groups/children; orphan recovery verifies identity to avoid PID-reuse kills |
| G3: Provide an isolated Workdir per execution | Every Execution receives a platform-generated directory and durable lifecycle record, blocking traversal, link escape, cross-tenant access, and out-of-scope cleanup |
| G4: Establish configurable resource boundaries and a Sandbox interface | CPU, memory, PID, disk, wall time, and output have explicit limits and a support matrix; unsupported requirements fail closed, while strong sandboxing remains Phase 6 |
| G5: Be observable and reversible without affecting React | Expose host/process/Workdir health and cleanup telemetry; the new Host is off by default and rollback abandons neither active processes nor audit records |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| External test-process and descendant cleanup rate | Pending Phase 0 inventory of cancellation/restart coverage; no external-process baseline exists | 100% cleanup in specified normal, cancellation, timeout, crash, and restart scenarios, with no managed descendants left |
| Cancellation/timeout to actual process-group stop latency | Pending Phase 0 measurement of existing cancellation latency; no OS-process baseline | Complete within configured grace + kill timeout plus 2s observation allowance; failure to stop alerts and is never reported as successful cleanup |
| Safe orphan identification | Pending Phase 0 inventory of Worker recovery semantics | 100% identification of recoverable orphans; zero kills on PID reuse/identity mismatch; unconfirmed processes enter manual-remediation state |
| Workdir isolation and malicious-path rejection | Pending Phase 0 inventory of filesystem path-safety coverage | 100% unique directories for valid Executions; zero escapes in specified traversal, absolute-path, symlink/hardlink, and race cases |
| Effective resource-limit enforcement | Pending Phase 0 inventory of deployment resource controls | Within the support matrix, every CPU/memory/PID/disk/time/output excess is terminated or rejected; zero silently ignored required capabilities |
| Host health and rollback observability coverage | Pending Phase 0 inventory of Worker health/metrics | 100% structured observability for active processes, orphans, cleanup failures, Workdir usage/retention, and recovery batches; zero active orphans after rollback |

## Scope

**Included**:

- Runtime Host, Process Runner, Process Supervisor, durable Process Registry, and Adapter-decoupled contracts.
- Process-group/child cleanup, bounded stdin/stdout/stderr handling, cancellation, timeout, crash, and restart recovery.
- Workspace Provider, Execution Workdir, mount/retention/cleanup policy, and safe path operations.
- Planned migration `0054_execution_runtime_host`: add only process and Workdir durable records required for cross-restart recovery, not a generic RuntimeHost service table.
- Configurable resource limits, Local Sandbox Provider, replaceable Sandbox interface, explicit support matrix, and fail-closed behavior.
- Host health, process/Workdir metrics, deployment volumes, failure/malicious/resource-boundary tests, and rollback.

**Excluded** (later phases / explicitly not in scope):

- Codex or other real external Engine Adapters, protocol parsing, and Session Resume (Phase 5).
- Complete strong sandboxing, container/VM isolation, network egress, untrusted credential brokering, and end-to-end Secret governance (Phase 6).
- **No untrusted multi-tenant code execution**, no arbitrary-command/arbitrary-host-path API, and no representation of local rlimit/cgroup controls as a security sandbox.
- Shared execution volumes across hosts, multiple replicas competing for one process, or automatic recovery of side-effecting external Engine sessions.
- Long-lived Workspace snapshots, shared Skill Store, Artifact object storage, or global tenant-fair scheduling (later review as needed).

## Risks and Constraints

- **Local isolation is not a strong sandbox**: processes with the same UID/kernel can still exceed authority; Phase 4 runs only built-in trusted test processes, and untrusted external execution remains disabled.
- **PID/PGID reuse**: signaling only by PID after restart can kill unrelated processes; verify host, process-start identity, group, and command digest, and forbid signaling with an alert on mismatch.
- **Path races**: a check-then-open sequence can be defeated by symlink replacement; use directory-handle-based, component-wise no-follow operations, and never follow links during cleanup.
- **Resource-support differences**: rlimit, cgroup, and filesystem quota support varies by OS/container; probe every limit required by an Execution and refuse start if it cannot be enforced.
- **Cleanup consistency**: Run terminal state, process exit, and Workdir deletion can complete at different times; persist each state and record `cleanup_failed`, never treating a Run terminal state as proof of resource release.
- **Shared-volume risk**: in Phase 4, each execution root belongs to one stable host_id; multiple Hosts cannot concurrently manage the same root.
- **Compatibility**: the in-process React path remains unchanged and the new Host is off by default; `0054` is a planned identifier, so revalidate actual head/down_revision before implementation and never alter the planned `0053` implementation or historical migrations.
