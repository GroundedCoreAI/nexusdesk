# Phase 3 · Capabilities, Configuration, and Instructions — Technical Design

> Status: design calibrated against baseline `3969258`; T2–T5 are implemented in the feature-branch working tree (uncommitted), while the §7 preview contract and §9 migration/release still await T8/T7 wiring, and every unimplemented item below remains planned
> Created: 2026-11-02
> Revised: 2026-11-13 (T5 rework freeze points in §5.2/§5.3: post-serialization strict revalidation, the two intentional narrowings for value-side path rejection and semantic-level replay guarantees, dual startup-identity gates, controlled write-barrier outcome with jsonb semantic equality; §8 adds no "not enabled" hint when the flags read fails)
> Revised: 2026-11-13 (T9 frontend-lane conflict rulings R-23–R-25: pinned Engine read-only presentation in §8, semantic-criterion clarification in §3.2.5, new §7.4 execution-config-flags read-only contract)
> Revised: 2026-11-13 (T4 rework rulings R-17–R-22: trusted policy-revision entry point, capability settings home and TTL floor, single Effective projection, non-bypassable Available narrowing)
> Revised: 2026-11-13 (§4.1 defines the required-capability-missing scope, per R-16)
> Revised: 2026-11-12 (Registry, execution chain, preview API, cache/snapshot, and migration reality)
> Basis: `01-business-goals.md` (G1–G4), `02-requirements.md` (FR-1–FR-9, AC-1–AC-11), architecture Sections 3, 5, 6, 11, 14–17, and 21
> Code verification: 2026-11-12; Alembic head is `0057_industry_pack_runtime`, and `0053_routing_decisions` already exists
> Development entry: focused baseline 163 passed / 5 skipped; Phase 0/1 formal acceptance and Phase 2 production/CI/UAT gaps remain governed by their reports

## 1. Current Code Mapping and Boundaries

| Area | Existing | Phase 3 extension |
|---|---|---|
| Registry | `AdapterDescriptor` has exact identity/enabled only; `register` never invokes factory; `resolve` returns a fresh Adapter and prevents live reuse | Add strict config schema, Declared, probe/policy/provider identities/versions, and exact metadata lookup; drafts never call `resolve` |
| Configuration | `AgentConfig(extra=forbid)` uses JSONB drafts/publications, legacy root model fields, and model/tool/knowledge validation | Normalize through one compatibility layer; retain storage/authorization/publication, add no table, and never rewrite history |
| Orchestration | Orchestrator fixes React/native/v1; ExecutionContext builds requests; composition registers ReactAdapter | Select published ExecutionConfig and extend Context/Orchestrator while preserving worker_emit/runtime_emit, ack, and private Outcome |
| React | `ReactAdapter.start` creates `_Execution` and a runner; RuntimeFactory builds model/tools/Runtime inside it | Prepare snapshots and Provider input before start; create the runner only afterward; retain RuntimeEngine message rules |
| Memory | Worker already supplies `summary_message/customer_memory`; RuntimeEngine orders System→Summary→Memory→history→user | Reuse each rendered result once; Providers only adapt and never reread, rebudget, or write back |
| Runs | Repository.claim marks running and publishes `run.started`; Worker retains legacy/on paths | Keep public claim ordering; add a private five-snapshot commit barrier before Adapter.start and an explicit flag matrix |
| Frontend/API | `/api/v1` internal routes, React 19 + antd v6 AgentsPage, four JSON locales, Playwright | Add internal preview and extend current pages/types; no external service, Postman publication, or component-test framework |

Runtime Host, real processes/Workdir/Sandbox, Codex, credential brokering, strong isolation, network egress, Fencing/Outbox, latest aliases, and automatic cross-Engine fallback remain excluded.

## 2. File-Level Plan

New paths are proposed locations; T2–T9 may adjust them slightly without changing boundaries if 08 is updated. Never copy the execution chain.

