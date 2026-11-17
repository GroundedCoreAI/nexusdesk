# Phase 6 · Security, Reliability, and Event Governance — Implementation Breakdown

> Status: Approved implementation baseline for development/testing; no task is implemented by this document and no acceptance result is implied.
> Created: 2026-11-16
> Basis: `01`–`05`, architecture Sections 7–10/12/17–22, and first-hand inspection of backend code/tests at branch `feat/agent-execution-platform-v2-phase6`, baseline `7772a32324f2eb6bb2c5de141baed4350aa53715`.
> Constraints: Direct-continue authorization applies to the approved scope. Preserve the modular monolith, Run=one attempt, existing queue/Host/Workspace/event contracts, and all security/data/real-environment hard gates. Maximum five coordinated rework rounds; further unresolved hard-gate disagreement stays blocked, while only genuinely non-core P2/P3 work may be negotiated for follow-up.

## 1. Selected Delivery Shape and Dependency Order

Use the **additive three-slice approach** selected in `03-technical-design.en.md` §2:

1. Reliability/event foundation (T-01–T-06).
2. Execution credential and strong-isolation foundation (T-07–T-08).
3. Integrated recovery, rollout, and evidence (T-09–T-12).

The alternatives were a parallel replacement stack (rejected: duplicate sources of truth) and one horizontal big-bang implementation (rejected: late vertical verification and high rollback risk). T-07 may proceed in parallel with T-04–T-06 after T-03, but 0071 always remains after 0070 in the migration graph. No task enables untrusted execution.

