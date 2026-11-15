"""P3-UT-16..19: InstructionInput, React/test providers, and React instruction parity.

AC-7 and AC-8 are parity requirements, so every case here compares the provider
output against the *real* ``RuntimeEngine.run`` message assembly (the Phase 2
baseline) instead of against a hand-written expectation. T6 deliverables are
loaded through ``importlib`` so a missing deliverable fails as a target-behaviour
gap inside the test, never as a module collection error.
"""

import ast
import copy
import importlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import chain
from pathlib import Path
from typing import Final
from uuid import UUID

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from agent_platform.applications.platform_runtime.runtime_factory import RuntimeFactory
from agent_platform.core_platform.agent_execution.contracts import ConfigurationError
from agent_platform.core_platform.agent_execution.contracts.config import EngineIdentity
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.service import ToolGateway
from agent_platform.extension_contracts import RuntimeBindings

AGENT_ID = UUID("60000000-0000-4000-8000-000000000006")
RUN_ID = UUID("61000000-0000-4000-8000-000000000001")
REACT_ENGINE = {"engine_id": "react", "protocol_id": "native", "adapter_version": "v1"}
NON_REACT_ENGINE = {"engine_id": "codex", "protocol_id": "cli", "adapter_version": "v1"}
AGENT_PROMPT = "AGENT PROMPT"
SYSTEM_RULES = "PLATFORM PROMPT"
CURRENT_INPUT = "current question"


def _contract():
    return importlib.import_module(
        "agent_platform.core_platform.agent_execution.contracts.instructions"
    )


def _package():
    return importlib.import_module("agent_platform.core_platform.agent_execution.instructions")


def _react_module():
    return importlib.import_module(
        "agent_platform.core_platform.agent_execution.instructions.react_provider"
    )


def _test_module():
    return importlib.import_module(
        "agent_platform.core_platform.agent_execution.instructions.test_provider"
    )


def _react_provider():
    return _react_module().ReactInstructionProvider()


def _test_provider():
    return _test_module().TestInstructionProvider()


def _factory_module():
    """The module holding the snapshot RuntimeFault codes raised by preparation."""
    return importlib.import_module("agent_platform.applications.platform_runtime.runtime_factory")


def _contains_callable(value: object) -> bool:
    """True when a live object (port, callable, model) is reachable inside a payload."""
    if callable(value) and not isinstance(value, type):
        return True
    if isinstance(value, Mapping):
        return any(_contains_callable(item) for item in chain(value.keys(), value.values()))
    if isinstance(value, (str, bytes)) or value is None:
        return False
    if isinstance(value, Sequence):
        return any(_contains_callable(item) for item in value)
    return not isinstance(value, (bool, int, float, UUID))


def _input(**updates):
    """One InstructionInput carrying the full 03 §6 field set."""
    contract = _contract()
    fields = {
        "engine": EngineIdentity(**REACT_ENGINE),
        "agent_id": AGENT_ID,
        "agent_version": 3,
        "system_prompt": "platform rules\nAGENT PROMPT\nlanguage policy",
        "history": (),
        "current_user_input": CURRENT_INPUT,
        "summary_message": None,
        "customer_memory": None,
        "engine_context": {},
    }
    fields.update(updates)
    return contract.InstructionInput(**fields)


def _payload_items(prepared):
    """The react-native payload, read back through the contract accessor."""
    return [dict(item) for item in _contract().react_native_messages(prepared)]


def _expected_types(instructions):
    """System -> optional Summary -> optional Memory -> kept history -> current user."""
    types = ["system"]
    if instructions.summary_message:
        types.append("system")
    if instructions.customer_memory:
        types.append("system")
    types.extend("human" if item["role"] == "user" else "ai" for item in instructions.history)
    types.append("human")
    return types


class _RecordingModel:
    """Captures the exact message objects the Engine hands to the model.

    The reply carries explicit usage so a parity diff cannot hide inside an
    otherwise empty ``usage`` event field (P3-UT-17, H-5).
    """

    USAGE: Final[dict[str, int]] = {
        "input_tokens": 11,
        "output_tokens": 5,
        "total_tokens": 16,
    }

    def __init__(self, content="answer") -> None:
        self.content = content
        self.seen: list[list[object]] = []

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return AIMessage(content=self.content, usage_metadata=dict(self.USAGE))


def _capture(rounds):
    return [
        [
            {
                "type": message.type,
                "content": message.content,
                "additional_kwargs": dict(message.additional_kwargs),
            }
            for message in round_messages
        ]
        for round_messages in rounds
    ]


class _TripwireMemory:
    """A Memory port stand-in that fails loudly if anything ever reaches it.

    H-4 replaced the old counting stand-in, whose counters could not move: the
    port was never handed to ``prepare_instructions`` or to a provider, so
    ``summary_calls == 1`` was true by construction. This one is fed to the very
    APIs it must not fit, and any acceptance or call is an immediate failure.
    """

    def render_summary(self, summary):
        raise AssertionError("instruction preparation must never render a summary")

    async def customer_memory(self, row, settings):
        raise AssertionError("instruction preparation must never read customer memory")

    def memory_context(self, row, dropped, settings):
        raise AssertionError("instruction preparation must never touch the memory port")


class _RoundPolicy:
    """Mirrors ``PolicyService.check_rounds``: the platform ceiling only narrows."""

    def check_rounds(self, requested, settings):
        return min(requested, settings.max_model_rounds)


class _PrepOnlyFactory(RuntimeFactory):
    """Real factory with every runner-side construction path booby-trapped."""

    def __init__(self, settings, client) -> None:
        super().__init__(
            object(), RuntimeBindings(policy=_RoundPolicy()), client, settings, shared_limit=None
        )
        self.effective_calls = 0

    def effective(self, snapshot):
        self.effective_calls += 1
        return super().effective(snapshot)

    def bound_model(self, snapshot, schemas, run_id=None):
        raise AssertionError("instruction preparation must not build a model")

    async def for_run(self, row, emit):
        raise AssertionError("instruction preparation happens before any runner exists")


