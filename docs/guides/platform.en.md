# Customer Service Platform MVP

The backend uses Python/FastAPI and PostgreSQL; the frontend uses TypeScript/React.

For local startup:

```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run python -m agent_platform.applications.seed
uv run uvicorn agent_platform.applications.customer_service.main:app --reload --host 127.0.0.1 --port 8000
```

The seed command is optional and idempotent. Preserve existing `.env` settings.

The platform supports staff accounts and fixed-role access control, enterprise OIDC/SSO, GET and JSON POST tools, and runtime SSE with transient model text deltas. See the [Chinese platform guide](platform.md) for detailed operations and current feature boundaries.
