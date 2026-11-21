# Codex ModelGateway Integration and Execution Config Hardening — Design

Status: proposed for issues #165–#168 (Q1, Q2, Q3, Q5 follow-up from the P7
Clean Image Probe / Stage A acceptance round).
Scope: backend execution contracts, ModelGateway catalogue, Codex CLI adapter,
Agent publish validation, frontend Agent execution configuration.

## 1. Findings that drive this design

### 1.1 Why Q1 produced `execution_error`

The P7 published agent carried `codex.credential_ref = 00201ea3-...`. That UUID
returns 404 from `GET /execution-credentials/{ref}`. At run time:

1. `CodexCliAdapter.start` parses the reference and asks `RuntimeHost.start` to
   issue a Broker grant.
2. `ExecutionCredentialBroker.issue` denies with `credential_not_found` by raising
   `CredentialGrantDenied`, a plain `RuntimeError` (`credentials/broker.py`).
3. `RuntimeHost.start` re-raises it raw. It is **not** an `AdapterExecutionError`.
4. `ExecutionOrchestrator._safe_legacy_code` therefore falls through to the
   sanitized legacy code `"execution_error"`.
5. `Conversations.tsx` renders the raw code, which has no i18n entry.

So `execution_error` is not a model/network failure and not a Stage-A gate
failure. It is an **unclassified configuration refusal** caused by a stale
credential reference that nothing validates before publication. Today there is
no existence, `status=active`, `allowed_engines`, or `allowed_workspaces`
validation at save/publish time; the Broker is the first and only place that
checks, after the agent has already been published.

### 1.2 Why Q2 has no good answer today

A valid `credential_ref` is a **UUID minted by the admin-only credential API**,
not something a user can invent or that the platform can auto-generate:

| Item | Location |
| --- | --- |
| API that creates it | `POST /api/v1/execution-credentials` (admin only) |
| Field holding the UUID | `credential_ref` in `public_metadata()`; DB column `execution_credentials.credential_ref` |
| Validity conditions | `status='active'`, `allowed_engines` contains `codex`, `allowed_workspaces` contains the run workspace, secret decryptable with the installation key |
| Where it is consumed | `AgentConfig.codex.credential_ref` in `agents.draft` / `agent_versions.config` |
| Consumer at run time | `ExecutionCredentialBroker.issue/consume` |

There is **no frontend UI** for creating credentials, and the Agent form exposes
a **free-text UUID input**. A user must call an admin API out-of-band and paste
the returned UUID. A typo, a rotated/revoked record, or a wrong-scope record all
publish cleanly and fail only at run time. This is the design defect, not a user
error.

### 1.3 Why Q3 is bound to DeepSeek

`CodexEngineHomeConfig` is built exclusively from four deployment-global
`Settings`: `codex_model`, `codex_model_provider`, `codex_model_base_url`,
`codex_credential_env_key`, with `WIRE_API = "responses"` as a module constant.
`CodexConfig` has no model/provider fields, and `AgentService.validate_model`
explicitly skips Gateway resolution for non-React engines. The Gateway is an
**outbound** client (`/model-gateway/invoke` uses a proprietary envelope); it
has no inbound OpenAI-compatible endpoint that a `codex` binary could use as a
`base_url`.

### 1.4 Why Q5's PATH field is misleading

`codex.path_env` is stored per published Agent, while `settings.codex_path_env`
(`AGENT_CODEX_PATH_ENV`) is declared and exported in compose but **never read by
any runtime source**. The customer form therefore edits the only effective
value, and the deployment switch is dead configuration.

## 2. Architecture decision for Q3

**Decision: drive the Codex provider from the ModelGateway catalogue, keeping the
Codex CLI pointed at the resolved upstream provider.**

`codex` is an external binary. It needs an OpenAI-compatible HTTP endpoint as
`base_url`; it cannot call `ModelGateway.invoke()` directly, because that is a
proprietary JSON envelope and ModelGateway currently exposes no inbound
`/chat/completions` or `/responses` route. Building an inbound Responses-API
facade (a translation layer from Responses to chat completions, plus streaming
SSE, tool calls and reasoning) is a separate, substantially larger programme
with real protocol-compatibility risk against the pinned 0.169.0 binary.

What the platform *can* own today, and what the user actually asked for — "full
access to the models and providers supported in ModelGateway, not hardcoded to
DeepSeek" — is the **selection and validation of the model/provider**. This
design makes ModelGateway the single source of truth for that selection:

- A Codex Agent binds a **ModelGateway chat profile**
  (`codex.model_profile_id` + `codex.model_profile_version`). Every connection,
  model and published profile in the Gateway catalogue becomes selectable,
  including all seeded providers and any custom `openai_compatible` connection.
- The Gateway **connection** carries the Codex-specific transport metadata and
  the credential binding: `codex_base_url`, `codex_wire_api`,
  `codex_model_provider`, `execution_credential_ref`.
- At run time a resolver reads the **published profile snapshot via
  `ModelCatalog.resolve()`**, takes the primary route, validates the address
  against `model_gateway_allowed_hosts`, and builds a per-run
  `CodexEngineHomeConfig`. No DeepSeek constant participates in this lane.
- The secret still travels through the fail-closed `ExecutionCredentialBroker`
  into exactly one child env slot. `OPENAI_API_KEY` is the neutral slot name;
  the value is the provider's real key held in `execution_credentials`.

### 2.1 Compatibility lane (mandatory)

