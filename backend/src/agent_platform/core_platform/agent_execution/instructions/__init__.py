"""Production instruction-provider registration.

React is the only Engine Phase 3 registers, so exactly one provider is reachable
from here. The independent test format provider is deliberately not referenced by
this module — not in the registry, not in an import — so it cannot reach a
production Registry entry even by accident (P3-UT-19). An unregistered provider id
must fail resolution rather than quietly borrow the React formatter.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from ..contracts.instructions import (
    REACT_INSTRUCTION_PROVIDER_ID,
    REACT_INSTRUCTION_PROVIDER_VERSION,
    InstructionProvider,
    instruction_contract_error,
)
from .react_provider import ReactInstructionProvider

REACT_INSTRUCTION_PROVIDER: Final[ReactInstructionProvider] = ReactInstructionProvider()

PRODUCTION_INSTRUCTION_PROVIDERS: Final[Mapping[tuple[str, str], InstructionProvider]] = (
    MappingProxyType(
        {
            (
                REACT_INSTRUCTION_PROVIDER_ID,
                REACT_INSTRUCTION_PROVIDER_VERSION,
            ): REACT_INSTRUCTION_PROVIDER,
        }
    )
)


def resolve_instruction_provider(
    provider_id: object,
    provider_version: object,
) -> InstructionProvider:
    """Exact ``id`` + ``version`` lookup; unknown identities never fall back.

    Both parameters stay ``object`` on purpose: the caller is the Registry
    descriptor plus an already-published configuration, and a hostile or
    mis-typed value has to produce the same configuration error as an unknown
    name instead of a ``TypeError`` that a caller might be tempted to swallow.
    """
    try:
        provider = PRODUCTION_INSTRUCTION_PROVIDERS.get((provider_id, provider_version))
    except TypeError:
        provider = None
    if provider is None:
        raise instruction_contract_error("instruction_resolve", "provider_id")
    return provider


__all__ = [
    "PRODUCTION_INSTRUCTION_PROVIDERS",
    "REACT_INSTRUCTION_PROVIDER",
    "resolve_instruction_provider",
]
