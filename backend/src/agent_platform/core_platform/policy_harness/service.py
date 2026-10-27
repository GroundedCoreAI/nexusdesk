from agent_platform.core_platform.platform_services.identity.context import ExecutionContext
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.extension_contracts import (
    ConfirmationRequirement,
    ExecutionConstraint,
    PolicyContext,
    PolicyDecision,
    ToolExecutionContext,
    ToolRisk,
)

from .contracts import Decision, ResourceFacts


class ExecutionPolicy:
    """Server-side capability checks. Tool names from the model grant no permissions."""

    def __init__(self, registry, contribution_registry=None):
        self.registry = registry
        self.contribution_registry = contribution_registry

    def authorize(self, context: ExecutionContext, action: str, resource: ResourceFacts):
        roles = {
            "resource.read": {"admin", "operator", "viewer"},
            "configuration.write": {"admin"},
            "service.operate": {"admin", "operator"},
            "business.confirm": {"admin", "operator"},
            "tool.invoke": {"runtime"},
        }
        if context.tenant_id != resource.tenant_id:
            return Decision("deny", "resource_scope_denied")
        if not resource.enabled:
            return Decision("deny", "resource_disabled")
        if not context.roles.intersection(roles.get(action, set())):
            return Decision("deny", "action_not_authorized")
        if action == "tool.invoke" and resource.capability not in resource.allowed_capabilities:
            return Decision("deny", "capability_not_granted")
        obligations = ("verify_business_confirmation",) if action == "business.confirm" else ()
        return Decision("allow", "authorized", obligations=obligations)

    async def check(self, tenant, name, allowed):
        decision = await self.evaluate_tool(
            ToolExecutionContext(tenant_id=tenant, source="worker"),
            name,
            allowed,
        )
        if not decision.allowed:
            raise DomainError("tool_not_allowed", 403)
        return decision

    async def evaluate_tool(self, context, name, allowed, risk: ToolRisk = "read"):
        """Return a contract-level decision for a trusted tool invocation."""

        policy_context = PolicyContext(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id or "runtime",
            roles=frozenset({"runtime"}),
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            source=context.source,
        )
        internal_context = ExecutionContext(
            policy_context.tenant_id,
            policy_context.actor_id,
            policy_context.roles,
            source=policy_context.source,
            conversation_id=str(policy_context.conversation_id)
            if policy_context.conversation_id
            else None,
            run_id=str(policy_context.run_id) if policy_context.run_id else None,
        )
        facts = ResourceFacts(
            context.tenant_id,
            await self.registry.enabled(context.tenant_id, name),
            name,
            frozenset(allowed),
        )
        decision = self.authorize(internal_context, "tool.invoke", facts)
        requires_confirmation = decision.allowed and risk == "proposal"
        result = PolicyDecision(
            effect=decision.effect,
            reason_code=decision.reason_code,
            risk=risk,
            confirmation=ConfirmationRequirement(
                required=requires_confirmation,
                action="confirm_tool" if requires_confirmation else None,
            ),
            constraint=ExecutionConstraint(idempotency_required=risk in {"write", "irreversible"}),
            policy_version=decision.policy_version,
        )
        if not result.allowed:
            return result
        if self.contribution_registry is None:
            providers = ()
        else:
            providers = self.contribution_registry.policy_providers(active_only=True)
        for capability_id, provider in providers:
            try:
                extension_decision = await provider.evaluate(
                    policy_context,
                    capability_id,
                    name,
                    risk,
                )
            except Exception:  # noqa: BLE001 - fail closed for extension policy errors
                return PolicyDecision(
                    effect="deny",
                    reason_code="extension_policy_error",
                    risk=risk,
                    policy_version="extension-policy-error",
                )
            if not extension_decision.allowed:
                return extension_decision
            result = self._tighten(result, extension_decision)
        return result

    @staticmethod
    def _tighten(
        baseline: PolicyDecision,
        extension: PolicyDecision,
    ) -> PolicyDecision:
        """Merge an allowed extension decision without weakening the baseline."""

        expiration_values = [
            value
            for value in (
                baseline.confirmation.expires_seconds,
                extension.confirmation.expires_seconds,
            )
            if value is not None
        ]
        return baseline.model_copy(
            update={
                "confirmation": baseline.confirmation.model_copy(
                    update={
                        "required": (
                            baseline.confirmation.required or extension.confirmation.required
                        ),
                        "action": (extension.confirmation.action or baseline.confirmation.action),
                        "expires_seconds": min(expiration_values) if expiration_values else None,
                    }
                ),
                "constraint": baseline.constraint.model_copy(
                    update={
                        "max_attempts": min(
                            baseline.constraint.max_attempts,
                            extension.constraint.max_attempts,
                        ),
                        "timeout_seconds": min(
                            baseline.constraint.timeout_seconds,
                            extension.constraint.timeout_seconds,
                        ),
                        "concurrency_key": (
                            extension.constraint.concurrency_key
                            or baseline.constraint.concurrency_key
                        ),
                        "idempotency_required": (
                            baseline.constraint.idempotency_required
                            or extension.constraint.idempotency_required
                        ),
                    }
                ),
                "policy_version": f"{baseline.policy_version}+{extension.policy_version}",
            }
        )

    def check_rounds(self, requested, settings):
        return min(requested, settings.max_model_rounds)
