"""Phase 7 Task 3 observability aggregation — local unit tests (no database).

Covers the pure section builders the D3 injection source switch picks
between: the PG integration tests always see the detail path (migration
0041 is part of the test baseline), so the events-mode degrade path is
pinned here, along with the shared rate convention (None on a zero
denominator).
"""

from agent_platform.core_platform.platform_services.observability.service import (
    _injection_from_detail,
    _injection_from_events,
    _rate,
)


def test_rate_is_none_without_denominator():
    assert _rate(3, 4) == 0.75
    assert _rate(0, 0) is None
    assert _rate(5, 0) is None


def test_injection_detail_source_splits_all_four_sections():
    row = {"logged": 5, "runs": 2, "flag": 1, "profile": 2, "preference": 1, "event": 1}
    section = _injection_from_detail(row)
    assert section["source"] == "detail"
    assert section["avg_items"] == 2.5
    assert section["by_section"] == {"flag": 1, "profile": 2, "preference": 1, "event": 1}


def test_injection_detail_without_runs_has_no_average():
    row = {"logged": 0, "runs": 0, "flag": 0, "profile": 0, "preference": 0, "event": 0}
    section = _injection_from_detail(row)
    assert section["avg_items"] is None
    assert section["by_section"] == {"flag": 0, "profile": 0, "preference": 0, "event": 0}


def test_injection_events_degrade_lumps_profile_and_preference():
    """The counts-only memory.injected event carries one ``items`` number for
    profile+preference, so the degrade path cannot split them — both stay
    None while flag/event remain exact and avg_items covers all sections."""
    row = {"runs": 2, "items": 3, "flags": 1, "events": 2}
    section = _injection_from_events(row)
    assert section["source"] == "events"
    assert section["avg_items"] == 3.0  # (3 items + 1 flag + 2 events) / 2 runs
    assert section["by_section"] == {"flag": 1, "profile": None, "preference": None, "event": 2}


def test_injection_events_without_runs_has_no_average():
    row = {"runs": 0, "items": 0, "flags": 0, "events": 0}
    section = _injection_from_events(row)
    assert section["avg_items"] is None
