"""Instruction provider contract: one prepared Engine input per execution.

Phase 3 moves instruction assembly *ahead* of ``Adapter.start`` without moving
the business rendering. The three rules this module exists to enforce are:

* ``InstructionInput`` carries values the caller already computed — the effective
  system prompt, the already-rendered Summary/Memory text, and the already
  retained history slice. Nothing here re-reads memory or re-renders anything.
* ``engine_context`` is a controlled, non-sensitive placeholder channel. It must
  never carry a second copy of a first-class field, because that would put two
  contexts in front of one Engine (P3-UT-19 rejects it at construction).
* ``PreparedInstructions`` is provider-native and opaque to the platform. Only
  the React accessor below understands the React payload shape, and it refuses
  anything that is not the registered React provider rather than degrading. It
  also separates the slots this layer owns (prompt, injected Summary/Memory,
  current Human turn) from the stored history in between: the "no empty
  messages" rule binds the first group only, so a history row reaches the Engine
  exactly as the Phase 2 assembly handed it over (AC-7 parity).
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import (
    Annotated,
    Final,
    NamedTuple,
    Protocol,
    cast,
    runtime_checkable,
)
from uuid import UUID

from pydantic import AfterValidator, Field, JsonValue, field_validator

from .base import ExecutionContractModel
from .common import AdapterVersion, Slug
from .config import EngineIdentity
from .errors import (
    ConfigurationError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionErrorDetails,
)

# The React provider identity. ``AdapterDescriptor.instruction_provider_id`` is
# what the Registry carries; resolution against the production registration
# happens in ``agent_execution.instructions``.
REACT_INSTRUCTION_PROVIDER_ID: Final[str] = "react-native"
REACT_INSTRUCTION_PROVIDER_VERSION: Final[str] = "v1"

# A conversation history entry is the shape the Runtime already produces and
# persists: ``{"role": ..., "content": ..., "reasoning_content": str | None}``.
# It is deliberately *not* re-modelled as a second message class; the tuple keeps
# the sequence ordered and the entries are copied on the way in, while the value
# type stays exactly the stored one.
_MESSAGE_FIELDS: Final[frozenset[str]] = frozenset({"role", "content", "reasoning_content"})
# The Engine maps ``role == "user"`` to a Human turn and everything else to an
# Assistant turn, so the payload vocabulary stays these three roles exactly.
_MESSAGE_ROLES: Final[frozenset[str]] = frozenset({"system", "user", "assistant"})
_CONTEXT_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
RESERVED_CONTEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "agent_id",
        "agent_version",
        "customer_memory",
        "current_user_input",
        "engine",
        "engine_context",
        "history",
        "input",
        "instruction",
        "instructions",
        "messages",
        "payload",
        "provider",
        "provider_id",
        "provider_version",
        "summary_message",
        "summary",
        "system_prompt",
    }
)

# Scalars only: a nested value in ``engine_context`` would be an unbounded,
# unreviewed structure riding into the Engine next to the reviewed fields.
Scalar = None | bool | int | float | str


def instruction_contract_error(operation: str, field: str) -> ConfigurationError:
    """Return the one safe configuration error the instruction layer raises.

    Only stable identifiers travel in the details; no rejected value, prompt,
    history entry, or Memory text is ever echoed (C3, AC-7).
    """
    return ConfigurationError(
        ExecutionError(
            category=ExecutionErrorCategory.CONFIGURATION_ERROR,
            code=ExecutionErrorCode.INVALID_REQUEST,
            details=ExecutionErrorDetails(operation=operation, field=field),
        )
    )


def _validated_history_message(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Narrow one stored conversation entry to what the Engine can actually read.

    ``dict[str, JsonValue]`` already proves the entry is a JSON object; this
    validator only adds the three keys the Engine indexes (``role``, ``content``,
    optional ``reasoning_content``) and requires ``role`` to be a non-empty string
    and ``content`` to be a string at all. Everything else is deliberately kept
    exactly as stored, and the entry is then handed on verbatim — nothing here
    rewrites a row, drops one, or decides what the model finally sees:

    * extra keys (``created_at`` and friends) are tolerated and stay in the
      entry; the React formatter rebuilds an entry from the reviewed keys only,
      so they never reach the Engine, and the Engine ignores them either way;
    * roles outside the current vocabulary are tolerated: the Engine maps
      ``role == "user"`` to a Human turn and anything else to an Assistant turn,
      so an older row is formatted, not refused;
    * blank ``content`` is tolerated, because the Phase 2 assembly put such a row
      in front of the model unchanged. The "no empty messages" rule binds the
      slots the instruction layer owns — the injected Summary/Memory turns and
      the current Human turn (see ``react_native_messages``) — never a stored
      history row; refusing one would turn a conversation that works today into
      a new failure once the prepared path is switched on (AC-7 parity).
    """
    role = value.get("role")
    content = value.get("content")
    if not isinstance(role, str) or not role:
        raise ValueError("history entries must carry a string role")
    if not isinstance(content, str):
        # TRY004 is intentionally not followed: this runs inside a Pydantic
        # AfterValidator, where a TypeError escapes as a raw exception instead of
        # being mapped to a ValidationError (measured on the pinned pydantic).
        # Callers must see exactly one error type for a bad history entry.
        raise ValueError("history entries must carry string content")  # noqa: TRY004
    if "reasoning_content" in value and not isinstance(
        value["reasoning_content"], (str, type(None))
    ):
        raise ValueError("history reasoning_content must be a string or null")
    return value


