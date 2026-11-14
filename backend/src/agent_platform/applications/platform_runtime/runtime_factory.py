"""Runtime-specific adapters assembled by the shared application runtime."""

import json
import re
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import Final
from uuid import UUID

from pydantic import ValidationError

from agent_platform.applications.platform_runtime.tool_defaults import BUILTIN_SCHEMAS
from agent_platform.business_capabilities.evaluation.service import MockTools
from agent_platform.core_platform.agent_execution.contracts.config import EngineIdentity
from agent_platform.core_platform.agent_execution.contracts.instructions import (
    InstructionInput,
    instruction_contract_error,
)
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

# Public RuntimeFault codes raised by instruction preparation, defined once here
# and referenced by every raise site. T7 must register exactly these two strings
# in ``agent_execution.adapters.react.error_mapper._ERROR_MAP``: until it does,
# ``_ERROR_MAP.get(code, _INTERNAL_ERROR)`` degrades both to the public
# ``internal_error`` code, and the operator-facing difference between "no
# published Agent snapshot" and "unusable published Agent snapshot" — one of
# which is a legacy row and one of which is broken data — disappears. Keeping
# them as constants is what lets the tests pin the code per triggering condition
# without repeating the literals a third time.
AGENT_SNAPSHOT_REQUIRED: Final[str] = "agent_snapshot_required"
AGENT_SNAPSHOT_INVALID: Final[str] = "agent_snapshot_invalid"

# The compatibility default the execution-config layer applies when a published
# snapshot predates the ``engine`` key: the same triple, never a guess.
_DEFAULT_ENGINE: dict[str, str] = {
    "engine_id": "react",
    "protocol_id": "native",
    "adapter_version": "v1",
}

# Same grammar as the contract ``Slug`` type, so a name taken out of a
# ``ValidationError`` can never itself fail the error model it is fed into.
_FIELD_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+){0,39}$")


def _rejected_field(exc: ValidationError) -> str:
    """First offending top-level field name, or a neutral identifier.

    pydantic's own text repeats the rejected value (its head and tail); the only
    thing preparation may hand on is *which field* broke, which is a stable
    identifier and never conversation content or prompt text (C3, AC-7).
    """
    for error in exc.errors():
        location = error.get("loc") or ()
        name = location[0] if location else None
        if isinstance(name, str) and _FIELD_NAME.fullmatch(name):
            return name
    return "instruction_input"


def _instruction_agent_id(snapshot: Mapping[str, object]) -> UUID:
    value = snapshot.get("id")
    try:
        if type(value) is UUID:
            return value
        if type(value) is str:
            return UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise RuntimeFault(AGENT_SNAPSHOT_INVALID) from None
    raise RuntimeFault(AGENT_SNAPSHOT_INVALID)


def _instruction_engine(config: Mapping[str, object]) -> EngineIdentity:
    engine = config.get("engine")
    if engine is None:
        return EngineIdentity(**_DEFAULT_ENGINE)
    if not isinstance(engine, Mapping) or set(engine) - set(_DEFAULT_ENGINE):
        raise RuntimeFault(AGENT_SNAPSHOT_INVALID)
    try:
        return EngineIdentity(**engine)
    except ValidationError:
        raise RuntimeFault(AGENT_SNAPSHOT_INVALID) from None


class RuntimeFactory:
    """Build one Runtime instance from a run snapshot and explicit bindings."""

    def __init__(self, base_runtime, bindings, client, settings, shared_limit, network_policy=None):
        if not isinstance(bindings, RuntimeBindings):
            raise TypeError("RuntimeFactory requires RuntimeBindings")
        self.base_runtime, self.client, self.settings = base_runtime, client, settings
        self.bindings = bindings
        self.limit = shared_limit
        self.network_policy: ToolEgressPolicy | None = network_policy
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

    def prepare_instructions(
        self,
        row: Mapping[str, object],
        *,
        history: Sequence[Mapping[str, object]] = (),
        summary_message: str | None = None,
        customer_memory: str | None = None,
        engine_context: Mapping[str, object] | None = None,
    ) -> InstructionInput:
        """Compute the run's effective instructions before a runner exists (R-10).

        ``effective()`` — platform prompt + Agent prompt + the reply-language
        rule, the gated round budget, and the summary switch — is the only place
        those are derived, and this step calls it exactly once per run. The
        instruction provider downstream therefore never recomputes a prompt or
        re-renders anything: Summary and customer Memory arrive already rendered
        by the memory capability through the caller and are passed through as-is.

        Retention is the existing sliding window, read from the same effective
        settings the Engine uses for its own writeback. The Engine keeps computing
        the kept slice for history and ``dropped`` reporting; what is handed over
        here must be that same slice, and ``RuntimeEngine`` now checks exactly that
        on the prepared path — along with the current input and the rule that no
        Summary/Memory text is re-supplied there — so a preparation computed from
        a different settings object fails closed instead of drifting.

        Preparation stays pure: no model, tool gateway, ``PlatformTools``,
        Runtime instance, database write, or event emission happens here, which is
        what lets it sit in front of ``Adapter.start`` as a hard barrier. A claimed
        row without a published Agent snapshot has no instructions to prepare, so
        it fails closed here instead of inventing defaults. A value that breaks the
        instruction contract — an input over the DTO limit, a history row the DTO
        cannot carry, a live object where rendered text belongs — is reported as the
        instruction layer's own configuration error naming the field, never as
        pydantic text quoting what was rejected.
        """
        config = row.get("config")
        snapshot = config.get("agent") if isinstance(config, Mapping) else None
        if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("config"), Mapping):
            raise RuntimeFault(AGENT_SNAPSHOT_REQUIRED)
        agent_config = snapshot["config"]
        version = snapshot.get("version")
        if type(version) is not int or version < 1:
            raise RuntimeFault(AGENT_SNAPSHOT_INVALID)

        # The one and only effective-settings computation for this run.
        effective = self.effective(snapshot)
        kept = list(history)[-(effective.history_turns * 2) :] if effective.history_turns else []
        try:
            return InstructionInput(
                engine=_instruction_engine(agent_config),
                agent_id=_instruction_agent_id(snapshot),
                agent_version=version,
                system_prompt=effective.system_prompt,
                history=tuple(dict(item) for item in kept),
                current_user_input=row.get("input"),
                summary_message=summary_message if effective.summary_enabled else None,
                customer_memory=customer_memory,
                engine_context=dict(engine_context or {}),
            )
        except ValidationError as exc:
            # The DTO is strict, and pydantic's default text quotes what it
            # rejected — prompt, conversation, or rendered Memory content. This
            # step sits on the run path, so it hands on the field name only and
            # drops the cause chain with it (H-6).
            raise instruction_contract_error("instruction_prepare", _rejected_field(exc)) from None

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
            network_policy=self.network_policy,
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
