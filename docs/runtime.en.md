# Asynchronous Customer-Service Runtime

The runtime uses LangGraph for model/tool execution and PostgreSQL for conversations, queues, terminal run state, and events.

Start the API with:

```powershell
uv run uvicorn agent_platform.applications.customer_service.main:app --host 127.0.0.1 --port 8000
```

To separate API and worker processes, set `AGENT_EMBEDDED_WORKER=false` and run:

```powershell
uv run python -m agent_platform.applications.worker
```

Migrations remain an explicit deployment step; processes do not create tables automatically.