def _agent_config(**overrides):
    config = {
        "system_prompt": AGENT_PROMPT,
        "tool_names": [],
        "knowledge_base_ids": [],
        "reply_language": "auto",
        "summary_enabled": True,
        "max_model_rounds": 6,
    }
    config.update(overrides)
    return config


def _row(config_overrides=None, **updates):
    row = {
        "id": RUN_ID,
        "tenant_id": "tenant-a",
        "conversation_id": None,
        "input": CURRENT_INPUT,
        "history": [],
        "summary": None,
        "_memory": None,
        "config": {
            "fingerprint": "t6-fingerprint",
            "agent": {
                "id": str(AGENT_ID),
                "version": 3,
                "config": _agent_config(**(config_overrides or {})),
                "tools": [],
            },
        },
    }
    row.update(updates)
    return row


# ``duration_ms`` is measured by the Engine itself and differs between two
# identical runs; every other emitted field — round, usage, first_token_ms,
# tool_call counts — is compared, so the prepared path cannot quietly change
# what a run reports while keeping the message sequence looking the same (H-5).
_TIMING_EVENT_KEYS: Final[frozenset[str]] = frozenset({"duration_ms"})


async def _run(engine, *, current, history, summary, memory, prepared=None):
    """Run one Engine and record every emitted event, payload included.

    A prepared run deliberately passes no ``summary_message``/``customer_memory``:
    those rendered strings are already inside the payload, and the Engine
    rejects them a second time (H-2). The baseline run keeps its Phase 2 call
    shape, which is the whole point of the comparison.
    """
    events = []

    async def emit(kind, data):
        events.append((kind, {k: v for k, v in data.items() if k not in _TIMING_EVENT_KEYS}))

    if prepared is None:
        result = await engine.run(
            current, history, emit, summary_message=summary, customer_memory=memory
        )
    else:
        result = await engine.run(current, history, emit, prepared_instructions=prepared)
    return result, events


async def _parity(settings, *, history, summary=None, customer_memory=None, config_overrides=None):
    """Run one row through the Phase 2 assembly and the prepared path.

    Both engines are constructed from the same effective settings, so a diff can
    only come from the instruction path itself. Returns
    ``(baseline, prepared, instructions)`` where each run is
    ``(captured_messages, engine_return, emitted_events)``.
    """
    row = _row(config_overrides)
    async with httpx.AsyncClient() as client:
        factory = _PrepOnlyFactory(settings, client)
        effective = factory.effective(row["config"]["agent"])
        instructions = factory.prepare_instructions(
            row,
            history=history,
            summary_message=summary,
            customer_memory=customer_memory,
        )
        prepared = _react_provider().prepare(instructions)

        baseline_engine = RuntimeEngine(
            _RecordingModel(), ToolGateway(httpx.AsyncClient(), []), effective
        )
        baseline_result = await _run(
            baseline_engine,
            current=row["input"],
            history=copy.deepcopy(history),
            summary=summary,
            memory=customer_memory,
        )
        prepared_engine = RuntimeEngine(
            _RecordingModel(), ToolGateway(httpx.AsyncClient(), []), effective
        )
        prepared_result = await _run(
            prepared_engine,
            current=row["input"],
            history=copy.deepcopy(history),
            summary=summary,
            memory=customer_memory,
            prepared=prepared,
        )
    return (
        (_capture(baseline_engine.model.seen), *baseline_result),
        (_capture(prepared_engine.model.seen), *prepared_result),
        instructions,
    )


def _factory_settings(**overrides):
    settings = Settings(_env_file=None, system_prompt=SYSTEM_RULES, **overrides)
    return _PrepOnlyFactory(settings, httpx.AsyncClient())


# ---------------------------------------------------------------------------
# P3-UT-16: empty Summary/Memory and switched-off inputs produce no empty messages
# ---------------------------------------------------------------------------


def test_p3_ut_16_empty_summary_and_memory_produce_no_empty_messages():
    provider = _react_provider()

    for summary, memory in ((None, None), ("", ""), (None, ""), ("", None)):
        prepared = provider.prepare(
            _input(
                history=({"role": "user", "content": "earlier"},),
                summary_message=summary,
                customer_memory=memory,
            )
        )
        items = _payload_items(prepared)
        assert [item["role"] for item in items] == ["system", "user", "user"]
        assert [item["content"] for item in items] == [
            _input().system_prompt,
            "earlier",
            CURRENT_INPUT,
        ]
        assert all(item["content"] for item in items), items
        assert all("reasoning_content" not in item for item in items), items


def test_p3_ut_16_summary_switch_off_keeps_the_baseline_sequence():
    # Agent-level switch stays on: the platform kill switch is what turns the
    # summary off here, which is the only combination the Engine ever saw.
    row = _row()
    rendered = "SUMMARY: rolled up"
    provider = _react_provider()

    switched_off = _factory_settings(summary_enabled=False)
    instructions_off = switched_off.prepare_instructions(
        row, history=[{"role": "user", "content": "earlier"}], summary_message=rendered
    )
    assert instructions_off.summary_message is None

    instructions_on = _factory_settings(summary_enabled=True).prepare_instructions(
        row, history=[{"role": "user", "content": "earlier"}], summary_message=rendered
    )
    assert instructions_on.summary_message == rendered

    items_off = _payload_items(provider.prepare(instructions_off))
    items_without_summary = _payload_items(
        provider.prepare(instructions_on.model_copy(update={"summary_message": None}))
    )
    assert items_off == items_without_summary
    assert [item["role"] for item in items_off] == ["system", "user", "user"]
    # The switch may hide the summary; it must never rewrite or drop the prompt.
    assert (
        items_off[0]["content"] == instructions_off.system_prompt == instructions_on.system_prompt
    )


