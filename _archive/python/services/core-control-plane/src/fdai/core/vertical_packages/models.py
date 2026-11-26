"""Immutable contracts for reviewed vertical package resources and activation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar

from fdai.core.capability_catalog import CapabilityBundle, ExtensionManifest, ExtensionState
from fdai.core.supply_chain.artifacts import TrustedArtifactKind
from fdai.core.verticals import VerticalDescriptor

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:/-]{1,191}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_PROFILE_SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class VerticalAssetKind(StrEnum):
    """Declarative package resource classes accepted by the vertical runtime."""

    POLICY = "policy"
    REMEDIATION = "remediation"
    RULE = "rule"
    SEMANTIC_PROFILE = "semantic_profile"
    WORKFLOW = "workflow"


@dataclass(frozen=True, slots=True)
class VerticalAssetDeclaration:
    """Stable resource identity, content digest, and declared references."""

    asset_id: str
    kind: VerticalAssetKind
    resource_path: str
    sha256: str
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _ID_PATTERN.fullmatch(self.asset_id) is None:
            raise ValueError("vertical asset_id must be stable lowercase ASCII")
        if not self.resource_path or self.resource_path.startswith(("/", "../")):
            raise ValueError("vertical resource_path must be package-relative")
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("vertical asset sha256 must be a lowercase SHA-256 digest")
        if len(set(self.references)) != len(self.references):
            raise ValueError("vertical asset references must not contain duplicates")
        if any(_ID_PATTERN.fullmatch(reference) is None for reference in self.references):
            raise ValueError("vertical asset references must use stable lowercase ASCII ids")


@dataclass(frozen=True, slots=True)
class VerticalPackageAsset:
    """One immutable declaration and its verified candidate bytes."""

    declaration: VerticalAssetDeclaration
    content: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", bytes(self.content))


@dataclass(frozen=True, slots=True)
class VerticalProviderDeclaration:
    """Provider Protocol binding required or optionally consumed by a package."""

    binding_id: str
    protocol: str
    required: bool = True

    def __post_init__(self) -> None:
        if _ID_PATTERN.fullmatch(self.binding_id) is None:
            raise ValueError("vertical provider binding_id must be stable lowercase ASCII")
        if not self.protocol or not self.protocol.isascii():
            raise ValueError("vertical provider protocol must be non-empty ASCII")


@dataclass(frozen=True, slots=True)
class VerticalPackageManifest:
    """Trusted extension identity plus vertical compatibility requirements."""

    artifact_kind: ClassVar[TrustedArtifactKind] = TrustedArtifactKind.EXTENSION

    extension: ExtensionManifest
    vertical_id: str
    asset_manifest_sha256: str
    ontology_release_range: str
    semantic_profile_sha256: str
    required_provider_bindings: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _ID_PATTERN.fullmatch(self.vertical_id) is None:
            raise ValueError("vertical_id must be stable lowercase ASCII")
        if _SHA256_PATTERN.fullmatch(self.asset_manifest_sha256) is None:
            raise ValueError("asset_manifest_sha256 must be a lowercase SHA-256 digest")
        if _PROFILE_SHA256_PATTERN.fullmatch(self.ontology_release_range) is None:
            raise ValueError("W2 ontology_release_range must pin one exact SHA-256 release")
        if _PROFILE_SHA256_PATTERN.fullmatch(self.semantic_profile_sha256) is None:
            raise ValueError("semantic_profile_sha256 must use sha256:<digest>")
        if len(set(self.required_provider_bindings)) != len(self.required_provider_bindings):
            raise ValueError("required_provider_bindings must not contain duplicates")
        if len(set(self.capability_ids)) != len(self.capability_ids):
            raise ValueError("capability_ids must not contain duplicates")
        if self.extension.capability_ids != self.capability_ids:
            raise ValueError("vertical and extension capability ids must match")


@dataclass(frozen=True, slots=True)
class VerticalPackageBundle:
    """Complete reviewed vertical candidate; contents grant no runtime authority."""

    descriptor: VerticalDescriptor
    manifest: VerticalPackageManifest
    asset_manifest: bytes
    semantic_profile: bytes
    assets: tuple[VerticalPackageAsset, ...]
    providers: tuple[VerticalProviderDeclaration, ...] = ()
    capability_bundle: CapabilityBundle | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_manifest", bytes(self.asset_manifest))
        object.__setattr__(self, "semantic_profile", bytes(self.semantic_profile))
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(self, "providers", tuple(self.providers))


@dataclass(frozen=True, slots=True)
class VerticalPackageAvailability:
    """Derived package availability with stable, bounded diagnostic reasons."""

    available: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reasons = tuple(sorted(set(self.reasons)))
        object.__setattr__(self, "reasons", reasons)
        if len(reasons) > 32 or any(
            not reason.isascii() or not 1 <= len(reason) <= 256 for reason in reasons
        ):
            raise ValueError("availability reasons must be bounded non-empty ASCII")
        if self.available == bool(reasons):
            raise ValueError("availability must be true exactly when reasons are empty")


@dataclass(frozen=True, slots=True)
class VerticalPackageRelease:
    """One verified immutable package release retained for N-1 rollback."""

    bundle: VerticalPackageBundle
    availability: VerticalPackageAvailability
    image_digest: str

    def __post_init__(self) -> None:
        if _PROFILE_SHA256_PATTERN.fullmatch(self.image_digest) is None:
            raise ValueError("vertical package image_digest must use sha256:<digest>")


@dataclass(frozen=True, slots=True)
class InstalledVerticalPackage(VerticalPackageRelease):
    """Disabled-first installed release plus at most one rollback candidate."""

    state: ExtensionState = ExtensionState.DISABLED
    previous_release: VerticalPackageRelease | None = None


@dataclass(frozen=True, slots=True)
class VerticalPackageActivationMetadata:
    """Manager-derived package state and immutable artifact attribution."""

    vertical_id: str
    package_id: str
    available: bool
    enabled: bool
    availability_reasons: tuple[str, ...]
    package_version: str
    image_digest: str
    asset_manifest_digest: str
    semantic_profile_digest: str
    ontology_release_digest: str

    def __post_init__(self) -> None:
        reasons = tuple(sorted(set(self.availability_reasons)))
        object.__setattr__(self, "availability_reasons", reasons)
        if self.available == bool(reasons):
            raise ValueError("available must be true exactly when availability reasons are empty")
        if self.enabled and not self.available:
            raise ValueError("an unavailable vertical package cannot be enabled")
        for name in (
            "image_digest",
            "asset_manifest_digest",
            "semantic_profile_digest",
            "ontology_release_digest",
        ):
            if _PROFILE_SHA256_PATTERN.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must use sha256:<digest>")


@dataclass(frozen=True, slots=True)
class VerticalPackageRuntime:
    """Immutable active package and asset projection rebuilt from a fixed base."""

    packages: Mapping[str, VerticalPackageBundle] = field(default_factory=dict)
    assets: Mapping[str, VerticalPackageAsset] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "packages", MappingProxyType(dict(self.packages)))
        object.__setattr__(self, "assets", MappingProxyType(dict(self.assets)))

    def package_ids(self) -> tuple[str, ...]:
        """Return active package ids in stable order."""

        return tuple(sorted(self.packages))

    def asset_ids(self) -> tuple[str, ...]:
        """Return active asset ids in stable order."""

        return tuple(sorted(self.assets))


class VerticalPackageValidationError(ValueError):
    """A vertical package failed validation before runtime publication."""


class VerticalPackageLifecycleError(ValueError):
    """A vertical package lifecycle request could not publish a candidate."""


__all__ = [
    "InstalledVerticalPackage",
    "VerticalAssetDeclaration",
    "VerticalAssetKind",
    "VerticalPackageAsset",
    "VerticalPackageActivationMetadata",
    "VerticalPackageAvailability",
    "VerticalPackageBundle",
    "VerticalPackageLifecycleError",
    "VerticalPackageManifest",
    "VerticalPackageRelease",
    "VerticalPackageRuntime",
    "VerticalPackageValidationError",
    "VerticalProviderDeclaration",
]
