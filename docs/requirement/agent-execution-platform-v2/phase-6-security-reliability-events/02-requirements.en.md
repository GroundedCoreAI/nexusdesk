# Phase 6 · Security, Reliability, and Event Governance — Requirements

> Status: Pending review (planning only, not implemented)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G7); `docs/architecture/agent-execution-platform-v2.md`, Sections 7–10, 12, 17 (Phase 6), and 18.2/18.4

## User Stories

**US-1 (Security administrator)**: As a security administrator, I want to issue short-lived credential grants by tenant, Agent, Execution, and Engine and revoke them immediately so that credential exposure is minimal in time and scope.

**US-2 (Platform operator)**: As a platform operator, I want untrusted commands to run in a strong sandbox with default-deny network/file access so that prompt injection or malicious input cannot reach the host or other tenants.

**US-3 (Worker/runtime developer)**: As a Worker/runtime developer, I want every claim to carry a monotonic Fencing Token and every write to validate ownership so that stale Workers cannot contaminate newer attempts.

**US-4 (SRE)**: As an SRE, I want Worker crashes, hung processes, cancellation, and timeouts to recover and release resources/quotas so that failures cannot leave permanent running states, orphaned processes, or capacity leaks.

**US-5 (Client developer)**: As a client developer, I want stable event versions, ordering, and deduplication IDs, with replay after SSE disconnect and explicit gap handling, so that I can build reliable, non-duplicating user experiences.

**US-6 (Finance and audit staff)**: As finance and audit staff, I want duplicate usage from one source never to bill twice and every correction to remain traceable so that usage data is trustworthy.

**US-7 (Adapter developer)**: As an Adapter developer, I want malformed/unknown native events to produce bounded redacted diagnostics without overwhelming the event stream so that protocol upgrades can be diagnosed without Secret disclosure.

## Functional Requirements

### FR-1 Execution credential Vault and lifecycle

| Item | Description |
|---|---|
| Trigger | When creating, reading, rotating, revoking, deleting, or recovering Engine credentials. |
| Input | Trusted tenant/administrator identity, credential type, Secret, allowed Engine/Workspace scope, version, and installation-key/KMS interface. |
| Output | Encrypted credential records, non-readable Secret references, version/status, and audit without plaintext. |
| Execution mode | Management operations use synchronous transactions; runtime accesses credentials only by reference, and public configuration never returns Secrets. |
| Failure handling | Missing keys, decryption/binding mismatch, revocation, and expired versions all fail closed; a lost master key is never recreated automatically. |

### FR-2 Credential Broker short-lived grants

| Item | Description |
|---|---|
| Trigger | At Execution launch, Session Resume, credential rotation/revocation, or grant expiration. |
| Input | Current authentication context, tenant/agent/run, Engine/Protocol, Workspace, credential version, scopes, and expires_at. |
| Output | A short-lived grant or Secret mount bound to Execution/audience/scope, plus grant/denial/use audit. |
| Execution mode | Authorize synchronously before launch and expose minimally at runtime; grants cannot transfer across Executions. |
| Failure handling | Cross-tenant, cross-Engine, expired, revoked, replayed, or scope-expanding use is denied; Resume reauthorizes and old grants are not authorization credentials. |

### FR-3 End-to-end Secret redaction and disclosure response

| Item | Description |
|---|---|
| Trigger | Before writing logs, events, SSE, errors, audit, parser diagnostics, artifact metadata, or alerts. |
| Input | Registered Secret fingerprints/canaries, structured sensitive fields, common Token patterns, and output-size bounds. |
| Output | Stable placeholders, redacted diagnostics, and disclosure security events; raw Secrets do not enter ordinary storage. |
| Execution mode | Redact synchronously at trust boundaries; scan, quarantine, or deny artifact publication according to policy. |
| Failure handling | Diagnostics that cannot be deemed safe are private by default; disclosure immediately revokes affected credentials, stops new executions, and retains Secret-free forensic references. |

### FR-4 Strong sandbox and resource limits

| Item | Description |
|---|---|
| Trigger | Before and during any Engine Execution capable of running untrusted code/commands. |
| Input | Trust level, Sandbox Provider, unprivileged identity, root/mount policy, and CPU/memory/PID/disk/time limits. |
| Output | Isolated RuntimeHost instance, effective policy snapshot, resource metrics, and destruction evidence. |
| Execution mode | Create and validate the sandbox synchronously before launch and supervise asynchronously; Agent configuration cannot expand security policy. |
| Failure handling | Unavailable sandbox, excessive privilege, unenforceable limits, or detected escape denies/terminates and alerts; never degrade to direct host execution. |

### FR-5 Sandbox network egress policy

