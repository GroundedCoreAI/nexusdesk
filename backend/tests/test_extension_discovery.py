import asyncio
from pathlib import Path

import pytest

from agent_platform.core_platform.extension_platform import (
    CapabilityBindingError,
    CapabilityImplementationRegistry,
    CapabilityRegistry,
    ExtensionRegistryError,
)


def _write_manifest(
    directory: Path,
    filename: str,
    capability_id: str,
    *,
    dependencies: list[str] | None = None,
    enabled_by_default: bool = True,
) -> Path:
    path = directory / filename
    path.write_text(
        f"""
manifest_version: "1"
capability:
  id: {capability_id}
  version: 1.0.0
  api_version: v1
  name: {capability_id}
  description: External capability.
  dependencies: {dependencies or []}
  dependency_constraints: {{}}
  requires_platform: ">=0.1.0,<1.0.0"
  enabled_by_default: {str(enabled_by_default).lower()}
""",
        encoding="utf-8",
    )
    return path


class _Lifecycle:
    def __init__(self, events: list[str], name: str, fail_start: bool = False) -> None:
        self.events = events
        self.name = name
        self.fail_start = fail_start

    async def start(self) -> None:
        self.events.append(f"start:{self.name}")
        if self.fail_start:
            raise RuntimeError(f"{self.name}_unavailable")

    async def stop(self) -> None:
        self.events.append(f"stop:{self.name}")


def test_manifest_directory_registration_resolves_dependencies_in_multiple_passes(
    tmp_path: Path,
):
    _write_manifest(tmp_path, "01-dependent.yaml", "dependent", dependencies=["base"])
    _write_manifest(tmp_path, "02-base.yaml", "base")

    registry = CapabilityRegistry()
    results = registry.register_manifest_directory(tmp_path)

    assert [(result.path.name, result.status) for result in results] == [
        ("01-dependent.yaml", "registered"),
        ("02-base.yaml", "registered"),
    ]
    assert tuple(item.capability_id for item in registry.list()) == ("base", "dependent")


def test_manifest_directory_registration_isolates_duplicates_missing_dependencies_and_cycles(
    tmp_path: Path,
):
    _write_manifest(tmp_path, "01-good.yaml", "good")
    _write_manifest(tmp_path, "02-duplicate.yaml", "good")
    _write_manifest(tmp_path, "03-missing.yaml", "missing", dependencies=["not-installed"])
    _write_manifest(tmp_path, "04-cycle-a.yaml", "cycle-a", dependencies=["cycle-b"])
    _write_manifest(tmp_path, "05-cycle-b.yaml", "cycle-b", dependencies=["cycle-a"])

    registry = CapabilityRegistry()
    results = registry.register_manifest_directory(tmp_path)
    by_name = {result.path.name: result for result in results}

    assert by_name["01-good.yaml"].status == "conflict"
    assert by_name["02-duplicate.yaml"].status == "conflict"
    assert by_name["03-missing.yaml"].status == "rejected"
    assert by_name["04-cycle-a.yaml"].status == "rejected"
    assert by_name["05-cycle-b.yaml"].status == "rejected"
    assert registry.get("good") is None
    assert registry.get("missing") is None


@pytest.mark.asyncio
async def test_external_lifecycle_failures_are_isolated_during_startup(tmp_path: Path):
    _write_manifest(tmp_path, "01-failing.yaml", "failing")
    _write_manifest(tmp_path, "02-healthy.yaml", "healthy")
    _write_manifest(tmp_path, "03-dependent.yaml", "dependent", dependencies=["healthy"])

    events: list[str] = []
    registry = CapabilityRegistry()
    registry.register_manifest_directory(
        tmp_path,
        {
            "failing": _Lifecycle(events, "failing", fail_start=True),
            "healthy": _Lifecycle(events, "healthy"),
            "dependent": _Lifecycle(events, "dependent"),
        },
    )

    statuses = await registry.start_all()

    assert events == ["start:healthy", "start:dependent", "start:failing"]
    assert registry.get("failing").status == "degraded"
    assert registry.get("failing").reason == "failing_unavailable"
    assert registry.get("healthy").status == "ready"
    assert registry.get("dependent").status == "ready"
    assert {item.status for item in statuses} == {"degraded", "ready"}


@pytest.mark.asyncio
async def test_enabled_degraded_capability_can_be_retried_without_reenabling(tmp_path: Path):
    _write_manifest(tmp_path, "failing.yaml", "failing")
    events: list[str] = []
    lifecycle = _Lifecycle(events, "failing", fail_start=True)
    registry = CapabilityRegistry()
    registry.register_manifest_directory(tmp_path, {"failing": lifecycle})

    await registry.start_all()
    assert registry.get("failing").status == "degraded"
    lifecycle.fail_start = False

    recovered = await registry.retry("failing")

    assert recovered.enabled is True
    assert recovered.status == "ready"
    assert events == ["start:failing", "start:failing"]

    await registry.disable("failing")
    with pytest.raises(ExtensionRegistryError, match="capability is disabled"):
        await registry.retry("failing")


