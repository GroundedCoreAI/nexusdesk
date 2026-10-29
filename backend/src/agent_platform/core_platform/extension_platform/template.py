"""Small starter template for new capability packages."""

from agent_platform.extension_contracts import CapabilityManifest

from .manifest import dump_capability_manifest


def capability_manifest_template(
    capability_id: str = "example-capability",
    name: str = "Example Capability",
) -> str:
    """Return a valid manifest developers can copy into a plugin package."""

    manifest = CapabilityManifest(
        id=capability_id,
        version="0.1.0",
        name=name,
        description="Replace this description with the capability boundary.",
        configuration_schema_version="v1",
        contributions=frozenset({"tools", "events"}),
        enabled_by_default=False,
    )
    return dump_capability_manifest(manifest)
