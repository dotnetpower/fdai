"""Package-resource loading and immutable bundle construction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from fdai.core.capability_catalog import ExtensionManifest
from fdai.core.vertical_packages import (
    VerticalAssetDeclaration,
    VerticalAssetKind,
    VerticalMaterializedCatalog,
    VerticalPackageAsset,
    VerticalPackageBundle,
    VerticalPackageManifest,
    VerticalPackageRuntime,
    VerticalProviderDeclaration,
    materialize_vertical_package_catalog,
)
from fdai.core.verticals import VerticalDescriptor
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.rule_catalog.schema.signal_type import SignalTypeRegistry
from fdai.shared.contracts.models import Category, OntologyActionType
from fdai.shared.contracts.registry import SchemaRegistry

from fdai_cost_governance.__about__ import __version__

_RESOURCE_PACKAGE = "fdai_cost_governance.resources"
_MANIFEST_PATH = "manifest.json"
_EXPECTED_PACKAGE_ID = "cost-governance"


class CostGovernanceResourceError(ValueError):
    """A packaged candidate resource failed deterministic verification."""


@dataclass(frozen=True, slots=True)
class PackageResource:
    """Verified package resource metadata and immutable bytes."""

    asset_id: str
    kind: VerticalAssetKind
    path: str
    sha256: str
    references: tuple[str, ...]
    content: bytes

    def as_vertical_asset(self) -> VerticalPackageAsset:
        """Convert verified package metadata to the generic Core contract."""

        return VerticalPackageAsset(
            declaration=VerticalAssetDeclaration(
                asset_id=self.asset_id,
                kind=self.kind,
                resource_path=self.path,
                sha256=self.sha256,
                references=self.references,
            ),
            content=self.content,
        )


def load_resource_bytes(path: str) -> bytes:
    """Load one package-relative resource without consulting the repository."""

    parts = path.split("/")
    if not path or any(part in {"", ".", ".."} for part in parts):
        raise CostGovernanceResourceError("resource path must be package-relative")
    resource = files(_RESOURCE_PACKAGE).joinpath(*parts)
    if not resource.is_file():
        raise CostGovernanceResourceError(f"package resource {path!r} does not exist")
    return resource.read_bytes()


def load_resource_manifest() -> dict[str, Any]:
    """Load and validate the canonical candidate resource manifest."""

    try:
        value = json.loads(load_resource_bytes(_MANIFEST_PATH))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CostGovernanceResourceError(
            "resource manifest must contain valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise CostGovernanceResourceError("resource manifest must contain a JSON object")
    if value.get("schema_version") != "1.0.0":
        raise CostGovernanceResourceError("resource manifest schema is unsupported")
    if value.get("package_id") != _EXPECTED_PACKAGE_ID:
        raise CostGovernanceResourceError("resource manifest package id is invalid")
    if value.get("package_version") != __version__:
        raise CostGovernanceResourceError("resource manifest package version is invalid")
    if value.get("candidate_state") != "inert":
        raise CostGovernanceResourceError("package candidates must remain inert")
    if not isinstance(value.get("assets"), list):
        raise CostGovernanceResourceError("resource manifest assets must be an array")
    return value


def load_package_resources() -> tuple[PackageResource, ...]:
    """Verify all manifest resources and return them in canonical id order."""

    manifest = load_resource_manifest()
    resources: list[PackageResource] = []
    ids: set[str] = set()
    paths: set[str] = set()
    digests: set[str] = set()
    for raw in manifest["assets"]:
        if not isinstance(raw, dict):
            raise CostGovernanceResourceError("resource manifest entries must be objects")
        try:
            asset_id = str(raw["id"])
            kind = VerticalAssetKind(str(raw["kind"]))
            path = str(raw["path"])
            sha256 = str(raw["sha256"])
            references = tuple(str(item) for item in raw["references"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CostGovernanceResourceError("resource manifest entry is invalid") from exc
        if asset_id in ids or path in paths or sha256 in digests:
            raise CostGovernanceResourceError("resource ids, paths, and digests must be unique")
        content = load_resource_bytes(path)
        if hashlib.sha256(content).hexdigest() != sha256:
            raise CostGovernanceResourceError(f"package resource digest mismatch: {asset_id}")
        resources.append(
            PackageResource(
                asset_id=asset_id,
                kind=kind,
                path=path,
                sha256=sha256,
                references=references,
                content=content,
            )
        )
        ids.add(asset_id)
        paths.add(path)
        digests.add(sha256)
    if [resource.asset_id for resource in resources] != sorted(ids):
        raise CostGovernanceResourceError("resource manifest entries must use canonical id order")
    return tuple(resources)


def resource_manifest_sha256() -> str:
    """Return the canonical JSON digest consumed by Core validation."""

    manifest = load_resource_manifest()
    encoded = json.dumps(
        manifest,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_cost_governance_bundle(
    *,
    archive_sha256: str,
    source: str = "image:fdai-cost-governance",
) -> VerticalPackageBundle:
    """Build the disabled, shadow-first candidate supplied to generic Core composition."""

    resources = load_package_resources()
    by_id = {resource.asset_id: resource for resource in resources}
    semantic_profile = by_id["semantic-profile:cost-governance"].content
    profile = json.loads(semantic_profile)
    extension = ExtensionManifest(
        extension_id="cost-governance",
        version=__version__,
        source=source,
        archive_sha256=archive_sha256,
        min_host_version="0.1.3",
    )
    manifest = VerticalPackageManifest(
        extension=extension,
        vertical_id="cost-governance",
        asset_manifest_sha256=resource_manifest_sha256(),
        ontology_release_range=str(profile["ontology_release_digest"]),
        semantic_profile_sha256=str(profile["canonical_sha256"]),
        required_provider_bindings=("cost-estimator",),
    )
    return VerticalPackageBundle(
        descriptor=VerticalDescriptor(
            vertical_id="cost-governance",
            display_name="Cost Governance",
            category=Category.COST,
            rule_source_ids=("package:cost-governance",),
        ),
        manifest=manifest,
        asset_manifest=load_resource_bytes(_MANIFEST_PATH),
        semantic_profile=semantic_profile,
        assets=tuple(resource.as_vertical_asset() for resource in resources),
        providers=(
            VerticalProviderDeclaration(
                binding_id="cost-estimator",
                protocol="fdai.shared.providers.CostEstimator",
            ),
        ),
    )


def materialize_cost_governance_catalog(
    runtime: VerticalPackageRuntime,
    *,
    schema_registry: SchemaRegistry,
    action_types: Iterable[OntologyActionType],
    resource_types: ResourceTypeRegistry,
    signal_types: SignalTypeRegistry | None = None,
) -> VerticalMaterializedCatalog:
    """Validate active package resources through the ordinary Core loaders."""

    return materialize_vertical_package_catalog(
        runtime,
        vertical_id=_EXPECTED_PACKAGE_ID,
        schema_registry=schema_registry,
        action_types=action_types,
        resource_types=resource_types,
        signal_types=signal_types,
    )


__all__ = [
    "CostGovernanceResourceError",
    "PackageResource",
    "build_cost_governance_bundle",
    "load_package_resources",
    "load_resource_bytes",
    "load_resource_manifest",
    "materialize_cost_governance_catalog",
    "resource_manifest_sha256",
]
