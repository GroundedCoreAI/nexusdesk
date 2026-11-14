"""Cross-backend regression for the knowledge vector store.

``run`` publishes one library's chunks with the configured backend and records
the top-k answer for a fixed query set. Running it twice — once with
``--backend pgvector``, once with ``--backend milvus`` — and then ``compare``-ing
the two files is what "both backends behave the same" means in practice: same
chunks win, in the same order, with the same similarity scores.

The query set is derived from the corpus itself (a prefix of each chunk), so the
regression is reproducible without hand-written questions and a correct backend
must rank each chunk first for its own prefix.

    python -m scripts.vector_backend_regression run --backend pgvector --out pgv.json
    python -m scripts.vector_backend_regression run --backend milvus   --out milvus.json
    python -m scripts.vector_backend_regression compare pgv.json milvus.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from agent_platform.business_capabilities.evaluation.scoring import ProfileRef
from agent_platform.business_capabilities.knowledge.vector_store import VectorIndex
from agent_platform.core_platform.platform_services.model_gateway.gateway import ModelGateway
from agent_platform.core_platform.platform_services.persistence.store import many
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

CHUNK_SQL = """
SELECT ch.id,ch.content,ch.version,d.id AS document_id,d.title
FROM knowledge_links l
JOIN knowledge_documents d ON d.id=l.document_id
JOIN knowledge_chunks ch ON ch.document_id=d.id AND ch.version=l.published_version
WHERE l.kb_id=:kid AND l.enabled AND d.enabled AND ch.enabled
ORDER BY ch.id LIMIT 10001
"""


async def _library(engine, name):
    async with engine.connect() as c:
        sql = "SELECT id,name,settings FROM knowledge_bases WHERE enabled"
        params = {}
        if name:
            sql += " AND name=:name"
            params["name"] = name
        for row in await many(c, sql, **params):
            if row["settings"] and row["settings"].get("embedding"):
                return row
    raise SystemExit("no enabled library with a bound embedding profile")


def derive_query(content: str, prefix: int) -> str:
    """Take a real question out of a chunk.

    FAQ chunks are rows of ``question | answer | faq_id | ...``, so the question
    cell is both natural language and self-answering: a correct index must rank
    the chunk it came from first. Falling back to the longest cell keeps plain
    text corpora usable.
    """

    for line in content.splitlines():
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        for cell in cells:
            if cell.endswith(("？", "?")) and len(cell) >= 6:
                return cell[:prefix]
    for line in content.splitlines():
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if not cells:
            continue
        text = max(cells, key=len)
        if len(text) >= 12:
            return text[:prefix]
    return content[:prefix]


async def _run(args):
    settings = Settings(knowledge_vector_backend=args.backend)
    engine = create_async_engine(settings.database_url.get_secret_value())
    client = httpx.AsyncClient()
    backend_name = settings.knowledge_vector_backend
    try:
        gateway = ModelGateway(engine, settings, client)
        index = VectorIndex(engine, gateway, settings, client)
        if not await index.backend.available():
            raise SystemExit(
                f"backend {backend_name} is not available ({index.backend.unavailable_code})"
            )
        library = await _library(engine, args.kb)
        kid = library["id"]
        profile = ProfileRef.model_validate(library["settings"]["embedding"])
        async with engine.connect() as c:
            chunks = await many(c, CHUNK_SQL, kid=kid)
        if not chunks:
            raise SystemExit("library has no published chunks to index")

        started = time.monotonic()
        result = await index.build(settings.tenant_id, "regression", kid, profile, publish=True)
        build_ms = round((time.monotonic() - started) * 1000, 1)

        queries, seen = [], set()
        for chunk in chunks:
            candidate = derive_query(chunk["content"], args.prefix)
            if candidate and candidate not in seen:
                seen.add(candidate)
                queries.append({"query": candidate, "expect": str(chunk["id"])})
            if len(queries) >= args.queries:
                break
        answers = []
        for item in queries:
            tick = time.monotonic()
            hits = await index.search(settings.tenant_id, kid, item["query"], args.limit)
            answers.append(
                {
                    "query": item["query"],
                    "expect": item["expect"],
                    "latency_ms": round((time.monotonic() - tick) * 1000, 1),
                    "hits": [
                        {
                            "chunk_id": str(hit["chunk_id"]),
                            "title": hit["title"],
                            "score": None if hit["score"] is None else round(hit["score"], 6),
                        }
                        for hit in hits
                    ],
                }
            )
        payload = {
            "backend": backend_name,
            "library": str(kid),
            "library_name": library["name"],
            "chunks": len(chunks),
            "dimension": result["dimension"],
            "build_ms": build_ms,
            "answers": answers,
        }
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        print(
            f"{backend_name}: {len(chunks)} chunks, dim {result['dimension']}, "
            f"build {build_ms} ms, {len(answers)} queries -> {args.out}"
        )
        for answer in answers:
            top = answer["hits"][0] if answer["hits"] else None
            recall = "hit " if top and top["chunk_id"] == answer["expect"] else "miss"
            print(
                f"  {answer['query'][:18]!r:24} {recall} {answer['latency_ms']:>6} ms  "
                + (f"{top['title']} / {top['score']}" if top else "(no hits)")
            )
    finally:
        await client.aclose()
        await engine.dispose()


def _compare(args):
    left = json.loads(Path(args.left).read_text("utf-8"))
    right = json.loads(Path(args.right).read_text("utf-8"))
    if left["library"] != right["library"]:
        raise SystemExit("result files came from different libraries")
    if left["backend"] == right["backend"]:
        raise SystemExit("both files came from the same backend")

    print(
        f"{left['backend']} vs {right['backend']} | {left['library_name']} | "
        f"{left['chunks']} chunks | dim {left['dimension']}/{right['dimension']} | "
        f"build {left['build_ms']}/{right['build_ms']} ms\n"
    )
    header = f"{'query':26} {'top1':6} {'recall':8} {'overlap':8} {'score Δ':9} {'ms':16}"
    print(header)
    print("-" * len(header))
    overlaps, deltas, same_first, latency, recalled = [], [], [], [], []
    for a, b in zip(left["answers"], right["answers"], strict=True):
        ids_a = [h["chunk_id"] for h in a["hits"]]
        ids_b = [h["chunk_id"] for h in b["hits"]]
        union = set(ids_a) | set(ids_b)
        overlap = len(set(ids_a) & set(ids_b)) / len(union) if union else 1.0
        first = bool(ids_a) and bool(ids_b) and ids_a[0] == ids_b[0]
        hit_a = bool(ids_a) and ids_a[0] == a.get("expect")
        hit_b = bool(ids_b) and ids_b[0] == b.get("expect")
        scores_a = {h["chunk_id"]: h["score"] for h in a["hits"]}
        scores_b = {h["chunk_id"]: h["score"] for h in b["hits"]}
        shared = [
            abs(scores_a[k] - scores_b[k])
            for k in scores_a.keys() & scores_b.keys()
            if scores_a[k] is not None and scores_b[k] is not None
        ]
        delta = max(shared) if shared else 0.0
        overlaps.append(overlap)
        deltas.append(delta)
        same_first.append(first)
        recalled.append(hit_a == hit_b)
        latency.append((a["latency_ms"], b["latency_ms"]))
        print(
            f"{a['query'][:24]:26} {'same' if first else 'DIFF':6} "
            f"{('Y' if hit_a else 'n') + '/' + ('Y' if hit_b else 'n'):>8} "
            f"{overlap:>7.0%} {delta:>9.6f} "
            f"{a['latency_ms']:>6.0f}/{b['latency_ms']:<6.0f}"
        )
    print("-" * len(header))
    print(
        f"top-1 identical: {sum(same_first)}/{len(same_first)} | "
        f"mean overlap: {sum(overlaps) / len(overlaps):.1%} | "
        f"recall agreement: {sum(recalled)}/{len(recalled)} | "
        f"worst score Δ: {max(deltas):.6f}"
    )
    verdict = (
        "PASS"
        if all(same_first) and all(recalled) and min(overlaps) >= 0.99
        else "REVIEW"
    )
    print(f"verdict: {verdict}")
    return 0 if verdict == "PASS" else 1


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="publish an index with one backend and record answers")
    run.add_argument("--backend", choices=("pgvector", "milvus"), required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--kb", default=None, help="library name; defaults to the first bound one")
    run.add_argument("--queries", type=int, default=6, help="how many corpus-derived queries")
    run.add_argument("--prefix", type=int, default=24, help="characters of a chunk used as query")
    run.add_argument("--limit", type=int, default=5)
    run.set_defaults(handler=lambda a: asyncio.run(_run(a)))
    compare = sub.add_parser("compare", help="diff two result files")
    compare.add_argument("left")
    compare.add_argument("right")
    compare.set_defaults(handler=_compare)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - a regression run must exit non-zero, not traceback
        sys.stderr.write(f"vector_backend_regression: {type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
