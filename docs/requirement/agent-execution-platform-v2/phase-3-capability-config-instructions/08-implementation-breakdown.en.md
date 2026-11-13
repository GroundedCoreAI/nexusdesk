# Phase 3 · Capabilities, Configuration, and Instructions — Implementation Breakdown

> Status: T1, T2, T3 and T4 complete; the T5 backend lane is in progress and the T9 frontend lane runs in parallel (depending only on frozen contracts; end-to-end preview evidence still awaits T8/T13); T6–T8 not started, T10–T13 not started; phase testing/acceptance not yet performed
> Created: 2026-11-12
> Revised: 2026-11-13 (T5 rework freeze points: §5 post-serialization revalidation, semantic-level replay, dual identity gates, the controlled outcome vocabulary; new barrier-result mapping discipline in T7; R-9 annotated)
> Revised: 2026-11-13 (T9 frontend-lane conflict rulings R-23–R-25: single-triple Engine read-only presentation, §3.2.5 minimal-write clarification, execution-config-flags read-only contract landing in T8/T9)
> Revised: 2026-11-13 (Section 1 rule 2 rewritten as the four-role subagent process: design / development (parallel backend and frontend lanes) / test / acceptance, with the coordinator in between)
> Revised: 2026-11-13 (T4 rework rulings R-17–R-22: trusted policy-revision entry point, capability settings home and TTL floor, single Effective projection, non-bypassable Available narrowing)
> Revised: 2026-11-13 (T4 specification review clarified the required-capability-missing boundary; added R-16, synchronized with 03 §4.1, 04 P3-UT-23, 05 A4)
> Basis: `01-business-goals.md`, `02-requirements.md`, `03-technical-design.md`, `04-test-plan.md`, `05-acceptance-plan.md`
> Baseline: `3969258`; focused baseline 163 passed / 5 skipped; baseline migration head `0057_industry_pack_runtime`, with `0058_agent_execution_metadata` added by T2
> Working constraints: RED before GREEN; never prewrite outcomes; create 06/07 only after actual testing/acceptance; seed after 06/07, quickstart after seed

## 1. Implementation Rules

1. Write a test that fails for the missing target behavior before implementing it. Confirm RED fails for the right reason; collection/environment errors do not count.
2. Every task proceeds through four independent subagent roles: **design** (only when an open design question exists or 02/03/04/05 must be revised; it produces rulings and writes them into the formal documents), **development** (split into a backend lane and a frontend lane that may run in parallel; the two lanes must have disjoint file scopes, and cross-lane contracts follow this breakdown plus the already-frozen 02/03 clauses — on a contract conflict, stop and hand it to the coordinator instead of editing the other side), **test** (one role; independent evidence gathering, no code changes, no verdicts), and **acceptance** (one role; passes / conditionally passes / fails against FR/AC, the test plan, and the 05 criteria). The checkpoint requirement is unchanged: both specification and quality conclusions must exist, and **findings are fixed before moving to the next task**. A small team may perform these as separate checks without inventing organizational roles. The coordinator relays conclusions between roles, settles conflicts, and handles environment failures (quota, classifier, containers, credentials); subagents never communicate with each other directly.
3. Run backend commands from repository root with `uv run --directory backend ...`; the architecture command is exactly `uv run --directory backend python ../scripts/check_architecture.py`.
4. Run `ruff check src tests` broadly; list only Phase 3 added/modified Python files for `ruff format --check`. Do not modify unrelated pre-existing Memory seed format differences or claim full-tree success; 06 records the boundary.
5. PostgreSQL integration defaults to an independent pgvector container. Reuse coordination environment `nexusdesk-phase3-pg` if available, but every executor revalidates container, head, and SHA. Secrets remain only in mode-600 `/tmp/nexusdesk-phase3-pg.env`, never in repository/reports.
6. Alembic reads `AGENT_DATABASE_URL`, while pytest reads `TEST_DATABASE_URL`. Prefix PG commands with:

   ```bash
   set -a; . /tmp/nexusdesk-phase3-pg.env; set +a
   export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
   export AGENT_API_TOKEN="${AGENT_API_TOKEN:?set a temporary test token}"
   ```

7. CI runs full pytest on push/PR; locally run the complete affected suite. Add no frontend component-test framework; use typecheck, `check:i18n`, build, and targeted Playwright.
8. Every documentation addition/change updates both `.md` and `.en.md`; production plans never backfill history, edit applied migrations, or pull in Phase 4/5/6 scope.

## 2. Conflict Log and Design Decisions

