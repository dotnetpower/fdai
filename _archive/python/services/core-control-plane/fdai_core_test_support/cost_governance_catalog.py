"""Test composition for the optional Cost Governance catalog."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from fdai.core.capability_catalog import ExtensionManifest, ExtensionState
from fdai.core.vertical_packages import VerticalPackageManager
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

from fdai_cost_governance import (
    build_cost_governance_bundle,
    materialize_cost_governance_catalog,
)

_ARCHIVE = b"reviewed-fdai-cost-governance-test-wheel"
_HOST_REFERENCES = {
    "action:remediate.remove-orphan-resource",
    "action:remediate.right-size",
    "action:remediate.set-retention-policy",
    "action:remediate.tag-add",
}


class _TrustExactArchive:
    def verify(self, manifest: ExtensionManifest, archive: bytes) -> bool:
        return manifest.archive_sha256 == hashlib.sha256(archive).hexdigest()


@dataclass(frozen=True, slots=True)
class CostGovernanceCatalogComposition:
    """One base catalog with an explicitly installed optional package."""

    rules: tuple[Rule, ...]
    action_types: tuple[OntologyActionType, ...]
    policies_root: Path
    remediation_root: Path
    package_state: ExtensionState
    base_rule_ids: frozenset[str]
    package_rule_ids: frozenset[str]

    @property
    def package_enabled(self) -> bool:
        return self.package_state is ExtensionState.ENABLED


def compose_cost_governance_catalog(
    repo_root: Path,
    *,
    enabled: bool,
    scratch_root: Path | None = None,
) -> CostGovernanceCatalogComposition:
    """Install the package and compose its active assets exactly once when enabled."""

    registry = PackageResourceSchemaRegistry()
    action_types = tuple(
        load_action_type_catalog(
            repo_root / "rule-catalog/action-types",
            schema_registry=registry,
            probes_root=repo_root / "rule-catalog/probes",
        )
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (repo_root / "rule-catalog/vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    policies_root = repo_root / "policies"
    remediation_root = repo_root / "rule-catalog/remediation"
    base_rules = load_rule_catalog(
        repo_root / "rule-catalog/catalog",
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=policies_root,
        remediation_root=remediation_root,
    )
    base_rule_ids = frozenset(rule.id for rule in base_rules)

    bundle = build_cost_governance_bundle(archive_sha256=hashlib.sha256(_ARCHIVE).hexdigest())
    manager = VerticalPackageManager(
        host_version="0.1.3",
        ontology_release_digest=bundle.manifest.ontology_release_range,
        provider_bindings={"cost-estimator"},
        host_reference_ids=_HOST_REFERENCES,
    ).install(
        bundle,
        archive=_ARCHIVE,
        image_digest=f"sha256:{'f' * 64}",
        verifier=_TrustExactArchive(),
    )
    if not enabled:
        if manager.runtime().package_ids():
            raise AssertionError("disabled package unexpectedly contributed runtime assets")
        return CostGovernanceCatalogComposition(
            rules=base_rules,
            action_types=action_types,
            policies_root=policies_root,
            remediation_root=remediation_root,
            package_state=manager.list()[0][1],
            base_rule_ids=base_rule_ids,
            package_rule_ids=frozenset(),
        )

    if scratch_root is None:
        raise ValueError("scratch_root is required for enabled package composition")
    manager = manager.enable("cost-governance")
    runtime = manager.runtime()
    if runtime.package_ids() != ("cost-governance",):
        raise AssertionError("enabled Cost Governance package is absent from the runtime")
    package_catalog = materialize_cost_governance_catalog(
        runtime,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
    )
    package_rule_ids = frozenset(rule.id for rule in package_catalog.rules)
    if len(package_rule_ids) != 12:
        raise AssertionError("Cost Governance package must materialize exactly 12 rules")
    duplicate_rule_ids = base_rule_ids & package_rule_ids
    if duplicate_rule_ids:
        raise AssertionError(
            f"base and package catalogs duplicate rule ids: {sorted(duplicate_rule_ids)}"
        )

    composed_root = scratch_root / "cost-governance-catalog"
    composed_policies_root = composed_root / "policies"
    composed_remediation_root = composed_root / "remediation"
    shutil.copytree(policies_root, composed_policies_root)
    shutil.copytree(remediation_root, composed_remediation_root)
    _write_package_assets(
        composed_policies_root,
        package_catalog.policies,
        prefix="policies",
    )
    _write_package_assets(
        composed_remediation_root,
        package_catalog.remediations,
        prefix="remediation",
    )

    rules = (*base_rules, *package_catalog.rules)
    if len(rules) != len({rule.id for rule in rules}):
        raise AssertionError("composed catalog contains duplicate rule ids")
    return CostGovernanceCatalogComposition(
        rules=rules,
        action_types=action_types,
        policies_root=composed_policies_root,
        remediation_root=composed_remediation_root,
        package_state=manager.list()[0][1],
        base_rule_ids=base_rule_ids,
        package_rule_ids=package_rule_ids,
    )


def _write_package_assets(
    root: Path,
    assets: Mapping[str, bytes],
    *,
    prefix: str,
) -> None:
    for resource_path, content in assets.items():
        relative = Path(resource_path)
        if not relative.parts or relative.parts[0] != prefix:
            raise AssertionError(f"unexpected package asset path: {resource_path}")
        target = root.joinpath(*relative.parts[1:])
        if target.exists():
            raise AssertionError(f"base and package catalogs duplicate asset path: {resource_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


__all__ = [
    "CostGovernanceCatalogComposition",
    "compose_cost_governance_catalog",
]
