# Module Delivery Notes

Run `uv sync`, apply `uv run alembic upgrade head`, and install frontend dependencies with `npm ci`.

Start the services with:

```powershell
uv run uvicorn agent_platform.applications.customer_service.main:app --host 127.0.0.1 --port 8000
npm run dev
uv run python -m agent_platform.applications.worker.knowledge
```

The knowledge worker must use the same database and tenant configuration as the API. It claims jobs with PostgreSQL locking and retries expired leases.