| ID | Conflict/code reality | Frozen decision |
|---|---|---|
| R-1 | Phase 0/1 formal acceptance incomplete and Phase 2 conditionally passed; old documents said upstream accepted | Separate development entry from final launch gates; merged code does not replace CI, real samples, production performance, or human evidence |
| R-2 | Phase 2 merged with 06/07 and seed/quickstart appendices | Extend existing Registry/Orchestrator/ReactAdapter; never say undeveloped or build a parallel chain |
| R-3 | `0053_routing_decisions` exists and head is `0057_industry_pack_runtime` | Plan `0058_agent_execution_metadata→0057`; T2 dynamically revalidates and synchronizes all bilingual documents if changed |
| R-4 | Registry has identity/factory only; draft `resolve` would instantiate an Adapter | Add exact metadata/schema lookup; zero factory calls for drafts/publication/preview; only execution resolves a fresh Adapter |
| R-5 | Legacy root model fields coexist with new `react`; defaults may write DB/pollute diffs | One normalizer; equal aliases accepted, unequal rejected; reads cause no UPDATE and canonical diff suppresses only default-equivalent noise |
| R-6 | Hot-path probes block, while cache-only reads can remain cold forever | Composition creates entries and a controlled background warmer populates/refreshes; cold/stale/error=false, no hot-path remote probe; test full lifecycle |
| R-7 | Client, UI, or Adapter declarations could be mistaken for authorization | Monotonically narrow Declared→Available→Policy→Effective with least privilege; missing Workspace unavailable and disabled only narrows |
| R-8 | Five snapshots versus public `run.started` ordering is ambiguous | Preserve claim's public event; commit five DTOs once before Adapter.start/runner/Runtime side effects, with start=0 on failure |
| R-9 | Concurrent retries could overwrite snapshots, but no sixth column is allowed | Reuse `ExecutionContext.execution_id` as DTO startup identity; conditional NULL writes, same-identity verification/reuse (judged by `jsonb` semantic equality), divergent decisions fail. **The identity invariant is enforced by both the entry guard and the SQL predicate**: each of the five payload bodies must also carry `execution_id` equal to this row's run id, otherwise `audit_conflict` is returned without touching the database |
| R-10 | ReactAdapter.start creates the runner and RuntimeFactory currently assembles inside it | Move Provider preparation/snapshot commit before start; compute system prompt and Summary/Memory once each; React message order remains exact |
| R-11 | Two flags create four states, with Runtime cache affecting transitions | Off/off and off/on retain original Phase 2; on/off fails closed; on/on uses Phase 3; off non-React rejects; Phase 3 flag stays out of fingerprint and Worker fixes each claimed Run's path |
| R-12 | Preview could leak internal capabilities/policy or reuse stale authorization | Strict `POST /api/v1/agents/execution-preview` with allowlisted Effective, scoped access, no Run/Adapter, and no future authorization |
| R-13 | Current global RequestValidationError handler only returns 422 without security audit | T8 wires trusted authenticated context/existing audit service without body/values/secrets; P3-IT-04 directly queries audit |
| R-14 | No component-test runner; helper-only performance or missing raw samples could fake a pass | Use existing Playwright/four locales; C11 uses real resolver/admission, warmed caches, at least 100 valid interleaved pairs, and raw p95 evidence |
| R-15 | User requires examples in the next quickstart after completion, without prewritten success | T10/T11 create real 06/07 first; T12 adds independent low-sensitivity idempotent seed; T13 wires fresh quickstart and only appends to existing 06/07 |
| R-16 | T4 once read "missing required capabilities block start" as every declared=true yet ineffective capability, conflating AC-3 infrastructure failures with the normal FR-4/AC-4 policy narrowing (e.g. agent_disabled in the 03 §7.2 preview example), which would turn a supported disable configuration into a startup block after T7 wiring | Start blocking is limited to probe_unavailable/probe_timeout/probe_stale/workspace_unavailable/policy_unavailable; not_declared and platform_denied/tenant_denied/agent_disabled/execution_denied only narrow and never block start (see 03 §4.1); 02 text and numbering stay unchanged—this ruling plus 03 §4.1 are normative; T7 admission, P3-UT-06～10/23, and A3/A4 follow it |
| R-17 | The resolver had no entry point to ask the trusted source for the current revision: a fixed value from T7 would reduce the 03 §4.3 revision invalidation to TTL, while a provider echoing its real revision against a caller value trips identity validation into `policy_unavailable` and blocks legitimate startup | `policy_revision` becomes a trusted observation: `TrustedPolicyProvider` gains the synchronous, local, no-I/O `current_revision(PolicyRevisionScope)->int` (peer to `WorkspaceAvailabilityPort.current`), the resolver reads it when building keys and the PolicyContext and requires `resolve()` to echo that same value, and `CapabilityResolutionRequest` drops `policy_revision`. A divergent echo records a cache error, hot-reads `policy_unavailable` (required-missing per R-16) and self-heals next bounded round; a raising read raises `PolicySourceUnavailableError` mapped to the stable `execution_policy_unavailable` and never defaults to 0. `execution_restriction_digest` stays a caller field but is computed server-side by composition with `execution_restriction_digest(values)` (same canonical form as `disabled_capabilities_digest`); Phase 3 always passes the empty-set constant `NO_EXECUTION_RESTRICTIONS`, and providers never echo it |
| R-18 | resolver/cache/warmer construction needs a policy timeout, probe concurrency cap, capacity and retry interval (plus warmer refresh cadence and deployment identity) with no FR-9 home, forcing hardcoded T7 defaults and an undefined C11 basis | Add six non-secret settings: `execution_capability_policy_timeout_seconds=2.0 (gt=0, le=10)`, `execution_capability_probe_max_concurrency=4 (ge=1, le=32)`, `execution_capability_cache_capacity=512 (ge=16, le=100000)` shared by both caches, `execution_capability_cache_retry_seconds=5.0 (gt=0, le=60)` shared by cache retry and warmer backoff, `execution_capability_warm_refresh_seconds=10.0 (gt=0, le=300)`, `execution_capability_deployment_identity="default"` (Slug pattern). All six go into `backend/.env.example`, none into `deploy/production/.env.example`; T7 may only read settings; with Phase 3 on, settings validate `warm_refresh < min(TTL)` |
| R-19 | The two `*_cache_seconds` settings allowed 0 while `CapabilityCache` requires `ttl_seconds > 0`, so TTL 0 became a construction-time crash | Standardize on forbidding 0: settings use `gt=0` (int, so the effective floor is one second). No "0 = never expires/no cache" branch—it would need an `expires_at is None` path plus warmer semantics and would contradict R-6's rule that stale values are never fresh authorization; `gt=0` is a one-place change that aligns configuration-time and construction-time validation and fails closed in settings. Phase 3 offers no capability-cache kill switch |
| R-20 | `execution_capability_policy_version` had no consumer because the resolver takes policy_version from the descriptor, so it would silently rot | The value is the deployment-declared policy contract version whose only consumer is composition: it seeds `AdapterDescriptor.policy_version` and the same registered provider, closing the loop descriptor→PolicyContext→PolicyCacheKey→provider echo; providers introduce no second version source, the type tightens to `AdapterVersion` (`^v[1-9][0-9]*$`), and the 02 FR-9 row stays unchanged |
| R-21 | `ExecutionRequest.effective_capabilities` is a bare `dict[str,bool]` while T4 produces structured `EffectiveCapabilities` and 03 §7.3 requires triples, with no single projection—T7/T8 would diverge or drop reason codes | Two pure functions live in and are exported from `contracts/capabilities.py`: `effective_capability_flags(effective)->dict[str,bool]` (always 11 keys, false never omitted, `CAPABILITY_ORDER`) and `effective_capability_views(effective)->tuple[EffectiveCapabilityDecision,...]` (the §7.2 triple, reusing the existing strict DTO with no new response model). T7/T8 call only these; the `ExecutionRequest` contract is unchanged and its dict is a degraded view (never an authorization), with reason codes and provenance living only in `EffectiveCapabilitiesSnapshot`; readers treat missing keys as False |
| R-22 | Available values are keyed by workspace_generation but not tenant/scope, and narrowing happens only on the read path, so a T5/T7 direct cache read could produce the contradictory evidence "available=true without a trusted Workspace" | The key design is unchanged; instead 03 §4.3/§5.3 state that the four capability snapshots and `ExecutionRequest` read available/effective only from `CapabilityResolution`, T5 snapshot constructors take a `CapabilityResolution` (not `AvailableCapabilities`/`CacheLookup`) as the type-level gate, P3-UT-25 is the negative control, and any bypass is a P1 defect. No `scripts/check_architecture.py` import rule for now because composition still constructs `CapabilityCache`; escalate only if a bypass appears |
| R-23 | 02 US-1/03 §8 phrase "Engine selection" as if a dropdown with a candidate source were required, yet the Phase 3 production Registry has exactly one legal triple `react/native/v1` and no Engine catalog endpoint is frozen | "Selection" in Phase 3 is implemented as a read-only presentation of the effective triple with a registered/unregistered status Tag (the frontend candidate set is a constant equal to the production legal set); no catalog endpoint and no free-form input are added, and this form is the compliant implementation of US-1/§8, pinned in 03 §8 and not revertible. Genuine multi-candidate selection belongs to Phase 4/5 (04 P3-CM-10) and must then read Registry metadata. FR-2 is not relaxed: unregistered or non-React triples remain precisely rejected, and the Tag is a presentation hint only |
| R-24 | 03 §3.2.5 could be read as "canonical must be written as soon as the user edits", making the frontend's minimal write (never fabricating engine/react, omitting empty disabled) look like a violation | Ruled: the minimal write is consistent with §3.2.5. That clause constrains semantic change at the canonical diff/audit layer (criterion: no default-triple noise in changes), not the key set of the client body; the server-side canonicalizing PUT (full normalized body plus `canonical_config_diff` noise suppression) is frozen T3 behavior and stays. Neither side may read it as "any edit fabricates engine/react" or "the server must persist legacy shapes verbatim"; §3.2.5 gains one clarifying sentence, 04/05 criteria already accommodate this reading unchanged, and no frontend rework is required |
| R-25 | 05 M3 demands "editing entries disabled/hidden in line with the flag", but the frontend had no way to read `execution_phase3_enabled`; error inference cannot express "hidden before any attempt" nor distinguish off from the on + orchestrator-off misconfiguration, while the frontend correctly keeps Phase 2 React editing usable under off + orchestrator-on | Add the minimal read-only `GET /api/v1/agents/execution-config-flags` (03 §7.4, precedent `memory-config-caps`): exactly the two booleans `execution_phase3_enabled/execution_orchestrator_enabled`, Reader permission on the same internal-management surface as preview; settings-only with zero side effects (no probe/Adapter/Run/cache read/audit), answers normally in both off and misconfiguration states, never returns domain errors; raw flags instead of a synthesized view, combined in the UI per the FR-9 matrix—off hides the preview/narrowing entries, misconfiguration shows a hint without fake success, and a failed flags read fails closed by hiding; React model/round editing and historical viewing are never flag-gated. Lands in T8 (implements) and T9 (consumes); new P3-UT-26/P3-IT-20, the 04 §6.1 scenario, and the 05 M3 criterion update |

