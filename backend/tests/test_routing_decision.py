from uuid import uuid4

import pytest

from agent_platform.business_capabilities.customer_service.routing.decision import (
    IngressResult,
    decide_ingress,
)
from agent_platform.business_capabilities.customer_service.routing.settings import (
    CustomerServiceRoutingSettings,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


class FakeAgents:
    def __init__(self, snapshot=None):
        self.snapshot_value = snapshot
        self.calls = []

    async def snapshot(self, tenant, agent_id, conn):
        self.calls.append((tenant, agent_id, conn))
        return self.snapshot_value


class FakeMemory:
    def __init__(self, flags=None):
        self.flags = flags or []
        self.calls = []

    async def active_flags(self, tenant, customer_id, limit):
        self.calls.append((tenant, customer_id, limit))
        return self.flags


def _conv(**overrides):
    values = {
        "id": uuid4(),
        "tenant_id": "tenant-a",
        "business_id": "customer-service",
        "workspace_id": "default",
        "mode": "bot",
        "agent_id": None,
        "customer_id": None,
    }
    values.update(overrides)
    return values


def _settings(**overrides):
    return Settings(_env_file=None, **overrides)


def _routing_settings():
    return CustomerServiceRoutingSettings(_env_file=None)


@pytest.mark.asyncio
async def test_closed_rejects_before_reading_agent_snapshot():
    conv = _conv(mode="closed", agent_id=uuid4())
    agents = FakeAgents(snapshot={"config": {}})
    result = await decide_ingress(
        conn=object(),
        conv=conv,
        message="hello",
        request_id=uuid4(),
        agents=agents,
        memory=FakeMemory(),
        settings=_settings(),
        routing_settings=_routing_settings(),
    )

    assert isinstance(result, IngressResult)
    assert result.decision.disposition == "reject"
    assert result.decision.action == "reject"
    assert result.decision.reason_code == "conversation_closed"
    assert result.decision.execution_tier is None
    assert result.decision.message_length == len("hello")
    assert result.agent_snapshot is None
    assert agents.calls == []


@pytest.mark.asyncio
async def test_handoff_rule_wins_over_human_mode_and_is_locale_agnostic():
    conv = _conv(mode="human", agent_id=uuid4(), customer_id=uuid4())
    agents = FakeAgents(snapshot={"config": {}})
    result = await decide_ingress(
        conn=object(),
        conv=conv,
        message=" HUMAN. ",
        request_id=uuid4(),
        agents=agents,
        memory=FakeMemory(),
        settings=_settings(),
        routing_settings=_routing_settings(),
    )

    assert result.decision.disposition == "handoff"
    assert result.decision.action == "request_handoff"
    assert result.decision.reason_code == "user_requested_human"
    assert result.decision.matched_rule_id == "en_human_request_001"
    assert result.decision.execution_tier is None
    assert result.agent_snapshot is None
    assert agents.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "reason"),
    [("human", "human_mode_active"), ("waiting", "waiting_mode_active")],
)
async def test_human_and_waiting_modes_defer(mode, reason):
    result = await decide_ingress(
        conn=object(),
        conv=_conv(mode=mode),
        message="hello",
        request_id=uuid4(),
        agents=FakeAgents(snapshot={"config": {}}),
        memory=FakeMemory(),
        settings=_settings(),
        routing_settings=_routing_settings(),
    )

    assert result.decision.disposition == "defer"
    assert result.decision.action == "defer"
    assert result.decision.reason_code == reason
    assert result.decision.execution_tier is None
    assert result.agent_snapshot is None


@pytest.mark.asyncio
async def test_blacklist_handoff_fetches_one_snapshot_and_reuses_it():
    agent_id = uuid4()
    customer_id = uuid4()
    snapshot = {"config": {}, "tools": []}
    agents = FakeAgents(snapshot=snapshot)
    memory = FakeMemory(flags=[{"key": "blacklist"}])
    result = await decide_ingress(
        conn=object(),
        conv=_conv(agent_id=agent_id, customer_id=customer_id),
        message="hello",
        request_id=uuid4(),
        agents=agents,
        memory=memory,
        settings=_settings(memory_blacklist_auto_handoff=True),
        routing_settings=_routing_settings(),
    )

    assert result.decision.disposition == "handoff"
    assert result.decision.reason_code == "blacklist_flag"
    assert result.agent_snapshot is snapshot
    assert agents.calls == [("tenant-a", agent_id, agents.calls[0][2])]
    assert memory.calls == [("tenant-a", customer_id, 3)]


@pytest.mark.asyncio
async def test_no_agent_with_unconfigured_model_rejects_after_rules():
    result = await decide_ingress(
        conn=object(),
        conv=_conv(mode="bot"),
        message="hello",
        request_id=uuid4(),
        agents=FakeAgents(),
        memory=None,
        settings=_settings(model_backend="unconfigured"),
        routing_settings=_routing_settings(),
    )

    assert result.decision.disposition == "reject"
    assert result.decision.action == "reject"
    assert result.decision.reason_code == "model_not_configured"
    assert result.decision.execution_tier is None
    assert result.agent_snapshot is None


@pytest.mark.asyncio
async def test_normal_message_continues_and_carries_agent_snapshot():
    agent_id = uuid4()
    snapshot = {"config": {}, "tools": []}
    agents = FakeAgents(snapshot=snapshot)
    result = await decide_ingress(
        conn=object(),
        conv=_conv(agent_id=agent_id),
        message="hello",
        request_id=uuid4(),
        agents=agents,
        memory=FakeMemory(),
        settings=_settings(),
        routing_settings=_routing_settings(),
    )

    assert result.decision.disposition == "continue"
    assert result.decision.execution_tier == "agent"
    assert result.decision.action == "submit_agent_run"
    assert result.decision.reason_code == "default_agent"
    assert result.agent_snapshot is snapshot
    assert len(agents.calls) == 1
