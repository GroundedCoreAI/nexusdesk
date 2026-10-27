import ast
import re
from pathlib import Path

from agent_platform.applications.customer_service.platform_services import PlatformServices
from agent_platform.applications.customer_service.service_groups import (
    build_runtime_bindings,
    build_service_groups,
)
from agent_platform.extension_contracts import RuntimeBindings


def test_agent_runtime_does_not_import_application_composition():
    root = (
        Path(__file__).parents[1]
        / "src"
        / "agent_platform"
        / "core_platform"
        / "agent_runtime"
    )
    offenders: list[str] = []

    for source_file in root.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            if any(name.startswith("agent_platform.applications") for name in names):
                offenders.append(str(source_file.relative_to(root)))

    assert offenders == []


def test_platform_services_does_not_own_runtime_implementation():
    source = (
        Path(__file__).parents[1]
        / "src"
        / "agent_platform"
        / "applications"
        / "customer_service"
        / "platform_services.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(
        name.startswith(
            (
                "agent_platform.core_platform.agent_runtime",
                "agent_platform.core_platform.platform_services.integrations.business_tools",
            )
        )
        for name in imported_modules
    )


def test_business_tool_adapter_does_not_write_tool_ledger_sql():
    source = (
        Path(__file__).parents[1]
        / "src"
        / "agent_platform"
        / "core_platform"
        / "platform_services"
        / "integrations"
        / "business_tools"
        / "platform_tools.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    direct_ledger_writes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if node.module == "agent_platform.core_platform.platform_services.persistence.store":
            direct_ledger_writes.extend(alias.name for alias in node.names)

    assert "execute" not in direct_ledger_writes


def test_platform_tool_adapter_does_not_dispatch_business_domains():
    source = (
        Path(__file__).parents[1]
        / "src"
        / "agent_platform"
        / "core_platform"
        / "platform_services"
        / "integrations"
        / "business_tools"
        / "platform_tools.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(
        name.startswith(
            (
                "agent_platform.business_capabilities.approval",
                "agent_platform.business_capabilities.customer_service",
                "agent_platform.business_capabilities.knowledge",
                "agent_platform.business_capabilities.memory",
            )
        )
        for name in imported_modules
    )


def test_platform_services_exposes_explicit_service_groups_and_runtime_ports():
    platform = object.__new__(PlatformServices)
    values = {
        "engine": object(),
        "settings": object(),
        "snapshot": {"fingerprint": "test"},
        "gateway": object(),
        "event_bus": object(),
        "approval": object(),
        "ui_extensions": object(),
        "tools": object(),
        "tool_workspace": object(),
        "policy": object(),
        "ledger": object(),
        "replay": object(),
        "tool_contributions": (),
        "agents": object(),
        "knowledge": object(),
        "ingestion": object(),
        "vector_index": object(),
        "knowledge_workspace": object(),
        "retrieval": object(),
        "memory": object(),
        "memory_store": object(),
        "conversations": object(),
        "handoffs": object(),
        "customer": object(),
        "confirmation": object(),
        "channels": object(),
        "staff": object(),
        "members": object(),
        "observability": object(),
        "open_platform": object(),
        "evaluation": object(),
    }
    for name, value in values.items():
        setattr(platform, name, value)

    groups = build_service_groups(platform)
    assert groups.runtime.gateway is values["gateway"]
    assert groups.runtime.ui_extensions is values["ui_extensions"]
    assert groups.tools.policy is values["policy"]
    assert groups.business.customer is values["customer"]
    assert groups.business.approval is values["approval"]
    assert groups.application.open_platform is values["open_platform"]

    bindings = build_runtime_bindings(groups)
    assert isinstance(bindings, RuntimeBindings)
    assert bindings.tools is values["tools"]
    assert bindings.customer is values["customer"]
    assert bindings.replay is values["replay"]
    assert bindings.tool_contributions == ()
    assert bindings.tool_contributions == ()


def test_runtime_composition_uses_explicit_runtime_bindings():
    source = (
        Path(__file__).parents[1]
        / "src"
        / "agent_platform"
        / "applications"
        / "customer_service"
        / "runtime_composition.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "from_legacy"
        for node in ast.walk(tree)
    )


def test_migrated_routes_use_service_groups_instead_of_aggregate_attributes():
    root = Path(__file__).parents[1] / "src" / "agent_platform"
    route_files = [
        root / "applications" / "customer_service" / "platform_routes.py",
        root / "core_platform" / "platform_services" / "access_control" / "routes.py",
        root / "business_capabilities" / "knowledge" / "routes.py",
        root / "business_capabilities" / "memory" / "routes.py",
        root / "core_platform" / "platform_services" / "model_gateway" / "routes.py",
        root
        / "core_platform"
        / "platform_services"
        / "model_gateway"
        / "management_routes.py",
        root / "business_capabilities" / "open_platform" / "routes.py",
        root / "core_platform" / "tool_gateway" / "routes.py",
        root / "core_platform" / "platform_services" / "identity" / "access.py",
        root / "core_platform" / "platform_services" / "identity" / "local_routes.py",
    ]
    legacy_access = re.compile(r"runtime\.platform\.")
    offenders = [
        str(path.relative_to(root))
        for path in route_files
        if legacy_access.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_confirmation_route_uses_the_runtime_confirmation_port():
    source = (
        Path(__file__).parents[1]
        / "src"
        / "agent_platform"
        / "applications"
        / "customer_service"
        / "platform_routes.py"
    ).read_text(encoding="utf-8")
    assert "business(request).confirmation.decide" in source
    assert "business(request).customer.decide" not in source
