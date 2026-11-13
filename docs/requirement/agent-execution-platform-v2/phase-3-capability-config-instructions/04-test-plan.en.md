# Phase 3 · Capabilities, Configuration, and Instructions — Test Plan

> Status: pending implementation (execute after development; no test results or 06 currently exist)
> Created: 2026-11-02
> Revised: 2026-11-13 (T5 rework freeze points in P3-UT-13/15, P3-IT-06/07/08/18, P3-CM-06: decisive per-class budget assertion, post-serialization revalidation, controlled barrier outcome, real commit-phase failure injection, whole-file SQL static gate)
> Revised: 2026-11-13 (added P3-UT-26/P3-IT-20 and the §6.1 M3 declarative-gating scenario, per 03 §7.4/R-25)
> Revised: 2026-11-13 (T4 rework rulings R-17–R-22: trusted policy-revision entry point, capability settings home and TTL floor, single Effective projection, non-bypassable Available narrowing)
> Revised: 2026-11-13 (T4 specification review clarified the required-capability-missing boundary; added P3-UT-23, per R-16)
> Revised: 2026-11-12 (small-team evidence reuse, real PostgreSQL, start barrier, 422 audit, four locales, and C11)
> Basis: `02-requirements.md` (FR-1–FR-9, AC-1–AC-11), `03-technical-design.md`

## 1. Scope and Principles

**Scope**: AgentConfig compatibility/canonical diff, Registry metadata, typed configuration, Declared/Available/Policy/Effective, trusted probe/policy/cache, read-only preview, five snapshots, Instruction Providers, React Summary/Memory, migration `0058_agent_execution_metadata`, both flags, and rollback.

**Principles**:

1. Use Phase 0 measurements and current code as baselines; focused baseline 163 passed / 5 skipped is development entry, not upstream formal acceptance or a full-suite pass.
2. Phase 3 off preserves the deployment's original Phase 2 on/off behavior; on+orchestrator-off fails closed; non-React in every off state is explicitly rejected.
3. Independently regress historical NULL, missing Engine, missing Summary/Memory, and default-equivalent diffs.
4. Cover forged capabilities/policy, extra fields, cross-tenant access, nested secrets, size excess, and DB failures; **422 alone is not a security audit**.
5. The snapshot barrier's start means `Adapter.start`/runner/Runtime side effects and does not change public `run.started` ordering.
6. Use fake clocks/controlled doubles for probe expiry, cache invalidation, and Run timeout; decision replay invokes no real model/tool.
7. Feed raw UT/IT/CM, CI, PG, and Playwright evidence directly to A/C; retain `pending_env` for unavailable environments and never remove hard gates.

## 2. Environments, Data, and Commands

| Environment | Purpose |
|---|---|
| Pure unit tests | Normalizer, schemas, capability intersection, cache keys, denylist, Providers, and preview DTOs |
| Independent pgvector PostgreSQL + pytest fixtures | Draft/publication/Run/snapshots, concurrency, cross-tenant, migration, and terminal states; container-based testing is the default |
| Phase 1 LocalTestAdapter + Phase 2 test Orchestrator | Fresh Adapter, barrier, events, ack, and terminal states without an external Engine |
| Mock/demo model + MemoryInjection doubles | React messages, Summary/Memory, one rendering pass, and write-back compatibility |
| Disposable migration database | Upgrade/downgrade from dynamically confirmed predecessor; never production |
| Existing frontend toolchain | Typecheck, `check:i18n`, build, targeted Playwright; no component-test runner |

Use Phase 0 authorized sanitized fixtures plus two tenants and multiple business/workspace scopes. Declarations, probes, policy, and Providers are deterministic doubles; inject persistence failures before the Adapter mock. Clean Runs/versions/audit per case and share no mutable policy.

The coordination environment has started `nexusdesk-phase3-pg` (127.0.0.1:55433), and baseline `0057_industry_pack_runtime` upgraded successfully; implementing agents must independently revalidate the container, head, and target commit. Random credentials remain only in mode-600 `/tmp/nexusdesk-phase3-pg.env`, never in repository/documents/reports. Alembic reads `AGENT_DATABASE_URL`, while pytest reads `TEST_DATABASE_URL`: load the env, explicitly assign `AGENT_DATABASE_URL="$TEST_DATABASE_URL"`, and set a temporary `AGENT_API_TOKEN`. The earlier TEST-only attempt reached default 5432 and was a corrected environment error, not a product defect.

