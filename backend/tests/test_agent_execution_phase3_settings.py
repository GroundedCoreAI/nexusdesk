import pytest
from pydantic import ValidationError

from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


def test_phase3_settings_default_to_safe_rollout_values():
    settings = Settings(_env_file=None)

    assert settings.execution_phase3_enabled is False
    assert settings.execution_capability_policy_version == "v1"
    assert settings.execution_capability_probe_timeout_seconds == 2.0
    assert settings.execution_capability_policy_timeout_seconds == 2.0
    assert settings.execution_capability_probe_cache_seconds == 30
    assert settings.execution_capability_policy_cache_seconds == 30
    assert settings.execution_capability_probe_max_concurrency == 4
    assert settings.execution_capability_cache_capacity == 512
    assert settings.execution_capability_cache_retry_seconds == 5.0
    assert settings.execution_capability_warm_refresh_seconds == 10.0
    assert settings.execution_capability_deployment_identity == "default"
    assert settings.execution_snapshot_max_bytes == 65536


def test_phase3_settings_accept_constructor_overrides():
    settings = Settings(
        _env_file=None,
        execution_phase3_enabled=True,
        execution_capability_policy_version="v2",
        execution_capability_probe_timeout_seconds=10.0,
        execution_capability_policy_timeout_seconds=4.5,
        execution_capability_probe_cache_seconds=1,
        execution_capability_policy_cache_seconds=300,
        execution_capability_probe_max_concurrency=32,
        execution_capability_cache_capacity=1024,
        execution_capability_cache_retry_seconds=60.0,
        execution_capability_warm_refresh_seconds=0.5,
        execution_capability_deployment_identity="node-a.1",
        execution_snapshot_max_bytes=262144,
    )

    assert settings.execution_phase3_enabled is True
    assert settings.execution_capability_policy_version == "v2"
    assert settings.execution_capability_probe_timeout_seconds == 10.0
    assert settings.execution_capability_policy_timeout_seconds == 4.5
    assert settings.execution_capability_probe_cache_seconds == 1
    assert settings.execution_capability_policy_cache_seconds == 300
    assert settings.execution_capability_probe_max_concurrency == 32
    assert settings.execution_capability_cache_capacity == 1024
    assert settings.execution_capability_cache_retry_seconds == 60.0
    assert settings.execution_capability_warm_refresh_seconds == 0.5
    assert settings.execution_capability_deployment_identity == "node-a.1"
    assert settings.execution_snapshot_max_bytes == 262144


