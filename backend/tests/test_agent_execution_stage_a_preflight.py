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
