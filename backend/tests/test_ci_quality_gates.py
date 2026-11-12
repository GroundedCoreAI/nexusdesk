import asyncio
from pathlib import Path

import pytest
import yaml
from conftest import require_migration_database_url, require_test_database_url

from agent_platform.core_platform.tool_gateway.harness import ToolExecutionHarness
from agent_platform.extension_contracts import (
    PolicyDecision,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.p0
@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("CI", "true"),
        ("REQUIRE_POSTGRES_TESTS", "1"),
    ],
)
def test_database_url_helpers_fail_closed_in_ci(monkeypatch, env_name, value):
    """Missing DB URLs must fail CI rather than silently skipping integration suites."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("REQUIRE_POSTGRES_TESTS", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv(env_name, value)

    with pytest.raises(pytest.fail.Exception, match="Infrastructure configuration error"):
        require_test_database_url()

    with pytest.raises(pytest.fail.Exception, match="Infrastructure configuration error"):
        require_migration_database_url()


def test_database_url_helpers_skip_locally_and_return_configured_values(monkeypatch):
    """Local runs without Postgres skip cleanly; configured URLs are returned verbatim."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("REQUIRE_POSTGRES_TESTS", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_TEST_DATABASE_URL", raising=False)

    with pytest.raises(pytest.skip.Exception):
        require_test_database_url()

    with pytest.raises(pytest.skip.Exception):
        require_migration_database_url()

    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://localhost/test")
    monkeypatch.setenv("MIGRATION_TEST_DATABASE_URL", "postgresql+asyncpg://localhost/mig")
    assert require_test_database_url() == "postgresql+asyncpg://localhost/test"
    assert require_migration_database_url() == "postgresql+asyncpg://localhost/mig"


@pytest.mark.p0
@pytest.mark.asyncio
async def test_harness_failure_paths_fail_closed_without_retry():
    """Denied, unconfirmed, and timed-out writes must fail closed without retrying."""
    calls: list[str] = []

    class RecordingHandler:
        async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
            calls.append(request.definition.name)
            return ToolExecutionResult(status="succeeded", data={"ok": True})

    class SlowHandler:
        async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
            calls.append(f"slow:{request.definition.name}")
            await asyncio.sleep(0.2)
            return ToolExecutionResult(status="succeeded", data={"ok": True})

    definition = ToolDefinition(
        name="cancel_order",
        description="Cancel an order.",
        parameters={"type": "object", "additionalProperties": False},
        capability="customer-service",
        risk="irreversible",
    )
    request = ToolExecutionRequest(
        definition=definition,
        context=ToolExecutionContext(tenant_id="tenant-a", source="runtime"),
        idempotency_key="idem-1",
    )
    harness = ToolExecutionHarness()

    denied = await harness.execute(
        RecordingHandler(),
        request,
        PolicyDecision(effect="deny", reason_code="forbidden", risk="irreversible"),
    )
    assert denied.status == "failed"
    assert denied.error_code == "tool_not_allowed"

    missing_key = await harness.execute(
        RecordingHandler(),
        request.model_copy(update={"idempotency_key": None}),
        PolicyDecision(
            effect="allow",
            reason_code="authorized",
            risk="irreversible",
            constraint={"idempotency_required": True},
        ),
    )
    assert missing_key.status == "failed"
    assert missing_key.error_code == "idempotency_key_required"

    unconfirmed = await harness.execute(
        RecordingHandler(),
        request,
        PolicyDecision(
            effect="allow",
            reason_code="requires_approval",
            risk="irreversible",
            confirmation={"required": True, "action": "confirm_cancel"},
        ),
    )
    assert unconfirmed.status == "requires_confirmation"
    assert calls == []

    timed_out = await harness.execute(
        SlowHandler(),
        request,
        PolicyDecision(
            effect="allow",
            reason_code="authorized",
            risk="irreversible",
            constraint={"timeout_seconds": 0.01},
        ),
    )
    assert timed_out.status == "failed"
    assert timed_out.error_code == "tool_timeout"
    assert timed_out.retryable is False
    assert calls == ["slow:cancel_order"]


def test_ci_workflow_enforces_non_mutating_checks_and_strict_postgres_gate():
    """CI must keep non-mutating checks, format verification, and fail-closed DB gates."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    jobs = workflow["jobs"]

    lint_steps = "\n".join(step.get("run", "") for step in jobs["backend-lint"]["steps"])
    assert "ruff check ." in lint_steps
    assert "ruff format --check" in lint_steps
    assert "ruff format ." not in lint_steps
    assert "--fix" not in lint_steps
    assert "git diff --exit-code" in lint_steps

    pg_job = jobs["backend-test-postgres"]
    assert pg_job["env"]["REQUIRE_POSTGRES_TESTS"] == "1"
    pg_steps = "\n".join(step.get("run", "") for step in pg_job["steps"])
    assert "--junitxml=" in pg_steps
    assert "runtime_baseline.py summary" in pg_steps
    assert "git diff --exit-code" in pg_steps

    unit_steps = "\n".join(step.get("run", "") for step in jobs["backend-test-unit"]["steps"])
    assert "--junitxml=" in unit_steps
    assert "runtime_baseline.py summary" in unit_steps
    assert "git diff --exit-code" in unit_steps

    fe_steps = "\n".join(step.get("run", "") for step in jobs["frontend"]["steps"])
    assert "git diff --exit-code" in fe_steps
