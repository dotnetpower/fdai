"""Trust-verified lifecycle for capability-bundle extensions."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from fdai.core.capability_catalog.runtime import (
    CapabilityBundle,
    CapabilityReferences,
    CapabilityRuntime,
    CapabilityRuntimeError,
)
from fdai.shared.telemetry.transitions import (
    RoutingTransition,
    RoutingTransitionSink,
    default_transition_emitter,
    emit_transition_safely,
)

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ExtensionState(StrEnum):
    DISABLED = "disabled"
    ENABLED = "enabled"


@dataclass(frozen=True, slots=True)
class ExtensionManifest:
    """Inert identity, provenance, compatibility, and content digest."""

    extension_id: str
    version: str
    source: str
    archive_sha256: str
    min_host_version: str
    max_host_version: str | None = None
    capability_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _ID_PATTERN.fullmatch(self.extension_id) is None:
            raise ValueError("extension_id MUST be lowercase ASCII with dot or hyphen separators")
        _version_tuple(self.version)
        _version_tuple(self.min_host_version)
        if self.max_host_version is not None:
            _version_tuple(self.max_host_version)
        if not self.source.strip():
            raise ValueError("extension source MUST be non-empty")
        if _SHA256_PATTERN.fullmatch(self.archive_sha256) is None:
            raise ValueError("archive_sha256 MUST be a lowercase SHA-256 digest")
        if len(set(self.capability_ids)) != len(self.capability_ids):
            raise ValueError("capability_ids MUST NOT contain duplicates")


@dataclass(frozen=True, slots=True)
class ExtensionPackage:
    """Manifest plus an already-composed, non-executable capability bundle."""

    manifest: ExtensionManifest
    bundle: CapabilityBundle


@dataclass(frozen=True, slots=True)
class InstalledExtension:
    package: ExtensionPackage
    state: ExtensionState = ExtensionState.DISABLED


class ExtensionTrustVerifier(Protocol):
    """Verify publisher provenance or a detached signature for an archive."""

    def verify(self, manifest: ExtensionManifest, archive: bytes) -> bool: ...


class ExtensionLifecycleError(ValueError):
    """An extension operation failed before changing the active runtime."""


class ExtensionManager:
    """Immutable extension registry rebuilt atomically from enabled bundles."""

    __slots__ = (
        "_base_runtime",
        "_host_version",
        "_installed",
        "_references",
        "_transition_sink",
    )

    def __init__(
        self,
        *,
        host_version: str,
        references: CapabilityReferences,
        base_runtime: CapabilityRuntime | None = None,
        installed: Mapping[str, InstalledExtension] | None = None,
        transition_sink: RoutingTransitionSink | None = None,
    ) -> None:
        _version_tuple(host_version)
        self._host_version = host_version
        self._references = references
        self._base_runtime = base_runtime or CapabilityRuntime()
        self._installed = MappingProxyType(dict(installed or {}))
        self._transition_sink = transition_sink or default_transition_emitter()

    def install(
        self,
        package: ExtensionPackage,
        *,
        archive: bytes,
        verifier: ExtensionTrustVerifier,
    ) -> ExtensionManager:
        """Verify and register one extension in the disabled state."""
        manifest = package.manifest
        if manifest.extension_id in self._installed:
            raise ExtensionLifecycleError(f"extension {manifest.extension_id!r} is installed")
        digest = hashlib.sha256(archive).hexdigest()
        if digest != manifest.archive_sha256:
            raise ExtensionLifecycleError("extension archive digest does not match manifest")
        if not verifier.verify(manifest, archive):
            raise ExtensionLifecycleError("extension trust verification failed")
        _validate_compatibility(manifest, self._host_version)
        _validate_manifest_bundle(package)
        installed = dict(self._installed)
        installed[manifest.extension_id] = InstalledExtension(package=package)
        result = self._copy(installed)
        self._emit(manifest.extension_id, "installed", "accepted")
        return result

    def enable(self, extension_id: str) -> ExtensionManager:
        installed = dict(self._installed)
        current = _require_extension(installed, extension_id)
        if current.state is ExtensionState.ENABLED:
            return self
        installed[extension_id] = InstalledExtension(
            package=current.package,
            state=ExtensionState.ENABLED,
        )
        candidate = self._copy(installed)
        candidate.runtime()
        self._emit(extension_id, "state", "enabled")
        return candidate

    def disable(self, extension_id: str) -> ExtensionManager:
        installed = dict(self._installed)
        current = _require_extension(installed, extension_id)
        if current.state is ExtensionState.DISABLED:
            return self
        installed[extension_id] = InstalledExtension(package=current.package)
        candidate = self._copy(installed)
        candidate.runtime()
        self._emit(extension_id, "state", "disabled")
        return candidate

    def uninstall(self, extension_id: str) -> ExtensionManager:
        installed = dict(self._installed)
        current = _require_extension(installed, extension_id)
        if current.state is ExtensionState.ENABLED:
            raise ExtensionLifecycleError("disable an extension before uninstalling it")
        del installed[extension_id]
        result = self._copy(installed)
        self._emit(extension_id, "uninstalled", "accepted")
        return result

    def runtime(self) -> CapabilityRuntime:
        """Build the active runtime from the base and enabled packages."""
        runtime = self._base_runtime
        try:
            for extension_id in sorted(self._installed):
                extension = self._installed[extension_id]
                if extension.state is ExtensionState.ENABLED:
                    runtime = runtime.install(
                        extension.package.bundle,
                        references=self._references,
                    )
        except CapabilityRuntimeError as exc:
            raise ExtensionLifecycleError(f"extension activation failed: {exc}") from exc
        return runtime

    def list(self) -> tuple[tuple[str, ExtensionState, str], ...]:
        return tuple(
            (extension_id, installed.state, installed.package.manifest.version)
            for extension_id, installed in sorted(self._installed.items())
        )

    def _copy(self, installed: Mapping[str, InstalledExtension]) -> ExtensionManager:
        return ExtensionManager(
            host_version=self._host_version,
            references=self._references,
            base_runtime=self._base_runtime,
            installed=installed,
            transition_sink=self._transition_sink,
        )

    def _emit(self, extension_id: str, name: str, outcome: str) -> None:
        emit_transition_safely(
            self._transition_sink,
            RoutingTransition(
                domain="extension",
                name=name,
                outcome=outcome,
                attributes={"extension_id": extension_id},
            ),
        )


def _validate_manifest_bundle(package: ExtensionPackage) -> None:
    declared = set(package.manifest.capability_ids)
    actual = {capability.capability_id for capability in package.bundle.capabilities}
    bound = {binding.capability_id for binding in package.bundle.bindings}
    if declared != actual or not bound.issubset(declared):
        raise ExtensionLifecycleError(
            "extension manifest capability ids do not match bundle metadata and bindings"
        )


def _validate_compatibility(manifest: ExtensionManifest, host_version: str) -> None:
    host = _version_tuple(host_version)
    if host < _version_tuple(manifest.min_host_version):
        raise ExtensionLifecycleError("extension requires a newer FDAI host")
    if manifest.max_host_version is not None and host > _version_tuple(manifest.max_host_version):
        raise ExtensionLifecycleError("extension does not support this FDAI host version")


def _require_extension(
    installed: Mapping[str, InstalledExtension], extension_id: str
) -> InstalledExtension:
    try:
        return installed[extension_id]
    except KeyError as exc:
        raise ExtensionLifecycleError(f"extension {extension_id!r} is not installed") from exc


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"version {value!r} MUST use MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


__all__ = [
    "ExtensionLifecycleError",
    "ExtensionManager",
    "ExtensionManifest",
    "ExtensionPackage",
    "ExtensionState",
    "ExtensionTrustVerifier",
    "InstalledExtension",
]
