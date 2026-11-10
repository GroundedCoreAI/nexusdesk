import ast
import asyncio
import functools
import gc
import inspect
import traceback
import weakref
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

import agent_platform.core_platform.agent_execution as execution_package
import agent_platform.core_platform.agent_execution.registry as registry_package
import agent_platform.core_platform.agent_execution.registry.adapter_registry as adapter_registry_module
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    AgentEvent,
    ConfigurationError,
    EngineCapabilities,
    ExecutionContractModel,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionErrorDetails,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
)
from agent_platform.core_platform.agent_execution.registry import (
    AdapterDescriptor,
    AdapterRegistry,
    EngineDescriptor,
    EngineRegistry,
    ProtocolDescriptor,
    ProtocolRegistry,
)

IDENTITY_FIELDS = ("engine_id", "protocol_id", "adapter_version")
ASYNC_METHODS = ("get_capabilities", "start", "cancel", "collect_result")
LIFECYCLE_METHODS = (*ASYNC_METHODS, "stream_events")
SECRET_MARKER = "secret-" + "marker"


class StubAdapter:
    """Structurally compliant adapter whose lifecycle must not run during resolution."""

    def __init__(
        self,
        engine_id: str = "engine-a",
        protocol_id: str = "protocol-a",
        adapter_version: str = "v1",
    ) -> None:
        self._engine_id = engine_id
        self._protocol_id = protocol_id
        self._adapter_version = adapter_version
        self.state: list[str] = []

    @property
    def engine_id(self) -> str:
        return self._engine_id

    @property
    def protocol_id(self) -> str:
        return self._protocol_id

    @property
    def adapter_version(self) -> str:
        return self._adapter_version

    async def get_capabilities(self) -> EngineCapabilities:
        raise AssertionError("resolution must not execute get_capabilities")

    async def start(self, request: ExecutionRequest) -> ExecutionHandle:
        raise AssertionError("resolution must not execute start")

    def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        raise AssertionError("resolution must not execute stream_events")

    async def cancel(self, handle: ExecutionHandle) -> None:
        raise AssertionError("resolution must not execute cancel")

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        raise AssertionError("resolution must not execute collect_result")


def adapter_class(
    *,
    missing: tuple[str, ...] = (),
    overrides: dict[str, object] | None = None,
) -> type[StubAdapter]:
    namespace = {
        name: value
        for name, value in StubAdapter.__dict__.items()
        if name not in {"__dict__", "__weakref__", *missing}
    }
    namespace.update(overrides or {})
    return type("CaseAdapter", (object,), namespace)


def recording_factory(
    engine_id: str,
    protocol_id: str,
    adapter_version: str,
    created: list[StubAdapter],
) -> Callable[[], StubAdapter]:
    def create() -> StubAdapter:
        instance = StubAdapter(engine_id, protocol_id, adapter_version)
        created.append(instance)
        return instance

    return create


def build_matrix() -> tuple[AdapterRegistry, list[StubAdapter]]:
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    for engine_id, enabled in (
        ("engine-a", True),
        ("engine-b", True),
        ("disabled-engine", False),
    ):
        engines.register(EngineDescriptor(engine_id=engine_id, enabled=enabled))
    for protocol_id, enabled in (
        ("protocol-a", True),
        ("protocol-b", True),
        ("disabled-protocol", False),
    ):
        protocols.register(ProtocolDescriptor(protocol_id=protocol_id, enabled=enabled))

    adapters = AdapterRegistry(engines, protocols)
    created: list[StubAdapter] = []
    registrations = (
        ("engine-a", "protocol-a", "v1", True),
        ("engine-a", "protocol-a", "v2", True),
        ("engine-a", "protocol-b", "v1", True),
        ("engine-a", "protocol-b", "v2", False),
        ("engine-b", "protocol-a", "v1", True),
        ("disabled-engine", "protocol-a", "v1", True),
        ("engine-a", "disabled-protocol", "v1", True),
        ("disabled-engine", "disabled-protocol", "v2", False),
    )
    for engine_id, protocol_id, adapter_version, enabled in registrations:
        adapters.register(
            AdapterDescriptor(
                engine_id=engine_id,
                protocol_id=protocol_id,
                adapter_version=adapter_version,
                enabled=enabled,
            ),
            recording_factory(engine_id, protocol_id, adapter_version, created),
        )
    return adapters, created


def simple_registries() -> tuple[EngineRegistry, ProtocolRegistry, AdapterRegistry]:
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    engines.register(EngineDescriptor(engine_id="engine-a"))
    protocols.register(ProtocolDescriptor(protocol_id="protocol-a"))
    return engines, protocols, AdapterRegistry(engines, protocols)


def assert_configuration_error(
    caught: pytest.ExceptionInfo[ConfigurationError],
    code: ExecutionErrorCode,
) -> None:
    error = caught.value
    assert isinstance(error, ConfigurationError)
    assert error.error.category == ExecutionErrorCategory.CONFIGURATION_ERROR
    assert error.error.code == code
    assert str(error) == error.error.message
    assert error.error.retryable is False


