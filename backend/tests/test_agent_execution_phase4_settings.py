"""Phase 4 FR-10 settings: bounds, enabled-state cross-validation, fingerprint exclusion.

Mirrors the Phase 3 settings test conventions (08 R-5): defaults, constructor
overrides, ``AGENT_`` env overrides, per-field bound rejection/acceptance, the
enabled-only cross-validation of 03 §5.1, and the R-8 rule that the whole
Phase 4 family stays out of the runtime configuration fingerprint.
"""

import pytest
from pydantic import ValidationError

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

PHASE4_FAMILY_FIELDS = [
    name
    for name in Settings.model_fields
    if name.startswith(
        (
            "execution_runtime_host_",
            "execution_workdir_",
            "execution_process_",
            "execution_resource_",
        )
    )
    or name == "execution_sandbox_provider"
]


def _phase4_fields():
    """Field-by-field alternates that stay internally valid for the validators."""
    return {
        "execution_runtime_host_enabled": True,
        "execution_runtime_host_id": "runtime-worker-02",
        "execution_workdir_root": "/srv/agent-execution",
        "execution_sandbox_provider": "local",
        "execution_resource_enforcement_required": False,
        "execution_process_cancel_grace_seconds": 12.5,
        "execution_process_kill_timeout_seconds": 20.0,
        "execution_process_reconcile_interval_seconds": 30.0,
        "execution_process_wall_timeout_seconds": 1800,
        "execution_process_output_max_bytes": 4_194_304,
        "execution_resource_cpu_seconds": 120,
        "execution_resource_memory_bytes": 1_073_741_824,
        "execution_resource_max_processes": 32,
        "execution_workdir_max_bytes": 2_147_483_648,
        "execution_workdir_max_file_bytes": 268_435_456,
        "execution_resource_sample_interval_seconds": 2.5,
        "execution_workdir_retention_seconds": 3600,
        "execution_workdir_failed_retention_seconds": 172_800,
        "execution_workdir_cleanup_interval_seconds": 120.0,
    }


def test_phase4_settings_family_has_nineteen_fr10_keys():
    # 02 FR-10 lists exactly nineteen keys; a missing or renamed key breaks traceability.
    assert len(PHASE4_FAMILY_FIELDS) == 19
    assert set(PHASE4_FAMILY_FIELDS) == set(_phase4_fields())


def test_phase4_settings_default_to_safe_rollout_values():
    settings = Settings(_env_file=None)

    assert settings.execution_runtime_host_enabled is False
    assert settings.execution_runtime_host_id == ""
    assert str(settings.execution_workdir_root) == "data/execution"
    assert settings.execution_sandbox_provider == "local"
    assert settings.execution_resource_enforcement_required is True
    assert settings.execution_process_cancel_grace_seconds == 5.0
    assert settings.execution_process_kill_timeout_seconds == 5.0
    assert settings.execution_process_reconcile_interval_seconds == 5.0
    assert settings.execution_process_wall_timeout_seconds == 900
    assert settings.execution_process_output_max_bytes == 1_048_576
    assert settings.execution_resource_cpu_seconds == 600
    assert settings.execution_resource_memory_bytes == 536_870_912
    assert settings.execution_resource_max_processes == 64
    assert settings.execution_workdir_max_bytes == 1_073_741_824
    assert settings.execution_workdir_max_file_bytes == 134_217_728
    assert settings.execution_resource_sample_interval_seconds == 1.0
    assert settings.execution_workdir_retention_seconds == 86_400
    assert settings.execution_workdir_failed_retention_seconds == 604_800
    assert settings.execution_workdir_cleanup_interval_seconds == 60.0


def test_phase4_settings_accept_constructor_overrides():
    settings = Settings(_env_file=None, **_phase4_fields())

    assert settings.execution_runtime_host_enabled is True
    assert settings.execution_runtime_host_id == "runtime-worker-02"
    assert str(settings.execution_workdir_root) == "/srv/agent-execution"
    assert settings.execution_resource_enforcement_required is False
    assert settings.execution_process_cancel_grace_seconds == 12.5
    assert settings.execution_process_wall_timeout_seconds == 1800
    assert settings.execution_workdir_cleanup_interval_seconds == 120.0