| # | Task and concrete completion boundary | Files (new/modified) | Depends | Quick-check scope | Traceability |
|---|---|---|---|---|---|
| T-01 | Freeze internal ownership/event/credential DTOs and bounded settings defaults. Tokens stay server-internal; defaults cannot enable exposure or delete history. | `core_platform/agent_execution/reliability/ownership.py` (new), `events/envelope.py` (new), `credentials/models.py` (new), `platform_settings/settings.py`, settings tests | — | New DTO/settings unit cases; `test_agent_execution_phase4_settings.py`; ruff | FR-1, FR-7, FR-11, FR-16; AC-16; R-3/R-10/R-11 |
| T-02 | Add 0070 expansion, deterministic event backfill, Outbox trigger/watermark/reconciliation, usage ledger, and data-preserving downgrade policy. Revalidate actual head first. | `backend/migrations/versions/0070_execution_fencing_event_outbox.py` (new), `backend/tests/test_execution_migration.py` (new), migration fixtures | T-01 | Fresh and populated PG upgrade; repeat backfill; old-shaped publishable insert gets ID+Outbox and internal replay gets no public Outbox; lock/duration evidence; head graph check | FR-7–FR-14, FR-16; AC-16; R-1/R-4/R-10 |
| T-03 | Implement monotonic claim/takeover epoch and enforce ownership on snapshots, append/finish, heartbeat, usage, tool replay, process, Workdir, and resource release. Add separate denial audit. | `agent_runtime/{repository,worker}.py`, `orchestration/{execution_context,orchestrator}.py`, `tool_gateway/replay.py`, `host/process_registry.py`, `workspace/{workspace_provider,workspace_manager}.py`, `reliability/ownership.py`, `backend/tests/test_execution_fencing.py` (new) | T-02 | New two-Worker/stale-write matrix plus only affected existing claim/cancel/replay/Host/Workdir cases | FR-7–FR-9; AC-7–AC-9; R-2/R-12/R-13/R-14 |
| T-04 | Preserve AgentEvent through Orchestrator/Worker; deduplicate without consuming durable seq; dispatch Outbox through acknowledged enqueue into the existing DurableEventBus. | `events/{envelope,outbox}.py`, `platform_services/events.py`, `agent_runtime/repository.py`, `orchestration/orchestrator.py`, `agent_runtime/worker.py`, `backend/tests/test_execution_{events,outbox}.py` (new) | T-03 | Concurrent dedup, adapter-local vs Run seq, pre/post commit and publish crash, direct-writer publication, internal replay exclusion, bus idempotency | FR-11, FR-12; AC-11, AC-12; R-3/R-4 |
| T-05 | Add SSE reserved envelope metadata and retention-floor 400/409 handling without changing existing fields, `id=seq`, transient delta, or terminal semantics. Cleanup stays off unless explicitly enabled. | `events/replay.py`, `agent_runtime/repository.py`, `applications/customer_service/runtime_routes.py`, `backend/tests/test_execution_sse.py` (new) | T-04 | >200-event reconnect, lost NOTIFY, invalid/expired cursor, terminal catch-up, existing HTTP/SSE cases | FR-13; AC-13; R-10/R-15 |
| T-06 | Persist terminal/native usage idempotently with correction chains and rebuildable aggregates; add bounded classified parser diagnostics without replacing existing Codex error behavior. | `events/{usage,diagnostics}.py`, `orchestration/execution_lifecycle.py`, `agent_runtime/{repository,worker}.py`, `adapters/{react,codex}/*`, `backend/tests/test_execution_{usage,diagnostics}.py` (new) | T-04 | Duplicate/old-epoch/correction/missing usage; malformed/unknown/oversized/rate-limit/canary cases; existing Codex mapper cases | FR-14, FR-15; AC-14, AC-15; R-8 |
| T-07 | Add 0071, Execution Vault/Broker, admin metadata/rotate/revoke API, grant binding/TTL, audit, common redaction, and disclosure response. No Secret-read API or auto-created missing runtime key. | `backend/migrations/versions/0071_execution_credential.py` (new), `credentials/{models,vault,broker,repository}.py`, `security/redaction.py`, `applications/customer_service/{execution_credential_routes.py,application.py}`, `backend/tests/test_execution_{credentials,redaction,migration}.py` | T-03 | Ciphertext/AAD/binding/revocation/expiry/cross-Run cases; route tenant/role checks; Secret scans; PG migration | FR-1–FR-3; AC-1–AC-3; R-11 |
| T-08 | Extend the existing sandbox launch port and implement the real Docker strong provider, default-deny network/managed allowlist proxy, cgroup limits, minimal mounts, and authorized artifact path. Local stays non-strong. | `host/{sandbox_provider,docker_sandbox_provider,network_policy,egress_proxy,process_runner,runtime_host,resource_manager}.py` (new/modified), `workspace/execution_workdir.py`, `backend/tests/test_execution_sandbox.py` (new) | T-07 | Pure policy/support tests everywhere; real Linux Docker escape, egress, mount, fork/memory/disk, residue tests in the dedicated environment | FR-4–FR-6; AC-4–AC-6; R-7 |
| T-09 | Integrate Worker loss, confirmed cancellation/timeout, reentrant cleanup, side-effect-aware retry, grant/network/Workdir cleanup, and independent Run/Host quota release. | `reliability/{recovery,retry}.py`, `agent_runtime/{repository,worker}.py`, `orchestration/orchestrator.py`, `host/{runtime_host,process_supervisor,process_registry}.py`, `workspace/workspace_manager.py`, `backend/tests/test_execution_recovery.py` (new) | T-06, T-08 | SIGKILL/heartbeat/late result; normal/hang/failed cleanup; pre-launch vs ambiguous retry; terminal/final-event/quota reconciliation | FR-8–FR-10; AC-8–AC-10; R-2/R-13 |
| T-10 | Complete composition/deployment wiring, startup recovery before admission, Outbox/retention loops, secure shutdown, metrics/alerts, and Secret-free examples. Preserve production React selector and Stage B lock. | `applications/platform_runtime/runtime_composition.py`, `backend/.env.example`, `deploy/production/.env.example`, `deploy/{quickstart,production}/compose.yaml`, settings/composition tests | T-09 | Off-state construction diff, startup/shutdown order, env override/default tests, Secret scan, architecture gate | FR-16; AC-16; R-5/R-6/R-12 |
| T-11 | Close all code-only P6 UT/IT/CM coverage and run only affected existing regressions; CI owns one final full backend/frontend lane. Record skips and pending environments honestly. | All affected `backend/tests/*`, `scripts/check_architecture.py` usage, `.github/workflows/ci.yml` only if a deterministic new lane requires registration | T-10 | ruff + architecture; focused non-PG and disposable Docker PG; final PR CI; no wholesale local reruns after every task | 04 all applicable code cases; AC-1–AC-16 code halves |
| T-12 | Execute real adversarial/fault/migration/rollback drills, produce 06, perform A/C acceptance and produce 07. Keep untrusted off without independent approvals and upstream evidence. | Phase 6 `06-test-report.md` (new after execution), `07-acceptance-report.md` (new after acceptance), linked external evidence | T-11 | Every 04/05 row has an individual verdict/evidence link; pending_env/not_measured never becomes pass | 04/05 all; G1–G7; R-5/R-9 |

