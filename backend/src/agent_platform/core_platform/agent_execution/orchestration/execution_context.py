"""Private per-run context, the rollout gate, and the trusted capability seam."""

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable
from uuid import UUID

from agent_platform.extension_contracts import (
    BusinessScope,
)

from ..capability.resolver import (
    CapabilityResolution,
    CapabilityResolutionRequest,
    CapabilityResolver,
)
from ..contracts import (
    ConfigurationError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionRequest,
    InstructionInput,
    PreparedInstructions,
)
from ..contracts.capabilities import NO_EXECUTION_RESTRICTIONS, disabled_capabilities_digest
from ..contracts.config import (
    ExecutionConfig,
    execution_config_from_agent_config,
    normalize_execution_config,
)

_ANONYMOUS_LEGACY_AGENT_ID = UUID(int=0)
_Resolved = TypeVar("_Resolved")
_execution_context_var: ContextVar[object] = ContextVar("agent_execution_context", default=None)

# The fixed production selector. Worker admission, the Registry and the warm
# targets all read this one definition, so a rollout gate can never disagree
# with what the orchestrator resolves (03 §4.3).
PRODUCTION_ADAPTER_SELECTOR: tuple[str, str, str] = ("react", "native", "v1")

# The triple a published configuration resolves to when its engine cannot be
# projected at all. No registration can carry empty identifiers, so it differs
# from every selector by construction and the rollout gate fails closed with the
# code its state defines instead of raising a new one.
_UNDETERMINABLE_ENGINE_TRIPLE: tuple[str, str, str] = ("", "", "")


@runtime_checkable
class ExecutionSnapshotBarrier(Protocol):
    """Write-once startup snapshot barrier over one claimed row.

    Structural on purpose: ``core_platform`` may not import the application
    repository, so composition adapts ``write_execution_snapshots`` to this seam
    and the orchestrator only ever sees a controlled outcome label.
    """

    async def write(
        self,
        *,
        run_id: UUID,
        owner: UUID | None,
        execution_id: UUID,
        payloads: Mapping[str, str],
    ) -> str: ...


@runtime_checkable
class InstructionPreparer(Protocol):
    """Prepares one claimed row's instructions before any runner exists (R-10).

    Also structural: the production implementation is
    ``RuntimeFactory.prepare_instructions``, which lives in ``applications`` and
    may not be imported from here.
    """

    def prepare_instructions(
        self,
        row: Mapping[str, object],
        *,
        history: object = (),
        summary_message: str | None = None,
        customer_memory: str | None = None,
        engine_context: Mapping[str, object] | None = None,
    ) -> InstructionInput: ...


def _configuration_error(code: ExecutionErrorCode) -> ConfigurationError:
    return ConfigurationError(
        ExecutionError(category=ExecutionErrorCategory.CONFIGURATION_ERROR, code=code)
    )


def _invalid_request() -> ConfigurationError:
    return _configuration_error(ExecutionErrorCode.INVALID_REQUEST)


def _factory_failed() -> ConfigurationError:
    return _configuration_error(ExecutionErrorCode.ADAPTER_FACTORY_FAILED)


