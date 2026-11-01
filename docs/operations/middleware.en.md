# Middleware and External Services

[中文](middleware.md) · **English**

NexusDesk requires PostgreSQL for business data and task queues. Other services depend on the enabled capabilities:

| Service | Purpose | Requirement |
|---|---|---|
| PostgreSQL | Business data, runtime and task queues, and optional pgvector retrieval for customer memory | Required; deployment templates use PostgreSQL 17 |
| Milvus | Vector indexing and retrieval for the knowledge base | Required for knowledge vector/hybrid search, not keyword-only search |
| MinIO / S3 | Original document storage | Optional; PostgreSQL is used when object storage is not configured |
| Model APIs | Chat, Embedding, Rerank, OCR, and speech operations | Configure when using the corresponding real model capability |
| External document parser | OCR and specialized document parsing | Configure when local parsing is insufficient |

Task scheduling does not require Redis, RabbitMQ, Kafka, or Celery. Knowledge vector/hybrid search uses Milvus; customer-memory vector retrieval can use PostgreSQL pgvector when the extension and embedding profile are available, which does not require Milvus.

See the [deployment guide](../../deploy/README.md), [production environment template](../../deploy/production/.env.example), and [backend environment template](../../backend/.env.example). Keep credentials in environment configuration rather than source code or images. The [Chinese middleware guide](middleware.md) lists all settings and Compose boundaries; the environment-specific server record is retained only in the [historical archive](../archive/middleware-server.md).