Run from repository root (T2–T10 supply exact affected test paths):

```bash
uv run --directory backend ruff check src tests
uv run --directory backend ruff format --check <only Python files added/modified by Phase 3>
uv run --directory backend python ../scripts/check_architecture.py
uv run --directory backend alembic heads
uv run --directory backend pytest <affected tests>
cd frontend && npm run typecheck && npm run check:i18n && npm run build
cd frontend && npx playwright test tests/agent-execution-config.spec.ts
```

CI runs the full pytest suite on push/PR. Full-tree `ruff format --check src` currently has unrelated pre-existing Memory seed differences; 06 must record that baseline boundary. Phase 3 formats only its own Python files, modifies no unrelated files, and never claims full-tree format success.

## 3. Unit Tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P3-UT-01 | Normalize legacy configuration without `engine/react` | Obtain `react/native/v1`, preserve old fields, and do not mutate input | FR-1; AC-1 |
| P3-UT-02 | Equal old/new React aliases | Accept and emit one canonical value | FR-1, FR-2; AC-1, AC-2 |
| P3-UT-03 | Unequal old/new React aliases | Reject with the conflicting fields, never silently choose | FR-2; AC-2 |
| P3-UT-04 | Unknown triple, latest, extra fields, arbitrary dictionaries | Reject all without bypassing Registry | FR-2; AC-2 |
| P3-UT-05 | Unpaired Profile ID/version, invalid rounds, unknown/duplicate disabled capabilities | Strictly reject or deduplicate under explicit rules without relaxing bounds | FR-2, FR-4; AC-2 |
| P3-UT-06 | Declared=true with missing/incompatible deployment | Available=false with stable reason; Declared unchanged | FR-3; AC-3 |
| P3-UT-07 | Probe timeout/exception and cache hit/invalidation | Bounded unavailable; complete keys; declaration changes invalidate; no raw exception | FR-3; AC-3 |
| P3-UT-08 | `workspace_required=true` without Workspace | Available=false; missing required capabilities block start | FR-3; AC-3 |
| P3-UT-09 | Lower layer allows after any upper-layer denial | Effective=false with all decisions recorded | FR-4; AC-4 |
| P3-UT-10 | Unknown capability/policy version and missing policy source | No default grant; minimum privilege or configuration rejection | FR-4; AC-4 |
| P3-UT-11 | Forge capability layers in ExecutionRequest/public RunRequest | Strict rejection; server objects ignore client values | FR-5; AC-5 |
| P3-UT-12 | Tenant/actor differs from authentication | Use trusted context and record the violation | FR-5; AC-5 |
| P3-UT-13 | Missing snapshot fields, unserializable data, one-type size excess, or `model_copy` bypassing validators | Fail the barrier; each type has its own default 64KiB limit (decisive assertion: with budget = the largest single class the aggregate succeeds while the five summed bytes exceed it, and only the oversized class is rejected); serialization strictly revalidates the canonical text, so missing/duplicate/reordered items and available↔reason contradictions are rejected | FR-6; AC-6 |
| P3-UT-14 | Nested Token/API Key/raw Memory/host path in snapshots | Reject at any depth before write; no original value in logs/errors | FR-6; AC-6 |
| P3-UT-15 | Repeat serialization and read-only decision replay | Stable keys/versions/reasons; no snapshot mutation or Engine call; replay guarantees are semantic (strict revalidation plus identity consistency), a prettified but semantically equal payload is accepted by design, and byte-level tamper detection is not promised; the entry accepts `str \| Mapping` and distinguishes wrong-type from missing-payload error codes | FR-6; AC-6 |
| P3-UT-16 | Empty/disabled React Summary/Memory | No empty messages; baseline sequence retained | FR-7; AC-7 |
| P3-UT-17 | Summary, Memory, combined, and history truncation | Exact System→Summary→Memory→history→user order | FR-7; AC-7 |
| P3-UT-18 | Different test Provider format | One business-rendering pass and no forced ReAct conversion | FR-7; AC-8 |
| P3-UT-19 | Unknown Provider, duplicate context, or contract error | Fail before start without Provider fallback | FR-7; AC-7, AC-8 |
| P3-UT-20 | FR-9 defaults, overrides, and invalid bounds (new R-18 fields plus the R-19 strict lower bounds) | Default off; valid overrides work; invalid timeout/cache/size/concurrency/capacity/retry/refresh/identity rejected; `*_cache_seconds=0` rejected; with Phase 3 on, `warm_refresh >= min(TTL)` rejected | FR-9; AC-10 |
| P3-UT-21 | Canonical diff and Registry metadata validation | Defaults produce no diff, real changes remain, and factory call counts prove drafts instantiate no Adapter | FR-1, FR-2; AC-1, AC-2 |
| P3-UT-22 | Preview allowlists, cache keys, and warmer lifecycle | No internal snapshots; complete keys; cold/expired unavailable, background success enables, hot path never probes, shutdown leaks no tasks | FR-3–FR-5; AC-3–AC-5 |
| P3-UT-23 | Reason-code partition (R-16): infrastructure-unavailability versus policy narrowing | Missing/admission blocking covers only probe_unavailable/probe_timeout/probe_stale/workspace_unavailable/policy_unavailable; with only not_declared or only platform/tenant/agent/execution narrowing, admission proceeds while Effective=false and snapshots retain source/version/reason | FR-3, FR-4; AC-3, AC-4 |
| P3-UT-24 | Trusted policy revision source and echo (R-17) | Key/context revision comes from the provider's own `current_revision`; an advance changes the key; a divergent echo records an error state producing `policy_unavailable`; a raising read maps to `execution_policy_unavailable` and never defaults to 0; the request DTO carries no `policy_revision` | FR-3, FR-4; AC-3, AC-4 |
| P3-UT-25 | Single Effective projection and non-bypassable Available narrowing (R-21/R-22) | `effective_capability_flags` always returns 11 keys with false entries retained; `effective_capability_views` returns the complete canonical-order triples; with a cached `workspace_required=true` and a Workspace port returning None/unavailable, `resolution.available` is false with `workspace_unavailable`; snapshot construction accepts only a `CapabilityResolution` | FR-3, FR-5, FR-6; AC-3, AC-5, AC-6 |
| P3-UT-26 | `GET /agents/execution-config-flags` strict DTO and zero side effects (03 §7.4) | The response carries exactly `execution_phase3_enabled/execution_orchestrator_enabled` verbatim from settings with `extra=forbid`; the call only reads settings—probe/Adapter/Run/cache-read counts are 0; both the fully-off and the on + orchestrator-off states answer normally instead of `execution_phase3_disabled` | FR-8, FR-9; AC-9, AC-10 |