def _normalize_execution_uuid(value: object) -> UUID:
    """Return exact stdlib UUID identity without modifying the claimed row value."""
    try:
        if not isinstance(value, UUID):
            raise _invalid_request()
        if type(value) is UUID:
            return value
        if not any(base is UUID for base in type(value).__mro__):
            raise _invalid_request()
        return UUID(str(value))
    except ConfigurationError:
        raise
    except Exception:  # noqa: BLE001 - hostile UUID values must fail closed.
        raise _invalid_request() from None


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """One claimed row and its already-rendered runtime inputs.

    This is deliberately not a serializable DTO. Event callbacks are owned by the
    worker/orchestrator and adapter respectively, and therefore cannot be fields here.

    The Phase 3 additions travel here rather than through the frozen
    ``AgentEngineAdapter.start`` contract (R-52/T1 freeze): ``prepared_instructions``
    is the provider output computed before the snapshot commit, ``owner`` is the
    claimed-row lease owner the write-once barrier is bound to, and ``scope`` is
    the same trusted business scope the Worker already bound for the persisted
    history read. ``execution_phase3_enabled`` is the rollout decision read once
    per claim, so the Phase 3 barrier steps on a fixed path instead of re-reading
    mutable settings (03 §4.3).
    """

    row: Mapping[str, object]
    execution_id: UUID
    history: list[dict[str, object]]
    summary_message: str | None = None
    customer_memory: str | None = None
    trace_id: str | None = None
    timeout_seconds: int | None = None
    prepared_instructions: PreparedInstructions | None = None
    owner: UUID | None = None
    scope: BusinessScope | None = None
    execution_phase3_enabled: bool = False

    def __post_init__(self) -> None:
        try:
            row = self.row
            if not isinstance(row, Mapping):
                raise _invalid_request()
            execution_id = _normalize_execution_uuid(self.execution_id)
            claimed_id = _normalize_execution_uuid(row.get("id"))
            history = deepcopy(self.history)
            valid = (
                execution_id == claimed_id
                and isinstance(history, list)
                and all(isinstance(item, dict) for item in history)
                and isinstance(self.summary_message, str | None)
                and isinstance(self.customer_memory, str | None)
                and isinstance(self.trace_id, str | None)
                and (
                    self.timeout_seconds is None
                    or (type(self.timeout_seconds) is int and self.timeout_seconds > 0)
                )
                and isinstance(self.prepared_instructions, PreparedInstructions | None)
                and (self.owner is None or _is_uuid(self.owner))
                and isinstance(self.scope, BusinessScope | None)
                and type(self.execution_phase3_enabled) is bool
            )
        except ConfigurationError:
            raise
        except Exception:  # noqa: BLE001 - arbitrary context inputs must fail closed.
            raise _invalid_request() from None
        if not valid:
            raise _invalid_request()
        object.__setattr__(self, "execution_id", execution_id)
        object.__setattr__(self, "history", history)


def build_execution_context(
    row: Mapping[str, object],
    *,
    history: list[dict[str, object]],
    summary_message: str | None = None,
    customer_memory: str | None = None,
    trace_id: str | None = None,
    timeout_seconds: int | None = None,
    prepared_instructions: PreparedInstructions | None = None,
    owner: UUID | None = None,
    scope: BusinessScope | None = None,
    execution_phase3_enabled: bool = False,
) -> ExecutionContext:
    """Validate and capture current-run inputs without consulting an Agent repository."""
    try:
        if not isinstance(row, Mapping):
            raise _invalid_request()
        return ExecutionContext(
            row=row,
            execution_id=row["id"],
            history=history,
            summary_message=summary_message,
            customer_memory=customer_memory,
            trace_id=trace_id,
            timeout_seconds=timeout_seconds,
            prepared_instructions=prepared_instructions,
            owner=owner,
            scope=scope,
            execution_phase3_enabled=execution_phase3_enabled,
        )
    except ConfigurationError:
        raise
    except Exception:  # noqa: BLE001 - arbitrary claimed-row access must fail closed.
        raise _invalid_request() from None


def _snapshot_agent_id(row: Mapping[str, object]) -> UUID:
    config = row.get("config")
    if not isinstance(config, Mapping):
        raise _invalid_request()
    if "agent" not in config:
        # The fixed React request builder only reaches this branch for RuntimeFactory's
        # no-snapshot legacy base_runtime path. The sentinel is never used for a lookup.
        return _ANONYMOUS_LEGACY_AGENT_ID

    snapshot = config["agent"]
    if not isinstance(snapshot, Mapping) or "id" not in snapshot:
        raise _invalid_request()
    value = snapshot["id"]
    try:
        if type(value) is UUID:
            agent_id = value
        elif type(value) is str:
            agent_id = UUID(value)
        else:
            raise _invalid_request()
    except (ValueError, TypeError, AttributeError):
        raise _invalid_request() from None
    if agent_id == _ANONYMOUS_LEGACY_AGENT_ID:
        raise _invalid_request()
    return agent_id


