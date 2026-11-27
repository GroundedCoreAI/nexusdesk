# Phase 2 · Skill Authoring, Testing, and Release — Technical Design

> Status: Design approved; implementation in progress.
> Created: 2026-11-27
> Basis: `00-ui-interaction-freeze.md` (U1–U13), `01-business-goals.md` (G1–G4), `02-requirements.md` (FR-1–FR-10, AC-1–AC-12).
> Verified baseline: the permitted development database is at `0075_gateway_allowed_hosts`; current application Skill implementation is scoped to `service_applications`.
> Revision: 2026-11-27 — migration number changed from `0074_skill_library` to `0076_skill_library` after confirming the live database already contains `0074_codex_wire_api_backfill` and `0075_gateway_allowed_hosts`. The two missing migration files are restored to the working branch from their existing upstream commits; no restamp or volume reset is performed.

## 1. Baseline Findings

| Area | Current reality | Consequence for this design |
|---|---|---|
| Frontend routes | `frontend/src/app/hashRouter.ts` only accepts a fixed list of Skill keys and `/skills/create` | Add generic key plus `/edit`; do not add test/version routes |
| Catalog | `frontend/src/features/skills/SkillsPage.tsx` renders a private static `catalog` array | Replace with API-backed list while preserving the approved Phosphor/Ant Design shell |
| Creation | `frontend/src/features/skills/CreateSkillPage.tsx` has local `step`, `tested`, and `published` state | Split wizard selection from shared editor/test/release components |
| Detail | `frontend/src/features/skills/SkillDetailPage.tsx` uses fixture details and placeholder actions | Load a persisted Skill; Edit/Test/Publish open real in-page workflows |
| Application Skills | `service_application_skills` rows are children of one application and require that application's connections | Not reusable as the global capability library identity |
| Application releases | `service_application_versions` snapshot the whole application, including its owned Skills | Correct for application releases, but not a global Skill version history |
| Existing test endpoint | `POST /service-apps/{key}/skills/{skill_key}/test` validates an application Skill contract | A useful precedent, but it is not a global test run/history model |
| Permissions | `core_platform/platform_services/identity/permissions.py` has no Skill permissions | Add `skill.read`, `skill.manage`, `skill.test`, and `skill.publish` |

## 2. Architecture Decision

### 2.1 Option comparison

| Option | Benefits | Problems | Decision |
|---|---|---|---|
| A. Extend `service_application_skills` | Reuses current table and connection ownership | Application FK makes a Skill non-global; no independent versions; no persisted test history; editing affects application draft semantics; a library entry would be a disguised application child | Rejected |
| B. New global Skill domain | Stable identity independent of applications; draft/version/test separation; can later be referenced by Agents and service applications | Requires a new migration, service, routes, API client, and frontend data layer | Accepted |

The new domain owns authoring, testing, and release. It does not retrofit the application-scoped Skill tables. A later integration phase may resolve a published global Skill version into an Agent/application snapshot, but Phase 2 must not make the global library depend on one application.

### 2.2 Placement

```text
backend/src/agent_platform/business_capabilities/skill_library/
  __init__.py
  models.py       # strict create/update/test/publish/version contracts
  service.py      # draft, readiness, publish, rollback, catalog, versions
  testing.py      # SkillTestExecutor and per-type execution adapters
  templates.py    # code-owned curated creation templates
  assistant.py    # optional AI draft generation through ModelGateway
  routes.py       # HTTP surface under /api/v1/skills
```

The module is a business capability, not a core-platform primitive. It imports the existing persistence, scope, permission, model gateway, retrieval, and tool gateway ports.

## 3. Change Inventory

