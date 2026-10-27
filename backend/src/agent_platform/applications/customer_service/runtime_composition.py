"""Application composition root for Runtime and platform services.

This module belongs to ``apps`` intentionally. Runtime implementation modules
must not import application composition code; applications assemble the core
runtime, platform services, and business capabilities here.
"""

import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from asyncpg import PostgresError
from sqlalchemy.exc import SQLAlchemyError

from agent_platform.business_capabilities.approval.capability import ApprovalCapability
from agent_platform.business_capabilities.customer_service.capability import (
    CustomerServiceCapability,
)
from agent_platform.business_capabilities.evaluation.service import EvaluationService
from agent_platform.business_capabilities.knowledge.capability import KnowledgeCapability
from agent_platform.business_capabilities.memory.capability import MemoryCapability
from agent_platform.business_capabilities.memory.store import build_memory_store
from agent_platform.core_platform.agent_runtime.admission import RuntimeAdmission
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.notify import Listener, Notifier
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker
from agent_platform.core_platform.extension_platform import (
    CapabilityConfigService,
    CapabilityContributionRegistry,
    CapabilityImplementationRegistry,
    CapabilityRegistry,
    CapabilityRuntimeStateService,
    ExtensionRegistryError,
    PluginDiscoveryResult,
    UiExtensionRegistry,
    register_builtin_capabilities,
    register_builtin_ui_extensions,
)
from agent_platform.core_platform.platform_services.model_gateway.service import build_model
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway
from agent_platform.extension_contracts import EventPublisher, IdentityBindings

from .platform_services import PlatformServices
from .runtime_factory import RuntimeFactory
from .service_groups import (
    PlatformServiceGroups,
    build_runtime_bindings,
    build_service_groups,
)
from .trusted_extensions import register_trusted_external_bindings

logger = logging.getLogger(__name__)


@dataclass
class RuntimeServices:
    """All resources owned by one application process."""

    repository: RunRepository
    worker: RuntimeWorker
    snapshot: dict[str, object]
    listener: Listener
    notifier: Notifier
    groups: PlatformServiceGroups
    identity: IdentityBindings
    admission: RuntimeAdmission
    extensions: CapabilityRegistry
    capability_config: CapabilityConfigService
    capability_state: CapabilityRuntimeStateService
    ui_extensions: UiExtensionRegistry
    contributions: CapabilityContributionRegistry
    events: EventPublisher
    extension_discovery: tuple[PluginDiscoveryResult, ...]


