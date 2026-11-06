# Phase 6 · Security, Reliability, and Event Governance — Business Goals

> Status: Pending review (planning only, not implemented; a blocking phase before untrusted multi-tenant code execution)
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 3, 7–10, 12–13, 17 (Phase 6), 18.2/18.4/18.6, and 19–22; see `03-technical-design.md` for the current-state audit

> Phase: Phase 6 (security, execution reliability, and event reliability workstreams accepted under one hard gate)
> Estimated effort: approximately 6–8 weeks, frozen after design review and fault-drill environment confirmation
> Dependencies: Phases 0–5 accepted; Phase 4 RuntimeHost/Workspace available; production-like environment supporting fault injection, sandbox adversarial tests, and independent security audit

## Problems to Solve

### Problem 1: Existing encrypted credentials are not an Execution-level security boundary

The current `CredentialVault` primarily serves model-gateway connections. It lacks short-lived Engine Execution grants, target/scope binding, revocation, Broker audit, and common redaction. If external Engines such as Codex inherit host credentials or long-lived environment variables directly, cross-tenant and post-execution disclosure risks increase.

### Problem 2: Logical Workspace and tool network policies cannot replace a strong sandbox

Existing Workspace/tool egress controls provide local protection, but untrusted Agent commands require combined process, mount, file, network, syscall, and resource isolation. Path traversal, symlinks, DNS rebinding, cloud metadata access, and host escape must be tested as attack surfaces rather than inferred from configuration presence.

### Problem 3: Owner/lease terminal protection still lacks cross-Worker Fencing

The current Repository rejects some expired-owner writes, but no monotonically increasing Lease Epoch/Fencing Token covers every event, result, usage, Session, Outbox, and resource operation. Worker loss, lease-renewal races, late results, and retry side effects can still create inconsistencies.

### Problem 4: Durable-event and SSE precedents are not yet a complete reliable-delivery system

Events and Runs currently commit in one transaction and SSE supports cursor replay, while NOTIFY only wakes readers. However, common schema/version/source/event_id, native-event deduplication, transactional Outbox, retained-cursor gap handling, and idempotent usage aggregation are missing. Parser failures also lack bounded, redacted, measurable diagnostics.

## Business Goals

| Goal | Description |
|---|---|
| G1: Establish an Execution credential security lifecycle | Vault/Broker provides encryption, versions, scopes, short-lived grants, rotation, revocation, and audit, with credentials minimally exposed only inside authorized Executions. |
| G2: Establish strong isolation for untrusted execution | Strong sandbox, default-deny networking, file/mount isolation, and resource limits operate together and pass real escape/exfiltration attacks. |
| G3: Guarantee execution ownership and recovery consistency | Lease Epoch/Fencing blocks every effective stale-Worker write; Worker loss, late results, cancellation, and cleanup produce consistent terminal states. |
| G4: Make side effects and quotas recoverable | Retries are classified by error and side effects; processes, Workdirs, connections, resource reservations, and quotas release correctly after success, failure, cancellation, timeout, and crash. |
| G5: Establish a versioned reliable-event system | Schema, sequence, event_id, deduplication, transactional Outbox, and SSE replay jointly provide traceable, replayable delivery without silent gaps. |
| G6: Ensure idempotent usage and diagnosable parsing | Duplicate/late usage never double-aggregates or double-bills; native parse failures produce bounded, redacted, correlated diagnostics and explicit fallback behavior. |
| G7: Preserve compatibility and verifiable release | React/Codex, existing Run/API/SSE, and historical data migrate and roll back safely; unmeasured baselines remain pending Phase 0, and averages cannot substitute for security/reliability hard metrics. |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| Execution credential escalation and plaintext disclosure | Unmeasured; security baseline pending Phase 0 | Zero unauthorized grants, cross-tenant/cross-Execution use, or plaintext disclosures in adversarial cases; 100% of new uses denied after revocation. |
| Sandbox/file/network escapes | Unmeasured; pending Phase 0 | Zero successful escapes, metadata access, or unauthorized egress in the planned attack matrix; any P0 stops exposure. |
| Effective stale-Worker commits | Unmeasured; pending Phase 0 | Zero stale state, event, usage, Session, or Outbox commits under fault injection, with Fencing-denial audit evidence. |
| Worker-loss and late-result consistency | Unmeasured; pending Phase 0 | 100% of cases enter a defined recoverable or terminal state; zero late-result overwrites, dual terminal states, or duplicate side effects. |
| Cancellation acknowledgment and cleanup/quota consistency | Unmeasured; pending Phase 0 | 100% of cases confirm actual exit/cleanup; unconfirmed cases never report cancelled; no residual reservations or quota leaks. |
| Event persistence/Outbox atomicity | Unmeasured; pending Phase 0 | Under fault-point injection, zero partial-state-without-terminal-event, event-without-Outbox, or duplicate business effects. |
| SSE replay completeness | Basic cursor replay exists; completeness/scale unmeasured pending Phase 0 | No silent gaps within retention; reconnect deduplicates by event_id, and terminal state agrees with the final event. |
| Duplicate usage aggregation/billing | Unmeasured; pending Phase 0 | Zero duplicate counting for the same source under duplication, replay, or Worker retry; corrections remain traceable. |
| Parser diagnostic coverage and disclosure | Unmeasured; pending Phase 0 | Every malformed/unknown native event yields a bounded classified diagnostic; zero Secret canary disclosures and no diagnostic event storms. |
| Security and reliability overhead | Unmeasured; pending Phase 0 | Record p50/p95, Outbox lag, and recovery time; review budgets after baseline and never claim zero performance impact before measurement. |
| Existing-behavior regression differences | Unmeasured; pending Phase 0 | Zero diff in compatibility and rollback scenarios, with applicable existing suites green. |

