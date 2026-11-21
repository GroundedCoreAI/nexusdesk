# Agent Execution Platform v2 — Remote Linux Acceptance Execution Runbook

> Status: executable draft, created 2026-11-17; revised 2026-11-18 to accept a governed shared production host for phases 0–3 non-destructive lanes; revised again 2026-11-18 to scope stage-acceptance gates to functional/switch/isolation/Secret/data/migration/terminal/side-effect criteria (performance/C11 latency, CI provenance, and historical-sample items are historical notes or out of stage scope, never blockers). Not an acceptance report and not evidence by itself.
> Target: `GroundedCoreAI/nexusdesk`, branch `integration`, exact SHA pinned at execution time.
> Authoritative inputs: `docs/requirement/agent-execution-platform-v2/phase-{3,4,5,6}-*/05-acceptance-plan*.md`,
> their `06-test-report*.md`, `07-acceptance-report*.md`, and `08-implementation-breakdown*.md`.
> Acceptance model: minimal core team (one acceptance owner, optionally one executor who may be the same person).
> High-risk capability enablement (untrusted multi-tenant execution, production Codex routing, Stage B) always
> requires a separate security/operations approval record; a phase pass never authorizes enablement.

## 中文使用说明

- 这份文档是给下一次“远程 Linux 验收会话”直接照着执行的 runbook；命令按 Phase A→H 顺序执行。
- **不要**把 `skip` / `pending_env` / `not_measured` 写成通过；不要为了变绿而删除断言或跳过门禁。
- Phase D 是现在就能跑的用例；Phase E 需要先实现产品能力或新增测试（当前代码里没有 cgroup/quota 强制执行，
  Phase 4 的三个 full-acceptance 测试只是占位符）；Phase F/G 是证据与报告流程；Phase H 是清理。
- 所有开关保持默认 `false`；阶段 0–3 的非破坏性自动化 lane 允许在**受控共享生产主机**上执行，前提是容器/端口/数据卷/证据目录全部 run-scoped，且不停机、不修改、不删除任何既有服务或数据。破坏性演练仍优先一次性主机；确需在共享机上做时必须变更审批、隔离范围、可回滚，并单独确认。
- 共享生产机不是"一次性主机"：它是现阶段真实生产场景，**可以接受为阶段 0–3 功能证据环境**；但资源争用、cgroup/内核能力、同机服务必须在证据里如实记录，不能因此把 `pending_env` 写成 pass。
- 如果目标机器是 arm64，而生产/CI 是 amd64，报告中必须写明架构差异；生产等价证据优先用 x86_64 生产/共享主机。

---

## 0. What this runbook can and cannot establish

| Lane type | Can be established on a Linux host (disposable VM or governed shared production host) | Cannot be established here |
|---|---|---|
| Existing automated suites (unit, PG, frontend, Docker drills) | Yes, with JUnit + logs + environment fingerprint | No additional stage gate; CI provenance (final PR head / CI run URL) is out of phase 0–3 scope (2026-11-18) |
| Phase 4 cgroup memory/PID/CPU hard limits | **Only after implementing enforcement** (currently probes only) | A green result by simply removing `skipif(True)` |
| Phase 4 filesystem/project quota | **Only after implementing quota enforcement** (`probe_fs_quota()` currently returns `unsupported`) | Quota claims from per-file RLIMIT or accounting |
| Phase 4 live mount-namespace experiments | Yes, via `unshare` on a real Linux kernel, after adding the drill | The current substituted-probe result presented as full support |
| Phase 6 strong-sandbox / network / two-Worker faults | Partially: Docker and multi-process drills on one host | True multi-host infrastructure faults and a dedicated adversarial host |
| Phase 6 representative production replica migration | Only with a sanitized, representative dump you provide | A synthetic small fixture presented as representative |
| Phase 3 C11 performance / latency sampling | Out of phase 0–3 stage scope (2026-11-18); no harness required for acceptance, historical note only | Not a stage gate; no production-equivalence claim needed for a phase pass |
| Phase 5 real Codex / credentials / two tenants | Yes if the CLI is installed and authenticated | Real release-like credentials and Stage B Session/Resume (not implemented) |
| Phase 0/1 acceptance-owner conclusion | Yes — closable by the kept gates plus one evidence-bound acceptance-owner record at a pinned SHA (Appendix B) | A later merge cannot retroactively ratify it; the conclusion must come from a new evidence-bound acceptance record (§0 Hard rule) |
| Independent security / SRE approval for high-risk enablement | No | Cannot be simulated by any machine or by any shared-host run; it needs a named independent approver and cannot be self-issued by the acceptance owner (§8 E11) |

**Hard rule:** a `07` conclusion is changed only by a new, evidence-bound acceptance record. This runbook
appends evidence; it never rewrites an earlier conclusion.

**Shared-host policy (revised 2026-11-18):** a shared production Linux host is accepted as the physical
environment for phases 0–3 non-destructive lanes and for the frontend/migration/execution suites, because
that is the real deployment scenario at this stage. Acceptance does **not** require a disposable host for
those lanes. It does require: run-scoped containers, ports, volumes, paths and credentials; no change to
co-tenant services; pre/post evidence that no existing service was stopped, restarted, reconfigured or
deleted; and an explicit label that the host is shared. Destructive or host-level drills (E1–E5, D9,
quota/mount/OOM/rollback) are the exception — they need an isolated disposable host, or written change
approval plus a bounded, reversible scope on the shared host. Host sharing is an environment fact; it does
not waive the kept gates (functional correctness, switch completeness, tenant isolation, Secret handling,
data integrity, migration correctness, terminal-state semantics, side effects/cleanup, no open P0/P1, and
one acceptance-owner record), nor substitute for the separate high-risk enablement approval. CI provenance,
C11 performance/latency and historical-sample items are out of phase 0–3 stage scope under the 2026-11-18
revision (historical notes only).

---

## 1. Controlled variables

Set these once per session. Do not put secrets in shell history or in the repository.

```bash
# On the Mac (control side)
export ACCEPT_HOST="${ACCEPT_HOST:-nexusdesk-accept}"   # ~/.ssh/config alias
export REPO_URL="$(git -C /Users/jackchow/Documents/CodeLib/nexusdesk remote get-url origin)"
export TARGET_BRANCH="integration"
export TARGET_SHA="$(git -C /Users/jackchow/Documents/CodeLib/nexusdesk rev-parse "origin/${TARGET_BRANCH}")"

# On the Linux host (execution side)
export ACCEPT_ROOT="/srv/nexusdesk-acceptance"
export REPO_DIR="${ACCEPT_ROOT}/repo"
export RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export EVIDENCE_ROOT="${ACCEPT_ROOT}/evidence"
export EVIDENCE_DIR="${EVIDENCE_ROOT}/${RUN_ID}"
export PG_CONTAINER="nd-accept-pg"
export PG_PORT="55432"
export PG_USER="accept"
export PG_DB="acceptance"
export PG_PASSWORD="$(openssl rand -hex 24)"
export TEST_DATABASE_URL="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${PG_DB}"
export AGENT_API_TOKEN="accept-$(openssl rand -hex 24)"
export ACCEPT_ENV_FILE="${ACCEPT_ROOT}/accept.env"     # chmod 600, never committed
export ACCEPT_COMPOSE_PROJECT="nd-accept-${RUN_ID}"     # run-scoped; isolate from co-tenant stacks
export NEXUSDESK_PORT="18080"                            # avoid 8080 if already occupied
export NEXUSDESK_MOCK_PORT="18010"                       # avoid 8010 if already occupied
```