## 3. Task Order

| Task | Content | Dependencies | Status |
|---|---|---|---|
| T1 | Calibrate bilingual 01–05/README and freeze 08 design | Baseline code review | **Complete (documents only)** |
| T2 | Migration `0058`, settings, and rollout skeleton | T1 | **Complete (specification/quality reviews passed)** |
| T3 | ExecutionConfig, Registry metadata, normalizer, canonical diff | T2 | **Complete (specification/quality reviews passed; post-fix independent re-review APPROVED)** |
| T4 | Four capability layers, trusted ports, cache/warmer, least privilege | T3 | **Complete (including the R-16–R-22 two-round rework; acceptance conditionally passed, close-out conditions ①②③ satisfied; M2/Minor-3 tracked as T7 items)** |
| T5 | Five snapshot DTOs, denylist/size, one-time Repository persistence | T2, T4 | In progress |
| T6 | InstructionInput, React/test Providers, RuntimeFactory preparation | T3 | Not started |
| T7 | Orchestrator/Context/Worker/composition/ReactAdapter integration and barrier | T5, T6 | Not started |
| T8 | Preview API, 422 security audit, scope, and OpenAPI | T4, T7 | Not started |
| T9 | AgentsPage, API types, four locales, Playwright | T3, T8 | In progress (frontend lane, ahead of order; contract-level evidence only until T8/T13) |
| T10 | Complete affected tests, PG/migration/C11/frontend evidence; create 06 | T2–T9 | Not started |
| T11 | Actual A1–A11/C1–C11/M1–M3 acceptance; create 07 | T10 | Not started |
| T12 | Independent low-sensitivity idempotent Phase 3 example seed | T11 | Not started |
| T13 | Fresh-quickstart wiring, off/on/rollback verification, 06/07 appendices | T12 | Not started |

