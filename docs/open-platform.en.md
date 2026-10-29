# Open Platform: Enterprise Agent API and Integrations

The enterprise API is exposed under `/openapi/v1`. Knowledge document publishing uses the existing asynchronous indexing queue.

Run the knowledge worker separately when deploying document synchronization:

```powershell
python -m agent_platform.applications.worker.knowledge
```

The API, application credentials, channel tokens, and document lifecycle semantics remain unchanged by the namespace refactor.