| Item | Description |
|---|---|
| Trigger | When an Engine or child process attempts DNS, connection, redirect, or proxy traffic. |
| Input | Default-deny policy, destination host/IP/port, DNS resolution results, and tenant/Execution allowlist. |
| Output | Only authorized connections pass, with redacted network audit and denial metrics. |
| Execution mode | Decide synchronously at the sandbox network boundary; validate every hop and actual connected IP, not only URL strings. |
| Failure handling | Private/link-local/metadata addresses, DNS rebinding, unauthorized redirects, and tunnel/proxy bypass are denied; failures never open access automatically. |

### FR-6 Filesystem, mount, and artifact isolation

| Item | Description |
|---|---|
| Trigger | When creating Workdirs, mounting, reading/writing, exporting artifacts, and cleaning up. |
| Input | tenant/workspace/execution, canonical paths, read-only/read-write policy, file type/size, and artifact authorization. |
| Output | Per-Execution file view, authorized artifacts, complete cleanup, and escalation audit. |
| Execution mode | Validate at both sandbox and Workspace Provider layers; path resolution prevents TOCTOU and mounts are minimal. |
| Failure handling | Traversal, symlink/hardlink, device files, sensitive host paths, cross-tenant access, and unauthorized overwrite are denied; suspicious artifacts are not exported after failure. |

### FR-7 Full Lease Epoch / Fencing Token coverage

| Item | Description |
|---|---|
| Trigger | At claim, heartbeat, takeover, and every Worker/Host write or resource release on behalf of an Execution. |
| Input | run_id, owner, monotonic lease_epoch, lease validity, and operation idempotency key. |
| Output | Conditional writes that succeed only for the current epoch; stale operations receive stable denial and audit. |
| Execution mode | The database increments epoch in claim/takeover transactions; state, events, usage, Sessions, Outbox, and resource operations use the same ownership evidence. |
| Failure handling | Owner/epoch/lease mismatch cannot produce partial writes; application-level read-then-write cannot replace database conditional updates/constraints. |

### FR-8 Worker loss, late results, and terminal-state protection

| Item | Description |
|---|---|
| Trigger | On heartbeat failure, lease expiration, Worker crash, late old result/event, or recovery takeover. |
| Input | Run/epoch, last heartbeat, Host liveness evidence, current terminal state, and recovery policy. |
| Output | Defined recoverable state or one terminal state, Fencing-denial record, cleanup/alert, and final event. |
| Execution mode | Detection and takeover are transactional; fence the old epoch before choosing recovery or failure, with no two effective Workers. |
| Failure handling | If external side effects or process state are uncertain, do not blindly retry/complete; late success cannot overwrite cancelled/failed/new epoch. |

### FR-9 Cancellation confirmation, timeout cleanup, and quota release

| Item | Description |
|---|---|
| Trigger | On user cancellation, queue/execution timeout, Worker stop, crash recovery, and cleanup retry. |
| Input | cancel_requested, epoch, Host process tree, connections, mounts, resource reservations, and cleanup deadline. |
| Output | Cancellation-request event, actual exit/cleanup confirmation, unique terminal state, resource release, and audit. |
| Execution mode | Separate request from confirmation; gracefully terminate then forcibly clean up, with reentrant cleanup still subject to Fencing/policy. |
| Failure handling | Unconfirmed exit never reports cancelled; mark cleanup_failed/cancellation_unconfirmed, retain isolation, and alert; release Run-active and Host-resource quotas independently according to actual state. |

### FR-10 Retry classification and side-effect governance

| Item | Description |
|---|---|
| Trigger | On launch failure, protocol/network error, timeout, Worker loss, Outbox retry, or manual rerun. |
| Input | Error class, execution phase, idempotency key, known side effects, attempt/retry_of_run, backoff, and budget. |
| Output | Decision to retry safely, retry later, require manual handling, or forbid retry, plus audit. |
| Execution mode | A Run remains one Execution attempt; new attempts correlate with the old Run and receive a new epoch without adding a Task dual-table model. |
| Failure handling | Automatic retry is allowed only before launch with no side effects; ambiguous timeout/disconnect never blindly replays side-effecting requests, and Outbox retry cannot duplicate business effects. |

### FR-11 Event schema and sequence governance

| Item | Description |
|---|---|
| Trigger | When producing, persisting, migrating, or consuming platform/native events. |
| Input | event_id, schema_version, run/execution, engine_session, sequence, type, source, timestamp, and payload. |
| Output | Versioned common envelope, strictly monotonic Run-local sequence, and compatible views of existing events. |
| Execution mode | Allocate sequence and persist the event in one database transaction; parse schemas by explicit version with size bounds. |
| Failure handling | Unknown major versions, invalid payloads, unauthorized sources, or sequence conflicts are denied/diagnosed; historical events are never silently reordered or renumbered. |