## 4. Detailed Tasks

### T1 — Design Revision and Documentation Freeze (Complete)

- **Files**: topic `README.md/.en.md`; this phase's bilingual `01`–`05`; this bilingual breakdown. No production code or 06/07.
- **Deliverables**: R-1–R-15; preserved G/US/FR/AC/P3/A/C numbering; T2–T13 order and verification gates.
- **Verification**: document pairing/numbering/stale-token/diff checks; these are documentation checks, not product tests or acceptance.
- **Specification review**: code reality, development versus launch gates, start barrier, flags, C11, and seed order frozen.
- **Quality review**: bilingual parity, no prewritten passes/secrets/production-file changes.

### T2 — Migration, Settings, and Rollout Skeleton

- **Files**: `backend/migrations/versions/0058_agent_execution_metadata.py`; `core_platform/platform_services/platform_settings/settings.py`; `backend/tests/test_agent_execution_phase3_migration.py`, `test_agent_execution_phase3_settings.py`; private ORM mappings if needed.
- **Dependencies/trace**: T1; FR-6, FR-9; AC-6, AC-10, AC-11; P3-UT-20, P3-IT-14/15, P3-CM-01/02.
- **RED**: revalidate with `uv run --directory backend alembic heads`, then `uv run --directory backend pytest tests/test_agent_execution_phase3_migration.py tests/test_agent_execution_phase3_settings.py`; confirm failure for missing five columns/safe settings.
- **GREEN**: load Section 1 PG environment; run the same pytest, `uv run --directory backend alembic upgrade head`, concurrency/old-row checks, and disposable downgrade; `uv run --directory backend ruff check src tests`; scoped format on task files; architecture check.
- **Acceptance points**: only five nullable JSONB columns, no backfill/sixth column/historical edits; off by default, strict probe/policy/cache/size bounds, no secrets.
- **Specification review**: migration chain and DTO/public-event boundaries follow R-3/R-8/R-9. **Quality review**: real PG evidence, reversibility, old-binary compatibility, and format boundary complete.

### T3 — ExecutionConfig, Registry Metadata, and AgentConfig Compatibility

