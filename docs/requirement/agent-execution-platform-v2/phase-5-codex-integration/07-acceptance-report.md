# Phase 5 · Codex Integration — Acceptance Report

> Status: **Executed** — **scoped conditional pass for the R18 stdin-channel implementation only**. **Stage A full acceptance has NOT passed and Stage B is NOT unlocked.**
> Created: 2026-11-13; rewritten 2026-11-16 by the Phase 5 acceptance sub-agent after the R18 D21/D22 fixes.
> Basis: `05-acceptance-plan.en.md` (A1–A12, M1–M2, C1–C10, and §6 decision rules), `06-test-report.md` (round-6 and round-6-follow-up evidence), `08-implementation-breakdown.md` (R10, R17, and R18).
> Acceptance owner / executor: Phase 5 acceptance sub-agent (the same role; no fabricated product, QA, business, security, or SRE approval).
> Target: the current **uncommitted working tree** on branch `integration`, based on `69b7c5eb58eefba47cb8fc1e727941d00dee783f`; no commit SHA exists for this target.
> Evidence discipline: fake-fixture results prove only deterministic platform seams. Real-provider claims below come only from measured real-binary runs. `pending_env` and `not_measured` are not passes, and Stage B remaining locked is not Stage B acceptance.

## 1. Acceptance Scope and Responsibility

### 1.1 Scope accepted

This decision covers the **R18 prompt-delivery channel and its immediate error-handling fixes**, within the existing Stage A contract-closure tree:

- `ProcessSpec.stdin_payload`: optional bounded UTF-8 bytes (`1..800_000`), default `None`, excluded from `repr()` and model dumps, and excluded from `command_digest`.
- `ProcessRunner`: `DEVNULL` remains unchanged when no payload is present; a payload gets a pipe, one bounded write/drain followed by EOF close, and fail-closed cleanup on early close or timeout. The delivery deadline is the smaller of the configured 10-second ceiling and the remaining process wall budget (D22).
- `CodexCliAdapter`: the prompt is encoded once after the execution gate and before Workdir creation, then passed as `stdin_payload`; the `promptless_target` bypass is removed. `HostStartError` is translated to a catalog-safe `AdapterExecutionError(ENGINE_UNAVAILABLE)` (D21).
- `cli_exec.py`: the fixed seven-token argv retains its trailing `-`; the prompt is never an argv element. R17's typed `PATH` remains the only environment value supplied by this lane.
- Focused unit, real-process, PostgreSQL integration, and local real-binary evidence recorded in `06-test-report.md`.

The R18 implementation is code-ready on the measured local face. This is **not** approval to enable Codex in a deployment.

### 1.2 Explicit exclusions

- Stage A trusted-tenant release acceptance, managed credentials/Secret canaries, host-auth inspection, cross-tenant mounts, and the 20-scenario/three-run stability batch.
- App-Server transport, JSON-RPC end-to-end execution, Session persistence/Resume, approvals, and interactive input. Stage B remains structurally disabled.
- Production Worker routing to Codex, production trusted-target registration, and publish-path enablement.
- Any Alembic migration. The current migration head remains `0059_execution_runtime_host`; this round adds none.
- Frontend, SDK, HTTP-route, SSE, and UI changes; none exist in this delta.
- Full backend/frontend CI at this target and performance percentiles.

### 1.3 Responsibility and preconditions

The acceptance owner and executor are the same role. Automated evidence is reused from `06`; this acceptance round executed only the targeted checks in §2.2 and did not repeat the full suite. No independent security audit or trusted-tenant UAT is claimed.

The `05` preconditions are only partly met: the code-only checks are green and no P0/P1 remains open, but the Phase 0 baseline is absent, real credential/tenant evidence is incomplete, and P5-IT-18 is unmeasured. PostgreSQL tests used disposable databases, but the required controlled two-tenant release environment was not established. These gaps block Stage A acceptance and Stage B unlock; they do not invalidate the narrower R18 code-readiness decision.