ConversationMessage = Annotated[
    dict[str, JsonValue],
    AfterValidator(_validated_history_message),
]


class InstructionInput(ExecutionContractModel):
    """Everything one Engine needs for one execution, already rendered once."""

    engine: EngineIdentity
    agent_id: UUID
    agent_version: int = Field(ge=1)
    system_prompt: str = Field(min_length=1, max_length=100_000)
    # Already retained by the caller's sliding window; the Provider never truncates.
    history: tuple[ConversationMessage, ...] = ()
    current_user_input: str = Field(min_length=1, max_length=200_000)
    summary_message: str | None = None
    customer_memory: str | None = None
    engine_context: Mapping[str, Scalar] = Field(default_factory=dict)

    @field_validator("engine_context", "history", mode="after")
    @classmethod
    def _copied_containers(
        cls, value: Mapping[str, Scalar] | tuple[dict[str, JsonValue], ...]
    ) -> Mapping[str, Scalar] | tuple[dict[str, JsonValue], ...]:
        # Both containers are copied on the way in: a caller that keeps editing
        # the row history or the context dict it handed us must not be able to
        # change an InstructionInput that has already been validated. The Engine
        # payload consumer hands out read-only mappings, so the format a Provider
        # produces cannot be edited either.
        if isinstance(value, Mapping):
            for key in value:
                if not isinstance(key, str) or not _CONTEXT_KEY_PATTERN.fullmatch(key):
                    raise ValueError("engine_context keys must be lower snake case identifiers")
                if key in RESERVED_CONTEXT_KEYS:
                    raise ValueError(
                        "engine_context must not duplicate a first-class instruction field"
                    )
            return dict(value)
        return tuple(dict(item) for item in value)


class PreparedInstructions(ExecutionContractModel):
    """One provider's native output, identified by the provider that made it."""

    provider_id: Slug
    provider_version: AdapterVersion
    # Provider-native by design: the React payload is a message sequence, a test
    # provider's payload is its own assertable structure, and neither is forced
    # into the other's shape (AC-8).
    payload: JsonValue


@runtime_checkable
class InstructionProvider(Protocol):
    """Formats one ``InstructionInput`` for one Engine; renders nothing itself."""

    @property
    def provider_id(self) -> str:
        """Stable identifier written into ``PreparedInstructions``."""

    @property
    def provider_version(self) -> str:
        """Versioned provider contract, changed only on a format break."""

    def prepare(self, instructions: InstructionInput) -> PreparedInstructions:
        """Pure formatting step: identical input must produce an equal payload."""


