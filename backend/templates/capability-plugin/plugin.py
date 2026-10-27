"""Capability package starter.

Keep domain rules and persistence in this package. Register only contracts and
capability-owned contributions with the application composition root.
"""


class ExampleCapability:
    async def start(self) -> None:
        """Initialize capability-owned resources."""

    async def stop(self) -> None:
        """Release capability-owned resources."""

    async def configure(self, config: dict[str, object]) -> None:
        """Apply one validated configuration snapshot."""
