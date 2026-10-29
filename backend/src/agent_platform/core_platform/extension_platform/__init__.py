"""In-process extension platform for built-in capabilities."""

from .bindings import (
    CapabilityBindingError,
    CapabilityContributionFactory,
    CapabilityImplementationRegistry,
    CapabilityLifecycleFactory,
)
from .builtins import (
    APPROVAL_UI_MANIFEST,
    BUILTIN_CAPABILITY_MANIFESTS,
    CUSTOMER_SERVICE_UI_MANIFEST,
    KNOWLEDGE_UI_MANIFEST,
    register_builtin_capabilities,
    register_builtin_ui_extensions,
)
from .compatibility import PLATFORM_VERSION, SemanticVersion, version_satisfies
from .config_service import CapabilityConfigService
from .contributions import (
    CapabilityContributionBundle,
    CapabilityContributionError,
    CapabilityContributionRegistry,
    EventSubscription,
)
from .discovery import (
    MANIFEST_SUFFIXES,
    ManifestCandidate,
    ManifestDiscoveryStatus,
    PluginDiscoveryResult,
    discover_manifest_directory,
)
from .manifest import ManifestValidationError, dump_capability_manifest, load_capability_manifest
from .registry import CapabilityRegistry, ExtensionRegistryError
from .state_service import CapabilityRuntimeStateService
from .template import capability_manifest_template
from .ui_registry import UiExtensionRegistry, UiExtensionRegistryError

__all__ = [
    "APPROVAL_UI_MANIFEST",
    "BUILTIN_CAPABILITY_MANIFESTS",
    "CUSTOMER_SERVICE_UI_MANIFEST",
    "KNOWLEDGE_UI_MANIFEST",
    "MANIFEST_SUFFIXES",
    "PLATFORM_VERSION",
    "CapabilityBindingError",
    "CapabilityConfigService",
    "CapabilityContributionBundle",
    "CapabilityContributionError",
    "CapabilityContributionFactory",
    "CapabilityContributionRegistry",
    "CapabilityImplementationRegistry",
    "CapabilityLifecycleFactory",
    "CapabilityRegistry",
    "CapabilityRuntimeStateService",
    "EventSubscription",
    "ExtensionRegistryError",
    "ManifestCandidate",
    "ManifestDiscoveryStatus",
    "ManifestValidationError",
    "PluginDiscoveryResult",
    "SemanticVersion",
    "UiExtensionRegistry",
    "UiExtensionRegistryError",
    "capability_manifest_template",
    "discover_manifest_directory",
    "dump_capability_manifest",
    "load_capability_manifest",
    "register_builtin_capabilities",
    "register_builtin_ui_extensions",
    "version_satisfies",
]
