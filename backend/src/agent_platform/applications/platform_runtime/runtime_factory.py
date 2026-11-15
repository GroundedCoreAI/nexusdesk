"""Runtime-specific adapters assembled by the shared application runtime."""

import json
from collections import OrderedDict

from agent_platform.applications.platform_runtime.tool_defaults import BUILTIN_SCHEMAS
from agent_platform.business_capabilities.customer_service.service_apps.runtime import (
    ApplicationRuntimeContext,
    ApplicationRuntimeResolver,
    application_http_tool_specs,
    application_knowledge_base_ids,
    authorized_tool_names,
)
from agent_platform.business_capabilities.evaluation.service import MockTools
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault
from agent_platform.core_platform.platform_services.integrations.business_tools.platform_tools import (
    PlatformTools,
)
from agent_platform.core_platform.platform_services.model_gateway.gateway import GatewayChatModel
from agent_platform.core_platform.platform_services.model_gateway.service import build_model
from agent_platform.core_platform.tool_gateway.egress import ToolEgressPolicy
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway
from agent_platform.extension_contracts import RuntimeBindings


class RuntimeFactory:
    """Build one Runtime instance from a run snapshot and explicit bindings."""

    def __init__(
        self,
        base_runtime,
        bindings,
        client,
        settings,
        shared_limit,
        network_policy=None,
        application_runtime=None,
    ):
        if not isinstance(bindings, RuntimeBindings):
            raise TypeError("RuntimeFactory requires RuntimeBindings")
        self.base_runtime, self.client, self.settings = base_runtime, client, settings
        self.bindings = bindings
        self.limit = shared_limit
        self.network_policy: ToolEgressPolicy | None = network_policy
        self.application_runtime = application_runtime or ApplicationRuntimeResolver(
            bindings.engine,
            None,
            settings,
        )
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
        application = row["config"].get("application")
        if application:
            specs = [
                HttpTool.model_validate(spec) for spec in application_http_tool_specs(application)
            ]
            allowed = authorized_tool_names(application)
            # Application skill tools are authorised by the snapshot itself; they
            # have no registered_tools row for the policy registry to find.
            skill_tools = frozenset(spec.name for spec in specs)

            async def credential_resolver(spec):
                return await self.application_runtime.credential_headers(
                    row["tenant_id"],
                    spec,
                    application_id=application.get("id"),
                    business_id=application.get("business_id"),
                    workspace_id=application.get("workspace_id"),
                )

        else:
            # Platform diagnostics may still use a direct Agent run. Customer
            # channels never reach this branch because their run snapshot is
            # application-scoped.
            specs = [HttpTool.model_validate(s["spec"]) for s in snapshot["tools"]]
            allowed = snapshot["config"]["tool_names"]
            skill_tools = frozenset()

            async def credential_resolver(spec):
                return await self.bindings.tools.credential_headers(
                    row["tenant_id"],
                    spec,
                )

        http = ToolGateway(
            self.client,
            specs,
            credential_resolver=credential_resolver,
            network_policy=self.network_policy,
        )
        http.limit = self.limit
        # Retrieval reads its scope from the snapshot it is handed, and that
        # snapshot is the Agent version's. A release may narrow the scope through
        # its own knowledge skill, so the run row carries the effective list.
        knowledge_base_ids = application_knowledge_base_ids(
            (application or {}).get("skills") or (),
            snapshot["config"].get("knowledge_base_ids") or (),
        )
        tools = PlatformTools(
            http,
            self.bindings,
            self._scoped_row(row, knowledge_base_ids),
            allowed,
            knowledge_base_ids,
            emit,
            skill_tools=skill_tools,
        )
        return RuntimeEngine(
            self.bound_model(snapshot, tools.schemas, row["id"]),
            tools,
            self.effective(snapshot),
        )

    @staticmethod
    def _scoped_snapshot(snapshot: dict, knowledge_base_ids: tuple[str, ...]) -> dict:
        """Return the snapshot with the knowledge scope this release actually uses.

        Retrieval reads its scope from the snapshot it is handed, and that snapshot
        is the Agent version's. A release may narrow the scope through its own
        knowledge skill, so the copy the tool container sees carries the effective
        list. The caller's snapshot keeps the Agent's own list, so the model, the
        trace and the audit still report what the Agent version declares.

        A copy is cheaper than teaching the knowledge capability about application
        skills: it must stay usable by a plain Agent run that has none.
        """

        if not knowledge_base_ids:
            return snapshot
        return {
            **snapshot,
            "config": {**snapshot["config"], "knowledge_base_ids": list(knowledge_base_ids)},
        }

    @classmethod
    def _scoped_row(cls, row: dict, knowledge_base_ids: tuple[str, ...]) -> dict:
        snapshot = row["config"].get("agent")
        if not snapshot:
            return row
        scoped = cls._scoped_snapshot(snapshot, knowledge_base_ids)
        if scoped is snapshot:
            return row
        return {**row, "config": {**row["config"], "agent": scoped}}

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