| File | Action | Content |
|---|---|---|
| `backend/migrations/versions/0058_agent_execution_metadata.py` | add | Currently `down_revision=0057_industry_pack_runtime`; five nullable `runtime_runs` JSONB columns; revalidate dynamically in T2 |
| `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | modify | Safe Phase 3/probe/policy/cache/snapshot/warmer defaults (R-18/R-19), with no secrets |
| `.../agent_execution/contracts/config.py` | add | `ExecutionConfig`, Engine identity, ReactConfig, and legacy alias normalization |
| `.../agent_execution/contracts/capabilities.py` | modify | Reuse 11 capabilities and add layered reason/decision DTOs; add the single Effective→Run/preview projection functions (R-21) and `execution_restriction_digest`/`NO_EXECUTION_RESTRICTIONS` (R-17) |
| `.../agent_execution/contracts/snapshots.py` | add | Five strict snapshot DTOs, schema/version, recursive denylist, serialization, and size validation |
| `.../agent_execution/contracts/instructions.py` | add | `InstructionInput`, PreparedInstructions, and Provider Protocol |
| `.../agent_execution/registry/adapter_registry.py` | modify | Metadata registration/exact lookup; preserve factory and fresh-Adapter semantics |
| `.../agent_execution/capability/{ports,resolver,cache,warmer}.py` | add | TrustedDeploymentProbe, TrustedPolicyProvider (with `current_revision`, R-17), Available/Policy/Effective resolution, caches, and the controlled background warmer |
| `.../agent_execution/instructions/{react,test}_provider.py` | add | React-native messages and an independent test format; test Provider stays out of production registration |
| `business_capabilities/agent_config/service.py` | modify | New AgentConfig fields, canonical diff, draft/publication validation, and read-only history |
| `core_platform/agent_runtime/repository.py` | modify | One-time five-snapshot write; preserve claim/terminal ordering |
| `core_platform/agent_runtime/schemas.py` | modify | Private DTO wiring only; public RunRequest remains strict with no capability/policy fields |
| `agent_execution/orchestration/{execution_context,orchestrator}.py` | modify | Configuration selection, capability/Provider/snapshot preparation, and Adapter.start barrier |
| `agent_execution/adapters/react/adapter.py` | modify | Consume prepared input without second business rendering; preserve gate/ack/cancel |
| `applications/platform_runtime/{runtime_factory,runtime_composition}.py` | modify | Compute system prompt once, inject resolver/Providers, and wire both flags |
| `core_platform/agent_runtime/worker.py` | modify | Four-state matrix: off retains original paths; on+orchestrator-off fails closed |
| `applications/customer_service/platform_routes.py` | modify | Strict `POST /agents/execution-preview` request, allowlisted response, and scope; add the read-only `GET /agents/execution-config-flags` contract (§7.4) |
| `frontend/src/shared/api/client.ts` | modify | Engine/React/disabled/preview types and API helper |
| `frontend/src/features/agents/AgentsPage.tsx`, `agents.css` | modify | Retain current sections; extract only modest `ExecutionConfigSection`/`CapabilityPreview` components if needed |
| `frontend/src/i18n/locales/{zh-CN,zh-TW,en,hi}.json` | modify | All forms, reasons, and errors in four locales |
| `frontend/tests/agent-execution-config.spec.ts` | add | Targeted Playwright M1–M3/forgery/read-only/four-locale evidence |

## 3. ExecutionConfig, Aliases, and Canonical Diff

### 3.1 Data model

```text
ExecutionConfig (strict, frozen, extra=forbid)
  engine: EngineIdentity { engine_id, protocol_id, adapter_version }
  react: ReactConfig | null
  disabled_capabilities: tuple[CapabilityName, ...] = ()
ReactConfig (strict, frozen)
  model_profile_id: UUID | None
  model_profile_version: int | None
  max_model_rounds: PositiveInt  # retain current bounds