def register_one(
    adapters: AdapterRegistry,
    factory: Callable[[], StubAdapter] = StubAdapter,
    *,
    enabled: bool = True,
) -> None:
    adapters.register(
        AdapterDescriptor(
            engine_id="engine-a",
            protocol_id="protocol-a",
            adapter_version="v1",
            enabled=enabled,
        ),
        factory,
    )


DESCRIPTOR_CASES = (
    (EngineDescriptor, {"engine_id": "engine-a"}, {"engine_id", "enabled"}),
    (ProtocolDescriptor, {"protocol_id": "protocol-a"}, {"protocol_id", "enabled"}),
    (
        AdapterDescriptor,
        {"engine_id": "engine-a", "protocol_id": "protocol-a", "adapter_version": "v1"},
        {"engine_id", "protocol_id", "adapter_version", "enabled"},
    ),
)


@pytest.mark.parametrize("descriptor_type,data,fields", DESCRIPTOR_CASES)
def test_descriptors_are_strict_frozen_execution_contracts(descriptor_type, data, fields):
    descriptor = descriptor_type(**data)
    assert isinstance(descriptor, ExecutionContractModel)
    assert set(descriptor_type.model_fields) == fields
    assert descriptor.enabled is True
    assert descriptor_type.model_config["strict"] is True
    assert descriptor_type.model_config["extra"] == "forbid"
    assert descriptor_type.model_config["frozen"] is True
    with pytest.raises(ValidationError):
        descriptor.enabled = False
    with pytest.raises(ValidationError):
        descriptor_type(**data, unknown="value")


@pytest.mark.parametrize("descriptor_type,data,_", DESCRIPTOR_CASES)
@pytest.mark.parametrize("enabled", [1, 0, "true", None])
def test_descriptors_require_strict_boolean_enabled(descriptor_type, data, _, enabled):
    with pytest.raises(ValidationError):
        descriptor_type(**data, enabled=enabled)


@pytest.mark.parametrize(
    "descriptor_type,field",
    [(EngineDescriptor, "engine_id"), (ProtocolDescriptor, "protocol_id")],
)
@pytest.mark.parametrize(
    "value",
    ["", "-bad", "_bad", "Upper", "has.dot", " bad", "bad ", "a" * 65, 7, None],
)
def test_engine_and_protocol_descriptors_validate_identity(descriptor_type, field, value):
    with pytest.raises(ValidationError):
        descriptor_type(**{field: value})


@pytest.mark.parametrize("value", ["latest", "v0", "v01", " v1", "v1 ", "V1", "1", 1, None])
def test_adapter_descriptor_validates_explicit_version(value):
    with pytest.raises(ValidationError):
        AdapterDescriptor(
            engine_id="engine-a",
            protocol_id="protocol-a",
            adapter_version=value,
        )


def test_registry_package_exports_only_public_registries_and_descriptors():
    assert set(registry_package.__all__) == {
        "AdapterDescriptor",
        "AdapterRegistry",
        "EngineDescriptor",
        "EngineRegistry",
        "ProtocolDescriptor",
        "ProtocolRegistry",
    }
    assert not hasattr(execution_package, "EngineRegistry")
    assert not hasattr(execution_package, "LocalTestAdapter")


def test_engine_and_protocol_registries_are_independent_and_readable():
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    engine = EngineDescriptor(engine_id="engine-a")
    protocol = ProtocolDescriptor(protocol_id="protocol-a", enabled=False)
    engines.register(engine)
    protocols.register(protocol)
    assert engines.get("engine-a") is engine
    assert protocols.get("protocol-a") is protocol
    assert engines.get("protocol-a") is None
    assert protocols.get("engine-a") is None


@pytest.mark.parametrize(
    "second",
    [
        EngineDescriptor(engine_id="engine-a"),
        EngineDescriptor(engine_id="engine-a", enabled=False),
    ],
)
def test_duplicate_engine_always_fails_even_for_identical_descriptor(second):
    registry = EngineRegistry()
    registry.register(EngineDescriptor(engine_id="engine-a"))
    with pytest.raises(ConfigurationError) as caught:
        registry.register(second)
    assert_configuration_error(caught, ExecutionErrorCode.DUPLICATE_ENGINE)


@pytest.mark.parametrize(
    "second",
    [
        ProtocolDescriptor(protocol_id="protocol-a", enabled=False),
        ProtocolDescriptor(protocol_id="protocol-a", enabled=True),
    ],
)
def test_duplicate_protocol_always_fails_even_for_identical_descriptor(second):
    registry = ProtocolRegistry()
    registry.register(ProtocolDescriptor(protocol_id="protocol-a", enabled=False))
    with pytest.raises(ConfigurationError) as caught:
        registry.register(second)
    assert_configuration_error(caught, ExecutionErrorCode.DUPLICATE_PROTOCOL)


@pytest.mark.parametrize("registry", [EngineRegistry(), ProtocolRegistry()])
def test_engine_and_protocol_registration_rejects_raw_configuration_safely(registry):
    with pytest.raises(ConfigurationError) as caught:
        registry.register({"id": SECRET_MARKER})
    assert_configuration_error(caught, ExecutionErrorCode.INVALID_REQUEST)
    assert SECRET_MARKER not in str(caught.value)


