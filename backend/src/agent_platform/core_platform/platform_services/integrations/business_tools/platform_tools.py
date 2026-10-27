import asyncio
import hashlib
import json
import time
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError

from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.tool_gateway.harness import ToolExecutionHarness
from agent_platform.extension_contracts import (
    OperationRecord,
    PolicyDecision,
    RuntimeBindings,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolRisk,
)

from .defaults import BUILTIN_SCHEMAS, default_tool_contributions
from .registry import HttpToolHandler, ToolHandlerRegistry

__all__ = ["BUILTIN_SCHEMAS", "PlatformTools"]


class PlatformTools:
    def __init__(self, http, bindings: RuntimeBindings, row, allowed, kb_ids, emit):
        self.http, self.row = http, row
        self.bindings = bindings
        self.allowed, self.kb_ids, self.emit = allowed, [UUID(k) for k in kb_ids], emit
        self.extensions = bindings.extensions
        self.harness = ToolExecutionHarness()
        contributions = bindings.tool_contributions or default_tool_contributions(bindings)
        contributed_handlers = []
        self._visible_tool_names = set()
        for contribution in contributions:
            handlers = contribution.handlers(self.row, self.emit)
            contributed_handlers.extend(handlers)
            visible = getattr(contribution, "visible", None)
            if visible is None or visible(self.row):
                self._visible_tool_names.update(handler.definition.name for handler in handlers)
        self.handlers = ToolHandlerRegistry(
            tuple(contributed_handlers)
            + tuple(HttpToolHandler(self.http, spec) for spec in self.http.specs.values())
        )
        contribution_registry = getattr(bindings, "contributions", None)
        if contribution_registry is not None and hasattr(
            contribution_registry, "validate_tool_definitions"
        ):
            for definition in self.handlers.definitions(self.allowed):
                if not contribution_registry.is_registered_capability(definition.capability):
                    continue
                contribution_registry.validate_tool_definitions(
                    definition.capability,
                    (definition,),
                )
        elif self.extensions is not None and hasattr(
            self.extensions, "validate_contribution_permissions"
        ):
            for definition in self.handlers.definitions(self.allowed):
                self.extensions.validate_contribution_permissions(
                    definition.capability,
                    definition.required_permissions,
                )

    def _risk(self, name) -> ToolRisk:
        handler = self.handlers.resolve(name)
        if handler is not None:
            return handler.definition.risk
        if name in self.http.specs:
            return self.http.specs[name].effect
        return "read"

    def _capability_enabled(self, name):
        handler = self.handlers.resolve(name)
        if handler is None or self.extensions is None:
            return True
        return self.extensions.is_enabled(handler.definition.capability)

    def _execution_context(self):
        return ToolExecutionContext(
            tenant_id=self.row["tenant_id"],
            run_id=UUID(str(self.row["id"])),
            conversation_id=UUID(str(self.row["conversation_id"])),
            actor_id=f"runtime:{self.row['id']}",
            source="runtime",
        )

    def _idempotency_key(self, name, args):
        if self._risk(name) not in {"write", "irreversible"}:
            return None
        payload = json.dumps(
            {"run_id": str(self.row["id"]), "tool": name, "arguments": args},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        return "runtime:" + str(self.row["id"]) + ":" + hashlib.sha256(payload.encode()).hexdigest()

    def _operation_id(self, name, args):
        key = self._idempotency_key(name, args)
        return uuid5(NAMESPACE_URL, key) if key else uuid4()

    @property
    def schemas(self):
        schemas = [
            definition.model_schema()
            for definition in self.handlers.definitions(self.allowed)
            if self._capability_enabled(definition.name)
            and definition.name in self._visible_tool_names
        ]
        return self.http.schemas + schemas

    async def execute(self, name, args):
        idempotency_key = self._idempotency_key(name, args)
        if idempotency_key and self.bindings.replay is not None:
            cached = await self.bindings.replay.get(idempotency_key)
            if cached is not None:
                return cached
        call_id, started, result = (
            self._operation_id(name, args),
            time.monotonic(),
            None,
        )
        effect = self._risk(name)
        adapter = "builtin" if self.handlers.resolve(name) is not None else "http"
        version = next(
            (
                s.get("version")
                for s in self.row.get("config", {}).get("agent", {}).get("tools", [])
                if s["spec"]["name"] == name
            ),
            None,
        )
        status, error = "failed", None
        try:
            result = await self._execute(name, args)
            status = (
                "requires_confirmation"
                if result.get("ok") and effect == "proposal"
                else "succeeded"
                if result.get("ok")
                else "failed"
            )
            error = result.get("error")
            payload = {
                **result,
                "call_id": str(call_id),
                "execution_status": status,
                "retryable": False,
                "effect": effect,
                "tool_version": version,
            }
            if idempotency_key and payload.get("ok") and self.bindings.replay is not None:
                await self.bindings.replay.put(idempotency_key, payload)
            return payload
        except asyncio.CancelledError:
            status, error = "cancelled", "tool_cancelled"
            raise
        finally:
            if self.bindings.ledger is not None:
                await self.bindings.ledger.record(
                    OperationRecord(
                        id=call_id,
                        tenant_id=self.row["tenant_id"],
                        run_id=self.row["id"],
                        tool_name=name,
                        tool_version=version,
                        adapter_type=adapter,
                        effect=effect,
                        status=status,
                        error_code=error,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                )

    async def _execute(self, name, args):
        try:
            if not self._capability_enabled(name):
                raise DomainError("capability_disabled", 409)
            policy = self.bindings.policy
            if hasattr(policy, "evaluate_tool"):
                decision = await policy.evaluate_tool(
                    self._execution_context(), name, self.allowed, self._risk(name)
                )
                if not decision.allowed:
                    raise DomainError("tool_not_allowed", 403)
            else:
                await policy.check(self.row["tenant_id"], name, self.allowed)
                decision = PolicyDecision(
                    effect="allow",
                    reason_code="legacy_compat",
                    risk=self._risk(name),
                )
            handler = self.handlers.resolve(name)
            if handler is not None:
                request = ToolExecutionRequest(
                    definition=handler.definition,
                    context=self._execution_context(),
                    arguments=args,
                    idempotency_key=self._idempotency_key(name, args),
                )
                return self._legacy_result(await self.harness.execute(handler, request, decision))
            return await self.http.execute(name, args)
        except ValidationError:
            return {"ok": False, "error": "invalid_arguments"}
        except DomainError as exc:
            return {"ok": False, "error": exc.code}

    def _legacy_result(self, result: ToolExecutionResult):
        payload = {"ok": result.status != "failed"}
        if result.status != "failed" or result.data is not None:
            payload["data"] = result.data
        if result.message is not None:
            payload["message"] = result.message
        if result.error_code is not None:
            payload["error"] = result.error_code
        if result.confirmation_ref is not None:
            payload["confirmation_ref"] = str(result.confirmation_ref)
        payload.update(result.metadata)
        return payload