Record the exact SHA and refuse to proceed if it is not the intended target:

```bash
mkdir -p "$EVIDENCE_DIR"
printf 'repo=%s\nbranch=%s\nsha=%s\ncollected_at=%s\n' \
  "$REPO_URL" "$TARGET_BRANCH" "$TARGET_SHA" "$(date -u +%FT%TZ)" \
  | tee "$EVIDENCE_DIR/00-pin.txt"
```

On the Linux host, before running any lane:

```bash
git -C "$REPO_DIR" rev-parse HEAD
test "$(git -C "$REPO_DIR" rev-parse HEAD)" = "$TARGET_SHA" || { echo "SHA mismatch"; exit 1; }
test -z "$(git -C "$REPO_DIR" status --porcelain)" || { echo "dirty tree"; exit 1; }
```

If a reviewed fix is required for an E-lane, commit it on a branch first; do not run acceptance
evidence on an uncommitted tree with no SHA.

---

## 2. Guardrails

1. **Shared host accepted, with a hard isolation boundary.** A disposable VM is still preferred for
   destructive drills, but phases 0–3 non-destructive lanes may run on a shared production host. Do not use
   its production database, real customer data, real API keys, or shared volumes; run-scoped containers,
   ports, paths and synthetic credentials only. Record the co-tenant services before and after.
2. **Synthetic credentials only.** Generate them on the host; keep them in a mode-0600 file outside the repo
   (`$ACCEPT_ENV_FILE`); never commit or paste them into chat.
3. **Default-off.** Do not flip `AGENT_EXECUTION_*` or `CODEX_*` switches for general testing. Controlled
   off/on drills are allowed only in Phase D9 on an isolated run-scoped stack; on a shared host they also
   require written change approval and non-conflicting ports, and must be recorded as controlled trials.
4. **Destructive drills behind an explicit confirmation.** `CONFIRM_DESTRUCTIVE=1` is required for Phase E
   operations (cgroup experiments, quota fill, SIGKILL, network loss, disk full, rollback). On a shared host
   these drills need an additional written change approval, a bounded run-scoped target and a rollback path;
   never touch co-tenant processes, data or volumes.
5. **No gate laundering.** Do not convert `skip` to pass, do not delete assertions, do not present an
   approximation as a hard limit. See Appendix C.
6. **Append-only reports.** Add dated appendices to the existing `06/07`; do not edit historical numbers.
7. **Artifacts survive the session.** Keep evidence outside `/tmp`; package it before the SSH session ends
   or the disposable VM is destroyed. On a shared host, never delete co-tenant artifacts to "clean up".
8. **Architecture honesty.** x86_64 is production/CI-equivalent; arm64 results must be labelled.
9. **High-risk enablement stays separate.** A phase acceptance record does not approve untrusted execution,
   production Codex routing, or Stage B.

---

## 3. Host requirements and access

| Item | Minimum | Preferred | Why |
|---|---|---|---|
| OS | Ubuntu 22.04/24.04 or Debian 12 | Ubuntu 24.04 | systemd, cgroup v2, package availability |
| Arch | x86_64 or arm64 | **x86_64** | Matches CI and most production images |
| CPU / RAM | 4 vCPU / 8 GB | **8 vCPU / 16 GB** | Docker drills, PG, parallel suites |
| Disk | 60 GB free | **100–150 GB** | Images, builds, loopback quota image, evidence |
| Privileges | passwordless sudo | root or passwordless sudo | cgroup, mount, quota, Docker, Playwright deps |
| Kernel | cgroup v2 unified (`cgroup2fs`) | same | Phase 4 E1/E3 |
| Filesystem | ext4/xfs root | plus one spare disk or loop support | Phase 4 E2 |
| Network | apt/pip/npm/Docker/GitHub reachable | mirrors available | provisioning |
| Lifecycle | disposable VM preferred for destructive drills; shared production host accepted for non-destructive lanes | fresh VM per round for destructive drills | destructive drills need isolation and a rollback path |

Access options, in order of preference:

1. **SSH alias** (recommended). On the Mac add to `~/.ssh/config`:

   ```sshconfig
   Host nexusdesk-accept
     HostName <public-ip-or-dns>
     User <user>
     IdentityFile ~/.ssh/<ephemeral-key>
     IdentitiesOnly yes
     ServerAliveInterval 30
   ```

   Then verify: `ssh "$ACCEPT_HOST" 'hostname; uname -m; sudo -n true && echo sudo=ok'`.

2. **Generated bootstrap script**, executed by you with `! bash ...` and output pasted back.
3. **Manual command-by-command**, slowest but shares no credentials.

Never ask for or accept a pasted private key or password in chat.

---

## 4. Phase A — Preflight (read-only, no changes)

Run from the Mac:

```bash
ssh "$ACCEPT_HOST" 'bash -s' <<'PREFLIGHT' | tee "/tmp/nd-preflight-$(date -u +%Y%m%dT%H%M%SZ).log"
set -euo pipefail
echo "== identity =="
hostname; uname -a; uname -m; cat /etc/os-release | head -5; nproc; free -h; df -h /
echo "== cgroup =="
stat -fc %T /sys/fs/cgroup || true
cat /sys/fs/cgroup/cgroup.controllers 2>&1 || true
cat /sys/fs/cgroup/cgroup.subtree_control 2>&1 || true
mount | grep -E 'cgroup|sysfs' || true
echo "== namespaces =="
unshare -m true && echo mountns=ok || echo mountns=FAIL
echo "== docker =="
docker info --format '{{.OperatingSystem}} | {{.Architecture}} | cgroup={{.CgroupVersion}} | driver={{.Driver}}' 2>&1 || echo docker=unavailable
docker compose version 2>&1 || true
echo "== tools =="
for c in python3 uv node npm git make gcc jq rsync openssl mkfs.ext4 xfs_quota quotaon setquota losetup; do
  printf '%-12s %s\n' "$c" "$(command -v "$c" || echo MISSING)"
done
echo "== loop devices =="
ls -l /dev/loop-control /dev/loop0 2>&1 || true
echo "== privileges =="
sudo -n true && echo sudo=passwordless || echo sudo=needs-password
echo "== network =="
curl -fsSI --max-time 10 https://pypi.org | head -1 || echo pypi=unreachable
curl -fsSI --max-time 10 https://registry-1.docker.io/v2/ | head -1 || echo dockerhub=unreachable
echo "== clock =="
date -u; timedatectl 2>/dev/null | head -4 || true
PREFLIGHT
```