`core_platform/...` in the table is under `backend/src/agent_platform/`. Development must update 03 and this file with any newly discovered path, migration, public-contract, or gate conflict before changing production code.

## 2. Reality Discrepancies and Rulings

### R-1 — Planned migration numbers are invalid

**Documents:** 01/03/04/05 reserve 0056/0057 and the old audit names head 0052.

**Reality:** `0067_merge_heads.py:22–23` is the single head and joins `0066_hosted_web` plus `0059_execution_runtime_host`; 0056/0057 are occupied.

**Ruling:** use revision identifier `0070_execution_fencing` (filename `0070_execution_fencing_event_outbox.py`; `down_revision="0067_merge_heads"`) and `0071_execution_credential` (`down_revision="0070_execution_fencing"`). Revision identifiers must fit `alembic_version.version_num VARCHAR(32)` (R-16). T-02 dynamically rechecks. Any change requires another R-n and synchronized 01/03/04/05/08 edits before implementation.

### R-2 — Host, supervision, resources, and Workspace already exist

**Documents:** old 03 uses planning-only `host/{runtime_host,process_supervisor,resource_manager}` and `sandbox/` paths as if still absent.

**Reality:** Phase 4 implementations exist. `host/sandbox_provider.py:315–337` defines the provider port; `local_sandbox_provider.py:89–255` implements managed local processes; Workspace has durable path/cleanup protections.

**Ruling:** extend existing Host/Workspace modules and tests. New reliability code coordinates ownership but does not replace process supervision, Workdir persistence, or Repository SQL authority.

### R-3 — Common AgentEvent exists, but its identity is dropped and sequence domains differ

**Documents:** old audit says the common envelope is missing and could imply writing AgentEvent.sequence to durable storage.

**Reality:** `contracts/events.py:12–23` already defines the v1 envelope. `orchestration/orchestrator.py:337–341` emits only type/payload. Adapter mappers start sequence at 1 while `runtime_runs.event_seq` already includes queued/started events.

**Ruling:** carry the envelope to the Repository, preserve `runtime_events.seq` as the sole durable Run sequence, and treat adapter sequence only as producer metadata. Deduplicate by event_id and optional stable producer key. The two producer fields are additive optional v1 metadata; existing producers remain valid.

### R-4 — Repository-only Outbox would miss a production writer

**Documents:** old design assigns event/Outbox writes mainly to `RunRepository`.

**Reality:** `tool_gateway/replay.py:80–119` increments event_seq and inserts directly; seed modules also insert directly. `platform_services/events.py:117–327` already provides a durable at-least-once bus over `memory_tasks`.

**Ruling:** 0070 adds DB event identity defaults and an AFTER-INSERT Outbox trigger for publishable types plus rollout-watermark reconciliation. Internal `tool.replay` is identity-bearing and fenced but never published to extension subscribers. T-03 fences tool replay. T-04 adds an acknowledged enqueue port to the existing bus; no second Event Store or external broker.

### R-5 — Upstream acceptance prerequisites are not met (genuine requirement conflict)

**Documents:** 01/05 say Phases 0–5 are accepted before Phase 6; the user authorized direct continuation.

