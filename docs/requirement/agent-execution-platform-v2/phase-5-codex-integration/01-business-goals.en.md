# Phase 5 · Codex Integration — Business Goals

> Status: Pending review (planning only, not implemented; the current code has no Codex support)
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 3.2, 4, 5, 7–10, 12–13, 17 (Phase 5), and 19–22; see `03-technical-design.md` for the current-state audit

> Phase: Phase 5 (Stage A: CLI Exec; Stage B: App-Server, unlocked strictly in sequence)
> Estimated effort: approximately 4 weeks for Stage A and 4 weeks for Stage B, to be confirmed after review
> Dependencies: Phases 0–4 accepted; supported Codex versions and test authorization confirmed; restricted to explicitly trusted tenants until Phase 6 is complete

## Problems to Solve

### Problem 1: There is no external Codex execution path

The current `RuntimeFactory` and `RuntimeWorker` still center on the LangGraph ReAct Runtime. The repository code and tests contain no Codex CLI, App-Server, JSON-RPC, or Codex Session implementation. Adding engine-specific branches directly would create a second execution path and bypass the common contract, Worker, and event governance.

### Problem 2: Coroutine lifetime cannot substitute for real external-process governance

Current Worker cancellation primarily cancels an asyncio Task. Codex CLI and App-Server also involve process trees, stdio, connections, timeouts, and orphaned resources. They must be started, stopped, and cleaned through the Phase 4 RuntimeHost; host PIDs, arguments, and private protocols must not leak into public APIs.

### Problem 3: Protocols, Sessions, and native semantics can easily be unified incorrectly

CLI Exec and App-Server are different Protocols for the same `codex` Engine. Reusing the Engine identity while conflating Protocols, or forcing Codex events into ReAct Tool Calling, would damage event fidelity, Session/Run mapping, and future protocol extensibility.

### Problem 4: Credentials and Workspace are release blockers

The current model-gateway Vault is not an Execution-level Credential Broker, and the current logical Workspace is not a strong sandbox. Phase 5 must not copy the host `~/.codex/auth.json`, share credential directories across tenants, or open code execution to untrusted tenants before the complete Broker and strong sandbox arrive in Phase 6.

## Business Goals

| Goal | Description |
|---|---|
| G1: Establish governed Codex CLI execution | Complete the Stage A request, event, result, usage, cancellation, and timeout loop through the common execution contract and RuntimeHost. |
| G2: Validate Engine/Protocol decoupling | `codex/cli_exec` and `codex/app_server` share an Engine identity while registering and versioning independently, without polluting the Worker or public APIs. |
| G3: Preserve native Codex value | Retain bounded native events and metadata while mapping stable platform events and collecting final results and usage, without pretending Codex is ReAct reasoning. |
| G4: Enforce execution security boundaries | Use isolated Execution Workdirs, controlled credential references, and Effective capability policy; untrusted tenants remain disabled until Phase 6. |
| G5: Deliver App-Server and Sessions in a controlled rollout | Implement JSON-RPC, streaming interaction, native Sessions, and reauthorized Resume only after the Stage A stability gate passes. |
| G6: Preserve existing behavior and rollback | No regressions to React, existing Run/API/SSE behavior, or historical configuration; CLI and App-Server can be rolled out and disabled independently. |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| Number of integrated Codex Protocols | 0; code search found no Codex Adapter | 1 for Stage A and 2 after Stage B acceptance, both using `engine_id=codex`. |
| Codex contract and end-to-end scenario pass rate | Unmeasured; external-Engine baseline pending Phase 0 | 100% of applicable UT/IT/CM and AC cases pass, with no open P0/P1 defects. |
| Stage A stability gate | Unmeasured; pending Phase 0 | Stage B is unlocked only after three consecutive pre-release applicable regression runs pass and one batch of at least 20 mixed success/failure/cancellation scenarios has no P0/P1 defects. |
| Native-event and usage correlation completeness | Unmeasured; pending Phase 0 | Supported native events, final results, and available usage correlate to the same Run/Execution; missing usage is explicit rather than reported as zero. |
| Actual cleanup rate after cancellation/timeout | Unmeasured; pending Phase 0 | In 100% of applicable scenarios, the process tree terminates and Workdir/connection resources are released within the configured grace period; failures are never reported as success. |
| Credential and cross-tenant leakage | Unmeasured; security baseline pending Phase 0 | Adversarial cases show zero plaintext Secret, host auth-file, or cross-tenant file disclosures; zero untrusted tenants are enabled. |
| React regression differences | Unmeasured; pending Phase 0 | With switches off, behavioral diff from the Phase 0 baseline is zero and existing regression suites are green. |
| Execution overhead and startup latency | Unmeasured; pending Phase 0 | Record CLI/App-Server p50/p95 first; do not claim performance improvement without a baseline, and review/freeze budgets after Phase 0. |

## Scope

**Included**:

- Stage A: supported-version detection and a pinned compatibility matrix, typed Codex configuration, CLI Adapter, RuntimeHost launch, stdout/stderr parsing, native events, results/usage, cancellation/timeouts, Workspace, and controlled credential policy.
- Stage A stability gate, contract tests, fault injection, trusted-tenant canary rollout, and an independent switch.
- Stage B: App-Server JSON-RPC encapsulation, connection lifecycle, Session/Turn/Run mapping, streaming events, capability-gated approvals/interactive input, and Session Resume with reauthorization.
- The planned `agent_engine_sessions` migration and Repository when Stage B requires persistent Sessions.
- React regression coverage, auditing, metrics, bilingual implementation planning, and rollout/rollback plans.

**Excluded** (later phase / explicitly out of scope):

- Complete Credential Broker, full short-lived credential lifecycle, strong sandbox, network egress, and cross-log/event/artifact redaction: Phase 6 and blockers before opening to untrusted tenants.
- Fencing Tokens, transactional Event Outbox, event deduplication/general replay governance, and idempotent usage aggregation: Phase 6; Phase 5 only collects and correlates data.
- Claude Code, ACP, OpenClaw, multi-Engine routing/fallback, and large-scale scheduling: Phase 7 or later.
- A custom Codex reasoning loop, exposing the native Codex protocol as a NexusDesk public API, or unconstrained support for every Codex release.
- This phase does not modify historical migrations or claim that currently absent Codex functionality is already available.

## Risks and Constraints

- **Codex version drift**: stdout/JSON-RPC/usage changes can break parsing; pin verified versions, check compatibility at startup, test contract fixtures, and fail closed on unknown versions.
- **Premature Stage B expansion**: parallel implementation would hide CLI foundation issues; App-Server merge and enablement remain locked until the Stage A stability gate passes.
- **Cancellation does not imply exit**: coroutine cancellation can leave child processes; rely on RuntimeHost evidence of process-group exit and resource release.
- **Unauthorized Session recovery**: a native Session ID is not authorization; Resume must recheck tenant, Agent, Workspace, credential scope, Protocol/Adapter, and Effective policy.
- **Credential security is a hard gate**: until the complete Broker and strong sandbox in Phase 6 are finished, only deployment-registered trusted tenants are allowed; deny by default and do not enable untrusted multi-tenant code execution.
- **Compatibility**: React remains the default; new fields and events are backward compatible, Codex switches default off, and rollback does not require dropping new tables or rewriting historical Runs.
