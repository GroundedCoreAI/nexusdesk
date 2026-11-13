"""Shared composition root for Runtime and platform services.

Business applications call :func:`runtime_services` with their trusted
extension bindings. Runtime implementation modules must not import application
composition code; applications assemble the core runtime, platform services,
and business capabilities here.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from uuid import UUID, uuid4

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
from agent_platform.business_capabilities.memory.injection import MemoryInjection
from agent_platform.business_capabilities.memory.store import build_memory_store
from agent_platform.core_platform.agent_execution.capability.cache import CapabilityCache
from agent_platform.core_platform.agent_execution.capability.ports import (
    TrustedDeploymentProbe,
    TrustedPolicyProvider,
    WorkspaceAvailabilityPort,
)
from agent_platform.core_platform.agent_execution.capability.production import (
    DeclarationDerivedDeploymentProbe,
    NoTrustedWorkspaceGeneration,
    PlatformDefaultPolicyProvider,
)
from agent_platform.core_platform.agent_execution.capability.resolver import (
    CapabilityResolutionRequest,
    CapabilityResolver,
)
from agent_platform.core_platform.agent_execution.capability.warmer import CapabilityWarmer
from agent_platform.core_platform.agent_execution.contracts.capabilities import (
    NO_EXECUTION_RESTRICTIONS,
    EngineCapabilities,
)
from agent_platform.core_platform.agent_execution.contracts.config import ReactConfig
from agent_platform.core_platform.agent_execution.contracts.instructions import (
    REACT_INSTRUCTION_PROVIDER_ID,
    REACT_INSTRUCTION_PROVIDER_VERSION,
)
from agent_platform.core_platform.agent_execution.contracts.snapshots import SNAPSHOT_COLUMNS
from agent_platform.core_platform.agent_execution.host.local_sandbox_provider import (
    LocalSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.process_registry import ProcessRegistry
from agent_platform.core_platform.agent_execution.host.process_runner import (
    ProcessRunner,
    TrustedTargetRegistry,
)
from agent_platform.core_platform.agent_execution.host.process_supervisor import ProcessSupervisor
from agent_platform.core_platform.agent_execution.host.resource_manager import ResourceManager
from agent_platform.core_platform.agent_execution.host.runtime_host import RuntimeHost
from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
    ExecutionSnapshotBarrier,
)
from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
    ExecutionOrchestrator,
)
from agent_platform.core_platform.agent_execution.registry import (
    AdapterDescriptor,
    AdapterRegistry,
    EngineDescriptor,
    EngineRegistry,
    ProtocolDescriptor,
    ProtocolRegistry,
)
from agent_platform.core_platform.agent_execution.workspace.workspace_manager import (
    ExecutionWorkspaceManager,
)
from agent_platform.core_platform.agent_runtime.admission import RuntimeAdmission
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.notify import Listener, Notifier
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import ExecutionSnapshotPayloads
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
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    TenantScopeService,
)
from agent_platform.core_platform.tool_gateway.egress import (
    ToolEgressPolicy,
    ToolEgressTransport,
)
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway
from agent_platform.extension_contracts import (
    DEFAULT_BUSINESS_ID,
    DEFAULT_WORKSPACE_ID,
    EventPublisher,
    IdentityBindings,
)

from .platform_services import PlatformServices
from .react_adapter_factory import ReactAdapterFactory
from .runtime_factory import RuntimeFactory
from .runtime_hooks import BusinessRuntimePersistenceHooks
from .service_groups import (
    PlatformServiceGroups,
    build_runtime_bindings,
    build_service_groups,
)

logger = logging.getLogger(__name__)
TrustedExtensionBinder = Callable[[CapabilityImplementationRegistry, PlatformServices], None]

# The deployment-level warm-scope components a Run supplies itself. Warm targets
# can only ever describe the deployment, never an Agent, because
# ``PolicyCacheKey`` also carries tenant/business/workspace/agent/published
# components that composition cannot enumerate at startup (R-46); the two scope
# constants are shared with the Worker so the warmed entries and the claimed rows
# cannot drift apart.
_WARM_TENANT_BUSINESS_ID = DEFAULT_BUSINESS_ID
_WARM_TENANT_WORKSPACE_ID = DEFAULT_WORKSPACE_ID


@dataclass(frozen=True, slots=True)
class ExecutionCapabilityPorts:
    """The three trusted ports one composition injects (R-42/R-44).

    Held together so a test substitution replaces all three at once: ports are
    selectable by code only, never by settings or environment (R-44 discipline),
    and a mixed double/production set would produce evidence that no deployment
    shape could ever produce.
    """

    probe: TrustedDeploymentProbe
    policy_provider: TrustedPolicyProvider
    workspace_port: WorkspaceAvailabilityPort


@dataclass(frozen=True, slots=True)
class ExecutionCapabilitySubsystem:
    """The wired Phase 3 capability subsystem one composition owns.

    ``snapshot_max_bytes`` is carried here so P3-IT-19/21 can assert the
    serializer ceiling through a public surface instead of trusting a default;
    ``barrier`` is the write-once snapshot seam, adapted to the repository by
    composition because the execution layer may not import it (R-51).
    """

    resolver: CapabilityResolver
    warmer: CapabilityWarmer
    probe: TrustedDeploymentProbe
    policy_provider: TrustedPolicyProvider
    workspace_port: WorkspaceAvailabilityPort
    warm_targets: tuple[CapabilityResolutionRequest, ...]
    registry: AdapterRegistry
    clock: Callable[[], float]
    barrier: ExecutionSnapshotBarrier
    snapshot_max_bytes: int
    policy_version: str


@dataclass(frozen=True, slots=True)
class _NoSnapshotBarrier:
    """Refuses every write: used when a composition has no snapshot seam at all.

    The off states never reach this object because the Phase 3 barrier does not
    run, and an on-state composition without a repository seam must fail closed
    rather than silently skip the write-once gate (R-8/R-51).
    """

    async def write(
        self,
        *,
        run_id: UUID,
        owner: UUID | None,
        execution_id: UUID,
        payloads: Mapping[str, str],
    ) -> str:
        raise RuntimeError("execution snapshot barrier is not wired")


class _RepositorySnapshotBarrier:
    """Adapt the run repository to the orchestration snapshot seam (R-51).

    ``core_platform`` may not import the repository from the orchestration layer,
    so the adapter lives here, on the application side of the boundary. The
    payloads arrive as the serializer's five canonical strings and are handed to
    the repository's own private DTO, whose entry guard is a second, independent
    gate (R-51): composition never re-implements the cleaning or the identity
    check, and the owner comes from the claimed row, never from a caller.
    """

    def __init__(self, write: Callable[..., Awaitable[object]]) -> None:
        self._write = write

    async def write(
        self,
        *,
        run_id: UUID,
        owner: UUID | None,
        execution_id: UUID,
        payloads: Mapping[str, str],
    ) -> str:
        if owner is None:
            # A lost/absent owner cannot bind a write-once claim; the repository
            # would refuse it anyway, and reporting it here keeps the mapping
            # honest instead of letting a lease-less write reach the SQL.
            return "not_claimed"
        result = await self._write(
            run_id,
            owner,
            ExecutionSnapshotPayloads(
                execution_id=execution_id,
                **{column: payloads[column] for column in SNAPSHOT_COLUMNS},
            ),
        )
        return str(result)


class RuntimeFactoryInstructionPreparer:
    """Adapt ``prepare_instructions`` to the orchestration seam (R-32/R-26).

    The instruction provider output is produced by the preparation step, which
    lives in this layer; the execution layer only ever sees a structural seam, so
    no ``applications`` import appears below the boundary.
    """

    def __init__(self, prepare: Callable[..., object]) -> None:
        self._prepare = prepare

    def prepare_instructions(
        self,
        row: Mapping[str, object],
        *,
        history: object = (),
        summary_message: str | None = None,
        customer_memory: str | None = None,
        engine_context: Mapping[str, object] | None = None,
    ) -> object:
        return self._prepare(
            row,
            history=history,
            summary_message=summary_message,
            customer_memory=customer_memory,
            engine_context=engine_context,
        )


def production_ports(
    settings: Settings,
    registry: AdapterRegistry,
    *,
    clock: Callable[[], float],
) -> ExecutionCapabilityPorts:
    """The production port set: the only place these three classes are built.

    Tests substitute doubles through the ``ports=`` seam of the private
    composition builders. There is no settings or environment key that selects a
    port, so a client-supplied trusted port is structurally impossible (R-44).
    """
    return ExecutionCapabilityPorts(
        probe=DeclarationDerivedDeploymentProbe(registry=registry, clock=clock),
        policy_provider=PlatformDefaultPolicyProvider(
            policy_provider_id="react-policy",
            # R-20 closed loop: the descriptor above and this provider read the
            # one settings value, so a mismatch is a cache error, never a grant.
            policy_version=settings.execution_capability_policy_version,
            clock=clock,
        ),
        workspace_port=NoTrustedWorkspaceGeneration(),
    )


def warm_targets(
    settings: Settings,
    descriptor: AdapterDescriptor,
) -> tuple[CapabilityResolutionRequest, ...]:
    """Derive the warm scope from the one descriptor composition registered.

    ``AdapterRegistry`` has no enumeration API on purpose (R-46): it is a T3 file,
    and ``metadata()`` raises for a disabled or unknown triple, so composition
    filters its own registered descriptor by ``enabled`` instead of inventing a
    second registry-side listing. The scope can only reach the deployment level -
    business/workspace/agent/published-version components come from the actual Run
    - and business/workspace reuse the Worker's own fallback constants.
    """
    if not descriptor.enabled:
        return ()
    return (
        CapabilityResolutionRequest(
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            tenant_id=settings.tenant_id,
            business_scope=_WARM_TENANT_BUSINESS_ID,
            workspace_id=_WARM_TENANT_WORKSPACE_ID,
            agent_id=None,
            agent_published_version=None,
            disabled_capabilities=(),
            execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
        ),
    )


def _runtime_fingerprint_exclude_fields() -> set[str]:
    """Fields that must never change the Runtime assembly fingerprint.

    ``execution_orchestrator_enabled`` is the pre-existing rollout precedent: the
    composition may keep side-effect-free objects and the Worker re-reads the flag
    per claim, so changing it must not invalidate queued Runs.

    R-48 adds the whole Phase 3 family for the same reason and repairs a real
    defect: ``execution_phase3_enabled`` plus the ``execution_capability_*`` and
    ``execution_snapshot_max_bytes`` tuning knobs used to be hashed into the
    fingerprint, so flipping the switch or re-tuning a TTL made every already
    queued Run report ``configuration_changed`` - exactly what 03 §4.3 forbids
    ("切换不要求重建 Runtime"). None of them is a Runtime assembly input; the
    model/round/history fields are, and stay hashed. The Phase 3 semantics survive
    the exclusion through the five snapshot columns' provenance and the R-17 live
    read, not through the fingerprint.

    R-8 (Phase 4 08) extends the same rule to the whole Phase 4 family:
    ``execution_runtime_host_*``, ``execution_workdir_*``, ``execution_process_*``,
    ``execution_resource_*`` and ``execution_sandbox_provider`` are rollout flags
    and tuning limits, none of them a Runtime assembly input, so changing one
    must never force queued Runs to ``configuration_changed``.
    """
    return {
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
        "execution_orchestrator_enabled",
        "execution_phase3_enabled",
        "execution_snapshot_max_bytes",
        *(name for name in Settings.model_fields if name.startswith("execution_capability_")),
        *(
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
        ),
    }


def _runtime_fingerprint(settings: Settings, specs: list[HttpTool]) -> str:
    public = settings.model_dump(mode="json", exclude=_runtime_fingerprint_exclude_fields())
    public["tools"] = [spec.model_dump(mode="json") for spec in specs]
    return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()


def _execution_adapter_registry() -> AdapterRegistry:
    """Fresh Registry with the React engine/protocol registrations only.

    Adapter registration itself happens in ``_build_execution_orchestrator``,
    which owns the single ``AdapterDescriptor`` instance the warm targets are
    derived from, so no second listing API is needed here (R-46).
    """

    engines = EngineRegistry()
    engines.register(EngineDescriptor(engine_id="react"))
    protocols = ProtocolRegistry()
    protocols.register(ProtocolDescriptor(protocol_id="native"))
    return AdapterRegistry(engines, protocols)


def _react_adapter_descriptor(settings: Settings) -> AdapterDescriptor:
    """The one production React registration (R-44/R-46/R-31).

    ``policy_version`` comes from ``execution_capability_policy_version`` and the
    instruction provider identity comes from the contracts constants, so the
    descriptor, the registered policy provider and the instruction registry cannot
    drift apart (R-20/R-31). ``probe_id``/``policy_provider_id`` have no constant
    source yet and stay deployment literals here (R-31 boundary).
    """
    return AdapterDescriptor(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        config_schema=ReactConfig,
        config_schema_version="v1",
        declared=EngineCapabilities(
            streaming=True,
            cancellation=True,
            tool_calling=True,
            native_events=True,
        ),
        declared_schema_version="v1",
        probe_id="react-probe",
        probe_version="v1",
        policy_provider_id="react-policy",
        policy_version=settings.execution_capability_policy_version,
        instruction_provider_id=REACT_INSTRUCTION_PROVIDER_ID,
        provider_version=REACT_INSTRUCTION_PROVIDER_VERSION,
    )


def _build_execution_orchestrator(
    runtime_factory: RuntimeFactory,
    adapters: AdapterRegistry | None = None,
    *,
    settings: Settings | None = None,
    ports: ExecutionCapabilityPorts | None = None,
    barrier: ExecutionSnapshotBarrier | None = None,
    clock: Callable[[], float] | None = None,
    subsystem: ExecutionCapabilitySubsystem | None = None,
    execution_runtime: "ExecutionRuntimeSubsystem | None" = None,
) -> ExecutionOrchestrator:
    """Register production metadata and wire the Phase 3 seams from settings.

    Nothing is resolved or run here: constructing the orchestration must never
    instantiate an Adapter, so the descriptor carries metadata only and the
    factory is captured, not called.

    The Phase 3 subsystem is constructed only while ``execution_phase3_enabled``
    holds, which is what makes "no Phase 3 probe or snapshot side effects" true in
    the off states: while off there is no resolver, no warmer task and no port
    call at all (P3-IT-12). ``barrier`` and ``clock`` are code-level seams for
    tests and for the Phase 4/5 replacement; settings can never select them.

    ``settings`` defaults to the field defaults rather than making the parameter
    required: the pre-Phase-3 call sites that assemble an orchestrator for a
    fixed-configuration test are exactly the off state, and a deployment that
    turns Phase 3 on always reaches this builder through :func:`runtime_services`,
    which passes its own settings object (R-20).
    """

    settings = settings or Settings(_env_file=None)
    adapters = adapters or _execution_adapter_registry()
    adapters.register(_react_adapter_descriptor(settings), ReactAdapterFactory(runtime_factory))
    subsystem = subsystem or _build_execution_capability_subsystem(
        settings,
        adapters,
        ports=ports,
        clock=clock,
        barrier=barrier,
    )
    # Phase 4 seams follow the same injected-port rule (08 R-4c): with the
    # runtime subsystem unset - the default everywhere host id is empty - the
    # orchestrator is byte-identical to Phase 3. With it set, the React
    # registration still declares workspace_required=False, so the process
    # barrier never fires for React (the default-off invariant).
    runtime_seams: dict[str, object] = {}
    if execution_runtime is not None:
        runtime_seams = {
            "workdir_provider": execution_runtime.workspace,
            "runtime_host": execution_runtime.host,
        }
    if subsystem is None:
        return ExecutionOrchestrator(adapters, **runtime_seams)
    return ExecutionOrchestrator(
        adapters,
        capabilities=subsystem.resolver,
        snapshot_barrier=subsystem.barrier,
        snapshot_max_bytes=subsystem.snapshot_max_bytes,
        instruction_preparer=RuntimeFactoryInstructionPreparer(runtime_factory),
        **runtime_seams,
    )


def _build_execution_capability_subsystem(
    settings: Settings,
    registry: AdapterRegistry,
    *,
    ports: ExecutionCapabilityPorts | None = None,
    barrier: ExecutionSnapshotBarrier | None = None,
    clock: Callable[[], float] | None = None,
) -> ExecutionCapabilitySubsystem | None:
    """Construct the trusted ports, caches, resolver and warmer from settings.

    Every constructor argument below is a FR-9 ``execution_capability_*`` value;
    there is no hard-coded timeout, capacity, interval, TTL or identity here
    (R-44, and 04 P3-IT-19 asserts this mapping through public surfaces).

    Returns ``None`` while Phase 3 is off so the off states provably construct no
    subsystem and cannot reach a trusted port at all (R-46, P3-IT-12).
    """
    if not settings.execution_phase3_enabled:
        return None
    # R-49: exactly one POSIX wall clock shared by both cache TTLs and by
    # ``observed_at``/``resolved_at``. ``time.monotonic`` would keep passing the
    # aware-datetime validation while producing evidence dated near 1970.
    shared_clock = clock or time.time
    production = ports or production_ports(settings, registry, clock=shared_clock)
    availability_cache = CapabilityCache(
        ttl_seconds=settings.execution_capability_probe_cache_seconds,
        capacity=settings.execution_capability_cache_capacity,
        clock=shared_clock,
        retry_interval_seconds=settings.execution_capability_cache_retry_seconds,
    )
    policy_cache = CapabilityCache(
        ttl_seconds=settings.execution_capability_policy_cache_seconds,
        capacity=settings.execution_capability_cache_capacity,
        clock=shared_clock,
        retry_interval_seconds=settings.execution_capability_cache_retry_seconds,
    )
    resolver = CapabilityResolver(
        registry=registry,
        probe=production.probe,
        policy_provider=production.policy_provider,
        workspace_port=production.workspace_port,
        availability_cache=availability_cache,
        policy_cache=policy_cache,
        deployment_identity=settings.execution_capability_deployment_identity,
        probe_timeout_seconds=settings.execution_capability_probe_timeout_seconds,
        policy_timeout_seconds=settings.execution_capability_policy_timeout_seconds,
        probe_max_concurrency=settings.execution_capability_probe_max_concurrency,
        clock=shared_clock,
    )
    warmer = CapabilityWarmer(
        resolver=resolver,
        targets=warm_targets(settings, _react_adapter_descriptor(settings)),
        refresh_interval_seconds=settings.execution_capability_warm_refresh_seconds,
        retry_interval_seconds=settings.execution_capability_cache_retry_seconds,
    )
    return ExecutionCapabilitySubsystem(
        resolver=resolver,
        warmer=warmer,
        probe=production.probe,
        policy_provider=production.policy_provider,
        workspace_port=production.workspace_port,
        warm_targets=tuple(warm_targets(settings, _react_adapter_descriptor(settings))),
        registry=registry,
        clock=shared_clock,
        # R-52: the ceiling reaches the serializer only through this value, never
        # through the serializer's own module default.
        snapshot_max_bytes=settings.execution_snapshot_max_bytes,
        policy_version=settings.execution_capability_policy_version,
        barrier=barrier or _NoSnapshotBarrier(),
    )


@dataclass
class ExecutionRuntimeSubsystem:
    """Phase 4 Host assembly: supervision, durable registry, workspace, sandbox.

    Constructed only when this process carries a stable execution host id
    (08 R-7): processes that do not own the execution root construct nothing,
    and the React path stays byte-identical to Phase 3. Recovery and cleanup
    run regardless of the admission state (03 §5.1, 08 R-8); ``enabled`` only
    gates new starts and that gate lives inside the Host.
    """

    host: RuntimeHost
    workspace: ExecutionWorkspaceManager
    registry: ProcessRegistry
    resources: ResourceManager
    reconcile_interval_seconds: float
    cleanup_interval_seconds: float
    _tasks: list[asyncio.Task] = field(default_factory=list)

    async def recover_on_startup(self) -> None:
        """R-8: process records left by previous boots before admission opens."""
        await self.host.reconcile()
        await self._sweep_once()

    def start(self) -> None:
        """Spawn the reconcile and cleanup interval loops (never blocking)."""
        self._tasks = [
            asyncio.create_task(self._reconcile_loop(), name="execution-runtime-reconcile"),
            asyncio.create_task(self._cleanup_loop(), name="execution-workdir-cleanup"),
        ]

    async def aclose(self) -> None:
        """Stop loops, then the Host's stop-admission->drain machine (T14 order).

        Shutdown order mirrors the Phase 3 warmer-close discipline: loops die
        first so no reconcile races the drain, then ``host.close`` cancels and
        reaps every tracked group through the bounded TERM/KILL machine. The
        default 5s+5s windows fit the deployment stop grace; larger FR-10
        values require a deployment stop-timeout change (03 §4.3), which the
        compose files document.
        """
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        remaining = await self.host.close()
        if remaining:
            logger.error("execution runtime shutdown left %s active groups", remaining)

    async def _reconcile_loop(self) -> None:
        while True:
            await asyncio.sleep(self.reconcile_interval_seconds)
            try:
                await self.host.reconcile()
            except Exception:  # noqa: BLE001 - DB outage retries on the next tick.
                logger.warning("execution runtime reconcile deferred")

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cleanup_interval_seconds)
            await self._sweep_once()

    async def _sweep_once(self) -> None:
        try:
            candidates = await self.workspace.sweep_expired()
        except Exception:  # noqa: BLE001 - the interval scan retries on the next tick.
            logger.warning("execution workdir sweep deferred")
            return
        for candidate in candidates:
            with suppress(Exception):
                await self.workspace.cleanup(
                    workdir_id=candidate.workdir_id,
                    run_id=candidate.run_id,
                    tenant_id=candidate.tenant_id,
                )


def _build_execution_runtime_subsystem(
    settings: Settings,
    engine,
    *,
    boot_id: str | None = None,
    clock: Callable[[], float] | None = None,
) -> ExecutionRuntimeSubsystem | None:
    """Assemble the Phase 4 runtime from FR-10 settings without starting it.

    Returns ``None`` when no execution host id is configured: the API and the
    channel/knowledge/memory workers, and quickstart defaults, construct no
    Host, no loops and no directories (08 R-7 topology; the AC-12 deployment
    check pins exactly this). ``boot_id`` and ``clock`` are code-level seams
    for tests and for the recovery audit, never settings-selectable.

    The trusted-target allowlist is the empty code constant: Phase 4 registers
    no production executable (08 §1.9 - real engines arrive in Phase 5), so
    anything started through this composition lane is refused by the Runner
    gate before spawn; test triples compose their own registry explicitly.
    """
    if not settings.execution_runtime_host_id:
        return None
    shared_clock = clock or time.time
    sandbox_provider_id = f"{settings.execution_sandbox_provider}/v1"
    provider = LocalSandboxProvider(
        enforcement_required=settings.execution_resource_enforcement_required,
    )
    resources = ResourceManager(
        provider,
        sample_interval_seconds=settings.execution_resource_sample_interval_seconds,
        clock=shared_clock,
    )
    registry = ProcessRegistry(
        engine,
        host_id=settings.execution_runtime_host_id,
        host_instance_id=boot_id or f"boot-{uuid4().hex}",
        sandbox_provider=sandbox_provider_id,
        clock=shared_clock,
    )
    workspace = ExecutionWorkspaceManager(
        engine,
        root=settings.execution_workdir_root,
        quota_bytes=settings.execution_workdir_max_bytes,
        retention_seconds=settings.execution_workdir_retention_seconds,
        failed_retention_seconds=settings.execution_workdir_failed_retention_seconds,
        clock=shared_clock,
    )
    host = RuntimeHost(
        enabled=settings.execution_runtime_host_enabled,
        host_id=settings.execution_runtime_host_id,
        runner=ProcessRunner(TrustedTargetRegistry(())),
        supervisor=ProcessSupervisor(
            cancel_grace_seconds=settings.execution_process_cancel_grace_seconds,
            kill_timeout_seconds=settings.execution_process_kill_timeout_seconds,
            clock=shared_clock,
        ),
        registry=registry,
        wall_timeout_seconds=settings.execution_process_wall_timeout_seconds,
        resource_enforcement_required=settings.execution_resource_enforcement_required,
        sandbox_provider_id=sandbox_provider_id,
        resource_manager=resources,
        workspace_manager=workspace,
        clock=shared_clock,
    )
    return ExecutionRuntimeSubsystem(
        host=host,
        workspace=workspace,
        registry=registry,
        resources=resources,
        reconcile_interval_seconds=settings.execution_process_reconcile_interval_seconds,
        cleanup_interval_seconds=settings.execution_workdir_cleanup_interval_seconds,
    )


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
    scope: TenantScopeService
    # The Phase 3 capability subsystem the Run path owns (08 T7). It is exposed
    # on the services root so the read-only preview face resolves through this
    # exact resolver instance (03 §7.1/§7.3, P3-IT-11): a second subsystem
    # would be a second cache and a second, drift-prone authorization source.
    # ``None`` while ``execution_phase3_enabled`` is false, which is what lets
    # the off state provably reach no trusted port at all.
    execution_subsystem: ExecutionCapabilitySubsystem | None = None
    # The Phase 4 runtime subsystem (Host/Workspace/loops) when this process
    # owns an execution root; ``None`` is the default topology for API and the
    # non-runtime workers (08 R-7).
    execution_runtime: ExecutionRuntimeSubsystem | None = None


@asynccontextmanager
async def runtime_services(
    settings: Settings,
    trusted_extension_binder: TrustedExtensionBinder | None = None,
) -> AsyncIterator[RuntimeServices]:
    """Assemble shared Runtime services for one business application.

    The platform composition is shared, while each application supplies its
    own reviewed bindings for external capability implementations. Keeping
    that hook at the composition boundary prevents one business application
    from importing another application's trusted extensions.
    """

    specs = (
        [
            HttpTool.model_validate(item)
            for item in json.loads(settings.tools_file.read_text(encoding="utf-8"))
        ]
        if settings.tools_file
        else []
    )
    fingerprint = _runtime_fingerprint(settings, specs)
    snapshot = {
        "fingerprint": fingerprint,
        "model_backend": settings.model_backend,
        "model_name": settings.model_name,
    }
    engine = create_engine(settings)
    adapters = _execution_adapter_registry()
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
    # Bound before the try so the close order in ``finally`` can never hit an
    # unbound name when startup fails earlier: while it stays None there is no
    # subsystem and nothing to close (R-46).
    subsystem: ExecutionCapabilitySubsystem | None = None
    # Bound before the try for the same reason as ``subsystem``: the close
    # order in ``finally`` must never hit an unbound name.
    execution_runtime: ExecutionRuntimeSubsystem | None = None
    tool_policy = ToolEgressPolicy.from_settings(settings)
    try:
        async with (
            httpx.AsyncClient(
                transport=ToolEgressTransport(
                    tool_policy,
                    trust_env=False,
                    limits=httpx.Limits(max_connections=settings.tool_concurrency),
                ),
                trust_env=False,
                limits=httpx.Limits(max_connections=settings.tool_concurrency),
            ) as client,
            httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=settings.model_timeout_seconds,
                limits=httpx.Limits(max_connections=settings.model_gateway_concurrency * 6),
            ) as model_client,
        ):
            tools = ToolGateway(
                client,
                specs,
                settings.tool_concurrency,
                network_policy=tool_policy,
            )
            model = build_model(settings, tools.schemas)
            runtime = RuntimeEngine(model, tools, settings)
            repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
            platform = PlatformServices(
                engine,
                repository,
                settings,
                snapshot,
                specs,
                model_client,
                contributions,
                tool_client=client,
                tool_network_policy=tool_policy,
                adapter_registry=adapters,
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
            if trusted_extension_binder is not None:
                trusted_extension_binder(implementation_registry, platform)
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
                            error=(f"trusted contribution binding failed: {type(exc).__name__}"),
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
            factory = RuntimeFactory(runtime, bindings, client, settings, tools.limit, tool_policy)
            subsystem = _build_execution_capability_subsystem(
                settings,
                adapters,
                barrier=_RepositorySnapshotBarrier(repository.write_execution_snapshots),
            )
            execution_runtime = _build_execution_runtime_subsystem(settings, engine)
            orchestrator = _build_execution_orchestrator(
                factory,
                adapters,
                settings=settings,
                subsystem=subsystem,
                execution_runtime=execution_runtime,
            )
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
            # R-46: readiness never waits on a probe. ``start()`` only spawns the
            # background loop, and ``GET /ready`` reads no capability cache, so a
            # hanging port cannot delay readiness; the first Run still fails
            # closed on a cold entry instead of the process refusing to boot.
            if subsystem is not None:
                subsystem.warmer.start()
            if execution_runtime is not None:
                # R-8: recovery precedes admission; the loops run even with
                # the Host disabled so existing records converge, while the
                # Host's admission gate refuses new starts (03 §5.1).
                await execution_runtime.recover_on_startup()
                execution_runtime.start()
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
                    memory=MemoryInjection(groups.business.memory),
                    orchestrator=orchestrator if settings.execution_orchestrator_enabled else None,
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
                scope=platform.scope,
                execution_subsystem=subsystem,
                execution_runtime=execution_runtime,
            )
    finally:
        # R-46 close order: this subsystem first (a warm round may still be
        # awaiting a port that reads the engine or HTTP), then contributions,
        # extensions, the engine, and the listener/notifier pair.
        # Phase 4 first: the Host drain reaps processes and closes records on
        # the engine that is disposed below; the loops must die before the
        # Host closes so no reconcile races the drain (mirrors the R-46
        # ordering discipline).
        if execution_runtime is not None:
            await execution_runtime.aclose()
        if subsystem is not None:
            await subsystem.warmer.aclose()
            await subsystem.resolver.aclose()
        contributions.detach_events()
        if extensions_started:
            await extensions.stop_all()
        await engine.dispose()
        await listener.close()
        await notifier.close()
