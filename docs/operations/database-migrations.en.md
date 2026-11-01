# Database Migrations

[中文](database-migrations.md) · **English**

NexusDesk uses one Alembic chain under `backend/migrations/versions/`. The chain currently contains 52 revisions, from `0001_runtime` through `0052_memory_tasks_tenant_index`.

Run migrations from the `backend` directory after confirming that `AGENT_DATABASE_URL` points to the intended environment:

```bash
uv run alembic heads
uv run alembic current
uv run alembic upgrade head
```

Migrations are an explicit deployment step. Backup the target database first, and do not treat rolling back an application image as rolling back the schema. Some downgrades deliberately refuse to proceed when data would require export or conversion; never use `stamp` to disguise an incomplete rollback.

The [Chinese migration guide](database-migrations.md) documents the ticketing and other major migrations, data-backfill behavior, rollback boundaries, and the isolated PostgreSQL migration tests. Current test results come from CI rather than historical pass counts.