def test_adapter_registration_requires_existing_references_in_priority_order():
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    adapters = AdapterRegistry(engines, protocols)
    descriptor = AdapterDescriptor(
        engine_id="engine-a",
        protocol_id="protocol-a",
        adapter_version="v1",
    )
    with pytest.raises(ConfigurationError) as caught:
        adapters.register(descriptor, StubAdapter)
    assert_configuration_error(caught, ExecutionErrorCode.UNKNOWN_ENGINE)

    engines.register(EngineDescriptor(engine_id="engine-a"))
    with pytest.raises(ConfigurationError) as caught:
        adapters.register(descriptor, StubAdapter)
    assert_configuration_error(caught, ExecutionErrorCode.UNKNOWN_PROTOCOL)


def test_adapter_registration_allows_disabled_engine_and_protocol_references():
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    engines.register(EngineDescriptor(engine_id="engine-a", enabled=False))
    protocols.register(ProtocolDescriptor(protocol_id="protocol-a", enabled=False))
    adapters = AdapterRegistry(engines, protocols)
    register_one(adapters)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ENGINE_DISABLED)


@pytest.mark.parametrize("same_factory", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
def test_duplicate_adapter_exact_triple_always_fails(same_factory, enabled):
    _, _, adapters = simple_registries()
    first_factory = recording_factory("engine-a", "protocol-a", "v1", [])
    second_factory = first_factory if same_factory else StubAdapter
    register_one(adapters, first_factory)
    with pytest.raises(ConfigurationError) as caught:
        adapters.register(
            AdapterDescriptor(
                engine_id="engine-a",
                protocol_id="protocol-a",
                adapter_version="v1",
                enabled=enabled,
            ),
            second_factory,
        )
    assert_configuration_error(caught, ExecutionErrorCode.DUPLICATE_ADAPTER)


@pytest.mark.parametrize(
    "second_triple,resolution_error",
    [
        (("engine-b", "protocol-a", "v1"), ExecutionErrorCode.INCOMPATIBLE_ENGINE_PROTOCOL),
        (("engine-a", "protocol-b", "v1"), ExecutionErrorCode.INCOMPATIBLE_ENGINE_PROTOCOL),
        (("engine-a", "protocol-a", "v2"), ExecutionErrorCode.UNKNOWN_ADAPTER_VERSION),
    ],
    ids=["engine", "protocol", "adapter-version"],
)
def test_same_factory_cannot_register_to_multiple_exact_triples(
    second_triple,
    resolution_error,
):
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    for engine_id in ("engine-a", "engine-b"):
        engines.register(EngineDescriptor(engine_id=engine_id))
    for protocol_id in ("protocol-a", "protocol-b"):
        protocols.register(ProtocolDescriptor(protocol_id=protocol_id))
    adapters = AdapterRegistry(engines, protocols)
    created: list[StubAdapter] = []
    factory = recording_factory("engine-a", "protocol-a", "v1", created)
    first_triple = ("engine-a", "protocol-a", "v1")
    register_one(adapters, factory)

    with pytest.raises(ConfigurationError) as caught:
        adapters.register(AdapterDescriptor(**dict(zip(IDENTITY_FIELDS, second_triple))), factory)

    assert_configuration_error(caught, ExecutionErrorCode.DUPLICATE_ADAPTER)
    assert caught.value.error.details == ExecutionErrorDetails(
        engine_id=second_triple[0],
        protocol_id=second_triple[1],
        adapter_version=second_triple[2],
    )
    assert created == []
    assert isinstance(adapters.resolve(*first_triple), StubAdapter)
    assert len(created) == 1
    with pytest.raises(ConfigurationError) as unresolved:
        adapters.resolve(*second_triple)
    assert_configuration_error(unresolved, resolution_error)
    assert len(created) == 1


class CustomEqualFactory:
    def __init__(self, adapter_version: str) -> None:
        self.adapter_version = adapter_version

    def __call__(self) -> StubAdapter:
        return StubAdapter(adapter_version=self.adapter_version)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CustomEqualFactory)


def test_distinct_factories_are_not_rejected_when_custom_equality_says_equal():
    _, _, adapters = simple_registries()
    first_factory = CustomEqualFactory("v1")
    second_factory = CustomEqualFactory("v2")
    assert first_factory == second_factory

    register_one(adapters, first_factory)
    adapters.register(
        AdapterDescriptor(
            engine_id="engine-a",
            protocol_id="protocol-a",
            adapter_version="v2",
        ),
        second_factory,
    )

    first = adapters.resolve("engine-a", "protocol-a", "v1")
    second = adapters.resolve("engine-a", "protocol-a", "v2")
    assert first.adapter_version == "v1"
    assert second.adapter_version == "v2"


async def async_factory() -> StubAdapter:
    return StubAdapter()


class AsyncCallableFactory:
    async def __call__(self) -> StubAdapter:
        return StubAdapter()


