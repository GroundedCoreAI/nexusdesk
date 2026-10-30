"""Business-capability adapters for the capability-neutral Runtime repository."""

import json

from sqlalchemy import text

from agent_platform.business_capabilities.conversation.service import add_message
from agent_platform.business_capabilities.memory.decay import enqueue_reinforce_task
from agent_platform.business_capabilities.memory.extraction import enqueue_extract_task
from agent_platform.business_capabilities.memory.summary import enqueue_summary_task


class BusinessRuntimePersistenceHooks:
    """Keep conversation and memory side effects outside Core Platform."""

    async def add_message(self, conn, conversation_id, role, content, run_id=None):
        await add_message(conn, conversation_id, role, content, run_id)

    async def _enqueue_summary(
        self, conn, tenant, conversation_id, dropped, old_summary, max_input
    ):
        return await enqueue_summary_task(
            conn, tenant, conversation_id, dropped, old_summary, max_input
        )

    async def _enqueue_extract(
        self,
        conn,
        tenant,
        conversation_id,
        customer_id,
        debounce_seconds,
        write_mode,
        types,
    ):
        return await enqueue_extract_task(
            conn,
            tenant,
            conversation_id,
            customer_id,
            debounce_seconds,
            write_mode,
            types,
        )

    async def _enqueue_reinforce(self, conn, tenant, hits):
        return await enqueue_reinforce_task(conn, tenant, hits)

    async def on_completed(self, conn, run, conversation_id, output, history, completion):
        # Core only hands over the id; the business columns it needs (summary,
        # customer, source) are read here, still inside the caller's transaction
        # and under the conversation lock the repository already took.
        conversation = (
            (
                await conn.execute(
                    text(
                        """SELECT summary,customer_id,source
                        FROM runtime_conversations WHERE id=:id"""
                    ),
                    {"id": conversation_id},
                )
            )
            .mappings()
            .one()
        )
        await self.add_message(conn, run["conversation_id"], "assistant", output, run["id"])
        await conn.execute(
            text(
                """UPDATE runtime_conversations
                SET history=CAST(:history AS jsonb) WHERE id=:id"""
            ),
            {"id": run["conversation_id"], "history": json.dumps(history or [])},
        )
        events = []
        if completion and completion.get("dropped"):
            await self._enqueue_summary(
                conn,
                run["tenant_id"],
                run["conversation_id"],
                completion["dropped"],
                conversation["summary"],
                completion.get("max_input", 40),
            )
            events.append(("summary.queued", {"dropped": len(completion["dropped"])}))
        if (
            completion
            and completion.get("extract")
            and conversation["customer_id"]
            and conversation["source"] != "playground"
        ):
            task_id = await self._enqueue_extract(
                conn,
                run["tenant_id"],
                run["conversation_id"],
                conversation["customer_id"],
                completion.get("extract_debounce", 300),
                completion.get("write_mode", "auto"),
                completion.get("types"),
            )
            if task_id:
                events.append(
                    (
                        "memory_extract.queued",
                        {"customer_id": str(conversation["customer_id"])},
                    )
                )
        if completion and completion.get("reinforce"):
            await self._enqueue_reinforce(conn, run["tenant_id"], completion["reinforce"])
        if completion and completion.get("injected"):
            events.append(("memory.injected", completion["injected"]))
            log_rows = completion.get("injection_log")
            if log_rows and conversation["customer_id"]:
                await conn.execute(
                    text(
                        """INSERT INTO memory_injection_log
                        (tenant_id,business_id,workspace_id,run_id,customer_id,item_id,section,score)
                        SELECT :tenant,:business_id,:workspace_id,:run,:customer,item_id,section,score
                        FROM unnest(
                            CAST(:item_ids AS uuid[]),
                            CAST(:sections AS varchar[]),
                            CAST(:scores AS real[])
                        ) AS detail(item_id,section,score)"""
                    ),
                    {
                        "tenant": run["tenant_id"],
                        "business_id": run["business_id"],
                        "workspace_id": run["workspace_id"],
                        "run": run["id"],
                        "customer": conversation["customer_id"],
                        "item_ids": [entry["item_id"] for entry in log_rows],
                        "sections": [entry["section"] for entry in log_rows],
                        "scores": [entry["score"] for entry in log_rows],
                    },
                )
        return events
