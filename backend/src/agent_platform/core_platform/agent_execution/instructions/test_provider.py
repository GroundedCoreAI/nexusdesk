"""Test-only instruction provider with a deliberately non-React format.

This module exists to prove AC-8: the same ``InstructionInput`` can be handed to
a second provider, and neither the platform nor the caller has to render the
business inputs a second time or bend them into ReAct message order. It is
imported only by test compositions; ``instructions/__init__.py`` never references
it, so it cannot reach a production Registry entry.
"""

from typing import Final

from pydantic import JsonValue

from ..contracts.instructions import (
    InstructionInput,
    PreparedInstructions,
)

TEST_INSTRUCTION_PROVIDER_ID: Final[str] = "test-native"
TEST_INSTRUCTION_PROVIDER_VERSION: Final[str] = "v1"
TEST_INSTRUCTION_FORMAT: Final[str] = "test-native-v1"


class TestInstructionProvider:
    """Keeps every input in its own keyed slot instead of a message sequence."""

    provider_id: Final[str] = TEST_INSTRUCTION_PROVIDER_ID
    provider_version: Final[str] = TEST_INSTRUCTION_PROVIDER_VERSION

    def prepare(self, instructions: InstructionInput) -> PreparedInstructions:
        """Return an assertable native structure; empty slots stay explicit nulls."""
        payload: dict[str, JsonValue] = {
            "format": TEST_INSTRUCTION_FORMAT,
            "engine": instructions.engine.model_dump(mode="json"),
            "agent_id": str(instructions.agent_id),
            "agent_version": instructions.agent_version,
            "system_prompt": instructions.system_prompt,
            # A switched-off or empty Summary stays ``null`` here. ReAct would
            # have dropped the turn entirely; keeping the field is what proves
            # this format is not a disguised ReAct sequence.
            "summary_message": instructions.summary_message,
            "customer_memory": instructions.customer_memory,
            "history": [dict(item) for item in instructions.history],
            "current_user_input": instructions.current_user_input,
            "engine_context": dict(instructions.engine_context),
        }
        return PreparedInstructions(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            payload=payload,
        )
