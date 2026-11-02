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

Tool egress policy: `AGENT_TOOL_ALLOWED_HOSTS` remains the hostname allowlist. Each call resolves and validates every IPv4/IPv6 result, rejects loopback, private, link-local, multicast, reserved, and unspecified destinations, and pins the validated address for the TCP connection. Explicitly allowlisted loopback names remain available for local development. Set `AGENT_TOOL_ALLOW_PRIVATE_NETWORKS=true` only for explicitly allowlisted internal development services.

The platform supports staff accounts and fixed-role access control, enterprise OIDC/SSO, GET and JSON POST tools, and runtime SSE with transient model text deltas. See the [Chinese platform guide](platform.md) for detailed operations and current feature boundaries.