class BrokenSignatureFactory:
    @property
    def __signature__(self) -> inspect.Signature:
        raise RuntimeError(SECRET_MARKER)

    def __call__(self) -> StubAdapter:
        return StubAdapter()


async def adapter_coroutine() -> StubAdapter:
    return StubAdapter()


class SynchronousCoroutineFactory:
    def __call__(self) -> object:
        return adapter_coroutine()


@pytest.mark.parametrize(
    "factory",
    [None, 1, "not-callable", async_factory, AsyncCallableFactory()],
    ids=["none", "integer", "string", "async-function", "async-callable"],
)
def test_adapter_registration_rejects_invalid_or_async_factory_without_invocation(factory, recwarn):
    _, _, adapters = simple_registries()
    with pytest.raises(ConfigurationError) as caught:
        register_one(adapters, factory)
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
    assert not [warning for warning in recwarn if warning.category is RuntimeWarning]


@pytest.mark.parametrize(
    "factory",
    [lambda required: StubAdapter(), lambda *, required: StubAdapter()],
    ids=["required-positional", "required-keyword-only"],
)
def test_adapter_registration_rejects_factories_requiring_arguments(factory):
    _, _, adapters = simple_registries()
    with pytest.raises(ConfigurationError) as caught:
        register_one(adapters, factory)
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)


@pytest.mark.parametrize(
    "factory",
    [
        lambda optional=None: StubAdapter(),
        lambda *args: StubAdapter(),
        lambda **kwargs: StubAdapter(),
    ],
    ids=["default", "var-positional", "var-keyword"],
)
def test_adapter_registration_accepts_zero_arg_compatible_signatures(factory):
    _, _, adapters = simple_registries()
    register_one(adapters, factory)
    assert isinstance(adapters.resolve("engine-a", "protocol-a", "v1"), StubAdapter)


def test_adapter_registration_maps_signature_inspection_failure_safely():
    _, _, adapters = simple_registries()
    with pytest.raises(ConfigurationError) as caught:
        register_one(adapters, BrokenSignatureFactory())
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
    rendered = "".join(traceback.format_exception(caught.value))
    assert SECRET_MARKER not in rendered
    assert SECRET_MARKER not in str(caught.value)


def test_adapter_registration_rejects_raw_descriptor_safely():
    _, _, adapters = simple_registries()
    with pytest.raises(ConfigurationError) as caught:
        adapters.register({"engine_id": SECRET_MARKER}, StubAdapter)
    assert_configuration_error(caught, ExecutionErrorCode.INVALID_REQUEST)
    assert SECRET_MARKER not in str(caught.value)


def test_registration_does_not_invoke_factory():
    _, _, adapters = simple_registries()
    created: list[StubAdapter] = []
    register_one(adapters, recording_factory("engine-a", "protocol-a", "v1", created))
    assert created == []


@pytest.mark.parametrize(
    "engine_id,protocol_id,adapter_version",
    [
        ("engine-a", "protocol-a", "v1"),
        ("engine-a", "protocol-a", "v2"),
        ("engine-a", "protocol-b", "v1"),
        ("engine-b", "protocol-a", "v1"),
    ],
)
def test_resolution_returns_the_exact_registered_factory_instance(
    engine_id, protocol_id, adapter_version
):
    adapters, created = build_matrix()
    before = len(created)
    instance = adapters.resolve(engine_id, protocol_id, adapter_version)
    assert instance is created[-1]
    assert len(created) == before + 1
    assert (
        instance.engine_id,
        instance.protocol_id,
        instance.adapter_version,
    ) == (engine_id, protocol_id, adapter_version)


def test_every_resolution_constructs_fresh_state_isolated_instances():
    adapters, created = build_matrix()
    first = adapters.resolve("engine-a", "protocol-a", "v1")
    first.state.append("first-only")
    second = adapters.resolve("engine-a", "protocol-a", "v1")
    assert first is not second
    assert created[-2:] == [first, second]
    assert first.state == ["first-only"]
    assert second.state == []


def test_synchronous_factory_returning_coroutine_is_closed_and_rejected(recwarn):
    _, _, adapters = simple_registries()
    register_one(adapters, SynchronousCoroutineFactory())
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
    gc.collect()
    assert not [
        warning
        for warning in recwarn
        if warning.category is RuntimeWarning and "was never awaited" in str(warning.message)
    ]


@pytest.mark.parametrize(
    "triple,code",
    [
        (("missing-engine", "missing-protocol", "v1"), ExecutionErrorCode.UNKNOWN_ENGINE),
        (("disabled-engine", "missing-protocol", "v1"), ExecutionErrorCode.ENGINE_DISABLED),
        (("engine-a", "missing-protocol", "v1"), ExecutionErrorCode.UNKNOWN_PROTOCOL),
        (("engine-a", "disabled-protocol", "v1"), ExecutionErrorCode.PROTOCOL_DISABLED),
        (("disabled-engine", "disabled-protocol", "v2"), ExecutionErrorCode.ENGINE_DISABLED),
        (("engine-b", "protocol-b", "v1"), ExecutionErrorCode.INCOMPATIBLE_ENGINE_PROTOCOL),
        (("engine-a", "protocol-a", "v3"), ExecutionErrorCode.UNKNOWN_ADAPTER_VERSION),
        (("engine-a", "protocol-b", "v2"), ExecutionErrorCode.ADAPTER_DISABLED),
    ],
)
def test_resolution_error_precedence_including_combined_invalid_cases(triple, code):
    adapters, created = build_matrix()
    before = len(created)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve(*triple)
    assert_configuration_error(caught, code)
    assert len(created) == before