## Scope

**Included**:

- Execution Credential Vault/Broker, typed Secret references, short-lived grants, target/scope binding, rotation/revocation/audit, and common redaction.
- Strong Sandbox Provider, default-deny network egress, DNS/IP/redirect protection, file/mount/artifact isolation, and resource limits.
- Lease Epoch/Fencing Tokens, Worker-loss detection, late-result/terminal protection, cancellation confirmation, timeout cleanup, retry side effects, and quota release.
- Event schema/version/source/event_id/sequence, deduplication, Event Store/transactional Outbox, SSE reconnect/cursor replay, and retention-gap handling.
- Idempotent usage aggregation, parser diagnostics, migration/backfill/reconciliation jobs, metrics/alerts, and adversarial/fault-injection drills.
- Planned migrations `0056_execution_fencing_event_outbox` and `0057_execution_credential_security`, plus compatible rollout and rollback plans.

**Excluded** (later phase / explicitly out of scope):

- New Engines, multi-Engine routing/fallback, global fair scheduling, and complete cost reporting: Phase 7 or later.
- Microservice decomposition, separate Task/Execution dual-table model, or wholesale scheduler rewrite: retain the modular monolith and Run=one Execution attempt.
- Vendor-specific external KMS/Secret Manager integration: this phase defines replaceable Vault/Broker interfaces and an installation-key implementation; vendor adapters follow deployment demand.
- Indefinite retention of raw events, unredacted payloads, or Secrets; no promise of complete SSE replay beyond retention.
- Treating “trusted tenant” as an exemption from this phase's security acceptance, or opening untrusted code execution before any hard gate passes.
- This phase modifies no historical migrations and does not describe current partial protections as complete target capabilities.

## Risks and Constraints

- **Migration/backfill races**: New event_id, epoch, and Outbox must coexist with old Workers; use expand/backfill/validate/switch, recheck planning numbers against head before implementation, and never modify historical migrations.
- **Incomplete Fencing coverage**: Protecting only Run state still leaks events or usage; every Repository/resource operation accepting Worker writes must validate `(run_id, owner, lease_epoch)`.
- **Timeout does not prove no side effects**: The process may already have performed external writes; ambiguous outcomes do not auto-retry by default and require idempotency keys/side-effect evidence or manual recovery.
- **Cancellation confirmation versus availability**: If process termination cannot be proven, do not report cancelled for UI convenience; enter explicit failure/pending-cleanup handling and alert while resources remain isolated.
- **Redaction false positives and negatives**: Replacing known Tokens alone is insufficient; combine registered Secrets, canaries, common patterns, structured fields, and artifact isolation, with bounded raw diagnostics excluded from ordinary events.
- **Outbox is not a notification bus**: NOTIFY/SSE remains an acceleration layer and the Event Store is the source of truth; Outbox publication retries safely and cannot block security denial or fabricate completion.
- **Untrusted exposure is a hard gate**: If Vault/Broker, strong sandbox, network/file isolation, Fencing/recovery, event consistency, or adversarial acceptance is incomplete, untrusted tenants must not be enabled.
- **Compatibility**: Add columns/tables through backward-compatible expansion, and keep existing SSE `id` as the Run-local sequence; rollback must not require deleting credential or event data.
