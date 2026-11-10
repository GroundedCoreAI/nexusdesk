"""Protocol descriptors and independent in-process registration."""

from ..contracts.base import ExecutionContractModel
from ..contracts.common import ProtocolId
from ..contracts.errors import (
    ConfigurationError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionErrorDetails,
)


class ProtocolDescriptor(ExecutionContractModel):
    """Registration metadata for one protocol."""

    protocol_id: ProtocolId
    enabled: bool = True


def _configuration_error(
    code: ExecutionErrorCode,
    *,
    protocol_id: str | None = None,
) -> ConfigurationError:
    return ConfigurationError(
        ExecutionError(
            category=ExecutionErrorCategory.CONFIGURATION_ERROR,
            code=code,
            details=ExecutionErrorDetails(protocol_id=protocol_id),
        )
    )


class ProtocolRegistry:
    """Synchronous registry containing only protocol descriptors."""

    def __init__(self) -> None:
        self._descriptors: dict[str, ProtocolDescriptor] = {}

    def register(self, descriptor: ProtocolDescriptor) -> None:
        """Register one protocol, rejecting every duplicate identifier."""
        if not isinstance(descriptor, ProtocolDescriptor):
            raise _configuration_error(ExecutionErrorCode.INVALID_REQUEST)
        if descriptor.protocol_id in self._descriptors:
            raise _configuration_error(
                ExecutionErrorCode.DUPLICATE_PROTOCOL,
                protocol_id=descriptor.protocol_id,
            )
        self._descriptors[descriptor.protocol_id] = descriptor

    def get(self, protocol_id: str) -> ProtocolDescriptor | None:
        """Return a registered descriptor without constructing runtime objects."""
        if not isinstance(protocol_id, str):
            return None
        return self._descriptors.get(protocol_id)