- **Files**: `agent_execution/contracts/config.py`, `registry/adapter_registry.py`, `business_capabilities/agent_config/service.py`; `backend/tests/test_agent_execution_phase3_config.py`, `test_agent_execution_registries.py`, `test_agent_config_execution_compat.py`.
- **Dependencies/trace**: T2; FR-1, FR-2; AC-1, AC-2; P3-UT-01–05/21, P3-IT-01/02/16, P3-CM-05.
- **RED**: `uv run --directory backend pytest tests/test_agent_execution_phase3_config.py tests/test_agent_execution_registries.py tests/test_agent_config_execution_compat.py`, covering aliases, unknown triples, factory=0, no read UPDATE, and default-free diffs.
- **GREEN**: same pytest plus affected model/tool tests including `test_agent_model_required.py`; ruff, scoped format, architecture.
- **Acceptance points**: one normalizer serves drafts/publication/preview/execution/diff; strict DTOs and exact metadata preserve fresh-Adapter semantics and historical JSONB.
- **Specification review**: verify AC-1/2 and no model/tool authorization bypass. **Quality review**: immutability, conflict paths, call counts, and canonical diffs that retain real changes.

### T4 — Capability Layers, Trusted Ports, and Cache/Warmer

- **Files**: `agent_execution/contracts/capabilities.py`; `agent_execution/capability/{ports,resolver,cache,warmer}.py`; `backend/tests/test_agent_execution_phase3_capabilities.py`.
- **Dependencies/trace**: T3; FR-3, FR-4, FR-5; AC-3, AC-4, AC-5; P3-UT-06–12/22/23, P3-IT-03/11, P3-CM-07 (R-16 see 03 §4.1).
- **RED**: `uv run --directory backend pytest tests/test_agent_execution_phase3_capabilities.py`, initially covering cold/stale, workspace_required, monotonic narrowing, unknown policy, complete cache keys, and warmer shutdown.
- **GREEN**: same pytest repeatedly with fake clocks and no waits/task leaks; ruff, scoped format, architecture.
- **Acceptance points**: composition/background warmer performs initial population/refreshes, hot path only reads; miss/stale/error unavailable; Available≤Declared and Effective narrows; unknown capabilities/policy fail closed.
- **Rework scope this round (R-16–R-22)**: add `PolicyRevisionScope` and `TrustedPolicyProvider.current_revision` in `capability/ports.py`; in `capability/resolver.py` drop the request field `policy_revision`, read it from the provider once per round and thread that observation through key/loader/echo validation, **delete the fallback branch so `EffectiveCapabilities.policy_revision` always equals the round's fresh observation**, and add `PolicySourceUnavailableError`; add `execution_restriction_digest`/`NO_EXECUTION_RESTRICTIONS` and the two projection functions in `contracts/capabilities.py` and export them from `contracts/__init__.py`; in `platform_settings/settings.py` add the six fields, change both TTLs to `gt=0`, type `policy_version` as `AdapterVersion`, and add the Phase-3-on cross-field validation; add six lines to `backend/.env.example`; flip the zero-value acceptance assertions in `test_agent_execution_phase3_settings.py` to rejection and update the request field-set assertion in `test_agent_execution_phase3_capabilities.py`. Verified by P3-UT-20/23/24/25.
- **Specification review**: R-6/R-7, cache identity/tenant/version/revision/digest/generation, and least privilege. **Quality review**: singleflight, timeouts, lifecycle, reasons, and sanitized DTOs reproducible.

### T5 — Five Snapshots and One-Time Persistence

- **Files**: `agent_execution/contracts/snapshots.py`, `agent_execution/capability/snapshots.py`, `core_platform/agent_runtime/repository.py`, `core_platform/agent_runtime/schemas.py`; `backend/tests/test_agent_execution_phase3_snapshots.py`.
- **Dependencies/trace**: T2, T4; FR-6; AC-6, AC-11; P3-UT-13–15, P3-IT-06–08/18, P3-CM-06.
- **RED**: load PG environment and run `uv run --directory backend pytest tests/test_agent_execution_phase3_snapshots.py tests/test_runtime_postgres.py`; confirm missing DTOs, nested denylist, per-type limits, and conditional NULL writes fail appropriately.
- **GREEN**: same pytest with concurrency/retry/DB-commit-failure tests (the injection must fail only after the UPDATE actually executed); ruff, scoped format, architecture.
- **Acceptance points**: strict/versioned DTOs; recursive scan without value echo (the value-side path rejection applies to every string value by design, with legitimate-shape negative controls); independent default 65536-byte limits (a decisive assertion distinguishes them from a shared aggregate); serialization strictly revalidates the canonical text so `model_copy` cannot become a write path; replay offers semantic guarantees, accepts `str | Mapping`, and distinguishes wrong-type from missing-payload codes; execution_id lives inside the DTOs with no sixth column, bound to this row's run id by both the entry guard and the SQL predicate; the barrier returns a controlled classification `written/reused/audit_conflict/not_claimed/lease_lost` (never payload content); one commit and no terminal-state rewrites (compared field by field against the full stored payload); the four capability snapshot constructors accept only a `CapabilityResolution`, whose available/effective already carry Workspace narrowing (R-22).
- **Specification review**: public `run.started` remains at claim; do not prematurely change Orchestrator order here. **Quality review**: transaction atomicity, write-once predicate, stable serialization, public allowlists, and secret-free logs.

