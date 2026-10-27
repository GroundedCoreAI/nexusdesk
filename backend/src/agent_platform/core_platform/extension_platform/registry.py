"""In-process capability registry for the extension platform."""

import asyncio
import inspect
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_platform.extension_contracts import (
    CapabilityConfigVersion,
    CapabilityLifecycle,
    CapabilityManifest,
    CapabilityStatus,
    CapabilityStatusView,
)

from .bindings import CapabilityImplementationRegistry, CapabilityLifecycleFactory
from .compatibility import PLATFORM_VERSION, SemanticVersion, version_satisfies
from .discovery import ManifestCandidate, PluginDiscoveryResult, _scan_manifest_directory


class ExtensionRegistryError(ValueError):
    """Raised when an extension cannot be registered or ordered."""


@dataclass
class _Entry:
    manifest: CapabilityManifest
    lifecycle: CapabilityLifecycle | None
    lifecycle_factory: CapabilityLifecycleFactory | None
    enabled: bool
    status: CapabilityStatus = "registered"
    reason: str | None = None
    lifecycle_started: bool = False
    last_started_at: datetime | None = None
    last_stopped_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_count: int = 0

    def view(self, config_version: int | None = None) -> CapabilityStatusView:
        return CapabilityStatusView(
            capability_id=self.manifest.id,
            version=self.manifest.version,
            enabled=self.enabled,
            config_version=config_version,
            status=self.status,
            reason=self.reason,
            last_started_at=self.last_started_at,
            last_stopped_at=self.last_stopped_at,
            last_failure_at=self.last_failure_at,
            failure_count=self.failure_count,
        )


@dataclass
class _Snapshot:
    """Runtime state retained for one-step capability rollback."""

    manifest: CapabilityManifest
    lifecycle: CapabilityLifecycle | None
    lifecycle_factory: CapabilityLifecycleFactory | None
    enabled: bool
    status: CapabilityStatus
    reason: str | None
    lifecycle_started: bool
    last_started_at: datetime | None
    last_stopped_at: datetime | None
    last_failure_at: datetime | None
    failure_count: int