**Reality:** Phase 5 `07-acceptance-report.md:135–159` grants only scoped R18 conditional code readiness, explicitly says Stage A full acceptance has not passed and Stage B is locked, and lists Phase 0 diff, real credential/tenant, stability, and environment evidence as open.

**Ruling:** direct-continue authorizes implementation, not a fabricated prerequisite pass. Develop T-01–T-11 with untrusted execution off. Final A16/C11 and overall Phase 6 acceptance remain blocked until the applicable upstream evidence is supplied or the acceptance owner records a truthful narrower verdict. No hard gate is deleted.

### R-6 — Production Codex routing is intentionally unreachable

**Documents:** AC-16 requires React/Codex regressions but does not authorize a routing redesign.

**Reality:** `execution_context.py:42` fixes production selection to React; `runtime_composition.py:901–919` constructs an empty trusted-target registry; Phase 5 also records capability/workspace denial.

**Ruling:** do not change production selector, trusted-target registration, publish-path projection, or Stage A/B gate in Phase 6. Use injected controlled Codex/Host seams for code tests. Production Codex enablement remains an upstream/deployment follow-up and cannot be claimed by regression evidence.

### R-7 — Local Sandbox cannot become strong by configuration

**Documents:** FR-4–FR-6 require actual strong isolation.

**Reality:** `local_sandbox_provider.py:247–255` rejects untrusted shapes; its contract has prepare/preexec/release but no container launch/network namespace control. Settings permit only `local` (`settings.py:142–148`).

**Ruling:** retain Local for controlled development and add an explicit provider-generated launch-plan seam plus a real Docker provider. Merely renaming Local, adding path checks, or mocking `--network=none` is not acceptance. Missing Linux/Docker enforcement leaves A4–A6 pending_env and exposure off.

### R-8 — Execution usage and gateway accounting are separate

**Documents:** old audit says usage is absent without distinguishing existing model-gateway cost accounting.

**Reality:** `ExecutionOutcome.usage` exists (`execution_lifecycle.py:14–84`) but Worker finish drops it; `model_gateway/governance.py:440–451` separately records `gateway_costs` by attempt.

**Ruling:** persist Execution usage in the new source-unique ledger with stable terminal/native identities. Do not migrate, duplicate, or implicitly sum gateway costs. Unknown remains unknown; corrections use new source records and supersedes links.

### R-9 — Engine Session/Resume does not exist

**Documents:** FR-2/FR-7 and AC-2/AC-7 include Resume and Session writes.

**Reality:** Phase 5 App-Server has codec/state primitives only; no `agent_engine_sessions` model or migration exists.

**Ruling:** implement generic Broker reauthorization and fencing ports and test them with controlled fakes. Do not add Stage B Session persistence in Phase 6. Real Session/Resume substeps remain `pending_upstream` and prevent a full corresponding AC/upstream release claim until Phase 5B supplies the capability; this is not silently marked not-applicable.

### R-10 — Retention needs a durable gap floor and a safe default

**Documents:** FR-13 requires explicit expired-cursor behavior, but the old schema has no floor and leaves retention timing open.

**Reality:** `runtime_routes.py:83–154` has replay but no cleanup/floor. Existing deployments retain events indefinitely.

**Ruling:** add `runtime_runs.event_retention_floor_seq`, advance it atomically with eligible deletion, and default `execution_event_cleanup_enabled=false` with a 30-day policy for later reviewed enablement. Cursor below the floor returns 409; no silent earliest-available reset.

### R-11 — Model CredentialVault cannot be reused as Execution authorization

**Documents:** FR-1 says missing keys never recreate automatically and requires Execution binding.

**Reality:** `platform_services/secrets/vault.py:13–60` binds tenant/connection/address/protocol and supports `create=True` key provisioning; it has no Execution grants.

**Ruling:** reuse Fernet lessons only. New Execution AAD includes credential ID/tenant/version and grants bind Run/engine/protocol/workspace/scope/expiry. Runtime key access never auto-creates a missing key. Existing model/tool credential behavior remains unchanged.