### T6 — Instruction Providers and React Preparation

- **Files**: `agent_execution/contracts/instructions.py`, `agent_execution/instructions/{react,test}_provider.py`, `applications/platform_runtime/runtime_factory.py`; `core_platform/agent_runtime/engine.py` only for equivalent input wiring if needed; `backend/tests/test_agent_execution_phase3_instructions.py`, `test_runtime_engine.py`.
- **Dependencies/trace**: T3; FR-7; AC-7, AC-8; P3-UT-16–19, P3-IT-09/10.
- **RED**: `uv run --directory backend pytest tests/test_agent_execution_phase3_instructions.py tests/test_runtime_engine.py tests/test_react_engine_adapter.py`, proving missing Provider/duplicate-rendering and message-compatibility tests fail first.
- **GREEN**: same pytest plus affected Summary/Memory tests; exact System→Summary→Memory→history→user comparison; ruff, scoped format, architecture.
- **Acceptance points**: one system-prompt and Summary/Memory computation each; test Provider has independent format and no Memory query; no empty messages/double write-back, dual emit/ack/Outcome unchanged.
- **Specification review**: Providers only adapt format and RuntimeFactory prepares before the runner. **Quality review**: message fixtures, budget/dropped/history, Provider call counts, and errors covered.

### T7 — Execution Integration, Start Barrier, and Flags

- **Files**: `agent_execution/orchestration/{execution_context,orchestrator}.py`, `agent_execution/adapters/react/adapter.py`, `applications/platform_runtime/runtime_composition.py`, `core_platform/agent_runtime/worker.py`; `backend/tests/test_agent_execution_phase3_orchestration.py`, `test_execution_orchestrator.py`.
- **Dependencies/trace**: T5, T6; FR-3–FR-9; AC-3–AC-10; P3-IT-03/06–13/18, P3-CM-03/06/07/09.
- **RED**: load PG environment and run `uv run --directory backend pytest tests/test_agent_execution_phase3_orchestration.py tests/test_execution_orchestrator.py tests/test_react_engine_adapter.py tests/test_runtime_postgres.py`, asserting DB failure start=0, public event order, and four-state matrix.
- **GREEN**: same pytest plus cached Runtime off→on/on→off, claimed-row fixed paths, late results/cancel/timeout; ruff, scoped format, architecture.
- **Acceptance points**: Provider prepare+snapshot commit→Adapter.start; Phase 3 flag outside fingerprint; off/off and off/on unchanged, on/off fails closed, on/on complete; off non-React=`execution_phase3_disabled`; composition wiring discipline, six items: all parameters come from the R-18 settings (zero hardcoding); `execution_capability_policy_version`→descriptor→provider share one source (R-20); the revision is read through `current_revision`, never passed as a constant or defaulted to 0 (R-17); `execution_restriction_digest` passes `NO_EXECUTION_RESTRICTIONS` (R-17); `ExecutionRequest.effective_capabilities` uses `effective_capability_flags` (R-21); snapshots and requests read only `resolution.*`, never raw cache values (R-22). **Barrier-result mapping discipline (frozen by T5 D-3)**: `audit_conflict` → fail closed with `Adapter.start` at zero; `not_claimed`/`lease_lost` → the existing lost-lease/cancellation path, never a configuration error; only `written`/`reused` may proceed to `Adapter.start`, and the payloads must come from `serialize_execution_snapshots` (anything else raises `ExecutionSnapshotError`, a programming/audit error rather than a runtime classification). Under concurrent identical writes both callers may report `written`; the label is diagnostic and the stored result is identical.
- **T4 carried-over items (must close before T7 acceptance)**: (1) constructor negative controls (M2)—`CapabilityCache` rejecting `ttl<=0`/`capacity<1` (cache.py:108), `CapabilityWarmer` rejecting non-positive intervals (warmer.py:35), `CapabilityResolver` rejecting `probe_timeout<=0` (resolver.py:182, currently only `policy_timeout` is tested); T7 is the first task that builds these components from settings values, so that is the natural place. (2) loader-side Workspace generation re-read fix (Minor-3)—the key is built from the round's observed generation while the loader re-reads generation when invoking probe/policy contexts (resolver.py:439/:560), the same class of skew as the revision issue already fixed this round; there is no echo validation so no false mismatch arises, the impact is minor semantic staleness within one TTL, and the fix is to pass the round's value into the loader as a parameter. (3) the `current_revision` implementation must satisfy 03 §4.2 "monotonic per scope" and be pinned by a T7 test. Owner: development role; deadline: before T7 acceptance.
- **Specification review**: R-8–R-11 without public Run/SSE, Memory, or terminal-state changes. **Quality review**: barrier call order, fault injection, ContextVar/cancel gate, concurrency, and cached-Runtime regressions.

