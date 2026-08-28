"""Materialize enabled vertical package assets through ordinary catalog loaders."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import yaml

from fdai.core.vertical_packages.models import (
    VerticalAssetKind,
    VerticalPackageAsset,
    VerticalPackageRuntime,
    VerticalPackageValidationError,
)
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.rule_catalog.schema.rule import load_rule_from_mapping
from fdai.rule_catalog.schema.signal_type import SignalTypeRegistry
from fdai.rule_catalog.schema.workflow import load_workflow_from_mapping
from fdai.shared.contracts.models import OntologyActionType, Rule, Workflow
from fdai.shared.contracts.registry import SchemaRegistry


@dataclass(frozen=True, slots=True)
class VerticalMaterializedCatalog:
    """Validated package catalog projection with no execution surface."""

    vertical_id: str
    package_version: str
    rules: tuple[Rule, ...]
    workflows: tuple[Workflow, ...]
    policies: Mapping[str, bytes]
    remediations: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policies", MappingProxyType(dict(self.policies)))
        object.__setattr__(self, "remediations", MappingProxyType(dict(self.remediations)))


def materialize_vertical_package_catalog(
    runtime: VerticalPackageRuntime,
    *,
    vertical_id: str,
    schema_registry: SchemaRegistry,
    action_types: Iterable[OntologyActionType],
    resource_types: ResourceTypeRegistry,
    signal_types: SignalTypeRegistry | None = None,
) -> VerticalMaterializedCatalog:
    """Load one active package with the standard Rule and Workflow validators."""

    bundle = runtime.packages.get(vertical_id)
    if bundle is None:
        raise VerticalPackageValidationError(f"vertical package {vertical_id!r} is not active")
    assets = {
        asset.declaration.asset_id: asset
        for asset in bundle.assets
        if asset.declaration.kind
        in {
            VerticalAssetKind.POLICY,
            VerticalAssetKind.REMEDIATION,
            VerticalAssetKind.RULE,
            VerticalAssetKind.WORKFLOW,
        }
    }
    action_type_names = {action_type.name for action_type in action_types}
    rules = tuple(
        load_rule_from_mapping(
            _yaml_mapping(asset),
            schema_registry=schema_registry,
            action_type_names=action_type_names,
            resource_type_ids=resource_types.ids(),
            signal_type_ids=signal_types.ids() if signal_types is not None else None,
            origin=f"package:{vertical_id}:{asset.declaration.resource_path}",
        )
        for asset in _assets_of_kind(assets.values(), VerticalAssetKind.RULE)
    )
    workflows = tuple(
        load_workflow_from_mapping(
            _yaml_mapping(asset),
            schema_registry=schema_registry,
            action_type_names=action_type_names,
            rule_ids={rule.id for rule in rules},
            origin=f"package:{vertical_id}:{asset.declaration.resource_path}",
        )
        for asset in _assets_of_kind(assets.values(), VerticalAssetKind.WORKFLOW)
    )
    _require_unique((rule.id for rule in rules), "rule")
    _require_unique((workflow.name for workflow in workflows), "workflow")
    return VerticalMaterializedCatalog(
        vertical_id=vertical_id,
        package_version=bundle.manifest.extension.version,
        rules=rules,
        workflows=workflows,
        policies=_content_by_path(assets.values(), VerticalAssetKind.POLICY),
        remediations=_content_by_path(
            assets.values(),
            VerticalAssetKind.REMEDIATION,
        ),
    )


def _assets_of_kind(
    assets: Iterable[VerticalPackageAsset],
    kind: VerticalAssetKind,
) -> tuple[VerticalPackageAsset, ...]:
    return tuple(
        sorted(
            (asset for asset in assets if asset.declaration.kind is kind),
            key=lambda asset: asset.declaration.asset_id,
        )
    )


def _yaml_mapping(asset: VerticalPackageAsset) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(asset.content)
    except yaml.YAMLError as exc:
        raise VerticalPackageValidationError(
            f"vertical asset {asset.declaration.asset_id!r} contains invalid YAML"
        ) from exc
    if not isinstance(value, Mapping):
        raise VerticalPackageValidationError(
            f"vertical asset {asset.declaration.asset_id!r} must contain a YAML object"
        )
    return value


def _content_by_path(
    assets: Iterable[VerticalPackageAsset],
    kind: VerticalAssetKind,
) -> Mapping[str, bytes]:
    return {
        asset.declaration.resource_path: bytes(asset.content)
        for asset in _assets_of_kind(assets, kind)
    }


def _require_unique(values: Iterable[str], label: str) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise VerticalPackageValidationError(
            f"materialized vertical package contains duplicate {label} ids"
        )


__all__ = ["VerticalMaterializedCatalog", "materialize_vertical_package_catalog"]