```

- Missing `engine` defaults in memory to `(react,native,v1)`; explicit non-React cannot carry `react` configuration.
- `ExecutionConfig` contains only publishable, auditable configuration, not Declared/Available/Policy/Effective, probes, tenant/actor, or host information.
- Extend `AdapterDescriptor` with `config_schema`, `declared`, `declared_schema_version`, `probe_id/probe_version`, `policy_provider_id/policy_version`, `instruction_provider_id/provider_version`, and `config_schema_version`. Exact `metadata(engine,protocol,version)` rejects disabled/unknown identities.
- Draft/publication/preview uses metadata schema validators; neither registration nor metadata lookup invokes a factory. Execution still resolves a fresh Adapter and may compare instance declarations with registered metadata before start, failing closed on divergence.

### 3.2 One legacy normalizer

1. Strictly parse existing shared AgentConfig fields, then extract legacy root model aliases and new `react`.
2. Use React defaults if both are absent, the present value if only one exists, and one canonical value if both are semantically equal; unequal values produce a field-path conflict.
3. Retain existing ID/version pairing, rounds, model Profile/tool/knowledge/tenant checks; compatibility never bypasses them.
4. Return a new object without mutating input dict/model; GET, rollback views, diffs, and normal background reads never persist.
5. Persist canonical configuration only when the user explicitly saves the new shape; merely editing an old draft must not create a default-triple change. This clause constrains semantic "change" (criterion: canonical diff/audit shows no default noise, per §3.3 and P3-IT-01), not the key set chosen by the client PUT body: the frontend may write minimally—touching only alias locations already present in the draft (root alias stays root alias, a present `react` object is kept in sync), never fabricating `engine` or `react` keys for old drafts and omitting an empty `disabled_capabilities`; the server still stores the canonicalized body, which is frozen T3 behavior and is not itself a "default-triple change". Neither side may read this as "any edit must fabricate engine/react" nor as "the server must persist legacy shapes verbatim"—the first manufactures alias conflicts, the second reopens T3 (pinned by 08 R-24).

### 3.3 Canonical diff

Normalize both diff sides into semantic views, then suppress only Phase 3 default additions: `engine=react/native/v1`, empty `disabled_capabilities`, and React defaults equivalent to legacy roots. Preserve real value changes, added disabled capabilities, and explicit non-React. Never globally strip defaults to hide changes; original published JSONB remains unchanged.

## 4. Capability Resolution, Trusted Ports, and Caches

### 4.1 Four types

| Type | Content/source | Constraint |
|---|---|---|
| `DeclaredCapabilities` | Registry 11 `EngineCapabilities`, declaration schema/version, exact triple | Trusted registered code; client cannot override |
| `AvailableCapabilities` | Per-item `{available,reason_code}`, probe id/version, observed_at, deployment/declaration digest | `available ⇒ declared`; raw probe output never enters snapshots/API |
| `PolicyDecisionSet` | Per-item/layer `{allowed,source,reason_code}`, platform/tenant/agent/execution policy versions/revisions | Trusted sources only; decisions only narrow |
| `EffectiveCapabilities` | Per-item `{effective,reason_code}`, resolved policy/declaration/probe version digests | `effective = declared ∧ available ∧ platform ∧ tenant ∧ ¬agent_disabled ∧ execution_allowed` |

Unknown capability names are schema/policy errors, not ignorable set entries. The platform ceiling grants the minimum by default; absent tenant/Agent/Execution policy cannot enlarge it. Stable reasons distinguish at least `not_declared`, `probe_unavailable`, `probe_timeout`, `probe_stale`, `workspace_unavailable`, `platform_denied`, `tenant_denied`, `agent_disabled`, `execution_denied`, and `policy_unavailable`; public responses expose only safe reasons.

"Required capability missing" (start-blocking) is limited to capabilities with declared=true whose final reason lies in the deployment/trusted-infrastructure unavailability class: `probe_unavailable`, `probe_timeout`, `probe_stale`, `workspace_unavailable`, `policy_unavailable` (including unavailable produced by cold/unwarmed or expired cache); these fail closed run admission (FR-2 "unavailable configuration must not be published or started", FR-3 failure handling, FR-4 "missing/untrusted policy grants only the minimum"). `not_declared` and the policy-layer narrowings `platform_denied`, `tenant_denied`, `agent_disabled`, and `execution_denied` are expected monotonic narrowing under FR-4/AC-4; they do not by themselves constitute a required-capability missing and never block start—such capabilities simply remain Effective=false with source, version, and reason recorded in snapshots. Until a controlled policy defines an explicit required subset, the full declared=true set is treated as required.

`workspace_required=true` with missing/unavailable trusted Workspace availability makes Adapter/run admission unavailable; Phase 3 neither creates a Workdir nor pretends Workspace exists. `disabled_capabilities` only changes true to false and cannot enable Declared=false or an upper-layer false.

### 4.2 Ports

```text
TrustedDeploymentProbe.probe(ProbeContext) -> ProbeResult
TrustedPolicyProvider.current_revision(PolicyRevisionScope) -> int
TrustedPolicyProvider.resolve(PolicyContext) -> PolicyDecisionSet
WorkspaceAvailabilityPort.current(WorkspaceScope) -> AvailabilityGeneration
```

Composition injects trusted implementations; request DTOs cannot supply probe/policy instances, URLs, policy versions, or results. ProbeContext contains only deployment identity, exact triple, adapter/config/probe versions, declaration digest, and Workspace scope/generation. Probes have timeout/concurrency bounds, start no external Engine, and emit no secrets. This phase assumes no existing circuit-breaker infrastructure; any backoff belongs only to the controlled background scheduler.

**Trusted entry point for the policy revision (R-17)**: `policy_revision` is a current observation from the trusted policy source, not caller input, so `CapabilityResolutionRequest` carries no such field. Whenever the resolver builds a Policy/Effective key and a PolicyContext it reads `current_revision(scope)` from the same injected `TrustedPolicyProvider`; that read is peer to `WorkspaceAvailabilityPort.current`—synchronous, local, no remote I/O, and allowed on the synchronous hot path. **The Availability key is built through the same fresh-read path (sharing one round's observation with the Policy key), so a policy-source failure fails the whole round fast—raising `PolicySourceUnavailableError` even for Available resolution. This is intentional, not an oversight: it guarantees that within one round the key, the loader, the echo validation and the Effective provenance all use the same revision value, preventing a revN+1 result from being stored under a revN key when the revision advances mid-round. T7 must not treat `availability_cache_status` as a diagnostic entry point independent of the policy source.** The value must be monotonic per scope and `resolve()` must echo the revision read in the same round; a divergent echo raises `_PolicyMismatchError`, the cache records an error state, later hot reads synthesize `policy_unavailable` (a required-capability-missing reason under R-16, failing closed), and the next bounded round self-heals. A raising revision read makes the resolver raise `PolicySourceUnavailableError`, which preview and run admission map to the stable `execution_policy_unavailable`; defaulting to `0` is forbidden. In Phase 3 the platform default provider has no versioned tenant policy data, so returning a scope-stable value is a compliant implementation; the §4.3 "policy revision changes invalidate entries" clause is honoured by this mechanism rather than by TTL alone. `execution_restriction_digest` is computed server-side by composition via `contracts/capabilities.py:execution_restriction_digest(values)` (same canonical form as `disabled_capabilities_digest`); Phase 3 has no restriction source and always passes the empty-set constant `NO_EXECUTION_RESTRICTIONS = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"` (i.e. the actual computed value of `execution_restriction_digest(())`; if the canonical form ever changes, this literal must change in lockstep and be pinned by a test). Providers never echo this digest, so it is outside identity validation.