Decision matrix:

| Observation | Consequence |
|---|---|
| `cgroup2fs` + `memory,pids,cpu` in controllers | E1/E3 are feasible **after** implementation |
| `mountns=ok` | E4 live mount experiments are feasible |
| `losetup` + `mkfs.ext4` present, sudo ok | E2 loopback quota is feasible |
| `docker` + compose v2 present | Phase 6 Docker drills and stack drills are feasible |
| passwordless sudo absent | E1–E4 and production-image drills are blocked; record `pending_env` |
| `x86_64` | Production/CI-equivalent lane |
| `arm64` | Record the difference; use a cloud x86_64 VM before claiming production equivalence |
| pypi/DockerHub unreachable | Provisioning blocked; configure mirrors or pre-baked images |

Save the preflight output into `$EVIDENCE_DIR` once the directory exists (Phase B).

---

## 5. Phase B — Provisioning

Run on the Linux host. On a shared production host, do **not** install system packages, change Docker
daemon state, or add users globally unless the host owner has explicitly approved it. Use preinstalled or
user-local tools (`uv`, Node under `$HOME/.local`), record every substitution in `01-environment.txt`, and
keep all writes under `$ACCEPT_ROOT`. The block below is the disposable-VM path.

```bash
sudo apt-get update
sudo apt-get install -y \
  ca-certificates curl git build-essential jq unzip rsync \
  docker.io docker-compose-v2 python3.12 python3.12-venv python3-pip \
  postgresql-client e2fsprogs xfsprogs quota openssl
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
# Reconnect SSH (or run `newgrp docker`) before using docker without sudo.

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Node 22 (only needed for frontend gates / Playwright / Codex CLI if installed via npm)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

# Repository at the pinned SHA
sudo mkdir -p "$ACCEPT_ROOT" "$EVIDENCE_ROOT"
sudo chown "$USER":"$USER" "$ACCEPT_ROOT"
git clone "$REPO_URL" "$REPO_DIR"
git -C "$REPO_DIR" fetch origin
git -C "$REPO_DIR" checkout --detach "$TARGET_SHA"
git -C "$REPO_DIR" rev-parse HEAD | tee "$EVIDENCE_DIR/00-target-sha.txt"

# Python dependencies
cd "$REPO_DIR/backend"
uv sync
uv run ruff check src tests
uv run python ../scripts/check_architecture.py
```

Create the runtime/test env file (synthetic only):

```bash
umask 077
cat > "$ACCEPT_ENV_FILE" <<ENV
AGENT_DATABASE_URL=${TEST_DATABASE_URL}
AGENT_API_TOKEN=${AGENT_API_TOKEN}
AGENT_TENANT_ID=local
AGENT_ENVIRONMENT=production
AGENT_REQUIRE_PASSWORD_CHANGE=false
AGENT_MODEL_BACKEND=demo
AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false
AGENT_EXECUTION_PHASE3_ENABLED=false
AGENT_EXECUTION_RUNTIME_HOST_ENABLED=false
AGENT_EXECUTION_UNTRUSTED_TENANTS_ENABLED=false
AGENT_EXECUTION_SANDBOX_REQUIRED=true
AGENT_EXECUTION_NETWORK_DEFAULT_DENY=true
AGENT_EXECUTION_OUTBOX_ENABLED=false
AGENT_EXECUTION_EVENT_CLEANUP_ENABLED=false
CODEX_CLI_ENABLED=false
CODEX_APP_SERVER_ENABLED=false
ENV
chmod 600 "$ACCEPT_ENV_FILE"
```

PostgreSQL (disposable container):

```bash
docker run -d --name "$PG_CONTAINER" \
  -e POSTGRES_USER="$PG_USER" -e POSTGRES_PASSWORD="$PG_PASSWORD" -e POSTGRES_DB="$PG_DB" \
  -p "127.0.0.1:${PG_PORT}:5432" pgvector/pgvector:pg17
until docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; do sleep 1; done
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -c 'SELECT version();'
```

Migrations:

```bash
cd "$REPO_DIR/backend"
set -a; . "$ACCEPT_ENV_FILE"; set +a
export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
uv run alembic upgrade head | tee "$EVIDENCE_DIR/01-alembic-upgrade.log"
uv run alembic heads | tee "$EVIDENCE_DIR/01-alembic-heads.log"
uv run alembic current | tee "$EVIDENCE_DIR/01-alembic-current.log"
```

Gate: exactly one head. If the head is not the expected single revision, stop and record the anomaly.

---

## 6. Phase C — Baseline stack and default-off proof

Controlled trial only; not an enablement. On a shared host, run this as a run-scoped project
(`-p "$ACCEPT_COMPOSE_PROJECT"` with the variables from §1); never bring up or down a pre-existing
`nexusdesk-quickstart` stack. If no isolated ports are available, keep this phase `pending_env`.

```bash
cd "$REPO_DIR"
set -a; . "$ACCEPT_ENV_FILE"; set +a
sh nexusdesk quickstart
```

Record:

```bash
docker compose -p "$ACCEPT_COMPOSE_PROJECT" -f deploy/quickstart/compose.yaml ps | tee "$EVIDENCE_DIR/02-stack-ps.log"
docker compose -p "$ACCEPT_COMPOSE_PROJECT" -f deploy/quickstart/compose.yaml exec -T app env \
  | grep -E 'AGENT_EXECUTION_|CODEX_' | sort | tee "$EVIDENCE_DIR/02-flags.log"
curl -ksS -o /dev/null -w '%{http_code}\n' "https://127.0.0.1:${NEXUSDESK_PORT}/" | tee "$EVIDENCE_DIR/02-root-status.txt"
docker exec "${ACCEPT_COMPOSE_PROJECT}-app-1" ls -la /data /data/execution 2>&1 \
  | tee "$EVIDENCE_DIR/02-data-layout.log"
```

Expected default-off facts (record actual output):

- `AGENT_EXECUTION_RUNTIME_HOST_ID` is unset/empty.
- `AGENT_EXECUTION_RUNTIME_HOST_ENABLED=false`.
- `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false`, `AGENT_EXECUTION_PHASE3_ENABLED=false`.
- `AGENT_EXECUTION_UNTRUSTED_TENANTS_ENABLED=false`.
- `/data/execution` is absent (declared, never created).
- Root returns 200 over HTTPS; app is healthy, restart count 0.

If any default is not false, stop: that is a fail-closed regression, not an acceptance result.

---

## 7. Phase D — Existing executable lanes (no product code changes)

Run everything with JUnit and `-rA`; keep command, log, and exit code together.

Common preamble:

```bash
cd "$REPO_DIR/backend"
set -a; . "$ACCEPT_ENV_FILE"; set +a
export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
mkdir -p "$EVIDENCE_DIR/03-logs" "$EVIDENCE_DIR/04-junit"
run_lane() {
  name="$1"; shift
  echo "$*" > "$EVIDENCE_DIR/03-logs/${name}.command"
  set +e
  "$@" 2>&1 | tee "$EVIDENCE_DIR/03-logs/${name}.log"
  code=${PIPESTATUS[0]}
  set -e
  echo "$code" > "$EVIDENCE_DIR/03-logs/${name}.exit"
  echo "${name} exit=${code}"
}
```

### D1 — Backend non-PG suite

```bash
run_lane d1-non-pg uv run pytest -q -m "not postgres" \
  -rA --durations=0 \
  --junitxml="$EVIDENCE_DIR/04-junit/d1-non-pg.xml"
```

Reported baselines (verify at your pinned SHA; never copy them across SHAs): Phase 6 re-verification
reported 2323 passed / 6 skipped; the execution-platform subset alone reported 1541 passed / 6 skipped /
203 deselected. Record actual; never adjust the test count to match a report.

### D2 — Backend PostgreSQL suite

```bash
run_lane d2-postgres uv run pytest -q -m postgres -rs \
  -rA --durations=0 \
  --junitxml="$EVIDENCE_DIR/04-junit/d2-postgres.xml"
```

The role must have `CREATEDB` (the official Postgres image user is superuser). Reported baselines
(verify at your pinned SHA): Phase 6 post-renumber re-verification reported 418 passed / 1 skipped;
Phase 3 reported 500 passed / 28 skipped. Record actual, list every skip reason.

### D3 — Execution-platform focused (fast re-check)

```bash
run_lane d3-execution-focused uv run pytest -q \
  tests/test_execution_*.py tests/test_agent_execution_*.py \
  tests/test_agent_config_execution_compat.py tests/agent_execution \
  -m "not postgres" -rA --durations=0 \
  --junitxml="$EVIDENCE_DIR/04-junit/d3-execution-focused.xml"
```

### D4 — Frontend gates

```bash
cd "$REPO_DIR/frontend"
npm ci
run_lane d4-typecheck npm run typecheck
run_lane d4-i18n npm run check:i18n
run_lane d4-build npm run build

# Phase 3 config/preview UI contract (route-mocked; needs the dev server on 5173)
npm run dev -- --port 5173 > "$EVIDENCE_DIR/03-logs/d4-vite.log" 2>&1 &
VITE_PID=$!
npx playwright install --with-deps chromium
run_lane d4-playwright-phase3 npx playwright test tests/agent-execution-config.spec.ts --reporter=line
kill "$VITE_PID" || true
```

Full Playwright e2e requires the running stack and a seeded database; if it is not in this round's scope,
record that boundary instead of running a partial set and calling it full.

### D5 — Phase 6 Docker / event / reliability lanes

```bash
cd "$REPO_DIR/backend"
run_lane d5-phase6-docker uv run pytest -q \
  tests/test_execution_sandbox.py \
  tests/test_execution_r18_allowlist_proxy.py \
  tests/test_execution_t12_real_drills.py \
  -rA --durations=0 \
  --junitxml="$EVIDENCE_DIR/04-junit/d5-phase6-docker.xml"

run_lane d5-phase6-core uv run pytest -q \
  tests/test_execution_credentials.py \
  tests/test_execution_credentials_migration.py \
  tests/test_execution_events.py \
  tests/test_execution_fencing.py \
  tests/test_execution_outbox.py \
  tests/test_execution_usage.py \
  tests/test_execution_sse.py \
  tests/test_execution_diagnostics.py \
  tests/test_execution_recovery.py \
  tests/test_execution_t12_matrix.py \
  tests/test_execution_t12_additional.py \
  tests/test_execution_t12_worker_usage.py \
  tests/test_execution_t12_resume_grant.py \
  tests/test_execution_r19_boundary_reaper.py \
  tests/test_execution_r19_replay_terminal.py \
  tests/test_execution_r18_launch_redaction.py \
  tests/test_execution_r18_emission_redaction.py \
  tests/test_execution_r18_wiring.py \
  tests/test_execution_r18_native_usage.py \
  tests/test_execution_r18_raw_sample_leak.py \
  -rA --durations=0 \
  --junitxml="$EVIDENCE_DIR/04-junit/d5-phase6-core.xml"
```

After the drills, assert no residue:

```bash
docker ps -a --format '{{.Names}} {{.Status}}' | grep -E 'nexus-egress|nd-accept' || true
docker network ls | grep nexus-egress || true
```

### D6 — Phase 5 Codex real-binary lane

The test hardcodes `/usr/local/bin/codex` and skips when absent.

```bash
# Install the same CLI line that was measured (0.169.0) using the vendor's documented installer/npm package.
# Example if using npm:
sudo npm install -g @openai/codex
sudo ln -sf "$(command -v codex)" /usr/local/bin/codex
codex --version | tee "$EVIDENCE_DIR/03-logs/d6-codex-version.log"
```

Authentication is a real prerequisite. If the CLI is not authenticated, do **not** fake the result:

```bash
# interactive on the host, performed by you if credentials are authorized
codex login status || true
```

Then:

```bash
cd "$REPO_DIR/backend"
run_lane d6-codex-unit uv run pytest -q tests/agent_execution \
  -rA --durations=0 --junitxml="$EVIDENCE_DIR/04-junit/d6-codex-unit.xml"

run_lane d6-codex-real uv run pytest -q \
  tests/agent_execution/test_host_stdin_delivery.py::test_real_codex_consumes_the_prompt_through_the_host \
  -rA --durations=0 --junitxml="$EVIDENCE_DIR/04-junit/d6-codex-real.xml"
```

If `codex` is absent or unauthenticated, the real lane is `pending_env`; the deterministic suite still runs.

### D7 — Phase 4 process/PG lanes

```bash
cd "$REPO_DIR/backend"
run_lane d7-phase4 uv run pytest -q tests/test_agent_execution_phase4_*.py \
  -rA --durations=0 --junitxml="$EVIDENCE_DIR/04-junit/d7-phase4.xml"
```

Reference: Phase 4 reported 341 passed / 3 skipped. The 3 skips are the placeholder full-acceptance
tests; they are **not** coverage (Appendix C).

### D8 — Migration lanes

```bash
cd "$REPO_DIR/backend"
run_lane d8-migrations uv run pytest -q \
  tests/test_execution_migration.py \
  tests/test_execution_credentials_migration.py \
  tests/test_agent_execution_phase3_migration.py \
  tests/test_agent_execution_phase4_migration.py \
  -rA --durations=0 --junitxml="$EVIDENCE_DIR/04-junit/d8-migrations.xml"
```

Record `alembic heads`, `current`, and the disposable databases created/destroyed.