| Layer | File | Change |
|---|---|---|
| Migration | `backend/migrations/versions/0076_skill_library.py` | Add `skills`, `skill_test_runs`, and `skill_versions` |
| New module | `backend/src/agent_platform/business_capabilities/skill_library/models.py` | Validate Skill definition, input, publish, rollback, and API responses |
| New module | `backend/src/agent_platform/business_capabilities/skill_library/service.py` | Catalog, draft revision, readiness, immutable versions, rollback, audit |
| New module | `backend/src/agent_platform/business_capabilities/skill_library/testing.py` | Execute and persist one test against an exact draft revision |
| New module | `backend/src/agent_platform/business_capabilities/skill_library/templates.py` | Curated template catalogue and draft defaults |
| New module | `backend/src/agent_platform/business_capabilities/skill_library/assistant.py` | Optional AI-assisted draft generation |
| New module | `backend/src/agent_platform/business_capabilities/skill_library/routes.py` | `/api/v1/skills` and `/api/v1/skill-templates` routes |
| Composition | `backend/src/agent_platform/applications/platform_runtime/platform_services.py` | Construct the domain and test executor; retain the tool HTTP client |
| Composition | `backend/src/agent_platform/applications/platform_runtime/service_groups.py` | Expose `business.skill_library` |
| Route mount | `backend/src/agent_platform/applications/customer_service/application.py` | Include the new router |
| Permission catalog | `backend/src/agent_platform/core_platform/platform_services/identity/permissions.py` | Add Skill permissions and role mapping |
| Settings | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | Add AI/test bounds and live-tool-test switch |
| Frontend contracts | `frontend/src/features/skills/contracts.ts` | API types and normalized Skill/version/test models |
| Frontend API | `frontend/src/features/skills/api.ts` | Typed CRUD/test/readiness/publish/rollback calls |
| Frontend hooks | `frontend/src/features/skills/useSkills.ts` | Catalog, detail, draft, test history, readiness, versions |
| Frontend editor | `frontend/src/features/skills/SkillEditor.tsx` | Shared sectioned editor and validation |
| Frontend test | `frontend/src/features/skills/TestWorkbench.tsx` | Two-pane test and history |
| Frontend release | `frontend/src/features/skills/ReleasePanel.tsx` | Readiness, publish, version history, rollback |
| Frontend pages | `frontend/src/features/skills/SkillsPage.tsx`, `CreateSkillPage.tsx`, `SkillDetailPage.tsx` | Replace fixtures/placeholders with API-backed state |
| Routing | `frontend/src/app/hashRouter.ts` | Accept generic Skill keys and `/edit` |
| Styles | `frontend/src/features/skills/skills.css`, `skill-workflows.css` | Add responsive editor/test/release states without changing the shell |
| Locales | `frontend/src/i18n/locales/en.json`, `hi.json`, `zh-CN.json`, `zh-TW.json` | Add every new visible string |
| Tests | `frontend/tests/skills.spec.ts`, new backend Skill tests | Replace static expectations with lifecycle and failure-state coverage |

## 4. Data Model

### 4.1 Migration `0076_skill_library.py`

The current database/upstream Alembic graph has one head, `0075_gateway_allowed_hosts`. The new revision identifier stays within the existing 32-character version column:

```python
revision = "0076_skill_library"
down_revision = "0075_gateway_allowed_hosts"
```

#### `skills`

```sql
CREATE TABLE skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    skill_key TEXT NOT NULL
        CHECK (skill_key ~ '^[a-z][a-z0-9_-]{0,63}$'),
    name TEXT NOT NULL CHECK (char_length(name) BETWEEN 1 AND 100),
    description TEXT NOT NULL DEFAULT ''
        CHECK (char_length(description) <= 1000),
    category TEXT NOT NULL
        CHECK (category IN ('service', 'finance', 'sales', 'general')),
    tags TEXT[] NOT NULL DEFAULT '{}',
    visibility TEXT NOT NULL DEFAULT 'workspace'
        CHECK (visibility = 'workspace'),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published', 'archived')),
    definition_schema_version TEXT NOT NULL DEFAULT 'v1'
        CHECK (definition_schema_version = 'v1'),
    draft_definition JSONB NOT NULL,
    draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision > 0),
    published_version INTEGER NULL CHECK (published_version > 0),
    published_revision INTEGER NULL CHECK (published_revision > 0),
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT skills_identity_unique
        UNIQUE (tenant_id, business_id, workspace_id, skill_key),
    CONSTRAINT skills_scope_id_unique
        UNIQUE (tenant_id, business_id, workspace_id, id)
);

CREATE INDEX skills_catalog
ON skills (
    tenant_id, business_id, workspace_id,
    status, category, updated_at DESC
);
```

`name`, `description`, `category`, and `tags` are indexed draft metadata used by the catalog; the immutable published display definition remains in `skill_versions.definition`. `published_revision` allows the UI and API to expose an honest `has_unpublished_changes` flag without comparing large JSON documents.

#### `skill_test_runs`

