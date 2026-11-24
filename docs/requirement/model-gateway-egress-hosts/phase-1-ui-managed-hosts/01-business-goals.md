# Phase 1 · UI-managed model egress hosts — Business Goals

> Phase: Phase 1 (iteration)
> Estimate: ~3-5 days
> Dependencies: existing model gateway catalogue, settings and console

## Problems

### Problem 1: Custom providers require a deployment change and a restart

`Catalog.validate_address` reads only
`Settings.model_gateway_allowed_hosts`. Adding `https://www.duckcoding.ai` means
editing `deploy/production/.env` (or `deploy/quickstart/.env`) and restarting the
backend. An administrator who is allowed to create channels in the console cannot
complete the workflow without server access.

### Problem 2: The rejection is opaque

The API returns `400 model_address_not_allowed`; the console has no translation
for it, so the operator sees
`请求失败，请重试或联系管理员 (400 · model_address_not_allowed)` with no hint
about the allowlist or how to change it.

### Problem 3: Quickstart cannot configure the list at all

`deploy/quickstart/compose.yaml` did not map
`AGENT_MODEL_GATEWAY_ALLOWED_HOSTS` into the app container. Writing the variable
to `deploy/quickstart/.env`, as the deployment README instructs for other
settings, had no effect.

## Business Goals

| Goal | Description |
|---|---|
| G1: Self-service onboarding | An administrator can add a public HTTPS provider host in the console and immediately save/probe the channel without a deployment change. |
| G2: Preserved security boundary | Only public HTTPS DNS names can be added; private, loopback, link-local, reserved and metadata addresses remain rejected, and every change is audited. |
| G3: Zero impact while disabled | With `AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS=false` (default), effective behaviour is byte-identical to the current env-only allowlist. |
| G4: Actionable errors | A blocked address tells the operator which host was rejected and, when management is enabled, offers an inline allow action. |

## Success Metrics

| Metric | Baseline | Target |
|---|---|---|
| Time to onboard a custom public provider | edit env + restart backend (server access required) | < 2 minutes through the console, no restart |
| Private/metadata hosts accepted through the UI | not applicable (no UI) | 0 by automated validation |
| Existing deployments changed by upgrade | not applicable | 0 when the new switch keeps its default `false` |

## Scope

**Included**

- Database table and admin API for UI-managed egress hosts.
- Effective allowlist = deployment env list ∪ enabled UI-managed list.
- Public-HTTPS host validation with resolution checks at write time and at call
  time for gateway HTTP paths.
- Console page under model gateway, plus inline "allow this host" on the channel
  save error.
- Audit records for add/remove.
- Quickstart Compose mapping and i18n error copy already drafted locally.

**Not included**

- Private/LAN/self-hosted provider hosts.
- Wildcard `*` managed from the UI.
- Connect-time IP pinning for the Codex CLI child process.
- Per-tenant independent egress policies beyond the existing tenant scoping.

## Risks and Constraints

- **SSRF / DNS rebinding**: a hostname can resolve to a public address at write
  time and a private one later. Mitigation: write-time resolution validation,
  call-time resolution checks on HTTP gateway paths, and no literal IPs. Residual
  risk is recorded in the technical design; full IP pinning is a later hardening
  item.
- **Multi-process propagation**: API and workers are separate processes. A
  changed host list becomes visible to workers within a short cache TTL; removal
  is fail-closed, never fail-open.
- **Compatibility**: the feature is additive and disabled by default. Turning the
  switch off ignores UI-managed hosts; connections that depend on them fail with
  `model_address_not_allowed` until re-enabled or moved to the env list.
- **Operational responsibility**: the deployment administrator remains
  responsible for the env baseline; the UI list cannot weaken it.