def test_phase4_settings_use_agent_environment_prefix(monkeypatch):
    overrides = {
        "AGENT_EXECUTION_RUNTIME_HOST_ENABLED": "true",
        "AGENT_EXECUTION_RUNTIME_HOST_ID": "edge-01",
        "AGENT_EXECUTION_WORKDIR_ROOT": "/data/execution",
        "AGENT_EXECUTION_SANDBOX_PROVIDER": "local",
        "AGENT_EXECUTION_RESOURCE_ENFORCEMENT_REQUIRED": "false",
        "AGENT_EXECUTION_PROCESS_CANCEL_GRACE_SECONDS": "7.5",
        "AGENT_EXECUTION_PROCESS_KILL_TIMEOUT_SECONDS": "8.5",
        "AGENT_EXECUTION_PROCESS_RECONCILE_INTERVAL_SECONDS": "9.5",
        "AGENT_EXECUTION_PROCESS_WALL_TIMEOUT_SECONDS": "1200",
        "AGENT_EXECUTION_PROCESS_OUTPUT_MAX_BYTES": "2097152",
        "AGENT_EXECUTION_RESOURCE_CPU_SECONDS": "300",
        "AGENT_EXECUTION_RESOURCE_MEMORY_BYTES": "1073741824",
        "AGENT_EXECUTION_RESOURCE_MAX_PROCESSES": "32",
        "AGENT_EXECUTION_WORKDIR_MAX_BYTES": "2147483648",
        "AGENT_EXECUTION_WORKDIR_MAX_FILE_BYTES": "268435456",
        "AGENT_EXECUTION_RESOURCE_SAMPLE_INTERVAL_SECONDS": "2.0",
        "AGENT_EXECUTION_WORKDIR_RETENTION_SECONDS": "3600",
        "AGENT_EXECUTION_WORKDIR_FAILED_RETENTION_SECONDS": "172800",
        "AGENT_EXECUTION_WORKDIR_CLEANUP_INTERVAL_SECONDS": "120",
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)

    assert settings.execution_runtime_host_enabled is True
    assert settings.execution_runtime_host_id == "edge-01"
    assert str(settings.execution_workdir_root) == "/data/execution"
    assert settings.execution_resource_enforcement_required is False
    assert settings.execution_process_cancel_grace_seconds == 7.5
    assert settings.execution_process_wall_timeout_seconds == 1200
    assert settings.execution_resource_memory_bytes == 1_073_741_824
    assert settings.execution_workdir_cleanup_interval_seconds == 120.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # Intervals must be strictly positive and bounded (03 §5.1 first bullet).
        ("execution_process_cancel_grace_seconds", 0),
        ("execution_process_cancel_grace_seconds", -0.1),
        ("execution_process_cancel_grace_seconds", 30.001),
        ("execution_process_kill_timeout_seconds", 0),
        ("execution_process_kill_timeout_seconds", 30.001),
        ("execution_process_reconcile_interval_seconds", 0),
        ("execution_process_reconcile_interval_seconds", 300.001),
        ("execution_resource_sample_interval_seconds", 0),
        ("execution_resource_sample_interval_seconds", 300.001),
        ("execution_workdir_cleanup_interval_seconds", 0),
        ("execution_workdir_cleanup_interval_seconds", 86400.001),
        # Wall/CPU/memory/PID/disk/output limits may never be zero or negative
        # (03 §5.1: "不得为 0 或负数").
        ("execution_process_wall_timeout_seconds", 0),
        ("execution_process_wall_timeout_seconds", -1),
        ("execution_process_wall_timeout_seconds", 86_401),
        ("execution_process_output_max_bytes", 0),
        ("execution_process_output_max_bytes", 268_435_457),
        ("execution_resource_cpu_seconds", 0),
        ("execution_resource_cpu_seconds", 86_401),
        ("execution_resource_memory_bytes", 0),
        ("execution_resource_memory_bytes", 68_719_476_737),
        ("execution_resource_max_processes", 0),
        ("execution_resource_max_processes", 4097),
        ("execution_workdir_max_bytes", 0),
        ("execution_workdir_max_bytes", 1_099_511_627_777),
        ("execution_workdir_max_file_bytes", 0),
        ("execution_workdir_max_file_bytes", 1_099_511_627_777),
        # Retention windows are bounded and nonnegative; negative is rejected.
        ("execution_workdir_retention_seconds", -1),
        ("execution_workdir_retention_seconds", 7_776_001),
        ("execution_workdir_failed_retention_seconds", -1),
        ("execution_workdir_failed_retention_seconds", 31_536_001),
        # Phase 4 ships the Local Provider only: any other value is rejected
        # by type (02 FR-8 fail-closed gate).
        ("execution_sandbox_provider", "gvisor"),
        ("execution_sandbox_provider", "docker"),
        ("execution_sandbox_provider", ""),
        # host_id is length-bounded even while disabled.
        ("execution_runtime_host_id", "x" * 201),
    ],
)
def test_phase4_settings_reject_values_outside_bounds(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_process_cancel_grace_seconds", 0.001),
        ("execution_process_cancel_grace_seconds", 30),
        ("execution_process_kill_timeout_seconds", 0.001),
        ("execution_process_kill_timeout_seconds", 30),
        ("execution_process_reconcile_interval_seconds", 0.001),
        ("execution_process_reconcile_interval_seconds", 300),
        ("execution_resource_sample_interval_seconds", 0.001),
        ("execution_resource_sample_interval_seconds", 300),
        ("execution_workdir_cleanup_interval_seconds", 0.001),
        ("execution_workdir_cleanup_interval_seconds", 86_400),
        ("execution_process_wall_timeout_seconds", 1),
        ("execution_process_wall_timeout_seconds", 86_400),
        ("execution_process_output_max_bytes", 1),
        ("execution_process_output_max_bytes", 268_435_456),
        ("execution_resource_cpu_seconds", 1),
        ("execution_resource_cpu_seconds", 86_400),
        ("execution_resource_memory_bytes", 1),
        ("execution_resource_memory_bytes", 68_719_476_736),
        ("execution_resource_max_processes", 1),
        ("execution_resource_max_processes", 4096),
        ("execution_workdir_max_bytes", 1),
        ("execution_workdir_max_bytes", 1_099_511_627_776),
        ("execution_workdir_max_file_bytes", 1),
        ("execution_workdir_max_file_bytes", 1_099_511_627_776),
        # Zero retention is legal: it means "clean as soon as the decision lands".
        ("execution_workdir_retention_seconds", 0),
        ("execution_workdir_retention_seconds", 7_776_000),
        ("execution_workdir_failed_retention_seconds", 0),
        ("execution_workdir_failed_retention_seconds", 31_536_000),
    ],
)
def test_phase4_settings_accept_inclusive_boundaries(field, value):
    settings = Settings(_env_file=None, **{field: value})

    assert getattr(settings, field) == value