def test_p3_ut_16_blank_history_rows_pass_through_but_blank_slots_still_fail():
    # H-1: "no empty messages" is a rule about the slots the instruction layer
    # owns (prompt, Summary, Memory, current Human turn). A stored history row
    # is passed through exactly as the Phase 2 assembly always passed it, blank
    # content included; rejecting one would turn an already-working conversation
    # into a new failure once the prepared path is switched on.
    contract = _contract()
    provider = _react_provider()

    instructions = _input(
        history=(
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "", "reasoning_content": "thinking"},
            {"role": "system", "content": ""},
            {"role": "user", "content": "kept tail", "created_at": "stored extra key"},
        ),
        summary_message="SUMMARY: rolled up",
    )
    assert [item["content"] for item in instructions.history] == ["", "", "", "kept tail"]

    items = _payload_items(provider.prepare(instructions))
    assert items == [
        {"role": "system", "content": instructions.system_prompt},
        {"role": "system", "content": "SUMMARY: rolled up"},
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "", "reasoning_content": "thinking"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "kept tail"},
        {"role": "user", "content": CURRENT_INPUT},
    ]

    # Blank slots and a blank current Human turn stay forbidden, and a content
    # that is not a string at all is still refused whatever the slot is.
    for rejected in (
        [{"role": "system", "content": ""}, {"role": "user", "content": "x"}],
        [
            {"role": "system", "content": "prompt"},
            {"role": "system", "content": ""},
            {"role": "user", "content": "x"},
        ],
        [{"role": "system", "content": "prompt"}, {"role": "user", "content": ""}],
        [
            {"role": "system", "content": "prompt"},
            {"role": "user", "content": None},
            {"role": "user", "content": "x"},
        ],
    ):
        with pytest.raises(ConfigurationError):
            contract.react_native_messages(_prepared_payload(rejected))


def _prepared_payload(items):
    """Wrap a raw React payload so the accessor can be driven directly."""
    contract = _contract()
    return contract.PreparedInstructions(
        provider_id=contract.REACT_INSTRUCTION_PROVIDER_ID,
        provider_version=contract.REACT_INSTRUCTION_PROVIDER_VERSION,
        payload=items,
    )


# ---------------------------------------------------------------------------
# P3-UT-17: System -> Summary -> Memory -> kept history -> current user, identical
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("summary", "customer_memory", "history", "settings_overrides"),
    [
        (None, None, [], {}),
        ("SUMMARY: rolled up", None, [], {}),
        (None, "CUSTOMER: preference-a", [], {}),
        ("SUMMARY: rolled up", "CUSTOMER: preference-a", [{"role": "user", "content": "h1"}], {}),
        (
            "SUMMARY: rolled up",
            "CUSTOMER: preference-a",
            [
                {"role": "user", "content": "h1"},
                {"role": "assistant", "content": "a1", "reasoning_content": "r1"},
                {"role": "assistant", "content": "a2", "reasoning_content": None},
                {"role": "system", "content": "legacy role"},
            ],
            {},
        ),
        ("", "", [{"role": "user", "content": "h1"}], {}),
        (
            "SUMMARY: rolled up",
            "CUSTOMER: preference-a",
            [{"role": "user", "content": "h1"}],
            {"summary_enabled": False},
        ),
        (
            "SUMMARY: rolled up",
            "CUSTOMER: preference-a",
            [{"role": "user", "content": f"q{index}"} for index in range(1, 6)]
            + [{"role": "assistant", "content": f"a{index}"} for index in range(1, 6)],
            {"history_turns": 2},
        ),
        (
            "SUMMARY: rolled up",
            "CUSTOMER: preference-a",
            [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}],
            {"history_turns": 0},
        ),
        # H-1 (AC-7 parity): stored rows with blank content are passed through
        # verbatim by the Phase 2 assembly, so the prepared path must too.
        (
            None,
            None,
            [
                {"role": "user", "content": ""},
                {"role": "assistant", "content": ""},
                {"role": "user", "content": "tail"},
            ],
            {},
        ),
        (
            "SUMMARY: rolled up",
            "CUSTOMER: preference-a",
            [
                {"role": "system", "content": ""},
                {"role": "assistant", "content": "", "reasoning_content": ""},
            ],
            {"history_turns": 2},
        ),
    ],
)
@pytest.mark.asyncio
async def test_p3_ut_17_react_provider_reproduces_the_engine_message_sequence(
    summary, customer_memory, history, settings_overrides
):
    settings = Settings(_env_file=None, system_prompt=SYSTEM_RULES, **settings_overrides)
    baseline, prepared, instructions = await _parity(
        settings, history=history, summary=summary, customer_memory=customer_memory
    )

    # Message sequence, content, and reasoning kwargs are identical, and the
    # writeback (output, kept history, dropped) plus emitted events are untouched.
    assert prepared[0] == baseline[0]
    assert prepared[1] == baseline[1]
    assert prepared[2] == baseline[2]
    assert len(prepared[0]) == 1, "the model must be called exactly once"
    assert [item["type"] for item in prepared[0][0]] == _expected_types(instructions)
    assert prepared[0][0][0]["content"] == instructions.system_prompt