### R-12 — Current composition/settings paths are confirmed, but Writer rollout needs explicit draining

**Documents:** old 03 has the right composition path but assumes gradual old/new Writer coexistence without defining epoch cutover.

**Reality:** settings/composition paths match the audit; old Writers do not supply epochs and direct resource operations do not check Run ownership.

**Ruling:** expand compatibly, then stop admission and drain old Writers before enforcing epochs. Rollback also drains new Writers first. Mixed enforcement is unsupported; schema defaults alone are not fencing evidence.

### R-13 — Existing reaper is not a complete recovery owner

**Documents:** FR-8/FR-9 require fencing before recovery and confirmed cleanup.

**Reality:** `repository.py:586–610` terminally fails/cancels expired rows; Host recovery independently reconciles process records. The two are not coordinated by an epoch or one terminal/Outbox transaction.

**Ruling:** T-03 introduces ownership/takeover primitives; T-09 coordinates Host/Workdir/grant cleanup before terminal completion. Unconfirmed cancellation stays failed/cleanup_failed/pending cleanup, never false-cancelled.

### R-14 — Fencing audit cannot commit in the rolled-back business transaction

**Documents:** FR-7 requires both zero partial writes and denial audit.

**Reality:** a stale conditional write must roll back its business transaction; an audit inserted in that same transaction would disappear.

**Ruling:** make the business decision solely by conditional SQL rowcount/constraint. After rollback, write bounded denial audit/metrics in a separate transaction with trusted scope and no payload. Audit failure does not turn a denied write into an allowed one.

### R-15 — Zero Phase 0 regression diff must distinguish additive event metadata

**Documents:** AC-16/C11 originally require zero diff, while FR-13 requires event_id/schema_version in SSE payload.

**Reality:** `runtime_routes.py:120–121` currently serializes only the stored business `data`; moving it under a new envelope would break clients, but adding event identity necessarily changes the serialized object.

**Ruling:** preserve every existing key and add only reserved `_execution.{event_id,schema_version,source,trace_id}` metadata. Phase 0 compatibility means zero behavioral/regression diff apart from this explicitly reviewed additive key; it does not permit other wire changes, dropped fields, reordered durable history, or altered transient-delta semantics.


### R-16 — Alembic revision identifiers must fit ``VARCHAR(32)``

**Documents:** R-1 and 01/03 use the full migration names as revision identifiers.

**Reality:** ``alembic_version.version_num`` is ``VARCHAR(32)``. ``0070_execution_fencing_event_outbox`` is 36 characters and the planned ``0071_execution_credential`` is 33, so both would truncate/fail on upgrade.

**Ruling:** keep the descriptive filenames, but use revision identifiers ``0070_execution_fencing`` and ``0071_execution_credential`` (both <= 32). ``down_revision`` for 0071 is ``0070_execution_fencing``. Filenames remain as listed in the task table; only the identifier string changes.


### R-17 — Managed allowlist egress proxy is an external deployment dependency

**Documents:** T-08 and FR-5 require a managed allowlist egress proxy.

**Reality:** the Docker provider can generate the per-Execution network/mount/resource plan and fail closed when no proxy endpoint is configured, but this code-only pass does not ship a proxy service image or daemon-side proxy container. Default-deny (`--network=none`) is enforced and drilled locally; allowlist, DNS-rebinding, metadata, and proxy-bypass drills need the dedicated environment's managed proxy.

**Ruling:** the provider refuses an allowlist without `execution_sandbox_docker_proxy_endpoint` (fail closed, no direct egress). The endpoint is a deployment Secret-free URL. Real allowlist/proxy drills remain `pending_env` and A5 cannot pass until that managed proxy is supplied and drilled.

### R-18 — Deferred launch, redaction, native-usage, and allowlist wiring is not test-only work

**Documents:** T-06 requires terminal **and native** usage persistence; T-07 requires Broker/redaction/disclosure response; T-08 requires a managed allowlist proxy; T-10 requires composition wiring. T-12 owns real drills and reports, not missing production behavior.

