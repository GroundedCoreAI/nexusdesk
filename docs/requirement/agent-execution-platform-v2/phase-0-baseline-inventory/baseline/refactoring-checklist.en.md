# Phase 0 Baseline · Identifiers and Phased Refactoring Checklist

> Status: Baseline checklist only; it does not indicate formal double-run, CI, acceptance, or Phase 1 approval
> Current-state target commit: `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> Current artifact tree: uncommitted feature-branch working tree with no fictitious SHA; later evidence must distinguish the target commit from the actual artifact
> Frozen on: 2026-11-07; T8 expansion: 2026-11-08
> Basis: `configuration-compatibility.en.md`, `regression-baseline.en.md`, `04-test-plan.en.md`
> Use: compare the target SHA at the start of each later phase and append new evidence item by item; never overwrite this baseline or substitute target architecture for current-state verification

## 1. Frozen Identifiers and Terminology

| Item | Frozen value | Constraint |
|---|---|---|
| Production React Engine | `react` | Future public Engine ID for the current LangGraph ReAct, not a Python class name |
| Production native Protocol | `native` | Preserve native ReAct model/tool semantics; do not flatten events |
| Initial Adapter | `v1` | Resolve explicitly; no implicit latest |
| Production tuple | `(react,native,v1)` | Must match across Phase 2 old/new React paths and Phase 3 legacy-config defaults |
| LocalTestAdapter tuple | `(local-test,scripted,v1)` | Test-only; never a production Agent default or evidence of real process supervision |
| Execution | One execution attempt | Initially `Run = one Execution attempt`; Phase 1 defines the execution_id/Run ID mapping |
| Task | No dual table | No Task/Execution dual-table model or second current state machine |
| Worker selection | No Engine branches | Resolve Engine/Protocol/Adapter exactly through contracts and registries, not vendor if/else in Worker |

Every new ID, version, or incompatible combination requires a compatibility-matrix entry and contract tests. Do not reuse `react` for a different reasoning implementation or use `local-test` to pass production authorization. AgentConfig currently rejecting an unknown `engine` field is current-state `extra=forbid` evidence, not prior approval of a future Engine mapping.

## 2. Common Gate for Every Refactor

- [ ] Record the implementation target SHA, clean worktree, and actual Alembic head; produce an incremental diff against the Phase 0 baseline and distinguish the current-state target from the current artifact commit.
- [ ] Preserve the five Run states, cancellation flag, owner/lease, fingerprint, per-Run Agent snapshot, and terminal transaction.
- [ ] Rerun Runtime core and baseline tooling: `test_runtime_engine.py`, `test_runtime_baseline.py`, `test_runtime_baseline_tooling.py`, and `test_runtime_baseline_fixtures.py`; retain raw summary/compare outputs.
- [ ] Rerun `test_agent_config_execution_compat.py` for AgentConfig fixture/publication/snapshot/tenant isolation/queued-Run snapshot and sparse raw-version limitation evidence; new compatibility-matrix cases must declare exact Pydantic `loc` arrays.
- [ ] For Runtime persistence, concurrency, SSE/replay, or Run API changes, rerun `test_runtime_postgres.py`, `test_runtime_availability.py`, `test_runtime_scope.py`, `test_tool_replay_postgres.py`, `test_platform_postgres.py`, and `test_open_platform.py` as applicable; run corresponding `test_agent_*` suites for Agent language/model-constraint changes.
- [ ] For memory or context-assembly changes, rerun `test_memory_config.py`, `test_memory_postgres.py`, `test_memory_customers_postgres.py`, and `test_memory_config_postgres.py` as applicable, especially the injection-detail, cap, switch, and isolation assertions in `test_memory_injection_postgres.py`.
- [ ] For model/tool boundary changes, rerun `test_model_gateway.py`, `test_model_discovery.py`, `test_tool_egress.py`, `test_tool_post.py`, `test_tool_credentials.py`, and `test_tool_workspace.py` as applicable. Unrelated edits do not mechanically require every suite; a phase-level formal baseline still follows its defined list.
- [ ] Assert ordinary durable events separately from transient deltas; preserve strict-after replay, terminal draining, and public-field reduction, with a separate judgment for the specialized `tool.replay` boundary.
- [ ] Retain reasons for every failure, skip, xfail, and pending_env; compare double-run `(classname,name)` nodes, outcomes, and skip reasons rather than only totals; durations do not participate in equivalence.
- [ ] Do not expose config/history/credentials/connection strings/raw provider text; fixtures remain synthetic, and real-production representativeness remains `pending_env` until authorized evidence exists.
- [ ] Give production fixes and behavior changes separate small commits with before/after evidence; never hide them in an "equivalent refactor."
- [ ] Create database changes on the actual implementation-time head; never edit an applied migration. A no-migration phase must prove the head is unchanged.

## 3. Phase 1–7 Mapping

| Phase | Must preserve/verify | Mandatory baseline and new evidence | Rollback/stop condition |
|---|---|---|---|
| Phase 1 Contracts and Registries | Zero production wiring; independent frozen tuples; explicit versions; neutral RunPort is not mistaken for the current HTTP contract | All new contract/Registry/LocalTestAdapter tests + Runtime unit, baseline-tooling/fixture, and static-identity checks; head equals the entry value | Rollback removes only unwired code; production wiring, implicit latest, Worker branches, or migration stops the line |
| Phase 2 React Provider/Orchestrator | Old/new output/history/dropped, events, errors, cancellation, reaper, and memory completion effects remain equivalent; Worker depends only on orchestration | Double-run all applicable Phase 0 Runtime/PostgreSQL/SSE/replay/AgentConfig/memory-injection baselines; same-script old/new A/B; Factory and direct-Runtime compatibility paths | Restore the old path by flag with no data reversal; any terminal, event, config, memory-side-effect, or cross-tenant difference stops the line |
| Phase 3 Capabilities/Config/Instructions | Legacy defaults map to `(react,native,v1)`; raw historical JSONB is unchanged; Declared/Available/Effective remain separate from authorization; resolve P0-I7's storage-stage limitation first | All fixtures and publication/snapshot/versioned execution; old/new default equivalence; client-elevation and cross-tenant adversarial tests; sparse raw-version fix or formal adjudication with regression | New config parsing can be disabled; valid legacy failure, rewritten history, or client elevation stops the line; do not misreport the manual sparse-row limitation as a public-publish failure |
| Phase 4 Runtime Host/Workspace | Process state does not duplicate Run governance; separately prove process-tree cleanup, path/symlink isolation, and resource limits | Phase 0 lifecycle/cancellation/late-write tests + new process-failure/workspace adversarial tests; LocalTestAdapter is not Host evidence | New Host remains off by default; host escape, leakage, dangling processes, or incomplete cancellation cleanup stops the line |
| Phase 5 Codex A/B | CLI/App-Server native protocols remain inside Providers; common governance does not flatten native events; credentials never enter fixtures/logs | Phase 0 contracts/lifecycle/SSE + new Provider contract suite and controlled integration; paid/external services are not mandatory for the old baseline | App-Server stays off until CLI is stable; security, fallback, or event-compatibility failure disables the new Provider |
| Phase 6 Security/Reliability/Event Governance | Fencing, Outbox, deduplication, cancellation/replay races; review ordinary and replay-specialized event paths separately | All applicable Phase 0 baselines + fault-injection, adversarial, security, and concurrency tests; use the terminal `tool.replay` SSE test as current-state evidence while explicitly adjudicating the unresolved post-terminal seq consumption | Untrusted multi-tenant launch requires every isolation/credential/network/resource gate; a P2 deferral or existing test evidence cannot bypass a security veto |
| Phase 7 Advanced Capabilities/Scale | Deferred since 2026-11-07; after reactivation, review independent slices and re-evaluate routing/fallback policy | No execution or acceptance now; after activation reuse applicable baselines and add evidence per slice | Track P4 issues #110–#120; without explicit reactivation there is no delivery commitment or weakening of earlier gates |

## 4. Current Differences, Open Items, and Ownership

| ID | Severity/status | Item | Owner / deadline | Phase 1 impact |
|---|---|---|---|---|
| P0-I1 | `pending_env` | Clean-CI double run of the same artifact commit, raw artifacts, and CI links do not yet exist | Engineering lead + QA; before Phase 1 entry review | Local double runs do not replace CI AC-4 evidence |
| P0-I2 | `pending_env` | No authorized real historical published snapshots were supplied; current fixtures are explicitly labelled synthetic field shapes | Agent-config representative + security representative; before Phase 1 config compatibility review | Do not claim real-sample representativeness; add samples or record a formal scope decision |
| P0-I3 | P2 / open | Open-platform stream comment says no token delta, while visible-text deltas are emitted | Open-platform backend owner; before Phase 2 | Does not change the current baseline or unwired contracts |
| P0-I4 | P2 / open | A specialized `tool.replay` invocation can consume seq after terminal state. `test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor` now proves current SSE payload hiding and cursor advancement, but the security/behavior boundary remains unfixed and unadjudicated | Runtime + security owner; no later than the Phase 6 security gate | Isolated and documented in Phase 0; terminal Run state is not overwritten. Do not call test evidence a security fix or spread this behavior to new event paths |
| P0-I5 | P3 / open | Existing full-format-check differences in `seed_memory_*` | Owning script maintainers; with later changes to those scripts | Unrelated to Phase 0 additions; do not mix bulk formatting into this phase |
| P0-I6 | Environment note | Ignored legacy directories/`__pycache__` interfere with local architecture scanning; the gate passes in a clean target worktree | Local environment owner; on later local reproduction | Not part of the target Git tree; never delete user files to manufacture a "clean" result |
| P0-I7 | P2 / open | A manually inserted extremely sparse raw version passes `AgentConfig` input validation, but direct `snapshot()` currently raises `KeyError("tool_names")`. This is a storage-stage limitation; it proves neither that public publish creates such a row nor that all valid configs are directly executable | AgentConfig + Runtime owner; resolve or formally adjudicate with regression before Phase 3 configuration mapping | Keep separate from P1 grading for failure of an authorized real historical valid sample. This item neither fabricates public-publish failure evidence nor permits the public-path tests to close the storage boundary |

The final number of open P0/P1 defects must be verified from actual results in `06-test-report.md` and `07-acceptance-report.md`; this checklist does not preclaim acceptance, P0/P1 counts, or Phase 1 authorization. T8 creates neither report and does not present focused prechecks, reviews, or self-comparison as the formal double run.

## 5. Phase 1 Entry Checklist

- [ ] AC-1–AC-6 have evidence against the current artifact commit; every pending_env has an environment and owner.
- [ ] Clean-CI double-run node outcomes match; every skip/xfail/flaky result has a disposition; unmeasured coverage/duration is not recorded as zero.
- [ ] Real historical samples have been added or their representativeness boundary has a formal Agent-config/security/product decision.
- [ ] Zero unresolved P0/P1 items; every P2/P3 has an owner, deadline, and impact boundary.
- [ ] Frozen identifiers and common gates from this checklist are present in the Phase 1 test design.
- [ ] Architecture, product, QA, engineering, and security sign individually; local development completion is not sign-off.