## 2. Acceptance Environment

### 2.1 Environments and reused evidence

| Environment | Configuration | Evidence carried |
|---|---|---|
| Local backend toolchain | macOS Darwin 27.0.0, Python 3.12.13 through `uv`, `UV_CACHE_DIR=/tmp/nexusdesk-uv-cache` | Acceptance spot checks; reused ruff, unit, Host, orchestration, and architecture-gate evidence from `06` |
| Real Codex CLI | `/usr/local/bin/codex`, `codex-cli 0.169.0` (version re-measured by acceptance) | Local R18 real-binary prompt consumption; full adapter-chain evidence reused from `06` A-14/C-11 |
| Disposable PostgreSQL | Fresh `pgvector/pgvector:pg17` Docker containers and per-run databases, used by the test sub-agent | 16 PostgreSQL integration tests, including four Codex Host tests and prompt-consumption/leak checks (`06` A-4b/C-6) |
| Deterministic fake fixture | `backend/tests/fixtures/codex_fake/`, including a fixture that reads stdin to EOF | Platform seam and fault coverage only; never provider compatibility |
| Controlled release-like Codex environment | Managed credentials, two isolated trusted tenants, pinned deployment, and CI with Codex installed | **Unavailable / `pending_env`** |
| CI at this target | No branch, commit, push, or PR was created | **No CI evidence**; local and test-sub-agent evidence only |

Latest reused execution results are kept distinct rather than summed: ruff passed; the round-6-follow-up non-PG Codex/local-adapter lane reported **157 passed, 4 deselected**; the Phase 4 runner+supervisor follow-up reported **98 passed**; the disposable-PG set reported **16 passed**; and earlier round-6 targeted orchestration snapshots reported **314 passed** for five suites and **385 passed** for six suites. The architecture gate passed. The full backend suite and frontend build were not run locally.

### 2.2 Independent low-cost acceptance checks (2026-11-16)

| # | Command / inspection | First-hand result |
|---|---|---|
| V1 | Six focused tests: default Codex metadata denial, publish-path denial, exactly-one-React warm target, D21 Host-start normalization, D22 wall-capped stdin timeout, and prompt-on-stdin/not-argv | **6 passed in 1.87s** |
| V2 | `/usr/local/bin/codex --version`, then `test_real_codex_consumes_the_prompt_through_the_host` | **`codex-cli 0.169.0`; 1 passed in 10.24s**. The real binary exited 0 and emitted a real `agent_message` and `turn.completed` after consuming the Host-delivered prompt |
| V3 | `git status --porcelain -- backend/migrations frontend sdk` plus `git rev-parse HEAD` | **Zero entries** in all three directories; base HEAD is `69b7c5eb58eefba47cb8fc1e727941d00dee783f` |
| V4 | Collect four `passed`/`partial` citations from `06`: two-protocol registration, PG prompt consumption, early-close cleanup, and usage extraction | **4 tests collected in 0.73s**; every cited node resolves |
| V5 | Read R18 Host/adapter code and scan the Codex package/composition root for `auth.json`, `~/.codex`, `expanduser`, `os.environ`, bearer, and `sk-` references | Fixed argv/stdin behavior and D21/D22 implementations match `08` R18; credential-path scan returned **zero matches**. D23–D26 remain visible as recorded |

V2 is a raw real-Host acceptance check. The stronger **complete adapter → RuntimeHost → ProcessRunner** result is reused from the test sub-agent's `06` A-14/C-11: local runs completed with `output == 'ok'`, five measured usage counters and no invented `total_tokens`, `active_count == 0`, and no pending process row. Event count and elapsed time varied between samples and are not treated as stable performance expectations.

## 3. Functional Acceptance Records (A1–A12)

