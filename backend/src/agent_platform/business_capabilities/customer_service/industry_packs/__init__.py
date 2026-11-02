"""Industry pack manifests and compilation contracts.

Industry packs are versioned content assets.  They are compiled into the
existing service-scenario and service-application contracts; they are not
runtime tenant entities and must not introduce industry-specific dispatch.
"""

from .compiler import (
    CompiledApplicationBlueprint,
    IndustryPackCompileError,
    IndustryPackCompiler,
    compile_scenario,
    compile_scenario_template,
    stable_digest,
)
from .content_community import CONTENT_COMMUNITY_PACK, build_content_community_pack
from .local_life import LOCAL_LIFE_PACK, build_local_life_pack
from .models import (
    AcceptanceCase,
    AcceptanceExpectation,
    ApplicationBlueprint,
    CatalogCategoryTemplate,
    IndustryPackManifest,
    IndustryPackMaturity,
    ObjectTemplate,
    PackSample,
    ScenarioKind,
    ScenarioTemplate,
)

__all__ = [
    "CONTENT_COMMUNITY_PACK",
    "LOCAL_LIFE_PACK",
    "AcceptanceCase",
    "AcceptanceExpectation",
    "ApplicationBlueprint",
    "CatalogCategoryTemplate",
    "CompiledApplicationBlueprint",
    "IndustryPackCompileError",
    "IndustryPackCompiler",
    "IndustryPackManifest",
    "IndustryPackMaturity",
    "ObjectTemplate",
    "PackSample",
    "ScenarioKind",
    "ScenarioTemplate",
    "build_content_community_pack",
    "build_local_life_pack",
    "compile_scenario",
    "compile_scenario_template",
    "stable_digest",
]