@pytest.mark.asyncio
async def test_p3_ut_17_history_truncation_is_applied_once_by_preparation():
    history = [
        {"role": role, "content": f"{prefix}{index}"}
        for index in range(1, 6)
        for role, prefix in (("user", "q"), ("assistant", "a"))
    ]
    factory = _factory_settings(history_turns=2)
    row = _row()

    instructions = factory.prepare_instructions(
        row, history=copy.deepcopy(history), summary_message="SUMMARY: rolled up"
    )
    # Existing retention policy: the last history_turns * 2 entries, oldest dropped.
    assert [item["content"] for item in instructions.history] == ["q4", "a4", "q5", "a5"]

    # The Provider must not truncate a second time: fed the full history it emits all of it.
    untruncated = _payload_items(
        _react_provider().prepare(
            instructions.model_copy(update={"history": tuple(copy.deepcopy(history))})
        )
    )
    assert [item["content"] for item in untruncated] == [
        instructions.system_prompt,
        "SUMMARY: rolled up",
        *(item["content"] for item in history),
        CURRENT_INPUT,
    ]

    prepared_items = _payload_items(_react_provider().prepare(instructions))
    assert [item["content"] for item in prepared_items] == [
        instructions.system_prompt,
        "SUMMARY: rolled up",
        "q4",
        "a4",
        "q5",
        "a5",
        CURRENT_INPUT,
    ]

    baseline, prepared_run, _ = await _parity(
        Settings(_env_file=None, system_prompt=SYSTEM_RULES, history_turns=2),
        history=history,
        summary="SUMMARY: rolled up",
    )
    assert prepared_run[0] == baseline[0]
    assert prepared_run[1] == baseline[1]
    # Kept/dropped history come from the Engine writeback, never from the Provider.
    output, kept, dropped = prepared_run[1]
    assert output == "answer"
    assert [item["content"] for item in kept] == ["q5", "a5", CURRENT_INPUT, "answer"]
    assert [item["content"] for item in dropped] == ["q4", "a4"]


@pytest.mark.asyncio
async def test_p3_ut_17_zero_history_turns_keeps_only_system_and_current_user():
    settings = Settings(_env_file=None, system_prompt=SYSTEM_RULES, history_turns=0)

    baseline, prepared, instructions = await _parity(
        settings,
        history=[{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}],
    )

    assert prepared[0] == baseline[0]
    assert prepared[1] == baseline[1]
    assert [item["type"] for item in prepared[0][0]] == ["system", "human"]
    assert instructions.history == ()


def test_p3_ut_17_fixed_instruction_order_is_enforced_on_both_sides():
    # H-7: 03 §6 freezes System -> Summary -> Memory -> kept history -> current
    # Human. The producer side is checked here by content (the payload cannot
    # tell a Summary turn from a Memory turn by anything but position), and the
    # consumer side refuses a payload that puts an injected system turn after
    # history, because that would reorder the conversation the Engine sees.
    contract = _contract()
    provider = _react_provider()

    instructions = _input(
        summary_message="SUMMARY: rolled up",
        customer_memory="CUSTOMER: preference-a",
        history=({"role": "user", "content": "h1"},),
    )
    items = _payload_items(provider.prepare(instructions))
    assert [item["role"] for item in items] == ["system", "system", "system", "user", "user"]
    assert [item["content"] for item in items] == [
        instructions.system_prompt,
        "SUMMARY: rolled up",
        "CUSTOMER: preference-a",
        "h1",
        CURRENT_INPUT,
    ]

    # Memory-only and Summary-only inputs keep the same relative order.
    memory_only = _payload_items(
        provider.prepare(instructions.model_copy(update={"summary_message": None}))
    )
    assert [item["content"] for item in memory_only][:2] == [
        instructions.system_prompt,
        "CUSTOMER: preference-a",
    ]

    # A system slot after history is not a re-arrangement the consumer accepts.
    with pytest.raises(ConfigurationError) as caught:
        contract.react_native_messages(
            _prepared_payload(
                [
                    {"role": "system", "content": "prompt"},
                    {"role": "user", "content": "h1"},
                    {"role": "system", "content": "late summary"},
                    {"role": "user", "content": CURRENT_INPUT},
                ]
            )
        )
    assert caught.value.error.details.field == "payload"

    parts = contract.react_native_input_parts(
        provider.prepare(
            _input(
                summary_message="SUMMARY: rolled up",
                customer_memory="CUSTOMER: preference-a",
                history=({"role": "user", "content": "h1"},),
            )
        )
    )
    assert parts.system_prompt == instructions.system_prompt
    assert [item["content"] for item in parts.injected_system] == [
        "SUMMARY: rolled up",
        "CUSTOMER: preference-a",
    ]
    assert [item["content"] for item in parts.history] == ["h1"]
    assert parts.current_user_input == CURRENT_INPUT
    assert parts.messages == tuple(items)


# ---------------------------------------------------------------------------
# P3-UT-18: the test provider proves format independence and single business render
# ---------------------------------------------------------------------------


def test_p3_ut_18_test_provider_keeps_an_independent_native_format():
    factory = _factory_settings()
    instructions = factory.prepare_instructions(
        _row(history=[{"role": "user", "content": "h1"}]),
        history=[{"role": "user", "content": "h1"}],
        summary_message="SUMMARY: rolled up",
        customer_memory="CUSTOMER: preference-a",
    )
    contract = _contract()

    react = _react_provider().prepare(instructions)
    test = _test_provider().prepare(instructions)

    assert react.provider_id == contract.REACT_INSTRUCTION_PROVIDER_ID
    assert react.provider_version == contract.REACT_INSTRUCTION_PROVIDER_VERSION
    assert test.provider_id == _test_module().TEST_INSTRUCTION_PROVIDER_ID
    assert test.provider_id != react.provider_id
    assert test.payload != react.payload

    # React format: one ordered ReAct message sequence, nothing else.
    react_items = _payload_items(react)
    assert [item["role"] for item in react_items] == ["system", "system", "system", "user", "user"]

    # Test format: keyed segments stay themselves. Empty slots remain explicit
    # nulls instead of vanishing as messages, and the history keeps its own shape,
    # which proves the input is not forced through the ReAct mould.
    assert isinstance(test.payload, dict)
    assert set(test.payload) == {
        "format",
        "engine",
        "agent_id",
        "agent_version",
        "system_prompt",
        "summary_message",
        "customer_memory",
        "history",
        "current_user_input",
        "engine_context",
    }
    assert test.payload["format"] == "test-native-v1"
    assert test.payload["engine"] == REACT_ENGINE
    assert test.payload["agent_id"] == str(AGENT_ID)
    assert test.payload["agent_version"] == 3
    assert test.payload["summary_message"] == "SUMMARY: rolled up"
    assert test.payload["customer_memory"] == "CUSTOMER: preference-a"
    assert test.payload["history"] == [{"role": "user", "content": "h1"}]
    assert test.payload["current_user_input"] == CURRENT_INPUT

    emptied = instructions.model_copy(
        update={"summary_message": None, "customer_memory": None, "history": ()}
    )
    assert _test_provider().prepare(emptied).payload["summary_message"] is None
    assert _test_provider().prepare(emptied).payload["customer_memory"] is None
    assert [item["role"] for item in _payload_items(_react_provider().prepare(emptied))] == [
        "system",
        "user",
    ]