@asynccontextmanager
async def runtime_services(settings: Settings) -> AsyncIterator[RuntimeServices]:
    """Assemble the Runtime and all platform capabilities for an application."""

    specs = (
        [
            HttpTool.model_validate(item)
            for item in json.loads(settings.tools_file.read_text(encoding="utf-8"))
        ]
        if settings.tools_file
        else []
    )
    public = settings.model_dump(
        mode="json",
        exclude={
            "knowledge_s3_access_key",
            "knowledge_s3_secret_key",
            "milvus_token",
            "database_url",
            "api_token",
            "operator_api_token",
            "viewer_api_token",
            "model_api_key",
            "embedded_worker",
            "worker_concurrency",
            "database_pool_size",
        },
    )
    public["tools"] = [spec.model_dump(mode="json") for spec in specs]
    fingerprint = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
    snapshot = {
        "fingerprint": fingerprint,
        "model_backend": settings.model_backend,
        "model_name": settings.model_name,
    }
    engine = create_engine(settings)
    dsn = settings.database_url.get_secret_value()
    listener = Listener(dsn)
    notifier = Notifier(dsn)
    extensions = CapabilityRegistry(
        lifecycle_timeout_seconds=settings.extension_lifecycle_timeout_seconds
    )
    capability_config = CapabilityConfigService(engine, extensions)
    capability_state = CapabilityRuntimeStateService(engine, extensions)
    ui_extensions = UiExtensionRegistry()
    contributions = CapabilityContributionRegistry(extensions, ui_extensions)
    implementation_registry = CapabilityImplementationRegistry()
    extension_discovery: tuple[PluginDiscoveryResult, ...] = ()
    extensions_started = False
    try:
        async with (
            httpx.AsyncClient(
                trust_env=False, limits=httpx.Limits(max_connections=settings.tool_concurrency)
            ) as client,
            httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=settings.model_timeout_seconds,
                limits=httpx.Limits(max_connections=settings.model_gateway_concurrency * 6),
            ) as model_client,
        ):
            tools = ToolGateway(client, specs, settings.tool_concurrency)
            model = build_model(settings, tools.schemas)
            runtime = RuntimeEngine(model, tools, settings)
            repository = RunRepository(engine)
            platform = PlatformServices(
                engine,
                repository,
                settings,
                snapshot,
                specs,
                model_client,
                contributions,
            )
            platform.extensions = extensions
            platform.ui_extensions = ui_extensions
            register_builtin_capabilities(
                extensions,
                {
                    "knowledge": KnowledgeCapability(platform.event_bus),
                    "customer-service": CustomerServiceCapability(platform.event_bus),
                    "memory": MemoryCapability(platform.event_bus),
                    "approval": ApprovalCapability(platform.event_bus),
                },
            )
            register_trusted_external_bindings(implementation_registry, platform)
            if settings.external_plugin_directory is not None:
                discovery_results = list(
                    extensions.register_manifest_directory(
                        settings.external_plugin_directory,
                        implementation_registry=implementation_registry,
                        require_implementation=True,
                        require_contribution_binding=True,
                    )
                )
                extension_discovery = tuple(discovery_results)
            register_builtin_ui_extensions(ui_extensions, contributions)
            try:
                await capability_state.load()
            except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
                logger.warning(
                    "Capability runtime state hydration unavailable during startup (%s)",
                    type(exc).__name__,
                )
            try:
                await capability_config.load()
            except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
                # Keep the process alive long enough for /ready to report the
                # actual dependency outage. This mirrors the memory-store
                # startup probe: a database outage must not turn a useful 503
                # health response into an opaque lifespan exception. Do not
                # include the exception text because database errors can carry
                # connection details.
                logger.warning(
                    "Capability configuration hydration unavailable during startup (%s)",
                    type(exc).__name__,
                )
            # Probe the memory store once at startup; Runtime, the memory worker,
            # and the memory_search tool share this instance.
            platform.memory_store = await build_memory_store(engine, platform.gateway, settings)
            if extension_discovery:
                discovery_results = list(extension_discovery)
                for index, result in enumerate(discovery_results):
                    if result.status != "registered" or result.capability_id is None:
                        continue
                    factory = implementation_registry.contribution_factory(result.capability_id)
                    if factory is None:
                        continue
                    try:
                        contributions.register_bundle(
                            result.capability_id,
                            factory(platform),
                        )
                    except Exception as exc:  # noqa: BLE001 - isolate one trusted extension
                        extensions.quarantine(
                            result.capability_id,
                            f"trusted_contribution_binding_failed:{type(exc).__name__}",
                        )
                        discovery_results[index] = PluginDiscoveryResult(
                            path=result.path,
                            capability_id=result.capability_id,
                            status="rejected",
                            error=(
                                "trusted contribution binding failed: "
                                f"{type(exc).__name__}"
                            ),
                        )
                extension_discovery = tuple(discovery_results)
                for result in extension_discovery:
                    if result.status == "registered":
                        logger.info(
                            "External capability registered: %s",
                            result.capability_id,
                        )
                    else:
                        logger.warning(
                            "External capability rejected: %s (%s)",
                            result.path.name,
                            result.error,
                        )
            platform.bind_tool_contributions()
            platform.channels.bind_listener(listener)
            groups = build_service_groups(platform)
            bindings = build_runtime_bindings(groups)
            factory = RuntimeFactory(runtime, bindings, client, settings, tools.limit)
            platform.evaluation = EvaluationService(engine, platform.agents, factory)
            groups.application.evaluation = platform.evaluation
            identity = IdentityBindings(
                engine=engine,
                enterprise=groups.application.open_platform.enterprise,
            )
            admission = RuntimeAdmission(
                engine,
                repository,
                groups.business.agents,
                settings,
                snapshot,
            )
            # Contributions are attached only after lifecycle startup.  This
            # prevents disabled, degraded, or dependency-blocked capabilities
            # from receiving events during the startup window.
            contributions.validate()
            await extensions.start_all()
            extensions_started = True
            try:
                await capability_state.persist_all("system")
            except ExtensionRegistryError as exc:
                logger.warning(
                    "Capability runtime state persistence unavailable during startup (%s)",
                    str(exc),
                )
            contributions.attach_events(platform.event_bus)
            yield RuntimeServices(
                repository=repository,
                worker=RuntimeWorker(
                    repository,
                    factory,
                    settings,
                    fingerprint,
                    notifier,
                    listener,
                    memory=groups.business.memory,
                ),
                snapshot=snapshot,
                listener=listener,
                notifier=notifier,
                groups=groups,
                identity=identity,
                admission=admission,
                extensions=extensions,
                capability_config=capability_config,
                capability_state=capability_state,
                ui_extensions=ui_extensions,
                contributions=contributions,
                events=platform.event_bus,
                extension_discovery=extension_discovery,
            )
    finally:
        contributions.detach_events()
        if extensions_started:
            await extensions.stop_all()
        await engine.dispose()
        await listener.close()
        await notifier.close()
