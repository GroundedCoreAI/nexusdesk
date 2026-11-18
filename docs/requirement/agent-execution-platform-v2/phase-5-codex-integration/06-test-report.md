# Phase 5 · Codex Integration — Test Report

> Status: Stage A contract closure complete; **prompt delivery through the Host stdin channel is implemented and verified against the real binary (`08` R18)**. Credentials, tenant isolation, JSON-RPC end-to-end, Session and Stage B evidence remain `pending_env`.
> Created: 2026-11-13; revised 2026-11-14 after the Stage A implementation round, then independently re-executed by the Phase 5 test sub-agent (four-agent orchestration round 3); revised again 2026-11-14 (round 5) for `08` R18.
> Basis: `04-test-plan.en.md` (P5-UT-01~18, P5-IT-01~18, P5-CM-01~08), `02-requirements.en.md`
> Executor/date: Phase 5 development sub-agent; 2026-11-14. Independent re-execution: Phase 5 test sub-agent; 2026-11-14.
>
> Independent re-execution note: every `passed` row below was re-run by the test sub-agent with the commands in Appendix A. Rows that the development round over-claimed are corrected in place and the correction is listed in §7.1 (D6-D17). The real-provider conclusion in the development round ("no provider execution attempted because the CLI is not logged in") was re-measured and is **false** — see §1 and D7; the lane still stays `pending_env`, but for the measured reasons recorded there, not for lack of credentials.

> Round verdict (round 3): **the code-only cases pass and the four P1 defects are fixed; the lane is still not acceptance-ready.** All 136 non-PG tests, the 3 PG integration tests, the 385-test targeted regression, ruff and the architecture gate reproduce green. D6 (real event grammar), D7 (false environment claim), D12 (public payload passthrough) and D13 (workdir escape) were fixed in the development round-3 pass and re-verified here with the original reproduction commands; see §7.2. D9, D10 and D14 stay open as tracked issues. Stage A full acceptance and Stage B remain blocked on the real-environment evidence listed in §8.
>
> **Round 5 verdict (`08` R18, prompt delivery): the last blocking lane seam is closed and measured against the real binary.** `ProcessSpec` now carries one optional bounded `stdin_payload`; the Host writes it and EOF-closes the pipe inside a bounded deadline; the adapter encodes `request.input` and refuses unencodable or over-ceiling prompts before any side effect. The `promptless_target` bypass and `PROMPT_DELIVERY_ISSUE` are deleted. Measured locally: `/usr/local/bin/codex` driven through the **complete adapter → RuntimeHost → ProcessRunner chain** exits **0** in ~4.7s with `output == 'ok'`, five measured usage counters, no `total_tokens`, and zero survivors (A-13/A-14). CI has no Codex binary, so the real-binary case is `pytest.skip`-guarded and remains `pending_env` there; the deterministic-fixture coverage (which now *reads* stdin) runs everywhere. **Stage A full acceptance still does not pass and Stage B is still locked**: credentials, tenant isolation, the 20-scenario batch and the Phase 0 baseline remain absent (§8).