def test_p3_ut_18_instruction_input_carries_rendered_values_and_never_a_memory_port():
    # H-4: the guarantee is structural, not a counter. ``InstructionInput`` owns
    # exactly the 03 §6 value fields, every instruction API refuses a live object
    # in their place, and no provider output contains one — so a second business
    # render has no channel to happen through, and adding such a channel turns
    # this test red instead of quietly updating a counter nobody increments.
    contract = _contract()
    factory = _factory_settings()
    row = _row(summary="rolled up", _memory="preference-a")
    sentinel_summary = "SUMMARY: rendered once by the caller"
    sentinel_memory = "CUSTOMER: rendered once by the caller"

    assert set(contract.InstructionInput.model_fields) == {
        "engine",
        "agent_id",
        "agent_version",
        "system_prompt",
        "history",
        "current_user_input",
        "summary_message",
        "customer_memory",
        "engine_context",
    }

    instructions = factory.prepare_instructions(
        row, summary_message=sentinel_summary, customer_memory=sentinel_memory
    )
    assert instructions.summary_message == sentinel_summary
    assert instructions.customer_memory == sentinel_memory
    # Preparation computed the effective prompt once and built no runner-side object.
    assert factory.effective_calls == 1
    assert factory.models == {}

    port = _TripwireMemory()
    refusals = (
        {"summary_message": port, "customer_memory": sentinel_memory},
        {"summary_message": sentinel_summary, "customer_memory": port},
        {
            "summary_message": sentinel_summary,
            "customer_memory": sentinel_memory,
            "engine_context": {"memory_port": port},
        },
    )
    # The preparation entry point is where a port could still be smuggled in, so
    # it must fail closed with the instruction layer's non-echoing error (H-6).
    for kwargs in refusals:
        with pytest.raises(ConfigurationError) as caught:
            _factory_settings().prepare_instructions(row, history=[], **kwargs)
        assert caught.value.error.details.field in set(contract.InstructionInput.model_fields)
    # The DTO itself is the hard boundary: the same values are refused here too.
    for kwargs in (
        {"summary_message": port},
        {"customer_memory": port},
        {"engine_context": {"memory_port": port}},
        {"history": ({"role": "user", "content": port},)},
    ):
        with pytest.raises(ValidationError):
            _input(**kwargs)

    react = _react_provider().prepare(instructions)
    test = _test_provider().prepare(instructions)
    for payload in (react.payload, test.payload):
        assert not _contains_callable(payload), payload
    # Both formats carry the caller's single render verbatim, and formatting is
    # pure: the same input twice is the same payload.
    assert _payload_items(react)[1]["content"] == sentinel_summary
    assert test.payload["summary_message"] == sentinel_summary
    assert test.payload["customer_memory"] == sentinel_memory
    assert _react_provider().prepare(instructions).payload == react.payload
    assert _test_provider().prepare(instructions).payload == test.payload


def test_p3_ut_18_react_provider_ignores_engine_context():
    # H-8: Phase 3 deliberately does not wire Skills or a workdir through the
    # instruction channel. ``engine_context`` is a placeholder the React provider
    # reads and then drops, while the test provider proves the values really are
    # in the input — so this is provider-side policy, not a platform-wide loss.
    instructions = _input(engine_context={"workspace_hint": "hint value", "run_mode": 1})
    plain = _input()

    contextual = _react_provider().prepare(instructions)
    assert contextual.payload == _react_provider().prepare(plain).payload
    assert "workspace_hint" not in json.dumps(contextual.payload)
    assert "hint value" not in json.dumps(contextual.payload)
    assert dict(instructions.engine_context) == {"workspace_hint": "hint value", "run_mode": 1}
    assert _test_provider().prepare(instructions).payload["engine_context"] == {
        "workspace_hint": "hint value",
        "run_mode": 1,
    }
    # Static half of the same guarantee: the React formatter never *reads* the
    # channel (a comment recording the deliberate drop is fine, an attribute
    # access is not), so Skill/Workdir state cannot creep into the messages.
    tree = ast.parse(Path(_react_module().__file__).read_text(encoding="utf-8"))
    loaded_attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    }
    assert "engine_context" not in loaded_attributes


def test_p3_ut_18_preparation_computes_the_effective_prompt_once_before_any_runner():
    factory = _factory_settings()
    row = _row(history=[{"role": "user", "content": "h1"}])

    instructions = factory.prepare_instructions(
        row, history=row["history"], summary_message=None, customer_memory=None
    )

    # Exactly one effective-settings computation for the whole preparation, and no
    # model, tool, or Runtime construction on the way.
    assert factory.effective_calls == 1
    assert factory.models == {}
    comparison = _factory_settings().effective(_row()["config"]["agent"])
    assert instructions.system_prompt == comparison.system_prompt
    assert instructions.engine.model_dump() == REACT_ENGINE
    assert instructions.agent_id == AGENT_ID
    assert instructions.agent_version == 3
    assert instructions.current_user_input == CURRENT_INPUT
    assert isinstance(instructions, _contract().InstructionInput)
    assert _test_provider().prepare(instructions).payload["system_prompt"] == (
        comparison.system_prompt
    )


