"""Execute a scenario's declared tool references through the tool gateway.

``scenarios.simulation`` stays a pure function: it walks a configured path and
never calls a provider.  This module owns the one place where a declared
executor turns into a real HTTP call, so the preview console and a served
conversation share the same execution path instead of drifting apart.

A provider opts in by declaring executors (see ``providers.executors``); the
absence of a declaration keeps the historical label-only simulation, which is
what the bundled demo packs rely on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway

from ..providers.executors import REFERENCE, ExecutorSpec, parse_executors
from ..providers.models import ProviderKind
from .models import ObjectMode, ScenarioConfig, SimulatedObject, SimulationRequest


def _lookup(values: Any, path: str) -> Any:
    """Read a dotted path, tolerating list indices such as ``items.0.title``."""

    current = values
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        return None
    return current


def _at_root(value: Any, root: str) -> Any:
    return _lookup(value, root) if root else value


def _render(template: Any, context: dict[str, Any]) -> Any:
    """Resolve ``$object.x`` style references; ``$$`` escapes a literal."""

    if isinstance(template, str):
        if template.startswith("$$"):
            return template[1:]
        match = REFERENCE.match(template)
        if match:
            return _lookup(context.get(match.group(1), {}), match.group(2))
        if template.startswith("$"):
            raise DomainError("provider_executor_template_invalid", 422)
        return template
    if isinstance(template, dict):
        return {key: _render(item, context) for key, item in template.items()}
    if isinstance(template, list):
        return [_render(item, context) for item in template]
    return template


def _context(
    obj: SimulatedObject | None,
    customer: dict[str, Any] | None,
    decision: str | None,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": obj.id if obj else "",
        "type": obj.type if obj else "",
        "status": obj.status if obj else "",
    }
    values.update(obj.facts if obj else {})
    return {
        "object": values,
        "customer": dict(customer or {}),
        "decision": {"selected": decision or ""},
    }


@dataclass(frozen=True)
class ToolOutcome:
    """Normalised result of one gateway call."""

    tool: str
    ok: bool
    data: Any = None
    error: str | None = None
    error_status: int = 0
    upstream_called: bool = True

    @property
    def missing(self) -> bool:
        """The upstream said the object does not exist."""

        return self.error_status == 404

    @property
    def denied(self) -> bool:
        """The upstream said the caller may not see the object."""

        return self.error_status == 403

    def public(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "error": self.error,
            "error_status": self.error_status,
            "upstream_called": self.upstream_called,
        }


@dataclass
class ObjectResolution:
    """What the provider told us about the object behind one request."""

    object: SimulatedObject | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    outcome: ToolOutcome | None = None
    source: str = "provider"
    on_error: str = "human"


class ScenarioToolBridge:
    """Resolve provider executors and run them through the tool gateway."""

    def __init__(self, registry: Any, providers: Any, workspace: Any) -> None:
        self.registry = registry
        self.providers = providers
        self.workspace = workspace

    async def executors(
        self,
        tenant: str,
        provider_key: str,
        *,
        kind: ProviderKind = ProviderKind.OBJECT,
        scope: Any = None,
    ) -> dict[str, ExecutorSpec]:
        if not provider_key:
            return {}
        try:
            record = await self.providers.get(tenant, kind, provider_key, scope=scope)
        except DomainError:
            # A missing provider is a placeholder, not an execution failure.
            return {}
        return parse_executors(record.get("config") or {})

    async def execute(
        self,
        tenant: str,
        executor: ExecutorSpec,
        context: dict[str, Any],
    ) -> ToolOutcome:
        try:
            arguments = _render(executor.arguments, context)
        except DomainError as exc:
            return ToolOutcome(tool=executor.tool, ok=False, error=exc.code, upstream_called=False)
        try:
            resolved = await self.registry.resolve(tenant, [executor.tool])
        except DomainError as exc:
            return ToolOutcome(tool=executor.tool, ok=False, error=exc.code, upstream_called=False)
        if not resolved:
            return ToolOutcome(
                tool=executor.tool,
                ok=False,
                error="tool_unavailable",
                upstream_called=False,
            )
        try:
            spec = HttpTool.model_validate(resolved[0]["spec"])
        except (KeyError, ValueError):
            return ToolOutcome(
                tool=executor.tool,
                ok=False,
                error="tool_spec_invalid",
                upstream_called=False,
            )
        gateway = ToolGateway(
            self.workspace.client,
            [spec],
            credential_resolver=lambda item: self.registry.credential_headers(tenant, item),
            network_policy=self.workspace.network_policy,
        )
        # Share the process-wide concurrency budget instead of opening a new one.
        gateway.limit = self.workspace.test_limit
        try:
            result = await gateway.execute(spec.name, arguments)
        except (TimeoutError, OSError):
            return ToolOutcome(tool=spec.name, ok=False, error="tool_execution_failed")
        if not result.get("ok"):
            error = str(result.get("error") or "tool_failed")
            status = int(result.get("status_code") or 0)
            return ToolOutcome(
                tool=spec.name,
                ok=False,
                error=error,
                error_status=status,
            )
        return ToolOutcome(
            tool=spec.name,
            ok=True,
            data=_at_root(result.get("data"), executor.result_root),
        )

    async def resolve_object(
        self,
        tenant: str,
        config: ScenarioConfig,
        request: SimulationRequest,
        *,
        customer: dict[str, Any] | None = None,
        scope: Any = None,
    ) -> ObjectResolution | None:
        """Return provider-backed facts, candidates, or ``None`` for placeholders."""

        object_config = config.object
        if (
            object_config is None
            or object_config.mode == ObjectMode.NONE
            or not object_config.provider
        ):
            return None
        executors = await self.executors(tenant, object_config.provider, scope=scope)
        if not executors:
            return None
        identity = customer if customer is not None else request.customer
        context = _context(request.object, identity, request.selected_decision)
        if request.object is not None and request.object.id and "get" in executors:
            outcome = await self.execute(tenant, executors["get"], context)
            return self._merged(request.object, outcome, executors["get"])
        if "list" in executors:
            outcome = await self.execute(tenant, executors["list"], context)
            return ObjectResolution(
                candidates=self._candidates(outcome),
                outcome=outcome,
                on_error=executors["list"].on_error,
            )
        return None

    @staticmethod
    def _merged(
        current: SimulatedObject,
        outcome: ToolOutcome,
        executor: ExecutorSpec,
    ) -> ObjectResolution:
        if outcome.missing:
            return ObjectResolution(
                object=current.model_copy(update={"exists": False, "facts": {}}),
                outcome=outcome,
                on_error=executor.on_error,
            )
        if outcome.denied:
            return ObjectResolution(
                object=current.model_copy(update={"accessible": False, "facts": {}}),
                outcome=outcome,
                on_error=executor.on_error,
            )
        if not outcome.ok:
            # Hand the untouched request object back; the caller decides whether
            # a failed read degrades to human service or fails the turn.
            return ObjectResolution(
                object=current,
                outcome=outcome,
                on_error=executor.on_error,
            )
        data = outcome.data if isinstance(outcome.data, dict) else {}
        facts = {**(current.facts or {}), **data}
        status = str(data.get("status") or current.status or "")
        return ObjectResolution(
            object=current.model_copy(update={"facts": facts, "status": status}),
            outcome=outcome,
            on_error=executor.on_error,
        )

    @staticmethod
    def _candidates(outcome: ToolOutcome) -> list[dict[str, Any]]:
        if not outcome.ok:
            return []
        data = outcome.data
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or []
        if not isinstance(data, list):
            return []
        candidates: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            identifier = item.get("id") or item.get("key")
            if identifier is None:
                continue
            candidates.append(
                {
                    "id": str(identifier),
                    "title": str(item.get("title") or item.get("name") or identifier),
                    "status": str(item.get("status") or ""),
                }
            )
        return candidates


__all__ = [
    "ObjectResolution",
    "ScenarioToolBridge",
    "ToolOutcome",
]
