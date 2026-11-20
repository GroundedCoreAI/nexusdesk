"""Stage A preflight guards found by the P7 end-to-end acceptance.

Two deployment defects made stage A unreachable even with every gate open:

* D-2: the Phase 3 barrier's instruction preparer received the
  ``RuntimeFactory`` object itself. A factory is not callable, so every
  orchestrated Run failed in the barrier with ``execution_error`` before an
  Adapter was ever started.
* D-3: the Codex CLI target is a Node process, and the generic 512 MiB
  ``RLIMIT_AS`` ceiling kills it with SIGTRAP before the first turn. A
  Codex-enabled deployment must therefore carry a Node-sized ceiling.
"""

import pytest

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.applications.platform_runtime.runtime_composition import (
    RuntimeFactoryInstructionPreparer,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import (
    CODEX_CLI_MIN_MEMORY_BYTES,
    Settings,
)

CODEX_ON = {
    "codex_cli_enabled": True,
    "codex_stage_a_verified": True,
    "codex_allowed_versions": ("0.169.0",),
    "codex_trusted_tenants": ("local",),
    "codex_cli_executable_path": "/opt/nexusdesk/codex/bin/bin/codex.js",
}


class _FakeFactory:
    """A factory *owns* ``prepare_instructions``; the instance is not callable."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def prepare_instructions(self, row, **kwargs):
        self.calls.append((row, kwargs))
        return {"prepared": True}


def test_the_preparer_binds_a_factory_method_instead_of_the_object():
    factory = _FakeFactory()
    # The composition passes the factory, which is exactly what used to raise
    # "'_FakeFactory' object is not callable" from inside the barrier.
    preparer = RuntimeFactoryInstructionPreparer(factory)

    assert preparer.prepare_instructions({"id": "run"}, history=()) == {"prepared": True}
    assert factory.calls == [({"id": "run"}, {
        "history": (),
        "summary_message": None,
        "customer_memory": None,
        "engine_context": None,
    })]


def test_the_preparer_still_accepts_a_plain_callable():
    seen: list[object] = []

    def prepare(row, **_kwargs):
        seen.append(row)
        return {"prepared": "callable"}

    preparer = RuntimeFactoryInstructionPreparer(prepare)
    assert preparer.prepare_instructions({"id": "run"}) == {"prepared": "callable"}
    assert seen == [{"id": "run"}]


def test_an_unconfigured_preparer_fails_loudly():
    with pytest.raises(TypeError, match="not configured"):
        RuntimeFactoryInstructionPreparer(None).prepare_instructions({"id": "run"})


def test_codex_requires_a_node_sized_memory_ceiling():
    with pytest.raises(ValueError, match="execution_resource_memory_bytes"):
        Settings(_env_file=None, **CODEX_ON)

    settings = Settings(
        _env_file=None,
        **CODEX_ON,
        execution_resource_memory_bytes=CODEX_CLI_MIN_MEMORY_BYTES,
    )
    assert settings.execution_resource_memory_bytes == CODEX_CLI_MIN_MEMORY_BYTES


def test_the_memory_ceiling_gate_is_inert_while_codex_is_off():
    # The default deployment keeps the generic 512 MiB ceiling and stays valid:
    # only a Codex-enabled configuration has to pay for the Node address space.
    settings = Settings(_env_file=None)
    assert settings.codex_cli_enabled is False
    assert settings.execution_resource_memory_bytes < CODEX_CLI_MIN_MEMORY_BYTES


# --------------------------------------------------------------------------- #
# D-4: the adapter must run the published Codex block, not the deployment one  #
# --------------------------------------------------------------------------- #

CODEX_PUBLISHED = {
    "engine": {"engine_id": "codex", "protocol_id": "cli_exec", "adapter_version": "v1"},
    "codex": {
        "version": "0.169.0",
        "credential_ref": "745a1781-e51b-4212-97f4-7b9834987781",
        "path_env": "/opt/nexusdesk/codex/node:/usr/bin:/bin",
    },
}


def _codex_context(published):
    from uuid import uuid4

    from test_agent_execution_phase3_wiring import published_row

    from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
        build_execution_context,
    )
    from agent_platform.extension_contracts import BusinessScope

    row = published_row()
    row["config"]["agent"]["config"] = published
    return build_execution_context(
        row,
        history=[],
        owner=uuid4(),
        scope=BusinessScope(
            tenant_id=row["tenant_id"],
            business_id=row["business_id"],
            workspace_id=row["workspace_id"],
        ),
        execution_phase3_enabled=True,
    )


def _cli_factory():
    settings = Settings(
        _env_file=None,
        **CODEX_ON,
        execution_resource_memory_bytes=2_147_483_648,
        execution_runtime_host_enabled=True,
        execution_runtime_host_id="runtime-01",
    )
    (_, factory), _ = runtime_composition._codex_adapters(settings, object(), object())
    return factory


def test_the_codex_factory_runs_the_published_block():
    from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
        resolve_with_execution_context,
    )

    adapter = resolve_with_execution_context(_codex_context(CODEX_PUBLISHED), _cli_factory())

    # The published credential reference is what the Broker lane needs; the old
    # deployment placeholder carried none, so P6 never issued a grant.
    assert adapter._config.credential_ref == CODEX_PUBLISHED["codex"]["credential_ref"]
    assert adapter._config.path_env == CODEX_PUBLISHED["codex"]["path_env"]


def test_the_codex_factory_refuses_a_run_without_a_published_block():
    from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
        resolve_with_execution_context,
    )

    react_published = {
        "engine": {"engine_id": "react", "protocol_id": "native", "adapter_version": "v1"}
    }
    with pytest.raises(RuntimeError, match="published codex block"):
        resolve_with_execution_context(_codex_context(react_published), _cli_factory())
