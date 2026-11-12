# Agent Execution Orchestrator Rollout and Rollback Runbook

This runbook covers the Phase 2 `react/native/v1` execution path. It only switches an in-process branch in the existing Runtime Worker; it adds no UI, service, client field, or second ReAct implementation. The default remains the existing legacy path. This document is not a production performance acceptance result.

## 1. Switch and invariants

- Every API/Worker process reads `AGENT_EXECUTION_ORCHESTRATOR_ENABLED` at startup; the default is `false`. An off Worker uses legacy execution, while an on Worker uses only the Orchestrator.
- After changing the environment value, recreate the container or perform a rolling restart of the selected process with the process manager. `docker compose restart` restarts the old container and does not apply new environment values from compose/.env.
- This is neither request-level hot switching nor automatic per-Run fallback. If an on Worker lacks a valid Orchestrator/registry entry or execution fails, the existing error contract applies; it must not silently switch to legacy.
- The API can remain off while an on Worker claims its queued Run. The switch is excluded from the runtime-composition fingerprint, so an off API, on Worker, and mixed Workers do not produce `configuration_changed` because of this setting alone. All other runtime configuration must remain consistent.
- Repository remains the sole terminal-state writer. Rollout requires no Alembic downgrade, data repair, client change, or new service.

## 2. Pre-rollout checks

1. Deploy the same version containing this switch with every API and Worker initially set to `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false`; complete normal migration and startup. The API uses its existing healthcheck; `runtime-worker` has no healthcheck and must be assessed through the process, log, and queue observations in sections 3 and 6. Do not merely edit `.env` and run `docker compose restart`.
2. Confirm that the fixed tuple is `react/native/v1` and that model, Profile, tool, and other runtime settings match except for this switch.
3. Save a non-sensitive baseline: Worker instance identities and switch values, `queued/running/terminal` counts, existing error rate, SSE/terminal checks, and raw latency samples. Use `run_id` only in authorized log/trace queries.
4. Assign stop conditions and a rollback owner. Do not combine canary rollout with schema upgrades, client protocol changes, or additional Worker services.

Run every command in this runbook from the repository root. Production values come from `deploy/production/.env`. These basic checks validate configuration and inspect status without printing connection strings or credentials:

```bash
docker compose --env-file deploy/production/.env \
  -f deploy/production/compose.yaml config -q
docker compose --env-file deploy/production/.env \
  -f deploy/production/compose.yaml ps
```

## 3. Canary rollout

### 3.1 Enable only selected Workers

Under systemd, Kubernetes, or another process manager, override `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true` only on the selected runtime Worker instances/Deployment, then recreate those instances in a rolling batch. Do not change shared API configuration or broadcast the value to every Worker. Keep the remaining Workers off, confirm that each new process has started, and assess readiness through running state, logs, the existing external probe (if the environment provides one), and queue/claim/terminal observations; do not wait for a nonexistent Worker healthy state.

In an existing production compose environment, you can start with **one one-off canary container**. It reuses the same `runtime-worker` service definition, image, network, and credentials; it is not a new service:

```bash
docker compose --env-file deploy/production/.env \
  -f deploy/production/compose.yaml run --rm --no-deps \
  --name nexusdesk-runtime-orchestrator-canary \
  -e AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true \
  runtime-worker
```

Prerequisites are a successful normal migrate step, an available database, and an existing off `runtime-worker`. `--no-deps` does not rerun migration. `-e AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true` overrides only this one-off `runtime-worker` container; it neither modifies `deploy/production/.env` nor changes the API or other services. This container and off Workers both claim work under the existing queue rules. The queue does not route by execution path, so this command cannot pin a particular Run to the canary. Submit low-risk Runs first and verify off API → on Worker claiming and terminal behavior before expanding.

Stop the canary by interrupting it in its terminal, or run:

```bash
docker stop nexusdesk-runtime-orchestrator-canary
```

Confirm that the one-off container has exited and that in-flight work converges under the existing Lease/reaper lifecycle. For a sustained canary, use the process manager to maintain the selected Workers instead of leaving an unattended one-off container.

### 3.2 Queue and existing rows with mixed Workers

- **queued**: Both off and on Workers can claim rows under the existing atomic claim rules. Only one owner can acquire a queued row; mixed deployment neither shares execution context nor permits an active row to be claimed again by the same execution.
- **running**: The original owner, heartbeat, Lease, cancellation, and reaper rules remain authoritative. Changing the switch or restarting does not let the other path take over the same execution and must not cause dual execution. Recovery after lease loss uses only the existing Lease/reaper semantics; no automatic retry is added.
- **terminal**: First-commit-wins remains in force. Completion, cancellation, reaping, and late finish/append retain their existing race behavior; rollout or rollback never rewrites a terminal state.