class CapabilityRegistry:
    """Register and lifecycle-manage built-in capabilities in dependency order."""

    def __init__(
        self,
        supported_api_versions: tuple[str, ...] = ("v1",),
        platform_version: str = PLATFORM_VERSION,
        lifecycle_timeout_seconds: float = 30.0,
    ) -> None:
        if not supported_api_versions:
            raise ValueError("at least one supported API version is required")
        version_satisfies(platform_version, "*")
        if lifecycle_timeout_seconds <= 0:
            raise ValueError("lifecycle timeout must be positive")
        self._supported_api_versions = frozenset(supported_api_versions)
        self._platform_version = platform_version
        self._lifecycle_timeout_seconds = lifecycle_timeout_seconds
        self._entries: dict[str, _Entry] = {}
        self._history: dict[str, list[_Snapshot]] = {}
        self._configs: dict[str, list[CapabilityConfigVersion]] = {}

    def _view(self, entry: _Entry | None) -> CapabilityStatusView | None:
        if entry is None:
            return None
        history = self._configs.get(entry.manifest.id)
        return entry.view(history[-1].version if history else None)

    def register(
        self,
        manifest: CapabilityManifest,
        lifecycle: CapabilityLifecycle | None = None,
        *,
        lifecycle_factory: CapabilityLifecycleFactory | None = None,
    ) -> CapabilityStatusView:
        """Validate and register one capability without starting it."""

        if lifecycle is not None and lifecycle_factory is not None:
            raise ExtensionRegistryError(
                "capability lifecycle and lifecycle factory are mutually exclusive"
            )
        self._validate_manifest(manifest)
        if manifest.id in self._entries:
            raise ExtensionRegistryError(f"capability already registered: {manifest.id}")
        self._validate_dependencies(manifest)
        self._entries[manifest.id] = _Entry(
            manifest=manifest,
            lifecycle=lifecycle,
            lifecycle_factory=lifecycle_factory,
            enabled=manifest.enabled_by_default,
            status="registered" if manifest.enabled_by_default else "stopped",
        )
        return self._view(self._entries[manifest.id])

    def register_manifest_file(
        self,
        path: str | Path,
        lifecycle: CapabilityLifecycle | None = None,
    ) -> CapabilityStatusView:
        """Load, validate, and register an external manifest safely."""

        from .manifest import load_capability_manifest

        manifest = load_capability_manifest(
            path,
            supported_api_versions=tuple(sorted(self._supported_api_versions)),
            platform_version=self._platform_version,
        )
        return self.register(manifest, lifecycle)

    def register_manifest_directory(
        self,
        directory: str | Path,
        lifecycles: Mapping[str, CapabilityLifecycle] | None = None,
        implementation_registry: CapabilityImplementationRegistry | None = None,
        *,
        require_implementation: bool = False,
        require_contribution_binding: bool = False,
    ) -> tuple[PluginDiscoveryResult, ...]:
        """Discover and register external manifests without importing code.

        Lifecycle implementations are explicit, trusted application-side
        bindings. Manifest contents are never used to dynamically import or
        execute a Python entry point. Registration is dependency-aware and a
        broken candidate does not prevent independent candidates from being
        registered. Factories are retained and invoked only when the
        capability is started.
        """

        if lifecycles is not None and implementation_registry is not None:
            raise ExtensionRegistryError(
                "lifecycles and implementation_registry are mutually exclusive"
            )
        candidates, initial_results = _scan_manifest_directory(
            directory,
            supported_api_versions=tuple(sorted(self._supported_api_versions)),
            platform_version=self._platform_version,
        )
        if not candidates:
            return initial_results

        results_by_path = {result.path: result for result in initial_results}
        candidate_by_id: dict[str, list[ManifestCandidate]] = {}
        for candidate in candidates:
            candidate_by_id.setdefault(candidate.manifest.id, []).append(candidate)

        pending: list[ManifestCandidate] = []
        for capability_id, duplicates in candidate_by_id.items():
            if len(duplicates) > 1:
                for candidate in duplicates:
                    results_by_path[candidate.path] = PluginDiscoveryResult(
                        path=candidate.path,
                        capability_id=capability_id,
                        status="conflict",
                        error=f"duplicate capability id: {capability_id}",
                    )
            elif capability_id in self._entries:
                candidate = duplicates[0]
                results_by_path[candidate.path] = PluginDiscoveryResult(
                    path=candidate.path,
                    capability_id=capability_id,
                    status="conflict",
                    error=f"capability already registered: {capability_id}",
                )
            else:
                pending.append(duplicates[0])

        pending.sort(key=lambda candidate: candidate.path.name.casefold())
        candidate_ids = {candidate.manifest.id for candidate in pending}
        while pending:
            next_pending = []
            progress = False
            for candidate in pending:
                try:
                    lifecycle = (
                        (lifecycles or {}).get(candidate.manifest.id)
                        if lifecycles is not None
                        else None
                    )
                    lifecycle_factory = (
                        implementation_registry.factory(candidate.manifest.id)
                        if implementation_registry is not None
                        else None
                    )
                    if require_implementation and lifecycle_factory is None:
                        raise ExtensionRegistryError(
                            "trusted capability implementation is not bound: "
                            f"{candidate.manifest.id}"
                        )
                    if (
                        require_contribution_binding
                        and candidate.manifest.contributions
                        and (
                            implementation_registry is None
                            or implementation_registry.contribution_factory(candidate.manifest.id)
                            is None
                        )
                    ):
                        raise ExtensionRegistryError(
                            "trusted capability contribution binding is missing: "
                            f"{candidate.manifest.id}"
                        )
                    self.register(
                        candidate.manifest,
                        lifecycle,
                        lifecycle_factory=lifecycle_factory,
                    )
                except ExtensionRegistryError as exc:
                    if self._has_pending_dependency(candidate, candidate_ids):
                        next_pending.append(candidate)
                        continue
                    results_by_path[candidate.path] = PluginDiscoveryResult(
                        path=candidate.path,
                        capability_id=candidate.manifest.id,
                        status="rejected",
                        error=str(exc),
                    )
                    candidate_ids.discard(candidate.manifest.id)
                    progress = True
                    continue
                results_by_path[candidate.path] = PluginDiscoveryResult(
                    path=candidate.path,
                    capability_id=candidate.manifest.id,
                    status="registered",
                )
                candidate_ids.discard(candidate.manifest.id)
                progress = True
            if not next_pending:
                break
            if not progress:
                for candidate in next_pending:
                    results_by_path[candidate.path] = PluginDiscoveryResult(
                        path=candidate.path,
                        capability_id=candidate.manifest.id,
                        status="rejected",
                        error="unresolvable capability dependencies",
                    )
                break
            pending = next_pending

        return tuple(
            results_by_path[path]
            for path in sorted(
                results_by_path,
                key=lambda item: (item.name.casefold(), str(item)),
            )
        )

    def _has_pending_dependency(
        self,
        candidate: ManifestCandidate,
        pending_ids: set[str],
    ) -> bool:
        """Return whether a failed registration may succeed in a later pass."""

        message = ""
        try:
            self._validate_dependencies(candidate.manifest)
        except ExtensionRegistryError as exc:
            message = str(exc)
        return message.startswith("missing capability dependency:") and any(
            dependency in pending_ids for dependency in candidate.manifest.dependencies
        )

    async def enable(self, capability_id: str) -> CapabilityStatusView:
        """Enable a capability and start its dependency chain in order."""

        if capability_id not in self._entries:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        return await self._activate(capability_id)

    async def retry(self, capability_id: str) -> CapabilityStatusView:
        """Retry a failed enabled capability without changing its intent.

        ``enable`` is allowed to turn a stopped capability on.  Recovery is a
        separate operation so operators cannot accidentally resurrect a
        capability that was deliberately disabled.
        """

        entry = self._entries.get(capability_id)
        if entry is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        if not entry.enabled:
            raise ExtensionRegistryError(f"capability is disabled: {capability_id}")
        return await self._activate(capability_id)

    async def _activate(self, capability_id: str) -> CapabilityStatusView:
        """Enable an entry and start its dependency chain in order."""

        for dependency_id in self._ordered_ids():
            if dependency_id == capability_id or self._depends_on(capability_id, dependency_id):
                self._entries[dependency_id].enabled = True
                await self._start_entry(self._entries[dependency_id])
        return self._view(self._entries[capability_id])

    def rollback_manifest(self, capability_id: str) -> CapabilityManifest | None:
        """Return the manifest that a rollback would restore, without mutating state."""

        history = self._history.get(capability_id)
        return history[-1].manifest if history else None

    async def disable(self, capability_id: str) -> CapabilityStatusView:
        """Stop a capability when no enabled capability depends on it."""

        entry = self._entries.get(capability_id)
        if entry is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        dependents = [
            candidate.manifest.id
            for candidate in self._entries.values()
            if candidate.enabled and self._depends_on(candidate.manifest.id, capability_id)
        ]
        if dependents:
            raise ExtensionRegistryError(
                f"capability has enabled dependents: {capability_id}->{','.join(dependents)}"
            )
        if not await self._stop_entry(entry):
            raise ExtensionRegistryError(f"capability could not be stopped: {capability_id}")
        entry.enabled = False
        entry.status = "stopped"
        entry.reason = None
        return self._view(entry)

    async def upgrade(
        self,
        capability_id: str,
        manifest: CapabilityManifest,
        lifecycle: CapabilityLifecycle | None = None,
    ) -> CapabilityStatusView:
        """Replace a capability version, restoring the previous runtime on failure."""

        current = self._entries.get(capability_id)
        if current is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        if manifest.id != capability_id:
            raise ExtensionRegistryError("capability upgrade cannot change identity")
        self._validate_manifest(manifest)
        if SemanticVersion.parse(manifest.version) <= SemanticVersion.parse(
            current.manifest.version
        ):
            raise ExtensionRegistryError("capability upgrade must increase the version")
        self._validate_dependencies(manifest, replacing=capability_id)

        snapshot = self._snapshot(current)
        was_enabled = current.enabled
        if not await self._stop_entry(current):
            self._restore_entry(current, snapshot)
            raise ExtensionRegistryError(f"capability upgrade could not stop: {capability_id}")

        current.manifest = manifest
        # The HTTP management API only replaces declarative manifest metadata.
        # Keep the already-installed runtime hook when the caller does not
        # provide a replacement implementation.
        current.lifecycle = lifecycle if lifecycle is not None else snapshot.lifecycle
        current.lifecycle_factory = None if lifecycle is not None else snapshot.lifecycle_factory
        current.enabled = was_enabled
        current.status = "registered" if was_enabled else "stopped"
        current.reason = None
        current.lifecycle_started = False
        current.last_started_at = None
        current.last_stopped_at = snapshot.last_stopped_at
        current.last_failure_at = None
        current.failure_count = snapshot.failure_count

        if was_enabled and not await self._start_entry(current):
            await self._stop_entry(current)
            self._restore_entry(current, snapshot)
            if snapshot.enabled and snapshot.status == "ready":
                await self._start_entry(current)
            raise ExtensionRegistryError(f"capability upgrade failed to start: {capability_id}")

        self._history.setdefault(capability_id, []).append(snapshot)
        return self._view(current)

    async def rollback(self, capability_id: str) -> CapabilityStatusView:
        """Restore the most recent successfully upgraded capability version."""

        history = self._history.get(capability_id)
        if not history:
            raise ExtensionRegistryError(f"no capability rollback available: {capability_id}")
        current = self._entries.get(capability_id)
        if current is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        snapshot = history.pop()
        current_snapshot = self._snapshot(current)
        if not await self._stop_entry(current):
            history.append(snapshot)
            raise ExtensionRegistryError(f"capability rollback could not stop: {capability_id}")
        self._restore_entry(current, snapshot)
        if snapshot.enabled and snapshot.status == "ready" and not await self._start_entry(current):
            # Rollback is transactional from the caller's perspective. If
            # the previous version cannot start, put the currently running
            # version back and retain the rollback opportunity.
            self._restore_entry(current, current_snapshot)
            if current_snapshot.enabled and current_snapshot.status == "ready":
                await self._start_entry(current)
            history.append(snapshot)
            raise ExtensionRegistryError(f"capability rollback failed to start: {capability_id}")
        return self._view(current)

    def _validate_manifest(self, manifest: CapabilityManifest) -> None:
        if manifest.api_version not in self._supported_api_versions:
            raise ExtensionRegistryError(
                f"unsupported capability API version: {manifest.api_version}"
            )
        try:
            version_satisfies(manifest.version, "*")
            platform_compatible = version_satisfies(
                self._platform_version,
                manifest.requires_platform,
            )
        except ValueError as exc:
            raise ExtensionRegistryError(
                f"invalid version metadata for capability: {manifest.id}"
            ) from exc
        if not platform_compatible:
            raise ExtensionRegistryError(
                f"capability requires unsupported platform version: {manifest.id}"
            )

    def _validate_dependencies(
        self,
        manifest: CapabilityManifest,
        replacing: str | None = None,
    ) -> None:
        for dependency in manifest.dependencies:
            if dependency not in self._entries or dependency == replacing:
                raise ExtensionRegistryError(
                    f"missing capability dependency: {manifest.id}->{dependency}"
                )
        for dependency, requirement in manifest.dependency_constraints.items():
            try:
                compatible = version_satisfies(
                    self._entries[dependency].manifest.version,
                    requirement,
                )
            except ValueError as exc:
                raise ExtensionRegistryError(
                    f"invalid dependency version constraint: {manifest.id}->{dependency}"
                ) from exc
            if not compatible:
                raise ExtensionRegistryError(
                    f"incompatible capability dependency: {manifest.id}->{dependency}"
                )

    def get(self, capability_id: str) -> CapabilityStatusView | None:
        """Return a capability status without exposing its implementation."""

        entry = self._entries.get(capability_id)
        return self._view(entry) if entry else None

    def get_manifest(self, capability_id: str) -> CapabilityManifest | None:
        """Return declarative metadata for contribution validation."""

        entry = self._entries.get(capability_id)
        return entry.manifest if entry else None

    def load_runtime_state(
        self,
        capability_id: str,
        *,
        manifest_version: str,
        enabled: bool,
        failure_count: int = 0,
        reason: str | None = None,
        last_started_at: datetime | None = None,
        last_stopped_at: datetime | None = None,
        last_failure_at: datetime | None = None,
    ) -> None:
        """Hydrate durable operator state without restoring a stale failure state."""

        entry = self._entries.get(capability_id)
        if entry is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        if entry.manifest.version != manifest_version:
            raise ExtensionRegistryError(
                f"capability runtime state version mismatch: {capability_id}"
            )
        entry.enabled = enabled
        entry.status = "registered" if enabled else "stopped"
        entry.reason = reason if not enabled else None
        entry.failure_count = max(0, failure_count)
        entry.last_started_at = last_started_at
        entry.last_stopped_at = last_stopped_at
        entry.last_failure_at = last_failure_at

    def quarantine(self, capability_id: str, reason: str) -> CapabilityStatusView:
        """Keep a broken capability visible but prevent it from becoming active."""

        entry = self._entries.get(capability_id)
        if entry is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        entry.enabled = False
        entry.status = "degraded"
        entry.reason = reason[:200] or "capability_quarantined"
        entry.last_failure_at = datetime.now(UTC)
        entry.failure_count += 1
        return self._view(entry)

    def is_enabled(self, capability_id: str) -> bool:
        """Return whether a capability is ready to receive new work."""

        entry = self._entries.get(capability_id)
        return bool(entry and entry.enabled and entry.status == "ready")

    def permissions(self, capability_id: str) -> frozenset[str]:
        """Return the immutable permission declaration for one capability."""

        entry = self._entries.get(capability_id)
        return entry.manifest.permissions if entry else frozenset()

    def configure(
        self,
        capability_id: str,
        config: dict[str, object],
        created_by: str,
        schema_version: str = "v1",
        rollback_of: int | None = None,
    ) -> CapabilityConfigVersion:
        """Create and activate an immutable configuration snapshot."""

        self.validate_configuration(capability_id, config, created_by, schema_version)
        version = len(self._configs.get(capability_id, ())) + 1
        snapshot = CapabilityConfigVersion(
            capability_id=capability_id,
            version=version,
            schema_version=schema_version,
            config=deepcopy(config),
            created_by=created_by,
            created_at=datetime.now(UTC),
            rollback_of=rollback_of,
        )
        self._configs.setdefault(capability_id, []).append(snapshot)
        return snapshot

    def validate_configuration(
        self,
        capability_id: str,
        config: dict[str, object],
        created_by: str,
        schema_version: str = "v1",
    ) -> None:
        """Validate a configuration before an external store commits it."""

        entry = self._entries.get(capability_id)
        if entry is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        expected_schema = entry.manifest.configuration_schema_version
        if expected_schema is not None and schema_version != expected_schema:
            raise ExtensionRegistryError(
                f"unsupported capability configuration schema: {capability_id}"
            )
        if not created_by:
            raise ExtensionRegistryError("capability configuration actor is required")
        try:
            encoded = json.dumps(
                config,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ExtensionRegistryError("capability configuration must be JSON") from exc
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise ExtensionRegistryError("capability configuration is too large")

    def load_config_version(self, snapshot: CapabilityConfigVersion) -> None:
        """Load one durable snapshot into the process-local registry."""

        self.validate_configuration(
            snapshot.capability_id,
            snapshot.config,
            snapshot.created_by,
            snapshot.schema_version,
        )
        history = self._configs.setdefault(snapshot.capability_id, [])
        expected_version = len(history) + 1
        if snapshot.version != expected_version:
            raise ExtensionRegistryError(
                "capability configuration history is not contiguous: "
                f"{snapshot.capability_id}@{snapshot.version}"
            )
        history.append(snapshot.model_copy(deep=True))

    async def activate_config_version(self, snapshot: CapabilityConfigVersion) -> None:
        """Load a snapshot and inject it into an already-running capability."""

        self.load_config_version(snapshot)
        entry = self._entries[snapshot.capability_id]
        if entry.lifecycle is None or not entry.lifecycle_started:
            return
        try:
                await self._configure_entry(entry, snapshot.config)
        except Exception as exc:
            self._configs[snapshot.capability_id].pop()
            raise ExtensionRegistryError(
                f"capability configuration apply failed: {snapshot.capability_id}"
            ) from exc

    def config(self, capability_id: str) -> CapabilityConfigVersion | None:
        """Return the currently active configuration snapshot."""

        history = self._configs.get(capability_id)
        return history[-1] if history else None

    def config_versions(self, capability_id: str) -> tuple[CapabilityConfigVersion, ...]:
        """Return configuration history in creation order."""

        if capability_id not in self._entries:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        return tuple(self._configs.get(capability_id, ()))

    def rollback_config(
        self,
        capability_id: str,
        version: int,
        created_by: str,
    ) -> CapabilityConfigVersion:
        """Activate a previous configuration as a new auditable version."""

        history = self._configs.get(capability_id)
        if capability_id not in self._entries:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        target = next((item for item in history or () if item.version == version), None)
        if target is None:
            raise ExtensionRegistryError(
                f"capability configuration version not found: {capability_id}@{version}"
            )
        return self.configure(
            capability_id,
            target.config,
            created_by,
            schema_version=target.schema_version,
            rollback_of=version,
        )

    def validate_contribution_permissions(
        self,
        capability_id: str,
        required_permissions: frozenset[str],
    ) -> None:
        """Reject a tool/UI contribution that exceeds its manifest declaration."""

        entry = self._entries.get(capability_id)
        if entry is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        undeclared = required_permissions - entry.manifest.permissions
        if undeclared:
            raise ExtensionRegistryError(
                "capability contribution requests undeclared permissions: "
                + ",".join(sorted(undeclared))
            )

    def list(self) -> tuple[CapabilityStatusView, ...]:
        """Return registered statuses in stable identifier order."""

        return tuple(self._view(self._entries[key]) for key in sorted(self._entries))

    def observability(self) -> dict[str, object]:
        """Return capability health without exposing lifecycle implementations."""

        items = self.list()
        by_status = {
            status: sum(item.status == status for item in items)
            for status in ("registered", "starting", "ready", "degraded", "stopped")
        }
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "summary": {
                "total": len(items),
                "by_status": by_status,
                "failures": sum(item.failure_count for item in items),
            },
        }

    async def start_all(self) -> tuple[CapabilityStatusView, ...]:
        """Start registered capabilities after validating dependency order."""

        for capability_id in self._ordered_ids():
            entry = self._entries[capability_id]
            if not entry.enabled:
                entry.status = "stopped"
                continue
            blocked_by = next(
                (
                    dependency
                    for dependency in entry.manifest.dependencies
                    if self._entries[dependency].status != "ready"
                ),
                None,
            )
            if blocked_by is not None:
                entry.status = "degraded"
                entry.reason = f"dependency_not_ready:{blocked_by}"
                continue
            if entry.status == "ready":
                continue
            await self._start_entry(entry)
        return self.list()

    async def stop_all(self) -> tuple[CapabilityStatusView, ...]:
        """Stop started capabilities in reverse dependency order."""

        for capability_id in reversed(self._ordered_ids()):
            entry = self._entries[capability_id]
            if not await self._stop_entry(entry):
                continue
            entry.status = "stopped"
        return self.list()

    async def _start_entry(self, entry: _Entry) -> bool:
        blocked_by = next(
            (
                dependency
                for dependency in entry.manifest.dependencies
                if self._entries[dependency].status != "ready"
            ),
            None,
        )
        if blocked_by is not None:
            entry.status = "degraded"
            entry.reason = f"dependency_not_ready:{blocked_by}"
            return False
        if entry.status == "ready" and (entry.lifecycle is None or entry.lifecycle_started):
            return True
        entry.status = "starting"
        entry.reason = None
        if entry.lifecycle is None and entry.lifecycle_factory is not None:
            try:
                lifecycle = entry.lifecycle_factory()
                if lifecycle is None:
                    raise TypeError("lifecycle factory returned None")
                entry.lifecycle = lifecycle
            except Exception as exc:  # noqa: BLE001 - isolate factory failures
                entry.status = "degraded"
                entry.reason = str(exc)[:200] or "lifecycle_factory_failed"
                entry.last_failure_at = datetime.now(UTC)
                entry.failure_count += 1
                return False
        if entry.lifecycle is None:
            entry.status = "ready"
            entry.last_started_at = datetime.now(UTC)
            return True
        try:
            active_config = self.config(entry.manifest.id)
            if active_config is not None:
                await self._configure_entry(entry, active_config.config)
            await self._call_lifecycle(entry.lifecycle.start)
            await self._health_check(entry.lifecycle)
        except Exception as exc:  # noqa: BLE001 - isolate lifecycle failures
            entry.status = "degraded"
            entry.reason = str(exc)[:200] or "lifecycle_start_failed"
            entry.last_failure_at = datetime.now(UTC)
            entry.failure_count += 1
            return False
        entry.lifecycle_started = True
        entry.status = "ready"
        entry.last_started_at = datetime.now(UTC)
        return True

    async def _configure_entry(self, entry: _Entry, config: dict[str, object]) -> None:
        configure = getattr(entry.lifecycle, "configure", None)
        if configure is None:
            return
        result = configure(deepcopy(config))
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=self._lifecycle_timeout_seconds)

    async def _call_lifecycle(self, hook) -> None:
        result = hook()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=self._lifecycle_timeout_seconds)

    async def _health_check(self, lifecycle: CapabilityLifecycle) -> None:
        health = getattr(lifecycle, "health", None)
        if health is None:
            return
        if not callable(health):
            raise TypeError("capability health hook must be callable")
        result = health()
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout=self._lifecycle_timeout_seconds)
        if result is False:
            raise RuntimeError("capability health check failed")

    async def _stop_entry(self, entry: _Entry) -> bool:
        if entry.lifecycle is None or not entry.lifecycle_started:
            entry.status = "stopped"
            entry.last_stopped_at = datetime.now(UTC)
            return True
        try:
            await self._call_lifecycle(entry.lifecycle.stop)
        except Exception as exc:  # noqa: BLE001 - isolate lifecycle failures
            entry.status = "degraded"
            entry.reason = str(exc)[:200] or "lifecycle_stop_failed"
            entry.last_failure_at = datetime.now(UTC)
            entry.failure_count += 1
            return False
        entry.lifecycle_started = False
        entry.status = "stopped"
        entry.last_stopped_at = datetime.now(UTC)
        return True

    @staticmethod
    def _snapshot(entry: _Entry) -> _Snapshot:
        return _Snapshot(
            manifest=entry.manifest,
            lifecycle=entry.lifecycle,
            lifecycle_factory=entry.lifecycle_factory,
            enabled=entry.enabled,
            status=entry.status,
            reason=entry.reason,
            lifecycle_started=entry.lifecycle_started,
            last_started_at=entry.last_started_at,
            last_stopped_at=entry.last_stopped_at,
            last_failure_at=entry.last_failure_at,
            failure_count=entry.failure_count,
        )

    @staticmethod
    def _restore_entry(entry: _Entry, snapshot: _Snapshot) -> None:
        entry.manifest = snapshot.manifest
        entry.lifecycle = snapshot.lifecycle
        entry.lifecycle_factory = snapshot.lifecycle_factory
        entry.enabled = snapshot.enabled
        entry.status = snapshot.status
        entry.reason = snapshot.reason
        entry.lifecycle_started = False
        entry.last_started_at = snapshot.last_started_at
        entry.last_stopped_at = snapshot.last_stopped_at
        entry.last_failure_at = snapshot.last_failure_at
        entry.failure_count = snapshot.failure_count

    def _depends_on(self, capability_id: str, dependency_id: str) -> bool:
        visiting: set[str] = set()

        def visit(current_id: str) -> bool:
            if current_id in visiting:
                return False
            visiting.add(current_id)
            entry = self._entries[current_id]
            if dependency_id in entry.manifest.dependencies:
                return True
            return any(visit(dependency) for dependency in entry.manifest.dependencies)

        return visit(capability_id)

    def _ordered_ids(self) -> tuple[str, ...]:
        order: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(capability_id: str) -> None:
            if capability_id in visited:
                return
            if capability_id in visiting:
                raise ExtensionRegistryError("capability dependency cycle detected")
            entry = self._entries.get(capability_id)
            if entry is None:
                raise ExtensionRegistryError(f"missing capability dependency: {capability_id}")
            visiting.add(capability_id)
            for dependency in entry.manifest.dependencies:
                visit(dependency)
            visiting.remove(capability_id)
            visited.add(capability_id)
            order.append(capability_id)

        for capability_id in sorted(self._entries):
            visit(capability_id)
        return tuple(order)