```sql
CREATE TABLE skill_test_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    skill_id UUID NOT NULL,
    draft_revision INTEGER NOT NULL CHECK (draft_revision > 0),
    status TEXT NOT NULL
        CHECK (status IN ('passed', 'failed', 'error', 'blocked')),
    execution_kind TEXT NOT NULL
        CHECK (execution_kind IN ('live', 'contract')),
    input JSONB NOT NULL,
    input_summary TEXT NOT NULL DEFAULT ''
        CHECK (char_length(input_summary) <= 500),
    output JSONB NULL,
    diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_code TEXT NULL
        CHECK (reason_code IS NULL OR char_length(reason_code) <= 200),
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    client_request_id TEXT NULL
        CHECK (client_request_id IS NULL OR char_length(client_request_id) <= 128),
    executed_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT skill_test_runs_skill_fk
        FOREIGN KEY (tenant_id, business_id, workspace_id, skill_id)
        REFERENCES skills (tenant_id, business_id, workspace_id, id)
        ON DELETE CASCADE,
    CONSTRAINT skill_test_runs_scope_run_unique
        UNIQUE (tenant_id, business_id, workspace_id, skill_id, id),
    CONSTRAINT skill_test_runs_request_unique
        UNIQUE (
            tenant_id, business_id, workspace_id, skill_id, client_request_id
        )
);

CREATE INDEX skill_test_runs_revision
ON skill_test_runs (
    tenant_id, business_id, workspace_id, skill_id,
    draft_revision, status, created_at DESC
);
```

Only completed test outcomes are persisted. The UI's Running state is the in-flight request state; it is not a durable run row. This avoids permanently stuck `running` rows when a request is cancelled or a worker dies. The API call is bounded by `skill_test_timeout_seconds`, and duplicate client request keys are rejected by the unique constraint.

#### `skill_versions`

```sql
CREATE TABLE skill_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    skill_id UUID NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    semver TEXT NOT NULL
        CHECK (semver ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    release_kind TEXT NOT NULL
        CHECK (release_kind IN ('initial', 'major', 'minor', 'patch', 'rollback')),
    definition_schema_version TEXT NOT NULL
        CHECK (definition_schema_version = 'v1'),
    definition JSONB NOT NULL,
    definition_digest TEXT NOT NULL
        CHECK (definition_digest ~ '^sha256:[a-f0-9]{64}$'),
    release_notes TEXT NOT NULL
        CHECK (char_length(release_notes) BETWEEN 1 AND 2000),
    source_draft_revision INTEGER NOT NULL CHECK (source_draft_revision > 0),
    test_run_id UUID NULL,
    rollback_from INTEGER NULL CHECK (rollback_from > 0),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT skill_versions_skill_fk
        FOREIGN KEY (tenant_id, business_id, workspace_id, skill_id)
        REFERENCES skills (tenant_id, business_id, workspace_id, id)
        ON DELETE CASCADE,
    CONSTRAINT skill_versions_scope_version_unique
        UNIQUE (tenant_id, business_id, workspace_id, skill_id, version),
    CONSTRAINT skill_versions_scope_semver_unique
        UNIQUE (tenant_id, business_id, workspace_id, skill_id, semver),
    CONSTRAINT skill_versions_test_run_fk
        FOREIGN KEY (tenant_id, business_id, workspace_id, skill_id, test_run_id)
        REFERENCES skill_test_runs (
            tenant_id, business_id, workspace_id, skill_id, id
        ),
    CONSTRAINT skill_versions_rollback_fk
        FOREIGN KEY (
            tenant_id, business_id, workspace_id, skill_id, rollback_from
        )
        REFERENCES skill_versions (
            tenant_id, business_id, workspace_id, skill_id, version
        )
);

CREATE INDEX skill_versions_history
ON skill_versions (
    tenant_id, business_id, workspace_id, skill_id, version DESC
);
```

Published rows are never updated. A rollback inserts a new row whose `definition` is copied from the target, `rollback_from` points to the target, `release_kind='rollback'`, and `test_run_id` may be `NULL` because the historical version already passed its release gate when it was originally published. `source_draft_revision` records the draft revision used for that historical snapshot.

### 4.2 Why one draft per Skill, not a draft table

There is exactly one active draft per Skill identity. Storing draft fields on `skills` gives the same revision-checked update pattern already proven by `agents`, keeps the row lock and revision comparison in one place, and avoids a second row with unclear lifecycle. A separate draft table would be justified only if multiple concurrent drafts or collaborative branches were in scope.

### 4.3 Definition JSON contract

