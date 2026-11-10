"""Exact engine/protocol/version registration and safe adapter resolution."""

import asyncio
import inspect
from collections.abc import Callable
from contextlib import suppress
from typing import cast
from weakref import ReferenceType, ref

from pydantic import ConfigDict, TypeAdapter, ValidationError

from ..contracts.adapter import AgentEngineAdapter
from ..contracts.base import ExecutionContractModel
from ..contracts.common import AdapterVersion, EngineId, ProtocolId
from ..contracts.errors import (
    ConfigurationError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionErrorDetails,
)
from .engine_registry import EngineRegistry
from .protocol_registry import ProtocolRegistry

_ENGINE_ID_ADAPTER = TypeAdapter(EngineId, config=ConfigDict(strict=True))
_PROTOCOL_ID_ADAPTER = TypeAdapter(ProtocolId, config=ConfigDict(strict=True))
_ADAPTER_VERSION_ADAPTER = TypeAdapter(AdapterVersion, config=ConfigDict(strict=True))
_ASYNC_METHODS = ("get_capabilities", "start", "cancel", "collect_result")
_SIGNATURE_PLACEHOLDER = object()


class AdapterDescriptor(ExecutionContractModel):
    """Registration metadata for one exact engine/protocol/version triple."""

    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    enabled: bool = True


def _configuration_error(
    code: ExecutionErrorCode,
    *,
    engine_id: str | None = None,
    protocol_id: str | None = None,
    adapter_version: str | None = None,
) -> ConfigurationError:
    return ConfigurationError(
        ExecutionError(
            category=ExecutionErrorCategory.CONFIGURATION_ERROR,
            code=code,
            details=ExecutionErrorDetails(
                engine_id=engine_id,
                protocol_id=protocol_id,
                adapter_version=adapter_version,
            ),
        )
    )


def _validated_resolution_identity(
    engine_id: str,
    protocol_id: str,
    adapter_version: str,
) -> tuple[str, str, str]:
    try:
        return (
            _ENGINE_ID_ADAPTER.validate_python(engine_id),
            _PROTOCOL_ID_ADAPTER.validate_python(protocol_id),
            _ADAPTER_VERSION_ADAPTER.validate_python(adapter_version),
        )
    except (ValidationError, TypeError, ValueError):
        raise _configuration_error(ExecutionErrorCode.INVALID_REQUEST) from None


def _is_async_callable(factory: Callable[[], AgentEngineAdapter]) -> bool:
    methods = (factory, factory.__call__)
    return any(
        inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(method)
        for method in methods
    )


def _validate_adapter_identity(
    instance: object,
    descriptor: AdapterDescriptor,
) -> None:
    expected = (
        descriptor.engine_id,
        descriptor.protocol_id,
        descriptor.adapter_version,
    )
    try:
        actual = (
            instance.engine_id,
            instance.protocol_id,
            instance.adapter_version,
        )
        identity_matches = all(isinstance(value, str) for value in actual) and actual == expected
    except Exception:  # noqa: BLE001 - identity access and comparison are safe boundaries.
        raise _configuration_error(
            ExecutionErrorCode.ADAPTER_IDENTITY_MISMATCH,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
        ) from None
    if not identity_matches:
        raise _configuration_error(
            ExecutionErrorCode.ADAPTER_IDENTITY_MISMATCH,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
        )


def _ensure_synchronous_factory_result(
    instance: object,
    descriptor: AdapterDescriptor,
) -> None:
    if not inspect.isawaitable(instance):
        return
    with suppress(Exception):
        if inspect.iscoroutine(instance):
            instance.close()
        elif isinstance(instance, asyncio.Future):
            instance.cancel()
    raise _configuration_error(
        ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH,
        engine_id=descriptor.engine_id,
        protocol_id=descriptor.protocol_id,
        adapter_version=descriptor.adapter_version,
    ) from None


def _validate_adapter_contract(
    instance: object,
    descriptor: AdapterDescriptor,
) -> None:
    try:
        async_methods = [getattr(instance, name) for name in _ASYNC_METHODS]
        stream_events = instance.stream_events
        valid_async_methods = all(
            callable(method) and inspect.iscoroutinefunction(method) for method in async_methods
        )
        valid_stream_events = callable(stream_events) and not inspect.iscoroutinefunction(
            stream_events
        )
        if valid_async_methods:
            inspect.signature(async_methods[0]).bind()
            for method in async_methods[1:]:
                inspect.signature(method).bind(_SIGNATURE_PLACEHOLDER)
        if valid_stream_events:
            inspect.signature(stream_events).bind(_SIGNATURE_PLACEHOLDER)
    except Exception:  # noqa: BLE001 - method access and inspection are safe boundaries.
        raise _configuration_error(
            ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
        ) from None
    if not valid_async_methods or not valid_stream_events:
        raise _configuration_error(
            ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
        )


def _track_returned_instance(
    instance: AgentEngineAdapter,
    descriptor: AdapterDescriptor,
    previous_references: list[ReferenceType[AgentEngineAdapter]],
) -> None:
    try:
        live_references: list[ReferenceType[AgentEngineAdapter]] = []
        repeated_instance = False
        for reference in previous_references:
            previous = reference()
            if previous is None:
                continue
            live_references.append(reference)
            if previous is instance:
                repeated_instance = True
        previous_references[:] = live_references
        if not repeated_instance:
            previous_references.append(ref(instance))
    except Exception:  # noqa: BLE001 - weakref tracking is a safe registry boundary.
        raise _configuration_error(
            ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
        ) from None
    if repeated_instance:
        raise _configuration_error(
            ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
        )