### T8 — Preview API and Forged-Field Security Audit

- **Files**: `applications/customer_service/platform_routes.py`, `applications/application_factory.py` (minimal route/field-path-aware audit hook only), related Run/Agent schemas and existing audit wiring; the §7.4 flags endpoint and response DTO (same test file); `backend/tests/test_agent_execution_phase3_preview.py`.
- **Dependencies/trace**: T4, T7; FR-5, FR-8, FR-9; AC-5, AC-9, AC-10; P3-UT-11/12/22/26, P3-IT-04/05/11/17/20, P3-CM-03/04.
- **RED**: load PG environment and run `uv run --directory backend pytest tests/test_agent_execution_phase3_preview.py`, covering strict 422, cross-scope 404, factory/Run=0, probe failures, OpenAPI allowlist, the missing `execution-config-flags` contract, and **actual audit records**.
- **GREEN**: same pytest plus Agent/Run route regressions; ruff, scoped format, architecture.
- **Acceptance points**: preview supports unsaved drafts; returns only Engine/safe schema/Effective reasons; trusted scope; audit contains no body/values/Authorization/Cookie; preview grants no Run; preview `capabilities` uses `effective_capability_views` with the field names and ordering of 03 §7.2, with no bespoke response model (R-21); the new `GET /api/v1/agents/execution-config-flags` returns only the two booleans, is zero-side-effect, answers normally under off/misconfiguration, and never returns domain errors (P3-UT-26/P3-IT-20, R-25).
- **Specification review**: HTTP statuses and stable DomainError mappings follow R-12/R-13. **Quality review**: query audit rather than only 422 and recursively scan responses for snapshots/probes/policy/path leaks.

### T9 — AgentsPage, Four Locales, and Playwright

- **Files**: `frontend/src/shared/api/client.ts`, `features/agents/AgentsPage.tsx`, `agents.css`, at most one or two necessary colocated components; `frontend/src/i18n/locales/{zh-CN,zh-TW,en,hi}.json`; `frontend/tests/agent-execution-config.spec.ts`.
- **Dependencies/trace**: T3, T8; FR-1, FR-5, FR-8; AC-1, AC-2, AC-5, AC-9; P3-CM-08; M1–M3.
- **RED**: `cd frontend && npx playwright test tests/agent-execution-config.spec.ts`, initially verifying old-Agent no-default-dirty, read-only preview, disabled-only narrowing, conflicts, and four locales.
- **GREEN**: `cd frontend && npm run typecheck && npm run check:i18n && npm run build && npx playwright test tests/agent-execution-config.spec.ts tests/agent-memory-config.spec.ts`; retain screenshots/traces/network evidence.
- **Acceptance points**: reuse antd/AgentModelPicker/styles, viewer read-only; preview creates no Run; no hardcoded fallback in `zh-CN/zh-TW/en/hi`; no component-test runner; M3 declarative gating—consume the 03 §7.4 flags: off hides the preview/narrowing entries, React model/round editing and historical viewing stay ungated, the misconfiguration state shows a hint without fake success, and a failed flags read fails closed (R-25).
- **Conflict rulings (R-23/R-24/R-25)**: the read-only Engine presentation is compliant (R-23, no rework); `patchReactConfig` minimal write-back is compliant (R-24, no rework); the T9 rework is limited to consuming the §7.4 flags for declarative hiding/hints plus the corresponding Playwright mocks and assertions (R-25), still touching only `frontend/`.
- **Specification review**: M1–M3 or equivalents, canonical dirty/diff, and preview-not-authorization complete. **Quality review**: API types, accessible names, locales, request assertions, and existing editor regression.

### T10 — Complete Affected Verification and 06

- **Files**: all T2–T9 tests/implementation; `backend/tests/test_agent_execution_phase3_performance.py`; create `06-test-report.md` and `.en.md` only after execution.
- **Dependencies/trace**: T2–T9; all FR/AC and P3-UT/IT/CM, especially C11.
- **RED/negative control**: `uv run --directory backend pytest tests/test_agent_execution_phase3_performance.py` first proves fewer than 100 samples/missing environment yields `not_measured` or `pending_env`, neither product pass nor product defect; confirm 06 does not yet exist.
- **GREEN**: run every affected T2–T9 pytest (real PG/migration), ruff, scoped format, architecture, and four frontend checks; collect at least 100 valid interleaved paired samples on the real warmed-cache resolver/admission path in one environment and retain raw data/p95; add target-SHA full CI when available.
- **Report gate**: create bilingual 06 only from actual commands/output, listing every P3-UT/IT/CM, environment, SHA, skips, pending_env, format baseline, and raw C11 evidence; do not enter T11 if incomplete.
- **Specification review**: independently verify evidence for every P3 ID without deleted hard gates. **Quality review**: recompute raw data, validate samples, scan secrets, and prevent exaggerated CI/production claims.