def test_phase3_settings_use_agent_environment_prefix(monkeypatch):
    overrides = {
        "AGENT_EXECUTION_PHASE3_ENABLED": "true",
        "AGENT_EXECUTION_CAPABILITY_POLICY_VERSION": "v3",
        "AGENT_EXECUTION_CAPABILITY_PROBE_TIMEOUT_SECONDS": "1.25",
        "AGENT_EXECUTION_CAPABILITY_POLICY_TIMEOUT_SECONDS": "1.5",
        "AGENT_EXECUTION_CAPABILITY_PROBE_CACHE_SECONDS": "12",
        "AGENT_EXECUTION_CAPABILITY_POLICY_CACHE_SECONDS": "13",
        "AGENT_EXECUTION_CAPABILITY_PROBE_MAX_CONCURRENCY": "7",
        "AGENT_EXECUTION_CAPABILITY_CACHE_CAPACITY": "64",
        "AGENT_EXECUTION_CAPABILITY_CACHE_RETRY_SECONDS": "9.5",
        "AGENT_EXECUTION_CAPABILITY_WARM_REFRESH_SECONDS": "11",
        "AGENT_EXECUTION_CAPABILITY_DEPLOYMENT_IDENTITY": "edge-01",
        "AGENT_EXECUTION_SNAPSHOT_MAX_BYTES": "4096",
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)

    assert settings.execution_phase3_enabled is True
    assert settings.execution_capability_policy_version == "v3"
    assert settings.execution_capability_probe_timeout_seconds == 1.25
    assert settings.execution_capability_policy_timeout_seconds == 1.5
    assert settings.execution_capability_probe_cache_seconds == 12
    assert settings.execution_capability_policy_cache_seconds == 13
    assert settings.execution_capability_probe_max_concurrency == 7
    assert settings.execution_capability_cache_capacity == 64
    assert settings.execution_capability_cache_retry_seconds == 9.5
    assert settings.execution_capability_warm_refresh_seconds == 11.0
    assert settings.execution_capability_deployment_identity == "edge-01"
    assert settings.execution_snapshot_max_bytes == 4096


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_capability_probe_timeout_seconds", 0),
        ("execution_capability_probe_timeout_seconds", -0.1),
        ("execution_capability_probe_timeout_seconds", 10.001),
        ("execution_capability_policy_timeout_seconds", 0),
        ("execution_capability_policy_timeout_seconds", -0.1),
        ("execution_capability_policy_timeout_seconds", 10.001),
        # R-19: TTL lower bound is strictly positive; 0 is no longer a legal
        # "disable caching" value because the caches themselves reject it.
        ("execution_capability_probe_cache_seconds", 0),
        ("execution_capability_probe_cache_seconds", -1),
        ("execution_capability_probe_cache_seconds", 301),
        ("execution_capability_policy_cache_seconds", 0),
        ("execution_capability_policy_cache_seconds", -1),
        ("execution_capability_policy_cache_seconds", 301),
        ("execution_capability_probe_max_concurrency", 0),
        ("execution_capability_probe_max_concurrency", 33),
        ("execution_capability_cache_capacity", 15),
        ("execution_capability_cache_capacity", 100001),
        ("execution_capability_cache_retry_seconds", 0),
        ("execution_capability_cache_retry_seconds", 60.001),
        ("execution_capability_warm_refresh_seconds", 0),
        ("execution_capability_warm_refresh_seconds", 300.001),
        ("execution_capability_deployment_identity", ""),
        ("execution_capability_deployment_identity", "Node A"),
        ("execution_capability_deployment_identity", "_lead"),
        ("execution_capability_deployment_identity", "trail-."),
        # R-20: the policy version grammar is the contracts' AdapterVersion.
        ("execution_capability_policy_version", ""),
        ("execution_capability_policy_version", "1"),
        ("execution_capability_policy_version", "v0"),
        ("execution_capability_policy_version", "v01"),
        ("execution_capability_policy_version", "V1"),
        ("execution_snapshot_max_bytes", 4095),
        ("execution_snapshot_max_bytes", 262145),
    ],
)
def test_phase3_settings_reject_values_outside_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_capability_probe_timeout_seconds", 0.001),
        ("execution_capability_probe_timeout_seconds", 10),
        ("execution_capability_policy_timeout_seconds", 0.001),
        ("execution_capability_policy_timeout_seconds", 10),
        ("execution_capability_probe_cache_seconds", 1),
        ("execution_capability_probe_cache_seconds", 300),
        ("execution_capability_policy_cache_seconds", 1),
        ("execution_capability_policy_cache_seconds", 300),
        ("execution_capability_probe_max_concurrency", 1),
        ("execution_capability_probe_max_concurrency", 32),
        ("execution_capability_cache_capacity", 16),
        ("execution_capability_cache_capacity", 100000),
        ("execution_capability_cache_retry_seconds", 0.001),
        ("execution_capability_cache_retry_seconds", 60),
        ("execution_capability_warm_refresh_seconds", 0.001),
        # The upper cadence bound only conflicts with the TTLs while Phase 3
        # is enabled; off-state deployments keep accepting it (tested below).
        ("execution_capability_warm_refresh_seconds", 300),
        ("execution_capability_deployment_identity", "default"),
        ("execution_capability_deployment_identity", "node-a.1_b"),
        ("execution_capability_policy_version", "v1"),
        ("execution_capability_policy_version", "v10"),
        ("execution_snapshot_max_bytes", 4096),
        ("execution_snapshot_max_bytes", 262144),
    ],
)
def test_phase3_settings_accept_inclusive_boundaries(field, value):
    settings = Settings(_env_file=None, **{field: value})

    assert getattr(settings, field) == value


def test_phase3_warm_refresh_must_stay_below_the_shortest_ttl_when_enabled():
    # Equal to the shortest TTL is rejected: the warmer must fire before any
    # entry expires, and the shortest of the two caches bounds the cadence.
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            execution_phase3_enabled=True,
            execution_capability_probe_cache_seconds=30,
            execution_capability_policy_cache_seconds=10,
            execution_capability_warm_refresh_seconds=10,
        )
    # Above the shortest TTL is rejected even when it fits the longer cache.
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            execution_phase3_enabled=True,
            execution_capability_warm_refresh_seconds=31,
        )
    # Strictly below the shortest TTL is accepted.
    settings = Settings(
        _env_file=None,
        execution_phase3_enabled=True,
        execution_capability_probe_cache_seconds=30,
        execution_capability_policy_cache_seconds=10,
        execution_capability_warm_refresh_seconds=9.5,
    )
    assert settings.execution_capability_warm_refresh_seconds == 9.5
    # The all-default cadence is compatible with enabling Phase 3.
    assert Settings(_env_file=None, execution_phase3_enabled=True).execution_phase3_enabled is True


def test_phase3_warm_refresh_window_is_unconstrained_when_disabled():
    # Off-state deployments keep constructing with any in-bounds cadence so
    # operators can stage values before flipping the rollout switch.
    settings = Settings(
        _env_file=None,
        execution_phase3_enabled=False,
        execution_capability_probe_cache_seconds=30,
        execution_capability_policy_cache_seconds=30,
        execution_capability_warm_refresh_seconds=300,
    )
    assert settings.execution_capability_warm_refresh_seconds == 300.0
