# Remote Linux acceptance appendix — 2026-11-17T16:22Z — 5170e140

> This appendix adds executed evidence only. It does not rewrite any earlier 06 test report or 07 acceptance
> report conclusion. Those documents keep their historical verdicts. This is a minimal-core-team execution
> record produced on a remote Linux host, pending the acceptance owner's formal signoff.
> Revised 2026-11-18 (scope revision): the executed evidence below is preserved verbatim; only its gate
> framing is superseded. See the 2026-11-18 scope-revision section and the per-row notes.
> Revised 2026-11-18 (signoff): the "pending the acceptance owner's formal signoff" status above is now
> closed — the single acceptance owner (JackChow) confirmed and signed the phases 0–3 scope-limited pass on
> 2026-11-18. See `11-scope-limited-acceptance-record-20261118.md` §7 and the execution addendum at the end
> of this file. The historical line is retained verbatim; this note records its current supersession.

## 2026-11-18 scope revision (supersedes gate framing; evidence preserved)

Under the 2026-11-18 scope revision for phases 0–3, the following are **not stage-acceptance gates** and may
appear only as historical notes or explicit out-of-scope statements: performance/capacity/latency (p50/p95,
C11, matched pairs, sample counts, ≤5%/≤50 ms), CI provenance (final-PR-head CI double-run / CI run URL),
real or authorized historical samples, and multi-sample/large-sample data-volume requirements. Phase
acceptance rests solely on functional correctness (A scenarios), switch completeness (default off, explicit
on, off/on/rollback matrix, no silent fallback, no flag leakage into public surfaces/fingerprint), tenant
isolation, Secret handling, data integrity, migration correctness, terminal-state semantics, side
effects/cleanup, no open P0/P1, and a single acceptance-owner record. High-risk enablement stays a separate
approval. A shared production Linux host with run-scoped containers/ports/volumes/paths/credentials and no
changes to co-tenant services is accepted for phases 0–3 non-destructive lanes.

The executed evidence below (environment, lanes, issues found and resolved, artifacts) is a historical record
and is preserved verbatim. The verdict and residual framing that treated the items above as blockers is
**superseded** by this revision; see the per-row notes in the tables below.

## Scope and boundary

Phases 0–3 executable automated lanes only. As written on 2026-11-17 this appendix stated that it does not
close human signoff, real historical samples, CI provenance at a final PR head, C11 performance measurement,
or high-risk capability enablement. Under the 2026-11-18 scope revision, historical samples, CI provenance
and C11 performance measurement are out of phase 0–3 stage scope; only the acceptance-owner record (human
signoff) and the separate high-risk enablement approval remain applicable. No fail-closed flag was flipped
during testing. All execution ran at a pinned, clean SHA.

## Environment