def test_resolution_never_falls_back_to_other_version_protocol_or_engine():
    adapters, created = build_matrix()
    before = len(created)
    for triple, code in (
        (("engine-a", "protocol-a", "v3"), ExecutionErrorCode.UNKNOWN_ADAPTER_VERSION),
        (("engine-b", "protocol-b", "v1"), ExecutionErrorCode.INCOMPATIBLE_ENGINE_PROTOCOL),
        (("engine-a", "missing-protocol", "v1"), ExecutionErrorCode.UNKNOWN_PROTOCOL),
        (("missing-engine", "protocol-a", "v1"), ExecutionErrorCode.UNKNOWN_ENGINE),
    ):
        with pytest.raises(ConfigurationError) as caught:
            adapters.resolve(*triple)
        assert_configuration_error(caught, code)
    assert len(created) == before


@pytest.mark.parametrize(
    "triple",
    [
        (None, "protocol-a", "v1"),
        ([], "protocol-a", "v1"),
        ({}, "protocol-a", "v1"),
        ("Upper", "protocol-a", "v1"),
        ("engine-a", None, "v1"),
        ("engine-a", [], "v1"),
        ("engine-a", "bad.protocol", "v1"),
        ("engine-a", "protocol-a", None),
        ("engine-a", "protocol-a", []),
        ("engine-a", "protocol-a", "latest"),
        ("engine-a", "protocol-a", "v0"),
        ("engine-a", "protocol-a", "v01"),
        ("engine-a", "protocol-a", 1),
    ],
    ids=lambda value: type(value).__name__ if not isinstance(value, str) else value,
)
def test_malformed_or_unhashable_resolution_inputs_fail_closed(triple):
    adapters, created = build_matrix()
    before = len(created)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve(*triple)
    assert_configuration_error(caught, ExecutionErrorCode.INVALID_REQUEST)
    assert len(created) == before


@pytest.mark.parametrize("mode", ["unknown", "safe"])
def test_factory_failures_are_safe_and_suppress_original_traceback_context(mode):
    _, _, adapters = simple_registries()

    def failing_factory() -> StubAdapter:
        if mode == "unknown":
            raise RuntimeError(SECRET_MARKER)
        safe_error = ExecutionError(category="workspace_error", code="workspace_error")
        try:
            raise RuntimeError(SECRET_MARKER)
        except RuntimeError as original:
            raise AdapterExecutionError(safe_error) from original

    register_one(adapters, failing_factory)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_FACTORY_FAILED)
    error = caught.value
    rendered = "".join(traceback.format_exception(error))
    serialized = error.error.model_dump_json()
    for exposed in (str(error), repr(error), str(error.error.model_dump()), serialized, rendered):
        assert SECRET_MARKER not in exposed
    assert "RuntimeError" not in rendered
    assert error.__suppress_context__ is True
    assert error.__cause__ is None
    assert error.error.details == ExecutionErrorDetails(
        engine_id="engine-a",
        protocol_id="protocol-a",
        adapter_version="v1",
    )


class ControlFlow(BaseException):
    pass


@pytest.mark.parametrize(
    "exception",
    [asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(), GeneratorExit(), ControlFlow()],
    ids=["cancelled", "keyboard-interrupt", "system-exit", "generator-exit", "base-exception"],
)
def test_factory_control_flow_base_exceptions_propagate_unchanged(exception):
    _, _, adapters = simple_registries()

    def control_flow_factory() -> StubAdapter:
        raise exception

    register_one(adapters, control_flow_factory)
    with pytest.raises(type(exception)) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert caught.value is exception


@pytest.mark.parametrize(
    "field,value",
    [("engine_id", "other"), ("protocol_id", "other"), ("adapter_version", "v2")],
)
def test_each_identity_field_mismatch_is_rejected_before_instance_escape(field, value):
    _, _, adapters = simple_registries()
    values = {"engine_id": "engine-a", "protocol_id": "protocol-a", "adapter_version": "v1"}
    values[field] = value
    register_one(adapters, lambda: StubAdapter(**values))
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_IDENTITY_MISMATCH)


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
@pytest.mark.parametrize("value", [None, 1, ""])
def test_missing_malformed_identity_values_are_rejected(field, value):
    _, _, adapters = simple_registries()
    values = {"engine_id": "engine-a", "protocol_id": "protocol-a", "adapter_version": "v1"}
    values[field] = value
    register_one(adapters, lambda: StubAdapter(**values))
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_IDENTITY_MISMATCH)


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_each_missing_identity_attribute_is_rejected(field):
    _, _, adapters = simple_registries()
    case_type = adapter_class(missing=(field,))
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_IDENTITY_MISMATCH)


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_identity_property_access_failure_is_safe(field):
    _, _, adapters = simple_registries()

    def broken_property(self) -> str:
        raise RuntimeError(SECRET_MARKER)

    case_type = adapter_class(overrides={field: property(broken_property)})
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_IDENTITY_MISMATCH)
    rendered = "".join(traceback.format_exception(caught.value))
    assert SECRET_MARKER not in rendered
    assert SECRET_MARKER not in str(caught.value)


