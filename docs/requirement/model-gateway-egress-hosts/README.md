# NexusDesk Model Gateway Egress Hosts · Phased Plan

> Status: Phase 1 requirements drafted (2026-11-24)
> Created: 2026-11-24

## Background

The model gateway only connects to hosts listed in the deployment setting
`AGENT_MODEL_GATEWAY_ALLOWED_HOSTS`. `Catalog.validate_address` enforces this at
channel save, connection probe, model discovery, profile resolution, gateway
invocation and the Codex route resolver. The list lives only in deployment
environment files:

- quickstart: `deploy/quickstart/.env`
- production: `deploy/production/.env`
- code: `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`

Operators who want to connect a custom OpenAI-compatible provider (for example
`https://www.duckcoding.ai`) must edit the deployment environment and restart the
backend. The console offers no view of the list and the rejection surfaces as the
generic `请求失败，请重试或联系管理员 (400 · model_address_not_allowed)`.

Two adjacent defects were found while investigating this:

1. The quickstart Compose file did not forward
   `AGENT_MODEL_GATEWAY_ALLOWED_HOSTS` into the app container, so writing it to
   `deploy/quickstart/.env` had no effect.
2. The frontend had no translation for `model_address_not_allowed`,
   `invalid_model_address` or `model_connection_requires_https`.

## Principles

1. **Deployment-owned baseline stays authoritative.** The environment list is
   always effective; the UI-managed list is additive and can never remove or
   override a deployment entry.
2. **Default off.** No deployment gains a new outbound capability until it sets
   `AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS=true`.
3. **Public HTTPS only.** UI-managed hosts must be public DNS names resolving to
   public addresses; loopback, private, link-local, reserved and metadata
   addresses are rejected.
4. **Every change is audited.** Adding or removing a host writes an audit record
   with tenant, actor, host and timestamp; no secret material is involved.
5. **Fail closed.** Removing a host (or turning the switch off) makes affected
   connections fail with `model_address_not_allowed`; it never silently falls
   back to an unvetted address.

## Phase Roadmap

| Phase | Theme | Core value | Difficulty | Estimate | Directory |
|---|---|---|---|---|---|
| Phase 1 | UI-managed public HTTPS egress hosts | Admins onboard custom providers without editing deployment env | Medium | ~3-5 days | [phase-1-ui-managed-hosts/](phase-1-ui-managed-hosts/) |

Each phase directory contains:

- `01-business-goals.md`
- `02-requirements.md`
- `03-technical-design.md`
- `04-test-plan.md`
- `05-acceptance-plan.md`
- `06-test-report.md` / `07-acceptance-report.md` after execution
- `08-implementation-breakdown.md` when useful

## Out of Scope (whole topic)

- **Private or LAN provider hosts**: rejected in Phase 1. Supporting them needs a
  separate deployment switch and private-network policy.
- **Wildcard `*` in the UI**: only the deployment environment may disable the
  hostname check.
- **Per-connection host overrides**: the allowlist is the only egress control.
- **Connect-time IP pinning for the Codex CLI**: the CLI connects directly from
  its child process; Phase 1 applies the allowlist and a save-time resolution
  check only. Residual DNS-rebinding risk is recorded in Phase 1 design.

## Review Guidance

- Phase 1 review should focus on the security boundary (public-only validation,
  DNS handling, tenant isolation, audit) and on multi-process cache propagation.