`draft_definition` and `skill_versions.definition` use one versioned JSON shape:

```json
{
  "schema_version": "v1",
  "creation_mode": "ai",
  "type": "instruction",
  "trigger": "agent_auto",
  "instructions": "Extract the customer name and phone number...",
  "parameters": [
    {
      "name": "text",
      "type": "string",
      "required": true,
      "default": null,
      "description": "Unstructured customer text"
    }
  ],
  "output": {
    "format": "json",
    "schema": {
      "type": "object",
      "properties": {
        "name": {"type": "string"},
        "phone": {"type": "string"}
      },
      "required": ["name", "phone"],
      "additionalProperties": false
    }
  },
  "dependencies": {
    "model_profile_id": "00000000-0000-0000-0000-000000000000",
    "model_profile_version": 1,
    "knowledge_base_ids": [],
    "tool_names": [],
    "handoff_queue": null
  },
  "runtime": {
    "timeout_seconds": 30,
    "retry_policy": "none",
    "confirmation_required": false,
    "idempotency": "none",
    "error_behavior": "fail",
    "max_amount": null
  },
  "permission_scope": "workspace"
}
```

Pydantic validation is authoritative. The JSONB column is not an unvalidated escape hatch. Required cross-field rules are enforced both at draft save and publish:

- Parameter names are unique and machine-safe; schema generation is deterministic.
- `instruction` requires instructions and a model profile.
- `knowledge` requires at least one enabled knowledge base.
- `query` requires a read-effect tool.
- `action` requires a write-effect tool and confirmation or an explicit stored exemption.
- `handoff` requires an existing queue.
- `output.format=json` requires a valid Draft 2020-12 schema.
- Runtime bounds and error behavior use closed enums.

## 5. API Contract

Router prefix: `/api/v1/skills`. All calls use the trusted tenant/business/workspace scope from request state. `{skill_key}` is stable and URL-safe.

| Method and path | Purpose | Permission | Key behavior |
|---|---|---|---|
| `GET /skills` | Catalog | `skill.read` | Search, category/status filters, page; no fixture rows |
| `POST /skills` | Create initial draft | `skill.manage` | Body has mode plus AI prompt/template/definition; server generates unique key |
| `GET /skills/{skill_key}` | Detail read | `skill.read` | Returns draft summary, published snapshot indicator, current version |
| `PUT /skills/{skill_key}/draft` | Save draft | `skill.manage` | Requires `revision`; validates definition; 409 on conflict |
| `GET /skills/{skill_key}/versions` | Immutable history | `skill.read` | Reverse chronological, paginated |
| `GET /skills/{skill_key}/versions/{version}` | Version detail | `skill.read` | Returns immutable definition and lineage |
| `GET /skills/{skill_key}/readiness` | Release checklist | `skill.read` | Evaluates current draft and latest test; publish permission included as a check |
| `POST /skills/{skill_key}/test-runs` | Execute one test | `skill.test` | Requires saved `draft_revision`; returns completed run; optional idempotency key |
| `GET /skills/{skill_key}/test-runs` | Test history | `skill.read` | Reverse chronological, paginated |
| `GET /skills/{skill_key}/test-runs/{run_id}` | Test detail | `skill.read` | Safe output/diagnostics; no Secret |
| `POST /skills/{skill_key}/publish` | Publish version | `skill.publish` | Requires revision, bump, release notes; rechecks readiness under lock |
| `POST /skills/{skill_key}/rollback` | Create rollback version | `skill.publish` | Requires target version, current revision, notes; never mutates target |
| `POST /skills/{skill_key}/duplicate` | Resolve save conflict | `skill.manage` | Copies current server draft into a new key |
| `GET /skill-templates` | Curated template catalogue | `skill.read` | Code-owned definitions with loading/error contract |

### 5.1 Create request

```json
{
  "mode": "ai",
  "prompt": "Extract name and phone number from customer text",
  "template_key": null,
  "definition": null
}
```

Mode rules:

- `ai`: prompt required; model profile resolved from settings; no draft is created when generation fails.
- `template`: exactly one existing `template_key`; the server applies its defaults.
- `professional`: neither prompt nor template is required; the server creates empty defaults.

### 5.2 Draft update

```json
{
  "revision": 3,
  "name": "Customer Information Extraction",
  "description": "Extract structured customer fields.",
  "category": "service",
  "tags": ["extraction", "customer"],
  "definition": { "...": "validated definition v1" }
}
```