### D9 — Controlled stack off/on/rollback drill (optional, isolated stack required)

Only if this round's scope includes Phase 2/3/4 rollout evidence. Run with `CONFIRM_DESTRUCTIVE=1`.
On a shared production host this drill is allowed only with written change approval, a project name and
ports isolated from co-tenant stacks, and a pre/post no-touch check. If the existing quickstart already owns
8080/8010, keep the drill `pending_env`; never stop or recreate that stack. If the Compose file's top-level
`name:` prevents `-p` from taking effect on your Compose version, copy the compose file under
`$ACCEPT_ROOT` and set a run-scoped `name:` there before starting.

```bash
# Off (default): run a demo conversation; assert completed and no orchestrator path line.
#
# On: quickstart's compose comments out AGENT_EXECUTION_RUNTIME_HOST_ID, so a host
# environment variable alone will NOT reach the app. Use a disposable override file:
cat > deploy/quickstart/compose.accept.override.yaml <<'YAML'
services:
  app:
    environment:
      AGENT_EXECUTION_ORCHESTRATOR_ENABLED: "true"
      AGENT_EXECUTION_PHASE3_ENABLED: "true"
      AGENT_EXECUTION_RUNTIME_HOST_ID: "accept-host"
      AGENT_EXECUTION_RUNTIME_HOST_ENABLED: "true"
YAML
docker compose -p "$ACCEPT_COMPOSE_PROJECT" -f deploy/quickstart/compose.yaml \
  -f deploy/quickstart/compose.accept.override.yaml up -d --build --wait --wait-timeout 300
# After the on run: remove the override, run `down` WITHOUT `-v` if you need to keep data,
# force-recreate the off stack, and verify a new run completes on the legacy path.
rm -f deploy/quickstart/compose.accept.override.yaml
```

Capture run IDs, status/output/error, event sequence/timestamps, container logs, and `/data/execution`
before/after. This is a controlled trial; it is **not** production enablement.

**Substitute when no pinned-SHA image is buildable (2026-11-18):** on a shared production host where
DockerHub is unreachable, `node:22-alpine` is not cached, and the only cached quickstart image was built
from an older commit, do **not** use that stale image as target-SHA evidence. Record the live Compose drill
as `pending_env` and prove the gate at the pinned SHA with a dedicated automated switch-completeness lane
(`tests/test_runtime_baseline.py`, `test_agent_execution_phase3_*flags/config/settings/wiring*`,
`test_agent_execution_phase4_*settings/deployment/orchestration/runtime_host*`,
`test_execution_orchestrator.py`, `test_execution_phase6_settings.py`, `test_execution_composition.py`,
`test_agent_execution_registries.py`, `test_agent_config_execution_compat.py`), plus a read-only
`docker inspect` default-off flag check on the running production stack. Record the image digest, its
source commit and the commit distance to the pinned SHA in `01-environment.txt`; deployment lag is an
environment fact, not a code defect and not a stage gate under the 2026-11-18 scope revision.

---

## 8. Phase E — Environment gates that require implementation and new tests

These lanes cannot be closed by running or unskipping existing tests. Complete the implementation,
add reviewed tests, then run them. Until then, keep the corresponding promises `pending_env`.

### E1 — Per-Execution cgroup v2 memory/PID/CPU hard limits (Phase 4 #133)

Current state (verified in code):

- `probe_cgroup_v2_memory/pids/cpu()` only read `cgroup.controllers`; they do not enforce anything.
- `LocalSandboxProvider.LOCAL_IMPLEMENTED` excludes `CAP_MEMORY_GROUP`, `CAP_PID_GROUP`, `CAP_CPU_GROUP`.
- `test_cgroup_memory_hard_limit_full_acceptance`, `test_cgroup_pids_hard_limit_full_acceptance`,
  `test_fs_quota_total_enforcement_full_acceptance` are `@pytest.mark.skipif(True)` bodies that
  `raise AssertionError(...)`; they are placeholders, not tests.

Required implementation: a Linux provider (or an explicit Local extension) that creates a per-Execution
cgroup, enables `+memory +pids +cpu` in the parent, applies limits, places the child in it, observes
events, and removes the cgroup on release — fail-closed when controllers are unavailable.

Acceptance test specification (replace the placeholders, do not merely unskip):

1. Create a disposable cgroup under a delegated root; assert writable; clean up in `finally`.
2. `memory.max=64MiB`; run a child allocating 256MiB; assert non-zero termination with the stable
   resource-exceeded reason, host remains responsive, and the cgroup is removed.
3. `pids.max=8`; attempt to spawn 32 children; assert bounded failures/termination, no host-wide impact.
4. `cpu.max="50000 100000"` (0.5 CPU); run a busy child for 2s; assert CPU time is bounded and the
   reservation reports the hard ceiling (not an rlimit approximation).
5. Every case asserts the recorded mechanism is `hard` (not `approximate`) and no silent ignore.

Run once implemented:

```bash
CONFIRM_DESTRUCTIVE=1 run_lane e1-cgroup uv run pytest -q \
  tests/test_agent_execution_phase4_sandbox.py -k 'cgroup or quota' \
  -rA --durations=0 --junitxml="$EVIDENCE_DIR/04-junit/e1-cgroup.xml"
```

### E2 — Filesystem/project quota total enforcement

`probe_fs_quota()` currently returns `unsupported`. Implement provider-level project quota on a dedicated
filesystem, then test:

```bash
CONFIRM_DESTRUCTIVE=1
sudo dd if=/dev/zero of="${ACCEPT_ROOT}/quota.img" bs=1M count=4096
sudo mkfs.ext4 -O project,quota "${ACCEPT_ROOT}/quota.img"
sudo mkdir -p "${ACCEPT_ROOT}/quota"
sudo mount -o loop,prjquota "${ACCEPT_ROOT}/quota.img" "${ACCEPT_ROOT}/quota"
sudo quotacheck -cum "${ACCEPT_ROOT}/quota" 2>/dev/null || true
```

Test: assign a project id to a workdir, set a 64MiB quota, write 128MiB; assert `EDQUOT`/`ENOSPC`,
no host-wide impact, the observation is persisted with a structured alert, and cleanup is idempotent.

### E3 — Live mount-namespace experiments (Phase 4 P4-UT-13 / P4-IT-17 mount halves)

There is no `unshare`/`CLONE_NEWNS` in the execution provider today. Implement a provider-level mount
namespace (or a controlled drill that uses one), then assert:

- A bind mount to an external sentinel is not reachable from the execution namespace.
- A mount-point replacement race is denied and the sentinel is byte-identical.
- Cleanup does not recurse outside the workdir.

Run with `unshare -m` on an isolated Linux host (disposable VM preferred; on a shared host only with
written change approval) and record `findmnt`/inode evidence. Until then, only the substituted-probe denial
is measured; do not claim full mount support.

### E4 — Deterministic OS PID-reuse corroboration (Phase 4 P4-IT-10 OS half)

