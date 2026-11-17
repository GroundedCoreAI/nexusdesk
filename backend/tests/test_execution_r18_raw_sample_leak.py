"""Phase 6 R-18(b): enabled raw samples fail closed without a redactor.

When raw_samples_enabled=True but no redactor callback is supplied, the
collector must NOT return the raw sample verbatim. It either redacts or drops
the sample; canaries are never retained verbatim.
"""
from uuid import uuid4

from agent_platform.core_platform.agent_execution.events.diagnostics import (
    ParserDiagnosticCollector,
)


def test_enabled_raw_sample_without_redactor_is_not_retained_verbatim():
    canary = "secret-canary-value"
    collector = ParserDiagnosticCollector(
        raw_samples_enabled=True,
        max_sample_bytes=256,
        redact=None,  # no redactor supplied
    )
    diag = collector.report(
        "malformed", run_id=uuid4(), engine_id="codex", protocol_id="cli_exec",
        sample=f'{{"token":"{canary}"}}',
    )
    assert diag is not None
    # The canary must never be retained verbatim without a redactor.
    assert diag.sample is None or canary not in diag.sample


def test_enabled_raw_sample_with_redactor_is_redacted():
    canary = "secret-canary-value"
    collector = ParserDiagnosticCollector(
        raw_samples_enabled=True,
        max_sample_bytes=256,
        redact=lambda value: value.replace(canary, "[redacted]"),
    )
    diag = collector.report(
        "malformed", run_id=uuid4(), engine_id="codex", protocol_id="cli_exec",
        sample=f'{{"token":"{canary}"}}',
    )
    assert diag is not None
    assert diag.sample is not None
    assert canary not in diag.sample
