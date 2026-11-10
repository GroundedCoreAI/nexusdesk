"""Industry pack manifests and compilation contracts.

Industry packs are versioned content assets.  They are compiled into the
existing service-scenario and service-application contracts; they are not
runtime tenant entities and must not introduce industry-specific dispatch.

Four demo packs ship by default (shopping / gaming / creator / mobility).  They
share one skeleton from :mod:`demo_kit`: three common catalog categories plus a
business-specific one, six fixed capabilities, four channels and GA-only
scenarios, so a freshly installed pack can pass the release gate as-is.
"""

from .compiler import (
    CompiledApplicationBlueprint,
    IndustryPackCompileError,
    IndustryPackCompiler,
    compile_scenario,
    compile_scenario_template,
    stable_digest,
)
from .creator import CREATOR_PACK, build_creator_pack
from .gaming import GAMING_PACK, build_gaming_pack
from .mobility import MOBILITY_PACK, build_mobility_pack
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
from .shopping import SHOPPING_PACK, build_shopping_pack

__all__ = [
    "CREATOR_PACK",
    "GAMING_PACK",
    "MOBILITY_PACK",
    "SHOPPING_PACK",
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
    "build_creator_pack",
    "build_gaming_pack",
    "build_mobility_pack",
    "build_shopping_pack",
    "compile_scenario",
    "compile_scenario_template",
    "stable_digest",
]