**Constructor-parameter sources (R-18/R-19/R-20)**: probe/policy timeouts, probe concurrency, cache capacity, retry interval, warmer refresh cadence and deployment identity all come from the FR-9 `execution_capability_*` settings; composition must not invent hardcoded constants. The `*_cache_seconds`, `*_retry/refresh_seconds` bounds match `CapabilityCache`/`CapabilityWarmer` requirements (`ttl_seconds > 0`, `retry_interval_seconds > 0`, `capacity >= 1`), so invalid configuration fails closed at the settings layer. `execution_capability_policy_version` is consumed by composition as both the `AdapterDescriptor.policy_version` and the version of the policy provider it registers.

**Initial population and lifecycle**: at composition startup, create probe/policy cache entries for every enabled exact triple and let a controlled background warmer perform the first probe. The warmer calls only trusted ports, writes sanitized Available DTOs, and creates no Adapter/Run. Application readiness need not wait for every external probe, but Available remains false until a valid value is stored. The warmer subsequently refreshes before TTL expiry; failures retain explicit stale/error state rather than treating old values as fresh authorization, with bounded retry intervals. Run and preview synchronous hot paths only read cache; miss/stale returns unavailable and schedules a deduplicated background refresh, never a remote probe inside the request. Test composition uses the same lifecycle interface with deterministic probe/policy doubles and a fake clock to control initial population, refresh, expiry, and shutdown, covering unavailable-before-warm → available-after-success → unavailable-after-expiry. Application shutdown cancels the warmer and tests leak no background tasks.

### 4.3 Cache keys and invalidation

- **Available key**: `deployment_identity + engine triple + adapter_version + config_schema_version + probe_id/probe_version + declaration_digest + workspace_availability_generation`.
- **Policy/Effective key**: the identity/declaration/probe digest above + `tenant_id + business/workspace scope + agent_id + published_version + policy_provider_id/policy_version/policy_revision + disabled_capabilities_digest + trusted_execution_restriction_digest` (with `policy_revision` read fresh via §4.2 `current_revision`, not supplied by the caller, R-17).
- Caches store only sanitized DTOs with TTL, capacity bounds, and per-key singleflight. The synchronous hot path never waits on unbounded remote calls; miss/stale/error makes Available false, and unknown/untrusted Policy fails closed.
- **The Available cache value is pre-narrowing (R-22)**: the Available key carries `workspace_availability_generation` but no tenant/scope (existing ruling retained), so a cached value is the raw deployment observation and `_narrow_workspace` happens only on the read path. Every snapshot, `ExecutionRequest`, audit or preview evidence constructor must consume `CapabilityResolution.available/effective` (already narrowed) and must never read `CapabilityCache.lookup(...).value` directly; snapshot constructors take a `CapabilityResolution` parameter, which is itself the gate. A bypass produces the contradictory evidence "available=true without a trusted Workspace" and is a P1 defect.
- Registration/declaration/probe-version changes replace identity keys; platform/tenant policy revisions invalidate relevant tenant/scope entries through the §4.2 `current_revision` read, not through TTL (R-17); Agent publication/disabled and Execution restriction changes naturally change keys; Workspace generation changes affect only relevant Available/Effective. Preview never writes decisions into Run authorization cache, and execution reevaluates current versions.
- **Runtime fingerprint decision**: following the `execution_orchestrator_enabled` precedent, `execution_phase3_enabled` is **not part of the fingerprint**. Composition may retain side-effect-free resolver/cache objects; Worker reads both current flags once at the start of each claimed Run and fixes that Run's path. Off/on transitions require no Runtime rebuild and never change legacy claim semantics. A mid-run flag change does not recompute the fixed path; startup identity guarantees snapshot consistency and cache reuse cannot rewrite policy. T7 adds cached-Runtime regressions for off→on, on→off, on+orchestrator-off, and already-claimed rows.

## 5. Five Snapshots and the Start Barrier

### 5.1 DTOs and columns

| Snapshot DTO | Planned column | Minimum content |
|---|---|---|
| `ExecutionConfigSnapshot` | `execution_config_snapshot` | schema_version, Agent/version, Engine triple, canonical config, provider id/version |
| `DeclaredCapabilitiesSnapshot` | `declared_capabilities_snapshot` | schema_version, Engine triple, declaration version/digest, 11 declarations |
| `AvailableCapabilitiesSnapshot` | `available_capabilities_snapshot` | schema_version, per-item available/reason, probe id/version, observed_at, digest |
| `EffectiveCapabilitiesSnapshot` | `effective_capabilities_snapshot` | schema_version, per-item effective/reason, related declaration/probe/policy versions |
| `ExecutionPolicySnapshot` | `execution_policy_snapshot` | schema_version, layered decisions, trusted source IDs, policy version/revision, disabled/restriction digests |