On success the response contains the complete current row with `draft_revision=4` and `has_unpublished_changes=true` when applicable. On stale revision, return `409 skill_revision_conflict` with `current_revision`; the frontend must offer reload/duplicate rather than silently overwrite.

### 5.3 Test request and response

```json
{
  "draft_revision": 4,
  "input": {"text": "Name: Li Wei; Phone: 13800138000"},
  "scenario": "Happy path",
  "client_request_id": "browser-generated-uuid"
}
```

Response:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "skill_id": "00000000-0000-0000-0000-000000000000",
  "draft_revision": 4,
  "status": "passed",
  "execution_kind": "live",
  "output": {"name": "Li Wei", "phone": "13800138000"},
  "duration_ms": 842,
  "reason_code": null,
  "diagnostics": {"model_profile_version": 1, "output_schema_valid": true},
  "executed_by": "enterprise:...",
  "created_at": "..."
}
```

`passed` is returned only after the executor completed and the declared output contract validated. A transport error, timeout, missing dependency, invalid output, or unsafe write test must not map to `passed`.

### 5.4 Readiness response

```json
{
  "skill_id": "00000000-0000-0000-0000-000000000000",
  "draft_revision": 4,
  "ready": false,
  "checks": [
    {
      "code": "latest_test_passed",
      "status": "fail",
      "reason": "The latest test for draft r4 failed.",
      "destination": "tests"
    }
  ]
}
```

Allowed check statuses are `pass`, `fail`, `warning`. `ready` is true only when every mandatory check is `pass`.

## 6. Service State Machines

### 6.1 Skill lifecycle

```text
draft (no current version)
  └─ publish success → published
published
  ├─ save draft with published_revision < draft_revision → published + dirty
  ├─ publish success → published at new current version
  └─ rollback success → published at new rollback version
published/draft ─ archive (future explicit action) → archived
```

Status is based on the Skill row, never on the client's current tab or form state. Publishing does not clear or rewrite the draft; it copies the exact validated snapshot and records `published_revision`.

### 6.2 Draft save (`service.py`)

```python
async def save_draft(..., revision: int, body: SkillDraftUpdate):
    async with engine.begin() as c:
        row = SELECT ... FROM skills ... FOR UPDATE
        require row in scope
        if row.draft_revision != revision:
            raise DomainError("skill_revision_conflict", 409)
        validated = SkillDefinition.model_validate(body.definition)
        UPDATE skills
          SET metadata, draft_definition, draft_revision=draft_revision+1, ...
        audit("skill.draft_saved", skill_id, revision=+1)
        return current row
```

Save is all-or-nothing; dependency load failures outside the request do not block editing, but publish validates them.

### 6.3 Test (`testing.py`)

```python
async def run_test(tenant, actor, skill, revision, request):
    require saved revision == request.draft_revision
    definition = SkillDefinition.model_validate(skill.draft_definition)
    validate input against definition.parameters
    started = monotonic()
    outcome = await executor.execute(definition, request)
    persist test result only after completion
    audit("skill.tested", skill.id, run_id, revision, status, duration_ms)
    return run
```

The executor runs outside the persistence write transaction so a slow model/tool call does not hold a row lock. The final row is tenant/scope bound and contains only bounded, redacted diagnostics.

### 6.4 Readiness and publish (`service.py`)

```python
async def readiness(..., can_publish: bool):
    check draft row exists and revision is current
    check definition validation
    check latest test for this revision is status=passed
    resolve all dependencies in scope and enabled state
    check caller permission
    check next version/sequence available

async def publish(..., revision, bump, release_notes):
    async with engine.begin() as c:
        lock skill row FOR UPDATE
        check revision and archived status
        try advisory publish lock; fail as skill_publish_in_progress when unavailable
        recompute readiness inside the same transaction
        choose server-owned next monotonic version and semver
        canonicalize definition and compute sha256 digest
        INSERT skill_versions
        UPDATE skills current version/published revision/status
        audit immutable version metadata, never the full Secret-bearing input
```

### 6.5 Rollback (`service.py`)

```python
async def rollback(..., target_version, current_revision, release_notes):
    async with engine.begin() as c:
        lock skill row and verify revision
        target = SELECT immutable version in scope
        revalidate target definition and current dependency availability
        next_version = max(version)+1
        next_patch_semver = semver_patch(current_semver)+1
        INSERT skill_versions(
            definition=target.definition,
            release_kind="rollback",
            rollback_from=target_version,
            test_run_id=None,
            release_notes
        )
        UPDATE skills current version/status/published_revision
        audit("skill.rolled_back", source_version=target_version)
