# Phase 3 · Capabilities, Configuration, and Instructions — Business Goals

> Status: design calibrated against code reality (not implemented, tested, or accepted)
> Created: 2026-11-02
> Revised: 2026-11-12 (migration, actual Phase 1/2 state, start barrier, preview, and evidence gates)
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 5, 6, 11, 14, 15, 17, 19, and 22; Phase 0–2 06/07; `02-requirements.md` (FR-1–FR-9)
> Estimated effort: ~2 weeks (re-estimate before T2)
> Development entry: baseline `3969258` contains merged Phase 1/2 code, with focused baseline 163 passed / 5 skipped; this is neither completed upstream formal acceptance nor final launch approval

## Problems to Solve

### Problem 1: Agent configuration cannot safely express multi-Engine selection

`AgentConfig(extra=forbid)` in `business_capabilities/agent_config/service.py` contains only existing root fields. Phase 2 `ExecutionOrchestrator` fixes `react/native/v1`, while the Registry has identity/factory data but no configuration schema, declarations, probe, policy, or provider metadata. An unrestricted dictionary would bypass exact typing and publication checks; blindly adding defaults would cause UPDATEs on historical reads or default noise in canonical diffs.

### Problem 2: Technical capability, environment availability, and authorization lack one decision chain

`EngineCapabilities` currently contains only 11 Declared booleans, and `ExecutionRequest.effective_capabilities` is only an internal DTO field. No Declared → Available → Policy → Effective resolver, trusted probe/policy ports, or cache boundaries exist. Treating Adapter declarations or client fields as authorization would confuse support with permission. Phase 3 requires least-privilege defaults and makes `workspace_required=true` unavailable without Workspace.

### Problem 3: Instructions and Summary/Memory injection are coupled to ReAct messages

`RuntimeFactory.effective()` builds the system prompt and `RuntimeEngine.run()` assembles SystemMessages; Worker already supplies rendered Summary/Memory. ReactAdapter.start creates the runner before RuntimeFactory assembles Runtime. Without a testable preparation/render → Adapter.start barrier, new Engines would duplicate prompt/Memory logic or change existing message ordering.

### Problem 4: An execution lacks an immutable decision snapshot

`runtime_runs.config` stores input snapshots but not five separate resolved configuration, Declared, Available, Policy, and Effective snapshots. After configuration, probe, or policy changes, a historical Run cannot explain its allow/deny decision. Public APIs must not expose those internal snapshots as a side effect.

## Business Goals

| Goal | Description |
|---|---|
| G1: Compatible, typed multi-Engine configuration | Default legacy configuration to `react/native/v1`; strict Registry-metadata schemas; accept equal legacy aliases, reject unequal aliases; no UPDATE on historical reads and no default noise in canonical diffs |
| G2: Server-side capability governance | Build a least-privilege, monotonically narrowing Declared → Available → Policy → Effective chain; clients, previews, and Adapters cannot bypass environment or policy |
| G3: Replaceable Engine instruction rendering | InstructionInput/Providers adapt Engine formats; compute the system prompt and Summary/Memory once while preserving React message order, wording, budgets, and write-back |
| G4: Traceable and reversible execution decisions | Persist all five snapshots once before Adapter.start for Phase 3 Runs; serialization/DB failures prevent start; rollback changes neither public `run.started` order nor historical snapshots |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| Legacy Agent draft and published-snapshot compatibility | Phase 0 synthetic valid fixtures: 5/5; authorized real historical samples remain `pending_env` | 100% of listed valid fixtures load, normalize, republish, and execute as React as specified; no bulk JSONB rewrite; missing real samples block a complete-pass claim |
| Rejection rate for invalid or unknown execution configuration | Existing AgentConfig/RunRequest are `extra=forbid`; no Engine schema exists | 100% stable rejection of unknown triples, type errors, extra fields, unequal aliases, and unavailable required capabilities |
| Successful client capability escalations | Public RunRequest has no capability fields; no Phase 3 preview API exists | Zero elevation through forged Declared/Available/Effective, Policy, host fields, or cross-tenant preview |
| Decision-snapshot completeness for Phase 3 Runs | No five snapshot columns | 100% five-snapshot coverage for completed, failed, cancelled, and timed-out Runs that reached Adapter.start; zero start calls without committed snapshots |
| React instruction compatibility | Phase 2 has controlled parity evidence; upstream real-world gaps remain as reported | Zero diff in existing message order/wording for empty, disabled, Summary, Memory, combined, and truncation cases; business rendering runs once |
| Added configuration/capability resolution latency | Numeric baseline pending measurement | After cache warmup, collect at least 100 valid interleaved paired samples of the real implementation in one environment; added p95 ≤50ms, excluding external model time; otherwise `not_measured`/`pending_env` |

## Scope

**Included**:

- Extend existing AgentConfig JSONB draft/publication flows with `ExecutionConfig`/legacy normalization, without a new Agent configuration table.
- Extend Registry registration metadata with strict config schema, Declared capabilities, probe, and policy/provider identities; drafts and previews instantiate no Adapter.
- Declared/Available/Policy/Effective types, trusted probe/policy ports, caching/invalidation, least privilege, and read-only Effective preview.
- Plan migration `0058_agent_execution_metadata` to add only five nullable snapshot columns to `runtime_runs`, dynamically revalidating `down_revision` before implementation.
- InstructionInput, React/test Providers, Orchestrator/ExecutionContext/ReactAdapter/RuntimeFactory extensions, and the start barrier.
- `POST /api/v1/agents/execution-preview`, modest component extraction within the existing AgentsPage, four locales, OpenAPI, auditing, tests, rollout, and rollback.
- An independent low-sensitivity idempotent example seed and fresh-quickstart automatic wiring/verification only after development, testing, and acceptance finish.

**Excluded**:

- Runtime Host, real external processes, Execution Workdir, or Sandbox (Phase 4).
- Codex CLI/App-Server, production instruction files, or Skill mounts (Phase 5).
- Credential Broker, strong sandboxing, network egress, Fencing/Outbox, and other full security/reliability work (Phase 6).
- Separate Task/Execution tables, relational Agent configuration, latest Adapter aliases, automatic cross-Engine fallback, or a general policy console.
- A new component-test runner, Postman publication, or external preview service; retain typecheck/i18n/build and targeted Playwright.

## Risks and Constraints

- **Ambiguous dual-write configuration**: equal legacy root and `react` values normalize; unequal values are rejected rather than silently choosing one.
- **Availability-probe instability**: synchronous hot paths read only bounded caches; miss/stale/failure means unavailable, and background probes have timeouts and start no external Engine.
- **Unclear policy provenance**: the platform ceiling grants the minimum by default; tenant/Agent/Execution layers only narrow; unknown capabilities/policy versions fail closed.
- **Snapshot disclosure and growth**: each of five DTOs has a denylist, schema/version, and size limit; no secrets, raw Summary/Memory, stderr, or host paths; public responses remain allowlisted.
- **Misread startup ordering**: preserve public `run.started` from `Repository.claim`; the snapshot barrier constrains Adapter.start/side effects only and does not change Phase 2 public events.
- **Instruction regressions**: Providers do not query Memory or rebuild system prompts, and do not alter dual emit/ack, history, budgets, logs, or completion write-back.
- **Compatibility**: historical `agents.draft`/`agent_versions.config` remain untouched; new default fields persist only when users explicitly adopt the new shape, while historical reads and default-equivalent diffs stay quiet.
- **Migration constraint**: `0058` currently follows `0057_industry_pack_runtime`; revalidate before T2 and never modify `0053_routing_decisions` or other historical migrations.