All five JSONB columns are nullable; NULL on old rows means pre-Phase 3. DTOs are strict/frozen, explicitly versioned, and have no unrestricted extension dictionaries. They exclude raw Summary/Memory, full user input, model responses, API Keys/Tokens, connection strings, stderr, plaintext secret references, and internal host paths.

### 5.2 Recursive denylist and size

Scan every path in nested dict/list/tuple/DTO structures. Normalized keys reject at least `password/passwd/secret/token/access_token/refresh_token/api_key/apikey/authorization/cookie/credential/private_key/connection_string`, plus explicit business fields `customer_memory/summary_message/raw_memory/stderr/host_path/workdir_path`. Top-level deletion is insufficient. Ordinary words in strings need not false-positive, but credential-shaped values or marked sensitive paths must fail. Errors return only field paths/stable codes, never values.

Canonicalize each of the five independently and calculate UTF-8 bytes; each must fit `execution_snapshot_max_bytes` (default 65536), rather than sharing one total. Unserializable values, denylist hits, excess size, and missing versions/required fields all fail closed. After producing the canonical text, serialization **runs a second strict DTO validation on that text** (`type(snapshot).model_validate_json(canonical)`): `frozen=True` blocks attribute assignment but not `model_copy(update=...)`, and the completeness/coverage invariants only run at construction, so this revalidation is the required second gate—bypassing validators via `model_copy` must never become a write path. The check runs after the denylist and JSON generation, so unserializable inputs still report "not serializable" as before, and revalidation leaves the canonical bytes unchanged (repeat serialization stays byte-identical).

Two intentional narrowings (frozen):

- The value-side host-path rejection applies to **every** string value, not only to matched key names. This is deliberate strictness: among the five snapshot DTOs the only format-free string field is `EffectiveCapabilitiesSnapshot.tenant_id`, while the rest (Slug/EngineId/AdapterVersion/DigestString) have grammars that already disallow a leading separator, so "reject values starting with `/`" cannot kill legitimate payloads; negative controls cover this repository's real tenant/workspace identifier shapes plus URLs, relative paths, and CJK business text.
- Read-only decision replay provides a **semantic** guarantee (strict revalidation + payload identity consistency + comparison against the canonicalized form), **not byte-level tamper detection**: PostgreSQL `jsonb` re-encodes key order and whitespace, so a byte comparison would reject legitimate read-backs; the comparison target is the canonicalized form rather than the raw stored bytes, and byte-level audit integrity would require a separate checksum/column outside Phase 3 scope. The replay entry accepts both `str | Mapping` shapes (`Repository.get` returns decoded dicts), and its error codes distinguish "absent" from "wrong type"—a type misuse must never be reported as a missing payload.

### 5.3 Ordering and write-once behavior

1. Existing Repository.claim still marks the Run running and publishes `run.started` first, preserving Phase 2 public compatibility.
2. On Phase 3 on+orchestrator-on, Worker/Orchestrator reads published configuration and current trusted Available/Policy, then builds five DTOs and PreparedInstructions. The four capability snapshots (Declared/Available/Policy/Effective) are built only from a `CapabilityResolution` (R-22); `ExecutionRequest.effective_capabilities` is derived from the same resolution by the single §7.2 projection, and reason codes are never reconstructed from raw cache values or the degraded view.
3. After validation, denylist, serialization, and size checks, write all five to one Run in a short transaction. Require all columns still NULL or `ExecutionConfigSnapshot.execution_id` equal to this startup identity, preventing retry/concurrency overwrites. Reuse `ExecutionContext.execution_id` as startup identity, store it in the configuration snapshot, and correlate the other four through the same field; **add no sixth column or separate token column**. The identity invariant is enforced by **two gates at once**: the entry guard requires `payloads.execution_id == run_id` **and that each of the five payload bodies also carries `execution_id == str(run_id)`** (defending against an honest guard argument with forged bodies), returning `audit_conflict` **without touching the database** on mismatch; the SQL predicate binds `execution_config_snapshot->>'execution_id'=:execution_id` on both branches, so even a caller that skipped the entry guard cannot aim a row at another run. The "same identity, verify and reuse" comparison means **PostgreSQL `jsonb` value equality (semantic equality)**, not byte equality. The write returns a controlled classification `SnapshotWriteResult.outcome ∈ {written, reused, audit_conflict, not_claimed, lease_lost}` (label only, never payload content); see 08 T7 wiring discipline for the caller mapping.
4. **Successful DB commit is the hard barrier to `Adapter.start`**. Any failure uses existing failed terminal/error handling, with zero Adapter.start, runner, or RuntimeFactory model/tool assembly.
5. Completion, failure, cancellation, lease loss, timeout, and late results never update the five columns. A retry with existing snapshots may only verify/reuse identical values (equality as above: `jsonb` semantic equality), never rewrite under new policy; divergence fails with `audit_conflict`.
6. Public Run/detail/SSE/preview responses never expose the columns. Authorized internal audit uses separate field allowlists; this phase adds no public snapshot endpoint.