```

Rollback cannot target the current version, cannot rewrite any version, and cannot leave a partially updated current pointer.

## 7. Test Execution Adapters

`SkillTestExecutor` is a narrow port; the service never imports model or tool internals directly.

| Skill type | Adapter | Pass criteria | Failure/blocked behavior |
|---|---|---|---|
| Instruction | `ModelGateway.invoke` with the declared chat profile | Request completes and output matches text/JSON contract | Model/profile error = `error`; schema mismatch = `failed` |
| Knowledge | `Retrieval.search` with declared KB IDs | Retrieval completes in scope | Missing/disabled KB = `error`; empty hits remain a valid successful output |
| Query | Read-effect HTTP tool through `ToolRegistry` + `ToolGateway` | `ok=true`, output matches declared schema | Tool unavailable = `error`; invalid output = `failed` |
| Action | Write-effect tool | Not executed live by default | `blocked` with `skill_write_test_unsafe`; no passing evidence |
| Handoff | Queue resolution and contract check | Queue exists and handoff payload validates | Missing queue = `error`; intentionally does not create a real handoff |

The `execution_kind` field makes the evidence honest: model/knowledge/read-tool tests are `live`; queue validation is `contract`. UI copy must expose this distinction and release readiness must not describe a contract check as a live side effect.

Live read-tool tests are additionally gated by `skill_live_tool_tests_enabled` (default `false`). With the switch off, query/action tests return `blocked` and the UI explains that live tool tests are disabled for this deployment.

## 8. AI-Assisted Draft Generation

AI mode uses a deployment-selected ModelGateway chat profile, not an arbitrary client-supplied model identifier.

```text
prompt + strict JSON response schema
  → ModelGateway.invoke(operation=chat)
  → parse/validate SkillGenerationResult
  → reject prompts/instructions containing unsupported fields
  → create one draft with creation_mode=ai
