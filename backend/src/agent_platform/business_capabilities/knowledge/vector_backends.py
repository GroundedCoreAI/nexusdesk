"""Vector store backends behind one publication contract.

The knowledge publication protocol is backend-agnostic: build a *fresh snapshot*
of a library, then flip ``knowledge_vector_indexes`` in a single transaction and
let the old snapshot be reclaimed later. ``VectorIndex`` owns that protocol; a
backend only has to materialise a snapshot, answer cosine search inside it, and
drop it.

Two implementations exist:

* ``MilvusBackend`` — REST v2 against a standalone cluster. A collection is the
  snapshot unit, and Milvus owns the vectors.
* ``PgVectorBackend`` — rows in ``knowledge_chunk_vectors`` inside the business
  database. ``collection_name`` plays the role of the collection, so a snapshot
  is a set of rows carrying the same name; dropping it is a ``DELETE``.

Both report *similarity* (larger is closer) on a ``-1..1`` scale for cosine, so
``fuse()``, ``min_vector_score`` and cross-library ranking behave identically no
matter which store answered.
"""

import json
import logging
from typing import Protocol

import httpx
from sqlalchemy import text

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    execute,
    one,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    resource_scope_values,
)

logger = logging.getLogger(__name__)

UPSERT_SQL = """
INSERT INTO knowledge_chunk_vectors(
    collection_name,chunk_id,tenant_id,business_id,workspace_id,kb_id,dimension,embedding
) VALUES(
    :collection,:chunk_id,:tenant_id,:business_id,:workspace_id,:kb_id,:dimension,
    CAST(:embedding AS vector)
) ON CONFLICT(collection_name,chunk_id) DO UPDATE SET
    embedding=EXCLUDED.embedding,
    dimension=EXCLUDED.dimension,
    tenant_id=EXCLUDED.tenant_id,
    kb_id=EXCLUDED.kb_id
"""


def literal(vector) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class VectorBackend(Protocol):
    name: str
    unavailable_code: str

    async def available(self) -> bool: ...

    async def create(self, collection: str, dimension: int) -> None: ...

    async def upsert(self, collection, tenant, kid, dimension, points) -> None: ...

    async def load(self, collection: str) -> None: ...

    async def search(self, collection, tenant, kid, dimension, vector, limit) -> list: ...

    async def drop(self, collection: str) -> None: ...


