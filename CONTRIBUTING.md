# Contributing

> Chinese version: [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md). This file is the English original. The Chinese version is optional; if it is maintained, both versions must be kept in sync.

Thanks for your interest in building NexusDesk with us. Ways to get involved include bug reports, documentation improvements, test cases and code contributions.

Before you start, please read the **current state and boundaries** of the project — it saves time on both sides:

- The project is under continuous development. The core customer-service flow runs, but it is **not yet production-ready out of the box**.
- What is implemented and what is planned are documented separately. Section 1 of each module README describes the **current code**; the remaining sections keep the **target design**, which is not necessarily delivered.
- Known limitations are listed in [current status and limits](README.md#current-status-and-limits) on the project home page and in section 1 of each module README. Archived documents are for historical reference only.

## Reporting issues

1. Use the matching issue template: **bug report**, **feature request** or **deployment problem**.
2. Describe the **use case, reproduction steps, deployment mode and redacted logs**. For deployment problems the three essentials are "deployment mode / middleware / logs".
3. If you are unsure whether the issue fits your scenario, or it cannot be reproduced yet, start a
   [discussion](https://github.com/GroundedCoreAI/nexusdesk/discussions) instead.

⚠️ **Do not include API keys, access tokens, database passwords or customer privacy data in issues, screenshots or code.**

For security vulnerabilities, please **do not** open a public issue — report it privately as described in [SECURITY.md](SECURITY.md).

## Sharing use cases

We are collecting real-world customer-service scenarios to decide which capabilities the platform should abstract next. If you are running (or have tried and abandoned) a customer-service agent, please share a case at
[call for use cases](https://github.com/GroundedCoreAI/nexusdesk/discussions/93).

**You do not need to use NexusDesk**, and you do not need to fill in every field — one concrete paragraph is far more useful than a blank form. This is product research: concrete defects and feature requests should still go through the issue templates above.

## Which branch to develop from

| Branch | Purpose | PR target |
|---|---|---|
| `integration` | Day-to-day development — **the default branch** | **Functionality, fixes, refactors and documentation all go here** |
| `main` | Release line (what the last release was cut from) | Only merges from `integration`, plus maintainer `release/*` and `hotfix/*` branches |

The repository's **default branch is `integration`**: clones, code browsing, forks and new pull requests all land on it. Branch off it:

```bash
git fetch origin
git switch -c fix/your-change origin/integration
```

Do not target `main` with a feature or fix pull request — it is the release line and does not receive development directly. If you already opened a branch from `main`, move it over before submitting:

```bash
git rebase --onto origin/integration origin/main your-branch
```

The reason `main` is not a starting point: it is a release snapshot, while `integration` carries the current documentation structure and module paths. A branch cut from `main` produces a large number of conflicts unrelated to your change when merged into `integration`, and the review gets buried in that noise. If you are unsure, just open the PR and we will help you adjust it.

## Contributing code

1. **Read [local development](docs/development/local-development.en.md) and [module development rules](docs/development/module-development.en.md) before you start.**
2. For changes involving architecture or data structures, **align on direction in an issue or discussion first** so that work does not have to be redone.
3. When submitting a change, state **the problem solved, the affected scope and the verification result**.
4. When an API or data structure changes, **update the documentation and the database migration together**. Migrations are append-only: never modify an already-applied migration.

### Self-checks before submitting

Run in the `backend` directory (this is what CI runs):

```bash
# Style and static checks
ruff check .
ruff format --check .

# Backend tests
pytest
```

> Note: without `TEST_DATABASE_URL`, tests marked `postgres` are skipped. For changes involving migrations or transactions, configure a real PostgreSQL instance and run them again.

In the `frontend` directory:

```bash
npm run build      # includes the i18n check and the TypeScript build
```

### Required CI gates (PR vs opt-in/live)

Every pull request must pass these non-mutating checks before merge (none rewrite tracked files):

- **Backend lint & architecture** (`Backend lint (ruff + architecture)`): `uv run ruff check .`, `uv run ruff format --check` on changed Python files, `python scripts/check_architecture.py`, and JS SDK tests (`sdk/javascript`: `npm test`).
- **Backend unit tests** (`Backend tests (unit)`): `pytest -m "not postgres"`.
- **Backend Postgres integration tests** (`Backend tests (postgres 1/2)`, `Backend tests (postgres 2/2)`): `alembic upgrade head` followed by `pytest -m postgres`. Missing `TEST_DATABASE_URL` or `MIGRATION_TEST_DATABASE_URL` fails closed when `CI=true` or `REQUIRE_POSTGRES_TESTS=1` rather than silently skipping.
- **Frontend** (`Frontend (i18n + typecheck + build)`): `npm run check:i18n` and `npm run build` (`tsc --noEmit` + Vite build).

Opt-in live-service suites (`KNOWLEDGE_LIVE=1`, `NEXUSDESK_LIVE_QUICKSTART=1`, and Playwright `npm run test:e2e`) are excluded from per-commit PR blockers and run on demand against live stacks. CI step summaries report test failures, fixture/infrastructure errors, and skipped tests separately.

### Conventions

- **Documentation is written in English**: new or updated documentation (`docs/`, `README*`, `CHANGELOG*`) only requires an English version. Existing Chinese versions (e.g. `README.zh-CN.md`, `CONTRIBUTING.zh-CN.md`) are optional and may be kept, updated, or retired over time. Frontend locale files are still maintained in parallel under `frontend/src/i18n/locales/`.
- **If a Chinese version is maintained, keep both versions in sync**: editing only one lets the two language versions silently diverge. Both must keep the same section structure.
- **Do not reformat unrelated files**, to avoid producing a huge unrelated diff.
- New features should carry **tests**, especially around transactions, migrations and permissions.
- **Write operations keep the existing "propose → human confirm" constraint**: an agent must never perform irreversible business actions on its own.

## Contributing documentation

A wrong statement, an unclear description or an example that does not run are all valuable feedback. Open a PR, or point out the location in an issue.

## Code of conduct

Keep technical discussions focused and civil: argue about the work, not the person, and do not start flame wars. This project targets self-hosted enterprise scenarios, so real customer environment details often appear in discussions — **never ask for or disclose someone else's sensitive configuration**.

## License

This project is licensed under the [Apache License 2.0](LICENSE). By contributing you agree to license your contribution under that license.