class ComparisonFailure(str):
    def __eq__(self, other: object) -> bool:
        raise RuntimeError(SECRET_MARKER)

    def __ne__(self, other: object) -> bool:
        raise RuntimeError(SECRET_MARKER)


def test_identity_comparison_failure_is_safe_and_suppresses_context():
    _, _, adapters = simple_registries()
    register_one(adapters, lambda: StubAdapter(engine_id=ComparisonFailure("engine-a")))
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_IDENTITY_MISMATCH)
    rendered = "".join(traceback.format_exception(caught.value))
    assert SECRET_MARKER not in rendered
    assert SECRET_MARKER not in str(caught.value)
    assert "RuntimeError" not in rendered
    assert caught.value.__suppress_context__ is True
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("method_name", LIFECYCLE_METHODS)
def test_each_missing_lifecycle_method_is_rejected(method_name, recwarn):
    _, _, adapters = simple_registries()
    case_type = adapter_class(missing=(method_name,))
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
    assert not [warning for warning in recwarn if warning.category is RuntimeWarning]


@pytest.mark.parametrize("method_name", LIFECYCLE_METHODS)
def test_each_noncallable_lifecycle_method_is_rejected(method_name):
    _, _, adapters = simple_registries()
    case_type = adapter_class(overrides={method_name: None})
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)


@pytest.mark.parametrize("method_name", ASYNC_METHODS)
def test_async_contract_methods_reject_regular_function_shape(method_name):
    _, _, adapters = simple_registries()

    def synchronous_method(*args, **kwargs):
        raise AssertionError("resolution must not execute lifecycle methods")

    case_type = adapter_class(overrides={method_name: synchronous_method})
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)


def test_coroutine_function_stream_events_is_rejected_without_coroutine_leak(recwarn):
    _, _, adapters = simple_registries()

    async def async_stream_events(self, handle):
        raise AssertionError("resolution must not execute stream_events")

    case_type = adapter_class(overrides={"stream_events": async_stream_events})
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
    assert not [warning for warning in recwarn if warning.category is RuntimeWarning]


def test_compliant_resolution_does_not_execute_any_lifecycle_method(recwarn):
    _, _, adapters = simple_registries()
    register_one(adapters)
    instance = adapters.resolve("engine-a", "protocol-a", "v1")
    assert isinstance(instance, StubAdapter)
    assert inspect.iscoroutinefunction(instance.get_capabilities)
    assert not inspect.iscoroutinefunction(instance.stream_events)
    assert not [warning for warning in recwarn if warning.category is RuntimeWarning]


def inspection_target() -> None:
    raise AssertionError("resolution must not execute lifecycle methods")


async def async_inspection_target() -> None:
    raise AssertionError("resolution must not execute lifecycle methods")


class CodeInspectionFailure(functools.partial):
    def __new__(cls, exception: BaseException):
        return super().__new__(cls, inspection_target)

    def __init__(self, exception: BaseException) -> None:
        self.exception = exception

    @property
    def func(self):
        raise self.exception


class SignatureInspectionFailure(functools.partial):
    def __new__(cls, exception: BaseException):
        return super().__new__(cls, async_inspection_target)

    def __init__(self, exception: BaseException) -> None:
        self.exception = exception

    @property
    def __signature__(self) -> inspect.Signature:
        raise self.exception


class InspectionFailureDescriptor:
    def __init__(self, bound_method: object) -> None:
        self.bound_method = bound_method

    def __get__(self, instance: object, owner: type) -> object:
        return self.bound_method


@pytest.mark.parametrize("method_name", LIFECYCLE_METHODS)
def test_lifecycle_shape_inspection_failures_are_safe(method_name):
    _, _, adapters = simple_registries()
    descriptor = InspectionFailureDescriptor(CodeInspectionFailure(RuntimeError(SECRET_MARKER)))
    case_type = adapter_class(overrides={method_name: descriptor})
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
    rendered = "".join(traceback.format_exception(caught.value))
    assert SECRET_MARKER not in rendered
    assert SECRET_MARKER not in str(caught.value)
    assert "RuntimeError" not in rendered
    assert caught.value.__suppress_context__ is True
    assert caught.value.__cause__ is None


