"""Persistence hooks used by the capability-neutral Runtime repository.

Core owns the protocol only. Conversation writes and memory dispatch live in the
application composition root
(``applications/platform_runtime/runtime_hooks.py``), so no conversation schema
and no memory vocabulary (summary / extraction / reinforce) appears here, and the
repository cannot fall back to a default Core would have to know how to write.

``on_completed`` receives an opaque ``completion`` payload produced by the
injection port; only the hook implementation interprets it.
"""

from __future__ import annotations

from typing import Protocol


class RuntimePersistenceHooks(Protocol):
    """Side effects the Runtime emits but does not implement."""

    async def add_message(self, conn, conversation_id, role, content, run_id=None) -> None:
        """Append one conversation message inside the caller's transaction."""

    async def on_completed(
        self, conn, run, conversation_id, output, history, completion
    ) -> list[tuple[str, dict]]:
        """Persist application-specific completion side effects and return events.

        Receives the conversation id, not a conversation row: Core must not read
        business columns (summary / customer_id / source), so the adapter loads
        what it needs inside the same transaction.

        Returns ``(event_type, data)`` pairs for the repository to append to the
        run's event log, so the adapter decides what is worth recording without
        the Runtime knowing any of the names.
        """
