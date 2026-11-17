"""Phase 6 T-06: bounded, classified, rate-limited parser diagnostics.

Diagnostics never replace existing Codex/React error behavior; they are an
additional, redacted, bounded record. Raw samples are private and off by
default, continuous failures are rate-limited per Run/category, and no
diagnostic path can recursively emit another diagnostic.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agent_platform.core_platform.agent_execution.adapters.codex.events import (
    CodexEventMapper,
    CodexEventParser,
)
from agent_platform.core_platform.agent_execution.adapters.react.event_mapper import (
    ReactEventMapper,
)
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    ExecutionRequest,
)
from agent_platform.core_platform.agent_execution.events.diagnostics import (
    DIAGNOSTIC_CATEGORIES,
    ParserDiagnostic,
    ParserDiagnosticCollector,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _collector(**overrides):
    records: list[ParserDiagnostic] = []
    values = {"sink": records.append}
    values.update(overrides)
    return ParserDiagnosticCollector(**values), records


def test_categories_are_closed_and_classification_is_explicit():
    assert set(DIAGNOSTIC_CATEGORIES) == {
        "malformed",
        "unknown_schema",
        "unknown_type",
        "size_limit",
        "critical_terminal",
    }
    collector, records = _collector()
    for category in DIAGNOSTIC_CATEGORIES:
        collector.report(
            category,
            run_id=uuid4(),
            engine_id="codex",
            protocol_id="cli_exec",
            adapter_version="v1",
        )
    assert {record.category for record in records} == set(DIAGNOSTIC_CATEGORIES)
    with pytest.raises(ValueError):
        collector.report("made_up", run_id=uuid4(), engine_id="codex", protocol_id="cli_exec")


def test_raw_samples_are_off_by_default():
    collector, _records = _collector()
    diag = collector.report(
        "malformed",
        run_id=uuid4(),
        engine_id="codex",
        protocol_id="cli_exec",
        sample='{"leak":"secret-value"}',
    )
    assert diag is not None and diag.sample is None


def test_enabled_samples_are_redacted_and_byte_bounded():
    collector, _records = _collector(
        raw_samples_enabled=True,
        max_sample_bytes=24,
        redact=lambda value: value.replace("secret-value", "[redacted]"),
    )
    diag = collector.report(
        "malformed",
        run_id=uuid4(),
        engine_id="codex",
        protocol_id="cli_exec",
        sample='{"token":"secret-value","pad":"' + "x" * 200 + '"}',
    )
    assert diag is not None
    assert "secret-value" not in diag.sample
    assert len(diag.sample.encode("utf-8")) <= 24


def test_rate_limit_is_per_run_and_category_with_bounded_counters():
    clock = _Clock()
    collector, _records = _collector(max_per_minute=2, clock=clock)
    run_id = uuid4()
    assert collector.report("malformed", run_id=run_id, engine_id="c", protocol_id="p") is not None
    assert collector.report("malformed", run_id=run_id, engine_id="c", protocol_id="p") is not None
    assert collector.report("malformed", run_id=run_id, engine_id="c", protocol_id="p") is None
    counters = collector.counters()
    assert counters["malformed"] == 2
    assert counters["suppressed"] == 1

    # A different category and a different Run still have their own budget.
    other = uuid4()
    assert (
        collector.report("unknown_type", run_id=run_id, engine_id="c", protocol_id="p") is not None
    )
    assert collector.report("malformed", run_id=other, engine_id="c", protocol_id="p") is not None

    clock.now += 61.0
    assert collector.report("malformed", run_id=run_id, engine_id="c", protocol_id="p") is not None


def test_sink_failure_is_swallowed_without_recursive_diagnostics():
    def broken_sink(_diagnostic):
        raise RuntimeError("sink down")

    collector = ParserDiagnosticCollector(sink=broken_sink, max_per_minute=1)
    # One report, one attempt: the failure cannot trigger a second diagnostic.
    diag = collector.report("malformed", run_id=uuid4(), engine_id="c", protocol_id="p")
    assert diag is not None
    counters = collector.counters()
    assert counters["malformed"] == 1


def test_parser_classifies_size_and_malformed_without_losing_its_error():
    collector, records = _collector()
    parser = CodexEventParser(
        max_line_bytes=32,
        on_diagnostic=lambda category, location: collector.report(
            category, engine_id="codex", protocol_id="cli_exec", location=location
        ),
    )

    with pytest.raises(ValueError, match="size limit"):
        parser.parse_lines([b'{"type":"x","payload":"' + b"a" * 40 + b'"}\n'])
    assert records[-1].category == "size_limit"

    with pytest.raises(ValueError, match="Malformed"):
        parser.parse_lines([b"{not-json}\n"])
    assert records[-1].category == "malformed"

    with pytest.raises(ValueError, match="Malformed"):
        parser.parse_lines([b'{"turn.completed": broken}\n'])
    assert records[-1].category == "critical_terminal"


def _codex_mapper(collector, known=("turn.completed",)):
    return CodexEventMapper(
        execution_id=uuid4(),
        engine_id="codex",
        protocol_id="cli_exec",
        adapter_version="v1",
        engine_session_id=None,
        diagnostics=collector,
        known_event_types=frozenset(known),
    )


def test_codex_mapper_reports_unknown_type_but_preserves_the_event():
    collector, records = _collector()
    mapper = _codex_mapper(collector)
    event = mapper.map_lines([b'{"type":"provider.new.event","x":1}\n'], max_line_bytes=1024)[0]
    assert event.event_type.startswith("codex.")
    assert records[-1].category == "unknown_type"


def test_codex_mapper_reports_size_limit_when_payload_is_truncated():
    collector, records = _collector()
    mapper = _codex_mapper(collector, known=("huge",))
    huge = "x" * (40 * 1024)
    event = mapper.map_lines(
        [('{"type":"huge","pad":"' + huge + '"}').encode()], max_line_bytes=1024 * 1024
    )[0]
    assert event.payload["truncated"] is True
    assert records[-1].category == "size_limit"


def test_codex_malformed_line_still_raises_protocol_error_with_diagnostic():
    collector, records = _collector()
    mapper = _codex_mapper(collector)
    with pytest.raises(AdapterExecutionError):
        mapper.map_lines([b"{not-json}\n"], max_line_bytes=1024)
    assert any(record.category in {"malformed", "critical_terminal"} for record in records)


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=uuid4(),
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        tenant_id="t",
        agent_id=uuid4(),
        input="x",
        config={},
    )


def test_react_mapper_reports_malformed_envelope_collision_and_still_fails_closed():
    collector, records = _collector()
    mapper = ReactEventMapper(_request(), diagnostics=collector)
    with pytest.raises(AdapterExecutionError):
        mapper.map("extension.note", {"event_id": str(uuid4())})
    assert records[-1].category == "malformed"


def test_react_mapper_still_maps_valid_events():
    collector, records = _collector()
    mapper = ReactEventMapper(_request(), diagnostics=collector)
    event = mapper.map("extension.note", {"note": "ok"})
    assert event.payload == {"note": "ok"}
    assert records == []
    assert event.timestamp.tzinfo == UTC and isinstance(event.timestamp, datetime)