## 6. Instruction Provider and React Compatibility

```text
InstructionInput (strict, frozen)
  engine: EngineIdentity
  agent_id, agent_version
  system_prompt: str                  # platform+Agent+reply-language rule computed by RuntimeFactory
  history: tuple[ConversationMessage, ...]  # already retained by existing policy
  current_user_input: str
  summary_message: str | None         # already rendered by Worker
  customer_memory: str | None         # already rendered by Worker
  engine_context: Mapping[str, Scalar] # controlled non-sensitive placeholders only; no Skill/Workdir
InstructionProvider.prepare(InstructionInput) -> PreparedInstructions
PreparedInstructions { provider_id, provider_version, payload }
```

- RuntimeFactory computes the effective system prompt once before the runner; Worker Summary/Memory results pass directly, and Providers never query Memory or change switches/budgets/text.
- React Provider yields structured input equivalent to `RuntimeEngine.run`: System → optional Summary System → optional Memory System → kept history → current Human; empty values create no empty messages.
- Existing history truncation, Summary switch, no-empty behavior, completion history/dropped, logs, and post-completion Memory write-back remain unchanged and are not repeated by the Provider.
- A test Provider returns an independently assertable native format only in test composition, proving one business-rendering pass and no forced ReAct conversion.
- Orchestrator calls `ReactAdapter.start` only after Provider preparation and snapshot commit. After the existing `_Execution`/asyncio runner creation point, the Adapter only consumes Engine-formatted input. Unknown Providers, duplicate rendering, and contract errors fail before start.
- Preserve dual emit, structured ack, backpressure, private Outcome, cancellation gates, and public Run/SSE semantics.

## 7. Preview HTTP Contract

### 7.1 Route and authorization

`POST /api/v1/agents/execution-preview` uses existing `applications/customer_service/platform_routes.py` and authenticated internal-management dependencies. It is not Open Platform and adds no external service/Postman publication. Reuse existing Agent read permission within Reader/Admin; write permission controls save/publish only, and preview never modifies data.

Strict request (`extra=forbid` at every layer):

```json
{
  "agent_id": "7b8f…optional or null",
  "config": {
    "system_prompt": "…",
    "engine": {"engine_id":"react","protocol_id":"native","adapter_version":"v1"},
    "react": {"model_profile_id":null,"model_profile_version":null,"max_model_rounds":6},
    "disabled_capabilities": ["terminal_execution"]
  }
}
```

`config` uses the complete AgentConfig draft contract (existing shared fields omitted in the example) and supports unsaved edits; `agent_id=null` previews a new draft. When supplied, load the ID under authenticated tenant + business/workspace scope and verify draft ownership. Cross-tenant/scope uses existing not-found behavior rather than merely hiding fields.

Reject `declared`, `available`, `effective`, `effective_capabilities`, `policy`, `policy_version`, `probe`, `tenant_id`, `actor`, host/Workspace internals, and all unknown fields; never ignore and continue. Compute only from registered metadata, trusted ports, and authenticated context.

### 7.2 Response

```json
{
  "engine": {"engine_id":"react","protocol_id":"native","adapter_version":"v1"},
  "config_schema": {"schema_version":"v1","fields":[{"name":"max_model_rounds","type":"integer","required":true}]},
  "capabilities": [
    {"name":"streaming","effective":true,"reason_code":"allowed"},
    {"name":"terminal_execution","effective":false,"reason_code":"agent_disabled"}
  ]
}
```

The strict response is also allowlisted. `config_schema` contains only public field names/types/required flags/safe bounds, not secrets or paths from internal JSON-schema descriptions. Return Effective and stable reasons for all 11 capabilities, never raw Declared/Available/Policy, five snapshots, raw probes, policy rules, internal IDs, or paths. Probe failure means `effective=false` with a stable reason, never successful availability.

The preview `capabilities` array is exactly `EffectiveCapabilities.items`, produced by the single projection `effective_capability_views(resolution.effective)`: fields fixed to `name/effective/reason_code` (reusing the existing strict DTO `EffectiveCapabilityDecision`, no new response model), all 11 entries present, ordered by `CAPABILITY_ORDER` (R-21). Run-side `ExecutionRequest.effective_capabilities` is produced only by `effective_capability_flags(effective)` from the same module—always 11 keys, false entries never omitted. Both projections must consume one and the same `EffectiveCapabilities` instance; T7/T8 may not inline dict comprehensions, reorder, trim, or reconstruct reason codes from the degraded view.

### 7.3 Errors and side effects

| Condition | Behavior |
|---|---|
| Phase 3 off | Stable `execution_phase3_disabled`; no probe or Adapter instantiation |
| Schema/type/extra/forged input | Existing 422 style with field paths and no sensitive echo |
| Missing/cross-scope Agent | Existing 404 domain behavior without revealing another tenant's existence |
| Unknown/disabled triple | Stable `execution_engine_unavailable` (or existing equivalent DomainError, fixed during implementation) |
| Registry schema/Provider/Policy configuration error | Stable `execution_configuration_invalid` / `execution_policy_unavailable`, without authorization fallback |
| Individual probe failure/timeout | 200 preview with that capability unavailable/stable reason; overall resolution failures use domain errors |