def build_execution_request(context: ExecutionContext) -> ExecutionRequest:
    """Build the fixed React/native/v1 request from one validated claimed row."""
    if not isinstance(context, ExecutionContext):
        raise _invalid_request()
    try:
        row = context.row
        return ExecutionRequest(
            execution_id=context.execution_id,
            engine_id="react",
            protocol_id="native",
            adapter_version="v1",
            tenant_id=row["tenant_id"],
            agent_id=_snapshot_agent_id(row),
            conversation_id=row.get("conversation_id"),
            input=row["input"],
            config={},
            effective_capabilities={},
            engine_session_id=row.get("engine_session_id"),
            workspace_id=row.get("workspace_id"),
            trace_id=context.trace_id,
            execution_workdir=row.get("execution_workdir"),
            timeout_seconds=context.timeout_seconds,
        )
    except ConfigurationError:
        raise
    except Exception:  # noqa: BLE001 - arbitrary claimed-row access must fail closed.
        raise _invalid_request() from None


def capture_execution_context() -> ExecutionContext:
    """Synchronously capture the current context into an adapter being constructed."""
    context = _execution_context_var.get()
    if not isinstance(context, ExecutionContext):
        raise _factory_failed()
    return context


def published_agent_identity(context: ExecutionContext) -> tuple[UUID | None, int | None]:
    """Return the published Agent identity the startup snapshot must pin.

    Both components come from the claimed row's published snapshot, never from
    request input: ``agent_id`` uses the same strict identity the fixed React
    request builder already validates, and ``agent_version`` keeps the snapshot's
    own positive integer. A row without a published Agent snapshot has no identity
    to pin and is refused by the barrier before any payload is built (R-51).
    """
    if _published_agent_config(context.row) is None or context.scope is None:
        raise _invalid_request()
    return _snapshot_agent_id(context.row), _published_agent_version(context.row)


def disabled_capabilities_digest_value(execution_config: ExecutionConfig) -> str:
    """The one canonical narrowing digest for one published configuration.

    The snapshot and the policy cache key must carry the same digest the
    ``PolicyCacheKey`` was built from, so it is computed here through the single
    contracts helper rather than re-derived per consumer (R-17/R-21).
    """
    return disabled_capabilities_digest(execution_config.disabled_capabilities)


def resolve_with_execution_context(
    context: ExecutionContext,
    resolve: Callable[[], _Resolved],
) -> _Resolved:
    """Run a synchronous zero-arg resolve in a scoped, finally-reset context."""
    if not isinstance(context, ExecutionContext) or not callable(resolve):
        raise _factory_failed()
    token = _execution_context_var.set(context)
    try:
        return resolve()
    finally:
        _execution_context_var.reset(token)


# --------------------------------------------------------------------------- #
# Phase 3 rollout gate (03 §4.3 four-state matrix, R-11/R-50)                    #
# --------------------------------------------------------------------------- #


def execution_rollout_fault(
    row: Mapping[str, object],
    *,
    phase3_enabled: bool,
    orchestrator_enabled: bool,
    selector: tuple[str, str, str] = PRODUCTION_ADAPTER_SELECTOR,
) -> str | None:
    """Classify one claimed row against the rollout matrix; None means proceed.

    This is a pure classifier rather than a raiser for one layering reason: the
    stable Run codes belong to the Runtime/Worker boundary
    (``core_platform.agent_runtime``), which the execution layer must not import
    (architecture gate). The Worker raises the returned code as a ``RuntimeFault``
    before it selects a path, and the Phase 3 barrier maps it to an outcome.

    The published engine triple is compared against the orchestrator selector in
    all four states (C9 veto face): "silently enabling legacy" is precisely the
    defect this gate exists to prevent, and an off state must refuse a non-React
    published configuration rather than pretend the flag is irrelevant.

    A row with **no published Agent snapshot** is not compared at all, because it
    is the RuntimeFactory no-snapshot legacy shape whose fixed React triple is the
    Phase 2 path AC-1/US-1 depends on (P2-IT-14 evidence), not a divergence: the
    publish and snapshot-read paths refuse an unknown triple before a Run is ever
    queued, so a refusal here would only invent a state production cannot reach.
    The Phase 3 barrier still refuses such a row, because with no published
    configuration there is no canonical ``ExecutionConfig`` to pin into the startup
    snapshot (R-52).
    """
    if type(phase3_enabled) is not bool or type(orchestrator_enabled) is not bool:
        # A non-boolean rollout value is a deployment defect, never a grant.
        return "execution_configuration_invalid"
    engine = _published_engine_identity(row)
    if engine is not None and engine != tuple(selector):
        return "execution_engine_unavailable" if phase3_enabled else "execution_phase3_disabled"
    if phase3_enabled and not orchestrator_enabled:
        # 03 §9.2 item 4: the misconfiguration fails closed for Runs while the
        # process still boots, so the §7.4 flags face and the R-25/M3 hint stay
        # observable in exactly that state (R-50).
        return "execution_configuration_invalid"
    return None