def test_lifecycle_signature_inspection_failure_is_safe():
    _, _, adapters = simple_registries()
    descriptor = InspectionFailureDescriptor(
        SignatureInspectionFailure(RuntimeError(SECRET_MARKER))
    )
    case_type = adapter_class(overrides={"get_capabilities": descriptor})
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
    rendered = "".join(traceback.format_exception(caught.value))
    assert SECRET_MARKER not in rendered
    assert SECRET_MARKER not in str(caught.value)
    assert "RuntimeError" not in rendered
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("exception", [ControlFlow(), asyncio.CancelledError()])
def test_lifecycle_inspection_base_exceptions_propagate_unchanged(exception):
    _, _, adapters = simple_registries()
    descriptor = InspectionFailureDescriptor(CodeInspectionFailure(exception))
    case_type = adapter_class(overrides={"get_capabilities": descriptor})
    register_one(adapters, case_type)
    with pytest.raises(type(exception)) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert caught.value is exception


def wrong_arity_override(method_name: str, arity: str):
    if method_name == "stream_events":
        if arity == "missing":

            def method(self):
                raise AssertionError("resolution must not execute lifecycle methods")

        else:

            def method(self, handle, extra):
                raise AssertionError("resolution must not execute lifecycle methods")

    elif method_name == "get_capabilities":

        async def method(self, required):
            raise AssertionError("resolution must not execute lifecycle methods")

    elif arity == "missing":

        async def method(self):
            raise AssertionError("resolution must not execute lifecycle methods")

    else:

        async def method(self, handle, extra):
            raise AssertionError("resolution must not execute lifecycle methods")

    return method


WRONG_ARITY_CASES = [
    ("get_capabilities", "extra"),
    *[
        (method_name, arity)
        for method_name in ("start", "stream_events", "cancel", "collect_result")
        for arity in ("missing", "extra")
    ],
]


@pytest.mark.parametrize("method_name,arity", WRONG_ARITY_CASES)
def test_each_lifecycle_method_rejects_wrong_bound_arity(method_name, arity):
    _, _, adapters = simple_registries()
    override = wrong_arity_override(method_name, arity)
    case_type = adapter_class(overrides={method_name: override})
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)


class OptionalSignatureAdapter(StubAdapter):
    async def get_capabilities(self, optional: object | None = None) -> EngineCapabilities:
        raise AssertionError("resolution must not execute get_capabilities")

    async def start(self, request: object | None = None) -> ExecutionHandle:
        raise AssertionError("resolution must not execute start")

    def stream_events(self, handle: object | None = None) -> AsyncIterator[AgentEvent]:
        raise AssertionError("resolution must not execute stream_events")

    async def cancel(self, handle: object | None = None) -> None:
        raise AssertionError("resolution must not execute cancel")

    async def collect_result(self, handle: object | None = None) -> ExecutionResult:
        raise AssertionError("resolution must not execute collect_result")


def test_zero_and_one_arg_compatible_lifecycle_signatures_remain_valid():
    _, _, adapters = simple_registries()
    register_one(adapters, OptionalSignatureAdapter)
    assert isinstance(adapters.resolve("engine-a", "protocol-a", "v1"), OptionalSignatureAdapter)


def test_live_singleton_result_is_rejected_on_second_resolution():
    _, _, adapters = simple_registries()
    singleton = StubAdapter()
    register_one(adapters, lambda: singleton)
    first = adapters.resolve("engine-a", "protocol-a", "v1")
    assert first is singleton
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)


def test_live_a_b_a_cycle_is_rejected_on_third_resolution():
    _, _, adapters = simple_registries()
    instances = [StubAdapter(), StubAdapter()]
    resolutions = iter((instances[0], instances[1], instances[0]))
    register_one(adapters, lambda: next(resolutions))
    first = adapters.resolve("engine-a", "protocol-a", "v1")
    second = adapters.resolve("engine-a", "protocol-a", "v1")
    assert first is instances[0]
    assert second is instances[1]
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)


def test_non_weak_referenceable_candidate_is_rejected_before_first_return():
    _, _, adapters = simple_registries()
    case_type = adapter_class(
        overrides={"__slots__": ("_engine_id", "_protocol_id", "_adapter_version", "state")}
    )
    register_one(adapters, case_type)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)


class EqualityFailureAdapter(StubAdapter):
    def __eq__(self, other: object) -> bool:
        raise AssertionError("registry freshness must compare only with is")


def test_freshness_never_invokes_adapter_equality():
    _, _, adapters = simple_registries()
    register_one(adapters, EqualityFailureAdapter)
    first = adapters.resolve("engine-a", "protocol-a", "v1")
    first.state.append("first-only")
    second = adapters.resolve("engine-a", "protocol-a", "v1")
    assert first is not second
    assert first.state == ["first-only"]
    assert second.state == []


def test_registry_weakrefs_do_not_retain_adapters_and_dead_refs_are_pruned():
    _, _, adapters = simple_registries()
    register_one(adapters, StubAdapter)
    triple = ("engine-a", "protocol-a", "v1")

    first = adapters.resolve(*triple)
    first_reference = weakref.ref(first)
    assert len(adapters._returned_instances[triple]) == 1
    del first
    gc.collect()
    assert first_reference() is None

    second = adapters.resolve(*triple)
    second_reference = weakref.ref(second)
    assert len(adapters._returned_instances[triple]) == 1
    assert adapters._returned_instances[triple][0]() is second
    del second
    gc.collect()
    assert second_reference() is None

    third = adapters.resolve(*triple)
    third_reference = weakref.ref(third)
    assert len(adapters._returned_instances[triple]) == 1
    del third
    gc.collect()
    assert third_reference() is None


