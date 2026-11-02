"""Compilation of industry-pack templates into existing runtime contracts.

The compiler only validates structure and performs deterministic data
conversion.  Runtime code must not inspect ``config.industry_pack.pack_key``
to choose an industry-specific behavior; that metadata exists for lineage,
audit, upgrade and display purposes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from ..scenarios.models import ObjectMode, ScenarioConfig
from ..service_apps.models import (
    ApplicationChannel,
    ApplicationScenarioReference,
    ApplicationServiceCategory,
    ServiceApplicationConfig,
)
from .models import (
    KEY_PATTERN,
    SEMVER_PATTERN,
    AcceptanceCase,
    IndustryPackManifest,
    ObjectTemplate,
    PackSample,
    ScenarioTemplate,
)


class IndustryPackCompileError(ValueError):
    """A pack is structurally valid JSON but cannot be compiled safely."""


class CompiledApplicationBlueprint(BaseModel):
    """Compiled application config plus pack lineage kept outside runtime data."""

    model_config = ConfigDict(extra="forbid")

    application_key: str
    application: ServiceApplicationConfig
    industry_pack: dict[str, Any]
    digest: str

    @property
    def config(self) -> ServiceApplicationConfig:
        """Expose the existing application config under a short alias."""

        return self.application

    @property
    def blueprint_digest(self) -> str:
        """Expose the deterministic blueprint digest under an explicit name."""

        return self.digest


def _json_compatible(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_compatible(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_compatible(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Return deterministic JSON used as the template digest input."""

    return json.dumps(
        _json_compatible(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def stable_digest(value: Any) -> str:
    """Return a stable, prefixed SHA-256 digest for a pack asset."""

    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _duplicate(values: Sequence[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


_DEFAULT_CHANNEL_NAMES = {
    "web": "官网帮助中心",
    "app": "移动应用",
    "wechat": "微信服务",
    "h5": "H5 服务页",
    "api": "开放平台 API",
}


class IndustryPackCompiler:
    """Validates a manifest and compiles templates into existing configs."""

    def __init__(self, manifest: IndustryPackManifest):
        self.manifest = manifest
        self.validate()

    @property
    def digest(self) -> str:
        """Digest of the complete manifest, useful for installation audit."""

        return stable_digest(self.manifest)

    def validate(self) -> IndustryPackManifest:
        """Validate keys, versions and all pack-internal references."""

        manifest = self.manifest
        if not isinstance(manifest, IndustryPackManifest):
            raise IndustryPackCompileError("manifest must be an IndustryPackManifest")
        self._validate_identifier(manifest.pack_key, "pack_key")
        self._validate_version(manifest.pack_version, "pack_version")

        category_keys = [item.key for item in manifest.catalog_categories]
        duplicate = _duplicate(category_keys)
        if duplicate is not None:
            raise IndustryPackCompileError(f"duplicate catalog category key: {duplicate}")
        category_keys_set = set(category_keys)

        object_keys = [item.object_template_key for item in manifest.object_templates]
        duplicate = _duplicate(object_keys)
        if duplicate is not None:
            raise IndustryPackCompileError(f"duplicate object template key: {duplicate}")
        object_keys_set = set(object_keys)

        scenario_keys = [item.template_key for item in manifest.scenario_templates]
        duplicate = _duplicate(scenario_keys)
        if duplicate is not None:
            raise IndustryPackCompileError(f"duplicate scenario template key: {duplicate}")
        scenario_keys_set = set(scenario_keys)

        supported_channels = set(manifest.supported_channels)
        for template in manifest.scenario_templates:
            self._validate_identifier(template.template_key, "template_key")
            self._validate_version(template.template_version, "template_version")
            if (
                template.catalog_category_key is not None
                and template.catalog_category_key not in category_keys_set
            ):
                raise IndustryPackCompileError(
                    "scenario template "
                    f"'{template.template_key}' references unknown catalog category: "
                    f"{template.catalog_category_key}"
                )
            if (
                template.object_template_key is not None
                and template.object_template_key not in object_keys_set
            ):
                raise IndustryPackCompileError(
                    "scenario template "
                    f"'{template.template_key}' references unknown object template: "
                    f"{template.object_template_key}"
                )
            unsupported_channels = [
                channel for channel in template.channels if channel not in supported_channels
            ]
            if unsupported_channels:
                raise IndustryPackCompileError(
                    f"scenario template '{template.template_key}' uses unsupported channels: "
                    f"{', '.join(unsupported_channels)}"
                )

        blueprint = manifest.application_blueprint
        if blueprint is not None:
            duplicate = _duplicate(blueprint.catalog_category_keys)
            if duplicate is not None:
                raise IndustryPackCompileError(
                    f"duplicate application blueprint catalog category: {duplicate}"
                )
            duplicate = _duplicate(blueprint.scenario_template_keys)
            if duplicate is not None:
                raise IndustryPackCompileError(
                    f"duplicate application blueprint scenario template: {duplicate}"
                )
            unknown_category = next(
                (key for key in blueprint.catalog_category_keys if key not in category_keys_set),
                None,
            )
            if unknown_category is not None:
                raise IndustryPackCompileError(
                    f"application blueprint references unknown catalog category: {unknown_category}"
                )
            unknown_scenario = next(
                (key for key in blueprint.scenario_template_keys if key not in scenario_keys_set),
                None,
            )
            if unknown_scenario is not None:
                raise IndustryPackCompileError(
                    "application blueprint references unknown scenario template: "
                    f"{unknown_scenario}"
                )
            pin_keys = set(blueprint.scenario_template_versions)
            unknown_pin = next(
                (key for key in pin_keys if key not in scenario_keys_set),
                None,
            )
            if unknown_pin is not None:
                raise IndustryPackCompileError(
                    "application blueprint references unknown scenario template version: "
                    f"{unknown_pin}"
                )
            unreferenced_pin = next(
                (key for key in pin_keys if key not in blueprint.scenario_template_keys),
                None,
            )
            if unreferenced_pin is not None:
                raise IndustryPackCompileError(
                    "application blueprint pins a scenario template that is not included: "
                    f"{unreferenced_pin}"
                )
            version_by_scenario = {
                template.template_key: template.template_version
                for template in manifest.scenario_templates
            }
            for template_key, pinned_version in blueprint.scenario_template_versions.items():
                actual_version = version_by_scenario[template_key]
                if pinned_version != actual_version:
                    raise IndustryPackCompileError(
                        "version mismatch for scenario template "
                        f"'{template_key}': blueprint expects {pinned_version}, "
                        f"pack provides {actual_version}"
                    )
            unsupported_blueprint_channels = [
                channel.key
                for channel in blueprint.channels
                if channel.key not in supported_channels
            ]
            if unsupported_blueprint_channels:
                raise IndustryPackCompileError(
                    "application blueprint uses unsupported channels: "
                    f"{', '.join(unsupported_blueprint_channels)}"
                )

        sample_ids = [sample.sample_id for sample in manifest.sample_data]
        duplicate = _duplicate(sample_ids)
        if duplicate is not None:
            raise IndustryPackCompileError(f"duplicate sample id: {duplicate}")
        acceptance_ids = [case.case_id for case in manifest.acceptance_cases]
        duplicate = _duplicate(acceptance_ids)
        if duplicate is not None:
            raise IndustryPackCompileError(f"duplicate acceptance case id: {duplicate}")

        sample_id_set = set(sample_ids)
        acceptance_id_set = set(acceptance_ids)
        for object_template in manifest.object_templates:
            unknown_sample = next(
                (
                    sample_id
                    for sample_id in object_template.sample_refs
                    if sample_id not in sample_id_set
                ),
                None,
            )
            if unknown_sample is not None:
                raise IndustryPackCompileError(
                    f"object template '{object_template.object_template_key}' references "
                    f"unknown sample: {unknown_sample}"
                )
        for template in manifest.scenario_templates:
            unknown_sample = next(
                (sample_id for sample_id in template.sample_refs if sample_id not in sample_id_set),
                None,
            )
            if unknown_sample is not None:
                raise IndustryPackCompileError(
                    f"scenario template '{template.template_key}' references "
                    f"unknown sample: {unknown_sample}"
                )
            unknown_acceptance = next(
                (
                    case_id
                    for case_id in template.acceptance_case_refs
                    if case_id not in acceptance_id_set
                ),
                None,
            )
            if unknown_acceptance is not None:
                raise IndustryPackCompileError(
                    f"scenario template '{template.template_key}' references "
                    f"unknown acceptance case: {unknown_acceptance}"
                )

        self._validate_samples_and_acceptance_cases()
        return manifest

    def get_scenario_template(self, template_key: str) -> ScenarioTemplate:
        """Resolve one scenario template or raise a precise compile error."""

        self.validate()
        template = next(
            (
                item
                for item in self.manifest.scenario_templates
                if item.template_key == template_key
            ),
            None,
        )
        if template is None:
            raise IndustryPackCompileError(f"scenario template not found: {template_key}")
        return template

    def digest_scenario_template(self, template: ScenarioTemplate | str) -> str:
        """Return the digest of a template model or template key."""

        resolved = self.get_scenario_template(template) if isinstance(template, str) else template
        return stable_digest(resolved)

    def compile_scenario(self, template_key: str) -> ScenarioConfig:
        """Compile one scenario template into the existing ScenarioConfig."""

        template = self.get_scenario_template(template_key)
        return self._compile_scenario_internal(template)

    def _compile_scenario_internal(self, template: ScenarioTemplate) -> ScenarioConfig:
        """Compile a template whose pack-internal references are already validated."""

        template_key = template.template_key
        body = deepcopy(template.config)
        if not isinstance(body, dict):
            raise IndustryPackCompileError(
                f"scenario template '{template_key}' config must be an object"
            )

        object_template = self._resolve_object_template(template)
        if object_template is not None:
            self._apply_object_template(body, object_template, template_key)

        body["name"] = template.name
        body["description"] = template.description
        body.setdefault("domain", self.manifest.name)
        body["template"] = template.execution_template.value
        if template.channels:
            body["channels"] = list(template.channels)

        if template.catalog_category_key is not None:
            category = next(
                item
                for item in self.manifest.catalog_categories
                if item.key == template.catalog_category_key
            )
            body["category"] = category.name

        source_config = body.get("config", {})
        if source_config is None:
            source_config = {}
        if not isinstance(source_config, dict):
            raise IndustryPackCompileError(
                f"scenario template '{template_key}' config.config must be an object"
            )
        if "industry_pack" in source_config:
            raise IndustryPackCompileError(
                f"scenario template '{template_key}' must not define reserved "
                "config.industry_pack metadata"
            )
        metadata: dict[str, Any] = {
            "pack_key": self.manifest.pack_key,
            "pack_version": self.manifest.pack_version,
            "template_key": template.template_key,
            "template_version": template.template_version,
            "template_digest": self.digest_scenario_template(template),
            "scenario_kind": template.scenario_kind.value,
            "maturity": template.maturity.value,
        }
        if template.catalog_category_key is not None:
            metadata["catalog_category_key"] = template.catalog_category_key
        body["config"] = {**source_config, "industry_pack": metadata}

        try:
            return ScenarioConfig.model_validate(body)
        except ValidationError as exc:
            raise IndustryPackCompileError(
                f"scenario template '{template_key}' produced an invalid ScenarioConfig: {exc}"
            ) from exc

    def compile(self, template_key: str) -> ScenarioConfig:
        """Alias for :meth:`compile_scenario`."""

        return self.compile_scenario(template_key)

    def compile_all(self) -> list[ScenarioConfig]:
        """Compile every scenario template in manifest order."""

        self.validate()
        return [
            self._compile_scenario_internal(template)
            for template in self.manifest.scenario_templates
        ]

    def compile_application(self) -> CompiledApplicationBlueprint:
        """Compile the optional application blueprint into the existing app contract."""

        self.validate()
        blueprint = self.manifest.application_blueprint
        if blueprint is None:
            raise IndustryPackCompileError("application blueprint not found")

        application_key = blueprint.application_key or f"{self.manifest.pack_key}-service"
        self._validate_identifier(application_key, "application_key")

        categories_by_key = {
            category.key: category for category in self.manifest.catalog_categories
        }
        selected_category_keys = blueprint.catalog_category_keys or list(categories_by_key)
        service_categories = [
            ApplicationServiceCategory(
                name=categories_by_key[key].name,
                order=categories_by_key[key].order,
            )
            for key in selected_category_keys
        ]

        templates_by_key = {
            template.template_key: template for template in self.manifest.scenario_templates
        }
        scenario_refs = [
            ApplicationScenarioReference(
                key=template_key,
                version=None,
                enabled=True,
            )
            for template_key in blueprint.scenario_template_keys
        ]

        channels = (
            [deepcopy(channel) for channel in blueprint.channels]
            if blueprint.channels
            else self._default_application_channels()
        )
        capabilities = [deepcopy(capability) for capability in blueprint.capabilities]
        if any(
            handler.enabled and handler.type.value == "human"
            for template_key in blueprint.scenario_template_keys
            for handler in self._compile_scenario_internal(templates_by_key[template_key]).handlers
        ) and not any(
            capability.enabled and capability.type.value == "human" for capability in capabilities
        ):
            raise IndustryPackCompileError(
                "application blueprint must declare an enabled human capability "
                "for scenarios with human handlers"
            )

        application_payload: dict[str, Any] = {
            "schema_version": "v1",
            "name": blueprint.name,
            "description": blueprint.description,
            "service_categories": [
                category.model_dump(mode="json") for category in service_categories
            ],
            "scenarios": [scenario.model_dump(mode="json") for scenario in scenario_refs],
            "capabilities": [capability.model_dump(mode="json") for capability in capabilities],
            "default_execution_order": list(blueprint.default_execution_order),
            "channels": [channel.model_dump(mode="json") for channel in channels],
        }
        try:
            application = ServiceApplicationConfig.model_validate(application_payload)
        except ValidationError as exc:
            raise IndustryPackCompileError(
                f"application blueprint produced an invalid ServiceApplicationConfig: {exc}"
            ) from exc

        referenced_templates = [templates_by_key[key] for key in blueprint.scenario_template_keys]
        industry_pack = {
            "pack_key": self.manifest.pack_key,
            "pack_version": self.manifest.pack_version,
            "maturity": self.manifest.maturity.value,
            "application_key": application_key,
            "blueprint_digest": stable_digest(blueprint),
            "scenario_template_versions": {
                template.template_key: template.template_version
                for template in referenced_templates
            },
            "scenario_template_digests": {
                template.template_key: self.digest_scenario_template(template)
                for template in referenced_templates
            },
        }
        digest = stable_digest(
            {
                "application_key": application_key,
                "application": application,
                "industry_pack": industry_pack,
            }
        )
        return CompiledApplicationBlueprint(
            application_key=application_key,
            application=application,
            industry_pack=industry_pack,
            digest=digest,
        )

    def compile_application_config(self) -> ServiceApplicationConfig:
        """Return only the existing application config, without pack lineage."""

        return self.compile_application().application

    def compile_application_dict(self) -> dict[str, Any]:
        """Return the compiled application and lineage as a JSON-compatible dict."""

        return self.compile_application().model_dump(mode="json")

    def _default_application_channels(self) -> list[ApplicationChannel]:
        return [
            ApplicationChannel(
                key=channel,
                name=_DEFAULT_CHANNEL_NAMES.get(channel, channel),
                type=channel,
            )
            for channel in self.manifest.supported_channels
        ]

    def _validate_samples_and_acceptance_cases(self) -> None:
        templates_by_key = {
            template.template_key: template for template in self.manifest.scenario_templates
        }
        compiled_by_key: dict[str, ScenarioConfig] = {}

        for sample in self.manifest.sample_data:
            template = templates_by_key.get(sample.scenario_template_key)
            if template is None:
                raise IndustryPackCompileError(
                    f"sample '{sample.sample_id}' references unknown scenario template: "
                    f"{sample.scenario_template_key}"
                )
            config = compiled_by_key.get(template.template_key)
            if config is None:
                config = self._compile_scenario_internal(template)
                compiled_by_key[template.template_key] = config
            self._validate_sample(sample, config)

        for case in self.manifest.acceptance_cases:
            template = templates_by_key.get(case.scenario_template_key)
            if template is None:
                raise IndustryPackCompileError(
                    f"acceptance case '{case.case_id}' references unknown scenario template: "
                    f"{case.scenario_template_key}"
                )
            config = compiled_by_key.get(template.template_key)
            if config is None:
                config = self._compile_scenario_internal(template)
                compiled_by_key[template.template_key] = config
            self._validate_acceptance_case(case, config)

    @staticmethod
    def _fact_references(config: ScenarioConfig) -> set[str]:
        return {value for fact in config.facts for value in (fact.key, fact.source)}

    @classmethod
    def _sample_fact_references(cls, config: ScenarioConfig) -> set[str]:
        return {
            *cls._fact_references(config),
            *(fact.source.split(".", 1)[0] for fact in config.facts),
        }

    def _validate_sample(self, sample: PackSample, config: ScenarioConfig) -> None:
        if sample.object is not None:
            if config.object is None or config.object.mode == ObjectMode.NONE:
                raise IndustryPackCompileError(
                    f"sample '{sample.sample_id}' supplies an object to a scenario "
                    "that does not use one"
                )
            if sample.object.type != config.object.type:
                raise IndustryPackCompileError(
                    f"sample '{sample.sample_id}' object type mismatch: expected "
                    f"{config.object.type}, found {sample.object.type}"
                )
            unknown_facts = sorted(set(sample.object.facts) - self._sample_fact_references(config))
            if unknown_facts:
                raise IndustryPackCompileError(
                    f"sample '{sample.sample_id}' references unknown fact fields: "
                    f"{', '.join(unknown_facts)}"
                )

        decision_keys = {decision.key for decision in config.decisions}
        if sample.selected_decision is not None and sample.selected_decision not in decision_keys:
            raise IndustryPackCompileError(
                f"sample '{sample.sample_id}' references unknown decision: "
                f"{sample.selected_decision}"
            )
        handler_keys = {handler.key for handler in config.handlers if handler.enabled}
        if sample.selected_handler is not None and sample.selected_handler not in handler_keys:
            raise IndustryPackCompileError(
                f"sample '{sample.sample_id}' references unknown handler: {sample.selected_handler}"
            )

    def _validate_acceptance_case(
        self,
        case: AcceptanceCase,
        config: ScenarioConfig,
    ) -> None:
        unknown_facts = sorted(set(case.then.must_include_facts) - self._fact_references(config))
        if unknown_facts:
            raise IndustryPackCompileError(
                f"acceptance case '{case.case_id}' references unknown fact fields: "
                f"{', '.join(unknown_facts)}"
            )
        if case.then.handler_type is not None and not any(
            handler.enabled and handler.type == case.then.handler_type
            for handler in config.handlers
        ):
            raise IndustryPackCompileError(
                f"acceptance case '{case.case_id}' references unavailable handler type: "
                f"{case.then.handler_type.value}"
            )

    def _resolve_object_template(
        self,
        template: ScenarioTemplate,
    ) -> ObjectTemplate | None:
        if template.object_template_key is None:
            return None
        object_template = next(
            (
                item
                for item in self.manifest.object_templates
                if item.object_template_key == template.object_template_key
            ),
            None,
        )
        if object_template is None:
            raise IndustryPackCompileError(
                f"scenario template '{template.template_key}' references unknown "
                f"object template: {template.object_template_key}"
            )
        return object_template

    def _apply_object_template(
        self,
        body: dict[str, Any],
        object_template: ObjectTemplate,
        template_key: str,
    ) -> None:
        required = object_template.default_mode in (
            ObjectMode.REQUIRED,
            ObjectMode.MULTIPLE,
        )
        compiled_object: dict[str, Any] = {
            "type": object_template.object_type,
            "provider": object_template.provider_key,
            "required": required,
            "mode": object_template.default_mode.value,
            "candidate_strategy": object_template.candidate_strategy.model_dump(mode="json"),
            "permission_policy": object_template.permission_scope,
            "config": deepcopy(object_template.config),
        }

        scenario_object = body.get("object")
        if scenario_object is not None:
            if not isinstance(scenario_object, dict):
                raise IndustryPackCompileError(
                    f"scenario template '{template_key}' object override must be an object"
                )
            for field in ("type", "provider", "mode", "required"):
                if field in scenario_object and scenario_object[field] != compiled_object[field]:
                    raise IndustryPackCompileError(
                        f"scenario template '{template_key}' object override changes "
                        f"protected field: {field}"
                    )
            compiled_object = {**compiled_object, **scenario_object}
        body["object"] = compiled_object

        template_facts = {
            field.key: field.model_dump(mode="json") for field in object_template.fact_fields
        }
        scenario_facts = body.get("facts", [])
        if scenario_facts is None:
            scenario_facts = []
        if not isinstance(scenario_facts, list):
            raise IndustryPackCompileError(
                f"scenario template '{template_key}' facts must be an array"
            )
        for fact in scenario_facts:
            if not isinstance(fact, dict) or not isinstance(fact.get("key"), str):
                raise IndustryPackCompileError(
                    f"scenario template '{template_key}' facts require a string key"
                )
            template_facts[fact["key"]] = fact

        sensitive_fields = set(object_template.sensitive_fields)
        for key, fact in template_facts.items():
            if key in sensitive_fields or fact.get("source") in sensitive_fields:
                fact["masked"] = True
        body["facts"] = list(template_facts.values())

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not isinstance(value, str) or re.fullmatch(KEY_PATTERN, value) is None:
            raise IndustryPackCompileError(f"invalid {label}: {value!r}")

    @staticmethod
    def _validate_version(value: str, label: str) -> None:
        if not isinstance(value, str) or re.fullmatch(SEMVER_PATTERN, value) is None:
            raise IndustryPackCompileError(f"invalid {label}: {value!r}")


def compile_scenario_template(
    manifest: IndustryPackManifest,
    template_key: str,
) -> ScenarioConfig:
    """Compile one scenario template from a manifest."""

    return IndustryPackCompiler(manifest).compile_scenario(template_key)


def compile_scenario(
    manifest: IndustryPackManifest,
    template_key: str,
) -> ScenarioConfig:
    """Short alias for :func:`compile_scenario_template`."""

    return compile_scenario_template(manifest, template_key)


__all__ = [
    "CompiledApplicationBlueprint",
    "IndustryPackCompileError",
    "IndustryPackCompiler",
    "canonical_json",
    "compile_scenario",
    "compile_scenario_template",
    "stable_digest",
]
