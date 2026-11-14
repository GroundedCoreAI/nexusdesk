from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agent_platform.applications.platform_runtime.runtime_factory import RuntimeFactory
from agent_platform.business_capabilities.agent_config.service import AgentConfig
from agent_platform.business_capabilities.customer_service.service_apps.runtime import (
    ApplicationRuntimeContext,
    authorized_tool_names,
    declared_builtin_tools,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.extension_contracts import RuntimeBindings


class PreviewModel:
    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
        if len(tool_messages) >= 2:
            return AIMessage(content="订单查询与知识检索均已在预览中模拟完成。")
        if len(tool_messages) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "preview-knowledge",
                        "name": "knowledge_search",
                        "args": {"query": "预览政策"},
                    }
                ],
            )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "preview-query",
                    "name": "order_lookup",
                    "args": {"order_no": "PREVIEW-001"},
                }
            ],
        )


@pytest.mark.asyncio
async def test_preview_runtime_mocks_application_tools_without_upstream_calls():
    config = AgentConfig(
        system_prompt="Preview the application contract.",
        reply_language="zh-CN",
    )
    context = ApplicationRuntimeContext(
        application_id=uuid4(),
        application_version=0,
        application_key="preview-application",
        business_id="customer-service",
        workspace_id="default",
        agent_snapshot={
            "id": str(uuid4()),
            "version": 1,
            "config": config.model_dump(mode="json"),
        },
        skills=(
            {
                "key": "order_lookup",
                "type": "query",
                "name": "订单查询",
                "enabled": True,
                "connection_key": "orders",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"order_no": {"type": "string"}},
                    "required": ["order_no"],
                },
            },
        ),
        connections=(
            {
                "key": "orders",
                "executor_kind": "http",
                "endpoint": "https://business.example.com/orders",
                "method": "GET",
                "public_headers": {},
                "auth_kind": "none",
                "timeout_seconds": 5,
                "max_response_bytes": 2048,
            },
        ),
        builtin_tools=("knowledge_search",),
    )
    bindings = RuntimeBindings(policy=SimpleNamespace(check_rounds=lambda rounds, settings: rounds))
    factory = RuntimeFactory(None, bindings, None, Settings(), None)
    factory.bound_model = lambda snapshot, schemas, run_id=None: PreviewModel()

    result = await factory.preview_application(
        context,
        "帮我查订单 PREVIEW-001",
        allow_write=False,
    )

    assert result["reply"] == "订单查询与知识检索均已在预览中模拟完成。"
    assert result["tools"] == ["order_lookup", "knowledge_search"]
    assert result["violations"] == []
    assert all(event.get("upstream_called") is not True for event in result["events"])


def test_declared_builtin_tools_come_from_the_release_skills():
    """Retrieval is authorised by the skill, not by the Agent or by a key spelling."""

    assert declared_builtin_tools(()) == ()
    assert declared_builtin_tools(
        ({"key": "knowledge_search", "type": "knowledge"},)
    ) == ("knowledge_search",)
    # A switched-off skill declares nothing, which is what makes the toggle real.
    assert (
        declared_builtin_tools(
            ({"key": "knowledge_search", "type": "knowledge", "enabled": False},)
        )
        == ()
    )
    # Query and action skills grant their own HTTP tool, never a platform tool.
    assert declared_builtin_tools(({"key": "order_lookup", "type": "query"},)) == ()
    # The platform tool follows the skill type: renaming the skill cannot silently
    # drop retrieval the release still declares.
    assert declared_builtin_tools(({"key": "知识检索", "type": "knowledge"},)) == (
        "knowledge_search",
    )


def test_authorized_tool_names_ignores_an_undeclared_retrieval_tool():
    application = {
        "skills": [{"key": "knowledge_docs", "type": "knowledge", "enabled": False}],
        "connections": [],
        "builtin_tools": [],
    }
    assert authorized_tool_names(application) == []

    application["skills"] = [{"key": "knowledge_docs", "type": "knowledge"}]
    assert authorized_tool_names(application) == ["knowledge_search"]


class RecordingModel:
    """Answer without calling tools while recording the schemas the model saw."""

    def __init__(self, seen: list[list[dict]]) -> None:
        self.seen = seen

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        return AIMessage(content="好的，我按已有信息答复。")


@pytest.mark.asyncio
async def test_preview_never_offers_retrieval_the_release_did_not_declare():
    """A preview must not show a capability the customer-facing release lacks."""

    skills = (
        {
            "key": "order_lookup",
            "type": "query",
            "name": "订单查询",
            "enabled": True,
            "connection_key": "orders",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"order_no": {"type": "string"}},
                "required": ["order_no"],
            },
        },
    )
    context = ApplicationRuntimeContext(
        application_id=uuid4(),
        application_version=0,
        application_key="preview-without-knowledge",
        business_id="customer-service",
        workspace_id="default",
        agent_snapshot={
            "id": str(uuid4()),
            "version": 1,
            # The Agent still lists retrieval; the release does not declare it.
            "config": AgentConfig(
                system_prompt="Preview the application contract.",
                reply_language="zh-CN",
                tool_names=["knowledge_search"],
            ).model_dump(mode="json"),
        },
        skills=skills,
        connections=(
            {
                "key": "orders",
                "executor_kind": "http",
                "endpoint": "https://business.example.com/orders",
                "method": "GET",
                "public_headers": {},
                "auth_kind": "none",
                "timeout_seconds": 5,
                "max_response_bytes": 2048,
            },
        ),
        builtin_tools=declared_builtin_tools(skills),
    )
    bindings = RuntimeBindings(policy=SimpleNamespace(check_rounds=lambda rounds, settings: rounds))
    factory = RuntimeFactory(None, bindings, None, Settings(), None)
    seen: list[list[dict]] = []
    factory.bound_model = lambda snapshot, schemas, run_id=None: (
        seen.append(schemas) or RecordingModel(seen)
    )

    await factory.preview_application(context, "帮我查订单", allow_write=False)

    offered = [schema["function"]["name"] for schema in seen[0]]
    assert "order_lookup" in offered
    assert "knowledge_search" not in offered
