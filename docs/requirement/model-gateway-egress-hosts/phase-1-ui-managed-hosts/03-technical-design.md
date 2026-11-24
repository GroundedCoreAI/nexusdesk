# Phase 1 · UI-managed model egress hosts — Technical Design

> Verified against the current tree on 2026-11-24: latest migration
> `0075_gateway_allowed_hosts`, allowlist in
> `platform_services/model_gateway/catalog.py::validate_address`, management
> routes in `model_gateway/management_routes.py`, console navigation in
> `frontend/src/features/models/ModelsPage.tsx`.

## Change Overview

| Layer | File | Change |
|---|---|---|
| Migration | `backend/migrations/versions/0075_gateway_allowed_hosts.py` | New `gateway_allowed_hosts` table |
| New module | `core_platform/platform_services/model_gateway/host_allowlist.py` | Normalization, public resolution, tenant-scoped store and cache |
| Core | `.../model_gateway/catalog.py` | Effective-address validation (env ∪ managed) |
| Core | `.../model_gateway/gateway.py`, `discovery.py`, `codex_route.py` | Use effective validation and call-time resolution check |
| Entry | `.../model_gateway/management_routes.py` | `GET/POST/DELETE /model-gateway/allowed-hosts` |
| Wiring | `applications/platform_runtime/platform_services.py` | Construct the store and attach it to the gateway/catalog |
| Config | `platform_services/platform_settings/settings.py` | `model_gateway_ui_allowed_hosts: bool = False` |
| Deploy | `deploy/quickstart/compose.yaml`, `deploy/README.md` | Forward the env allowlist; document the switch |
| Frontend | `frontend/src/features/models/ModelsPage.tsx`, new `AllowedHostsPanel.tsx` | 出站主机 page and inline allow action |
| Frontend | `frontend/src/i18n/index.ts`, `locales/*.json` | New error and UI copy in zh-CN/zh-TW/en/hi |
| Tests | `backend/tests/test_model_gateway_hosts.py` (new), existing gateway tests | UT/IT coverage |

## Data Model

### Migration `0075_gateway_allowed_hosts.py`

```sql
CREATE TABLE gateway_allowed_hosts (
    id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    host TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT gateway_allowed_hosts_unique UNIQUE (tenant_id, host),
    CONSTRAINT gateway_allowed_hosts_host_lower CHECK (host = lower(host))
);
CREATE INDEX gateway_allowed_hosts_tenant ON gateway_allowed_hosts(tenant_id);
```

`downgrade()` drops the table. The migration is additive and online-safe.

## Core Flow

### 1. Effective allowlist (`catalog.py`)

```python
def validate_address(self, spec):                     # unchanged: format + env list
    ...

async def validate_effective_address(self, tenant: str, spec) -> None:
    self.validate_address(spec)
    if not self.settings.model_gateway_ui_allowed_hosts:
        return
    managed = await self.hosts.effective(tenant)      # cached, TTL 15s
    host = urlsplit(spec["base_url"]).hostname.lower()
    if host in managed:
        await ensure_public_resolution(host)          # call-time private-IP check
        return
    if host not in self.deployment_hosts_lower:
        raise DomainError("model_address_not_allowed", 400)
```

- Deployment entries are checked first and remain authoritative; `"*"` in the env
  list keeps its current meaning.
- Call-time resolution is only applied to managed hosts; env-listed hosts keep
  today's behaviour.
- Call sites switched to `validate_effective_address`: `catalog.validate`,
  `catalog.resolve`, `gateway.probe`, `gateway.invoke`, `discovery.discover`,
  `codex_route.CodexProviderResolver._assert_host_allowed` (made async, tenant
  passed in).

### 2. Host validation (`host_allowlist.py`)

```python
def normalize_public_host(value: str) -> str:
    """Accept 'host' or 'https://host[/path]'; return lowercase host or raise."""

async def resolve_public(host: str) -> tuple[str, ...]:
    """getaddrinfo in a worker thread; reject empty/private/metadata results."""
```

