# Knowledge Workspace Implementation

## Local runtime commands

Run migrations from `backend`, then start the refactored application entrypoint:

```powershell
uv run uvicorn agent_platform.applications.customer_service.main:app --host 127.0.0.1 --port 8000
uv run python -m agent_platform.applications.worker.knowledge
```

The knowledge worker must run separately from the API. It processes parsing, chunking, and indexing jobs for the configured tenant.