### FR-12 Event deduplication and transactional Outbox

| Item | Description |
|---|---|
| Trigger | When Adapters resend native events, Workers retry, Run state/events commit, or Outbox publishes. |
| Input | Global event_id, producer/native_event_id, Run/epoch, event record, and publication cursor. |
| Output | One durable business event, same-transaction Outbox record, retryable publication state, and deduplication audit. |
| Execution mode | Commit state+event+Outbox+required usage in one transaction; publish after commit, use NOTIFY only as wakeup, and recover from the database source of truth. |
| Failure handling | Duplicate input returns the original result without consuming sequence; publication retries with bounded backoff; crashes rescan unpublished records without partial terminal state. |

### FR-13 SSE reconnect, cursor replay, and gap handling

| Item | Description |
|---|---|
| Trigger | On new event stream, reconnect, paged catch-up, retention cleanup, or Run terminal state. |
| Input | Trusted tenant/scope, Run, `after`/`Last-Event-ID`, retention cursor, and live notifications. |
| Output | Ordered durable events, compatible SSE `id=sequence`, event_id/schema_version in payload, heartbeat, and explicit terminal state. |
| Execution mode | Authorize first, then replay in batches from the Event Store and catch up with live delivery; polling recovers missed notifications. |
| Failure handling | Invalid cursors return 400; cursors older than retention return explicit 409/reset instructions without silently skipping events; transient deltas never masquerade as replayable events. |

### FR-14 Idempotent usage aggregation and corrections

| Item | Description |
|---|---|
| Trigger | When native/terminal usage arrives, events replay, Workers retry, or providers issue corrections. |
| Input | Run/epoch, source, source_event_id, usage schema, quantities/cost, received time, and correction correlation. |
| Output | Unique source records, idempotent aggregate views, missing/estimated markers, and traceable corrections. |
| Execution mode | Source uniqueness plus transactional upsert; duplicates from one source return the existing record without recounting. |
| Failure handling | Unknown is not zero-filled; late usage uses correction/version semantics rather than blind addition; old epochs cannot write, and aggregates are rebuildable. |

### FR-15 Native-event parser diagnostics

| Item | Description |
|---|---|
| Trigger | When native events cannot parse, have unknown type/schema, contain out-of-range fields, or exceed payload limits. |
| Input | Adapter/Protocol version, Run, native event identifier, parse location, category, and bounded sample. |
| Output | Redacted structured diagnostics, counted/rate-limited metrics, explicit skip/quarantine/fail policy, and security alerts. |
| Execution mode | Diagnostics do not block independent events that can continue; raw samples are private by default with size/rate bounds. |
| Failure handling | Continuous errors or an unparseable critical terminal event fail/alert by policy; diagnostics themselves cannot recursively create infinite events or leak Secrets. |

### FR-16 Configuration, migration, observability, and compatible rollout

| Configuration item | Level | Default | Description |
|---|---|---|---|
| `execution_untrusted_tenants_enabled` | Global settings | `false` | Enabled only after every hard gate and sign-off; cannot independently bypass sub-policies. |
| `execution_sandbox_required` | Global settings | `true` | Untrusted execution requires a sandbox; configuration cannot degrade to host execution. |
| `execution_network_default_deny` | Deployment policy | `true` | No egress by default, with minimal per-Execution allowances. |
| `execution_credential_grant_ttl_seconds` | Global settings | Bounded short default, frozen at review | Grants expire on schedule and cannot exceed the deployment hard limit. |
| `execution_outbox_enabled` | Global settings | Compatibility rollout, target always on | Controls the publisher during rollout; Event Store polling always recovers and security checks never roll back. |
| `execution_event_retention_days` | Deployment policy | Determined at review | Cleans only retention-eligible data; cursor gaps are explicit. |
| `execution_parser_raw_sample_enabled` | Global settings | `false` | Raw samples are not retained by default; temporary enablement still enforces redaction, size, and retention limits. |

## Non-functional Requirements

- **Performance**: Fencing/Outbox/redaction must not create unbounded lock waits or event backlogs; p50/p95, Outbox-lag, and recovery-time targets are frozen after the Phase 0 baseline.
- **Compatibility**: Existing Run states, event types, SSE `id`, React/Codex public contracts, and historical configuration remain compatible; new fields use expansion/backfill without modifying historical migrations.
- **Multi-tenancy**: Credentials, grants, Workspaces, events, usage, diagnostics, and audit bind to trusted tenant/scope, with cross-tenant access denied by default.
- **Security**: Untrusted execution has no “disable sandbox for availability” mode; Secrets are not stored in plaintext in databases/logs/events, and network/file access denies by default.
- **Reliability**: Every multi-step write has transaction boundaries and reentrant recovery; terminal state is unique, final events agree, and resources/quotas are reconcilable.
- **Operability**: Provide metrics/alerts/audit for Fencing denials, Worker loss, cleanup failure, Outbox lag, replay gaps, usage conflicts, parser errors, and revocation.

