"""Shared identity fields and bounded string validators."""

import unicodedata
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, StringConstraints

from .base import ExecutionContractModel

EngineId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$"),
]
ProtocolId = EngineId
AdapterVersion = Annotated[
    str,
    StringConstraints(min_length=2, pattern=r"^v[1-9][0-9]*$"),
]
EventType = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]
Slug = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]


def _validate_opaque_string(value: str) -> str:
    if value[0].isspace() or value[-1].isspace():
        raise ValueError("Opaque strings must not have leading or trailing whitespace.")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("Opaque strings must not contain control characters.")
    return value


OpaqueString = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200),
    AfterValidator(_validate_opaque_string),
]


class ExecutionKey(ExecutionContractModel):
    """Identity shared by execution requests, handles, results, and events."""

    execution_id: UUID
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