| # | Decision | Execution record, evidence, and missing coverage |
|---|---|---|
| A1 | **pass (local real-binary R18 half) / `pending_env` in CI** | The real CLI consumed stdin through the Host and completed locally (V2). `06` A-14/C-11 also proves the complete adapter chain: correlated `output='ok'`, real usage, terminal durable state, no survivor, and no public PID. The deterministic PG case independently proves prompt consumption. Missing: the same real-binary evidence in CI/controlled release-like infrastructure and full trusted-tenant/public-API release evidence. Evidence: `06` P5-IT-01/19, A-13/A-14, C-11; V1–V2. |
| A2 | **partial (registration/denial pass) / `pending_env` for unlock** | One `codex` Engine with independent `cli_exec` and `app_server` Protocols is registered. Default metadata resolution denies both; App-Server remains literally `enabled=False` even if settings are opened. No complete Stage A evidence set or acceptance-owner unlock record exists, so the unlock half cannot pass. Evidence: `06` P5-UT-01/02, P5-IT-02; V1, V4. |
| A3 | **partial; real local message/usage half pass, remaining native families `pending_env`** | Real local evidence retains and correlates thread/item/turn events, an `agent_message`, and five usage counters without zero-filling `total_tokens`. Deterministic tests cover ordering, identity, malformed input, and explicit unknown usage. Missing: real command/file-change native families, a real no-usage task, and broader provider/version accuracy. Evidence: `06` P5-UT-06/07, P5-IT-03/19, A-14/C-11; V2, V4. |
| A4 | **partial / `pending_env`** | Real process-group cancellation and R18 early-close/starvation cleanup are fail-closed; D22 keeps delivery within a tighter wall. Missing: end-to-end wall timeout, driven grandchild tree, simulated cleanup failure, crash sweep, and all App-Server cases. Evidence: `06` P5-IT-05/06/07, P5-UT-20, Appendix D; V1. |
| A5 | **partial / `pending_env` for cross-tenant attacks** | Valid local restricted execution succeeds, and traversal/absolute/encoded/drive/symlink Workdir attacks are refused before Host start. Missing: cross-tenant read/write and mount adversarial evidence in the controlled environment. Evidence: `06` P5-UT-09, P5-IT-08; V2. |
| A6 | **`pending_env`** | No managed Secret-canary execution, host-auth inspection, credential-scope test, or end-to-end untrusted-tenant launch was performed. Static disabled-state evidence is assessed under C1–C3 but does not satisfy A6. Evidence: `06` P5-UT-10, P5-IT-09/10. |
| A7 | **`pending_env` (Stage B locked)** | Only bounded JSON-RPC codec/state primitives exist. No transport, concurrent Turns, disconnection matrix, or public/native end-to-end surface exists. Evidence: `06` P5-UT-11/12, P5-IT-11. |
| A8 | **`pending_env` (Stage B locked)** | No App-Server Session store, persistence mapping, expiration, Resume, or migration exists; CLI default behavior is unchanged. Evidence: `06` P5-IT-12; V3. |
| A9 | **`pending_env` (Stage B locked)** | Approval and interactive-input allow/deny flows are not implemented. Stage A configuration deliberately pins `approval_mode='never'` and `sandbox_mode='read-only'`. Evidence: `06` P5-UT-13, P5-IT-13. |
| A10 | **`pending_env` (Stage B locked)** | No Session exists to resume or reauthorize. Legitimate and denied Resume scenarios remain unexecuted. Evidence: `06` P5-UT-15, P5-IT-14. |
| A11 | **partial** | Unknown versions, malformed CLI output, invalid JSON-RPC, oversized payloads, and missing usage have bounded catalog outcomes; D21 now prevents raw `HostStartError` from crossing the adapter boundary. Missing: real-provider fault injection and Run/Protocol/version telemetry locatability. D26 records a latent pydantic validation-error payload echo, currently unreachable through the adapter's prevalidated bytes path. Evidence: `06` P5-UT-17, P5-IT-15, D21/D26, Appendix D; V1. |
| A12 | **partial; Phase 0 diff `not_measured`** | Defaults deny Codex, warm scope remains exactly one React target, targeted regressions are green, and rollback requires no table operation because no migration exists. Missing: full CI/frontend regression and the Phase 0 baseline diff; an unmeasured diff is not zero. Evidence: `06` P5-IT-16/17, §6; V1, V3. |