Existing published agents (including the acceptance host's P7 probe) have no
`model_profile_id`. When the pair is absent, the adapter keeps the legacy path:
deployment-global `Settings` + `codex.credential_ref` + `codex.path_env`. No
published snapshot becomes unparseable and no live agent regresses. New fields
are additive with defaults.

### 2.2 Transport constraint, stated plainly

This design routes **configuration and credential governance** through
ModelGateway; the CLI's inference traffic still goes directly from the Runtime
Host to the resolved upstream. Unifying governance/retries/audit for that
traffic requires the inbound bridge described above and is recorded as a
follow-up phase, not silently implied. Both `wire_api` and `base_url` are
per-connection configurable so providers whose `/responses` path or protocol
differs can be onboarded without a code change.

## 3. Q2 — where a valid credential is configured, and the fix

**Answer to the question:** the credential record is created by an administrator
through `POST /api/v1/execution-credentials` with `secret`, `allowed_engines`
(must include `codex`) and `allowed_workspaces`. The response field
`credential_ref` is the UUID. Its validity is defined by
`status='active'` plus the engine/workspace scopes. There is deliberately no
API that returns the plaintext.

**Optimization:**

1. Remove the free-text `Codex 凭据引用（UUID）` input from the customer Agent
   form. Replace it with a **read-only selector populated from
   `GET /execution-credentials`** (admin metadata only), showing name, status,
   allowed engines, and version. Invalid, revoked and out-of-scope records are
   either hidden or flagged; users can no longer invent a UUID.
2. In the recommended Gateway lane, the reference is not chosen on the Agent at
   all: it is the connection's `execution_credential_ref`, so an Agent only
   chooses a model profile.
3. Server-side, on every save/publish, **validate and canonicalize**
   `codex.credential_ref` against the `execution_credentials` record (the client
   may choose among valid records but cannot invent one), and replace any
   client-supplied `codex.path_env` with the deployment value. In the Gateway
   lane the reference is derived from the connection, so the client value is
   ignored entirely.
4. Publish validation resolves the whole chain (profile → route → connection →
   active scoped credential) and fails with a stable, translatable domain code
   before a broken version can be published.

## 4. Q5 — Codex PATH

- `AGENT_CODEX_PATH_ENV` becomes the single effective source of truth. The
  composition root passes `settings.codex_path_env` into `CodexCliAdapter`, and
  `start()` uses it for the child `PATH` instead of the published snapshot value.
  This heals already-published agents without a re-publish.
- Remove the `Codex PATH` input from the customer form.
- Update compose / `.env.example` comments that currently describe the variable
  as dead, and document that changing it requires a backend restart.

## 5. Q1 — fix plan (four layers)

| Layer | Change | Effect |
| --- | --- | --- |
| L1 Prevent | Publish-time validation of the Codex credential chain (existence, active, engine scope, workspace scope, profile resolution, host allowlist) with `codex_credential_invalid` / `codex_model_profile_invalid` | A stale or wrong-scope reference can no longer be published |
| L2 Classify | `CredentialGrantDenied` maps to a typed run code `execution_credential_unavailable` instead of the sanitized `execution_error`; gate denials keep `adapter_disabled` | The failure names its cause without leaking secrets |
| L3 Explain | i18n entries for the new codes; `Conversations.tsx` renders through `errorText` instead of the raw code; `CredentialSource` shows a recovery hint | Users see an actionable message |
| L4 Repair | Acceptance step: correct the P7 agent's stale reference via the new selector, re-publish, and re-run the trial chat | The originally reported symptom is verified fixed on the real machine |

The immediate data-level repair (repointing the online P7 agent to a valid
credential) is an acceptance step, not a substitute for L1–L3. L1 makes the
whole class of defect unreachable through the product UI.

## 6. Issue breakdown

| Issue | Title | Deliverable |
| --- | --- | --- |
| #165 | Q1: classify and prevent stale Codex credential run failures | L1–L3 backend + i18n + tests |
| #166 | Q2: valid credential_ref configuration entry and UI optimization | selector, server-side injection, docs |
| #167 | Q3: Codex CLI driven by the ModelGateway catalogue | contracts, connection fields, resolver, adapter, compatibility lane, tests |
| #168 | Q5: deployment-owned Codex PATH | settings wiring, UI removal, deploy docs |

## 7. Acceptance criteria

1. A Codex Agent bound to any published Gateway chat profile renders a
   `config.toml` whose `model`, `model_provider`, `base_url`, `wire_api` and
   `env_key` come from that profile's route — no `deepseek-flash` literal in the
   Gateway lane.
2. A Codex Agent with the legacy shape still runs unchanged.
3. Publishing with an unknown/revoked/out-of-scope credential reference is
   rejected with a stable, translated code; the trial chat no longer returns
   `execution_error` for this cause.
4. `AGENT_CODEX_PATH_ENV` changes the child `PATH` without editing any Agent;
   the customer form has no credential UUID or PATH input.
5. Existing backend tests, frontend typecheck/i18n/build and the
   `agent-execution-config.spec.ts` regression specs pass; CI is green; the
   acceptance host is re-verified after CD.

## 8. Risk and rollback

- All new contract fields are optional and defaulted; the denylist in
  `contracts/snapshots.py` only needs the two new profile keys whitelisted as
  typed, non-secret values.
- The Gateway lane is opt-in. If it misbehaves, removing the profile pair from
  an Agent returns it to the legacy lane with no migration.
- No secret value is stored in any snapshot, `config.toml`, log or API response.
- No database migration is required: all new Gateway connection fields live in
  the existing JSONB spec column.