## Acceptance Criteria

| # | Scenario | Expected | Traceability |
|---|---|---|---|
| AC-1 | Create/rotate/revoke an Execution credential, then simulate missing master key, binding tampering, and cross-tenant read. | Storage is encrypted and public views contain no plaintext; rotation applies by version, new use after revocation is denied, and anomalies fail closed with audit. | FR-1; G1 |
| AC-2 | Issue a short-lived grant for a specified Run/Engine/scope, then use it across Executions, with expanded scope, after expiry, replayed, and during Resume. | Only the original authorized scope works; all other uses are denied, Resume reauthorizes, and audit contains no Secrets. | FR-2; G1 |
| AC-3 | Inject a Secret canary into logs, stdout, events, SSE, exceptions, diagnostics, and artifacts, then simulate disclosure. | Ordinary output is redacted/quarantined; response revokes credentials and stops new executions without storing plaintext forensics. | FR-3; G1, G2 |
| AC-4 | As an untrusted task, attempt host/container escape, privilege escalation, fork bomb, and memory/disk exhaustion, then launch with sandbox disabled. | Launch is denied without a sandbox; attacks are contained/terminated without affecting the host or other Executions, with resource and alert evidence. | FR-4; G2 |
| AC-5 | Attempt unauthorized egress, DNS rebinding, private/metadata access, redirects, and proxy bypass. | Every unauthorized connection is denied at the actual network boundary; minimal allowlists apply and audit contains no credentials. | FR-5; G2 |
| AC-6 | Attempt `../`, absolute paths, symlink/hardlink, device files, host paths, cross-tenant access, and malicious artifact export. | Every escalation is denied; valid files remain within the Execution view, cleanup leaves no residue, and suspicious artifacts are not published. | FR-6; G2 |
| AC-7 | After Worker A expires and B takes over, let A submit state, events, usage, Session, Outbox, and resource release. | B receives a larger epoch; A performs zero effective writes and no partial commits, with Fencing audit. | FR-7; G3 |
| AC-8 | Inject Worker crash, heartbeat stall, lease expiration, and late success from the old Worker. | Execution enters a defined recoverable state or one terminal state; old results do not overwrite, and no dual Workers/terminal states occur. | FR-8; G3 |
| AC-9 | Cancel/time out a running task with normal exit, hang, cleanup failure, and Worker loss injected separately. | Report cancelled only after confirmed exit/cleanup; anomalies explicitly fail/alert; no orphaned resources or quota leaks remain. | FR-9; G3, G4 |
| AC-10 | Request retry after pre-launch failure, ambiguous timeout, post-external-write disconnection, and Outbox retry. | Only proven side-effect-free cases auto-retry; ambiguous/side-effecting requests do not replay blindly, and new attempts correlate without duplicate effects. | FR-10; G4 |
| AC-11 | Write mixed v1/new-version platform and native events while creating invalid schemas and concurrent sequence allocation. | Versions are identifiable, history remains compatible, and sequence is strictly monotonic without conflicts; invalid input is diagnosed without renumbering history. | FR-11; G5 |
| AC-12 | Resend the same native event and inject crashes before/after state+event+Outbox commit and publication. | Duplicates consume no new sequence and cause no duplicate effects; transactions have no partial terminal state, and recovery completes Outbox publication with at-least-once delivery and idempotent consumption, without claiming network-level exactly-once. | FR-12; G5 |
| AC-13 | Reconnect SSE after more than one page of events, drop notifications, use invalid/expired cursors, and catch up to terminal state. | No silent gaps within retention, event_id deduplicates, SSE id remains compatible; expired cursors return explicit 409, and terminal state agrees with the final event. | FR-13; G5 |
| AC-14 | Duplicate/replay one usage record, submit late usage from an old Worker, and send provider corrections and missing fields. | One source counts once, old epochs are denied, corrections remain traceable, unknown is not zero-filled, and aggregates rebuild correctly. | FR-14; G6 |
| AC-15 | Inject malformed, unknown-type, oversized payload, continuous parse failures, and Secret-containing samples. | Diagnostics classify/correlate/rate-limit correctly and samples are redacted; skip/quarantine/fail follows policy without event storms or Secret disclosure. | FR-15; G6 |
| AC-16 | Gradually enable/roll back each capability, upgrade planned migrations, and run React/Codex, Run/API/SSE, and historical-data regressions. | Switches cannot bypass security checks; migrations expand/backfill online, rollback retains data, and Phase 0 diff is zero. | FR-16; G7 |