## 4. Security, Data, and Release Hard Gates (C1–C10)

| # | Decision | Evidence and boundary |
|---|---|---|
| C1 — veto | **pass (disabled-state/static evidence)** | No credential value source or credential-path reference exists in the Codex lane. Fixed argv has no prompt/credential interpolation; the only adapter-supplied environment value is typed `PATH`. Public payload filtering removes credential/environment keys, and R18 prompt-sentinel checks found no prompt in logs, dumps, events, or durable rows. The real Secret-canary run remains A6 `pending_env`; D26 is a latent prompt-validation boundary, not a measured credential disclosure. |
| C2 — veto | **pass (disabled-state/structural evidence)** | V5 found no `auth.json`/`~/.codex` reference, copy, mount, or host-home expansion. `ProcessSpec` has no mount field and composition mounts no credential directory. This is not a real Secret-isolation test; A6 remains open and production stays disabled. |
| C3 — veto | **pass** | Both trust/version allowlists default empty, all Codex switches default off, default metadata lookup raises `ADAPTER_DISABLED`, the production Worker selector remains React, and the production trusted-target registry remains empty. No wildcard or untrusted-tenant enablement path was added. Evidence: V1 and `08` R11/R16. |
| C4 — veto | **pass for the locked Stage A/R18 boundary; full cross-tenant/Resume evidence remains pending** | Local traversal and symlink cases fail before Host start, and no Session/Resume capability exists to bypass reauthorization. Production cannot reach an untrusted Codex execution. This verdict asserts **no veto violation while locked**, not that future cross-tenant mounts or Session Resume have passed their A5/A10 acceptance scenarios. Those remain mandatory before enablement/unlock. |
| C5 | **partial** | One Engine/two Protocols and public JSON-RPC sanitization are proven. D12 is fixed, but other real native families and App-Server native-stream behavior have not been exercised end to end. Evidence: `06` P5-CM-05; V4. |
| C6 | **partial** | Real cancellation, failed-start cleanup, bounded stdin delivery, and malformed-output failure are proven without false success. Real wall-timeout, grandchild, crash, cleanup-failure, and App-Server disconnection matrices remain incomplete. Evidence: `06` P5-CM-06, Appendix C/D; V1–V2. |
| C7 | **pass because Stage B remains locked** | App-Server descriptor `enabled=False`, its factory raises, and settings cannot legitimately enable a half-configured Stage B. P5-IT-18 and three consecutive release regressions are not complete. This row is **not** a Stage B pass and grants no unlock. |
| C8 | **pass — no migration this round** | V3 shows zero migration changes. Historical migrations are untouched, head remains `0059_execution_runtime_host`, and the obsolete planned-0055 wording is treated as documentation residual D25, not as an executed migration. Rollback drops no table because this change creates none. |
| C9 | **`not_measured` — cannot pass** | Targeted behavioral regressions are green and default React remains the sole warm target, but no Phase 0 baseline exists. Therefore no zero-diff claim is made and C9 cannot pass under `05`. Full CI/frontend evidence is also absent. |
| C10 | **partial** | Adversarial Workdir, payload bound, malformed stream, duplicate/late JSON-RPC, early-close, never-read, wall-cap, and Host-start-failure cases exist. Every unavailable real-environment item is marked `pending_env` here and assigned in §7. Missing real Secret, cross-tenant, provider-fault, crash/timeout, and controlled stability coverage prevents a full pass. |

## 5. Key Manual Checks (M1–M2)

