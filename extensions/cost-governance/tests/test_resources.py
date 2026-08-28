from __future__ import annotations

import ast
import hashlib
import json
import tomllib
from pathlib import Path

import pytest
import yaml
from fdai.core.capability_catalog import ExtensionManifest, ExtensionState
from fdai.core.vertical_packages import (
    VerticalAssetKind,
    VerticalPackageManager,
    VerticalPackageValidationError,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.shared.contracts.models import Rule, Workflow
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

from fdai_cost_governance import (
    __version__,
    build_cost_governance_bundle,
    load_package_resources,
    load_resource_manifest,
    materialize_cost_governance_catalog,
    resource_manifest_sha256,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
ARCHIVE = b"reviewed-fdai-cost-governance-wheel"


class _TrustExactArchive:
    def verify(self, manifest: ExtensionManifest, archive: bytes) -> bool:
        return manifest.archive_sha256 == hashlib.sha256(archive).hexdigest()


def _walk(value: object) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.append((str(key), child))
            found.extend(_walk(child))
    elif isinstance(value, list | tuple):
        for child in value:
            found.extend(_walk(child))
    return found


def test_resource_manifest_is_canonical_inert_and_complete() -> None:
    manifest = load_resource_manifest()
    resources = load_package_resources()

    assert manifest["candidate_state"] == "inert"
    assert len(resources) == 38
    assert [resource.asset_id for resource in resources] == sorted(
        resource.asset_id for resource in resources
    )
    assert sum(resource.kind is VerticalAssetKind.RULE for resource in resources) == 12
    assert sum(resource.kind is VerticalAssetKind.POLICY for resource in resources) == 12
    assert sum(resource.kind is VerticalAssetKind.REMEDIATION for resource in resources) == 12
    assert {resource.asset_id for resource in resources} >= {
        "rule:compute.vm.low-utilization",
        "semantic-profile:cost-governance",
        "workflow:cost-aware-remediation",
    }
    canonical = json.dumps(
        manifest,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    assert resource_manifest_sha256() == hashlib.sha256(canonical).hexdigest()


def test_cutover_assets_preserve_w0_ids_and_leave_no_active_base_copy() -> None:
    resources = {resource.asset_id: resource for resource in load_package_resources()}
    inventory = json.loads(
        (REPO_ROOT / "config/cost-governance-package-inventory.json").read_text(encoding="utf-8")
    )

    assert inventory["w6_cutover"]["active_owner"] == "package-owned"
    for binding in inventory["cost_rule_bindings"]:
        rule_id = binding["rule_id"]
        for kind, field in (
            ("rule", "rule_path"),
            ("policy", "policy_path"),
            ("remediation", "remediation_path"),
        ):
            resource = resources[f"{kind}:{rule_id}"]
            assert hashlib.sha256(resource.content).hexdigest() == resource.sha256
            assert not (REPO_ROOT / binding[field]).exists()
    assert not (REPO_ROOT / "rule-catalog/workflows/cost-aware-remediation.yaml").exists()


def test_public_facade_builds_a_disabled_generic_core_bundle() -> None:
    archive_sha256 = hashlib.sha256(ARCHIVE).hexdigest()
    bundle = build_cost_governance_bundle(archive_sha256=archive_sha256)

    assert bundle.manifest.extension.version == __version__ == "0.1.1"
    assert bundle.manifest.vertical_id == "cost-governance"
    assert not bundle.descriptor.enabled
    assert bundle.descriptor.default_mode.value == "shadow"
    assert bundle.manifest.required_provider_bindings == ("cost-estimator",)
    assert bundle.manifest.artifact_kind.value == "extension"
    assert bundle.capability_bundle is None

    manager = VerticalPackageManager(
        host_version="0.1.3",
        ontology_release_digest=bundle.manifest.ontology_release_range,
        provider_bindings={"cost-estimator"},
        host_reference_ids={
            "action:remediate.remove-orphan-resource",
            "action:remediate.right-size",
            "action:remediate.set-retention-policy",
            "action:remediate.tag-add",
        },
    )
    installed = manager.install(
        bundle,
        archive=ARCHIVE,
        image_digest=f"sha256:{'f' * 64}",
        verifier=_TrustExactArchive(),
    )

    assert installed.list()[0][1] is ExtensionState.DISABLED
    assert installed.runtime().package_ids() == ()
    assert installed.enable("cost-governance").runtime().package_ids() == ("cost-governance",)


def test_enabled_catalog_materializes_once_through_standard_core_loaders() -> None:
    bundle = build_cost_governance_bundle(archive_sha256=hashlib.sha256(ARCHIVE).hexdigest())
    manager = VerticalPackageManager(
        host_version="0.1.3",
        ontology_release_digest=bundle.manifest.ontology_release_range,
        provider_bindings={"cost-estimator"},
        host_reference_ids={
            "action:remediate.remove-orphan-resource",
            "action:remediate.right-size",
            "action:remediate.set-retention-policy",
            "action:remediate.tag-add",
        },
    ).install(
        bundle,
        archive=ARCHIVE,
        image_digest=f"sha256:{'f' * 64}",
        verifier=_TrustExactArchive(),
    )
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(
        REPO_ROOT / "rule-catalog/action-types",
        schema_registry=registry,
        probes_root=REPO_ROOT / "rule-catalog/probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (REPO_ROOT / "rule-catalog/vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )

    with pytest.raises(VerticalPackageValidationError, match="not active"):
        materialize_cost_governance_catalog(
            manager.runtime(),
            schema_registry=registry,
            action_types=action_types,
            resource_types=resource_types,
        )

    catalog = materialize_cost_governance_catalog(
        manager.enable("cost-governance").runtime(),
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
    )

    assert len(catalog.rules) == 12
    assert len(catalog.policies) == 12
    assert len(catalog.remediations) == 12
    assert len(catalog.workflows) == 1
    assert all(isinstance(rule, Rule) for rule in catalog.rules)
    assert all(isinstance(workflow, Workflow) for workflow in catalog.workflows)
    assert catalog.workflows[0].name == "cost-aware-remediation"
    assert len({rule.id for rule in catalog.rules}) == 12


def test_package_contract_contains_no_authority_grant() -> None:
    bundle = build_cost_governance_bundle(archive_sha256=hashlib.sha256(ARCHIVE).hexdigest())
    manifest = load_resource_manifest()
    forbidden = {
        "can_approve",
        "can_execute",
        "can_promote",
        "grants_authority",
        "mutation_authority",
    }

    assert not {key for key, value in _walk(manifest) if key in forbidden and value}
    assert not any(
        field in forbidden
        for contract in (bundle.manifest, bundle.descriptor)
        for field in contract.__dataclass_fields__
    )


def test_distribution_metadata_and_typed_marker_are_present() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["name"] == "fdai-cost-governance"
    assert project["dependencies"] == ["fdai-core-control-plane==0.1.3"]
    assert (PACKAGE_ROOT / "src/fdai_cost_governance/py.typed").is_file()


def test_package_loader_uses_only_importlib_resources() -> None:
    source = (PACKAGE_ROOT / "src/fdai_cost_governance/resource_loader.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    assert "importlib.resources" in source
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path"
        for node in ast.walk(tree)
    )