**Round 6 verdict (independent re-execution of the R18 change, test sub-agent, 2026-11-15): every code-only check reproduces green — ruff, format, 155 non-PG, 16 PG against a fresh Docker container, 143 Phase 4 Host tests, 314/385 orchestration regression, the architecture gate, and 16 stdin-delivery cases three times — and the real-binary halves A-13/A-14 reproduce first-hand (exit 0, `output == 'ok'`, five usage counters, no `total_tokens`). No P0/P1 defect was found.** Independent probes beyond the shipped tests confirm the load-bearing claims: `None` really is `DEVNULL` (character device vs FIFO), R1/R2 both fail closed with `runtime_host_pipe_setup_failed` and leave no process group, no half-started handle is returned, no prompt text reaches logs/dumps/events/durable rows, and no fd or process leak appears over 100 cancellations. Seven new defects were filed by this round and none of them is a hard gate: D21 (raw `HostStartError` escapes `adapter.start`, P2), D22 (the 10 s delivery deadline is not clamped by a tighter Run/Host wall ceiling, P2), D23 (the `wait_closed()` "asyncio noise" rationale does not reproduce, P3), D24 (dead duplicate block in the fixture, P3), D25 (the English `03` rollout step was left unsynced, P3), D26 (pydantic's `ValidationError` echoes the payload, latent, P3) and D27 (count drift in `07` and in A-7b, P3). **P5-CM-08 is ruled down to `partial`.** Stage A full acceptance still does not pass and Stage B is still locked for the reasons in §8; the R18 code itself is acceptance-ready on the code-only face.

**Round-6 follow-up verdict (D21/D22 fix re-verification, test sub-agent, 2026-11-16): both P2 defects are confirmed closed by re-running this round's own reproduction probes, not by re-reading the diff.** D21 now surfaces `AdapterExecutionError(code=engine_unavailable)` with the message `Engine is unavailable.` and no internal reason vocabulary, while the durable Host row keeps `runtime_host_pipe_setup_failed`; D22 now fails a starved delivery after **1.01 s** under a 1 s wall (previously 10.03 s). Targeted scope only: `ruff check .` → All checks passed; the non-PG Codex+local-adapter lane is **157 passed, 4 deselected**; the Phase 4 runner+supervisor suites are **98 passed**. No regression was found in R1/R2 semantics, in the DEVNULL default, in the small-payload buffering reverse case, or in legitimate tight-wall deliveries. New defects filed this round: none. D23–D27 remain open as previously recorded; I14/I15 are closed. **P5-CM-08 stays `partial`** (D25/D27 are docs items, unchanged by this fix).

**Round 6 follow-up fixes (development sub-agent, 2026-11-16):** D21 and D22 are fixed in code and pinned by regression tests. `CodexCliAdapter.start` translates `HostStartError` to a safe `AdapterExecutionError(ENGINE_UNAVAILABLE)` without exposing the Host reason text; the Host durable row retains its precise reason. `ProcessRunner` now uses `min(stdin_delivery_timeout_seconds, remaining resource_policy.wall_seconds)` for stdin delivery, measured from the start of `start()`. The original reproductions now produce `AdapterExecutionError code=engine_unavailable, escaped_host_reason=False` and `ProcessSpawnError code=runtime_host_pipe_setup_failed, elapsed_seconds=1.008` for the 1-second wall case. New tests: `test_codex_adapter_unit.py::test_host_start_failure_is_normalized_to_an_adapter_error` and `test_host_stdin_delivery.py::test_delivery_timeout_is_capped_by_the_process_wall_budget`. Self-check: ruff passed; non-PG lane **157 passed, 4 deselected**; Phase 4 runner/supervisor **98 passed**. D23–D27 remain open documentation/fixture follow-ups, not silently closed.

## 1. Scope and environment

Implemented and exercised in this round: fail-closed settings and stage gate, registrable typed Codex configuration, the fixed CLI argv contract, the Stage A CLI adapter over the real Phase 4 `RuntimeHost`, bounded native-event mapping and usage extraction, and the App-Server JSON-RPC codec / correlation / negotiation primitives.

Explicitly **not** exercised: credentials, tenant isolation, App-Server transport, Session persistence/Resume, migration work, the 20-scenario Stage A stability batch, and performance measurement.

**Correction (independently measured 2026-11-14 by the test sub-agent):** `codex-cli 0.169.0` **does execute successfully in this environment** with a working provider (`codex exec --json ... "reply ok"` returns exit 0, an `agent_message`, and a real `turn.completed` usage block). The development round's claim that the CLI is "Not logged in / not usable" is wrong: `codex login status` reports the auth mode, not reachability. Three measured seams used to block an adapter-mediated run — (a) the `stdin=DEVNULL` prompt gap (08 R10), (b) the empty `ProcessSpec.environment` (a `/usr/bin/env node` launcher needs `PATH`), and (c) the real event schema mismatch documented as D6 — and **all three are now closed** ((a) by R18, (b) by R17, (c) by the D6 fix). Round 5 therefore executed a real provider run **through the adapter** (A-14). What still keeps the lane `pending_env` in CI is the absence of a Codex binary there, plus credentials/tenant/Secret evidence, which this lane does not carry by construction.

**Round-6 correction (independent test sub-agent, 2026-11-15):** the round-5 snapshots A-13/A-14 and the non-PG/PG counts all reproduce (Appendix C). Two round-5 claims did **not** hold and are corrected in place: P5-IT-03's "usage without `total_tokens`" describes the frozen real transcript, not the deterministic fixture, whose `turn.completed` block **does** emit `total_tokens: 8`; and P5-CM-08's bilingual claim is false because the English `03` rollout step 2 still says "Execute planned `0055`" and the English data-model heading was renamed while the Chinese pair kept the old heading.

| Environment | Configuration | Use |
|---|---|---|
| macOS `Darwin 27.0.0`, Python 3.12.13, backend venv via `uv` | `UV_CACHE_DIR=/tmp/nexusdesk-uv-cache` | ruff, unit tests, non-PG suite |
| Dedicated Docker PostgreSQL | `pgvector/pgvector:pg17`, container started fresh for the test round on a throwaway port with a per-round database, `alembic upgrade head` | Host-backed integration tests |
| Local Codex CLI | `codex-cli 0.169.0` installed at `/usr/local/bin/codex` (a `/usr/bin/env node` launcher); **reaches the provider successfully** with `PATH` present, and executes through the adapter chain after R17+R18 (A-13/A-14) | Proves real-provider reachability and prompt delivery; the real half stays `pending_env` only where the binary is absent (CI) |
| Fake Codex fixture | `backend/tests/fixtures/codex_fake/` (deterministic simulator, unprivileged) | Deterministic integration harness only |

**Independent measurement of the real CLI (this round):**

```text
$ codex --version                       -> codex-cli 0.169.0
$ codex login status                    -> Not logged in          (auth mode label, NOT reachability)
$ codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral "reply ok"
  {"type":"thread.started","thread_id":"..."}
  {"type":"item.completed","item":{"id":"item_0","type":"error","message":"Model metadata ... not found ..."}}
  {"type":"turn.started"}
  {"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"ok"}}
  {"type":"turn.completed","usage":{"input_tokens":10526,"cached_input_tokens":10496,
    "cache_write_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":0}}
  exit 0
$ env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=<home> codex exec ... -> same success
$ env -i codex exec ...                                     -> exit 127 "env: node: No such file or directory"
```

**Skip attribution** (`-m postgres`): the PG integration module has one fixture entry point. When `TEST_DATABASE_URL` is unset it skips with `Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB` — that is an environment-selection gap, not a product defect. In this round the container was started and the tests **ran**, so the module reported 0 skips.

## 2. Execution overview

| Check | Result | Evidence |
|---|---|---|
| `uv run ruff check .` | **All checks passed** | A-1 (re-run by the test sub-agent) |
| `uv run ruff format --check src/.../adapters/codex` | **7 files already formatted** | A-2 (re-run) |
| `uv run pytest tests/agent_execution/ tests/test_local_test_adapter.py -q -m "not postgres"` | **136 passed, 3 deselected** | A-3 (re-run in round 4 after the D6/D8/D11/D12/D13/D17 fixes; round 1 measured 112 before the 24 new cases) |
| `uv run pytest tests/agent_execution/test_codex_host_integration.py -q -m postgres` | **4 passed** (round 5: fresh Docker pgvector database, real `RuntimeHost`, real process groups, plus the new prompt-consumption case) | A-4/A-4b |
| **Round 5: `uv run pytest tests/agent_execution/test_host_stdin_delivery.py -q`** | **16 passed** (15 DB-free delivery cases + 1 real-binary case that `skip`s where Codex is absent) | A-13 |
| **Round 5: full non-PG lane** | **155 passed, 4 deselected** (136 + 19: 16 stdin-delivery, +2 adapter-unit, +1 contract) | B-4 |
| Targeted regression (6 suites: `test_execution_orchestrator`, `test_agent_execution_phase3_wiring`, `test_agent_config_execution_compat`, `test_agent_execution_phase4_orchestration`, `test_agent_execution_phase4_settings`, `test_runtime_baseline`) | **385 passed, 21 deselected** | A-5 (re-run; the development round quoted 226 from the 4-suite subset, which the test sub-agent also reproduced exactly) |
| `uv run --directory backend python ../scripts/check_architecture.py` | **architecture gate passed** | A-6 (re-run) |
| Full backend suite / CI | not run locally (CI owns it) | — |

## 3. Unit tests (P5-UT) — item by item

| ID | Case | Test location | Environment | Result |
|---|---|---|---|---|
| P5-UT-01 | Two Protocols, one Engine | `test_codex_registration.py::test_both_protocols_share_one_engine_and_resolve_independently`, `::test_unknown_protocol_combinations_are_rejected`, `::test_orchestrator_closed_loop_with_an_injected_codex_selector` | local | **passed** (the Orchestrator→Adapter→outcome loop is proven with an injected selector; the Worker default is untouched) |
| P5-UT-02 | Stage A/B gate state machine | `test_codex_settings.py::test_app_server_requires_cli_and_a_verified_stage_a`, `::test_stage_a_verification_alone_does_not_enable_anything`; `test_codex_contract.py::test_stage_gate_fails_closed_and_keeps_protocols_independent` | local | **passed** (Stage B can never enable: descriptor hardwired `enabled=False`; independently re-verified with the gate forced open) |
| P5-UT-03 | Version compatibility matrix | `test_codex_contract.py::test_stage_gate_fails_closed_and_keeps_protocols_independent`; `test_codex_adapter_unit.py::test_gate_refusal_happens_before_any_host_call` | local | **passed** for the gate (unknown/high/low version denied, empty allowlist denies); real-provider version matrix `pending_env` |
| P5-UT-04 | Typed configuration / capability narrowing | `test_codex_contract.py::test_codex_config_rejects_host_paths_and_unknown_options`; `test_codex_adapter_unit.py::test_capabilities_match_the_composition_declaration` | local | **partial** — the *typing* half passes (strict/frozen/forbid, path and unknown-option rejection, bounded timeout le=600). The **capability-narrowing** half has no test: no Codex test references `effective_capabilities` (tracked as issue I12, D9). |
| P5-UT-05 | CLI argument and environment allowlist | `test_codex_adapter_unit.py::test_argv_is_the_fixed_prefix_with_zero_trailing_parameters`, `test_codex_contract.py::test_cli_invocation_is_bounded_and_contains_no_host_path_or_secret` | local | **passed** (argv is 7 code constants, 0 trailing parameters, empty env; re-asserted independently) |
| P5-UT-06 | Valid/chunked/malformed CLI output | `test_codex_events.py::test_multi_line_payload_is_parsed_per_line_in_order`, `::test_chunk_boundaries_reassemble_into_complete_events` (D8/D16: real chunk-boundary reassembly), `::test_malformed_and_oversized_lines_are_bounded_errors`, `test_codex_adapter_unit.py::test_a_malformed_native_line_fails_the_execution_as_protocol_error`, `::test_real_codex_transcript_yields_the_nested_agent_message` | local | **passed** — line-delimited parsing, chunk-boundary reassembly and the measured real transcript shape all pass. The adapter still splits `ProcessResult.stdout` after exit (no live intra-Turn stream, `08` R9); that limitation is recorded, not hidden. |
| P5-UT-07 | Usage extraction and absence | `test_codex_events.py::test_usage_reports_every_measured_field_or_unknown` (6 fields), `test_codex_adapter_unit.py::test_usage_is_measured_or_explicitly_unknown`, `::test_real_codex_transcript_yields_the_nested_agent_message` | local | **passed** — missing fields are never zero-filled, and the measured provider output has no `total_tokens`, which the adapter does not invent. |
| P5-UT-08 | Error and cancellation mapping | `test_codex_adapter_unit.py::test_wall_timeout_and_resource_reasons_map_to_frozen_codes`, `::test_cancel_is_idempotent_and_caches_the_terminal_result` | local | **partial** — Host reason codes map to frozen catalog codes with no new `ExecutionErrorCode`, but `AUTHENTICATION_FAILED`/`PERMISSION_DENIED` cannot be distinguished from a generic CLI exit in Stage A (tracked as issue I11, D10). |
| P5-UT-09 | Workspace path and link validation | `test_codex_adapter_unit.py::test_hostile_workdir_paths_are_refused_before_any_host_call` (11 traversal/absolute/encoded/drive cases), `::test_symlinked_workdir_cannot_escape_the_root`, `::test_missing_workdir_is_refused_with_workspace_error` (D11), `::test_the_root_itself_is_not_an_execution_workdir` | local | **passed (D13 fixed)** — the adapter calls `workspace_policy.normalize_relative_path`, re-checks `is_relative_to(root)` after `resolve()` and refuses with `WORKSPACE_ERROR` before any Host call; the previously untested missing-dir branch is covered too (D11). Cross-tenant mount cases remain `pending_env` (P5-IT-08). |
| P5-UT-10 | Credential reference and trust boundary | `test_codex_app_server.py::test_frames_are_private_and_never_carry_credentials`, `test_codex_events.py::test_environment_and_credential_keys_never_enter_the_payload`; gate tenant checks | local | **partial** — no credential exists in Stage A; the metadata/argv/event surfaces carry none and the D12 denylist now drops `token`/`credential`/`credential_ref` at the top level. A real Secret-canary run remains `pending_env`. |
| P5-UT-11 | JSON-RPC framing and version negotiation | `test_codex_app_server.py::test_frame_decode_is_bounded_and_requires_jsonrpc_2`, `::test_initialize_result_requires_a_supported_version`, `::test_protocol_handshake_negotiates_then_refuses_a_bad_version`, `test_codex_contract.py::test_app_server_frames_are_private_bounded_jsonrpc` | local | **passed** (pure codec; no transport) |
| P5-UT-12 | Duplicate/unknown/late JSON-RPC responses | `test_codex_app_server.py::test_handle_frame_ignores_late_responses_and_never_replays`, `::test_duplicate_and_late_ids_keep_the_frozen_semantics`, `test_codex_contract.py::test_jsonrpc_state_rejects_duplicates_and_ignores_late_responses` | local | **passed** (pending set bounded at 256, slots freed on resolve, late/duplicate ignored) |
| P5-UT-13 | Approval/input capability gate | — | — | `pending_env` / not implemented (Stage B) |
| P5-UT-14 | Session/Turn/Run mapping | — | — | `pending_env` / not implemented (Stage B) |
| P5-UT-15 | Full Session Resume reauthorization | — | — | `pending_env` / not implemented (Stage B) |
| P5-UT-16 | Reentrant Session expiration cleanup | — | — | `pending_env` / not implemented (Stage B) |
| P5-UT-17 | Log/event diagnostic bounds | `test_codex_events.py::test_oversized_payload_is_truncated_and_marked`, `::test_malformed_line_mapping_is_a_bounded_protocol_error_without_raw_text` | local | **passed** (32 KiB ceiling holds after `native_type` is added — worst case measured at 32,714 B; truncation marker; static catalog message only; stderr canary never reaches events/results) |
| P5-UT-18 | Codex switches and React default | `test_codex_settings.py` (4 tests), `test_codex_registration.py::test_default_deployment_disables_both_codex_protocols`, `::test_disabled_metadata_fails_closed_for_the_publish_path`, `::test_codex_registration_does_not_add_a_second_warm_target` | local | **passed** (every switch false, both allowlists empty, warm targets still exactly 1 — re-measured with the gate *enabled* and a real Host seam, still 1) |
| P5-UT-19 | StdIn payload validation and representation | `test_host_stdin_delivery.py::test_process_spec_rejects_empty_oversized_and_str_payloads`, `::test_the_ceiling_itself_is_accepted`, `::test_payload_ceiling_covers_the_worst_case_utf8_expansion_of_a_request`, `::test_payload_is_outside_the_command_digest`, `::test_the_payload_is_invisible_in_repr_and_dumps`, `::test_the_payload_never_enters_a_public_event_payload`; `test_codex_adapter_unit.py::test_the_prompt_is_delivered_on_stdin_and_never_in_argv`; `test_codex_contract.py::test_cli_invocation_enforces_the_stdin_byte_ceiling` | local | **passed** — `b""`, 800_001 bytes and `str` are `ValidationError`; 800_000 is accepted; `MAX_STDIN_PAYLOAD_BYTES == 4 * 200_000` and `ExecutionRequest.input` max_length is still 200_000; two specs differing only in payload have equal `command_digest`; the sentinel prompt is absent from `repr()`, `model_dump()`, a mapped `AgentEvent.payload` and a failure log line. |
| P5-UT-20 | StdIn delivery failure semantics | `test_host_stdin_delivery.py::test_no_payload_keeps_devnull_and_the_child_sees_immediate_eof`, `::test_largest_payload_is_delivered_byte_for_byte_within_the_deadline`, `::test_a_child_that_closes_early_fails_the_start_and_leaves_no_group`, `::test_a_child_that_never_reads_fails_inside_the_delivery_deadline`, `::test_delivery_failure_logs_only_stable_facts`, `::test_the_default_delivery_timeout_is_positive_and_rejects_nonpositive` | local (real pipes, real groups) | **passed** — `None` keeps `DEVNULL` (child sees immediate EOF); 800 KB with a 2s-delayed reader is delivered byte for byte; early close and never-read both fail with `runtime_host_pipe_setup_failed` inside the deadline (never-read measured well under 2s with a 0.2s deadline) and leave no process group; the failure log carries the reason/executable/run only. |

## 4. Integration tests (P5-IT) — item by item

| ID | Case | Test location | Result |
|---|---|---|---|
| P5-IT-01 | Controlled real CLI execution | `test_codex_host_integration.py::test_cli_success_end_to_end_through_the_real_host` | **partial** — fake fixture through the real Orchestrator-adjacent Host chain (gate → `ProcessSpec` → trusted target → process group → bounded stdout → events → terminal state → durable record). The fixture now emits the **measured** 0.169.0 grammar (`thread.started`/`turn.started`/`item.completed`/`turn.completed`), so the adapter's parse path is real-schema-correct (D6 fixed). The real binary also runs through this chain (A-14, P5-IT-19); this row stays `partial` only for native families beyond `agent_message`, fault injection and CI evidence. Real-provider AC-1 in **CI** remains `pending_env`. |
| P5-IT-02 | Two-Protocol registration and Stage unlock | `test_codex_registration.py` | **passed** for registration/denial and the injected-selector Orchestrator loop; App-Server denial is structural (`enabled=False`, re-verified with the gate forced open) |
| P5-IT-03 | CLI native events and usage end to end | `test_codex_host_integration.py::test_cli_success_end_to_end_through_the_real_host` | **partial** — ordering/identity/usage proven end to end for the fixture, and the fixture's event vocabulary matches the measured provider (`item.completed` with nested `item.{type,text}`). **Correction (round 6):** the fixture's `turn.completed` block still carries `total_tokens: 8`; only the frozen real transcript (`real_transcript.py`) and the measured provider omit it. The claim "usage without `total_tokens`" therefore applies to the real-transcript/real-binary evidence (A-14), not to the deterministic fixture. Real native families beyond `agent_message` (commands, file changes) and adapter-mediated provider accuracy remain `pending_env`. |
| P5-IT-04 | App-Server native stream | — | `pending_env` (Stage B locked) |
| P5-IT-05 | CLI cancellation with grandchild process | `test_codex_host_integration.py::test_cancellation_terminates_the_real_process_group` | **partial** — real group cancellation + idempotency + zero survivors; the fixture's `child` scenario (grandchild) exists in `fake_codex.py` but is **not driven by any test** |
| P5-IT-06 | CLI timeout and hang | `test_codex_host_integration.py::test_cancellation_terminates_the_real_process_group` (hang scenario, cancel path) | **partial** — cancellation proven; the wall-timeout path is unit-covered only (`test_wall_timeout_and_resource_reasons_map_to_frozen_codes`) |
| P5-IT-07 | Crash and App-Server disconnection | `test_codex_host_integration.py::test_malformed_cli_output_is_a_bounded_protocol_error` | **partial** — malformed output terminal state proven; process-crash matrix and App-Server disconnect are `pending_env` |
| P5-IT-08 | Workspace I/O and escape adversarial cases | — | `pending_env` — and the adapter's own pilot shows it accepts absolute/`..`/symlinked workdirs when the caller supplies them (D13); the production Workdir lane is the only thing preventing escape today |
| P5-IT-09 | Minimal credential exposure / Secret canary | — | `pending_env` |
| P5-IT-10 | Untrusted tenant and trust revocation | gate unit tests only | `pending_env` for the end-to-end denial |
| P5-IT-11 | JSON-RPC concurrency/disconnection | `test_codex_app_server.py` (state machine) | **partial** — pure state machine proven; no transport exists |
| P5-IT-12 | Session persistence | — | `pending_env` / not implemented |
| P5-IT-13 | Approval/input allow-deny | — | `pending_env` (Stage B) |
| P5-IT-14 | Session Resume | — | `pending_env` (Stage B) |
| P5-IT-15 | Unsupported version / bad output / missing usage | `test_codex_app_server.py::test_initialize_result_requires_a_supported_version`, `test_codex_host_integration.py::test_malformed_cli_output_is_a_bounded_protocol_error`, `test_codex_events.py::test_usage_reports_every_measured_field_or_unknown` | **partial** — all with the fixture/unit surfaces; real provider fault injection is `pending_env` |
| P5-IT-16 | Switch-off React/API/SSE regression | targeted regression above | **partial** — 385 targeted tests pass (the development round's 226 for its 4-suite subset also reproduced exactly); full-suite, frontend build and Phase 0 baseline diff are `pending_env` / **not_measured** |
| P5-IT-17 | Conditional Session migration | none created | **n/a this phase** — head is `0059_execution_runtime_host`, `0055` is taken by `0055_service_applications`; no migration was added and `git status` shows zero migration changes |
| P5-IT-18 | Stage A pre-release stability batch (20 scenarios, 3 runs) | — | `pending_env` / **not_measured** — this is exactly why Stage B stays locked |
| P5-IT-19 | Prompt delivery end to end through the Host | `test_codex_host_integration.py::test_prompt_is_consumed_from_stdin_end_to_end`; `test_host_stdin_delivery.py::test_real_codex_consumes_the_prompt_through_the_host`; A-13/A-14 | **passed (fixture half) / passed locally (real-binary half) / `pending_env` in CI** — the fixture *reads* stdin and answers with `stdin:<len>:<sha16>`, so the assertion proves consumption and EOF rather than pipe buffering; the durable record reaches a terminal state with `active_count == 0`. Through the **complete adapter → RuntimeHost → ProcessRunner chain** the real `/usr/local/bin/codex` exits **0** in ~4.7s with `output == 'ok'`, five usage counters and no `total_tokens` (A-14). The real-binary test skips where Codex is absent, so CI evidence for that half is `pending_env` by design. |

## 5. Common checks (P5-CM) — item by item

| ID | Check | Test location | Environment | Result |
|---|---|---|---|---|
| P5-CM-01 | Migration planning number and historical protection | — | — | **passed as a negative**: no migration created; head rechecked (`0059_execution_runtime_host` with `down_revision = 0058_agent_execution_metadata`), `0055_service_applications` occupied, no historical file touched (`git status` on `backend/migrations/` is empty) |
| P5-CM-02 | Configuration loading and default denial | `test_codex_settings.py` | local | **passed** (all six switches false, both allowlists empty, `AGENT_CODEX_*` env overrides work, App-Server without CLI or Stage A is rejected at settings load) |
| P5-CM-03 | Secret and sensitive-argument scan | `test_codex_adapter_unit.py::test_argv_is_the_fixed_prefix_with_zero_trailing_parameters`, `test_codex_app_server.py::test_frames_are_private_and_never_carry_credentials` | local | **partial** — an independent scan of the whole `adapters/codex/` package, the composition root and settings found **zero** secret-shaped literals, key material, bearer tokens, `auth.json` references or `~/.codex` paths; argv/frames/events carry no secret; a real Secret-canary end-to-end run is `pending_env` |
| P5-CM-04 | Tenant and Session isolation | gate tenant check only | local | **partial** — no Session store exists; tenant denial is unit-proven (untrusted tenant → `ADAPTER_DISABLED`) |
| P5-CM-05 | Native protocol boundary | `test_codex_app_server.py::test_frames_are_private_and_never_carry_credentials`, `test_codex_events.py::test_mapped_events_are_public_identity_consistent_and_monotone`, `::test_process_started_pid_is_stripped_from_the_public_payload`, `::test_jsonrpc_envelope_keys_are_stripped_but_nested_item_id_survives`, `::test_environment_and_credential_keys_never_enter_the_payload`, `::test_raw_std_streams_never_enter_the_payload` | local | **partial (D12 fixed)** — a public payload denylist now strips `pid`/`process_group_id`/`method`/`jsonrpc`/`id`/`params`/`stdout`/`stderr`/`environment`/`token`/`credential_ref` at the top level while keeping nested `item.id`; four tests pin it. Still `partial`, not `passed`, because a real-provider run has not confirmed that no other native family smuggles a private identifier. |
| P5-CM-06 | Process and connection resources | `test_codex_host_integration.py` (all three) | Docker PG + real processes | **partial** — no survivors after completed/malformed/cancelled (`health().active_count == 0` and no pending row); crash and timeout sweeps `pending_env` |
| P5-CM-07 | Observability and audit | Host `health()`/registry assertions in the integration test | Docker PG | **partial** — `active_count` reaches 0 and the run leaves no pending row; Run/Protocol/Session correlation queries `pending_env` |
| P5-CM-08 | Bilingual and requirement traceability | this report + `08` | — | **partial (round-6 correction)** — the round-5 claim of `passed` does not hold. IDs for the round-5 rows do match across the pairs (P5-UT-19/20, P5-IT-19 present in both `04` files; the R18 note present in both `05` files), and the Chinese `03` head/`0055` contradiction (D14) **is** fixed. But two English↔Chinese divergences remain inside the round-5 delta: the English `03` **rollout step 2 still reads "Execute planned `0055` only if Stage B requires it"** while the Chinese step 2 was rewritten, and the English data-model heading was renamed to "Session migration (Stage B only; not created in this phase)" while the Chinese heading still reads "规划迁移 `0055_agent_engine_sessions.py`". The `04` basis lines in both languages still cite "planned migration 0055". Ruled down to `partial`; see D25/D27. |

## 6. Regression scope

- `tests/agent_execution/` + `tests/test_local_test_adapter.py` (non-PG), **round 5 measurement**: **155 passed, 4 deselected**. Composition: `test_codex_settings` 4, `test_codex_registration` 10, `test_codex_adapter_unit` 33 (re-measured this round with `--collect-only`; the prompt-refusal case was replaced in place by the prompt-delivery case), `test_codex_events` 14, `test_codex_app_server` 12, `test_codex_contract` 8, `test_host_stdin_delivery` 16, plus the `test_local_test_adapter` 58 (which includes the Phase 4 pin test). `test_codex_host_integration` contributes 4 more under `-m postgres`. The round-4 measurement was 136 passed / 3 deselected; nothing was removed, so the +19 is entirely new coverage. **Round-6 follow-up measurement (after the D21/D22 fixes): 157 passed, 4 deselected in 18.45s**, i.e. +2 tests: `test_codex_adapter_unit` is now **34** (was 33, +`test_host_start_failure_is_normalized_to_an_adapter_error`) and `test_host_stdin_delivery` is now **17** (was 16, +`test_delivery_timeout_is_capped_by_the_process_wall_budget`). `test_codex_contract` is still 8. Appendix B-3's `16 passed` is therefore the round-5 figure; the round-6 follow-up count for that file is 17.
- Targeted Phase 2/3/4 regression: **385 passed, 21 deselected** across the six affected suites. The development round's 4-suite subset (226 passed, 21 deselected) was reproduced exactly.
- Architecture gate: passed (Core imports no business/application modules; the Codex adapter imports only contracts, Host contracts, orchestration lifecycle and its own package — confirmed by an independent AST scan: imports are `json`, `collections.abc`, `pathlib`, `uuid`, `contracts`, `host.host_models`, `host.runtime_host`, `orchestration.execution_lifecycle`, `cli_exec`, `config`, `events`).
- The pin test `test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact` now includes the seven `adapters/codex/*` modules and still passes (58 passed in that file).
- Full suite and frontend/build are **not** run locally; CI owns them.

## 7. Defects found and fixed in this round

| # | Severity | Defect | Found in | Fix | Regression |
|---|---|---|---|---|---|
| D1 | P2 | `ruff check .` failed with EXE001 on `tests/fixtures/codex_fake/fake_codex.py` (shebang without executable bit), which blocked the repository-wide lint gate. | Local self-check | Removed the shebang; the fixture is always launched through an explicit interpreter path. | `ruff check .` now passes |
| D2 | P2 | `test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact` failed because the new `adapters/codex/*` modules were not registered, silently allowing an unlisted module tree. | Local self-check | Added the seven modules to the pinned set; dependency-direction assertions now cover them too. | `tests/test_local_test_adapter.py` 58 passed |
| D3 | P2 | `ExecutionError(WORKSPACE_ERROR, WORKSPACE_ERROR)` raised by the adapter used the wrong category (the catalog requires `ExecutionErrorCategory.WORKSPACE_ERROR`, not `CONFIGURATION_ERROR`), producing a pydantic `ValidationError` instead of a safe adapter error. | PG integration run | Introduced a category-correct `_bounded_error` helper. | `test_codex_host_integration.py` 3 passed |
| D4 | P3 | Oversized event payload truncation produced a wrapper that exceeded the 32 KiB ceiling once its own JSON overhead was counted. | `test_codex_events.py` | Truncation now shrinks the preview until the serialized wrapper fits. | `test_oversized_payload_is_truncated_and_marked` passes |
| D5 | P3 | A malformed native line left the execution reporting `completed` (exit code 0) after the stream had already failed. | Adapter review | The stream now records a terminal `PROTOCOL_ERROR` result before re-raising. | `test_a_malformed_native_line_fails_the_execution_as_protocol_error` |

**Round 4 verdict (independent re-execution):** the code-only cases are green — every automated check reproduces (ruff, format, 136 non-PG, 3 PG, 385 targeted regression, architecture gate). **The four P1 defects are confirmed fixed** by re-running the original round-1 reproduction probes: D6 (real event grammar → `output == 'ok'`), D7 (reports now state the measured blockers), D12 (top-level PID/JSON-RPC keys stripped; nested business fields preserved), D13 (absolute / `..` / symlink workdirs refused before `Host.start`). D9, D10 and D14 remain open as tracked P2 issues. Stage A full acceptance and Stage B remain blocked on the real-environment evidence in §8.

**Two P3 findings from this round are now closed** (docs-only): `08` R6 was rewritten to the three measured blockers (D18, fixed in this revision), and the §7.1 "Four P1-class defects are open" sentence was superseded by the round-4 verdict (D19). Appendix A-10 is annotated as a pre-fix capture superseded by A-12 (D20).

### 7.1 Defects found by the independent re-execution (test sub-agent, 2026-11-14)

Severity follows `04-test-plan.en.md` §7. D6-D15 are added by this round; none of them was reported by the development round.

| # | Severity | Defect | Reproduction | Expected vs actual | Suggested fix |
|---|---|---|---|---|---|
| D6 | **P1 (fixed round 3)** | The fake fixture's event grammar did not match the pinned real provider, and the adapter only understood the fixture's grammar. | (a) real CLI emits `{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}`; (b) the old fixture emitted a flat `message.completed`; (c) the old `_completed_output` read only a top-level `text`, so the real answer was dropped (`output == ''`). | **Fixed:** `_completed_output` now reads `item.{type,text}` for `item.type == "agent_message"` (and ignores `item.type == "error"`) while still accepting the flat fixture shape; `fake_codex.py` emits the measured `thread.started`/`turn.started`/`item.completed`/`turn.completed` grammar; `tests/fixtures/codex_fake/real_transcript.py` freezes the measured bytes and `test_real_codex_transcript_yields_the_nested_agent_message` pins it. Re-verified: `output == ['ok']`, usage has no `total_tokens`. |
| D7 | **P1 (fixed round 3)** | This report and `07` asserted the local CLI was "Not logged in / not usable". That was false; the real provider is reachable. | `codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral` → exit 0 with `thread.started`/`turn.started`/`item.completed(agent_message)`/`turn.completed(usage)`; `env -i /usr/local/bin/codex --version` → exit 127 `env: node: No such file or directory`. | **Fixed in the report:** §1 and §2 and the 07 environment table now describe three measured blockers (stdin `DEVNULL` prompt gap; empty `ProcessSpec.environment` vs the `/usr/bin/env node` launcher; the D6 grammar) instead of a credentials claim. `pending_env` is unchanged, for the real reasons. |
| D8 | P2 (fixed round 3) | `P5-UT-06` was titled "chunked" but no chunk reassembly was tested or existed. | The old test fed whole lines. | **Fixed:** renamed to `test_multi_line_payload_is_parsed_per_line_in_order` and added `test_chunk_boundaries_reassemble_into_complete_events`, which splits the byte stream in 7-byte chunks and proves the reassembled event list is identical to the whole-blob parse (trailing partial line yields no event). |
| D9 | P2 (open — issue I12) | `P5-UT-04` claims "Agent configuration cannot expand deployment Effective capabilities" is passed. No Codex test references `effective_capabilities`, narrowing, or expansion. | `grep -rln "effective_capabilities\|narrow\|expand" tests/agent_execution/test_codex_*.py` → no hits. | Expected: a test proving `CodexConfig` cannot widen a deployment decision. Actual: only the pydantic typing half is covered. | Reclassify P5-UT-04 as `partial` (done above) or add the narrowing test. |
| D10 | P2 (open — issue I11) | `P5-UT-08` claims `AuthenticationError`/`PermissionDenied` map stably. The Codex package contains **no reference to `AUTHENTICATION` or `PERMISSION_DENIED`**; host reason codes map only to timeout/resource/engine-unavailable/protocol/cancelled. | `grep -rn "AUTHENTICATION\|PERMISSION_DENIED" src/.../adapters/codex/` → no hits (0 matches). | Expected: authentication and permission failures produce `AUTHENTICATION_FAILED` / `PERMISSION_DENIED`. Actual: any such CLI exit becomes `ENGINE_UNAVAILABLE`. | Reclassify as `partial` (done above) and add an explicit mapping or document why Stage A cannot detect auth failures. |
| D11 | P2 (fixed round 3) | The adapter's missing-workdir refusal had no test. | `grep WORKSPACE_ERROR tests/agent_execution/` previously found only the Phase 4 suite. | **Fixed:** `test_missing_workdir_is_refused_with_workspace_error` and `test_the_root_itself_is_not_an_execution_workdir` cover the branch. |
| D12 | **P1 (fixed round 3)** | `AgentEvent.payload` passed native keys through unchanged, so `pid`/`method`/`jsonrpc`/`id` reached the public surface. | `CodexEventMapper...map(CodexNativeEvent(event_type="process.started", payload={"type":"process.started","pid":4242}))` previously returned `payload={'type':..., 'pid': 4242}`. | **Fixed:** `events._public_payload` strips a top-level denylist (`pid`, `process_id`, `process_group_id`, `pgid`, `method`, `jsonrpc`, `id`, `params`, `stdout`, `stderr`, `auth`, `token`, `credential`, `credential_ref`, `environment`, `env`) before the size bound, and nested `item.id` survives. Re-verified: `{'type': 'process.started'}` and `{'item': {'id': 'item_1', ...}}`. Four tests pin it. |
| D13 | **P1 (fixed round 3)** | `(root / relative).resolve()` followed by only `is_dir()` let absolute paths, `..` and symlinks escape the workdir root into `Host.start`. | Probe with a stub Host: `execution_workdir="/tmp"` → `/private/tmp`; `"../.."` → the root's grandparent; a symlinked subdirectory → outside the root. | **Fixed:** the new `_contained_workdir` calls `workspace_policy.normalize_relative_path` (authoritative Phase 4 policy), re-checks `candidate.is_relative_to(root)` and `candidate != root` after `resolve()`, and refuses with `WORKSPACE_ERROR` before any Host call. Re-verified: `/tmp`, `../..`, `aa11/../..` and a symlinked dir are all refused with `host.started == []`; a safe `aa11` still starts. |
| D14 | P2 (**fixed round 5** — issue I13 closeable) | The Chinese `03-technical-design.md` now contradicts the English file: it still says head is `0052_memory_tasks_tenant_index` and its rollout step 2 still says "execute planned `0055` only if Stage B requires it". `08` R8 says the omission was deliberate "to avoid a numbering mismatch", but the mismatch exists in the opposite direction. | `grep -n "0052\|0055" docs/.../03-technical-design.md` → lines 19, 31, 42, 154. | Expected (CM-08): paired files agree on IDs and facts, or the divergence is recorded as a blocking docs item. Actual: two facts differ and the Chinese file was left stale. | Update the Chinese `03` facts to `0059`/occupied `0055` in the same round, or record it as a P2 blocking docs defect (it is currently only mentioned as a footnote). |
| D15 | P3 (fixed round 3) | `06` cited a non-existent test in two rows: `test_codex_events.py::test_frames_are_private_and_never_carry_credentials`; the test lives in `test_codex_app_server.py`. Related count drift: `07` §7.1 says `test_codex_registration.py` is "9 collected" (it is 10), and the development round's "50 new Codex cases" is 47 new non-PG cases (54 collected across the seven modules minus the 7 pre-existing `test_codex_contract` cases). | `grep -rn "test_frames_are_private_and_never_carry_credentials" tests/agent_execution/`; `pytest --collect-only -q tests/agent_execution/test_codex_registration.py` → 10. | Expected: every citation resolves and every count matches collection. Actual: one dead citation, two off-by counts. | Corrected in this revision for the citation (P5-UT-10 / P5-CM-03 now cite `test_codex_app_server.py`); `07` §7.1 still needs the 9→10 correction (left to the acceptance sub-agent, D15a). |
| D16 | P3 (fixed round 3) | The "chunked" test name over-claimed. | Same as D8. | **Fixed:** renamed; the P5-UT-06 row now cites the accurate names. |
| D17 | P2 (fixed round 3) | `_stream` re-emitted events on a second iteration and `collect_result` bypassed the parser, so exit-0 garbage reported `completed`. | stdout `{"type":"turn.started"}\n{not-json}\n`, exit 0 → old `collect_result()` alone returned `completed/error=None`; a second `stream_events` repeated sequence 1,2. | **Fixed:** `collect_result` now runs `CodexEventParser` over the same stdout and returns a terminal `PROTOCOL_ERROR` failure instead of `completed`; `stream_events` is claim-once and raises `INVALID_ADAPTER_STATE` on a second claim. Re-verified by `test_collect_result_rejects_a_malformed_transcript` and `test_stream_events_can_be_claimed_only_once`. |
| D18 | P3 (fixed round 4) | `08` R6 stated "a local `codex-cli 0.169.0` binary is installed, but `codex login status` reports `Not logged in`. Authenticated provider execution is therefore impossible in this environment." That was the exact claim D7 retracted; it contradicted `06` §1, `07` §2 and the measured `codex exec` success. | `grep -n "Not logged in" docs/.../08-implementation-breakdown.md` → R6 line (pre-fix). `codex exec --json ... "reply ok"` → exit 0. | Expected: R6 matches the measured blockers (stdin / env / grammar). Actual (pre-fix): the superseded credentials claim was the ruling text. | **Fixed:** R6 rewritten to the three measured blockers (stdin `DEVNULL`, empty `ProcessSpec.environment` with a `/usr/bin/env node` launcher, and the grammar gap closed by D6). |
| D19 | P3 (fixed round 4) | The §7.1 sentence "Four P1-class defects are open (D6, D7, D12, D13)" in this report was written before the fixes landed and contradicts §7.2 and this round's re-verification. | Read §7 (verdict paragraph) against §7.2. | Expected: one verdict. Actual: two contradictory verdicts in the same file until this revision. | **Corrected in this revision** (see the round-4 verdict paragraph); retained here for traceability. |
| D20 | P3 (fixed round 4) | `06` Appendix A-10 still lists the stale pre-fix reproductions (`D6 ... status=completed output=''`, `D12 ... keeps pid=424242`, `D13 ... escapes root`) without marking them superseded, so a reader skimming the appendix sees the defects as live. | Appendix A-10 vs §7.2. | Expected: appendix distinguishes pre-fix vs post-fix captures. Actual (pre-fix): only the pre-fix capture was present. | **Fixed:** A-10 annotated as a pre-fix capture superseded by A-12. |
| D21 | **P2 (fixed round 6 follow-up)** | A failed stdin delivery leaks the raw `HostStartError` past the adapter's error vocabulary: `CodexCliAdapter.start` awaits `self._host.start(...)` with no translation, so `HostStartError` (a `RuntimeError` from `host/runtime_host.py`) escapes instead of an `AdapterExecutionError`. `contracts.errors.normalize_adapter_exception` exists precisely to keep boundary failures inside the catalog, and every other adapter lane raises catalog-coded start errors (`adapter_contract_suite.test_prestart_errors_precede_handle_and_preserve_retryability`); the Codex lane does not run that suite and has no test for a Host-side start failure. `orchestrator._safe_legacy_code` maps the escape to the generic `execution_error`, so `runtime_host_pipe_setup_failed` never reaches the Run outcome. R18 makes this path reachable for an ordinary prompt-carrying request: pre-R18 the adapter refused prompt-carrying starts before the Host call, so the only way to hit it was a test with a trusted target. Not P1: the outcome is still `failed` (no false success), the durable row records the correct reason code, nothing leaks, and production cannot reach Codex anyway (R11/R16). | `/tmp/r18verify/probe13.py` (StubHost raising `HostStartError` → `type(e) is HostStartError`, `isinstance(e, AdapterExecutionError) is False`, adapter `_request` stays `None`); `/tmp/r18verify/probe12.py` (real Host + a target that exits without reading a 450 KB prompt → same escape, durable row `exited`/`runtime_host_pipe_setup_failed`, `active_count == 0`, no non-terminal row). | Expected: an `AdapterExecutionError` carrying a catalog code. Actual: `agent_platform...runtime_host.HostStartError` escaping `adapter.start`; the Run-level code degrades to `execution_error` while the durable record keeps the precise code. | **Fixed (round-6 follow-up):** `start` now catches `HostStartError` and raises `_bounded_error(ENGINE_UNAVAILABLE, ENGINE_UNAVAILABLE) from None`. **Re-verified with the original reproduction probes (round-6 follow-up):** probe13/probe27 now yield `AdapterExecutionError`, `category=engine_unavailable`, `code=engine_unavailable`, message `Engine is unavailable.` — no `runtime_host_pipe_setup_failed`, no `pipe` substring, `__suppress_context__=True`, `__cause__=None` (the `__context__` object is still the `HostStartError`, but it is display-suppressed); adapter `_request` stays `None`. probe12 (real `RuntimeHost` + fresh PG container) yields the same adapter error **while the durable row is unchanged**: `status='exited'`, `last_error_code='runtime_host_pipe_setup_failed'`, `pid`/`process_group_id` NULL, `active_count == 0`, zero non-terminal rows — so the fix alters only the adapter's exception type, not Host persistence. New test `test_host_start_failure_is_normalized_to_an_adapter_error` finally uses the previously unused `StubHost.raise_on_start` and additionally asserts `host.started == []`. |
| D22 | P2 (fixed round 6 follow-up) | The R2 (starvation) guard is bounded by a fixed 10 s module constant that ignores tighter Run/Host ceilings, so a failed start can outlive the wall ceiling that the adapter itself computes (`_wall_seconds()` = min(config, Run deadline, Host wall)). | `/tmp/r18verify/probe16.py`: `ProcessRunner()` default deadline (10 s) + `resource_policy.wall_seconds=1` + a never-reading child → `ProcessSpawnError` only after **10.03 s**. | Expected: delivery aborts inside the effective ceiling. Actual: 10.03 s, i.e. ~9 s past the 1 s wall ceiling. With the production defaults (`wall_seconds=900`) this is cosmetic, but a Run started with a 1–5 s deadline can pay 10 s before the Host even observes the start failure. | **Fixed (round-6 follow-up):** `ProcessRunner.start` records `start_monotonic`, and `_deliver_stdin` now computes `wall_remaining = max(0.0, wall_seconds - (loop.time() - start_monotonic))` and `deadline = loop.time() + min(self._stdin_timeout, wall_remaining)`, so the configured 10 s is only an upper bound and the spawn/identity-capture time is charged to the same budget. **Re-verified with the original probe16:** `wall_seconds=1` + a never-reading child + 400 KB payload → `ProcessSpawnError(runtime_host_pipe_setup_failed)` after **1.01 s** (was 10.03 s), process group gone. Legitimate deliveries are not falsely failed by the clamp: `wall_seconds=1` with 5 B and 20 000 B prompts returns in 0.02 s / 0.01 s; `wall_seconds=2` with an 800 000 B prompt and a 1 s-delayed reader returns in 1.04 s; and the 800 KB + 2 s-delayed-reader case still delivers byte-for-byte (`stdin=800000:964f4fdf3d47635c`, peak traced allocation 1.2 MB). New test `test_delivery_timeout_is_capped_by_the_process_wall_budget` deliberately keeps the 10 s default, sets `wall_seconds=1`, and asserts `elapsed < 2.0` plus `_group_gone(pid)`; my probe confirms the actual elapsed is ~1 s, not ~0 s, so the case is not vacuous. `STDIN_DELIVERY_TIMEOUT_SECONDS` remains 10.0 and the pre-existing assertion on it still passes. |
| D23 | P3 (open — round 6) | `08` R18's write-ordering point 4 claims "awaiting `wait_closed()` produces `ERROR asyncio: Exception in callback SubprocessStreamProtocol.pipe_connection_lost` noise". Re-measured, that noise does not reproduce — in either the clean-EOF path or the EPIPE path, with or without `wait_closed()`. | `/tmp/r18verify/probe23.py`, `/tmp/r18verify/probe24.py`: 0 asyncio ERROR records in all four combinations; the only observable is a `BrokenPipeError` **raised by** `wait_closed()` in the EPIPE path. | Expected: the ruling's rationale is reproducible (or stated as a preference). Actual: the measurement does not support the claim; skipping the await is still defensible (no benefit, and it can raise), but the reason given is wrong. | Reword the ordering note to the measured fact. |
| D24 | P3 (open — round 6) | The deterministic fixture carries an unreachable duplicate block: after `run_cli`'s `return 0`, a second copy of the `item.completed`/`turn.completed` emitters and its comment is dead code. | `tests/fixtures/codex_fake/fake_codex.py` lines ~88-104 (`return 0` followed by a duplicated `emit(...)` pair); `ruff` does not flag it. | Expected: one emitter. Actual: dead duplicate that reads as if it might run (it is also the block that suggests the fixture omits `total_tokens`, which it does not). | Delete the unreachable block. |
| D25 | P3 (open — round 6) | The English `03` rollout step 2 was not synced with its Chinese pair: it still instructs "Execute planned `0055` only if Stage B requires it", i.e. the exact `0055` decision D14's fix removed, and the English data-model heading no longer matches the Chinese one. | `grep -n "Execute planned" docs/.../03-technical-design.en.md` → line 160; `grep -n "本阶段不新增迁移" docs/.../03-technical-design.md` → line 161. Heading: EN "### Session migration (Stage B only; not created in this phase)" vs CN "### 规划迁移 `0055_agent_engine_sessions.py`（仅 Stage B 需要时）". `04` basis lines in both languages still say "planned migration 0055". | Expected: paired files agree on the `0055` decision. Actual: the Chinese file is correct and the English file still carries the pre-fix instruction. This is why P5-CM-08 is ruled down to `partial`. | Sync EN step 2 and the heading pair; update both `04` basis lines. |
| D26 | P3 (open — round 6) | The "payload never reaches an exception message" invariant does not cover pydantic's own validation error: a `str` (or oversized) `stdin_payload` makes `ValidationError.__str__` echo the prompt prefix and `e.errors()[0]["input"]` retain the **whole** payload, so `repr=False`/`exclude=True` only protect `repr()` and serialization, not validation failures. | `/tmp/r18verify/probe9.py`: `ProcessSpec(stdin_payload="SENTINEL-12345-UNIQUE secret-user-text ...")` → `1 validation error for ProcessSpec / stdin_payload / Input should be a valid bytes [... input_value='SENTINEL-12345-UNIQUE se...-text secret-user-text ', input_type=str]`; `errors()[0]["input"]` holds the entire string. Oversized bytes behave the same (`errors()[0]["input"]` retained 2 100 000 bytes). | Expected: no prompt text in any exception surface. Actual: prompt text appears in `str(e)` (truncated, start+tail) and verbatim in `e.errors()[0]["input"]`. Latent only: the adapter encodes to `bytes` and enforces the ceiling before constructing the spec, and no Host/Runner path logs exception text (`_stable_code` collapses to a code), so no current production path prints it — but the DTO is not leak-proof by construction and the existing tests never assert the error text. | Document the boundary explicitly, or validate through a pre-checked constructor and/or add a test asserting the validation error's `str()` does not carry prompt content for the paths the adapter can produce. |
| D27 | P3 (open — round 6) | Count drift between this report's round-5 figures and the acceptance report: `07` still records `136 non-PG` (§2 preconditions and §7.2), `3 passed` for the PG module (§2.4), and V12's per-file collections `adapter_unit 31 / contract 7 / host_integration 3`, while the round-5 tree collects 33/8/4 and the module passes 4. `06` A-7b likewise still shows `test_codex_contract.py → 7 passed` although A-7 in the same appendix lists 8. | `uv run pytest tests/agent_execution/ tests/test_local_test_adapter.py -q -m "not postgres"` → **155 passed, 4 deselected**; `uv run pytest tests/agent_execution/test_codex_host_integration.py -q -m postgres` → **4 passed**; per-file `--collect-only -q`: settings 4, registration 10, adapter_unit 33, events 14, app_server 12, contract 8, host_integration 4, host_stdin_delivery 16, local_test_adapter 58. | Expected: the acceptance report's executed numbers match the tree it accepts. Actual: §2.4 mixes round-5 (155) and round-4 (3 passed, V12 counts) figures. | Re-measure and sync `07` §2/§2.4/§7.2/V12 and `06` A-7b; treat the acceptance delta fingerprint in `07` §2.1 as stale too (28 files claimed, 37 files present). |

### 7.3 Round-4 independent re-verification (test sub-agent, 2026-11-14)

Re-ran the original round-1 reproduction probes against the fixed tree. Every command below was executed in this round.

| # | Probe | Result |
|---|---|---|
| D13 | stub Host, `execution_workdir` ∈ {`/tmp`, `../..`, `aa11/../..`, `aa11\..`, `aa11%2f..`}, plus a symlinked subdirectory | all refused `workspace_error`, `host.started == 0`; control `aa11` starts inside the root; nested `aa11/bb22` starts; `adhoc/<uuid>` still works (UUID hyphens accepted by the policy) |
| D12 | payload with 16 forbidden top-level keys | `payload={'type': 'process.started'}`, zero leaks; nested `item.{id,type,text,command}` and `turn.completed.usage` fully preserved; common keys (`type`,`usage`,`text`,`item`,`thread_id`,`command`,`status`,`exit_code`,`message`,`turn_id`,`error`) all preserved |
| D6 | `real_transcript.REAL_CODEX_SUCCESS_TRANSCRIPT` through `_completed_output` | `output='ok'`, 5-field usage, **no** `total_tokens`; `item.type=="error"` excluded; minimal transcript also `'ok'`; dual-syntax case prefers the nested text; multiple `agent_message` items join with `\n` |
| D17 | `{not-json}` with exit 0 via `collect_result` alone; second `stream_events` | `failed`/`protocol_error`; second claim raises `invalid_adapter_state` (also when the first generator was never iterated) |
| R2.4 | normal Orchestrator order (stream then collect) | 4 events, `completed`, `output='ok'` |

### 7.2 Round-3 fix verification (development sub-agent, 2026-11-14)

Each P1 was re-run with its original reproduction command after the fix.

| # | Reproduction command | Round-3 result |
|---|---|---|
| D6 | Feed `codex_fake/real_transcript.py:REAL_CODEX_SUCCESS_TRANSCRIPT` through `CodexCliAdapter._completed_output` | `output == 'ok'`; usage `{'input_tokens': 10525, 'output_tokens': 2, 'cached_input_tokens': 10240, 'cache_write_input_tokens': 0, 'reasoning_output_tokens': 0}`; no `total_tokens` invented |
| D7 | `env -i /usr/local/bin/codex --version` vs `env PATH=... codex exec --json ...` | exit **127** `env: node: No such file or directory` vs exit **0** with real events — both blockers measured and recorded in §1 |
| D12 | `map(CodexNativeEvent("process.started", {"type":"process.started","pid":4242}))` | `{'type': 'process.started'}` (no `pid`); a JSON-RPC frame yields `{'item': {'id': 'item_1', 'text': 'ok'}}` |
| D13 | Stub-Host probe of `execution_workdir` values `/tmp`, `../..`, `aa11/../..`, symlinked `aa11/linked` | all four refused with `workspace_error`, `host.started == []`; a plain `aa11` still starts inside the root |
| D17 | stdout `{"type":"turn.started"}\n{not-json}\n`, exit 0 | `collect_result` → `failed` / `PROTOCOL_ERROR`; a second `stream_events` → `INVALID_ADAPTER_STATE` |

## 8. Residual risks

| # | Severity | Description | Disposition |
|---|---|---|---|
| R1 | ~~P1 gate~~ **closed round 5** | A real Codex provider is reachable and the adapter now understands the measured 0.169.0 grammar (D6). The two remaining lane seams — prompt delivery (R4) and the empty `ProcessSpec.environment` (R10) — were closed in rounds 4/5 (R17/R18), and the complete adapter → `RuntimeHost` → real-binary chain now completes a Turn (A-14: exit 0, `output == 'ok'`, 5-counter usage, no `total_tokens`, ~4.7s). | **Closed for the measured local environment.** Credential/tenant/Secret evidence (R2) and the 20-scenario batch (R6) are separate and still open. |
| R2 | P1 gate | Credentials, tenant isolation and Secret-canary evidence are absent by construction: Stage A carries no credential. | `pending_env`; must be closed before any trusted-tenant enablement. |
| R3 | P1 gate | App-Server transport, JSON-RPC end-to-end, Session persistence and Resume are unimplemented; Stage B is locked. | Owner: future Stage B work; the descriptor is hardwired disabled (independently re-verified with the gate forced open). |
| R4 | ~~P2~~ **closed round 5** | A real prompt could not be delivered because the Phase 4 Host fixed stdin to `DEVNULL` and `ProcessSpec` had no payload field. **Closed by `08` R18:** `ProcessSpec.stdin_payload` (bounded `bytes`, default `None` = `DEVNULL`), Host write + EOF-close inside a deadline capped at 10 seconds and by the remaining process wall budget, adapter encodes `request.input` once with `INVALID_REQUEST` on an unencodable/over-ceiling prompt, and the `promptless_target` bypass is deleted. Measured against the real binary end to end (A-14). | Closed; see P5-UT-19/20 and P5-IT-19. Residual: CI has no binary, so the real-binary case is `pending_env`. |
| R5 | P2 | The production Worker selector is the fixed constant `("react","native","v1")`, so a production Run cannot reach Codex even when the gate would permit it. | Intentional per the coordination ruling (no production routing change); documented in `08` R11. |
| R6 | P2 | The Stage A 20-scenario / 3-consecutive-run stability batch and Phase 0 baseline diff were not measured. | `not_measured`; Stage B must not unlock without them. |
| R7 | P3 | Performance p50/p95 was not measured. | `not_measured`; requires a real provider. |
| R8 | P2 | Publishing a Codex engine configuration is still refused: `AdapterRegistry.validate_config` validates a non-React engine against the *empty* `react` projection, so `CodexConfig` (which requires `version`) rejects it with `invalid_request`. Independently re-measured with the gate open: the descriptor reports `enabled=True` while `validate_config` still raises `invalid_request`. | Documented limitation; the production Run path cannot reach Codex anyway (R5 / `08` R11). Issue candidate I7. |
| R9 | P2 | The production `TrustedTargetRegistry` remains empty (`ProcessRunner(TrustedTargetRegistry(()))`, re-verified as the only construction site), so even with the CLI gate enabled a real Run's `Host.start` would refuse the `codex` executable as untrusted and fail closed with `ENGINE_UNAVAILABLE`. | Intentional fail-closed state; registering a real executable is a later deployment decision (issue I2). |
| R10 | ~~P2~~ **closed (R17 + R18)** | The `ProcessSpec.environment` map was empty while the installed `codex` is a `/usr/bin/env node` launcher (measured exit **127**). Fixed in round 4 by the typed `path_env` (R17). The second half of the same lane — prompt delivery — was closed in round 5 by the stdin channel (R18). Both are now measured against the real binary: `environment={"PATH": …}` + `stdin_payload=prompt` → exit **0** with a real answer (A-13/A-14). | Closed. |
| R11 | P2 | The production capability barrier refuses Codex **before** `adapter.start` even with the gate fully open: `NoTrustedWorkspaceGeneration.current()` returns `None`, so `workspace_required` narrows to `workspace_unavailable`, and `policy` resolves to `None` with `required_capabilities_missing=('streaming','cancellation','native_events','workspace_required')`. Independently re-measured through the real resolver. This is genuine fail-closed behaviour, but it means "enable the gate" alone can never produce a Codex Run. | Intentional (`08` R13); recorded so no later reader mistakes it for a missing implementation. |

## 9. Follow-up issue candidates

| # | Suggested title |
|---|---|
| I1 | ~~`feat(backend): deliver a Codex prompt through the RuntimeHost (stdin channel or argv file)`~~ — **closed round 5 by `08` R18** (bounded Host stdin channel; argv deliberately untouched) |
| I2 | `feat(backend): add a Codex selection path for the Worker (routing + settings) without weakening the React default` |
| I3 | `test(backend): run the Phase 5 Stage A 20-scenario / 3-run stability batch against a verified Codex binary` |
| I4 | `feat(backend): implement Stage B App-Server transport + Session persistence (head+1 migration) once the Stage A gate passes` |
| I5 | `test(backend): add Workspace traversal/symlink/cross-tenant adversarial cases for the Codex Workdir lane` (see D13) |
| I6 | `test(backend): record Phase 0 baseline diff and performance p50/p95 for the Codex lane` |
| I7 | `feat(backend): project a Codex engine configuration through the publish path (AdapterRegistry.validate_config currently validates it against the empty react block)` |
| I8 | ~~`fix(backend): set a minimal ProcessSpec.environment (PATH) for the /usr/bin/env node Codex launcher`~~ — **closed round 4 by `08` R17** |
| I9 | `test(backend): confirm on a real provider that no other Codex native family smuggles a private identifier past the payload denylist` (follow-up to the fixed D12) |
| I10 | `test(backend): add cross-tenant mount adversarial cases for the Codex Workdir lane` (follow-up to the fixed D13) |
| I11 | `feat(backend): distinguish Codex authentication and permission failures from a generic engine-unavailable exit` (D10) |
| I12 | `test(backend): prove an Agent configuration cannot widen a Codex deployment Effective capability decision` (D9) |
| I13 | `docs(docs): synchronize the Chinese 03-technical-design.md head (0052 vs 0059) and the 0055 rollout step` (D14) |
| I14 | ~~`fix(backend): map a failed Codex Host start onto a catalog-coded AdapterExecutionError instead of letting HostStartError escape`~~ — **closed round-6 follow-up by D21** (adapter catches `HostStartError`, raises `ENGINE_UNAVAILABLE` with `from None`) |
| I15 | ~~`fix(backend): bound the Host stdin delivery deadline by the effective Run/Host wall ceiling`~~ — **closed round-6 follow-up by D22** (`deadline = min(configured timeout, wall - elapsed)`) |
| I16 | `docs(docs): correct the R18 ordering rationale for skipping stdin.wait_closed, and remove the unreachable duplicate block in fake_codex.py` (D23, D24) |
| I17 | `docs(docs): sync the English 03 rollout step 2 and data-model heading with the Chinese pair, and refresh the stale executed counts in 07 §2/§2.4/§7.2/V12 and 06 A-7b` (D25, D27) |
| I18 | `test(backend): decide and document the prompt-leak boundary of pydantic ValidationError for ProcessSpec.stdin_payload` (D26) |
| I19 | `fix(backend): sweep or delete the adapter-created adhoc/<execution_id> Workdir when Host.start fails after it was created` — measured by `/tmp/r18verify/probe19.py`: a delivery failure leaves `adhoc/<uuid>` behind; `ExecutionWorkspaceManager.sweep_expired` only iterates DB-recorded workdirs, and an adhoc directory has no record, so it is never reclaimed. Pre-existing for any Host start failure, but R18 adds a new prompt-dependent trigger. Low priority: empty, owner-only directory, no data. |
| I20 | `docs(docs): note that ProcessSpec.model_dump() drops stdin_payload, so a future dump->validate round trip would silently turn a prompt-carrying spec into a DEVNULL one` — measured by `/tmp/r18verify/probe9.py`; no such round trip exists today. |
| I21 | `test(backend): define the AC-S1..AC-S8 identifiers used in test_host_stdin_delivery.py inside 04-test-plan, or replace them with the P5-UT-19/20 + P5-IT-19 IDs` — the labels currently exist only as test comments, so they carry no requirement traceability. |

## 10. CI evidence

No pull request was opened in this round (the coordination rules forbid committing/pushing). CI evidence is therefore absent; the local evidence in Appendix A is the only executed evidence and it covers the Codex lane plus a targeted Phase 2/3/4 regression, **not** the full suite.

> **Revision 2026-11-18 (scope-limited acceptance):** under `05-acceptance-plan.md` §6.1, CI provenance at the final PR head (this section), the Phase 0 baseline diff (P5-IT-16 / R6 / L14), the startup/execution p50/p95 and sample-size items (R7 / L15), and the P5-IT-18 "20 scenarios × 3 runs" / stability-batch reading as a **stage-acceptance** exit criterion are no longer stage gates. CI runs and performance/baseline items remain recorded facts and historical context; P5-IT-18 stays unchanged as the separate high-risk Stage B unlock condition. This note changes no row, count, verdict, or conclusion above, keeps Stage B locked, and is not an acceptance conclusion.

## Appendix A — local execution snapshots (2026-11-14, working directory `backend/`)

Every block below is a captured tail from the test sub-agent's independent re-execution unless marked "development round".

A-1 `UV_CACHE_DIR=/tmp/nexusdesk-uv-cache uv run ruff check .`

```text
All checks passed!
```

A-2 `UV_CACHE_DIR=/tmp/nexusdesk-uv-cache uv run ruff format --check src/agent_platform/core_platform/agent_execution/adapters/codex`

```text
7 files already formatted
```

A-3 `UV_CACHE_DIR=/tmp/nexusdesk-uv-cache uv run pytest tests/agent_execution/ tests/test_local_test_adapter.py -q -m "not postgres"`

```text
................................................................         [ 52%]
................................................................         [100%]
136 passed, 3 deselected in 1.02s

(round-3 collection: 136/139 tests collected, 3 deselected; the +24 over the
round-2 count are the D6/D11/D12/D13/D17 regression tests)
```

A-4 `set -a; . <mode-600 TEST_DATABASE_URL file>; set +a; uv run pytest tests/agent_execution/test_codex_host_integration.py -q -m postgres`

```text
...                                                                      [100%]
3 passed, 6 warnings in 2.52s
```

Container: `pgvector/pgvector:pg17`, started fresh for this round on a throwaway port, credentials in a mode-600 `/tmp` file (never printed, never in the repo). The module creates `phase5_codex_<uuid>` and drops it afterwards with `WITH (FORCE)`. The 6 warnings are the pre-existing `os.fork()` DeprecationWarning from `host/sandbox_provider.py:224`.

A-5 Targeted regression (4 suites, matching the development round's claim)

```text
226 passed, 21 deselected in 1.36s
```

A-5b Targeted regression (6 suites, this round's wider scope: adds `test_agent_execution_phase4_settings.py` and `test_runtime_baseline.py`)

```text
385 passed, 21 deselected in 4.51s
```

A-6 `UV_CACHE_DIR=/tmp/nexusdesk-uv-cache uv run --directory backend python ../scripts/check_architecture.py`

```text
architecture gate passed
```

A-7 Per-file collection counts (re-measured with `--collect-only -q`)

```text
test_codex_settings.py           4
test_codex_registration.py      10
test_codex_adapter_unit.py      33   (re-measured this round; 22 test functions + 11 parametrized workdir cases)
test_codex_events.py            14   (9 in round 1; +5 for D8/D12)
test_codex_app_server.py        12
test_codex_host_integration.py   4  (postgres; +1 prompt-consumption case)
test_codex_contract.py           8
test_local_test_adapter.py      58
```

A-7b `test_codex_contract.py` and `test_local_test_adapter.py`

```text
7 passed in 0.12s
58 passed in 0.20s
```

A-8 Real Codex CLI reachability (this round) — values only, no credentials

```text
$ codex --version
codex-cli 0.169.0
$ codex login status
Not logged in
$ codex exec --json --sandbox read-only --skip-git-repo-check --ephemeral "reply ok"
{"type":"thread.started","thread_id":"<id>"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Model metadata ... not found ..."}}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"ok"}}
{"type":"turn.completed","usage":{"input_tokens":10526,"cached_input_tokens":10496,
  "cache_write_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":0}}
exit 0
$ env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=<home> codex exec ...   -> same success, exit 0
$ env -i codex exec ...                                                 -> exit 127 "env: node: No such file or directory"
$ <codex argv> ... - </dev/null                                         -> exit 1 "No prompt provided via stdin."
```

A-9 Independent invariant probes (all PASS unless noted)

```text
B1  argv == CODEX_CLI_FIXED_ARGV (7 tokens, 0 trailing), executable_id == "codex", environment {}
B2  default: warm_targets == 1 (react/native); metadata("codex", cli_exec|app_server) -> adapter_disabled
B3  fully-configured gate: gate.deployment_enabled(app_server) == True BUT descriptor.enabled == False
B4  descriptor.declared == instance.get_capabilities() == declared_capabilities()
B5  denial() and deployment_enabled() share one source across 7 gate states
B6  prompt-carrying start -> ENGINE_UNAVAILABLE, host.start call count == 0
B7  parse_usage: 6 fields, partial never zero-filled, missing -> {"status":"unknown"}
B8  events: codex.* grammar valid, sequence 1..n, 32 KiB ceiling holds (worst 32,714 B)
B9  JsonRpcState: default max_pending 256, bounded, duplicate/late ignored, clear drops
B10 one host.wait for stream+collect+cancel (cached ProcessResult); cancel call count 0
C1  secret scan over 9 files: 0 hits (no sk-, AKIA, bearer, key block, auth.json, ~/.codex)
C2  public DTO fields: no method/request_id/jsonrpc field; only the documented process_id slot
C3  ProcessRunner(TrustedTargetRegistry(())) is the only construction site
C4  adapter.py AST: no subprocess/signal/os/multiprocessing/pty/resource import, no Popen/kill/fork/spawnv
```

A-10 Independent defect reproductions — **pre-fix captures (round 1, superseded by §7.3 / A-12)**

```text
D6  real 0.169.0 stdout through the adapter -> status=completed output='' (real answer "ok" dropped)
D12 payload {"type":"process.started","pid":424242} -> public event payload keeps pid=424242
D13 execution_workdir="/tmp"      -> Host working_dir=/private/tmp        (escapes root)
    execution_workdir="../.."     -> Host working_dir=<root grandparent>  (escapes root)
    execution_workdir="link"      -> Host working_dir=<outside dir>       (symlink escape)
D17 collect_result() alone on "{not-json}" with exit 0 -> status=completed, error=None
    stream_events() twice                        -> sequence 1,2 then 1,2 (replay)
R8  gate open: descriptor.enabled == True, validate_config(codex) -> invalid_request
R11 capability barrier with gate open: policy is None,
    required_capabilities_missing=('streaming','cancellation','native_events','workspace_required')
```

A-12 Round-4 post-fix re-verification (original probes re-run on the fixed tree)

```text
D13 absolute /tmp                  -> workspace_error, host.started=0     PASS
D13 traversal ../..                -> workspace_error, host.started=0     PASS
D13 traversal aa11/../..           -> workspace_error, host.started=0     PASS
D13 backslash aa11\..              -> workspace_error, host.started=0     PASS
D13 percent aa11%2f..              -> workspace_error, host.started=0     PASS
D13 symlinked subdirectory         -> workspace_error, host.started=0     PASS
D13 control aa11                   -> started=1, working_dir inside root  PASS
D13 nested aa11/bb22               -> started=1                           PASS
R2.2 adhoc/<execution_id>          -> started=1 (UUID hyphens accepted)    PASS
D12 16 forbidden top-level keys    -> payload={'type':'process.started'}   PASS
R2.1 nested item.id/type/text      -> preserved verbatim                  PASS
R2.1 nested turn.completed.usage   -> preserved verbatim                  PASS
R2.1 thread_id / command_execution -> preserved verbatim                  PASS
D6 real transcript                 -> output='ok', 5-field usage, no total_tokens  PASS
D6 minimal transcript              -> output='ok'                          PASS
D6 error item excluded             -> output='' (diagnostic not mixed)     PASS
R2.3 dual syntax                   -> nested text wins ('NESTED')           PASS
R2.3 multiple agent_message items  -> joined with '\n' ('one\ntwo')        INFO
D17 collect_result on {not-json}   -> failed / protocol_error              PASS
D17 second stream claim            -> invalid_adapter_state                PASS
R2.4 stream then collect (normal)  -> 4 events, completed, output='ok'     PASS
```

Residual observations from round 4 (not P1, recorded for the next round):
- `collect_result` classifies a truncated-but-otherwise-valid stdout whose last line is incomplete as `PROTOCOL_ERROR` even when the Host already reported `runtime_host_output_limit_exceeded` (the reason code is checked after the transcript validation). Complete-lines-only output still maps to `resource_exhausted`. Pre-existing ordering, unchanged by these fixes.
- The denylist is top-level by design; a nested `item.pid` survives (ordinary item data). No measured native family emits one today.

A-11 Independent doc-citation resolution

```text
cited test references in 06 + 07: 34   resolvable: 33   missing: 1
  missing: test_codex_events.py::test_frames_are_private_and_never_carry_credentials  (D15)
```

## Appendix B — round 5 (`08` R18 prompt delivery) local execution snapshots (2026-11-14)

Working directory `backend/`, `UV_CACHE_DIR=/tmp/nexusdesk-uv-cache`. Every block is a captured tail from this round's execution.

B-1 `uv run ruff check .`

```text
All checks passed!
```

B-2 `uv run ruff format --check src/agent_platform/core_platform/agent_execution tests/agent_execution`

```text
76 files already formatted
```

B-3 `uv run pytest tests/agent_execution/test_host_stdin_delivery.py -q`

```text
................                                                         [100%]
16 passed in 8.53s
```

B-4 `uv run pytest tests/agent_execution/ tests/test_local_test_adapter.py -q -m "not postgres"`

```text
........................................................................ [ 46%]
........................................................................ [ 93%]
..........                                                               [100%]
155 passed, 4 deselected in 9.53s
```

B-5 Targeted regression, 4 Phase 4 Host suites (`test_agent_execution_phase4_runner`, `_supervisor`, `_observability`, `_sandbox`)

```text
143 passed, 3 skipped, 9 deselected, 19 warnings in 3.10s
```

B-6 Targeted regression, 5 Phase 2/3/4 orchestration suites (`test_execution_orchestrator`, `test_agent_execution_phase3_wiring`, `test_agent_config_execution_compat`, `test_agent_execution_phase4_orchestration`, `test_runtime_baseline`)

```text
314 passed, 21 deselected in 4.30s
```

B-7 `uv run --directory backend python ../scripts/check_architecture.py`

```text
architecture gate passed
```

A-4b PG integration (fresh throwaway `pgvector/pgvector:pg17` container on port 55433, credentials in a mode-600 `/tmp` file never printed; `test_codex_host_integration`, `test_agent_execution_phase4_orchestration`, `test_agent_execution_phase4_runtime_host`, `-m postgres`)

```text
................                                                         [100%]
16 passed, 16 deselected, 22 warnings in 10.61s
```

The 4 Codex rows include the new `test_prompt_is_consumed_from_stdin_end_to_end`; the 22 warnings are the pre-existing `os.fork()` DeprecationWarnings from `host/sandbox_provider.py:224`.

A-13 Real binary through the raw Host channel (no adapter). Spec: `executable_id="codex"`, `argv=CODEX_CLI_FIXED_ARGV`, `environment={"PATH": "/usr/local/bin:/usr/bin:/bin"}`, `stdin_payload=b"Reply with exactly the word: ok"`, `/usr/local/bin/codex`, real `ProcessRunner` + `ProcessSupervisor`.

```text
exit_code: 0
final_state: exited reason: runtime_host_exited
wall_seconds(host): 6.42 probe_elapsed: 6.44
stderr_len: 496
OUT: {"type":"thread.started","thread_id":"<uuid>"}
OUT: {"type":"item.completed","item":{"id":"item_0","type":"error","message":"Model metadata for `deepseek-v4-1-flash-261017` not found. Defaulting to fallback metadata; ..."}}
OUT: {"type":"turn.started"}
OUT: {"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"ok"}}
OUT: {"type":"turn.completed","usage":{"input_tokens":10549,"cached_input_tokens":10240,"cache_write_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":0}}
ERR_HEAD: ... ERROR codex_core::session::session: failed to load skill /Users/<user>/.agents/skills/daily-report/SKILL.md: invalid YAML ...
```

A-14 Real binary through the **complete adapter chain** (`CodexCliAdapter` → `RuntimeHost` → `ProcessRunner`, real `ProcessRegistry` on a migrated throwaway database, production-default `ResourcePolicy`, real `codex-cli 0.169.0`)

```text
exit_via_outcome_status: completed
host_result: final_state='exited' reason_code='runtime_host_exited' exit_code=0 term_signal=None
stdout: thread.started / item.completed(item.type=error) / turn.started /
        item.completed(item.type=agent_message,text="ok") / turn.completed(usage)
output: 'ok'
usage: {'input_tokens': 10603, 'output_tokens': 2, 'cached_input_tokens': 10240,
        'cache_write_input_tokens': 0, 'reasoning_output_tokens': 0}
events: ['codex.thread.started', 'codex.item.completed', 'codex.turn.started',
         'codex.item.completed', 'codex.turn.completed']
elapsed_s: 4.68
history_tail: {'role': 'assistant', 'content': 'ok'}
active_count: 0
pending_rows_for_run: []
```

Notes on A-13/A-14, recorded so no later reader misreads them:
- The provider is the same local model endpoint the environment already uses; `codex login status` reports `Not logged in`, which is an auth-mode label and not a reachability verdict (D7).
- The `item.type == "error"` line is the provider's own model-metadata diagnostic; the adapter correctly does **not** treat it as the answer (D6 behaviour preserved end to end).
- An early probe run used a `workdir_file_bytes` of 16 MiB and was killed with SIGXFSZ (`reason_code=runtime_host_resource_exceeded`, exit_code=None, term_signal=25) because the real CLI writes more than that. That is the deployment `RLIMIT_FSIZE` doing its job, not a delivery defect; A-14 uses the production-default 128 MiB file ceiling. **Deployments enabling the Codex lane must keep `execution_workdir_max_file_bytes` comfortably above the CLI's own write volume.**
- The first probe attempt also failed before the database was migrated (`relation "runtime_runs" does not exist`); the numbers above are from the migrated throwaway database.

## Appendix C — round-6 independent re-execution (test sub-agent, 2026-11-15)

Every number below was re-measured first-hand on the round-5 tree; nothing is copied from the development round. Working directory `backend/`, `UV_CACHE_DIR=/tmp/nexusdesk-uv-cache`. Ad-hoc probes live outside the repository at `/tmp/r18verify/probe*.py`, `/tmp/r18verify/a13.py`, `/tmp/r18verify/a14.py`, `/tmp/r18verify/pgleak.py`; they are deliberately uncommitted.

C-1 Lint and format

```text
uv run ruff check .                                  -> All checks passed!
uv run ruff format --check src/agent_platform/core_platform/agent_execution tests/agent_execution
                                                     -> 76 files already formatted
uv run ruff format --check src/.../adapters/codex    -> 7 files already formatted
```

C-2 `uv run pytest tests/agent_execution/ tests/test_local_test_adapter.py -q -m "not postgres"`

```text
155 passed, 4 deselected in 21.25s
```

C-3 Phase 4 Host suites (`_runner`, `_supervisor`, `_observability`, `_sandbox`, `-m "not postgres"`)

```text
143 passed, 3 skipped, 9 deselected, 19 warnings in 2.98s
```

C-4 Orchestration regression

```text
5 suites (orchestrator, phase3_wiring, config_compat, phase4_orchestration, runtime_baseline):
314 passed, 21 deselected in 4.30s
6 suites (same + test_agent_execution_phase4_settings):
385 passed, 21 deselected in 4.69s
```

C-5 `uv run --directory backend python ../scripts/check_architecture.py` → `architecture gate passed`.

C-6 PostgreSQL, run for real (not skipped): a fresh `pgvector/pgvector:pg17` container (`nexusdesk-pg-r18-test`, new database, nothing reused) on `127.0.0.1:55433`, connection string written to a mode-600 `/tmp` file and injected with `set -a; . file; set +a` (never printed).

```text
uv run pytest tests/agent_execution/test_codex_host_integration.py \
  tests/test_agent_execution_phase4_orchestration.py \
  tests/test_agent_execution_phase4_runtime_host.py -q -m postgres
-> 16 passed, 16 deselected, 22 warnings in 11.05s

uv run pytest tests/agent_execution/test_codex_host_integration.py -q -m postgres
-> 4 passed, 8 warnings in 3.43s
```

The container was stopped afterwards and the credential file deleted.

C-7 `uv run pytest tests/agent_execution/test_host_stdin_delivery.py -q`, three consecutive runs (the real-binary case runs here because `/usr/local/bin/codex` exists)

```text
16 passed in 9.38s / 16 passed in 7.12s / 16 passed in 7.45s
```

C-8 R1/R2 re-measured with my own trusted target, not the shipped test (probe.py)

```text
no payload   -> child sees fd0 as a character device (DEVNULL), len=0, exit 0
payload      -> child sees fd0 as a FIFO, exact bytes+sha16, exit 0
R1 400_000 B to a child that exits without reading
             -> ProcessSpawnError(code=runtime_host_pipe_setup_failed) in 0.02s; group gone (own
                process_identity.process_alive/group_alive poll, not the test's assertion)
R2 400_000 B to a child that never reads, deadline 0.2s
             -> same code in 0.21s; group gone
reverse 20_000 B to a never-reading child, deadline 0.2s
             -> start RETURNS (kernel pipe buffer absorbs it) -- so R2's 400 KB choice is load-bearing
child closes fd0 but stays alive (400_000 B)          -> same code in 0.02s, group gone
child spawns a grandchild then closes fd0 (400_000 B) -> same code, whole group gone
partial reader (reads 10 B then exits, 400_000 B)     -> same code
EPIPE shape: write() does not raise; drain() raises BrokenPipeError(32) / ConnectionResetError,
             both OSError subclasses, so the except OSError arm is what fires
payload-size boundary against an immediately-exiting child: 1/64/4096/65536 B all return a handle
             (buffered, no EPIPE observable); >=200_000 B always raises. Small-payload refusal is
             therefore reported by the child's exit code downstream, not by delivery failure.
```

C-9 No half-started handle, and cleanup is real

```text
adapter.start on a delivery failure raises; adapter._request/_managed_id/_handle stay None;
durable row status='exited', last_error_code='runtime_host_pipe_setup_failed',
pid/process_group_id NULL, active_count == 0, zero non-terminal rows.
fd count (macOS /dev/fd): 7 -> 7 across 20 successful deliveries, 5 failed deliveries,
100 cancelled deliveries, and 30 runs that never close the pump. No background asyncio tasks
left after a failed delivery. 100 cancellations mid-drain leave zero live pids and stdin closed.
Memory for an 800_000 B write: tracemalloc peak +1.2 MB, start returns in 2.05s against a reader
that delays 2s (ordering probe: a child writing 200_000 B to stdout before reading stdin does not
deadlock because the pumps start first).
```

C-10 Leak boundary, sentinel `SENTINEL-12345-UNIQUE`

```text
repr(spec) / spec.model_dump() / spec.model_dump_json() : no sentinel; "stdin_payload" absent from
model_dump(); model_dump(include={"stdin_payload"}) == {}; model_json_schema() lists the field NAME
only (no value).
command_digest identical for specs differing only in payload; policy_digest identical and stable
(only resource_policy is hashed).
Real adapter -> RuntimeHost -> fake fixture (prompt-digest) on throwaway PG:
  outcome 'stdin=35:6c01872971952c36' (sha over the whole stdin read, not a prefix);
  sentinel absent from every AgentEvent.payload, from all 22 runtime_host_processes columns
  (metadata is exactly {"executable_id":"codex"}), from runtime_runs and from runtime_events.data.
Failure log at DEBUG: exactly one record, "runtime host stdin delivery failed reason=... 
  executable_id=... run_id=..." -- no payload.
Counter-example recorded as D26: pydantic's own ValidationError DOES echo the payload for a str or
  oversized stdin_payload.
```

C-11 Real-binary halves re-measured (this environment has `codex-cli 0.169.0`)

```text
A-13 raw Host channel: exit_code 0, final_state exited / runtime_host_exited, wall 5.764s,
     probe_elapsed 5.78s, stderr_len 496; OUT thread.started -> item.completed(type=error) ->
     turn.started -> item.completed(agent_message,"ok") -> turn.completed(5 counters, no total_tokens).
A-14 complete adapter -> RuntimeHost -> ProcessRunner chain on a migrated throwaway DB:
     elapsed 6.40s, outcome completed, output 'ok', usage 5 counters with NO total_tokens,
     active_count 0, pending_rows_for_run [].
     Note: this run produced 6 mapped events (an extra codex.item.completed) and usage
     output_tokens 8 / reasoning_output_tokens 6, versus the 5 events and 4.68s recorded in A-14 --
     provider nondeterminism, not a behavioural difference. The event count in A-14 is therefore a
     single sample, not a stable expectation.
```

C-12 Risk probes

```text
F1 asyncio.wait_for(coro, timeout=0.0) raises TimeoutError even when the write already succeeded
   (probe11). The Runner computes max(0.0, deadline - loop.time()); reaching 0 requires the whole
   10s budget to be spent between the deadline assignment and the wait_for call, which cannot
   happen because stdin.write() is synchronous and there is no await in between. Verdict: no
   practical false positive; a genuinely expired budget still fails closed.
F2 800_000 B write+drain: peak traced allocation 1.2 MB, no event-loop blocking; a child that never
   reads fails at the deadline, not by hanging the worker. Caveat measured in D22: the 10s deadline
   is not clamped by a tighter Run/Host wall ceiling (10.03s against wall_seconds=1).
F3 No fd growth and no ResourceWarning with -W error::ResourceWarning; awaiting wait_closed() does
   NOT reproduce the asyncio ERROR noise claimed in 08 R18 ordering point 4 (probe23/probe24: 0
   records), though wait_closed() itself can raise BrokenPipeError in the EPIPE path.
```

C-13 `ProcessSpec` construction sites (answers "does the new field change any existing site?")

```text
8 direct ProcessSpec(...) instantiations + 62 helper call sites = 70 spec-producing sites in tests;
56 of them predate R18. All are keyword constructions; pydantic rejects positional construction
outright ("BaseModel.__init__() takes 1 positional argument but 6 were given"), so inserting
stdin_payload cannot shift any positional argument. extra="forbid" is untouched, strict mode still
rejects str/bytearray/memoryview payloads, and no test asserts the exact field set, round-trips a
dump, or compares two ProcessSpec instances. 155 non-PG + 143 Phase 4 + 314/385 regression tests
reproduce green, which is the behavioural proof.
```

## Appendix D — round-6 follow-up re-verification of the D21/D22 fixes (2026-11-16)

Targeted scope only; no full suite was re-run. Same out-of-tree probes as Appendix C (`/tmp/r18verify/`).

D-1 Targeted green checks

```text
uv run ruff check .
-> All checks passed!

uv run pytest tests/agent_execution/ tests/test_local_test_adapter.py -q -m "not postgres"
-> 157 passed, 4 deselected in 18.45s

uv run pytest tests/test_agent_execution_phase4_runner.py tests/test_agent_execution_phase4_supervisor.py -q -m "not postgres"
-> 98 passed in 2.06s
```

D-2 D21 — the original reproduction no longer triggers

```text
probe13.py (StubHost.raise_on_start = HostStartError("runtime_host_pipe_setup_failed"))
  BEFORE: raw exception type = ...runtime_host.HostStartError, isinstance(e, AdapterExecutionError) = False
  NOW   : raw exception type = ...contracts.errors.AdapterExecutionError, isinstance = True,
          adapter state _request = None

probe27.py (assertions on the error object)
  type: AdapterExecutionError
  category: engine_unavailable
  code: engine_unavailable | is ENGINE_UNAVAILABLE: True
  message: Engine is unavailable.
  contains internal reason (runtime_host_pipe_setup_failed): False
  contains 'pipe': False
  suppress_context: True | __cause__: None | __context__ type: HostStartError (display-suppressed)
```

D-3 D22 — the original reproduction no longer triggers

```text
probe16.py (ProcessRunner() default 10s deadline, resource_policy.wall_seconds=1,
            trusted target "stdin-never-read 60", payload 400_000 B)
  BEFORE: ProcessSpawnError(runtime_host_pipe_setup_failed) after 10.03s (wall ceiling was 1s)
  NOW   : ProcessSpawnError(runtime_host_pipe_setup_failed) after 1.01s  (wall ceiling was 1s)
          log line: "runtime host stdin delivery failed reason=timeout ..."
```

D-4 D21 must not change Host persistence (fresh `pgvector/pgvector:pg17` container
`nexusdesk-pg-r18-d21` on 127.0.0.1:55434, credentials in a mode-600 /tmp file, never printed;
container stopped and the file deleted afterwards)

```text
probe12.py (real RuntimeHost + CodexCliAdapter, target exits without reading a 450_000-byte prompt)
  runtime host stdin delivery failed reason=closed_early executable_id=codex run_id=...
  adapter.start raised: AdapterExecutionError | code: engine_unavailable | msg: Engine is unavailable.
  adapter internal state after failure: _request=None _managed_id=None _handle=None
  host active_count: 0
  durable row: {'status': 'exited', 'last_error_code': 'runtime_host_pipe_setup_failed',
                'metadata': '{"recovery": "start-failed", "executable_id": "codex"}',
                'pid': None, 'process_group_id': None}
  non-terminal rows: 0
  -> the public error is normalized, the durable reason code is still the precise Host code.
```

D-5 No regression from either fix

```text
probe.py  : no payload -> fd0 character device len=0; payload -> FIFO exact bytes;
            R1 400KB early-exit  -> pipe_setup_failed in 0.02s, group_gone=True;
            R2 400KB never-read  -> pipe_setup_failed in 0.21s, group_gone=True;
            reverse 20KB never-read -> start RETURNS in 0.01s (buffered), unchanged;
            fd before=7 after=7 across 5 failed deliveries.
probe6.py : 800_000 B with a 2s-delayed reader still delivered byte for byte
            (stdin=800000:964f4fdf3d47635c), start 2.04s, traced peak 1.2MB.
probe28.py: wall_seconds=1 + 5B prompt      -> start ok in 0.02s, exit 0 (no false timeout)
            wall_seconds=1 + 20_000B prompt -> start ok in 0.01s, exit 0
            wall_seconds=2 + 800_000B with a 1s-delayed reader -> start ok in 1.04s, exit 0
```

D-6 New tests are not vacuous

```text
test_host_start_failure_is_normalized_to_an_adapter_error
  uses the previously unused StubHost.raise_on_start, asserts AdapterExecutionError with
  code ENGINE_UNAVAILABLE, asserts the internal reason string is absent from the message,
  and asserts host.started == [] (no side effect before the failure).
test_delivery_timeout_is_capped_by_the_process_wall_budget
  keeps the 10s default, sets wall_seconds=1, asserts elapsed < 2.0 and _group_gone(pid).
  It asserts no lower bound, so it could in principle pass on an instant failure; the independent
  probe16 measurement of 1.01s is what proves the deadline is the wall budget rather than an
  immediate error. STDIN_DELIVERY_TIMEOUT_SECONDS is still 10.0 and its old assertion still passes.
Collection after the fixes: test_codex_adapter_unit 34 (was 33), test_host_stdin_delivery 17 (was 16),
test_codex_contract 8 (unchanged).
```

D-7 Documentation sync checked this round

```text
08-implementation-breakdown.md R18 line ~125: deadline is now "min(configured timeout, wall - elapsed)"
  and names D22; line ~134 records the adapter's HostStartError -> ENGINE_UNAVAILABLE translation
  and states the durable Host row retains the precise reason (D21).
03-technical-design.en.md R18 paragraph: "a deadline capped at 10 seconds and by the remaining
  process wall budget".
03-technical-design.md R18 paragraph: "最多 10 秒且受剩余进程 wall 预算约束的截止时间".
07-acceptance-report.md Blocker 1: "a deadline capped at 10 seconds and by the remaining process
  wall budget". No other "fixed 10s" wording remains in 03/06/07.
```


---

## 2026-11-18 远程执行结果补记（范围限定）

本轮远程执行（run `20261118T150343Z`，SHA `80fac60`）结果：12 lane exit 0；6,103 tests / 0 failures / 0 errors / 62 declared skips；各 lane 明细与 JUnit XML 见权威记录 `../12-scope-limited-acceptance-record-20261118-phase4-6.md` 与证据包 `20261118T150343Z.tar.gz`。本段仅追加执行结果，不修改上文历史数字。E 类环境演练为 `pending_env`，按 2026-11-18 修订不阻断阶段验收。
