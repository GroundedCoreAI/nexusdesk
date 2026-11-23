# Stage A · Credential Lane Security Sign-off (P6 / G5)

> Status: **SIGNED — JackChow, 2026-11-20 (GMT+8), owner and sole signatory.**
> Scope: quickstart demo only; trusted tenant `local`; Codex `codex/cli_exec/v1`.
> This record satisfies `09-stage-a-cli-engine-enablement-design.md` §4.5 and is the
> blocking signature required before the P6 credential lane merges. It does **not**
> authorize Stage B, untrusted tenants, or production multi-tenant enablement.

## Signature

| Field | Value |
|---|---|
| Signatory | **JackChow** (repository `git user.name`; owner/user) |
| Capacity | Sole security signatory for this minimal-team track |
| Date | 2026-11-20 (GMT+8) |
| Authority | Owner instruction in this session: all signatories to date are JackChow |
| Code under review | P6 code commit `107b92c` plus the docs-only sign-off appended in the same PR |
| Decision | **APPROVED for merge**, conditional on PR checks remaining green |

If the P6 code diff changes after this record is committed, this signature is void and
must be re-affirmed on the new head.

## Item-by-item evidence

### 1. Secret transport has no recording or recovery window

- `ProcessSpec.environment` and the new `credential_env_key` declaration are both
  `repr=False, exclude=True` (`host/host_models.py`). The secret-bearing child
  environment is therefore absent from `repr()`, `model_dump()`, Run snapshots,
  events and Outbox payloads.
- `host/runtime_host.py::_with_credential_env` maps the consumed secret into exactly
  one child env slot and clears the declaration afterwards. `command_digest` remains
  a hash of executable id plus argv only.
- `test_agent_execution_stage_a_credential_lane.py::test_secret_maps_to_declared_key_and_never_serializes`
  and `::test_legacy_callers_keep_the_original_credential_slot` prove the canary
  cannot be recovered from `repr`, `model_dump` or `command_digest`.
- Existing broker/audit invariants remain green:
  `test_execution_credentials.py::test_audit_rows_are_secret_free`,
  `test_execution_r2_reservation_and_secret.py`.
- `reconcile()` now revokes in-memory grants for foreign-boot rows
  (`test_agent_execution_stage_a_credential_lane.py::test_reconcile_revokes_a_foreign_boot_grant`).

### 2. `credential_env_key` allowlist is closed and mismatch fails closed

- `CODEX_CREDENTIAL_ENV_KEYS` in `contracts/config.py` is a deployment-owned frozenset
  (`OPENAI_API_KEY`); clients cannot add keys.
- `CodexEngineHomeConfig` validates the key against that set before rendering the
  key-free `config.toml`, and `write_private_engine_config` writes the same declared
  name into `env_key` (`adapters/codex/home_config.py`).
- The adapter refuses a credential reference when no private-home config or broker is
  present; `credential_env_key` only reaches `ProcessSpec` from the validated config.
- Tests: `test_env_key_allowlist_is_closed`,
  `test_renderer_rejects_non_https_and_injection_shaped_values`, and
  `test_agent_execution_stage_a_contract.py::test_codex_reference_and_path_env_snapshot_only_at_the_typed_path`.

### 3. Tenant / Execution / Workspace / Engine binding is revalidated per start

- The adapter converts the published UUID reference and supplies an explicit audience
  (`engine_id=codex`, `protocol_id=cli_exec`, `workspace_id=request.workspace_id`) instead
  of relying on Host defaults (`native`/`default`). Missing broker, private home or
  workspace id fails closed with `ENGINE_UNAVAILABLE`.
- Broker `issue` and `consume` continue to check tenant, run/lease, engine, protocol,
  workspace, scope, expiry and one-time grant use; there is no read-secret API.
- Tests: `test_adapter_passes_reference_and_explicit_audience`,
  `test_adapter_fails_closed_without_broker_or_workspace`,
  `test_adapter_rejects_a_non_uuid_reference`, and existing
  `test_execution_credentials.py::test_grants_bind_run_engine_workspace_scope_and_ttl`,
  `::test_grant_denials_cover_expiry_revocation_scope_and_tenant`.

### 4. Per-Execution `CODEX_HOME` cleanup is proven

- P3 creates a 0700 no-follow private home inside the validated Run workdir; P5 writes
  `config.toml` at 0600 through the same no-follow primitive and denies planted
  symlinks (`test_agent_execution_stage_a_engine_home.py::test_writer_denies_a_planted_symlink`).
- The home is cleaned with the durable workdir lifecycle; `cleanup_failed` stays
  terminal (`test_agent_execution_stage_a_workspace.py`, phase 4 runtime-host cleanup
  tests). No host `~/.codex` path is ever mounted.
- Broker grants are revoked on `wait`, `cancel`, `close` and now foreign-boot
  `reconcile`, so a lost process does not leave a live grant beside a stale home.

### 5. C1/C2 and AC-6 adversarial cases re-run with the lane enabled

- Quickstart compose mounts only two parameterized read-only directories with an empty
  in-repo default; tests assert no `/home/`, `.codex`, `auth.json` or whole-home mount
  (`test_quickstart_codex_mounts_are_narrow_and_read_only`).
- The config template contains only provider metadata and a variable name, never a
  value (`test_quickstart_codex_template_is_key_free`).
- Credential admin routes remain tenant/role scoped with no secret-read endpoint
  (`test_execution_credentials.py::test_credential_admin_routes_are_tenant_role_and_secret_safe`),
  and cross-tenant use is denied by the Broker binding tests above.
- Local full backend suite at the signed code head: **2389 passed / 636 skipped**;
  skipped lanes are declared `pending_env` placeholders (PostgreSQL integration,
  real Codex binary, opt-in migration/env drills), not self-skips introduced by P6.
  PR checks must be green before merge.

## Boundary

This signature authorizes only the quickstart-demo credential lane described in design
`09` §4. Stage B (`codex/app_server`), untrusted tenants, production multi-tenancy and
host-home credential mounts remain locked and require separate records.
