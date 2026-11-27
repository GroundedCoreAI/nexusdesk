"""Bounded Skill test execution and honest outcome classification."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from agent_platform.business_capabilities.knowledge.retrieval import SearchInput
from agent_platform.core_platform.platform_services.model_gateway.contracts import (
    ChatRequest,
    Message,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway

from .models import SkillDefinition, validate_output

TestStatus = Literal["passed", "failed", "error", "blocked"]
ExecutionKind = Literal["live", "contract"]


@dataclass
class TestOutcome:
    status: TestStatus
    execution_kind: ExecutionKind
    output: Any = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    reason_code: str | None = None
    duration_ms: int = 0


class SkillTestExecutor:
    def __init__(self, settings: Any, gateway: Any, retrieval: Any, tools: Any, workspace: Any):
        self.settings = settings
        self.gateway = gateway
        self.retrieval = retrieval
        self.tools = tools
        self.workspace = workspace

    async def execute(
        self,
        *,
        tenant: str,
        actor: str,
        definition: SkillDefinition,
        payload: dict[str, Any],
        scenario: str,
    ) -> TestOutcome:
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.settings.skill_test_timeout_seconds):
                outcome = await self._execute(
                    tenant=tenant,
                    actor=actor,
                    definition=definition,
                    payload=payload,
                    scenario=scenario,
                )
        except TimeoutError:
            outcome = TestOutcome(
                "error",
                self._execution_kind(definition),
                diagnostics={"stage": "timeout"},
                reason_code="skill_test_timeout",
            )
        except DomainError as exc:
            outcome = TestOutcome(
                "error",
                self._execution_kind(definition),
                diagnostics={"stage": "dependency"},
                reason_code=exc.code,
            )
        except (KeyError, TypeError, ValueError):
            outcome = TestOutcome(
                "error",
                self._execution_kind(definition),
                diagnostics={"stage": "executor"},
                reason_code="skill_test_execution_error",
            )
        outcome.duration_ms = max(0, int((time.monotonic() - started) * 1000))
        outcome.diagnostics = _bounded_diagnostics(outcome.diagnostics)
        if outcome.output is not None:
            encoded = _json_size(outcome.output)
            if encoded > self.settings.skill_test_max_output_chars:
                outcome.status = "failed"
                outcome.output = None
                outcome.reason_code = "skill_test_output_too_large"
                outcome.diagnostics = {
                    **outcome.diagnostics,
                    "output_chars": encoded,
                }
        return outcome

    @staticmethod
    def _execution_kind(definition: SkillDefinition) -> ExecutionKind:
        return "contract" if definition.type == "handoff" else "live"

    async def _execute(
        self,
        *,
        tenant: str,
        actor: str,
        definition: SkillDefinition,
        payload: dict[str, Any],
        scenario: str,
    ) -> TestOutcome:
        if definition.type == "instruction":
            return await self._instruction(tenant, actor, definition, payload, scenario)
        if definition.type == "knowledge":
            return await self._knowledge(tenant, definition, payload)
        if definition.type == "query":
            return await self._query(tenant, definition, payload, scenario)
        if definition.type == "action":
            return TestOutcome(
                "blocked",
                "live",
                diagnostics={"policy": "write_action_tests_disabled"},
                reason_code="skill_write_test_unsafe",
            )
        return self._handoff(definition, payload)

    async def _instruction(
        self,
        tenant: str,
        actor: str,
        definition: SkillDefinition,
        payload: dict[str, Any],
        scenario: str,
    ) -> TestOutcome:
        dependencies = definition.dependencies
        if dependencies.model_profile_id is None or dependencies.model_profile_version is None:
            return TestOutcome(
                "error",
                "live",
                diagnostics={"dependency": "model_profile"},
                reason_code="model_profile_unavailable",
            )
        prompt = (
            definition.instructions.strip()
            + "\n\nTest scenario: "
            + (scenario.strip() or "not provided")
            + "\nTest input:\n"
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        try:
            result = await self.gateway.invoke(
                tenant,
                dependencies.model_profile_id,
                dependencies.model_profile_version,
                ChatRequest(messages=[Message(role="user", content=prompt)]),
                actor=actor,
            )
        except DomainError as exc:
            return TestOutcome(
                "error",
                "live",
                diagnostics={"dependency": "model_profile"},
                reason_code=exc.code,
            )
        content = str(result.get("payload", {}).get("content", "")).strip()
        value: Any = content
        if definition.output.format == "json":
            try:
                value = json.loads(content)
            except ValueError:
                return TestOutcome(
                    "failed",
                    "live",
                    diagnostics={"output_schema_valid": False},
                    reason_code="output_schema_invalid",
                )
        try:
            validate_output(definition, value)
        except ValueError:
            return TestOutcome(
                "failed",
                "live",
                diagnostics={"output_schema_valid": False},
                reason_code="output_schema_invalid",
            )
        return TestOutcome(
            "passed",
            "live",
            output=value,
            diagnostics={
                "model_profile_version": dependencies.model_profile_version,
                "output_schema_valid": True,
            },
        )

    async def _knowledge(
        self,
        tenant: str,
        definition: SkillDefinition,
        payload: dict[str, Any],
    ) -> TestOutcome:
        kb_ids = definition.dependencies.knowledge_base_ids
        if not kb_ids:
            return TestOutcome(
                "error",
                "live",
                diagnostics={"dependency": "knowledge_base"},
                reason_code="knowledge_base_unavailable",
            )
        query = _query_text(payload)
        try:
            result = await self.retrieval.search(
                tenant,
                SearchInput(query=query[:500], kb_ids=kb_ids),
            )
        except (DomainError, ValueError) as exc:
            return TestOutcome(
                "error",
                "live",
                diagnostics={"dependency": "knowledge_base"},
                reason_code=getattr(exc, "code", "knowledge_base_unavailable"),
            )
        if definition.output.format == "json":
            output: Any = result
        else:
            output = "\n".join(str(hit.get("excerpt", "")) for hit in result["items"])
        try:
            validate_output(definition, output)
        except ValueError:
            if definition.output.format == "json":
                return TestOutcome(
                    "failed",
                    "live",
                    diagnostics={"output_schema_valid": False},
                    reason_code="output_schema_invalid",
                )
            # An empty retrieval result is still a valid completed search. The
            # declared text contract is represented by a bounded status string.
            output = "No knowledge snippets matched the test input."
        return TestOutcome(
            "passed",
            "live",
            output=output,
            diagnostics={
                "knowledge_base_count": len(kb_ids),
                "hit_count": len(result["items"]),
                "total_ms": result["total_ms"],
            },
        )

    async def _query(
        self,
        tenant: str,
        definition: SkillDefinition,
        payload: dict[str, Any],
        scenario: str,
    ) -> TestOutcome:
        if not self.settings.skill_live_tool_tests_enabled:
            return TestOutcome(
                "blocked",
                "live",
                diagnostics={"policy": "live_tool_tests_disabled"},
                reason_code="skill_live_tool_tests_disabled",
            )
        names = definition.dependencies.tool_names
        if not names:
            return TestOutcome(
                "error",
                "live",
                diagnostics={"dependency": "tool"},
                reason_code="tool_unavailable",
            )
        try:
            rows = await self.tools.resolve(tenant, names)
        except DomainError as exc:
            return TestOutcome(
                "error",
                "live",
                diagnostics={"dependency": "tool"},
                reason_code=exc.code,
            )
        specs = [HttpTool.model_validate(row["spec"]) for row in rows]
        read_specs = [spec for spec in specs if spec.effect == "read"]
        if not read_specs:
            return TestOutcome(
                "error",
                "live",
                diagnostics={"dependency": "read_tool"},
                reason_code="read_tool_required",
            )
        gateway = ToolGateway(
            self.workspace.client,
            read_specs,
            concurrency=max(1, min(8, self.settings.tool_concurrency)),
            credential_resolver=lambda spec: self.tools.credential_headers(tenant, spec),
            network_policy=self.workspace.network_policy,
        )
        result = await gateway.execute(read_specs[0].name, payload)
        if not result.get("ok"):
            error = str(result.get("error", "tool_execution_error"))
            status: TestStatus = (
                "failed" if error in {"invalid_arguments", "invalid_output_schema"} else "error"
            )
            return TestOutcome(
                status,
                "live",
                diagnostics={"tool": read_specs[0].name, "error": error[:100]},
                reason_code=error[:200],
            )
        value = result.get("data")
        contract_value: Any = value
        if definition.output.format == "text" and not isinstance(value, str):
            contract_value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        try:
            validate_output(definition, contract_value)
        except ValueError:
            return TestOutcome(
                "failed",
                "live",
                diagnostics={"output_schema_valid": False, "tool": read_specs[0].name},
                reason_code="output_schema_invalid",
            )
        return TestOutcome(
            "passed",
            "live",
            output=value,
            diagnostics={
                "tool": read_specs[0].name,
                "output_schema_valid": True,
                "scenario_present": bool(scenario.strip()),
            },
        )

    @staticmethod
    def _handoff(definition: SkillDefinition, payload: dict[str, Any]) -> TestOutcome:
        queue = definition.dependencies.handoff_queue
        if not queue:
            return TestOutcome(
                "error",
                "contract",
                diagnostics={"dependency": "handoff_queue"},
                reason_code="handoff_queue_unavailable",
            )
        return TestOutcome(
            "passed",
            "contract",
            output={"queue": queue, "payload": payload},
            diagnostics={"queue": queue, "contract_only": True},
        )


def _query_text(payload: dict[str, Any]) -> str:
    for value in payload.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return len(str(value))


def _bounded_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in list(value.items())[:20]:
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[str(key)[:80]] = item[:200] if isinstance(item, str) else item
    return safe


__all__ = ["SkillTestExecutor", "TestOutcome"]