| Item | Value |
|---|---|
| Host | `iZwz9hk5o1f6h2hs6kfetpZ` (Alibaba Cloud Linux 3, kernel 5.10.134, x86_64) |
| Architecture | x86_64 — production/CI-equivalent |
| CPU / RAM | 2 vCPU / 3.5 GiB (below runbook's 4C/8G minimum; see Residuals) |
| cgroup | v1 (`tmpfs`, per-controller mounts) — not cgroup v2 |
| Docker | 26.1.3, Compose v2.27.0, overlay2 |
| Python | 3.12.16 via uv 0.13.9; pytest 9.1.1 |
| Node | 22.14.0 / npm 10.9.2 (user-local install) |
| PostgreSQL | 17-alpine, single disposable container `nd-accept-pg`, migrated to `0071_execution_credential` (head), 114 tables |
| Target SHA | `5170e140f10b117549cf54ba400131f5d7f95f69` (integration, PR #143 merge) — verified clean before and after |
| Host sharing | Shared server: an ERP Java service, MySQL, and a pre-existing quickstart stack run on the same host; no service was stopped or modified |
| Evidence dir | `/home/nexus/nexusdesk-acceptance/evidence/20261117T162253Z` |
| Evidence package | `20261117T162253Z.tar.gz`, sha256 `6c2ebe00213daf1114d94a3900020c36e1246d61226076562afc2b73b3fe41e9` |

## Lane results

| Lane | Command (see `03-logs/<lane>.command`) | JUnit totals | Exit | Verdict |
|---|---|---|---|---|
| D1 non-PG suite | `uv run pytest -q -m "not postgres" -rA` | 2329 tests, 0 failures, 0 errors, 7 skipped | 0 | pass |
| D2 PostgreSQL suite | `uv run pytest -q -m postgres -rs -rA` | 660 tests, 0 failures, 0 errors, 47 skipped | 0 | pass |
| D3 execution-focused | `uv run pytest -q tests/test_execution_*.py … -m "not postgres"` | 1547 tests, 0 failures, 0 errors, 7 skipped | 0 | pass |
| D4 frontend gates | `npm run typecheck` / `check:i18n` / `build` | 2556 translations × 4 languages; 3326 modules built | 0 | pass |
| D8 migrations | `uv run pytest -q test_*migration*.py` | 15 tests, 0 failures, 0 errors, 0 skipped | 0 | pass |
| Alembic | `alembic heads` / `current` | `0071_execution_credential (head)` on a migrated disposable DB | 0 | pass |

All skips are declared environment or vector-mode skips (`pending_env`: Codex CLI absent, cgroup v2 hard
limits absent, `CREATEDB`-requiring cases, pgvector/embedding-column absent). None was rewritten as a pass.

## Two issues found and resolved during execution

1. **517 failed / 499 errors on the first D2 run** — root cause: the disposable test database had not been
   migrated (`relation "tenant_businesses" does not exist`). This is an environment-preparation omission, not
   a product defect. After `alembic upgrade head` (114 tables, head `0071`), the same suite reported
   1 failed / 612 passed / 47 skipped.
2. **Remaining single failure** (`test_end_to_end_demo_uses_real_http_and_persistent_events`, `assert 401 ==
   202`) — root cause: the quickstart API token `AGENT_API_TOKEN` was sourced into the pytest process and
   enabled the auth middleware. With that variable unset (correct for the PG suite, which needs only
   `TEST_DATABASE_URL`), the test passes in isolation and the full D2 rerun is green (613 passed / 47 skipped,
   exit 0). No product code change was required; no subagent code fix was needed.

## Phase-by-phase verdict against the minimal-core-team criteria

> **2026-11-18 scope note:** the verdicts and reasons in this table reflect the 2026-11-17 gate framing.
> The CI double-run, authorized historical-sample, five-role-signoff, and C11-performance reasons listed
> here are superseded as phase 0–3 gates (historical notes / out of scope). The executed evidence itself is
> unchanged and remains valid.

| Phase | Automated evidence available here | Verdict from this appendix |
|---|---|---|
| Phase 0 baseline inventory | Full backend suites (D1/D2/D3) green at pinned SHA; migration head verified | **Evidence partial** — functional baseline exercised; CI double-run, authorized real historical samples, and five-role signoff cannot be produced on a shared host. Formal Phase 0 acceptance remains open. |
| Phase 1 execution contracts | D3 execution-focused green includes contract/registry tests; second-Adapter UAT and CI evidence not run here | **Evidence partial** — automated contract tests green; Adapter UAT and CI provenance remain open. |
| Phase 2 React provider | D1/D3 runtime-baseline parity tests green; D4 frontend gates green; C11 performance **not measured**, off/on/rollback stack drill **not run** | **Conditionally ready** — functional/frontend evidence green; performance submetric `pending_env`, so per §6.1 T9 cannot be "fully passed". |
| Phase 3 capability/config | D3 green; migration chain 0058/0059/0070/0071 verified; C11 paired-baseline measurement **not performed**; seed/quickstart wiring deferred (#127/#128) | **Conditionally ready** — A/C functional evidence green; C11 `not_measured` and deferred #127/#128 mean "fully passed" is not claimable. |

**Overall**: no P0/P1 product defect was found in phases 0–3 automated lanes at SHA `5170e140`. All seven
executed lanes are green. This appendix does not itself upgrade any phase to "passed" — the acceptance owner
records the conclusion in a single acceptance record. Under the 2026-11-18 scope revision, the former reasons
for withholding a pass (missing CI provenance, real-environment measurement, and real/authorized historical
samples) are historical/out-of-scope for phases 0–3 and are superseded; only kept-gate failures, an open P0/P1,
or the separate high-risk enablement approval can block a phase conclusion.

## Residuals (owner to be assigned by acceptance owner)

| ID | Item | Impact | Type | 2026-11-18 status |
|---|---|---|---|---|
| R-1 | Host is shared (ERP/MySQL/other stack); 2C/3.5G, cgroup v1, no mount namespace | Blocks Phase 4 E1–E4; below runbook minimum | `pending_env` | Accepted for phases 0–3 non-destructive lanes under the governed shared-host policy; still applies to Phase 4 destructive drills |
| R-2 | No CI run at the final PR head; all evidence is local ssh-run pytest | Blocks formal Phase 0/1 acceptance and Phase 2 T9 | governance | **Superseded** — CI provenance / final-PR-head double-run / CI run URL are out of phase 0–3 stage scope (historical note only) |
| R-3 | No authorized real historical samples; no five-role / multi-role signoff | Blocks Phase 0/1 formal acceptance | governance | **Superseded** — real/authorized historical samples and multi-role signoff are out of phase 0–3 stage scope; only the single acceptance-owner record remains |
| R-4 | Phase 2 C11-style performance ≤5% and Phase 3 C11 p95 ≤50 ms not measured | Caps Phase 2 and Phase 3 at conditional | `not_measured` | **Superseded** — C11/p95/≤5%/≤50 ms and sample-count requirements are out of phase 0–3 stage scope (historical note only) |
| R-5 | Phase 2 controlled off/on/rollback stack drill not run (port 8080 held by a pre-existing stack) | Phase 2 T10/T11 evidence gap | `pending_env` | **Closed for phases 0–3 by the 2026-11-18 run** — switch completeness proven at the pinned SHA by the 913-test `d9-switch-completeness` automated lane plus read-only production default-off inspection; live Compose drill remains `pending_env` as a non-gate supplement |
| R-6 | Phase 3 seed + quickstart wiring deferred to issues #127/#128 | Must be recorded as deferred, not complete | deferred | Unchanged — record as deferred, not complete |
| R-7 | Codex CLI absent | D6 real-binary lane and Phase 5 out of scope for phases 0–3 | `pending_env` | Unchanged — Phase 5 is out of phases 0–3 scope |
| R-8 | Vector/embedding-column (pgvector) absent; CREATEDB-restricted cases skipped | 47 D2 skips; must stay skipped, not passed | `pending_env` | Unchanged — skips must stay skipped, not passed |

> Residuals R-2/R-3/R-4 are retained as the original 2026-11-17 historical record and are explicitly
> **superseded as gates** by the 2026-11-18 scope revision; they are not blockers for phase 0–3 acceptance.

## Reproduction

Evidence package `20261117T162253Z.tar.gz` contains `00-pin.txt`, `01-environment.txt`, `03-logs/<lane>.{command,log,exit}`,
`04-junit/*.xml`, `manifest.json`, and `sha256sums.txt`. Commands are recorded verbatim in the `.command` files.

---

## 2026-11-18 execution addendum (scope-limited acceptance under the revised standard)

A second, corrected run was executed on the same governed shared production host at the pinned SHA
`5170e140f10b117549cf54ba400131f5d7f95f69` under the 2026-11-18 scope revision.

| Item | Result |
|---|---|
| Evidence package | `20261118T125822Z.tar.gz` |
| SHA256 | `109989c3c0a0ee4f9aa1bcc49b7ebc3b382f697de98461f4a6b3ee366e9a9d23` |
| Lanes | 13 lanes, all exit 0 |
| JUnit totals | 5,464 tests / 0 failures / 0 errors / 55 declared skips |
| New switch-completeness lane | `d9-switch-completeness`: 913 tests, 0 failures, 0 errors, 0 skipped at the pinned SHA |
| Default-off proof | `d10-code-defaults.txt` + `d10-production-default-off.txt`: all execution/Codex flags default to `False`; production container declares none |
| Live Compose off/on/rollback drill | `pending_env` (no pinned-SHA image buildable: DockerHub unreachable, `node:22-alpine` not cached, cached image 37 commits behind); not a gate under the 2026-11-18 revision |
| Co-tenant impact | None; pre/post `docker ps` and port inventory identical; acceptance PG rebound to `127.0.0.1:55432` |
| Verdict | **PASS (scope-limited)** for phases 0–3; see `11-scope-limited-acceptance-record-20261118.md` |

The 2026-11-17 evidence above is retained unchanged. This addendum supersedes only the former
CI/performance/historical-sample blockers (R-2/R-3/R-4) and closes R-5 as a gate; no historical
test number or verdict is rewritten. High-risk capability enablement remains separately gated.

**Signoff recorded (2026-11-18):** the single acceptance owner (JackChow, the user) confirmed
"phases 0–3 acceptance passed" and signed the single acceptance record in
`11-scope-limited-acceptance-record-20261118.md` §7. The verdict above is therefore no longer
"pending signoff": it is **PASS (scope-limited), signed**. No high-risk capability enablement,
production release, or later-phase authorization was granted by this signoff.
