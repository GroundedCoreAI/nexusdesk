# Local Development

The local development workflow uses Python 3.11+, uv, PostgreSQL 17, Node.js, and npm. Keep existing `.env` values and run migrations before starting services.

```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run python -m agent_platform.applications.seed
uv run python -m agent_platform.applications.seed_memory_demo
uv run python -m agent_platform.applications.seed_memory_acceptance
uv run uvicorn agent_platform.applications.customer_service.main:app --reload --host 127.0.0.1 --port 8000
```

The knowledge worker is a separate process:

```powershell
uv run python -m agent_platform.applications.worker.knowledge
```

The Vite development server proxies `/api` to the API at `http://127.0.0.1:8000`.