Rules: lowercase, strip trailing dot, ASCII only (IDN must be punycode), at least
two labels, RFC 1123 label grammar, length ≤253, no IP literal, no wildcard, no
port/userinfo/query/fragment. Reject known metadata names and any resolved address
classified as private, loopback, link-local, reserved, multicast or unspecified by
the existing `agent_execution/host/network_policy.py` classifier (expose its
`_address_class` as a public `classify_address`).

### 3. Store and cache (`host_allowlist.py`)

```python
class HostAllowlistStore:
    async def effective(self, tenant: str) -> frozenset[str]   # TTL cache
    async def add(self, tenant, actor, host) -> dict            # insert + audit
    async def remove(self, tenant, actor, host) -> None         # delete + audit
    def invalidate(self, tenant: str) -> None
```

Cache: process-local `{tenant: (expires_at, hosts)}` with a 15-second TTL; `add`
and `remove` invalidate the local tenant entry. Workers converge within the TTL.
When the switch is off, `effective()` returns an empty set (managed hosts are not
effective) and mutations raise `model_host_management_disabled`.

### 4. API (`management_routes.py`)

```text
GET    /model-gateway/allowed-hosts
POST   /model-gateway/allowed-hosts        {"host": "..."}
DELETE /model-gateway/allowed-hosts/{host}
```

Admin-only (`Admin` dependency, matching existing management routes). Errors:
`model_host_management_disabled`, `model_host_invalid`, `model_host_not_public`,
`model_host_unresolved`, `model_host_exists`, `model_host_not_found`. Each
mutation writes `audit(..., "model_gateway.allowed_host.added"|"removed",
"gateway_allowed_host:"+host)` in the same transaction.

### 5. Console (`ModelsPage.tsx`)

- Add `allowed_hosts` to the `Workspace` union and render the nav button only for
  admins.
- `AllowedHostsPanel`: status banner (switch on/off), read-only deployment chips,
  managed table with add input and delete confirmation.
- Channel drawer: when `action.error` contains `model_address_not_allowed`, show
  the host from the form `base_url`; if admin and the switch is on, render an
  "allow this host" button that POSTs FR-2 and asks the operator to retry save.
- All copy goes through i18n in four locales.

## Configuration

```python
# settings.py
model_gateway_ui_allowed_hosts: bool = False   # AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS
```

The quickstart Compose file maps `AGENT_MODEL_GATEWAY_ALLOWED_HOSTS` with the
current settings defaults as its interpolation default; the production Compose
already loads `env_file: .env`.

## Security Notes

- No literal IPs, no private/metadata targets, no wildcard via the UI.
- Write-time resolution plus call-time resolution on HTTP gateway paths.
- Residual risk R-1: the HTTP client re-resolves the name when it connects, so a
  DNS-rebinding attacker could swap the record between our check and the connect.
  Mitigation is planned as a follow-up (pinned transport); the admin-only write
  path and audit trail bound the exposure.
- Residual risk R-2: the Codex CLI resolves the host itself in a child process;
  Phase 1 applies the allowlist and write-time resolution only.
- Removing a host is fail-closed; in-flight calls are unaffected, new calls fail
  with `model_address_not_allowed` after the cache TTL.

## Test Plan (summary)

| Layer | Coverage |
|---|---|
| Unit | Host normalization, IP/private/metadata rejection, URL extraction, cache TTL, switch-off behavior |
| Integration | Store CRUD + audit, tenant isolation, API RBAC, effective allowlist union, channel save/probe after add/remove |
| Regression | Existing gateway catalogue, discovery, Codex route and settings tests |

Detailed cases are in `04-test-plan.md`.

## Rollout and Rollback

- Migration adds a table only; safe online.
- Default switch `false`: no behavior change on upgrade.
- Rollback: code rollback leaves the table unused; migration downgrade drops it.
  Turning the switch off immediately removes managed hosts from the effective
  list (fail-closed) without deleting data.