def enforce_execution_rollout(
    row: Mapping[str, object],
    *,
    phase3_enabled: bool,
    orchestrator_enabled: bool,
    selector: tuple[str, str, str] = PRODUCTION_ADAPTER_SELECTOR,
    fault: Callable[[str], BaseException],
) -> None:
    """Fail closed on every off-matrix state before any Runtime or Adapter work.

    Called exactly once per claim with the flags the Worker already read, so the
    selected path is fixed for the whole Run: a settings object flipped mid-claim
    cannot re-decide this gate (03 §4.3). The ``fault`` constructor is injected
    because ``RuntimeFault`` lives behind the architecture boundary this layer may
    not import; the Worker passes its own class, so the raise site stays one.
    """
    code = execution_rollout_fault(
        row,
        phase3_enabled=phase3_enabled,
        orchestrator_enabled=orchestrator_enabled,
        selector=selector,
    )
    if code is not None:
        raise fault(code)


def execution_config_from_context(context: ExecutionContext) -> ExecutionConfig:
    """Return the canonical execution config of one claimed, published row.

    The snapshot is projected through the six-key helper only, so the Phase 3
    startup snapshot and the publish path cannot drift (R-52); a row without a
    published Agent snapshot has no canonical config to pin and fails closed as a
    configuration fault instead of defaulting into evidence.
    """
    published = _published_agent_config(context.row)
    if published is None:
        raise _invalid_request()
    try:
        return execution_config_from_agent_config(published)
    except ConfigurationError:
        raise
    except Exception:  # noqa: BLE001 - a non-canonical published config is fatal.
        raise _invalid_request() from None


async def resolve_execution_capabilities(
    resolver: CapabilityResolver,
    context: ExecutionContext,
    execution_config: ExecutionConfig,
) -> CapabilityResolution:
    """Resolve one Run's capabilities, warming a cold entry exactly once (R-47).

    ``CapabilityResolver.resolve`` stays read-only (P3-UT-22 "hot path 不 probe"),
    so a Run whose scope composition never enumerated would fail closed forever if
    the barrier refused to await one bounded refresh. The await happens only on the
    Worker background Run path, never on the HTTP preview face, and it stays
    bounded by the same settings-derived probe/policy timeouts because it goes
    through the same trusted ports.
    """
    request = _resolution_request(context, execution_config)
    resolution = await resolver.resolve(request)
    if not resolution_is_observed(resolution):
        await resolver.warm(request)
        resolution = await resolver.resolve(request)
    return resolution


def resolution_is_observed(resolution: CapabilityResolution) -> bool:
    """True only when both layers carry a fresh observation for this round."""
    return resolution.availability_status == "fresh" and resolution.policy_status == "fresh"


def disabled_capabilities_from(execution_config: ExecutionConfig) -> str:
    """The one canonical narrowing digest for one published config (R-17)."""
    return disabled_capabilities_digest(execution_config.disabled_capabilities)