Before expanding, observe at least one complete in-flight convergence window. Verify that there are no duplicate owners/terminal states, off/on outputs and events are equivalent, cancellation/timeout/worker_lost classification is unchanged, queued work has no abnormal backlog, terminal rows are unchanged, and the fingerprint does not report `configuration_changed`. Go to section 6 immediately if any stop condition is met.

## 4. Observability and security boundaries

Worker terminal logs for the new path use low-cardinality fields:

- `path=orchestrator`
- `tuple=react/native/v1`
- `status=completed|failed|cancelled`
- Failed logs always contain `error=execution_failed`; completed/cancelled logs contain no `error` field.
- Every terminal log contains a finite, non-negative `duration_ms`.

Authorized operators can correlate logs/traces by `run_id` and then inspect Run state, SSE, and persisted events. Never put raw legacy error codes, unknown future Provider codes, raw exceptions/stacks, prompt/input/history, customer data, configuration, or credentials into logs/traces. Metrics must not contain `run_id`; use only the low-cardinality `path/tuple/status/error` labels above. Never fabricate traces, metrics, or production logs.

`duration_ms` is one Worker execution measurement and cannot demonstrate end-to-end production performance. Preserve raw performance evidence according to acceptance plan 05 section 4: in the same real equivalent environment with identical input and configuration, collect at least 30 valid matched pairs after five excluded matched warm-up pairs, using alternating or balanced off/on order. Preserve old/new end-to-end latency, paired delta/ratio, raw Adapter overhead, first-token latency, and error rate separately. Use nearest-rank p95, and do not subtract external model/tool latency from end-to-end measurements. A single log entry, demo/mock/test double, or canonical diff cannot support a claim of “production regression ≤5%”. If the environment is insufficient, keep the performance sub-metric `pending_env`.

## 5. Controlled expansion and verification

Expand only one Worker batch at a time, repeat sections 2–4, and retain the instances, timestamps, switch values, and observation window for each batch. Confirm that new processes actually picked up the value rather than merely editing a configuration file. Continue to verify:

1. Runs submitted through an off API can complete on an on Worker, and mixed Workers never claim the same row twice.
2. Existing queued rows remain readable and claimable, running rows converge only under their original owner/Lease, and terminal rows remain unchanged.
3. Failures on the on path never silently fall back; log labels and `duration_ms` are valid and contain neither sensitive data nor future codes.
4. Results, events, SSE, cancellation, timeout, Lease/reaper, and terminal rules remain unchanged between paths.

## 6. Emergency rollback

### 6.1 Stop conditions

Stop expansion and roll back upon any of the following: duplicate execution/terminal state, rewritten terminal state, unexpected `configuration_changed`, silent fallback from a failed on path to legacy, sensitive-data or future-code leakage, non-finite/negative `duration_ms`, incorrect cancellation/lease-loss classification, persistently abnormal queued backlog, broken SSE/result parity, or error rate/real matched-pair latency beyond the approved threshold.

### 6.2 Procedure

1. Stop launching new on Workers and stop the one-off canary.
2. Restore `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false` on every Worker and recreate/rolling-restart them in batches. Keep APIs off as well; do not rely on request-level switching.
3. For a long-running compose-managed `runtime-worker`, force recreation with the new environment instead of using `restart`:

   ```bash
   docker compose --env-file deploy/production/.env \
     -f deploy/production/compose.yaml up -d --no-deps \
     --force-recreate runtime-worker
   ```

   Use the equivalent rolling recreation for each Worker batch under other process managers. If other production compose Workers were started from the same shared `.env`, first confirm that their configuration is also false, then recreate them batch by batch rather than switching every process at once.
4. For each batch, first confirm that the target containers are running, inspect startup/path logs for anomalies, and use the existing external probe if the environment provides one. Then use queue, claim, and terminal observations to confirm Worker readiness and convergence of old in-flight work under its original owner/heartbeat/Lease/reaper before proceeding. `runtime-worker` has no Docker healthcheck: running does not mean healthy, and you must not wait for a nonexistent healthy state. The existing API healthcheck applies only to the API and cannot establish Worker readiness. Off Workers continue to claim queued work; the same request is not automatically retried through fallback.
5. Verify that terminal rows still follow first-commit-wins, lease loss is recovered only by the existing Lease/reaper, and no existing rows are repaired. After rollback, newly claimed Runs on off Workers should use only the legacy path.

**Completion criteria**: every Worker is false and running in a new process; the one-off canary has exited; there are no duplicate owners/terminal states or abnormal queued backlog; in-flight work has converged; terminal rows are unchanged; and subsequent Runs match the legacy baseline. If these conditions are not met, keep rollout stopped and follow the existing Run/Lease incident procedures rather than hiding the problem with data repair.

Rollback performs no Alembic downgrade, no runtime-data repair/rewrite, no client change, and no new service. Controlled T7 rehearsal evidence is stored outside the repository; formal T8/T9 conclusions require independent later testing and human acceptance.