class AdapterRegistry:
    """Store one synchronous factory per exact adapter identity triple."""

    def __init__(
        self,
        engines: EngineRegistry,
        protocols: ProtocolRegistry,
    ) -> None:
        self._engines = engines
        self._protocols = protocols
        self._registrations: dict[
            tuple[str, str, str],
            tuple[AdapterDescriptor, Callable[[], AgentEngineAdapter]],
        ] = {}
        self._returned_instances: dict[
            tuple[str, str, str],
            list[ReferenceType[AgentEngineAdapter]],
        ] = {}

    def register(
        self,
        descriptor: AdapterDescriptor,
        factory: Callable[[], AgentEngineAdapter],
    ) -> None:
        """Register a factory without invoking it or probing external systems."""
        if not isinstance(descriptor, AdapterDescriptor):
            raise _configuration_error(ExecutionErrorCode.INVALID_REQUEST)
        triple = (
            descriptor.engine_id,
            descriptor.protocol_id,
            descriptor.adapter_version,
        )
        if triple in self._registrations:
            raise _configuration_error(
                ExecutionErrorCode.DUPLICATE_ADAPTER,
                engine_id=descriptor.engine_id,
                protocol_id=descriptor.protocol_id,
                adapter_version=descriptor.adapter_version,
            )
        if any(
            registered_factory is factory for _, registered_factory in self._registrations.values()
        ):
            raise _configuration_error(
                ExecutionErrorCode.DUPLICATE_ADAPTER,
                engine_id=descriptor.engine_id,
                protocol_id=descriptor.protocol_id,
                adapter_version=descriptor.adapter_version,
            )
        try:
            invalid_factory = not callable(factory) or _is_async_callable(factory)
            if not invalid_factory:
                inspect.signature(factory).bind()
        except Exception:  # noqa: BLE001 - callable inspection must fail safely.
            raise _configuration_error(
                ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH,
                engine_id=descriptor.engine_id,
                protocol_id=descriptor.protocol_id,
                adapter_version=descriptor.adapter_version,
            ) from None
        if invalid_factory:
            raise _configuration_error(
                ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH,
                engine_id=descriptor.engine_id,
                protocol_id=descriptor.protocol_id,
                adapter_version=descriptor.adapter_version,
            )
        if self._engines.get(descriptor.engine_id) is None:
            raise _configuration_error(
                ExecutionErrorCode.UNKNOWN_ENGINE,
                engine_id=descriptor.engine_id,
            )
        if self._protocols.get(descriptor.protocol_id) is None:
            raise _configuration_error(
                ExecutionErrorCode.UNKNOWN_PROTOCOL,
                engine_id=descriptor.engine_id,
                protocol_id=descriptor.protocol_id,
            )
        self._registrations[triple] = (descriptor, factory)
        self._returned_instances[triple] = []

    def resolve(
        self,
        engine_id: str,
        protocol_id: str,
        adapter_version: str,
    ) -> AgentEngineAdapter:
        """Resolve only the exact enabled triple and construct a fresh adapter."""
        engine_id, protocol_id, adapter_version = _validated_resolution_identity(
            engine_id,
            protocol_id,
            adapter_version,
        )
        engine = self._engines.get(engine_id)
        if engine is None:
            raise _configuration_error(ExecutionErrorCode.UNKNOWN_ENGINE, engine_id=engine_id)
        if not engine.enabled:
            raise _configuration_error(ExecutionErrorCode.ENGINE_DISABLED, engine_id=engine_id)
        protocol = self._protocols.get(protocol_id)
        if protocol is None:
            raise _configuration_error(
                ExecutionErrorCode.UNKNOWN_PROTOCOL,
                engine_id=engine_id,
                protocol_id=protocol_id,
            )
        if not protocol.enabled:
            raise _configuration_error(
                ExecutionErrorCode.PROTOCOL_DISABLED,
                engine_id=engine_id,
                protocol_id=protocol_id,
            )

        pair = (engine_id, protocol_id)
        if not any(triple[:2] == pair for triple in self._registrations):
            raise _configuration_error(
                ExecutionErrorCode.INCOMPATIBLE_ENGINE_PROTOCOL,
                engine_id=engine_id,
                protocol_id=protocol_id,
            )
        triple = (engine_id, protocol_id, adapter_version)
        registration = self._registrations.get(triple)
        if registration is None:
            raise _configuration_error(
                ExecutionErrorCode.UNKNOWN_ADAPTER_VERSION,
                engine_id=engine_id,
                protocol_id=protocol_id,
                adapter_version=adapter_version,
            )
        descriptor, factory = registration
        if not descriptor.enabled:
            raise _configuration_error(
                ExecutionErrorCode.ADAPTER_DISABLED,
                engine_id=engine_id,
                protocol_id=protocol_id,
                adapter_version=adapter_version,
            )
        try:
            instance = factory()
        except Exception:  # noqa: BLE001 - all factory failures use the safe catalog error.
            raise _configuration_error(
                ExecutionErrorCode.ADAPTER_FACTORY_FAILED,
                engine_id=engine_id,
                protocol_id=protocol_id,
                adapter_version=adapter_version,
            ) from None
        _ensure_synchronous_factory_result(instance, descriptor)
        _validate_adapter_identity(instance, descriptor)
        _validate_adapter_contract(instance, descriptor)
        adapter = cast(AgentEngineAdapter, instance)
        _track_returned_instance(adapter, descriptor, self._returned_instances[triple])
        return adapter