@pytest.mark.asyncio
async def test_lifecycle_start_and_health_are_bounded(tmp_path: Path):
    _write_manifest(tmp_path, "slow.yaml", "slow")

    class SlowLifecycle:
        async def start(self):
            await asyncio.sleep(0.05)

        async def stop(self):
            return None

    registry = CapabilityRegistry(lifecycle_timeout_seconds=0.001)
    registry.register_manifest_directory(tmp_path, {"slow": SlowLifecycle()})

    await registry.start_all()

    assert registry.get("slow").status == "degraded"
    assert registry.get("slow").reason == "lifecycle_start_failed"


def test_manifest_entrypoint_is_data_only_and_never_imported(tmp_path: Path):
    path = _write_manifest(tmp_path, "entrypoint.yaml", "safe")
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text + '\nentrypoint: "os.system:system"\n',
        encoding="utf-8",
    )

    registry = CapabilityRegistry()
    results = registry.register_manifest_directory(tmp_path)

    assert results[0].status == "rejected"
    assert "invalid capability manifest" in results[0].error
    assert registry.get("safe") is None


def test_trusted_implementation_registry_rejects_invalid_and_duplicate_bindings():
    implementations = CapabilityImplementationRegistry()
    implementations.register("safe", lambda: _Lifecycle([], "safe"))

    assert implementations.contains("safe")
    assert implementations.list() == ("safe",)
    assert implementations.factory("safe") is not None

    with pytest.raises(CapabilityBindingError, match="already bound"):
        implementations.register("safe", lambda: _Lifecycle([], "safe-again"))
    with pytest.raises(CapabilityBindingError, match="invalid capability id"):
        implementations.register("Invalid", lambda: _Lifecycle([], "invalid"))
    with pytest.raises(CapabilityBindingError, match="must be callable"):
        implementations.register("other", object())


@pytest.mark.asyncio
async def test_trusted_factory_is_constructed_only_at_controlled_startup(tmp_path: Path):
    _write_manifest(tmp_path, "01-safe.yaml", "safe")
    _write_manifest(tmp_path, "02-broken.yaml", "broken")
    events: list[str] = []
    factory_calls: list[str] = []

    def safe_factory() -> _Lifecycle:
        factory_calls.append("safe")
        return _Lifecycle(events, "safe")

    def broken_factory() -> _Lifecycle:
        factory_calls.append("broken")
        raise RuntimeError("trusted_factory_unavailable")

    implementations = CapabilityImplementationRegistry()
    implementations.register("safe", safe_factory)
    implementations.register("broken", broken_factory)
    registry = CapabilityRegistry()

    results = registry.register_manifest_directory(
        tmp_path,
        implementation_registry=implementations,
    )

    assert {result.status for result in results} == {"registered"}
    assert factory_calls == []

    statuses = await registry.start_all()

    assert factory_calls == ["broken", "safe"]
    assert events == ["start:safe"]
    assert registry.get("broken").status == "degraded"
    assert registry.get("broken").reason == "trusted_factory_unavailable"
    assert registry.get("safe").status == "ready"
    assert {item.status for item in statuses} == {"degraded", "ready"}


def test_manifest_registration_rejects_ambiguous_implementation_sources(tmp_path: Path):
    _write_manifest(tmp_path, "safe.yaml", "safe")
    registry = CapabilityRegistry()
    implementations = CapabilityImplementationRegistry()
    implementations.register("safe", lambda: _Lifecycle([], "safe"))

    with pytest.raises(ExtensionRegistryError, match="mutually exclusive"):
        registry.register_manifest_directory(
            tmp_path,
            {"safe": _Lifecycle([], "safe")},
            implementations,
        )


def test_runtime_discovery_requires_explicit_trusted_bindings(tmp_path: Path):
    _write_manifest(tmp_path, "unbound.yaml", "unbound")
    registry = CapabilityRegistry()
    implementations = CapabilityImplementationRegistry()

    results = registry.register_manifest_directory(
        tmp_path,
        implementation_registry=implementations,
        require_implementation=True,
        require_contribution_binding=True,
    )

    assert results[0].status == "rejected"
    assert "trusted capability implementation is not bound" in results[0].error
    assert registry.get("unbound") is None


def test_runtime_discovery_accepts_explicit_lifecycle_and_contribution_binding(tmp_path: Path):
    path = _write_manifest(tmp_path, "bound.yaml", "bound")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "  enabled_by_default: true",
            "  contributions:\n    - tools\n  enabled_by_default: true",
        ),
        encoding="utf-8",
    )
    implementations = CapabilityImplementationRegistry()
    implementations.register(
        "bound",
        lambda: _Lifecycle([], "bound"),
        lambda _platform: object(),
    )
    registry = CapabilityRegistry()

    results = registry.register_manifest_directory(
        tmp_path,
        implementation_registry=implementations,
        require_implementation=True,
        require_contribution_binding=True,
    )

    assert results[0].status == "registered"
    assert registry.get("bound").capability_id == "bound"