Preview invokes no factory/`resolve`, creates no Run, Conversation, snapshot, Memory task, or Adapter, and caches no future Run authorization. Execution rereads the published version and current trusted policy.

**422 is not a security audit**: the current global RequestValidationError handler in `applications/application_factory.py` only returns 422. T8 must add testable audit wiring for forged fields and unauthorized attempts across Run/Agent/preview, preferably reusing the existing audit service and trusted authenticated context, optionally through a minimal route/field-path-aware hook in that handler. Record only timestamp, trusted tenant/actor/scope, route, request ID, error category, and sanitized field paths—**never request bodies, field values, Authorization/Cookie, or secrets**. P3-IT-04 must query audit records directly rather than merely asserting 422.

### 7.4 Phase 3 flag read-only contract

`GET /api/v1/agents/execution-config-flags` sits beside the preview endpoint in `applications/customer_service/platform_routes.py` on the same authenticated internal-management surface (`Reader` read permission—viewers must also render per the flag, hence not Admin) and is not Open Platform. There are no request parameters and no body; the response is a strict DTO (`extra=forbid`, frozen, exactly two booleans whose names are verbatim the settings keys):

```json
{
  "execution_phase3_enabled": false,
  "execution_orchestrator_enabled": true
}
```

The endpoint exists so the frontend satisfies 05 M3 ("Phase 3 editing entries disabled/hidden in line with the flag") declaratively rather than by error inference—error inference can only express "tried and failed", cannot express "hidden before any attempt", and cannot distinguish off from the on + orchestrator-off misconfiguration. The precedent is the existing `GET /agents/memory-config-caps`, which likewise exposes tenant-agnostic deployment switches to Readers. Discipline:

- Read only the two booleans from `runtime(request).settings`; never consult the capability cache, start a probe, call any remote port, instantiate an Adapter/factory, create a Run/Conversation/snapshot, trigger the warmer, or write audit (a cache read would couple the endpoint to the Phase 3 subsystem lifecycle and make it unreadable on cold/off deployments). It must answer normally with Phase 3 entirely off—that is precisely its purpose—and must never return `execution_phase3_disabled` or other execution_* domain errors; authentication failures follow the existing 401/403.
- Expose the two raw flags rather than a synthesized view: a synthesized field would replicate the FR-9 four-state matrix server-side, drift from the frontend, and collapse "normal rollback off" into "misconfiguration"; ops hints must cite setting names verbatim from `backend/.env.example`. The UI-side matrix combination lives in §8; the authoritative evaluation remains server-side.
- Security boundary: the two booleans are non-secret, tenant-agnostic deployment configuration at the same confidentiality level as the already-exposed `summary_enabled` family, contain no bodies/tokens/keys/raw Memory/host details, and do not violate C3; every authenticated tenant receives identical values with no per-tenant data surface or cross-scope query, so C4 is not violated. No other `execution_capability_*` tuning settings, internal IDs, digests, policy/probe payloads, or schema_version are returned.
- OpenAPI includes the route automatically like any internal route; the response is deterministic and the frontend fetches it once per editor lifecycle. Pinned by 08 R-25; implemented in T8, consumed in T9.

## 8. Frontend and Observability