## 4. Integration Tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P3-IT-01 | Read old draft → edit/publish normally → React Run | Reads cause no UPDATE; default-free canonical diff; baseline-compatible behavior | AC-1; FR-1, FR-2 |
| P3-IT-02 | Publish valid/unknown/unavailable configuration | Valid exact resolution; invalid rejected before publication/admission with no Adapter start | AC-2; FR-2 |
| P3-IT-03 | Execute with declarations, probes, and layered policy | Five data types agree; Effective narrows; preview/Run share resolver | AC-3, AC-4; FR-3, FR-4 |
| P3-IT-04 | Inject forged fields into Run/Agent/preview | 4xx/domain errors, zero elevation; **directly query security audit** for trusted principal/route/sanitized paths, with no body/values/secrets | AC-5; FR-5 |
| P3-IT-05 | Tenant B accesses tenant A configuration, preview, Run snapshots, and audit | Query-layer inaccessibility and existing 404, not merely hidden fields | AC-5; FR-5 |
| P3-IT-06 | Inspect Adapter.start barrier for a completed Run | Five columns committed once before Adapter.start (barrier returns `written`); public `run.started` remains at claim | AC-6; FR-6 |
| P3-IT-07 | Inspect snapshots after Adapter failure, cancellation, and timeout | Startup snapshots retained, existing terminal states correct, late results do not rewrite (assertion compares the full stored payload field by field, not only `execution_id`/`schema_version`) | AC-6; FR-6 |
| P3-IT-08 | Inject serialization/denylist/DB-commit failures | Run fails closed, `Adapter.start=0`, no runner/model/tool side effects; commit-failure injection must fail **after the UPDATE executed** (a before_execute injection never ran the statement and proves nothing about atomicity), and must show the same barrier landing normally afterwards | AC-6; FR-6 |
| P3-IT-09 | MemoryInjection through Summary/Memory/switches/write-back | Zero diff in text/order/budget/logs/write-back; one business-rendering pass | AC-7; FR-7 |
| P3-IT-10 | Same context through React and test Provider | Independent formats, one rendering pass, public events unaffected | AC-8; FR-7 |
| P3-IT-11 | Change platform/tenant policy after preview, then execute | Preview read-only; execution recomputes and never reuses old authorization | AC-4, AC-9; FR-4, FR-8 |
| P3-IT-12 | Phase 3 off with Orchestrator off and on | Each exactly preserves its original Phase 2 path, five NULL columns, no Phase 3 probe/snapshot side effects | AC-10; FR-8, FR-9 |
| P3-IT-13 | Off non-React and on+orchestrator-off | Off non-React returns `execution_phase3_disabled` with zero React starts; invalid on combination fails closed, never legacy | AC-10; FR-8, FR-9 |
| P3-IT-14 | Upgrade `0058` from dynamic predecessor with concurrent old/new Run I/O | Only five columns; old rows NULL, new rows writable, existing statements unaffected | AC-11; FR-6 |
| P3-IT-15 | Roll back to Phase 2 binary without downgrade | Nullable columns do not obstruct old code; React and history intact | AC-10, AC-11; FR-8 |
| P3-IT-16 | Old/new React through Model Gateway/tool validation | Profile/version/authorization/Run association unchanged; no generic bypass or secret snapshots | AC-1, AC-2, AC-6; FR-2, FR-6 |
| P3-IT-17 | Preview unsaved draft and published Agent | Support `agent_id=null`; create no Run/Conversation/Adapter/snapshot; scope and OpenAPI allowlist correct | AC-5, AC-9; FR-5, FR-8 |
| P3-IT-18 | Concurrent snapshot retry and cached-Runtime flag changes | Reuse execution_id with no sixth column; same startup verifies/reuses (`reused`, judged by `jsonb` semantic equality) and divergent decisions return `audit_conflict`; **a foreign execution_id into an all-NULL row must return `audit_conflict` without touching the database**; lost lease and non-running states return `lease_lost`/`not_claimed` rather than a configuration error; off→on/on→off and claimed rows retain fixed paths and policy | AC-6, AC-10; FR-6, FR-9 |
| P3-IT-19 | Real composition wiring consistency (R-18/R-20/R-21) | resolver/cache/warmer parameters all come from settings with no hardcoded constants; `execution_capability_policy_version` equals the registered `descriptor.policy_version` and the provider echo; zero identity-validation failures across consecutive resolutions; preview and Run use the shared projections and match all 11 entries byte-for-byte | AC-3–AC-6, AC-10; FR-3–FR-6, FR-9 |
| P3-IT-20 | Reader fetches execution-config-flags on the internal-management surface | Unauthenticated receives 401/403; a Reader receives the real flag pair, identical for every tenant and across scopes; OpenAPI includes the route and the allowlisted response contains no internal IDs/digests/policy/probe payloads; the frontend hides Phase 3-only entries from it (Playwright evidence in §6.1) | FR-8, FR-9; AC-9, AC-10 |