@pytest.mark.parametrize(
    "exception",
    [RuntimeError(SECRET_MARKER), ControlFlow(), asyncio.CancelledError()],
    ids=["exception", "base-exception", "cancelled"],
)
def test_weakref_tracking_failures_are_safe_or_propagate(exception, monkeypatch):
    _, _, adapters = simple_registries()
    register_one(adapters, StubAdapter)

    def failed_reference(instance: object) -> weakref.ReferenceType:
        raise exception

    monkeypatch.setattr(adapter_registry_module, "ref", failed_reference, raising=False)
    expected_exception = ConfigurationError if isinstance(exception, Exception) else type(exception)
    with pytest.raises(expected_exception) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    if isinstance(exception, Exception):
        assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
        rendered = "".join(traceback.format_exception(caught.value))
        assert SECRET_MARKER not in rendered
        assert SECRET_MARKER not in str(caught.value)
        assert "RuntimeError" not in rendered
    else:
        assert caught.value is exception


def test_future_returning_factory_is_rejected_and_future_is_cancelled():
    _, _, adapters = simple_registries()
    loop = asyncio.new_event_loop()
    future = loop.create_future()

    def factory() -> object:
        return future

    try:
        register_one(adapters, factory)
        with pytest.raises(ConfigurationError) as caught:
            adapters.resolve("engine-a", "protocol-a", "v1")
        assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
        assert future.cancelled() is True
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_task_returning_factory_is_rejected_and_task_is_cleaned_up():
    _, _, adapters = simple_registries()

    async def wait_forever() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(wait_forever())
    register_one(adapters, lambda: task)
    with pytest.raises(ConfigurationError) as caught:
        adapters.resolve("engine-a", "protocol-a", "v1")
    assert_configuration_error(caught, ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled() is True
    assert task.done() is True
    current = asyncio.current_task()
    assert task not in [
        item for item in asyncio.all_tasks() if item is not current and not item.done()
    ]


def test_current_t2_and_t3_modules_have_exact_scope_and_one_directional_dependencies():
    package_root = (
        Path(__file__).parents[1] / "src" / "agent_platform" / "core_platform" / "agent_execution"
    )
    expected_contract_modules = {
        "__init__.py",
        "contracts/__init__.py",
        "contracts/base.py",
        "contracts/common.py",
        "contracts/request.py",
        "contracts/handle.py",
        "contracts/result.py",
        "contracts/events.py",
        "contracts/capabilities.py",
        "contracts/errors.py",
        "contracts/adapter.py",
    }
    expected_registry_modules = {
        "registry/__init__.py",
        "registry/engine_registry.py",
        "registry/protocol_registry.py",
        "registry/adapter_registry.py",
    }
    expected_modules = expected_contract_modules | expected_registry_modules
    actual_contract_modules = {
        str(path.relative_to(package_root)) for path in (package_root / "contracts").glob("*.py")
    } | {"__init__.py"}
    actual_registry_modules = {
        str(path.relative_to(package_root)) for path in (package_root / "registry").glob("*.py")
    }
    assert actual_contract_modules == expected_contract_modules
    assert actual_registry_modules == expected_registry_modules

    common_forbidden = (
        ".worker",
        ".repository",
        ".factory",
        "business_capabilities",
        "applications",
        "agent_runtime",
        "langgraph",
        "langchain",
        "openai",
    )
    for relative_path in sorted(expected_modules):
        source_file = package_root / relative_path
        assert source_file.is_file(), relative_path
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        imports: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend((alias.name, 0) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((node.module, node.level))
        names = [name for name, _ in imports]
        assert not any(part in name for name in names for part in common_forbidden), (
            relative_path,
            imports,
        )
        if relative_path.startswith("contracts/") or relative_path == "__init__.py":
            forbidden = (*common_forbidden, ".registry", ".adapters")
            assert not any(part in name for name in names for part in forbidden), (
                relative_path,
                imports,
            )
        if relative_path in expected_registry_modules - {"registry/__init__.py"}:
            forbidden = (*common_forbidden, ".adapters", ".testing")
            assert not any(part in name for name in names for part in forbidden), (
                relative_path,
                imports,
            )
            assert any(level == 2 and name.startswith("contracts") for name, level in imports), (
                relative_path
            )
        if relative_path == "registry/adapter_registry.py":
            assert not any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "id"
                for node in ast.walk(tree)
            )
        extension_imports = [
            name for name in names if name.startswith("agent_platform.extension_contracts")
        ]
        assert all(name == "agent_platform.extension_contracts.base" for name in extension_imports)

    assert not hasattr(execution_package, "LocalTestAdapter")
    assert not hasattr(registry_package, "LocalTestAdapter")
