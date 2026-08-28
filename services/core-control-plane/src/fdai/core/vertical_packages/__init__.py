"""Generic immutable vertical package contracts and lifecycle."""

from fdai.core.vertical_packages.catalog import (
    VerticalMaterializedCatalog,
    materialize_vertical_package_catalog,
)
from fdai.core.vertical_packages.manager import VerticalPackageManager
from fdai.core.vertical_packages.models import (
    InstalledVerticalPackage,
    VerticalAssetDeclaration,
    VerticalAssetKind,
    VerticalPackageActivationMetadata,
    VerticalPackageAsset,
    VerticalPackageAvailability,
    VerticalPackageBundle,
    VerticalPackageLifecycleError,
    VerticalPackageManifest,
    VerticalPackageRelease,
    VerticalPackageRuntime,
    VerticalPackageValidationError,
    VerticalProviderDeclaration,
)

__all__ = [
    "InstalledVerticalPackage",
    "VerticalAssetDeclaration",
    "VerticalAssetKind",
    "VerticalPackageAsset",
    "VerticalPackageActivationMetadata",
    "VerticalPackageAvailability",
    "VerticalPackageBundle",
    "VerticalPackageLifecycleError",
    "VerticalMaterializedCatalog",
    "VerticalPackageManager",
    "VerticalPackageManifest",
    "VerticalPackageRelease",
    "VerticalPackageRuntime",
    "VerticalPackageValidationError",
    "VerticalProviderDeclaration",
    "materialize_vertical_package_catalog",
]
