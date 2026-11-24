# Phase 1 · UI-managed model egress hosts — Requirements

## User Stories

**US-1 (deployment administrator)**: As an administrator, I want to add a public
HTTPS provider host in the console, so that I can configure a custom channel
without editing deployment files or restarting the backend.

**US-2 (deployment administrator)**: As an administrator, I want to see both the
deployment baseline and the UI-managed hosts, so that I know why a channel is
allowed or blocked.

**US-3 (security reviewer)**: As a security reviewer, I want every host change
audited and private addresses rejected, so that the egress boundary is not
silently widened.

**US-4 (operator)**: As an operator, when a save is blocked, I want a message that
names the host and tells me what to do next, instead of a generic retry prompt.

## Functional Requirements

### FR-1 List effective and managed hosts

| Item | Description |
|---|---|
| Trigger | Admin opens model gateway → 出站主机 |
| Input | Authenticated principal (tenant, actor, role) |
| Output | `{enabled, deployment: [host...], managed: [{host, created_by, created_at}...]}` |
| Execution | Synchronous read; deployment list from settings, managed list from DB |
| Failure | Unauthenticated 401; non-admin 403; DB failure 500 with the existing domain error path |

### FR-2 Add a managed host

| Item | Description |
|---|---|
| Trigger | Admin submits a hostname |
| Input | `host` (string), tenant and actor from the principal |
| Output | Created record; cache invalidated in the serving process |
| Execution | Normalize → validate public HTTPS DNS name → resolve → insert → audit |
| Failure | Invalid/private/unresolved host returns a stable 400/409 code; duplicate is idempotent or 409 |

### FR-3 Remove a managed host

| Item | Description |
|---|---|
| Trigger | Admin deletes a row |
| Input | Hostname, tenant, actor |
| Output | Row removed; audit written; cache invalidated |
| Execution | Delete by `(tenant, host)`; 404 when absent |
| Failure | Existing channels using the host fail closed with `model_address_not_allowed` |

### FR-4 Public-only validation

| Item | Description |
|---|---|
| Trigger | Add request |
| Input | Raw hostname or URL pasted by the administrator |
| Output | Canonical lowercase hostname, or a stable rejection |
| Execution | Accept a bare hostname or `https://host[/path]`; extract the host; reject scheme other than https, userinfo, query, fragment, wildcard, literal IPv4/IPv6, single-label names, and names resolving to non-public addresses |
| Failure | `model_host_invalid`, `model_host_not_public`, `model_host_unresolved` |

### FR-5 Effective allowlist

| Item | Description |
|---|---|
| Trigger | Channel save, probe, discovery, profile resolve, gateway invoke, Codex resolve |
| Input | Tenant, connection spec |
| Output | Allowed or `model_address_not_allowed` |
| Execution | Deployment list is always checked first and is authoritative; when the switch is on, the managed list for the tenant is unioned in |
| Failure | Any check failure is fail-closed; no fallback to "allow all" |

### FR-6 Console page

| Item | Description |
|---|---|
| Trigger | Admin opens `模型网关 → 出站主机` |
| Input | Hostname to add |
| Output | Deployment list (read-only), managed list with delete, switch state |
| Execution | Calls FR-1..FR-3 endpoints; hidden from non-admin |
| Failure | When the switch is off, the page is read-only and explains the env setting |

### FR-7 Inline allow on save error

| Item | Description |
|---|---|
| Trigger | Saving a channel fails with `model_address_not_allowed` |
| Input | The form's `base_url` hostname |
| Output | Hint naming the host; admin + switch-on shows an "allow this host" action |
| Execution | POST FR-2, then the operator retries save |
| Failure | If the action fails, show the specific host error; no automatic retry |

### FR-8 Audit

| Item | Description |
|---|---|
| Trigger | Add or remove succeeds |
| Input | Tenant, actor, host |
| Output | `audit_records` row with action `model_gateway.allowed_host.added` / `.removed` |
| Execution | Same transaction as the change |
| Failure | Audit failure aborts the change |

### FR-9 Deployment switch

| Item | Description |
|---|---|
| Trigger | Backend start |
| Input | `AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS` |
| Output | Feature enabled/disabled |
| Execution | Boolean setting, default `false`; disabled means managed hosts are not effective and mutations are refused |
| Failure | Invalid value fails settings validation at startup |

### FR-10 Cache propagation

| Item | Description |
|---|---|
| Trigger | Read of the effective allowlist |
| Input | Tenant |
| Output | Cached managed host set |
| Execution | Process-local cache with a 15-second TTL; writes invalidate the local entry immediately; other processes converge within the TTL |
| Failure | Cache read failure falls back to the DB or fails closed; never allow-all |

## Configuration

| Key | Level | Default | Description |
|---|---|---|---|
| `AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS` | global settings | `false` | Enables UI-managed hosts and the management API/UI |
| `AGENT_MODEL_GATEWAY_ALLOWED_HOSTS` | global settings | existing list | Deployment baseline; unchanged semantics |

## Non-Functional Requirements

- **Security**: public HTTPS only; private/metadata addresses rejected; admin-only
  mutations; audit without secrets; no wildcard from the UI.
- **Compatibility**: default off; existing env-only deployments behave identically.
  No change to existing connections or published profiles.
- **Multi-tenant**: managed rows are tenant-scoped; one tenant cannot see or use
  another tenant's hosts.
- **Performance**: cached lookup adds no database round-trip to the hot invoke
  path beyond the TTL refresh; no blocking DNS call in async request handlers.
- **Observability**: audit rows plus counter-shaped log lines on add/remove.

## Acceptance Criteria

| # | Scenario | Expected |
|---|---|---|
| AC-1 | Switch off (default), admin opens 出站主机 | Page is read-only and explains `AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS`; add/remove API returns the disabled error |
| AC-2 | Switch on, admin adds `www.duckcoding.ai` | 201; row visible; channel with `https://www.duckcoding.ai/v1` saves and probes |
| AC-3 | Admin adds `http://www.duckcoding.ai`, `127.0.0.1`, `localhost`, or a private-resolving name | Rejected with the specific code; nothing persisted |
| AC-4 | Admin removes a host used by a channel | Subsequent save/probe/invoke fails with `model_address_not_allowed`; audit has the removal |
| AC-5 | Non-admin opens the page or calls the API | Page hidden; API 403 |
| AC-6 | Tenant A adds a host | Tenant B cannot see it and cannot use it |
| AC-7 | Env baseline contains `api.openai.com`; managed list empty | `api.openai.com` still allowed; no behaviour change |
| AC-8 | Channel save fails with `model_address_not_allowed` while the switch is on | Hint names the host and offers an allow action; after allowing, retry succeeds |