```

The model may generate names, descriptions, instructions, parameter proposals, and an output schema. It cannot generate Secrets, endpoint URLs, approved roles, or permission escalation. Any generated dependency reference is revalidated; unresolved references remain visible warnings and block publish.

If the AI profile is absent or generation is disabled, the API returns `503 skill_ai_generation_unavailable`. Template and professional modes remain usable.

## 9. Permissions, Audit, and Isolation

Add these permissions:

| Permission | Admin | Operator | Viewer |
|---|---|---|---|
| `skill.read` | Yes | Yes | Yes |
| `skill.manage` | Yes | No | No |
| `skill.test` | Yes | Yes | No |
| `skill.publish` | Yes | No | No |

Routes use the existing principal dependency and permission checks. Every SQL statement includes `tenant_id`, `business_id`, and `workspace_id`; a missing or cross-scope row is reported as not found, not as forbidden data that confirms existence.

Audit actions:

- `skill.created`
- `skill.draft_saved`
- `skill.tested`
- `skill.published`
- `skill.rolled_back`
- `skill.duplicated`

Audit details include revision, version, semver, release kind, test status/run id, duration, dependency reason codes, and definition digest. They exclude Secrets, full model prompts, customer content, and raw tool credentials.

## 10. Configuration

Add to `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`:

```python
skill_ai_generation_enabled: bool = False
skill_ai_profile_id: UUID | None = None
skill_ai_profile_version: int = 1
skill_test_timeout_seconds: int = 30
skill_test_max_input_chars: int = 20000
skill_test_max_output_chars: int = 20000
skill_live_tool_tests_enabled: bool = False
```

Defaults are safe:

- AI generation is off until a chat profile is explicitly selected.
- Live external tool tests are off until an operator enables them for a trusted environment.
- Write-action testing is never converted to a live call by a switch in this phase.
- Timeout and input/output caps are enforced server-side as well as surfaced in the UI.

## 11. Frontend Data Flow

1. `SkillsPage` subscribes to `/skills` and renders skeleton/error/empty/API records.
2. `CreateSkillPage` owns only Step 1; successful draft creation navigates to the editor key.
3. `SkillEditor` loads the current draft and dependency pickers independently. It keeps one local form object and last-saved revision.
4. `TestWorkbench` receives the saved revision and current definition; it never tests local dirty fields.
5. `ReleasePanel` loads readiness and versions, then opens publish/rollback dialogs.
6. `SkillDetailPage` selects the published snapshot for read-only tabs and exposes Edit/Test/Publish actions according to permission and status.
7. Runtime Analytics becomes an empty-state panel until a real runtime aggregation endpoint exists; no fake sparklines remain.

The static `catalog`, `details`, and fixed test/version rows are removed from production branches once API integration lands. Tests may retain explicitly named fixtures inside a mock server, not inside the page components.

## 12. Error Codes

| Code | HTTP | User-facing meaning |
|---|---|---|
| `skill_not_found` | 404 | Skill does not exist in the active scope |
| `skill_key_conflict` | 409 | Generated/stable key already exists |
| `skill_revision_conflict` | 409 | A newer draft exists; reload or duplicate |
| `skill_definition_invalid` | 422 | A required field or cross-field rule failed |
| `skill_dependency_unavailable` | 409 | A model, KB, tool, queue, or connector is unavailable |
| `skill_test_input_invalid` | 422 | Input does not satisfy the parameter contract |
| `skill_test_execution_blocked` | 409 | A write or live-tool test is not safe in this environment |
| `skill_test_execution_error` | 502 | Model/tool execution failed |
| `skill_readiness_blocked` | 409 | One or more mandatory release checks failed |
| `skill_publish_in_progress` | 409 | Another publish operation owns the Skill lock |
| `skill_version_not_found` | 404 | Version does not exist in scope |
| `skill_ai_generation_unavailable` | 503 | AI generation is not configured |
| `insufficient_permission` | 403 | Caller lacks the required Skill permission |

The frontend maps stable codes to localized copy. It may append sanitized server diagnostics but must not render raw exception text or Secrets.

## 13. MVP Delivery Sequence

| Stage | Delivery | Exit condition |
|---|---|---|
| T1 | Migration, models, domain service skeleton, permissions, settings | Additive migration and service unit tests pass |
| T2 | Catalog, create draft, read detail, save draft | API-backed catalog and revision conflicts work |
| T3 | Shared editor and dependency resolution | All five sections render and validate; no placeholder Save |
| T4 | Test executor and history | Passed/Failed/Error/Blocked outcomes persist against revision |
| T5 | Readiness, publish, versions, rollback | Immutable version chain and rollback lineage pass integration tests |
| T6 | Frontend lifecycle integration | Creation, edit, test, publish, rollback complete without static success messages |
| T7 | Honest states, responsive/i18n/accessibility, regression | Phase 2 test plan is executable end to end |

## 14. Testing Summary

| Layer | Coverage |
|---|---|
| Unit | Definition validation, semver suggestion, readiness combination, test outcome classification, rollback lineage |
| Integration | Migration, create/save/revision conflict, test persistence, publish atomicity, rollback atomicity, tenant isolation, permissions, audit |
| UI/E2E | Creation handoff, dirty guard, test states/history, readiness blockers, publish/rollback dialogs, not-found/permission states, four locales, responsive widths |

Detailed cases and traceability are in `04-test-plan.md`.

## 15. Rollout and Rollback

- The migration is additive and does not alter or backfill `service_application_skills` or `service_application_versions`.
- No static frontend fixture is copied into the database. A new deployment starts with an honest empty catalog; templates are code-owned defaults, not customer records.
- Backend routes can ship before the frontend switch while remaining invisible and side-effect-free; the UI must not display static success once it points at the API.
- The migration downgrade drops the three new tables only after verifying they contain no persisted Skill data; otherwise it refuses and requires an export or explicit cleanup.
- Application runtime, Agent execution, customer channels, and service-application release paths remain unchanged in this phase.
- A later integration phase will add an immutable `global_skill_version` reference to Agent/application snapshots; this design deliberately does not mutate those schemas now.

## 16. Frozen MVP Decisions for Review

These decisions are part of the proposed Phase 2 contract and are carried into the UI freeze, test plan, and acceptance gates:

1. A global Skill with a write-effect Action may be authored, but its live test remains `blocked/skill_write_test_unsafe` and it cannot obtain passing release evidence or publish until a sandbox/fixture policy exists.
2. Runtime Analytics uses an honest empty state in Phase 2; no usage-aggregation table or fabricated metric is introduced.
3. Curated templates remain code-owned and are not editable through a template-management screen in this phase.