# ---------------------------------------------------------------------------
# P3-UT-19: unknown provider, duplicate context, and contract errors fail before start
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identity",
    [
        ("unknown-native", "v1"),
        ("react-native", "v2"),
        ("react_native", "v1"),
        ("test-native", "v1"),
        ("", ""),
        ("REACT-NATIVE", "v1"),
    ],
)
def test_p3_ut_19_resolve_rejects_unknown_providers_without_fallback(identity):
    package = _package()
    provider = _react_provider()

    resolved = package.resolve_instruction_provider(provider.provider_id, provider.provider_version)
    assert resolved is package.REACT_INSTRUCTION_PROVIDER
    assert type(resolved) is type(provider)

    with pytest.raises(ConfigurationError) as caught:
        package.resolve_instruction_provider(*identity)
    assert caught.value.error.code.value == "invalid_request"
    assert caught.value.error.category.value == "configuration_error"


@pytest.mark.parametrize("hostile", [None, 1, 1.5, True, ["react-native"], {"a": 1}, object()])
def test_p3_ut_19_resolve_rejects_hostile_provider_identity(hostile):
    package = _package()

    for arguments in ((hostile, hostile), ("react-native", hostile), (hostile, "v1")):
        with pytest.raises(ConfigurationError):
            package.resolve_instruction_provider(*arguments)


