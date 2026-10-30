"""Runtime-specific adapters assembled by the shared application runtime."""

import json
from collections import OrderedDict

from agent_platform.applications.platform_runtime.tool_defaults import BUILTIN_SCHEMAS
from agent_platform.business_capabilities.evaluation.service import MockTools
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault
from agent_platform.core_platform.platform_services.integrations.business_tools.platform_tools import (
    PlatformTools,
)
from agent_platform.core_platform.platform_services.model_gateway.gateway import GatewayChatModel
from agent_platform.core_platform.platform_services.model_gateway.service import build_model
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway
from agent_platform.extension_contracts import RuntimeBindings


class RuntimeFactory:
    """Build one Runtime instance from a run snapshot and explicit bindings."""

    def __init__(self, base_runtime, bindings, client, settings, shared_limit):
        if not isinstance(bindings, RuntimeBindings):
            raise TypeError("RuntimeFactory requires RuntimeBindings")
        self.base_runtime, self.client, self.settings = base_runtime, client, settings
        self.bindings = bindings
        self.limit = shared_limit
        self.models = OrderedDict()

    @property
    def legacy(self):
        """Expose the fixed runtime used by runs without an agent snapshot.

        ``RuntimeFactory`` owns both the per-run runtime construction path and
        the pre-agent-snapshot compatibility path.  Keeping the latter
        available under its historical name lets operational/test adapters
        replace the legacy model without changing the factory contract.
        """
        return self.base_runtime

    def model(self, schemas):
        key = json.dumps(schemas, sort_keys=True)
        if key not in self.models:
            self.models[key] = build_model(self.settings, schemas)
            if len(self.models) > 32:
                self.models.popitem(last=False)
        return self.models[key]

    def effective(self, snapshot):
        languages = {
            "auto": "Match the language of the user's latest message.",
            "zh-CN": "Reply in Simplified Chinese.",
            "zh-TW": "Reply in Traditional Chinese.",
            "en": "Reply in English.",
            "hi": "Reply in Hindi using the Devanagari script.",
        }
        language_rule = languages[snapshot["config"].get("reply_language", "auto")]
        return self.settings.model_copy(
            update={
                "system_prompt": self.settings.system_prompt
                + "\n"
                + snapshot["config"]["system_prompt"]
                + "\nResponse language policy (takes precedence over other language preferences in this prompt): "
                + language_rule
                + " Preserve proper names, identifiers and quoted source text when appropriate.",
                "max_model_rounds": self.bindings.policy.check_rounds(
                    snapshot["config"]["max_model_rounds"], self.settings
                ),
                "summary_enabled": self.settings.summary_enabled
                and snapshot["config"].get("summary_enabled", True),
            }
        )

    async def for_run(self, row, emit):
        snapshot = row["config"].get("agent")
        if not snapshot:
            return self.base_runtime
        http = ToolGateway(
            self.client,
            [HttpTool.model_validate(s["spec"]) for s in snapshot["tools"]],
            credential_resolver=lambda spec: self.bindings.tools.credential_headers(
                row["tenant_id"], spec
            ),
        )
        http.limit = self.limit
        tools = PlatformTools(
            http,
            self.bindings,
            row,
            snapshot["config"]["tool_names"],
            snapshot["config"]["knowledge_base_ids"],
            emit,
        )
        return RuntimeEngine(
            self.bound_model(snapshot, tools.schemas, row["id"]),
            tools,
            self.effective(snapshot),
        )

    def bound_model(self, snapshot, schemas, run_id=None):
        config = snapshot["config"]
        if config.get("model_profile_id"):
            return GatewayChatModel(
                self.bindings.gateway,
                self.settings.tenant_id,
                config["model_profile_id"],
                config["model_profile_version"],
                schemas,
                run_id,
            )
        raise RuntimeFault("agent_model_required")

    def evaluation(self, snapshot, responses):
        schemas = [HttpTool.model_validate(s["spec"]).model_schema() for s in snapshot["tools"]]
        schemas += [
            schema
            for name, schema in BUILTIN_SCHEMAS.items()
            if name in snapshot["config"]["tool_names"]
        ]
        mocks = MockTools(schemas, responses)
        return (
            RuntimeEngine(self.bound_model(snapshot, schemas), mocks, self.effective(snapshot)),
            mocks,
        )