## 5. Common Checks

| ID | Check | Pass standard | Trace |
|---|---|---|---|
| P3-CM-01 | Online migration and numbering | Dynamically revalidate head/down_revision, currently `0058→0057`; five columns only, no backfill/history edits; disposable downgrade | AC-11; FR-6 |
| P3-CM-02 | Settings | Defaults, overrides, invalid bounds, and cache invalidation follow FR-9; examples contain no secrets | AC-10; FR-9 |
| P3-CM-03 | Audit and observability | Engine/provider/policy versions/reasons present; forged 422 has real audit; no body/Token/Memory/host details | AC-5, AC-6; FR-5, FR-6 |
| P3-CM-04 | Tenant/scope isolation | Configuration, preview, snapshots, policy, and audit isolated by tenant/business/workspace | AC-5; FR-5 |
| P3-CM-05 | Historical compatibility | Valid fixtures follow decisions; no UPDATE/bulk rewrite/default diff; failures have defect records | AC-1; FR-1 |
| P3-CM-06 | Snapshot immutability and NULL | Commit once before Adapter.start and never update; no historical backfill or public exposure; the static gate must scan **every** `UPDATE runtime_runs` in repository.py (not only statements preceding the barrier method) and assert the five snapshot columns appear only inside `write_execution_snapshots`; that static test must not carry the postgres marker so it also runs in the non-PG selection | AC-6; FR-6 |
| P3-CM-07 | Capability authorization | Declared/Available/Effective are not client authorization; upper denial persists and missing Workspace never opens access | AC-3–AC-5; FR-3–FR-5 |
| P3-CM-08 | Frontend i18n/read-only | `zh-CN/zh-TW/en/hi` complete; typecheck/check:i18n/build and Playwright pass; Effective has no edit/submit authorization | AC-9; FR-8 |
| P3-CM-09 | Overall rollback | Flag matrix and application rollback follow 03 without downgrade; non-React never degrades and history remains | AC-10; FR-8, FR-9 |
| P3-CM-10 | Phase boundary | No real Host/Workdir/Sandbox, Codex, general policy console, automatic Engine fallback, or new test framework | AC-2, AC-10; FR-2, FR-8 |