def react_native_history_item(message: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Project one stored conversation row into a React message entry.

    The rule is the Phase 2 Engine's own and is unchanged: ``role == "user"``
    becomes a Human turn and anything else becomes an Assistant turn, with
    ``reasoning_content`` carried only when it is actually present. The Producer
    formats history with it and the Engine checks a prepared payload against its
    own kept slice with the same function, so a row can never be described two
    ways — which is what makes that check able to fail.
    """
    if message["role"] == "user":
        return {"role": "user", "content": message["content"]}
    item: dict[str, JsonValue] = {"role": "assistant", "content": message["content"]}
    if message.get("reasoning_content") is not None:
        item["reasoning_content"] = message["reasoning_content"]
    return item


class ReactMessagePlan(NamedTuple):
    """The slots a validated React payload was built from, in ``03 §6`` order."""

    messages: tuple[Mapping[str, JsonValue], ...]
    system_prompt: str
    # Injected Summary/Memory turns, in the order the provider emitted them.
    injected_system: tuple[Mapping[str, JsonValue], ...]
    history: tuple[Mapping[str, JsonValue], ...]
    current_user_input: str


def _injected_system_count(items: tuple[Mapping[str, JsonValue], ...]) -> int:
    """How many entries after the prompt are injected system turns.

    ``react_native_messages`` guarantees those turns form one contiguous block
    directly after the system prompt and before history, so counting the run is
    the whole split rule.
    """
    count = 0
    while 1 + count < len(items) - 1 and items[1 + count]["role"] == "system":
        count += 1
    return count


def react_native_messages(
    prepared: PreparedInstructions,
) -> tuple[Mapping[str, JsonValue], ...]:
    """Read the React Engine's native message sequence back out of a payload.

    This is the single place that knows the React payload grammar, so the
    Producer side (``ReactInstructionProvider``) and the Consumer side
    (``RuntimeEngine``) cannot drift. A payload from any other provider is a
    contract error, never a reason to fall back to a different interpretation.

    What is refused: a foreign provider, a sequence shorter than one system and
    one human turn, an entry with a key or role the Engine cannot map, a content
    that is not a string, ``reasoning_content`` on anything but an assistant
    turn, a blank content in a slot the instruction layer owns (the leading
    system block and the current Human turn), and an injected system turn placed
    after history has started. What is *not* refused: a stored history row with
    blank content — kept rows are the conversation as written, and the Phase 2
    assembly put them in front of the model verbatim (AC-7 parity).
    """
    if not isinstance(prepared, PreparedInstructions):
        raise instruction_contract_error("instruction_consume", "prepared")
    if (
        prepared.provider_id != REACT_INSTRUCTION_PROVIDER_ID
        or prepared.provider_version != REACT_INSTRUCTION_PROVIDER_VERSION
    ):
        raise instruction_contract_error("instruction_consume", "provider_id")

    payload = prepared.payload
    if not isinstance(payload, list) or len(payload) < 2:
        raise instruction_contract_error("instruction_consume", "payload")

    last = len(payload) - 1
    items: list[Mapping[str, JsonValue]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict) or set(entry) - _MESSAGE_FIELDS:
            raise instruction_contract_error("instruction_consume", "payload")
        role = entry.get("role")
        content = entry.get("content")
        if not isinstance(role, str) or role not in _MESSAGE_ROLES:
            raise instruction_contract_error("instruction_consume", "payload")
        if not isinstance(content, str):
            raise instruction_contract_error("instruction_consume", "payload")
        # No empty messages, for the slots this layer owns: an injected slot that
        # rendered to nothing must have been dropped by the Provider, and the
        # current Human turn is the input the run was asked about. History rows
        # in between are pass-through data and stay as they are.
        if not content and (role == "system" or index == last):
            raise instruction_contract_error("instruction_consume", "payload")
        if "reasoning_content" in entry and (
            role != "assistant" or not isinstance(entry["reasoning_content"], str)
        ):
            raise instruction_contract_error("instruction_consume", "payload")
        items.append(MappingProxyType(dict(entry)))

    # System prompt first, current Human turn last; everything between them is
    # optional Summary/Memory system turns plus the kept history (AC-7 order).
    if items[0]["role"] != "system" or items[-1]["role"] != "user":
        raise instruction_contract_error("instruction_consume", "payload")
    # The injected slots are one contiguous block right after the prompt. Stored
    # history can only ever surface as a user or assistant entry (see
    # ``react_native_history_item``), so a system turn after history has started
    # is a Summary/Memory message inserted into the middle of the conversation —
    # not the order 03 §6 fixes, and not something to reorder here.
    injected = _injected_system_count(tuple(items))
    if any(item["role"] == "system" for item in items[1 + injected : last]):
        raise instruction_contract_error("instruction_consume", "payload")
    return tuple(items)


def react_native_input_parts(prepared: PreparedInstructions) -> ReactMessagePlan:
    """Split a validated React payload back into the slots it was built from.

    ``react_native_messages`` has already fixed the shape, so the split is pure
    bookkeeping: the leading system block is the prompt plus the injected
    Summary/Memory turns in provider order, everything between that block and
    the last entry is the kept history, and the last entry is the current Human
    turn. This is the consumer-side mirror of ``InstructionInput``, which is what
    lets the Engine compare a payload against the arguments it was called with
    instead of trusting either.
    """
    items = react_native_messages(prepared)
    injected = _injected_system_count(items)
    plan = ReactMessagePlan(
        messages=items,
        # Both are checked non-empty strings by ``react_native_messages`` above;
        # the annotations document that guarantee rather than coerce it.
        system_prompt=cast("str", items[0]["content"]),
        injected_system=items[1 : 1 + injected],
        history=items[1 + injected : -1],
        current_user_input=cast("str", items[-1]["content"]),
    )
    return plan
