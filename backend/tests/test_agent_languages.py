from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent_platform.applications.customer_service.runtime_factory import RuntimeFactory
from agent_platform.business_capabilities.agent_config.service import AgentConfig
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.extension_contracts import RuntimeBindings


@pytest.mark.parametrize(
    "language, expected",
    [
        ("auto", "Match the language of the user's latest message."),
        ("zh-CN", "Reply in Simplified Chinese."),
        ("zh-TW", "Reply in Traditional Chinese."),
        ("en", "Reply in English."),
        ("hi", "Reply in Hindi using the Devanagari script."),
    ],
)
def test_language_policy_reaches_runtime_without_changing_source(language, expected):
    source = "保留原始中文指令"
    config = AgentConfig(system_prompt=source, reply_language=language)
    bindings = RuntimeBindings(
        policy=SimpleNamespace(check_rounds=lambda rounds, settings: rounds)
    )
    factory = RuntimeFactory(None, bindings, None, Settings(), None)
    effective = factory.effective({"config": config.model_dump()})
    assert expected in effective.system_prompt
    assert source in effective.system_prompt
    assert config.system_prompt == source
    assert effective.max_model_rounds == 6


def test_legacy_config_defaults_and_rejects_unsupported_languages():
    assert AgentConfig(system_prompt="hello").reply_language == "auto"
    with pytest.raises(ValidationError):
        AgentConfig(system_prompt="hello", reply_language="fr")
