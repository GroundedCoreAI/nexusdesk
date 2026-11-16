"""Phase 5 settings gates and fingerprint exclusions (02 FR-12, 04 P5-UT-18)."""

import pytest
from pydantic import ValidationError

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.core_platform.platform_services.platform_settings.settings import (
    Settings,
)

_BASE = {
    "_env_file": None,
    "database_url": "postgresql+asyncpg://agent:agent@127.0.0.1/none",
}


def _settings(**overrides) -> Settings:
    return Settings(**{**_BASE, **overrides})


def test_every_codex_switch_defaults_off_and_every_allowlist_defaults_empty() -> None:
    settings = _settings()

    assert settings.codex_cli_enabled is False
    assert settings.codex_app_server_enabled is False
    assert settings.codex_stage_a_verified is False
    assert settings.codex_session_persistence_enabled is False
    assert settings.codex_allowed_versions == ()
    assert settings.codex_trusted_tenants == ()


def test_app_server_requires_cli_and_a_verified_stage_a() -> None:
    with pytest.raises(ValidationError, match="requires codex_cli_enabled"):
        _settings(codex_app_server_enabled=True)

    with pytest.raises(ValidationError, match="requires codex_stage_a_verified"):
        _settings(codex_app_server_enabled=True, codex_cli_enabled=True)

    # Both prerequisites present is the only accepted pairing.
    settings = _settings(
        codex_app_server_enabled=True,
        codex_cli_enabled=True,
        codex_stage_a_verified=True,
    )
    assert settings.codex_app_server_enabled is True


def test_stage_a_verification_alone_does_not_enable_anything() -> None:
    settings = _settings(codex_stage_a_verified=True)

    assert settings.codex_cli_enabled is False
    assert settings.codex_app_server_enabled is False


def test_codex_settings_never_change_the_runtime_fingerprint() -> None:
    """A rollout flip must not force queued Runs to ``configuration_changed``."""
    baseline = runtime_composition._runtime_fingerprint(_settings(), [])
    flipped = runtime_composition._runtime_fingerprint(
        _settings(
            codex_cli_enabled=True,
            codex_stage_a_verified=True,
            codex_allowed_versions=("0.169.0",),
            codex_trusted_tenants=("tenant-a",),
        ),
        [],
    )

    assert baseline == flipped
    excluded = runtime_composition._runtime_fingerprint_exclude_fields()
    codex_fields = {name for name in Settings.model_fields if name.startswith("codex_")}
    assert codex_fields
    assert codex_fields <= excluded