| # | Decision | Record |
|---|---|---|
| M1 | **not_applicable / no UI evidence** | No frontend, SDK, route, or SSE file changed (V3). No common-UI task, streaming, approval/input, or final-result inspection was performed, and no UI screenshot/log evidence exists. No App-Server UI availability is advertised by this backend delta; structural disablement is covered by C7, not presented as a UI check. |
| M2 | **not_applicable for UI/Resume; automated error evidence only** | No manual malformed-message or Session Resume UI check was performed. Automated tests cover bounded error text, and no Session exists. Legitimate/denied Resume remains A10 `pending_env`; this report does not convert the absence of a Session into a passed Resume check. |

No developer self-verification is relabelled as user UAT.

## 6. Engineering Measurement

**Startup/execution p50 and p95: `not_measured`.** No representative sample size or pinned release-like task set exists. The observed single-run timings in `06` and V2 (including V2's 10.24-second test duration) are observations, not percentile measurements or performance passes. Owner and required environment are recorded in L15.

## 7. Residual List

| # | Level | Residual | Owner | Deadline |
|---|---|---|---|---|
| L1 | P3 | **D23:** R18's stated `wait_closed()` asyncio-noise rationale did not reproduce; reword it to the measured behavior without changing the verified write/close semantics. | Backend/docs owner (I16) | Next Phase 5 documentation iteration |
| L2 | P3 | **D24:** `fake_codex.py` contains an unreachable duplicate emitter block after `return 0`; remove it and retain the actual fixture usage shape in tests/docs. | Test owner (I16) | Next Phase 5 test iteration |
| L3 | P3 | **D25:** English `03` rollout step 2 and the paired migration heading still carry stale planned-0055 wording; both `04` basis lines also need synchronization. P5-CM-08 stays partial. | Docs owner (I17) | Next Phase 5 documentation iteration |
| L4 | P3 | **D26:** pydantic `ValidationError` can retain/echo invalid `stdin_payload` input. The adapter currently supplies prevalidated bounded bytes, so this is latent rather than a measured production leak; document or harden the boundary and add an assertion. | Backend/test owner (I18) | Before exposing direct `ProcessSpec` construction to a new caller |
| L5 | P3 | **D27:** this rewrite removes the stale counts from `07`; `06` Appendix A-7b still says seven contract tests although the current file collects eight. Keep round-5/round-6 snapshots historically labelled rather than rewriting them as one execution. | Test/docs owner (I17) | Next test-report revision; `07` portion closed here |
| L6 | P2 | **D9:** capability-narrowing has no Codex-specific test; only typed configuration is covered. | Backend/test owner (I12) | Next Phase 5 iteration |
| L7 | P2 | **D10:** authentication and permission failures cannot yet be distinguished from generic `ENGINE_UNAVAILABLE`. | Backend owner (I11) | Before trusted-tenant enablement |
| L8 | Environment | A1/A3 real-binary evidence is local only; CI has no Codex binary and the real test intentionally skips with `pending_env`. | Test/acceptance owner (I1 follow-up environment, I9) | First controlled CI/runner with pinned Codex |
| L9 | Enablement/security | A5/A6: managed Secret canary, host-auth inspection, two-tenant isolation, cross-tenant mounts, trust revocation, and untrusted-tenant end-to-end denial are absent. | Security/test owner (I5, I9, I10) | Before any trusted-tenant enablement |
| L10 | Environment | A4/C6: real wall-timeout, grandchild, crash, cleanup-failure, and connection-disconnection matrices are incomplete. | RuntimeHost/test owner | Before Stage A full acceptance |
| L11 | Stage B | A7–A10: App-Server transport, concurrent Turns, approvals/input, Session persistence/expiration/Resume, and reauthorization are unimplemented. **Keep Stage B locked.** | Future Stage B owner (I4) | Only after Stage A unlock |
| L12 | Stage gate | P5-IT-18 (at least 20 mixed scenarios, no P0/P1, three consecutive applicable regressions) and the formal Stage A unlock record are absent. | Test/acceptance owner (I3) | Before Stage B merge/enable/advertising |
| L13 | Environment | A11/C5: real-provider fault injection, additional native-family public-payload checks, and Run/Protocol/version telemetry locatability remain unmeasured. | Test/observability owner (I9) | Before Stage A full acceptance |
| L14 | Hard gate | C9/Phase 0 baseline diff is `not_measured`; full historical Run/API/SSE regression evidence is incomplete. | Maintainer/test owner (I6) | Before Stage A full acceptance or release |
| L15 | Measurement | Startup/execution p50/p95 and sample size are `not_measured`. | Performance/test owner (I6) | Controlled pinned-version measurement window |
| L16 | Process | No CI exists for this uncommitted target; full backend and frontend suites were not run by acceptance. CI results, once available, supersede local evidence. | Coordinator/main session | Immediately after push/PR |
| L17 | P2/deployment | Production Worker selection, trusted-target registration, and Codex publish-path projection intentionally remain unavailable/fail-closed (R8/R9/R11 in `06`). | Backend/deployment owner (I2, I7) | Separate enablement design; not R18 |

Additional low-priority observations remain tracked in `06`: I19 (empty adhoc Workdir left after a failed Host start), I20 (`model_dump()` intentionally excludes the payload, so a future dump/revalidate round trip would lose it), and I21 (test-comment AC-S identifiers lack formal `04` definitions). None changes this round's R18 verdict.

## 8. Conclusion and Single Acceptance Record

**Decision: scoped conditional pass — the R18 stdin-channel implementation is code-ready on the measured local face. Stage A full acceptance has NOT passed and Stage B is NOT unlocked.**

Why this is not a full Pass or Stage A pass:

- A2–A5, A11, and A12 are partial; A6–A10 remain `pending_env`; A1/A3 real-binary CI evidence remains `pending_env`.
- C5, C6, and C10 are partial; C9 is `not_measured`; M1/M2 have no UI evidence; performance is `not_measured`.
- P5-IT-18, the Phase 0 baseline, managed credential/tenant evidence, and the formal Stage A unlock record are absent.

Why the narrower R18 decision is not Fail:

- The real local provider now consumes the prompt through the Host and completes; the full adapter-chain result is independently recorded in `06`.
- D21 and D22 are fixed and their focused regression tests passed again in V1. No open P0/P1 or open R18 P2 remains.
- C1–C4 veto items pass on the static/disabled and measured Stage A boundary; no production enablement or untrusted-tenant exposure is authorized.
- C7 passes only by keeping Stage B locked, and C8 passes because there is no migration.
- Remaining R18 defects are P3 documentation/fixture/latent-boundary items with owners above. Older P2 items and every environment/hard-gate gap remain explicit and prevent any broader acceptance claim.

This decision does **not** authorize enabling Codex, merging/enabling/advertising Stage B, claiming credential or tenant isolation, claiming full provider/version compatibility, or treating the fake fixture as provider evidence.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence / residual confirmation |
|---|---|---|---|---|---|
| Phase 5 acceptance sub-agent | Phase 5 acceptance sub-agent (same role; targeted V1–V5 only, not a full-suite rerun) | 2026-11-16 | Uncommitted working tree based on `69b7c5eb58eefba47cb8fc1e727941d00dee783f` (branch `integration`; no target commit SHA) | **Scoped conditional pass for R18 code readiness only; Stage A full acceptance NOT passed; Stage B NOT unlocked** | `06-test-report.md` round-6/follow-up and Appendices A–D; `08` R10/R17/R18; this report V1–V5. P2/P3 and environment residuals L1–L17 acknowledged with owners/deadlines in §7 |

> High-risk independent approval: none was sought and none is claimed. Credential-bearing trusted-tenant execution, untrusted multi-tenant execution, and App-Server transport remain disabled/out of scope. They require the later controlled evidence and any applicable independent security/operations approval before enablement.