### T11 — Actual Acceptance and 07

- **Files**: reference existing 06/CI/database/Playwright evidence; create `07-acceptance-report.md` and `.en.md` only after acceptance.
- **Dependencies/trace**: T10; A1–A11, C1–C11, M1–M3, G1–G4, US-1–US-6.
- **RED/preconditions**: confirm bilingual 06 and exit criteria; otherwise remain unaccepted and write no passing 07. Supplemental checks follow 04 only for affected items rather than repeating full manual suites.
- **GREEN/evidence**: acceptance owner/executor (may be the same person) checks A/C, completes M or accepts equivalent Playwright, reviews C11/migration/rollback/upstream launch gaps, and records one conclusion.
- **Report gate**: write bilingual 07 only after actual acceptance; any veto, C11, cross-tenant, disclosure, or silent non-React fallback failure blocks passage; retain environmental gaps.
- **Specification review**: each A maps to correct AC/FR/G/US and development entry is not confused with launch gates. **Quality review**: evidence links, expected/actual, open-item owners/deadlines, and acceptance record are genuine.

### T12 — Post-Acceptance Independent Example Seed

- **Files**: `backend/src/agent_platform/applications/seed_execution_phase3.py`; necessary low-sensitivity fixtures; `backend/tests/test_execution_phase3_seed.py`. Do not wire quickstart automatically in this task.
- **Dependencies/trace**: T11 with real 06/07 present; supports later US-1/US-6 demonstrations but never substitutes for FR/AC evidence.
- **RED**: load PG environment and run `uv run --directory backend pytest tests/test_execution_phase3_seed.py`, first proving the module/deterministic examples/idempotency are absent.
- **GREEN**: same pytest; execute seed twice to verify create-or-preserve, stable IDs, no duplicates, and no runtime side effects; ruff, scoped format, architecture.
- **Acceptance points**: low-sensitivity typed Engine/React/disabled examples and necessary safe demo Profile resources; no fabricated snapshots, Runs, automatic capability grants, or production opt-in changes.
- **Specification review**: strictly post-acceptance with no Host/Codex/secrets. **Quality review**: idempotency, preservation of user edits, sensitive scanning, and standalone-run evidence.

### T13 — Fresh Quickstart Wiring, Verification, and Appendices

- **Files**: minimal changes to `deploy/container/bootstrap.py` and the existing quickstart chain; T12 seed; after verification append to **existing** `06-test-report.md/.en.md` and `07-acceptance-report.md/.en.md`.
- **Dependencies/trace**: T12; deployment-form verification of AC-10 and P3-CM-02/09; never rewrite T10/T11 original conclusions.
- **RED**: in an unwired fresh environment confirm bootstrap produces no Phase 3 examples, recording missing wiring rather than a fabricated product-test failure; confirm both 06/07 exist for appendices.
- **GREEN**: run `sh nexusdesk quickstart` in a dedicated fresh environment; verify automatic idempotent seed, default off, original Orchestrator off/on paths, Phase 3 on+Orchestrator on, on+off fail-closed, off non-React rejection, real Run snapshot generation, and application rollback; restart/rerun seed to prove no duplicates.
- **Evidence**: retain container/migration/seed/off/on/rollback/real-Run snapshot and sensitive-scan evidence; append a bilingual post-acceptance quickstart appendix to existing 06/07; production never auto-inserts examples.
- **Specification review**: order remains seed→fresh quickstart→appendices without early creation/overwriting of 06/07. **Quality review**: fresh environment, repeated startup, flags, rollback, real snapshots, and secret-free evidence reproducible.

## 5. Definition of Done and Coordination

- Close T2–T9 only after RED/GREEN, both reviews, traceability, and document synchronization.
- T10/T11 reports contain actual results, not expectations from this plan; never move T12/T13 ahead of acceptance.
- **Coordination items (not unresolved architecture)**: T2 revalidates migration head; T10 coordinates target-SHA CI, independent PG, real performance environment, and authorized historical fixtures; T11 names the small-team acceptance owner/executor and determines upstream-gap impact on launch scope; T13 uses an isolated fresh quickstart environment without damaging an existing developer stack.
- If environments/evidence are unavailable, retain `pending_env` / `not_measured` and do not mark DONE or passed. Never lower C11, remove security audit, skip locales, or fabricate quickstart evidence to obtain a pass.
- R-17–R-22 are frozen before T5, T7 and T8 start; if a T7/T8 implementation conflicts with a ruling, update the bilingual 08/03 first (and 02/04/05 accordingly) before implementing.
- R-23–R-25 are frozen before T8 starts and before the T9 rework starts; if an implementation conflicts, update the bilingual 08/03 first (and 04/05 accordingly) before implementing; 02 stays untouched unless a ruling itself changes requirement semantics.
