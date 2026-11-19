# Execution platform examples

Quickstart starts with a persistent, synthetic dataset for the
`agent-execution-platform-v2` capabilities. It is generated automatically on
**every** `sh nexusdesk quickstart` start, after the workspace/industry/memory
seeds and before the API serves traffic. Production `migrate` never installs it.

The seed module is
`backend/src/agent_platform/applications/seed_execution_platform.py`.

## What is installed

All rows are deterministic, tenant-scoped and idempotent. Re-running the seed
preserves existing rows and operator edits; the JSON report printed by the
module contains `created` and `preserved` counts only.

| Group | Demo data | Phases |
|---|---|---|
| Model chain | sample connection/model/chat profile, profile published | 0, 3 |
| Agents | one published agent execution platform demo agent with a config snapshot, one unpublished draft | 0, 2, 3 |
| Conversations | `execution-platform-published` (agent bound) and `execution-platform-legacy` (`agent_id = NULL`) | 2 |
| Runs | `completed`, `cancelled`, `failed` terminal states | 0, 2, 6 |
| Events | 3 ordered events per Run, including the correct terminal event; 9 published Outbox rows | 1, 2, 6 |
| Phase 3 snapshots | config, declared/available/effective capability and policy snapshots on the completed Run | 3 |
| Workspace evidence | one `cleanup_failed` workdir and one exited, explicitly synthetic host process on the failed Run | 4 |
| Credential | one canary execution credential with metadata only; no grant, no real secret | 6 |
| Audit | one `execution_platform_seed` record with no secret values | 1, 6 |

Display names follow `AGENT_SEED_LOCALE`; identity keys, UUID seeds and
external IDs never change with locale. The credential secret is a fixed canary
string and is never returned by the metadata API. If the execution credential
key is unavailable, the seeder fails closed for that one item and still
installs everything else.

## Phase walkthrough

Use `https://localhost:8080` and the quickstart login. All data is under the
configured tenant (`local` by default).

> The quickstart deployment keeps the Phase 3 switches fail-closed, so the
> agent form shows the read-only execution view only. To surface the
> capability preview and narrowing entries, start the stack with both
> `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true` and
> `AGENT_EXECUTION_PHASE3_ENABLED=true` (the console warns when phase 3 is on
> while the orchestrator is off). Runtime Host, Codex and Stage B stay off;
> see deploy/README.md for their switch combinations.

1. **Phase 0 — baseline.** Open the Agent list: one published agent execution platform demo
   agent and one draft. Inspect the three terminal Runs; each has one terminal
   event and no contradictory state.
2. **Phase 1 — contracts.** Call `/api/v1/runs/{id}` for a seeded Run and
   `/api/v1/ready`; the DTO shape is stable. Inspect the audit row for
   `execution_platform_seed` — it contains no secret.
3. **Phase 2 — orchestrator paths.** Compare the published conversation with
   the legacy conversation. The completed Run config contains
   `execution_config_snapshot_marker`; the legacy Runs have no Agent binding.
   Replay its events:

   ```bash
   curl -ksS -N -H "Authorization: Bearer $TOKEN" \
     "https://127.0.0.1:8080/api/v1/runs/<run-id>/events?after=0"
   ```

   Events arrive as `run.queued`, `run.started`, then the matching terminal
   event. `Last-Event-ID: abc` is rejected as an invalid cursor.
4. **Phase 3 — capability/config snapshots.** Open the published Agent draft
   to see the bound model profile and disabled Stage B capabilities. The
   completed Run carries all five snapshot columns; the legacy Runs leave them
   null so the compatibility path remains distinguishable.
5. **Phase 4 — workspace cleanup.** Inspect the failed Run's workdir: status
   `cleanup_failed`, error `execution_demo_cleanup_failed_sample`, with an
   attached exited process whose metadata says `real_process: false`. No real
   process or filesystem resource is created.
6. **Phase 5 — Codex posture.** Confirm the demo explicitly does **not**
   install a real Codex session: `codex_cli_enabled` and
   `codex_app_server_enabled` stay false and Stage B remains locked. The
   synthetic fixture never stands in for a real CLI run.
7. **Phase 6 — security/events.** Call `/api/v1/execution-credentials`: only
   credential metadata is visible. Inspect the Outbox rows for the seeded
   Runs (all `published`), and the fencing-denial/usage tables — the seed adds
   no rows to either. High-risk switches remain off.

## Boundaries

This is customer-facing demonstration data, not acceptance evidence. It does
not enable Runtime Host, Codex, untrusted tenants, Stage B or any other
high-risk capability; it does not create credential grants, usage records,
fencing denials or real processes; and it does not simulate cgroup/quota/mount
limits, multi-Worker faults, performance measurements or CI provenance. Those
items require their own controlled environments and reports.

## Manual re-run and removal

Automatic startup is normally enough. To re-apply the idempotent seed inside
the app container:

```bash
docker compose -f deploy/quickstart/compose.yaml exec app \
  python -m agent_platform.applications.seed_execution_platform
```

To start from a clean quickstart database, recreate the volume:

```bash
docker compose -f deploy/quickstart/compose.yaml down -v
sh nexusdesk quickstart
```