def test_p3_ut_19_test_provider_is_never_production_registered():
    package = _package()
    contract = _contract()
    test = _test_provider()

    assert set(package.PRODUCTION_INSTRUCTION_PROVIDERS) == {
        (contract.REACT_INSTRUCTION_PROVIDER_ID, contract.REACT_INSTRUCTION_PROVIDER_VERSION)
    }
    assert isinstance(
        package.PRODUCTION_INSTRUCTION_PROVIDERS[
            (contract.REACT_INSTRUCTION_PROVIDER_ID, contract.REACT_INSTRUCTION_PROVIDER_VERSION)
        ],
        _react_module().ReactInstructionProvider,
    )
    assert not hasattr(package, "TestInstructionProvider")
    assert not hasattr(_react_module(), "TestInstructionProvider")
    # Static guarantee: no import in the production registration module reaches
    # the test provider, so a Registry entry for it cannot be added by accident.
    init_path = (
        Path(__file__).parents[1]
        / "src"
        / "agent_platform"
        / "core_platform"
        / "agent_execution"
        / "instructions"
        / "__init__.py"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(init_path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)
    assert not [name for name in imported if "test_provider" in name.lower()]
    assert not [name for name in imported if "Test" in name]
    # ... and it is not reachable through the production registry either.
    with pytest.raises(ConfigurationError):
        package.resolve_instruction_provider(test.provider_id, test.provider_version)


def test_p3_ut_19_duplicate_context_fails_the_contract():
    for duplicate in (
        "summary_message",
        "customer_memory",
        "system_prompt",
        "history",
        "current_user_input",
        "input",
        "messages",
        "engine",
        "agent_id",
    ):
        with pytest.raises(ValidationError):
            _input(engine_context={duplicate: "already carried by a first-class field"})


def test_p3_ut_19_contract_errors_fail_closed():
    contract = _contract()

    with pytest.raises(ValidationError):
        contract.InstructionInput(engine=REACT_ENGINE, unexpected=1)
    with pytest.raises(ValidationError):
        _input(unknown_field=1)
    with pytest.raises(ValidationError):
        _input(system_prompt="")
    with pytest.raises(ValidationError):
        _input(current_user_input="")
    with pytest.raises(ValidationError):
        _input(engine_context={"nested": {"not": "a scalar"}})
    with pytest.raises(ValidationError):
        _input(history=({"role": "user", "content": 7},))
    with pytest.raises(ValidationError):
        _input(history=({"content": "no role"},))
    with pytest.raises(ValidationError):
        _input(summary_message=7)
    with pytest.raises(ValidationError):
        _input(agent_id=str(AGENT_ID))
    with pytest.raises(ValidationError):
        _input(engine="react")
    with pytest.raises(ValidationError):
        _input(engine_context={"UPPER_CASE": "x"})
    with pytest.raises(ValidationError):
        _input(history=[{"role": "user", "content": "list instead of tuple"}])
    frozen = _input()
    with pytest.raises(ValidationError):
        frozen.agent_version = 4
    with pytest.raises(ValidationError):
        contract.PreparedInstructions(
            provider_id=contract.REACT_INSTRUCTION_PROVIDER_ID,
            provider_version=contract.REACT_INSTRUCTION_PROVIDER_VERSION,
            payload=[{"role": "system", "content": "x"}, {"role": "user", "content": "y"}],
            extra=1,
        )


def test_p3_ut_19_react_provider_refuses_foreign_engine_and_payload():
    contract = _contract()
    provider = _react_provider()
    instructions = _input()

    with pytest.raises(ConfigurationError):
        provider.prepare(_input(engine=EngineIdentity(**NON_REACT_ENGINE)))

    # A foreign provider payload is never re-interpreted as React instructions.
    with pytest.raises(ConfigurationError):
        contract.react_native_messages(_test_provider().prepare(instructions))

    for bad in (
        "not a message sequence",
        7,
        None,
        [],
        [{"role": "user", "content": "no system prompt"}],
        [{"role": "system", "content": "prompt"}, {"role": "user", "content": "x", "extra": 1}],
        [{"role": "system", "content": "prompt"}, {"role": "tool", "content": "x"}],
        [{"role": "system", "content": None}, {"role": "user", "content": "x"}],
        [
            {"role": "system", "content": "prompt"},
            {"role": "user", "content": "x"},
            {"role": "system", "content": "trailing"},
        ],
        [{"role": "system", "content": "prompt"}],
    ):
        with pytest.raises(ConfigurationError):
            contract.react_native_messages(
                contract.PreparedInstructions(
                    provider_id=contract.REACT_INSTRUCTION_PROVIDER_ID,
                    provider_version=contract.REACT_INSTRUCTION_PROVIDER_VERSION,
                    payload=bad,
                )
            )

    # The provider's own output always round-trips through the same accessor.
    assert [
        dict(item) for item in contract.react_native_messages(provider.prepare(instructions))
    ] == [
        {"role": "system", "content": instructions.system_prompt},
        {"role": "user", "content": instructions.current_user_input},
    ]


async def _noop_emit(kind, data):
    return None


@pytest.mark.asyncio
async def test_p3_ut_19_engine_never_degrades_when_the_prepared_input_is_foreign():
    settings = Settings(_env_file=None, system_prompt=SYSTEM_RULES)
    engine_model = _RecordingModel()
    engine = RuntimeEngine(engine_model, ToolGateway(httpx.AsyncClient(), []), settings)
    instructions = _input(system_prompt=settings.system_prompt)

    with pytest.raises(ConfigurationError):
        await engine.run(
            CURRENT_INPUT,
            [],
            _noop_emit,
            prepared_instructions=_test_provider().prepare(instructions),
        )
    assert engine_model.seen == []

    with pytest.raises(ConfigurationError):
        await engine.run(CURRENT_INPUT, [], _noop_emit, prepared_instructions="not instructions")
    assert engine_model.seen == []


@pytest.mark.asyncio
async def test_p3_ut_19_start_is_never_reached_when_preparation_fails():
    class _StartSpy:
        def __init__(self) -> None:
            self.start_calls = 0

        async def start(self, prepared):
            # Only a prepared input that survived every pre-start check may get
            # here; anything else must leave this counter at zero.
            self.start_calls += 1
            return prepared

    spy = _StartSpy()
    factory = _factory_settings()
    provider = _react_provider()

    async def prepare_and_start(row):
        instructions = factory.prepare_instructions(
            row, history=[], summary_message=None, customer_memory=None
        )
        prepared = provider.prepare(instructions)
        await spy.start(prepared)
        return prepared

    # A claimed row without a published Agent snapshot cannot be prepared.
    legacy_row = {"id": RUN_ID, "tenant_id": "tenant-a", "input": CURRENT_INPUT, "config": {}}
    with pytest.raises(RuntimeFault):
        await prepare_and_start(legacy_row)
    assert spy.start_calls == 0

    # An unregistered provider is refused before anything can be started.
    with pytest.raises(ConfigurationError):
        _package().resolve_instruction_provider("react-native", "v9")
    assert spy.start_calls == 0

    # A duplicate context fails at DTO construction, i.e. before any await.
    with pytest.raises(ValidationError):
        _input(engine_context={"customer_memory": "second copy"})
    assert spy.start_calls == 0

    # A happy preparation does reach the (spied) start exactly once.
    prepared = await prepare_and_start(_row())
    assert spy.start_calls == 1
    assert prepared.provider_id == _contract().REACT_INSTRUCTION_PROVIDER_ID


# ---------------------------------------------------------------------------
# T6 hardening: H-2 prepared-argument invariant, H-3 snapshot codes, H-6 no echo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut_19_prepared_input_that_contradicts_the_engine_arguments_fails_closed():
    # H-2: the prepared branch used to ignore arguments it disagreed with, so a
    # caller could persist one current input while the model only ever saw the
    # one inside the payload, and a re-supplied Summary/Memory vanished without
    # a trace. A contradiction is now the instruction layer's own error, raised
    # before the model is called — never a silent fallback to the baseline.
    settings = Settings(_env_file=None, system_prompt=SYSTEM_RULES)
    instructions = _input(system_prompt=settings.system_prompt)
    prepared = _react_provider().prepare(instructions)

    async with httpx.AsyncClient() as client:
        model = _RecordingModel()
        engine = RuntimeEngine(model, ToolGateway(client, []), settings)

        with pytest.raises(ConfigurationError) as caught:
            await engine.run("ANOTHER QUESTION", [], _noop_emit, prepared_instructions=prepared)
        assert caught.value.error.details.field == "current_user_input"
        assert caught.value.error.category.value == "configuration_error"
        assert caught.value.error.code.value == "invalid_request"

        for field, extra in (
            ("summary_message", {"summary_message": "SUMMARY: rolled up"}),
            ("summary_message", {"summary_message": ""}),
            ("customer_memory", {"customer_memory": "CUSTOMER: preference-a"}),
            ("customer_memory", {"customer_memory": ""}),
        ):
            with pytest.raises(ConfigurationError) as caught:
                await engine.run(
                    CURRENT_INPUT, [], _noop_emit, prepared_instructions=prepared, **extra
                )
            assert caught.value.error.details.field == field

        assert model.seen == [], "the guard must fire before the model is called"

        # The same call without the contradiction still runs.
        rounds = len(model.seen)
        output, kept, dropped = await engine.run(
            CURRENT_INPUT, [], _noop_emit, prepared_instructions=prepared
        )
        assert output == "answer"
        assert len(model.seen) == rounds + 1
        assert [item["content"] for item in kept][-2:] == [CURRENT_INPUT, "answer"]
        assert dropped == []

        # The off/baseline branch is untouched: it still takes the Phase 2 args.
        output, _, _ = await engine.run(
            CURRENT_INPUT,
            [],
            _noop_emit,
            summary_message="SUMMARY: rolled up",
            customer_memory="CUSTOMER: preference-a",
        )
        assert output == "answer"


@pytest.mark.asyncio
async def test_p3_ut_19_prepared_history_must_be_the_windows_own_kept_slice():
    # H-2 (other half): the payload's history and the Engine's kept slice come
    # from two settings objects that can disagree. The message sequence alone
    # cannot show it, but kept/dropped — and with them the persisted history and
    # the summary rollup queue — would drift silently.
    rows = [
        {"role": "user", "content": "q1", "created_at": "extra keys stay tolerated"},
        {"role": "assistant", "content": "a1", "reasoning_content": "r1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    prepared = _react_provider().prepare(
        _input(system_prompt=SYSTEM_RULES, history=tuple(copy.deepcopy(row) for row in rows))
    )
    narrow = Settings(_env_file=None, system_prompt=SYSTEM_RULES, history_turns=1)
    wider = Settings(_env_file=None, system_prompt=SYSTEM_RULES, history_turns=3)

    async with httpx.AsyncClient() as client:
        model = _RecordingModel()
        with pytest.raises(ConfigurationError) as caught:
            await RuntimeEngine(model, ToolGateway(client, []), narrow).run(
                CURRENT_INPUT, copy.deepcopy(rows), _noop_emit, prepared_instructions=prepared
            )
        assert caught.value.error.details.field == "history"
        assert model.seen == []

        # A different settings object that keeps exactly the prepared slice is
        # accepted: the rule compares the retained slice, not the window number.
        output, kept, dropped = await RuntimeEngine(
            _RecordingModel(), ToolGateway(client, []), wider
        ).run(CURRENT_INPUT, copy.deepcopy(rows), _noop_emit, prepared_instructions=prepared)
        assert output == "answer"
        assert [item["content"] for item in kept] == [
            "q1",
            "a1",
            "q2",
            "a2",
            CURRENT_INPUT,
            "answer",
        ]
        assert dropped == []

        # The same window handed a shorter history is the same contradiction.
        with pytest.raises(ConfigurationError) as caught:
            await RuntimeEngine(_RecordingModel(), ToolGateway(client, []), wider).run(
                CURRENT_INPUT, copy.deepcopy(rows[:-2]), _noop_emit, prepared_instructions=prepared
            )
        assert caught.value.error.details.field == "history"


def test_p3_ut_19_snapshot_fault_codes_are_pinned_to_the_triggering_condition():
    # H-3: both codes were only ever asserted by type, so swapping them, or
    # renaming one at a single raise site, kept every test green while T7's
    # error_mapper registration and the operator-facing code drifted apart.
    module = _factory_module()
    required = module.AGENT_SNAPSHOT_REQUIRED
    invalid = module.AGENT_SNAPSHOT_INVALID
    assert required != invalid

    def prepared_code(row):
        with pytest.raises(RuntimeFault) as caught:
            _factory_settings().prepare_instructions(
                row, history=[], summary_message=None, customer_memory=None
            )
        return caught.value.code

    # No published Agent snapshot at all (a legacy claimed row, or a snapshot
    # that is not there / not shaped as one): there is nothing to prepare from.
    assert (
        prepared_code({"id": RUN_ID, "tenant_id": "tenant-a", "input": CURRENT_INPUT, "config": {}})
        == required
    )
    assert prepared_code(_row(config={"fingerprint": "t6"})) == required
    assert prepared_code(_row(config={"agent": None})) == required
    assert prepared_code(_row(config={"agent": {"id": str(AGENT_ID), "version": 3}})) == required

    # A snapshot that is present but structurally unusable is a different code,
    # and each shape below reaches it through a different raise site.
    def unusable(**overrides):
        snapshot = {"id": str(AGENT_ID), "version": 3, "config": _agent_config()}
        snapshot.update(overrides)
        return _row(config={"agent": snapshot})

    assert prepared_code(unusable(version="3")) == invalid  # version is not an int
    assert prepared_code(unusable(version=0)) == invalid  # version is not published
    assert prepared_code(unusable(id="not-a-uuid")) == invalid  # agent id is not a UUID
    assert prepared_code(unusable(config=_agent_config(engine={"unknown_key": 1}))) == invalid
    assert prepared_code(unusable(config=_agent_config(engine={"engine_id": "react"}))) == invalid

    # The accepted shapes stay accepted, including the pre-``engine`` snapshot
    # that falls back to the compatibility default.
    assert _factory_settings().prepare_instructions(_row(), history=[]).engine.engine_id == "react"

    # Single definition point: every snapshot code raised by this module comes
    # from the module constants, so a raise site cannot invent a fourth string.
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    raise_site_literals = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "RuntimeFault"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    assert not [code for code in raise_site_literals if code.startswith("agent_snapshot")]
    assert required not in raise_site_literals
    assert invalid not in raise_site_literals


def test_p3_ut_19_preparation_refuses_a_contract_breaking_value_without_echoing_it():
    # H-6: ``InstructionInput`` is a pydantic model, and pydantic's default text
    # repeats the rejected value (its head and tail). Preparation sits on the run
    # path, so that text must never be what a caller sees or logs.
    marker_head = "leak-head-"
    marker_tail = "-leak-tail"
    oversized = marker_head + "x" * 200_000 + marker_tail

    with pytest.raises(ConfigurationError) as caught:
        _factory_settings().prepare_instructions(
            _row(input=oversized), history=[], summary_message=None, customer_memory=None
        )
    assert caught.value.error.details.field == "current_user_input"
    assert caught.value.error.details.operation == "instruction_prepare"
    assert caught.value.__cause__ is None
    for text in (
        str(caught.value),
        repr(caught.value),
        str(caught.value.error),
        repr(caught.value.error),
        repr(caught.value.error.details),
    ):
        assert marker_head not in text
        assert marker_tail not in text

    # A stored row the DTO cannot carry is refused the same way. A datetime is
    # exactly what a repository row can hand over by accident, and pydantic
    # quotes it, so this is the case that must not reach a caller or a log.
    for bad_row in (
        {
            "role": "user",
            "content": "ok",
            "created_at": datetime(2026, 11, 13, 12, 34, 56, tzinfo=UTC),
        },
        {"role": "user", "content": 7},
    ):
        with pytest.raises(ConfigurationError) as caught:
            _factory_settings().prepare_instructions(
                _row(), history=[bad_row], summary_message=None, customer_memory=None
            )
        assert caught.value.error.details.field == "history"
        assert caught.value.__cause__ is None
        text = str(caught.value) + repr(caught.value) + repr(caught.value.error)
        assert "12:34:56" not in text
        assert marker_head not in text