def _resolution_request(
    context: ExecutionContext, execution_config: ExecutionConfig
) -> CapabilityResolutionRequest:
    scope = context.scope
    if scope is None or _published_agent_config(context.row) is None:
        # Without a trusted scope or a published snapshot there is nothing to
        # resolve; the barrier classifies that as a configuration fault.
        raise _invalid_request()
    return CapabilityResolutionRequest(
        engine_id=execution_config.engine.engine_id,
        protocol_id=execution_config.engine.protocol_id,
        adapter_version=execution_config.engine.adapter_version,
        tenant_id=scope.tenant_id,
        business_scope=scope.business_id,
        workspace_id=scope.workspace_id,
        agent_id=_snapshot_agent_id(context.row),
        agent_published_version=_published_agent_version(context.row),
        disabled_capabilities=execution_config.disabled_capabilities,
        # Phase 3 has no server-trusted restriction source; R-17 froze this to the
        # empty-set canonical digest, never a caller-supplied value.
        execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
    )


def _published_engine_identity(row: Mapping[str, object]) -> tuple[str, str, str]:
    """Project the published triple, defaulting exactly like the legacy path.

    The projection is the six-key one the snapshot uses (R-52), never the whole
    published Agent config: a real Agent config carries prompt, language, memory
    and tool keys that ``ExecutionConfig`` forbids, and normalizing the unprojected
    mapping would reject every published row and turn the off-state rollout check
    into an ``execution_error`` - a Phase 2 parity break on the common path.

    A published config that still cannot be projected after the six-key filter is
    reported as the unknown triple rather than raised: the gate is a classifier, it
    must never invent a new failure mode, and "not the engine this deployment
    registered" is the honest reading of a configuration whose engine cannot be
    determined. The publish path validates the triple through the Registry before a
    Run is ever queued, so this only ever describes a hand-written row (R-50).
    """
    published = _published_agent_config(row)
    if published is None:
        # No Agent snapshot means the RuntimeFactory base_runtime path, whose
        # fixed React triple is the production selector by construction.
        return PRODUCTION_ADAPTER_SELECTOR
    try:
        execution = execution_config_from_agent_config(published)
    except ConfigurationError:
        raise
    except (TypeError, ValueError):
        # Only a rejected configuration is narrowed here. Control flow (an
        # ExceptionGroup with a cancellation inside) is never an ``Exception``,
        # so it propagates untouched and the Worker keeps its existing
        # control-flow membership on every path, off included (03 §4.3).
        #
        # The two faces of a rejected config answer differently (03 §5.3/D5): an
        # Engine this deployment never registered is an availability answer, while
        # a published configuration whose canonical form simply does not add up is
        # a configuration answer. Re-projecting the engine block alone keeps that
        # distinction without duplicating the normalizer's own defaults: when the
        # triple is still readable the gate lets the Run through and the barrier's
        # own normalization step (which runs before any payload is built) reports
        # ``execution_configuration_invalid``; only a triple that cannot be read at
        # all becomes the unknown one.
        engine_only = _engine_block_triple(published)
        if engine_only is None:
            return _UNDETERMINABLE_ENGINE_TRIPLE
        return engine_only
    return (
        execution.engine.engine_id,
        execution.engine.protocol_id,
        execution.engine.adapter_version,
    )


def _engine_block_triple(published: Mapping[str, object]) -> tuple[str, str, str] | None:
    """The triple named by the published engine block alone, or None."""
    engine = published.get("engine")
    candidate: dict[str, object] = {} if engine is None else {"engine": engine}
    try:
        execution = normalize_execution_config(candidate)
    except (TypeError, ValueError):
        return None
    return (
        execution.engine.engine_id,
        execution.engine.protocol_id,
        execution.engine.adapter_version,
    )


def _published_agent_config(row: Mapping[str, object]) -> Mapping[str, object] | None:
    config = row.get("config")
    if not isinstance(config, Mapping):
        return None
    snapshot = config.get("agent")
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("config"), Mapping):
        return None
    return snapshot["config"]


def _published_agent_version(row: Mapping[str, object]) -> int | None:
    config = row.get("config")
    snapshot = config.get("agent") if isinstance(config, Mapping) else None
    if not isinstance(snapshot, Mapping):
        return None
    version = snapshot.get("version")
    if version is None:
        return None
    if type(version) is not int or version < 1:
        raise _invalid_request()
    return version


def _is_uuid(value: object) -> bool:
    return isinstance(value, UUID) and (
        type(value) is UUID or any(b is UUID for b in type(value).__mro__)
    )
