"""Engine descriptors and independent in-process registration."""

from ..contracts.base import ExecutionContractModel
from ..contracts.common import EngineId
from ..contracts.errors import (
    ConfigurationError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionErrorDetails,
)


class EngineDescriptor(ExecutionContractModel):
    """Registration metadata for one engine."""

    engine_id: EngineId
    enabled: bool = True


def _configuration_error(
    code: ExecutionErrorCode,
    *,
    engine_id: str | None = None,
) -> ConfigurationError:
    return ConfigurationError(
        ExecutionError(
            category=ExecutionErrorCategory.CONFIGURATION_ERROR,
            code=code,
            details=ExecutionErrorDetails(engine_id=engine_id),
        )
    )


class EngineRegistry:
    """Synchronous registry containing only engine descriptors."""

    def __init__(self) -> None:
        self._descriptors: dict[str, EngineDescriptor] = {}

    def register(self, descriptor: EngineDescriptor) -> None:
        """Register one engine, rejecting every duplicate identifier."""
        if not isinstance(descriptor, EngineDescriptor):
            raise _configuration_error(ExecutionErrorCode.INVALID_REQUEST)
        if descriptor.engine_id in self._descriptors:
            raise _configuration_error(
                ExecutionErrorCode.DUPLICATE_ENGINE,
                engine_id=descriptor.engine_id,
            )
        self._descriptors[descriptor.engine_id] = descriptor

    def get(self, engine_id: str) -> EngineDescriptor | None:
        """Return a registered descriptor without constructing runtime objects."""
        if not isinstance(engine_id, str):
            return None
        return self._descriptors.get(engine_id)