def test_phase4_enabling_the_host_requires_a_slug_shaped_host_id():
    # 03 §5.1: nonempty execution_runtime_host_id while enabled.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, execution_runtime_host_enabled=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, execution_runtime_host_enabled=True, execution_runtime_host_id=" ")
    # The deployment slug grammar is enforced only in the enabled state.
    for bad in ("Runtime-Worker", "node..1", "-lead", "trail-", "node 1"):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                execution_runtime_host_enabled=True,
                execution_runtime_host_id=bad,
            )
    settings = Settings(
        _env_file=None,
        execution_runtime_host_enabled=True,
        execution_runtime_host_id="runtime-worker.01_a-b",
    )
    assert settings.execution_runtime_host_enabled is True


def test_phase4_off_state_accepts_unstaged_host_identity():
    # Operators stage values before flipping the switch (Phase 3 precedent): with
    # the Host disabled the id may stay empty or not yet match the grammar.
    settings = Settings(_env_file=None, execution_runtime_host_enabled=False)
    assert settings.execution_runtime_host_id == ""
    staged = Settings(_env_file=None, execution_runtime_host_id="staging-node")
    assert staged.execution_runtime_host_enabled is False


def test_phase4_enforcement_required_default_is_fail_closed():
    # Defaults are the fail-closed shape: enforcement required with the local
    # Provider; unsupported platforms are rejected at composition (T11/T12).
    settings = Settings(_env_file=None)
    assert settings.execution_resource_enforcement_required is True
    assert settings.execution_sandbox_provider == "local"


def test_phase4_settings_family_is_named_by_the_fingerprint_exclude_set():
    # R-8 rule, not coincidence: every Phase 4 field is listed by the prefix rule.
    excluded = runtime_composition._runtime_fingerprint_exclude_fields()

    assert excluded >= set(PHASE4_FAMILY_FIELDS)


def test_phase4_settings_never_move_the_runtime_fingerprint():
    base = Settings(_env_file=None)
    for field, value in _phase4_fields().items():
        updates = {field: value}
        if field == "execution_runtime_host_enabled":
            # The cross-validator pairs the switch with a valid id; enabling
            # without one is rejected above and never reaches composition.
            updates["execution_runtime_host_id"] = "runtime-worker-02"
        if field == "execution_runtime_host_id":
            updates["execution_runtime_host_enabled"] = True
        tuned = Settings(_env_file=None, **updates)
        assert runtime_composition._runtime_fingerprint(base, []) == (
            runtime_composition._runtime_fingerprint(tuned, [])
        ), field

    everything = Settings(_env_file=None, **_phase4_fields())
    assert runtime_composition._runtime_fingerprint(base, []) == (
        runtime_composition._runtime_fingerprint(everything, [])
    )
