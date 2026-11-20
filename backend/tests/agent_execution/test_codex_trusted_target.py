"""P4/G4: the Codex CLI trusted target stays fail-closed unless fully enabled."""

import pytest

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.core_platform.agent_execution.adapters.codex.cli_exec import (
    CODEX_CLI_EXECUTABLE_ID,
    CODEX_CLI_FIXED_ARGV,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessSpec,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.process_runner import UntrustedTargetError
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


def _enabled_settings(**overrides):
    values = {
        "execution_runtime_host_enabled": True,
        "execution_runtime_host_id": "runtime-01",
        "codex_cli_enabled": True,
        "codex_stage_a_verified": True,
        "codex_allowed_versions": ("0.169.0",),
        "codex_trusted_tenants": ("local",),
        "codex_cli_executable_path": "/opt/codex/bin/codex",
        # D-3: a fully staged Codex lane needs a Node-sized address-space ceiling
        # (>= 1 GiB); the generic 512 MiB default kills V8 with SIGTRAP.
        "execution_resource_memory_bytes": 2_147_483_648,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _spec(argv):
    return ProcessSpec(
        executable_id=CODEX_CLI_EXECUTABLE_ID,
        argv=argv,
        workdir_relative_path="run",
        resource_policy=ResourcePolicy(
            cpu_seconds=10,
            memory_bytes=1024,
            max_processes=8,
            workdir_total_bytes=4096,
            workdir_file_bytes=1024,
            wall_seconds=10,
            output_max_bytes_per_stream=1024,
        ),
    )


def test_default_registers_no_trusted_target():
    assert Settings(_env_file=None).codex_cli_executable_path == ""
    assert runtime_composition._codex_trusted_targets(Settings(_env_file=None)) == ()
    subsystem = runtime_composition._build_execution_runtime_subsystem(
        Settings(_env_file=None), object()
    )
    assert subsystem is None


def test_partial_gate_registers_no_trusted_target():
    for overrides in (
        {"codex_cli_enabled": False},
        {"codex_stage_a_verified": False},
        {"codex_allowed_versions": ()},
        {"codex_trusted_tenants": ()},
        {"codex_cli_executable_path": ""},
        {"execution_runtime_host_enabled": False},
    ):
        settings = _enabled_settings(**overrides)
        assert runtime_composition._codex_trusted_targets(settings) == ()


def test_roll_back_to_disabled_gate_registers_no_trusted_target():
    enabled = _enabled_settings()
    rolled_back = _enabled_settings(codex_cli_enabled=False, codex_cli_executable_path="")
    subsystem = runtime_composition._build_execution_runtime_subsystem(enabled, object())
    assert subsystem is not None
    assert subsystem.host._runner._registry.executable_ids == frozenset({CODEX_CLI_EXECUTABLE_ID})
    rolled_back_subsystem = runtime_composition._build_execution_runtime_subsystem(
        rolled_back, object()
    )
    assert rolled_back_subsystem.host._runner._registry.executable_ids == frozenset()


def test_relative_executable_path_is_rejected_before_registration():
    with pytest.raises(ValueError, match="absolute"):
        _enabled_settings(codex_cli_executable_path="bin/codex")


def test_descriptor_pins_the_full_argv_and_rejects_extra_parameters():
    (descriptor,) = runtime_composition._codex_trusted_targets(_enabled_settings())
    assert descriptor.resolve(_spec(CODEX_CLI_FIXED_ARGV)) == (
        "/opt/codex/bin/codex",
        *CODEX_CLI_FIXED_ARGV,
    )
    with pytest.raises(UntrustedTargetError):
        descriptor.resolve(_spec((*CODEX_CLI_FIXED_ARGV, "--extra")))
    with pytest.raises(UntrustedTargetError):
        descriptor.resolve(_spec(("exec", "--json")))
