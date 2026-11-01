"""Static architecture gates for the modular platform boundary."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
SOURCE_ROOT = BACKEND_ROOT / "src" / "agent_platform"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def check_no_imports(paths: list[Path], forbidden_prefixes: tuple[str, ...]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        offenders = sorted(
            module
            for module in imported_modules(path)
            if module.startswith(forbidden_prefixes)
        )
        if offenders:
            failures.append(f"{path.relative_to(REPO_ROOT)} imports {', '.join(offenders)}")
    return failures


def run() -> int:
    failures: list[str] = []

    required_roots = (
        "core_platform",
        "extension_contracts",
        "business_capabilities",
        "applications",
    )
    for name in required_roots:
        if not (SOURCE_ROOT / name).is_dir():
            failures.append(f"missing architecture root: {SOURCE_ROOT / name}")

    legacy_roots = (
        "modules",
        "apps",
        "integrations",
        "platform",
        "contracts",
        "extension_platform",
        "extensions",
    )
    for name in legacy_roots:
        if (SOURCE_ROOT / name).exists():
            failures.append(f"legacy runtime root still exists: {SOURCE_ROOT / name}")

    contract_files = list((SOURCE_ROOT / "extension_contracts").glob("*.py"))
    failures.extend(
        check_no_imports(
            contract_files,
            (
                "agent_platform.applications",
                "agent_platform.business_capabilities",
                "agent_platform.core_platform.platform_services.integrations",
            ),
        )
    )

    extension_files = list((SOURCE_ROOT / "core_platform" / "extension_platform").glob("*.py"))
    failures.extend(
        check_no_imports(
            extension_files,
            (
                "agent_platform.applications",
                "agent_platform.business_capabilities",
                "agent_platform.core_platform.platform_services.integrations",
            ),
        )
    )

    # The whole Core Platform must stay free of business and application imports.
    # Checking a hand-picked list of files let a transitive default slip through:
    # business_tools/defaults.py imported four capabilities while the gate only
    # looked at platform_tools.py next to it, so the tree is scanned as a whole.
    core_files = sorted((SOURCE_ROOT / "core_platform").rglob("*.py"))
    failures.extend(
        check_no_imports(
            core_files,
            (
                "agent_platform.applications",
                "agent_platform.business_capabilities",
            ),
        )
    )
    failures.extend(
        check_no_imports(
            [SOURCE_ROOT / "applications" / "platform_runtime" / "platform_services.py"],
            (
                "agent_platform.core_platform.agent_runtime",
                "agent_platform.core_platform.platform_services.integrations.business_tools",
            ),
        )
    )

    forbidden_template_tokens = (
        "entrypoint",
        "importlib",
        "__import__",
        "dynamic python loading",
    )
    template_root = BACKEND_ROOT / "templates"
    if template_root.exists():
        for path in sorted(template_root.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8").lower()
            except UnicodeDecodeError:
                failures.append(f"{path.relative_to(REPO_ROOT)} is not UTF-8 text")
                continue
            for token in forbidden_template_tokens:
                if token in text:
                    failures.append(
                        f"{path.relative_to(REPO_ROOT)} contains forbidden plugin-loading token: "
                        f"{token}"
                    )

    if failures:
        print("architecture gate failed:")
        print("\n".join(f" - {failure}" for failure in failures))
        return 1
    print("architecture gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
