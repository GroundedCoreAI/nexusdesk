"""Memory rendering adapted to the Runtime's injected-context port.

Everything that knows memory vocabulary lives here, next to the capability that
owns it. ``core_platform.agent_runtime`` holds only a
``MemoryInjectionPort`` reference, so the Runtime decides *whether* to inject and
this module decides *what* the text is.

Both the render helpers (:mod:`.service`, :mod:`.summary`) and the switch
resolution (``agent_config.memory.resolve_agent_memory``) are reused as-is: this
module adds no second copy of any of them.
"""

from __future__ import annotations

import logging
import random

from agent_platform.business_capabilities.agent_config.memory import (
    MEMORY_TYPES,
    resolve_agent_memory,
)
from agent_platform.business_capabilities.memory.service import (
    overlap_ids,
    render_event_injection,
    render_flag_injection,
    render_memory_injection,
)
from agent_platform.business_capabilities.memory.summary import render_injection

logger = logging.getLogger(__name__)


class MemoryInjection:
    """Render rolling summaries and customer memory for one run.

    Implements ``extension_contracts.MemoryInjectionPort``. ``store`` may be
    ``None`` in deployments without customer memory: the switches still resolve
    so extraction and summary dispatch keep working. The effective ``settings``
    arrive per call, so a long-lived adapter never holds a stale snapshot.
    """

    def __init__(self, store):
        self.store = store

    def render_summary(self, summary):
        return render_injection(summary) if summary else None

    async def customer_memory(self, row, settings):
        if self.store is None or not row.get("customer_id"):
            return None
        agent = (row["config"].get("agent") or {}).get("config") or {}
        effective = resolve_agent_memory(agent, settings)
        if not effective.read:
            return None
        profile_types = tuple(t for t in ("profile", "preference") if t in effective.types)
        event_limit = min(
            effective.inject_max_items,
            getattr(settings, "memory_event_inject_max", 5),
        )
        try:
            items = await self.store.injection_items(
                row["tenant_id"],
                row["customer_id"],
                effective.inject_max_items,
                types=profile_types,
            )
            events = (
                await self.store.pending_event_items(
                    row["tenant_id"], row["customer_id"], event_limit
                )
                if "event" in effective.types
                else []
            )
            flags = await self.store.active_flags(
                row["tenant_id"],
                row["customer_id"],
                getattr(settings, "memory_flag_inject_max", 3),
            )
        except Exception:
            logger.warning("Customer memory lookup failed for run %s", row["id"], exc_info=True)
            return None

        reinforce = row.setdefault("_memory_reinforce", {})
        for item_id in overlap_ids([*items, *events], row.get("input") or ""):
            key = str(item_id)
            reinforce[key] = reinforce.get(key, 0) + 1
        flag_text, flag_log = render_flag_injection(flags)
        memory_text, memory_log = render_memory_injection(items)
        event_text, event_log = render_event_injection(events)
        sections = [section for section in (flag_text, memory_text, event_text) if section]
        if sections:
            rendered = [*flag_log, *memory_log, *event_log]
            row["_memory_injected"] = {
                "items": len(items),
                "flags": len(flags),
                "events": len(events),
                "item_ids": [str(item_id) for item_id, _, _ in rendered if item_id],
            }
            row["_memory_injection_log"] = [
                {
                    "item_id": str(item_id),
                    "section": section,
                    "score": round(float(score), 6) if score is not None else None,
                }
                for item_id, section, score in rendered
                if item_id
            ]
        return "\n\n".join(sections) or None

    def memory_context(self, row, dropped, settings):
        agent = row["config"].get("agent") or {}
        effective = resolve_agent_memory(agent.get("config") or {}, settings)
        memory = {}
        if dropped and effective.summary:
            memory["dropped"] = dropped
            memory["max_input"] = settings.summary_max_input_messages
        if effective.write and not agent.get("is_example"):
            memory["extract"] = True
            memory["extract_debounce"] = settings.memory_extract_debounce_seconds
            memory["write_mode"] = effective.write_mode
            memory["types"] = [t for t in MEMORY_TYPES if t in effective.types]
        hits = row.get("_memory_reinforce")
        if (
            getattr(settings, "memory_decay_enabled", False)
            and hits
            and random.random() < getattr(settings, "memory_reinforce_sample_rate", 1.0)
        ):
            memory["reinforce"] = hits
        if row.get("_memory_injected"):
            memory["injected"] = row["_memory_injected"]
        if row.get("_memory_injection_log") and getattr(
            settings, "memory_injection_log_enabled", True
        ):
            memory["injection_log"] = row["_memory_injection_log"]
        return memory or None


__all__ = ["MemoryInjection"]
