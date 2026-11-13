"""React-native instruction provider: format adaptation only, never re-assembly.

The React message order is frozen by Phase 2 and is the whole point of AC-7:
System, optional Summary system, optional Memory system, kept history, current
Human. This provider reproduces exactly that sequence from data the caller has
already produced. It does not read Memory, does not apply switches, budgets, or
retention, and does not write anything back — all four already happened, and
doing them twice is the defect this split exists to prevent.
"""

from typing import Final

from pydantic import JsonValue

from ..contracts.instructions import (
    REACT_INSTRUCTION_PROVIDER_ID,
    REACT_INSTRUCTION_PROVIDER_VERSION,
    InstructionInput,
    PreparedInstructions,
    instruction_contract_error,
    react_native_history_item,
    react_native_messages,
)


class ReactInstructionProvider:
    """Produces the React Engine's native message sequence for one execution."""

    provider_id: Final[str] = REACT_INSTRUCTION_PROVIDER_ID
    provider_version: Final[str] = REACT_INSTRUCTION_PROVIDER_VERSION

    def prepare(self, instructions: InstructionInput) -> PreparedInstructions:
        """Adapt the prepared input to React message order; renders nothing."""
        # The triple is the Registry's decision, so serving a non-React engine
        # would be silently inventing a format. Fail closed instead of degrading.
        if instructions.engine.engine_id != "react":
            raise instruction_contract_error("instruction_prepare", "engine")

        # ``engine_context`` is deliberately not read here. Phase 3 registers no
        # Skill, workdir, or other engine-side state, and the React message
        # sequence has no slot for a placeholder channel: emitting one would put
        # unreviewed text in front of the model next to the reviewed fields. The
        # channel stays available for a provider that actually owns it, and the
        # consumer-side invariant (``react_native_input_parts``) never expects it.
        items: list[dict[str, JsonValue]] = [
            {"role": "system", "content": instructions.system_prompt}
        ]
        # Empty or switched-off slots are dropped, never emitted as blank turns.
        # The order of these two appends *is* the Summary-before-Memory rule of
        # 03 §6; the consumer can only check that injected turns stay in front of
        # history (``react_native_messages``), not tell them apart by content.
        if instructions.summary_message:
            items.append({"role": "system", "content": instructions.summary_message})
        if instructions.customer_memory:
            items.append({"role": "system", "content": instructions.customer_memory})
        # History rows are copied through as they are, blank content included:
        # the Phase 2 assembly put them in front of the model unchanged, and the
        # Engine validates this very projection against its own kept slice.
        items.extend(react_native_history_item(message) for message in instructions.history)
        items.append({"role": "user", "content": instructions.current_user_input})

        prepared = PreparedInstructions(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            payload=items,
        )
        # Self-check against the one accessor the Consumer uses, so a payload the
        # React Engine could not consume is never returned from here.
        react_native_messages(prepared)
        return prepared
