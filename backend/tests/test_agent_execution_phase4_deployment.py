"""Phase 4 deployment configuration checks (08 T14, P4-IT-29 static half).

Static YAML/env assertions only; the Linux production runtime half of
P4-IT-29 and the container restart drill (P4-IT-09) stay pending_env (08 R-3).
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

FR10_KEYS = (
    "AGENT_EXECUTION_RUNTIME_HOST_ENABLED",
    "AGENT_EXECUTION_WORKDIR_ROOT",
    "AGENT_EXECUTION_SANDBOX_PROVIDER",
    "AGENT_EXECUTION_RESOURCE_ENFORCEMENT_REQUIRED",
    "AGENT_EXECUTION_PROCESS_CANCEL_GRACE_SECONDS",
    "AGENT_EXECUTION_PROCESS_KILL_TIMEOUT_SECONDS",
    "AGENT_EXECUTION_PROCESS_RECONCILE_INTERVAL_SECONDS",
    "AGENT_EXECUTION_PROCESS_WALL_TIMEOUT_SECONDS",
    "AGENT_EXECUTION_PROCESS_OUTPUT_MAX_BYTES",
    "AGENT_EXECUTION_RESOURCE_CPU_SECONDS",
    "AGENT_EXECUTION_RESOURCE_MEMORY_BYTES",
    "AGENT_EXECUTION_RESOURCE_MAX_PROCESSES",
    "AGENT_EXECUTION_WORKDIR_MAX_BYTES",
    "AGENT_EXECUTION_WORKDIR_MAX_FILE_BYTES",
    "AGENT_EXECUTION_RESOURCE_SAMPLE_INTERVAL_SECONDS",
    "AGENT_EXECUTION_WORKDIR_RETENTION_SECONDS",
    "AGENT_EXECUTION_WORKDIR_FAILED_RETENTION_SECONDS",
    "AGENT_EXECUTION_WORKDIR_CLEANUP_INTERVAL_SECONDS",
)


def _quick():
    return yaml.safe_load((ROOT / "deploy/quickstart/compose.yaml").read_text(encoding="utf-8"))


def _prod():
    return yaml.safe_load((ROOT / "deploy/production/compose.yaml").read_text(encoding="utf-8"))


def test_quickstart_execution_defaults_are_off_and_rooted():
    quick = _quick()
    env = quick["services"]["app"]["environment"]
    assert env["AGENT_EXECUTION_RUNTIME_HOST_ENABLED"] == (
        "${AGENT_EXECUTION_RUNTIME_HOST_ENABLED:-false}"
    )
    assert env["AGENT_EXECUTION_WORKDIR_ROOT"] == "/data/execution"
    # No host id on the default topology: the Runtime Host subsystem is not
    # assembled at all (08 R-7), which keeps quickstart byte-identical.
    assert "AGENT_EXECUTION_RUNTIME_HOST_ID" not in env
    assert "app_data:/data" in quick["services"]["app"]["volumes"]
    assert quick["services"]["app"]["stop_grace_period"] == "45s"


def test_quickstart_default_windows_fit_the_stop_grace():
    # 03 §4.3: default 5s+5s plus the 5s reconcile margin must fit the
    # existing 45s stop_grace_period, or the compose would have to raise it.
    from agent_platform.core_platform.platform_services.platform_settings.settings import (
        Settings,
    )

    settings = Settings(_env_file=None)
    quick = _quick()
    grace = int(quick["services"]["app"]["stop_grace_period"].removesuffix("s"))
    budget = (
        settings.execution_process_cancel_grace_seconds
        + settings.execution_process_kill_timeout_seconds
        + settings.execution_process_reconcile_interval_seconds
    )
    assert budget <= grace


def test_production_runtime_worker_declares_both_volumes_and_host_identity():
    prod = _prod()
    worker = prod["services"]["runtime-worker"]
    # YAML merge replaces whole keys (08 R-7): the anchor's credentials volume
    # must be redeclared next to the dedicated execution root.
    assert worker["volumes"] == [
        "credentials:/data/credentials",
        "execution_data:/data/execution",
    ]
    env = worker["environment"]
    # ...and the anchor environment likewise.
    for key in (
        "AGENT_ENVIRONMENT",
        "AGENT_QUICKSTART_MODE",
        "AGENT_EMBEDDED_WORKER",
        "AGENT_MODEL_CREDENTIAL_KEY_FILE",
    ):
        assert key in env
    assert env["AGENT_EXECUTION_RUNTIME_HOST_ID"] == (
        "${NEXUSDESK_RUNTIME_HOST_ID:-production-runtime}"
    )
    assert env["AGENT_EXECUTION_WORKDIR_ROOT"] == "/data/execution"
    assert env["AGENT_EXECUTION_RUNTIME_HOST_ENABLED"] == (
        "${AGENT_EXECUTION_RUNTIME_HOST_ENABLED:-false}"
    )
    assert "execution_data" in prod["volumes"]


def test_production_other_workers_have_no_execution_surface():
    # One Host per execution root (03 §4.4): the volume's absence on every
    # other backend service is itself the AC-12 topology check.
    prod = _prod()
    for name in ("migrate", "api", "channel-worker", "knowledge-worker", "memory-worker"):
        service = prod["services"][name]
        volumes = service.get("volumes", [])
        assert not any("execution_data" in str(item) for item in volumes), name
        assert "AGENT_EXECUTION_RUNTIME_HOST_ID" not in service.get("environment", {})
        assert "AGENT_EXECUTION_WORKDIR_ROOT" not in service.get("environment", {})


def test_production_env_example_carries_the_fr10_block_with_no_secrets():
    text = (ROOT / "deploy/production/.env.example").read_text(encoding="utf-8")
    for key in FR10_KEYS:
        assert f"{key}=" in text, key
    assert "AGENT_EXECUTION_RUNTIME_HOST_ENABLED=false" in text
    # The host id must NOT be an env_file key (that would leak assembly to
    # every service); it is interpolated from NEXUSDESK_RUNTIME_HOST_ID.
    assert "AGENT_EXECUTION_RUNTIME_HOST_ID=" not in text
    assert "NEXUSDESK_RUNTIME_HOST_ID=production-runtime" in text
    phase4_lines = [
        line
        for line in text.splitlines()
        if line.startswith(FR10_KEYS) or line.startswith("NEXUSDESK_RUNTIME_HOST_ID=")
    ]
    assert all("REPLACE" not in line for line in phase4_lines)
    # The darwin enforcement note and the stop-timeout note are documented.
    assert "darwin" in text
    assert "stop_grace_period" in text


def test_backend_env_example_mirrors_the_fr10_defaults():
    text = (ROOT / "backend/.env.example").read_text(encoding="utf-8")
    for key in FR10_KEYS:
        assert key in text, key


@pytest.mark.parametrize("compose", ["deploy/quickstart/compose.yaml"])
def test_compose_files_stay_parseable_after_phase4(compose):
    data = yaml.safe_load((ROOT / compose).read_text(encoding="utf-8"))
    assert data is not None
