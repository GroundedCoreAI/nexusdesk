"""Provider executor declarations.

A provider record is a placeholder until it declares how its data is read. The
declaration lives in ``config.executors`` and is validated here, at the
configuration boundary, so a broken reference can never reach the execution
path at conversation time.

Shape::

    {"executors": {
        "get":  {"tool": "order_status", "arguments": {"order_id": "$object.id"}},
        "list": {"tool": "order_list",   "arguments": {"customer_id": "$customer.id"},
                 "result_root": "data.items"}
    }}

Only the tool gateway naming rules are enforced: a tool name must be callable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent_platform.core_platform.platform_services.persistence.store import DomainError

EXECUTOR_TOOL_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
EXECUTOR_ROLES = ("get", "list")
EXECUTOR_ERROR_POLICIES = frozenset({"human", "fail", "ignore"})
EXECUTOR_FIELDS = frozenset({"tool", "arguments", "result_root", "on_error"})
REFERENCE = re.compile(r"^\$(object|customer|decision)\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)$")
PATH = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")


def _validate_template(value: Any) -> None:
    if isinstance(value, str):
        if value.startswith("$$"):
            return
        if value.startswith("$") and not REFERENCE.match(value):
            raise DomainError("provider_executor_template_invalid", 422)
        return
    if isinstance(value, dict):
        for item in value.values():
            _validate_template(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_template(item)


@dataclass(frozen=True)
class ExecutorSpec:
    """One declared way to read data for a provider."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result_root: str = ""
    on_error: str = "human"

    @classmethod
    def parse(cls, raw: Any) -> ExecutorSpec | None:
        if raw is None or raw == "" or raw == {}:
            return None
        if not isinstance(raw, dict):
            raise DomainError("provider_executor_invalid", 422)
        unknown = set(raw) - EXECUTOR_FIELDS
        if unknown:
            raise DomainError("provider_executor_unknown_field", 422)
        tool = str(raw.get("tool") or "").strip()
        if not EXECUTOR_TOOL_NAME.fullmatch(tool):
            raise DomainError("provider_executor_tool_invalid", 422)
        arguments = raw.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise DomainError("provider_executor_arguments_invalid", 422)
        _validate_template(arguments)
        result_root = str(raw.get("result_root") or "").strip().strip(".")
        if result_root and not PATH.fullmatch(result_root):
            raise DomainError("provider_executor_result_root_invalid", 422)
        on_error = str(raw.get("on_error") or "human").strip()
        if on_error not in EXECUTOR_ERROR_POLICIES:
            raise DomainError("provider_executor_error_policy_invalid", 422)
        return cls(
            tool=tool,
            arguments=arguments,
            result_root=result_root,
            on_error=on_error,
        )

    def public(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "result_root": self.result_root,
            "on_error": self.on_error,
        }


def parse_executors(config: dict[str, Any] | None) -> dict[str, ExecutorSpec]:
    """Read ``config.executors`` from one provider record.

    Returns only the roles that declared an executor.  An empty mapping means
    the provider is a placeholder and the simulator keeps its label-only
    behaviour.
    """

    if not config:
        return {}
    raw = config.get("executors")
    if raw is None:
        # A single ``executor`` block historically meant the read path.
        single = ExecutorSpec.parse(config.get("executor"))
        return {"get": single} if single is not None else {}
    if not isinstance(raw, dict):
        raise DomainError("provider_executor_invalid", 422)
    executors: dict[str, ExecutorSpec] = {}
    for role, value in raw.items():
        if role not in EXECUTOR_ROLES:
            raise DomainError("provider_executor_role_invalid", 422)
        parsed = ExecutorSpec.parse(value)
        if parsed is not None:
            executors[role] = parsed
    return executors


def validate_executors(config: dict[str, Any] | None) -> None:
    """Reject a malformed declaration before it is persisted."""

    parse_executors(config)


__all__ = [
    "EXECUTOR_ERROR_POLICIES",
    "EXECUTOR_ROLES",
    "ExecutorSpec",
    "parse_executors",
    "validate_executors",
]