**Reality at `671b637`:** production code contains no Broker issue/consume call at Codex/Host launch and no Secret channel. `SecretRedactor` has no production call site; Outbox forwards stored data directly and no disclosure response is wired. `RunRepository.record_usage` has no adapter/Orchestrator caller, so only terminal usage is persisted. R-17 correctly records fail-closed default-deny evidence, but the managed allowlist integration itself is also absent.

**Ruling (coordination round 1):** items (a)–(c) are immediate development fixes required before another code-ready handoff, not T-12 test debt:
1. Wire Broker issuance/consumption before spawn, bind the current Run/engine/protocol/workspace/scopes, materialize Secrets only into the controlled launch channel, revoke/clean them on every terminal path, and prove denial leaves zero spawn plus no Secret in logs/events/DB.
2. Apply common redaction at log, event, SSE, Outbox, error/diagnostic, and artifact trust boundaries; implement disclosure-driven credential revocation and admission closure with canary assertions.
3. Route native usage through the Adapter/Orchestrator boundary into the ownership-checked source-unique ledger, using stable producer identity and preserving duplicate/old-epoch/correction/unknown semantics. Terminal-only persistence does not complete FR-14.

For item (d), R-17's default-deny pass and `pending_env` verdict remain valid, and real allowlist/DNS/metadata/proxy-bypass drills belong to T-12. However, R-17 must not reclassify the approved managed-proxy integration as wholly external/test work: development must supply or integrate the managed endpoint and prove its actual enforcement contract before calling T-08 code-complete. No proxy means allowlist remains unavailable/fail-closed and A5 cannot pass. Real multi-Worker/fault drills likewise remain T-12 testing work. This ruling changes no FR/AC and waives no hard gate; untrusted execution remains off.


### R-19 — Actual network boundary, live-reaper confirmation, and fence-before-cleanup

**Documents:** testing preflight (coordination round 1) verified three production blockers under FR-5/FR-8/FR-9.

**Reality at `7c2373c`:** (1) the Docker allowlist used unrestricted `--network=bridge` plus advisory proxy env vars, which is not an enforced network boundary; (2) the live Worker still calls `repository.reap()`, which terminal-cancels/fails expired runs without confirmed cleanup; (3) `RecoveryCoordinator` performed cleanup before `apply_recovery` incremented the epoch, so cleanup ran under stale ownership.

**Ruling (same coordination round 1, not a new round):** (1) the managed allowlist must enforce an actual network boundary (internal container network plus a managed egress proxy, with explicit denial when the proxy is unavailable); default-deny stays `--network=none`. (2) the live Worker reaper path must use the confirmed RecoveryCoordinator so unconfirmed cancellation never reports cancelled. (3) recovery must fence/take over the expired claim (new epoch) first, then perform cleanup under the new ownership. These are production fixes, not test debt; no FR/AC or hard gate changes.

### R-20 — Integration branch advanced with colliding 0068/0069 migrations

**Documents:** 08 R-1/R-16 fixed the Phase 6 revisions at `0070_execution_fencing` / `0071_execution_credential` after the planning numbers collided with a different branch.