## 6. Frontend, Performance, and Regression Evidence

### 6.1 Frontend

Using mocked `/api/v1/**`, Playwright covers old-Agent default-without-dirty, valid new save, conflict/unknown errors, read-only preview and probe-unavailable, disabled-only narrowing, viewer read-only, and M1–M3 or equivalent evidence. Switch through `zh-CN`, `zh-TW`, `en`, and `hi`, asserting every new control/error/reason is translated without hardcoded fallback. Retain screenshots/traces/network requests proving preview creates no Run. The M3 scenario must mock `GET /api/v1/agents/execution-config-flags`: with `execution_phase3_enabled=false`, assert the preview button and narrowing checkboxes are absent from the DOM, no `/agents/execution-preview` request is issued, and React model/round editing plus historical viewing remain usable; with `true + orchestrator=false`, assert the deployment-misconfiguration hint appears and no fake success is shown.

### 6.2 Real C11 measurement

- Measure the real Phase 3 resolver/admission path against a paired Phase 2 baseline, not an isolated helper; exclude model/tool execution time.
- Before C11 sampling, record and freeze the six R-18 settings values (policy/probe timeouts, concurrency, capacity, retry, refresh, deployment identity) together with the SHA in 06; paired samples must be collected under identical values.
- Use the same host, process build, data, and load; warm config/probe/policy caches separately and discard warmups.
- Interleave old/new paths for at least **100 valid paired samples**; explain excluded failures/timeouts/environment interruptions and retain raw pair timings, timestamps, SHA, configuration, cache versions, and load.
- Report configuration parsing, probe cache, policy cache, and total admission separately; calculate paired-delta p95 against ≤50ms. Averages, one best effort, or pure mock caches are insufficient.
- Missing required environments or insufficient samples remain `pending_env` / `not_measured` and C11 cannot pass. Put raw data in 06 and reference it from 07 without prewriting outcomes.

### 6.3 Regression

- RuntimeEngine, Worker, Repository, cancellation/lease-loss/timeout, Run API/SSE, dual emit/ack/Outcome, and Phase 2 focused tests.
- Agent configuration/publication/rollback, Model Gateway, tool/knowledge authorization, Summary/Memory configuration/injection/logs/write-back.
- Old-code compatibility after migration and new-code NULL behavior; architecture, ruff, three frontend checks, targeted Playwright; full suite in CI.
- Never alter historical fixture expectations to match new behavior or report skips as passes.

## 7. Defects, Exit Criteria, and Reporting

| Severity | Definition | Handling |
|---|---|---|
| P0 blocker | Elevation, cross-tenant access, secret disclosure, unauthorized Adapter.start, data loss | Stop acceptance; fix and rerun complete security/compatibility regression |
| P1 severe | Legacy incompatibility, incorrect Effective, missing snapshots, Provider regression, flag/non-React rejection failure | Fix before acceptance |
| P2 normal | Non-blocking reason, preview, or general quality deviation | Only non-hard-gates may carry an owner/deadline recorded by the acceptance owner |
| P3 minor | Wording, non-sensitive log, or display issue | Schedule a fix; never disguise missing i18n/disclosure by downgrading |

**Exit**: all P3-UT/IT/CM pass; AC-1–AC-11 reproducible; no P0/P1; zero elevation/cross-tenant success; snapshots/audit meet criteria; flag diffs comply; C11 has valid passing measurements. Environmental gaps block their launch commitments. Only after actual completion create bilingual `06-test-report.md/.en.md` with commands, SHA, environment, raw evidence, skips/pending_env, and the format baseline boundary; this plan prewrites no pass conclusion.