class MilvusBackend:
    name = "milvus"
    unavailable_code = "milvus_not_configured"

    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    async def available(self) -> bool:
        return bool(self.settings.milvus_url)

    async def request(self, path, body):
        if not self.settings.milvus_url:
            raise DomainError("milvus_not_configured", 503)
        headers = (
            {"Authorization": "Bearer " + self.settings.milvus_token.get_secret_value()}
            if self.settings.milvus_token
            else {}
        )
        try:
            response = await self.client.post(
                self.settings.milvus_url.rstrip("/") + "/v2/vectordb/" + path,
                json=body,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DomainError("milvus_unavailable", 502) from exc
        if data.get("code") != 0:
            raise DomainError("milvus_operation_failed", 502)
        return data.get("data")

    async def create(self, collection, dimension):
        await self.request(
            "collections/create",
            {
                "collectionName": collection,
                "schema": {
                    "autoID": False,
                    "enableDynamicField": True,
                    "fields": [
                        {
                            "fieldName": "id",
                            "dataType": "VarChar",
                            "isPrimary": True,
                            "elementTypeParams": {"max_length": "64"},
                        },
                        {
                            "fieldName": "vector",
                            "dataType": "FloatVector",
                            "elementTypeParams": {"dim": str(dimension)},
                        },
                    ],
                },
                "indexParams": [
                    {
                        "fieldName": "vector",
                        "indexName": "vector_index",
                        "metricType": "COSINE",
                        "params": {"index_type": "AUTOINDEX"},
                    }
                ],
            },
        )

    async def upsert(self, collection, tenant, kid, dimension, points):
        await self.request(
            "entities/upsert",
            {
                "collectionName": collection,
                "data": [
                    {
                        "id": point["id"],
                        "vector": point["vector"],
                        "tenant_id": tenant,
                        "kb_id": str(kid),
                    }
                    for point in points
                ],
            },
        )

    async def load(self, collection):
        await self.request("collections/load", {"collectionName": collection})

    async def search(self, collection, tenant, kid, dimension, vector, limit):
        hits = await self.request(
            "entities/search",
            {
                "collectionName": collection,
                "data": [vector],
                "annsField": "vector",
                "filter": "tenant_id == "
                + _quote(tenant)
                + " and kb_id == "
                + _quote(str(kid)),
                "limit": limit,
                "outputFields": ["id"],
                "consistencyLevel": "Strong",
            },
        )
        if not isinstance(hits, list):
            raise DomainError("invalid_milvus_response", 502)
        return [{"id": hit["id"], "score": hit.get("distance")} for hit in hits]

    async def drop(self, collection):
        """Drop a snapshot, treating "already gone" as success.

        The cleanup queue can legitimately hold a name that only ever existed in
        the other backend (a publication made before ``knowledge_vector_backend``
        was switched). Asking Milvus to drop an unknown collection is an error,
        but the desired end state is already true, so it must not retry forever.
        """

        try:
            await self.request("collections/drop", {"collectionName": collection})
            return
        except DomainError:
            pass
        existing = await self.request("collections/list", {})
        if collection in (existing or []):
            raise DomainError("milvus_operation_failed", 502)


class PgVectorBackend:
    """Vectors next to the documents, so visibility filters stay in one query."""

    name = "pgvector"
    unavailable_code = "pgvector_not_installed"

    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self._indexed: set[int] = set()

    async def available(self) -> bool:
        async with self.engine.connect() as c:
            row = await one(
                c,
                """SELECT to_regclass('knowledge_chunk_vectors') IS NOT NULL AS present,
                EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector') AS installed""",
            )
        return bool(row and row["installed"] and row["present"])

    async def create(self, collection, dimension):
        """The table is shared; only the per-dimension HNSW index is materialised.

        pgvector cannot index a typmod-free ``vector`` column, and one library per
        dimension would multiply tables. A partial expression index keyed by
        ``dimension`` keeps one table for every embedding space. Index creation is
        best effort: exact scan stays correct, only slower, so a locked-down
        database role that cannot run DDL must not break publication.
        """

        dimension = int(dimension)
        if not self.settings.knowledge_pgvector_hnsw or dimension in self._indexed:
            return
        statement = (
            f"CREATE INDEX IF NOT EXISTS knowledge_chunk_vectors_hnsw_{dimension} "
            "ON knowledge_chunk_vectors USING hnsw "
            f"((embedding::vector({dimension})) vector_cosine_ops) "
            f"WHERE dimension={dimension}"
        )
        try:
            async with self.engine.begin() as c:
                await execute(c, statement)
        except Exception as exc:  # noqa: BLE001 - correctness never depends on the index
            logger.warning(
                "pgvector HNSW index for dimension %s could not be created (%s); "
                "falling back to exact scan",
                dimension,
                type(exc).__name__,
            )
        else:
            self._indexed.add(dimension)

    async def upsert(self, collection, tenant, kid, dimension, points):
        scope = resource_scope_values()
        rows = [
            {
                "collection": collection,
                "chunk_id": str(point["id"]),
                "tenant_id": tenant,
                "business_id": scope["business_id"],
                "workspace_id": scope["workspace_id"],
                "kb_id": str(kid),
                "dimension": int(dimension),
                "embedding": literal(point["vector"]),
            }
            for point in points
        ]
        async with self.engine.begin() as c:
            await c.execute(text(UPSERT_SQL), rows)

    async def load(self, collection):
        """No load step: the rows are visible the moment the transaction commits."""

    async def search(self, collection, tenant, kid, dimension, vector, limit):
        dimension = int(dimension)
        distance = f"embedding::vector({dimension}) <=> CAST(:v AS vector({dimension}))"
        async with self.engine.connect() as c:
            result = await c.execute(
                text(
                    "SELECT chunk_id::text AS id,1 - ("
                    + distance
                    + ") AS score FROM knowledge_chunk_vectors "
                    "WHERE collection_name=:collection AND tenant_id=:tenant "
                    "AND kb_id=:kid AND dimension=:dimension "
                    "ORDER BY " + distance + " LIMIT :limit"
                ),
                {
                    "collection": collection,
                    "tenant": tenant,
                    "kid": str(kid),
                    "dimension": dimension,
                    "v": literal(vector),
                    "limit": int(limit),
                },
            )
            rows = result.mappings().all()
        return [{"id": row["id"], "score": row["score"]} for row in rows]

    async def drop(self, collection):
        async with self.engine.begin() as c:
            await execute(
                c,
                "DELETE FROM knowledge_chunk_vectors WHERE collection_name=:collection",
                collection=collection,
            )


def build_backend(settings, engine, client):
    if settings.knowledge_vector_backend == "milvus":
        return MilvusBackend(client, settings)
    return PgVectorBackend(engine, settings)


def _quote(value: str) -> str:
    """Milvus expression literals use JSON quoting."""

    return json.dumps(value)