**Reality (PR #142 CI):** `integration` merged its own `0068_open_application_archive` and `0069_open_app_unique_name`, both chained from `0067_merge_heads`. The PR merge result therefore had two heads and `alembic upgrade head` failed with "Multiple head revisions are present", before any test ran.

**Ruling:** merge the latest `integration` into the Phase 6 branch and renumber the Phase 6 revisions to `0070_execution_fencing` (file `0070_execution_fencing_event_outbox.py`, `down_revision="0069_open_app_unique_name"`) and `0071_execution_credential` (file `0071_execution_credential.py`, `down_revision="0070_execution_fencing"`). The open-platform 0068/0069 are now historical and must not be modified. Revision identifiers stay within `VARCHAR(32)`. Tests and 01/03/04/05/06/07 are synchronized; no FR/AC, security gate, or acceptance verdict changes.


## 3. Focused Regression Reuse (Do Not Rerun Wholesale Unchanged)

| Existing evidence/cases | Reuse or rerun rule |
|---|---|
| `test_runtime_postgres.py::test_concurrent_submit_and_exclusive_claim`, `::test_capacity_and_tenant_isolation` | Reuse before T-03; rerun after claim/admission changes (T-03/T-09). |
| `::test_cancellation_wins_finish_race_and_event_replay`, `::test_lost_worker_is_failed_and_cannot_publish_late_result`, `::test_queue_expiration_and_cancel_without_worker` | Rerun after T-03 and T-09; add new epoch/cleanup assertions separately rather than weakening old expectations. |
| `::test_http_api_authorization_conflicts_cancel_and_sse`, `::test_end_to_end_demo_uses_real_http_and_persistent_events` | Rerun after T-05/T-09; assert legacy fields plus additive `_execution`, not byte-for-byte SSE equality. |
| Phase 4 `test_agent_execution_phase4_supervisor.py` real TERM/KILL/wall/crash cases | Reuse for untouched Host behavior; rerun only after T-08/T-09 changes to those paths. |
| Phase 4 `test_agent_execution_phase4_sandbox.py` Local gate/support/release cases | Rerun after T-08 to prove Local still rejects untrusted execution; Linux hard-cgroup pending cases remain attributed, not converted to passes. |
| Phase 4 `test_agent_execution_phase4_workdir.py` path/link/race/tenant/cleanup cases | Rerun the affected path and persistence cases after T-03/T-08/T-09; unchanged pure policy cases are reused. |
| Phase 4 migration/settings/composition/orchestration suites | Rerun only the files corresponding to T-02/T-03/T-09/T-10 changes. |
| Codex `test_codex_events.py`, `test_codex_adapter_unit.py`, `test_host_stdin_delivery.py` | Rerun after T-06/T-07/T-08 only where mapper, Secret, launch, or diagnostics behavior changed; preserve R18 stdin semantics. |
| Codex `test_codex_host_integration.py` and Phase 4 PG Host cases | Run in disposable Docker PostgreSQL after T-03/T-07/T-08/T-09; real Codex remains separately attributed/pending in CI without a binary. |
| `test_gateway_credentials.py`, `test_tool_credentials.py`, `test_tool_egress.py`, `test_tool_workspace.py` | Rerun after credential/network/Workspace changes; existing model/tool credential semantics must not be relaxed. |
| Full backend/frontend suites | CI runs the final PR merge result. Do not repeat the full local suite for documentation or every task; any failure reruns only its affected scope after a fix. |

## 4. Coordination Questions and Gate Ownership

1. **Coordinator / acceptance:** provide the Phase 0 baseline diff and resolve the Phase 5 full-acceptance prerequisites, or keep the final Phase 6 verdict blocked/narrow. Direct-continue is not evidence. Development need not wait for this to start T-01.
2. **Development / testing / acceptance:** identify a disposable Linux environment with a Docker daemon permitted to create unprivileged sibling containers, cgroups, disposable networks/volumes, DNS/metadata decoys, and two Workers. Without it, T-08 code may land fail-closed but A4–A6 and overall phase acceptance stay `pending_env`.
3. **Coordinator / security operations:** name the independent security and SRE/operations approvers before any request to set `execution_untrusted_tenants_enabled=true`. The four implementation subagents cannot self-issue those approvals.
4. **Development / testing:** Stage B Session/Resume and production Codex routing remain outside Phase 6. Use controlled test adapters; report real Session/Resume and production release gaps under R-5/R-6/R-9 instead of expanding scope.
5. **Testing / acceptance:** reuse the existing passed evidence according to §3. Rerun affected cases after changes, and reserve full-suite evidence for final CI. Non-code/descriptive P2/P3 gaps may be conditionally accepted only by the acceptance owner; hard-gate or main-flow gaps cannot.

Reports must follow the required `06-test-report.md` and `07-acceptance-report.md` templates. No report file is created before its actual execution phase.
