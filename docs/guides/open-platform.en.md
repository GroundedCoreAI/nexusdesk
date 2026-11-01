# Open Platform: Enterprise Agent API and Integrations

The enterprise API is exposed under `/openapi/v1`. Runtime SSE includes replayable lifecycle events and transient `model.delta` events containing visible answer text only; deltas are not replayed, and `run.completed` remains the source of the complete answer. Knowledge document publishing uses the existing asynchronous indexing queue.

Run the knowledge worker separately when deploying document synchronization:

```powershell
python -m agent_platform.applications.worker.knowledge
```

The API, application credentials, channel tokens, and document lifecycle semantics remain unchanged by the namespace refactor.
