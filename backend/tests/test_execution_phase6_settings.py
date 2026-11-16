"""Phase 6 T-01: bounded, fail-closed Phase 6 settings (02 FR-16, 03 §7).

Defaults must never enable untrusted execution, network egress, raw parser
samples, or historical event deletion. Every bound is asserted at both
boundaries, and the whole Phase 6 rollout family must stay outside the Runtime
configuration fingerprint (changing a switch must never invalidate a queued Run).
"""

import pytest
from pydantic import ValidationError

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

PHASE6_FAMILY_FIELDS = [
    "execution_untrusted_tenants_enabled",
    "execution_sandbox_required",
    "execution_network_default_deny",
    "execution_credential_grant_ttl_seconds",
    "execution_credential_key_file",
    "execution_outbox_enabled",
    "execution_outbox_batch_size",
    "execution_outbox_poll_seconds",
    "execution_event_retention_days",
    "execution_event_cleanup_enabled",
    "execution_parser_raw_sample_enabled",
    "execution_parser_sample_max_bytes",
    "execution_parser_max_diagnostics_per_minute",
]


def test_phase6_settings_default_to_fail_closed_values():
    settings = Settings(_env_file=None)

    assert settings.execution_untrusted_tenants_enabled is False
    assert settings.execution_sandbox_required is True
    assert settings.execution_network_default_deny is True
    assert settings.execution_credential_grant_ttl_seconds == 300
    assert settings.execution_credential_key_file == __import__("pathlib").Path(
        "data/credentials/execution.key"
    )
    assert settings.execution_outbox_enabled is False
    assert settings.execution_outbox_batch_size == 100
    assert settings.execution_outbox_poll_seconds == 1.0
    assert settings.execution_event_retention_days == 30
    assert settings.execution_event_cleanup_enabled is False
    assert settings.execution_parser_raw_sample_enabled is False
    assert settings.execution_parser_sample_max_bytes == 1024
    assert settings.execution_parser_max_diagnostics_per_minute == 10


def test_phase6_settings_family_is_complete():
    for name in PHASE6_FAMILY_FIELDS:
        assert name in Settings.model_fields
    assert len(PHASE6_FAMILY_FIELDS) == 13


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_credential_grant_ttl_seconds", 29),
        ("execution_credential_grant_ttl_seconds", 3601),
        ("execution_credential_grant_ttl_seconds", 0),
        ("execution_outbox_batch_size", 0),
        ("execution_outbox_batch_size", 1001),
        ("execution_outbox_poll_seconds", 0),
        ("execution_outbox_poll_seconds", -0.5),
        ("execution_outbox_poll_seconds", 300.001),
        ("execution_event_retention_days", 0),
        ("execution_event_retention_days", 3651),
        ("execution_parser_sample_max_bytes", 0),
        ("execution_parser_sample_max_bytes", 4097),
        ("execution_parser_max_diagnostics_per_minute", 0),
        ("execution_parser_max_diagnostics_per_minute", 601),
    ],
)
def test_phase6_settings_reject_values_outside_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_credential_grant_ttl_seconds", 30),
        ("execution_credential_grant_ttl_seconds", 3600),
        ("execution_outbox_batch_size", 1),
        ("execution_outbox_batch_size", 1000),
        ("execution_outbox_poll_seconds", 0.001),
        ("execution_outbox_poll_seconds", 300),
        ("execution_event_retention_days", 1),
        ("execution_event_retention_days", 3650),
        ("execution_parser_sample_max_bytes", 64),
        ("execution_parser_sample_max_bytes", 4096),
        ("execution_parser_max_diagnostics_per_minute", 1),
        ("execution_parser_max_diagnostics_per_minute", 600),
    ],
)
def test_phase6_settings_accept_inclusive_boundaries(field, value):
    assert getattr(Settings(_env_file=None, **{field: value}), field) == value


def test_untrusted_execution_cannot_disable_the_sandbox_or_use_local():
    # 02 FR-4/FR-16: no host fallback and no configuration-only strong sandbox.
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            execution_untrusted_tenants_enabled=True,
            execution_sandbox_required=False,
        )
    assert Settings(_env_file=None, execution_untrusted_tenants_enabled=False).execution_sandbox_required


def test_phase6_rollout_family_stays_out_of_the_runtime_fingerprint():
    excluded = runtime_composition._runtime_fingerprint_exclude_fields()
    assert set(PHASE6_FAMILY_FIELDS) <= excluded

    base = Settings(_env_file=None)
    tuned = Settings(
        _env_file=None,
        execution_outbox_enabled=True,
        execution_outbox_batch_size=250,
        execution_outbox_poll_seconds=2.5,
        execution_event_retention_days=90,
        execution_event_cleanup_enabled=True,
        execution_parser_raw_sample_enabled=True,
        execution_parser_sample_max_bytes=2048,
        execution_parser_max_diagnostics_per_minute=30,
        execution_credential_grant_ttl_seconds=600,
        execution_credential_key_file="/run/secrets/execution.key",
    )
    assert runtime_composition._runtime_fingerprint(base, []) == (
        runtime_composition._runtime_fingerprint(tuned, [])
    )