The decision-table tests exist (`test_decision_table_pid_reuse_gets_zero_signals`,
`test_pid_reuse_substitute_forbids_signals`), but the real-OS experiment is absent. Implement a bounded
drill on an isolated Linux host: spawn a managed child, capture host/boot/start-token/digest, kill it, force PID
reuse (or simulate the identity table), and assert **zero signals** on any identity mismatch.
Record the kernel method and why it is deterministic; otherwise keep `pending_env`.

### E5 — Production-image restart / stop-timeout / rollback (Phase 4 P4-IT-09/28/29 production faces)

Use the production compose shape on an isolated host, with the Host **off** by default and then a
controlled trial. Create a disposable `deploy/production/.env` from the example with **synthetic**
credentials only; never copy a real production env file to the host. Keep this file mode 0600 and outside
version control.

- Build the production image; `docker compose up -d --wait`.
- Record `docker inspect` health/restart count, `alembic current`, tables.
- `docker compose restart app`; assert recovery and idempotent seed.
- Stop with the configured grace; assert managed processes are gone, no orphans, no data loss.
- Roll back to the previous image; assert no downgrade needed and records retained.

If the Host is enabled for the trial, stop admission and drain to zero active before rollback; never
delete `cleanup_failed` rows.

### E6 — Phase 6 real two-Worker SIGKILL / heartbeat / late-result / mixed faults

Existing coverage is PG-level (`test_lost_worker_is_failed_and_cannot_publish_late_result`,
`test_execution_r19_boundary_reaper.py`, `test_execution_t12_matrix.py`). Add a multi-process drill:

- Start two worker processes/containers against the same DB with distinct worker identities.
- Worker A claims a Run; SIGKILL A mid-Run; assert B/reaper marks it failed after lease expiry,
  no late success overwrites the terminal, and resources/grants are released once.
- Repeat with a heartbeat stall, network loss (`docker network disconnect`), disk full (loop-backed
  workdir), and a hung child (`SIGSTOP`).
- Assert one effective terminal, no orphan process/FD/mount/volume, and Secret-free logs.

This is new test code. Do not present the PG-only tests as the two-Worker drill.

### E7 — Phase 6 representative populated-replica migration

Requires a sanitized, representative dump from you. Without it, record `pending_env`.

Procedure: restore the dump to a disposable DB; run `alembic upgrade head` with timing; sample
`pg_locks` and long-running transactions; assert the backfill preserves historical IDs/order; run a
protected downgrade on a copy; assert no data loss. Record the data scale and anonymization method.

### E8 — Phase 3 C11 performance (issue #129) — OUT OF PHASE 0–3 STAGE SCOPE

> **2026-11-18 scope revision:** C11 latency, p50/p95, matched pairs, sample counts, ≤5%/≤50 ms, and
> multi-sample requirements are **not stage-acceptance gates** for phases 0–3. No measurement harness is
> required to accept a phase, and a missing or `not_measured` C11 result never blocks a phase pass. This
> lane is retained as a historical note / possible separate follow-up only.

Historical harness description (kept for traceability; explicitly out of stage scope):
No `test_agent_execution_phase3_performance.py` exists. Add a harness that:

- Warms resolver/admission caches, then discards warm-up samples.
- Runs at least 100 valid interleaved paired samples (alternating old/new) in the same environment/load.
- Retains raw JSON; reports nearest-rank paired-delta p95; target ≤50 ms; excludes external models.
- Freezes the six R-18 settings and the SHA before sampling.

If such a harness is run for context only, record the environment and load and keep any production claim
separate; it must not affect a phase acceptance conclusion.

### E9 — Phase 5 Stage A 20-scenario / three-run batch (P5-IT-18)

No batch harness exists. Add one that runs at least 20 mixed scenarios (success, malformed output,
timeout, cancel, crash, usage, version denial, tenant denial, prompt-delivery failure, etc.) three
consecutive times with no P0/P1 and stable outcomes. Keep all raw logs. This is required before Stage A
full acceptance and before any Stage B discussion.

### E10 — Phase 5 credentials / two-tenant / cross-tenant mounts

Implement or execute the controlled drills: managed Secret canary through the Host, inspect child
argv/env/stdout/stderr/logs/DB for plaintext, revoke and assert admission closes, and prove two tenants
cannot read/write each other's workspace or mounts. Host-auth inspection is mandatory. Without
authorized credentials/tenants, keep `pending_env`.

### E11 — Phase 6 independent security / SRE approval

This is a separate approval record bound to the target SHA, tenant scope, batch plan, evidence, and
revocation conditions. A VM cannot produce it, and a phase acceptance owner cannot self-issue it.

---

## 9. Phase F — Evidence packaging

Required layout:

```text
$EVIDENCE_DIR/
  00-pin.txt                      # repo, branch, SHA, UTC
  00-target-sha.txt
  01-environment.txt              # uname, os-release, cgroup, docker, python, node
  01-alembic-*.log
  02-stack-*.log
  03-logs/<lane>.command|.log|.exit
  04-junit/*.xml
  05-coverage/*                   # optional, if coverage is enabled
  06-stack/*.json                 # docker inspect, ps, flags, migration state
  manifest.json
  sha256sums.txt
  summary.md
```

Create the fingerprint and manifest:

```bash
{
  uname -a; uname -m; cat /etc/os-release; nproc; free -h; df -h /
  stat -fc %T /sys/fs/cgroup; cat /sys/fs/cgroup/cgroup.controllers
  docker version; docker compose version
  python3 --version; uv --version; node --version; npm --version
} > "$EVIDENCE_DIR/01-environment.txt" 2>&1

python3 - <<'PY'
import json, os, pathlib, subprocess, datetime
d = pathlib.Path(os.environ["EVIDENCE_DIR"])
manifest = {
  "run_id": os.environ["RUN_ID"],
  "sha": os.environ["TARGET_SHA"],
  "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "arch": subprocess.check_output(["uname", "-m"], text=True).strip(),
  "lanes": sorted(p.stem for p in (d / "04-junit").glob("*.xml")),
}
(d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY

( cd "$EVIDENCE_DIR" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt )
tar -C "$EVIDENCE_ROOT" -czf "${EVIDENCE_ROOT}/${RUN_ID}.tar.gz" "$RUN_ID"
```

Optional repository hand-off: copy the non-sensitive summary, commands, and JUnit XML under
`docs/requirement/agent-execution-platform-v2/evidence/<run-id>/` and open a PR. Ask before adding
any log that might contain environment details; never commit `.env`, credentials, or raw customer data.

---

## 10. Phase G — Append-only report updates

Update only by appending a dated appendix to the existing reports:

- Phase 3: `phase-3-.../06-test-report*.md`, `07-acceptance-report*.md` (#127–#130; C11 performance out of stage scope since 2026-11-18).
- Phase 4: `phase-4-.../06-test-report.en.md`, `07-acceptance-report.en.md` (#133–#136).
- Phase 5: `phase-5-.../06-test-report.md`, `07-acceptance-report.md` (Stage A lanes).
- Phase 6: `phase-6-.../06-test-report.md`, `07-acceptance-report.md` (L1–L8).

Appendix template:

```markdown
## Remote Linux acceptance appendix — <UTC timestamp> — <SHA>

> This appendix adds executed evidence only. It does not rewrite earlier conclusions.

Environment: <OS/kernel/arch/cgroup/docker/PG versions; host id; shared or isolated>

| Item | Command / drill | Result | Verdict | Evidence |
|---|---|---|---|---|
| P4-IT-19 memory half | ... | ... | pass / pending_env / not_measured | <relative path or CI URL> |

Residuals: <L-n items, owner, deadline>
```

Verdict rules:

- `pass` only with executed evidence at the recorded SHA and environment.
- `pending_env` when the required environment/data/authorization is absent.
- `not_measured` when no valid measurement exists; never infer from a local observation.
- Any failure reopens the affected A/C row; do not leave an older pass standing.
- CI results, when present, are supporting/historical evidence only (2026-11-18); they do not gate phase acceptance or override an evidence-bound acceptance record. CI provenance / final-PR-head double-run is not required.

Issue handling (only with your approval): update #133/#134/#136; create issues for Phase 6 L1–L8 and
Phase 5 D9/D10/D23–D27 if they are still untracked. Keep the target SHA and evidence link in each issue.

---

## 11. Phase H — Cleanup

On a disposable host, the block below is safe as written. On a shared production host, delete **only**
resources created by this run and verified by name (containers, networks, cgroups, loop mounts, env file);
do not run a bare `docker compose down -v` against a pre-existing stack, and stop and ask before deleting
anything ambiguous.

```bash
cd "$REPO_DIR"
# Only if a run-scoped acceptance stack was created in D9, and only that project.
docker compose -p "$ACCEPT_COMPOSE_PROJECT" -f deploy/quickstart/compose.yaml down -v || true
docker rm -f "$PG_CONTAINER" || true
# Egress networks: remove only run-scoped names; on a shared host, stop and ask for anything else.
docker network ls --format '{{.Name}}' \
  | grep -E "^(${ACCEPT_COMPOSE_PROJECT}|${RUN_ID}).*nexus-egress|nexus-egress.*(${ACCEPT_COMPOSE_PROJECT}|${RUN_ID})" \
  | xargs -r docker network rm

# cgroups created by drills (names are run-scoped)
sudo find /sys/fs/cgroup -maxdepth 2 -type d -name 'nd-accept-*' -print -exec rmdir {} \; 2>/dev/null || true

# quota drill — detach only this run's loop device; never detach all loop devices on a shared host.
sudo umount "${ACCEPT_ROOT}/quota" 2>/dev/null || true
LOOP_DEV="$(findmnt -n -o SOURCE --target "${ACCEPT_ROOT}/quota" 2>/dev/null || true)"
case "$LOOP_DEV" in /dev/loop*) sudo losetup -d "$LOOP_DEV" 2>/dev/null || true ;; esac
rm -f "${ACCEPT_ROOT}/quota.img"

shred -u "$ACCEPT_ENV_FILE" 2>/dev/null || true
```

Verify no residue: no run-scoped quickstart project (`$ACCEPT_COMPOSE_PROJECT`), no `$PG_CONTAINER`, no
matching run-scoped egress networks, no loop mount under `$ACCEPT_ROOT`, and no `nd-accept-*` cgroups.
Co-tenant services must still be running with their original configuration. Confirm the evidence tarball
exists and has a checksum before the session ends or the disposable VM is destroyed.

---

## 12. Troubleshooting

| Symptom | Cause / action |
|---|---|
| `/sys/fs/cgroup` read-only in a container | Run on the isolated Linux host (disposable VM preferred; shared host needs written approval), or use `--privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw` only for a probe; Docker Desktop LinuxKit is not the acceptance target for #133 |
| `docker: permission denied` | `sudo usermod -aG docker $USER`, reconnect SSH or `newgrp docker` |
| `TEST_DATABASE_URL` tests skip | Set the URL; ensure the role has `CREATEDB`; do not count skips as passes |
| Alembic multiple heads | Stop; record the revision files and do not stamp/upgrade blindly; resolve per the repo migration procedure |
| `alembic` needs a token | Export `AGENT_API_TOKEN` from `$ACCEPT_ENV_FILE`; never write it into the repo |
| apt/pip/DockerHub unreachable | Configure mirrors or pre-bake images; record the substitution |
| Playwright missing browser deps | `npx playwright install --with-deps chromium` (needs sudo) |
| Codex binary skips | Install the pinned CLI at `/usr/local/bin/codex` and authenticate; otherwise record `pending_env` |
| Quota mount fails | Kernel/filesystem lacks project quota; use a dedicated ext4/xfs disk; record the failure, do not substitute accounting |
| OOM kills the host | Cap memory with `systemd-run --scope -p MemoryMax=...` or a container; keep destructive drills scoped; on a shared production host stop immediately and notify the owner |
| arm64 results differ from CI | Record the arch; repeat on x86_64 before claiming production equivalence |

---

## 13. Appendix A — One-shot bootstrap script (copy to the host)

Save as `$ACCEPT_ROOT/bootstrap.sh`, then run `MODE=preflight bash bootstrap.sh` first. It contains no
destructive action.

```bash
#!/usr/bin/env bash
set -euo pipefail
MODE="${MODE:-preflight}"
ACCEPT_ROOT="${ACCEPT_ROOT:-/srv/nexusdesk-acceptance}"
REPO_URL="${REPO_URL:?set REPO_URL}"
TARGET_SHA="${TARGET_SHA:?set TARGET_SHA}"
PG_CONTAINER="${PG_CONTAINER:-nd-accept-pg}"
PG_PORT="${PG_PORT:-55432}"
PG_USER="${PG_USER:-accept}"
PG_DB="${PG_DB:-acceptance}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

preflight() {
  echo "== preflight =="
  uname -a; uname -m; cat /etc/os-release | head -5; nproc; free -h; df -h /
  stat -fc %T /sys/fs/cgroup || true
  cat /sys/fs/cgroup/cgroup.controllers 2>&1 || true
  unshare -m true && echo mountns=ok || echo mountns=FAIL
  docker info --format '{{.OperatingSystem}} | {{.Architecture}} | cgroup={{.CgroupVersion}}' 2>&1 || true
  for c in python3 uv node npm git jq openssl mkfs.ext4 losetup; do
    printf '%-10s %s\n' "$c" "$(command -v "$c" || echo MISSING)"
  done
  sudo -n true && echo sudo=passwordless || echo sudo=needs-password
  curl -fsSI --max-time 10 https://pypi.org | head -1 || echo pypi=unreachable
}

provision() {
  echo "== provision =="
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl git build-essential jq unzip rsync \
    docker.io docker-compose-v2 python3.12 python3.12-venv python3-pip \
    postgresql-client e2fsprogs xfsprogs quota openssl
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER"
  curl -LsSf https://astral.sh/uv/install.sh | sh || true
  export PATH="$HOME/.local/bin:$PATH"
  sudo mkdir -p "$ACCEPT_ROOT"; sudo chown "$USER":"$USER" "$ACCEPT_ROOT"
  if [ ! -d "$ACCEPT_ROOT/repo/.git" ]; then
    git clone "$REPO_URL" "$ACCEPT_ROOT/repo"
  fi
  git -C "$ACCEPT_ROOT/repo" fetch origin
  git -C "$ACCEPT_ROOT/repo" checkout --detach "$TARGET_SHA"
  git -C "$ACCEPT_ROOT/repo" rev-parse HEAD
  ( cd "$ACCEPT_ROOT/repo/backend" && uv sync )
}

baseline() {
  echo "== baseline =="
  mkdir -p "$ACCEPT_ROOT/evidence/$RUN_ID"
  if ! docker inspect "$PG_CONTAINER" >/dev/null 2>&1; then
    : "${PG_PASSWORD:?set PG_PASSWORD}"
    docker run -d --name "$PG_CONTAINER" \
      -e POSTGRES_USER="$PG_USER" -e POSTGRES_PASSWORD="$PG_PASSWORD" -e POSTGRES_DB="$PG_DB" \
      -p "127.0.0.1:${PG_PORT}:5432" pgvector/pgvector:pg17
  fi
  until docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; do sleep 1; done
  export TEST_DATABASE_URL="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${PG_DB}"
  export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
  ( cd "$ACCEPT_ROOT/repo/backend" && uv run alembic upgrade head && uv run alembic heads )
}

case "$MODE" in
  preflight) preflight ;;
  provision) provision ;;
  baseline)  baseline ;;
  *) echo "MODE must be preflight|provision|baseline" >&2; exit 2 ;;
esac
```

Remote invocation pattern:

```bash
scp "$ACCEPT_ROOT/bootstrap.sh" "$ACCEPT_HOST:$ACCEPT_ROOT/bootstrap.sh"
ssh "$ACCEPT_HOST" "MODE=preflight REPO_URL='$REPO_URL' TARGET_SHA='$TARGET_SHA' bash '$ACCEPT_ROOT/bootstrap.sh'"
```

---

## 14. Appendix B — Lane → acceptance-row mapping

| Acceptance area | Rows | Lanes |
|---|---|---|
| Phase 3 capabilities/config/instructions | A1–A11, C1–C10 (C11 performance out of stage scope, 2026-11-18) | D1–D4, D9 |
| Phase 4 Runtime Host/Workspace | A1–A12, C1–C14 | D1, D2, D7, D8, D9; E1–E5 |
| Phase 5 Codex Stage A | A1–A6, A11–A12, C1–C5, C9–C10 | D1, D2, D6; E9–E10 |
| Phase 5 Stage B | A7–A10, C7 | Not runnable: not implemented; keep locked |
| Phase 6 security/reliability/events | A1–A16, C1–C12 | D1, D2, D5, D8; E6–E7, E11 |
| Phase 0/1 upstream | A1–A6 / A1–A8 | Closable via kept gates plus one acceptance-owner record on the shared host; CI provenance and real/authorized historical samples are out of stage scope (2026-11-18); see §0, where the acceptance-owner conclusion and the independent security approval are now separate rows |

Verdict mapping: a lane that only exercises controlled/deterministic doubles cannot upgrade a row whose
acceptance criterion requires real provider/tenant/host evidence. Keep the row `partial` or `pending_env`.

---

## 15. Appendix C — Do-not-claim list (read before writing 06/07 appendices)

1. **The three Phase 4 full-acceptance tests are placeholders.** Unskipping them yields
   `AssertionError`; it does not yield evidence.
2. **cgroup per-Execution hard limits are not implemented.** Probes detect controllers; `LOCAL_IMPLEMENTED`
   excludes memory/PID/CPU groups. #133 stays open until a provider enforces and tests them.
3. **Filesystem/project quota is not implemented.** `probe_fs_quota()` returns `unsupported`.
4. **No live mount-namespace implementation exists in the provider.**
5. **C11 performance is out of phase 0–3 stage scope (2026-11-18)**; p95/p50, matched pairs, sample counts and ≤5%/≤50 ms are historical notes only and never block a phase pass. Do not compute p95 from unrelated suite timings even for historical context.
6. **Phase 5 P5-IT-18 (20 scenarios × 3 runs) has no harness**; do not present ad-hoc runs as it.
7. **Phase 6 two-Worker SIGKILL/mixed-fault drills are absent**; PG-level tests are not a substitute.
8. **Representative production-replica migration evidence requires your sanitized dump.**
9. **Performance/latency claims are out of phase 0–3 stage scope (2026-11-18)**; if reported for historical context only, label the host, co-tenancy and load and keep any production claim separate.
10. **No phase is formally accepted by this runbook.** It produces evidence; the acceptance owner records
    the conclusion, and high-risk enablement needs a separate security/operations approval.
11. **README/index status lines are historical**; update them only in a reviewed PR, not silently.

---

## 16. Appendix D — Single acceptance record template (minimal core team)

```markdown
| Field | Value |
|---|---|
| Acceptance owner | <name/role> |
| Executor | <name/role; may be the same> |
| Date (UTC) | <YYYY-MM-DD> |
| Target SHA | <40-hex> |
| Environment | <OS/kernel/arch/cgroup/docker/PG; host id; shared or isolated; co-tenant note> |
| Conclusion | pass / conditionally passed / not passed |
| Evidence | <evidence dir / tarball; CI URL optional, not a gate> |
| Residuals | <L-n: level, owner, deadline> |
| High-risk enablement | not requested / separate approval link (required if any flag is enabled) |
```

**Conclusion rules**

- `pass`: every applicable A/C row has executed evidence; no open P0/P1; switch completeness proven
  (default off, explicit on, off/on/rollback matrix, no silent fallback, no flag leakage into public
  surfaces/fingerprint); tenant isolation, Secret handling, data integrity, migration correctness,
  terminal-state semantics and side effects/cleanup gates closed; one acceptance-owner record.
  Performance/C11, CI provenance and historical-sample items are out of stage scope (2026-11-18).
- `conditionally passed`: only non-hard-gate P2/P3 residuals with owner/deadline; never covers a veto
  gate (functional/switch/isolation/Secret/data/migration/terminal/side-effect) or an absent kept-gate
  prerequisite.
- `not passed`: any A/C failure, veto-gate violation, or missing required evidence for a kept gate.
  An unmeasured C11 result or absent CI/historical sample is not a valid reason for `not passed`.
- High-risk enablement is never included in "phase pass"; it is a separate decision.