- Add Engine and React configuration blocks to the existing AgentsPage, reusing `AgentModelPicker`, antd Form, and `agents.css`; extract at most one or two colocated components if complexity warrants, with no new design system.
- US-1's "select a supported Engine/Protocol" is, under Phase 3's single legal triple, implemented as a read-only presentation: the draft's effective triple (default `react/native/v1`) with a registered/unregistered status Tag; the frontend candidate set is a constant equal to the production Registry's legal set, there is no Engine catalog endpoint, and no free-form input is offered (this form is the compliant implementation of US-1/§8, pinned by 08 R-23 and not revertible). Genuine multi-candidate selection becomes a requirement only when non-React Engines enter production registration in Phase 4/5 (04 P3-CM-10), and its source must then be Registry metadata rather than frontend enumeration. The read-only presentation does not relax FR-2: unregistered or non-React triples remain precisely rejected server-side on save/publish/preview/Run, the Tag is a presentation hint rather than validation, and display convenience must never introduce `latest` or automatic cross-Engine switching.
- Continue existing draft/publication/diff flows; canonical defaults do not create dirty state, and old Agents require no forced fields or republication.
- “Preview capabilities” explicitly POSTs current unsaved config; results are read-only Effective/reasons. Disabled items only add to `disabled_capabilities`; expose no Declared/Available/Policy editor or Run authorization.
- The frontend gates declaratively from `GET /agents/execution-config-flags` (§7.4) instead of inferring the flag by clicking into an error: with `execution_phase3_enabled=false` it hides the Phase 3-only editing entries (the "preview capabilities" button and result panel, the `disabled_capabilities` narrowing checkboxes) and shows a "Phase 3 not enabled" hint; the read-only Engine display is not an editing entry and may remain visible (hiding the whole card is equally compliant). When `execution_phase3_enabled=true && execution_orchestrator_enabled=false` (the FR-9 misconfiguration) it keeps the read-only display, shows a deployment-misconfiguration hint, and never presents a fake success; if the flags read fails, Phase 3-only entries stay hidden (fail closed) but the UI must **not** show the "Phase 3 not enabled" hint—a failed read is not proof of off, and reporting it as such would be a new kind of misleading; the read follows the `memory-config-caps` precedent (interface plus one page-level `useResource`), with no extra fetch helper invented. React model/round editing, the save/publish/diff flow, and historical publication/Run viewing are **never** gated by these flags—off + orchestrator-on must preserve the original Phase 2 React path exactly (FR-9/AC-10), and disabling them would itself be a violation. New hint copy goes into all four locales.
- Viewer remains read-only and the backend remains authoritative. Put every label, reason, error, and help string into `zh-CN`, `zh-TW`, `en`, and `hi` JSON; no hardcoding.
- Use existing Playwright mocks for `/api/v1/**`, covering M1–M3 or equivalent evidence, forged-request absence, and four locales; add no component-test runner.
- OpenAPI automatically includes the internal route. Audit records Agent/version, Engine, provider/policy/probe versions, and outcome summaries without secrets, raw Memory, or host paths. Metrics cover cache hit/miss/stale, probe timeout, resolution latency, snapshot rejection, and start-barrier failure.

## 9. Migration, Rollout, and Rollback

### 9.1 Migration

Plan `0058_agent_execution_metadata`, currently following `0057_industry_pack_runtime`. T2 first runs `uv run --directory backend alembic heads` for dynamic revalidation; if the target head changed, update every bilingual document and 08 before implementation. Add only five nullable JSONB columns, with no default backfill, historical UPDATE, or existing-sequence rename. Test downgrade only on a disposable database; production rollback never depends on it.

PostgreSQL integration defaults to an independent pgvector container. Alembic reads `AGENT_DATABASE_URL`, while pytest reads `TEST_DATABASE_URL`. Keep random container credentials only in a mode-600 environment file, never in repository/documents/reports. Load that environment, explicitly assign the test URL to `AGENT_DATABASE_URL`, and set a temporary `AGENT_API_TOKEN`. Connection misconfiguration is an environment issue, not a product defect or pass.

### 9.2 Rollout order

1. Deploy the additive migration; old binaries keep reading/writing because they do not reference the nullable columns.
2. Run new binaries with `execution_phase3_enabled=false`, preserving the original Phase 2 path selected by the deployment's current `execution_orchestrator_enabled`.
3. Validate metadata, probe/policy, snapshots, preview, React parity, and C11 in dedicated tenants, then enable Phase 3 only where the Orchestrator is already on.
4. `execution_phase3_enabled=true && execution_orchestrator_enabled=false` is misconfiguration: health/startup validation and Runs fail closed rather than silently enabling legacy.
5. Roll back by disabling Phase 3; off rejects non-React explicitly. Legacy React returns to the deployment's original Phase 2 path, historical columns remain read-only, and application rollback needs no database downgrade.

### 9.3 Post-completion seed and quickstart

Only after real `06-test-report*` and `07-acceptance-report*` exist: add an independent low-sensitivity, deterministic-ID, create-or-preserve idempotent `seed_execution_phase3.py`-style example without fabricated snapshot evidence. Then separately wire fresh quickstart to run it automatically and verify off/on/rollback plus real Run snapshot generation. Append evidence only to existing 06/07; production never auto-inserts examples.

## 10. Requirements Traceability

| Design | FR | AC | Primary verification |
|---|---|---|---|
| ExecutionConfig/normalizer/metadata/canonical diff | FR-1, FR-2 | AC-1, AC-2 | P3-UT-01–05, P3-IT-01/02/16, P3-CM-05 |
| Four capability layers, trusted ports, caches, least privilege | FR-3, FR-4, FR-5 | AC-3–AC-5 | P3-UT-06–12, P3-IT-03–05/11, P3-CM-04/07 |
| Five DTOs, denylist, size, one-time commit barrier | FR-6 | AC-6, AC-11 | P3-UT-13–15, P3-IT-06–08/14/15, P3-CM-01/06 |
| InstructionInput/React/test Provider | FR-7 | AC-7, AC-8 | P3-UT-16–19, P3-IT-09/10 |
| Preview, flags read-only contract, AgentsPage, four locales, audit, flag matrix | FR-5, FR-8, FR-9 | AC-5, AC-9, AC-10 | P3-UT-26, P3-IT-04/05/11–13/20, P3-CM-02–04/08/09; M1–M3 |

Do not prewrite test or acceptance outcomes. Keep environmental gaps, real-history samples, CI/production performance, and human evidence as `pending_env`/`not_measured`; never remove hard gates to obtain a pass.
