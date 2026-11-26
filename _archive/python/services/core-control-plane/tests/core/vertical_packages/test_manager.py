from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from fdai.core.capability_catalog import ExtensionManifest, ExtensionState
from fdai.core.vertical_packages import (
    VerticalAssetDeclaration,
    VerticalAssetKind,
    VerticalPackageAsset,
    VerticalPackageBundle,
    VerticalPackageLifecycleError,
    VerticalPackageManager,
    VerticalPackageManifest,
    VerticalPackageRuntime,
    VerticalPackageValidationError,
    VerticalProviderDeclaration,
)
from fdai.core.vertical_packages.catalog import _asset_map, _content_by_path
from fdai.core.verticals import VerticalDescriptor
from fdai.shared.contracts.models import Category

ARCHIVE = b"reviewed-wheel"
ARCHIVE_SHA256 = hashlib.sha256(ARCHIVE).hexdigest()
ONTOLOGY_RELEASE = "sha256:" + ("1" * 64)
IMAGE_DIGEST = "sha256:" + ("f" * 64)


class _TrustAll:
    def verify(self, manifest: ExtensionManifest, archive: bytes) -> bool:
        return manifest.archive_sha256 == hashlib.sha256(archive).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _profile(**extra: object) -> bytes:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "profile_id": "test.semantic-profile",
        "ontology_release_digest": ONTOLOGY_RELEASE,
        "safety": {
            "approval_authority": False,
            "execution_authority": False,
            "promotion_authority": False,
        },
    }
    payload.update(extra)
    payload["canonical_sha256"] = "sha256:" + _canonical_digest(payload)
    return json.dumps(payload, indent=2, sort_keys=True).encode()


def _bundle(
    *,
    package_id: str = "test-vertical",
    asset_references: tuple[str, ...] = ("action:remediate.right-size",),
    assets: tuple[VerticalPackageAsset, ...] | None = None,
    profile: bytes | None = None,
    min_host_version: str = "0.1.0",
    ontology_release: str = ONTOLOGY_RELEASE,
    provider_required: bool = True,
    version: str = "1.0.0",
) -> VerticalPackageBundle:
    rule_content = b"""\
schema_version: 2.0.0
id: test.cost-rule
version: 1.0.0
source: azure_advisor
severity: medium
category: cost
resource_type: compute.vm
check_logic:
  kind: rego
  reference: policies/test.cost-rule.rego
remediation:
  template_ref: remediation/test.cost-rule.tftpl
  cost_impact_monthly_usd: 0
remediates: remediate.right-size
provenance:
  source_url: https://example.com/test-rule
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: sha256:0000000000000000000000000000000000000000000000000000000000000000
  license: LicenseRef-reference-only
  redistribution: reference-only
  retrieved_at: "2026-08-28T00:00:00Z"
"""
    policy_content = b"package fdai.test_cost_rule\n\ndefault allow := false\n"
    remediation_content = b'resource "example" "test" {}\n'
    default_asset = VerticalPackageAsset(
        declaration=VerticalAssetDeclaration(
            asset_id="rule:test.cost-rule",
            kind=VerticalAssetKind.RULE,
            resource_path="rules/test.cost-rule.yaml",
            sha256=hashlib.sha256(rule_content).hexdigest(),
            references=(
                *asset_references,
                "policy:test.cost-rule",
                "remediation:test.cost-rule",
            ),
        ),
        content=rule_content,
    )
    default_policy = VerticalPackageAsset(
        declaration=VerticalAssetDeclaration(
            asset_id="policy:test.cost-rule",
            kind=VerticalAssetKind.POLICY,
            resource_path="policies/test.cost-rule.rego",
            sha256=hashlib.sha256(policy_content).hexdigest(),
        ),
        content=policy_content,
    )
    default_remediation = VerticalPackageAsset(
        declaration=VerticalAssetDeclaration(
            asset_id="remediation:test.cost-rule",
            kind=VerticalAssetKind.REMEDIATION,
            resource_path="remediation/test.cost-rule.tftpl",
            sha256=hashlib.sha256(remediation_content).hexdigest(),
        ),
        content=remediation_content,
    )
    selected_assets = assets or (default_asset, default_policy, default_remediation)
    resource_manifest = {
        "schema_version": "1.0.0",
        "package_id": package_id,
        "package_version": version,
        "candidate_state": "inert",
        "assets": [
            {
                "id": asset.declaration.asset_id,
                "kind": asset.declaration.kind.value,
                "path": asset.declaration.resource_path,
                "references": list(asset.declaration.references),
                "sha256": asset.declaration.sha256,
            }
            for asset in selected_assets
        ],
    }
    resource_manifest_bytes = json.dumps(
        resource_manifest,
        indent=2,
        sort_keys=True,
    ).encode()
    selected_profile = profile or _profile()
    profile_data = json.loads(selected_profile)
    providers = (
        (
            VerticalProviderDeclaration(
                binding_id="cost-estimator",
                protocol="fdai.shared.providers.CostEstimator",
            ),
        )
        if provider_required
        else ()
    )
    required_providers = ("cost-estimator",) if provider_required else ()
    extension = ExtensionManifest(
        extension_id=package_id,
        version=version,
        source="image:test-vertical",
        archive_sha256=ARCHIVE_SHA256,
        min_host_version=min_host_version,
    )
    manifest = VerticalPackageManifest(
        extension=extension,
        vertical_id=package_id,
        asset_manifest_sha256=_canonical_digest(resource_manifest),
        ontology_release_range=ontology_release,
        semantic_profile_sha256=profile_data["canonical_sha256"],
        required_provider_bindings=required_providers,
    )
    return VerticalPackageBundle(
        descriptor=VerticalDescriptor(
            vertical_id=package_id,
            display_name="Test vertical",
            category=Category.COST,
            rule_source_ids=(f"package:{package_id}",),
        ),
        manifest=manifest,
        asset_manifest=resource_manifest_bytes,
        semantic_profile=selected_profile,
        assets=selected_assets,
        providers=providers,
    )


def _manager(
    *,
    host_version: str = "0.1.3",
    ontology_release: str = ONTOLOGY_RELEASE,
    providers: tuple[str, ...] = ("cost-estimator",),
    base_runtime: VerticalPackageRuntime | None = None,
) -> VerticalPackageManager:
    return VerticalPackageManager(
        host_version=host_version,
        ontology_release_digest=ontology_release,
        provider_bindings=providers,
        host_reference_ids={
            "action:remediate.right-size",
            "action:remediate.tag-add",
        },
        base_runtime=base_runtime,
    )


def test_catalog_maps_reject_duplicate_asset_and_resource_path_ownership() -> None:
    asset = _bundle().assets[0]
    with pytest.raises(VerticalPackageValidationError, match="duplicate asset ids"):
        _asset_map((asset, asset))

    duplicate_path = replace(
        asset,
        declaration=replace(asset.declaration, asset_id="rule:test.other-rule"),
    )
    with pytest.raises(VerticalPackageValidationError, match="duplicate rule resource path"):
        _content_by_path((asset, duplicate_path), VerticalAssetKind.RULE)


def test_install_rejects_rule_that_violates_catalog_contract() -> None:
    bundle = _bundle()
    rule = bundle.assets[0]
    malformed_content = b"schema_version: 2.0.0\nid: test.cost-rule\n"
    malformed_rule = replace(
        rule,
        declaration=replace(
            rule.declaration,
            sha256=hashlib.sha256(malformed_content).hexdigest(),
        ),
        content=malformed_content,
    )

    with pytest.raises(VerticalPackageValidationError, match="catalog contract"):
        _manager().install(
            _bundle(assets=(malformed_rule, *bundle.assets[1:])),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )


def test_install_is_disabled_then_enable_and_disable_rebuild_atomically() -> None:
    base = _manager()
    installed = base.install(
        _bundle(),
        archive=ARCHIVE,
        image_digest=IMAGE_DIGEST,
        verifier=_TrustAll(),
    )

    assert base.list() == ()
    assert installed.list()[0][1] is ExtensionState.DISABLED
    assert installed.availability("test-vertical").available
    metadata = installed.activation_metadata("test-vertical")
    assert metadata.available is True
    assert metadata.enabled is False
    assert metadata.availability_reasons == ()
    assert metadata.package_version == "1.0.0"
    assert metadata.image_digest == IMAGE_DIGEST
    assert metadata.asset_manifest_digest.startswith("sha256:")
    assert metadata.semantic_profile_digest.startswith("sha256:")
    assert metadata.ontology_release_digest == ONTOLOGY_RELEASE
    assert installed.runtime().package_ids() == ()

    enabled = installed.enable("test-vertical")
    assert installed.runtime().package_ids() == ()
    assert enabled.runtime().package_ids() == ("test-vertical",)
    assert enabled.runtime().asset_ids() == (
        "policy:test.cost-rule",
        "remediation:test.cost-rule",
        "rule:test.cost-rule",
    )
    assert enabled.activation_metadata("test-vertical").available is True
    assert enabled.activation_metadata("test-vertical").enabled is True

    disabled = enabled.disable("test-vertical")
    assert enabled.runtime().package_ids() == ("test-vertical",)
    assert disabled.runtime().package_ids() == ()


def test_enabled_n_minus_one_upgrade_and_rollback_are_atomic_without_replay() -> None:
    original = (
        _manager()
        .install(
            _bundle(version="1.0.0"),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )
        .enable("test-vertical")
    )
    audit_records = ["audit-before-upgrade"]
    action_records = ["action-before-upgrade"]

    upgraded = original.upgrade(
        "test-vertical",
        _bundle(version="1.0.1"),
        archive=ARCHIVE,
        image_digest="sha256:" + ("e" * 64),
        verifier=_TrustAll(),
        expected_current_version="1.0.0",
    )

    assert original.activation_metadata("test-vertical").package_version == "1.0.0"
    assert upgraded.activation_metadata("test-vertical").package_version == "1.0.1"
    assert upgraded.activation_metadata("test-vertical").enabled is True
    assert upgraded.runtime().asset_ids() == (
        "policy:test.cost-rule",
        "remediation:test.cost-rule",
        "rule:test.cost-rule",
    )
    assert audit_records == ["audit-before-upgrade"]
    assert action_records == ["action-before-upgrade"]

    rolled_back = upgraded.rollback(
        "test-vertical",
        expected_current_version="1.0.1",
    )

    assert rolled_back.activation_metadata("test-vertical").package_version == "1.0.0"
    assert rolled_back.activation_metadata("test-vertical").enabled is True
    assert rolled_back.runtime().asset_ids() == (
        "policy:test.cost-rule",
        "remediation:test.cost-rule",
        "rule:test.cost-rule",
    )
    assert audit_records == ["audit-before-upgrade"]
    assert action_records == ["action-before-upgrade"]


def test_disabled_upgrade_stays_disabled_and_disable_rebuild_has_no_assets() -> None:
    installed = _manager().install(
        _bundle(version="1.0.0"),
        archive=ARCHIVE,
        image_digest=IMAGE_DIGEST,
        verifier=_TrustAll(),
    )
    upgraded = installed.upgrade(
        "test-vertical",
        _bundle(version="1.0.1"),
        archive=ARCHIVE,
        image_digest="sha256:" + ("e" * 64),
        verifier=_TrustAll(),
        expected_current_version="1.0.0",
    )

    assert upgraded.activation_metadata("test-vertical").enabled is False
    assert upgraded.runtime().asset_ids() == ()
    enabled = upgraded.enable("test-vertical")
    assert enabled.runtime().asset_ids() == (
        "policy:test.cost-rule",
        "remediation:test.cost-rule",
        "rule:test.cost-rule",
    )
    assert enabled.disable("test-vertical").runtime().asset_ids() == ()


def test_failed_or_non_n_minus_one_upgrade_preserves_active_runtime() -> None:
    current = (
        _manager()
        .install(
            _bundle(version="1.0.0"),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )
        .enable("test-vertical")
    )
    runtime = current.runtime()
    metadata = current.activation_metadata("test-vertical")

    with pytest.raises(VerticalPackageLifecycleError, match="one patch"):
        current.upgrade(
            "test-vertical",
            _bundle(version="1.0.2"),
            archive=ARCHIVE,
            image_digest="sha256:" + ("e" * 64),
            verifier=_TrustAll(),
            expected_current_version="1.0.0",
        )
    with pytest.raises(VerticalPackageValidationError, match="archive digest"):
        current.upgrade(
            "test-vertical",
            _bundle(version="1.0.1"),
            archive=b"damaged",
            image_digest="sha256:" + ("e" * 64),
            verifier=_TrustAll(),
            expected_current_version="1.0.0",
        )

    assert current.runtime() == runtime
    assert current.activation_metadata("test-vertical") == metadata


@pytest.mark.parametrize(
    ("manager", "bundle", "reason"),
    [
        (_manager(host_version="0.1.3"), _bundle(min_host_version="0.2.0"), "host_incompatible"),
        (
            _manager(ontology_release="sha256:" + ("2" * 64)),
            _bundle(),
            "ontology_incompatible",
        ),
        (_manager(providers=()), _bundle(), "missing_provider:cost-estimator"),
    ],
)
def test_install_derives_bounded_unavailable_reasons(
    manager: VerticalPackageManager,
    bundle: VerticalPackageBundle,
    reason: str,
) -> None:
    installed = manager.install(
        bundle,
        archive=ARCHIVE,
        image_digest=IMAGE_DIGEST,
        verifier=_TrustAll(),
    )

    assert installed.availability("test-vertical").reasons == (reason,)
    metadata = installed.activation_metadata("test-vertical")
    assert metadata.available is False
    assert metadata.enabled is False
    assert metadata.availability_reasons == (reason,)
    if reason == "ontology_incompatible":
        assert metadata.ontology_release_digest == "sha256:" + ("2" * 64)
    with pytest.raises(VerticalPackageLifecycleError, match="unavailable"):
        installed.enable("test-vertical")
    assert installed.activation_metadata("test-vertical") == metadata
    assert installed.runtime().package_ids() == ()


def test_package_absence_keeps_base_runtime_healthy() -> None:
    manager = _manager()

    assert manager.availability("cost-governance").reasons == ("package_absent",)
    assert manager.runtime() == VerticalPackageRuntime()


def test_archive_and_asset_digest_failures_leave_prior_manager_unchanged() -> None:
    manager = _manager()
    bundle = _bundle()
    damaged_asset = replace(bundle.assets[0], content=b"changed")
    damaged_bundle = _bundle(assets=(damaged_asset, *bundle.assets[1:]))

    with pytest.raises(VerticalPackageValidationError, match="archive digest"):
        manager.install(
            bundle,
            archive=b"wrong",
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )
    with pytest.raises(VerticalPackageValidationError, match="asset digest mismatch"):
        manager.install(
            damaged_bundle,
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )
    assert manager.list() == ()
    assert manager.runtime().package_ids() == ()


def test_profile_content_and_authority_mutations_are_rejected() -> None:
    manager = _manager()
    profile = json.loads(_profile())
    profile["profile_id"] = "mutated"
    stale_identity = json.dumps(profile, sort_keys=True).encode()

    with pytest.raises(VerticalPackageValidationError, match="profile content mismatch"):
        manager.install(
            _bundle(profile=stale_identity),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )

    authority_profile = json.loads(_profile())
    authority_profile["safety"]["execution_authority"] = True
    authority_profile.pop("canonical_sha256")
    authority_profile["canonical_sha256"] = "sha256:" + _canonical_digest(authority_profile)
    authority_bytes = json.dumps(authority_profile, sort_keys=True).encode()
    with pytest.raises(VerticalPackageValidationError, match="grants authority"):
        manager.install(
            _bundle(profile=authority_bytes),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )
    assert manager.list() == ()


def test_duplicate_ids_digests_and_cross_references_are_rejected() -> None:
    manager = _manager()
    first = _bundle(provider_required=False).assets[0]
    duplicate_id = replace(
        first,
        declaration=replace(
            first.declaration,
            resource_path="rules/duplicate.yaml",
            sha256=hashlib.sha256(b"other").hexdigest(),
        ),
        content=b"other",
    )
    with pytest.raises(VerticalPackageValidationError, match="duplicate vertical asset id"):
        manager.install(
            _bundle(assets=(first, duplicate_id), provider_required=False),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )

    duplicate_digest = replace(
        first,
        declaration=replace(
            first.declaration,
            asset_id="rule:test.second-rule",
            resource_path="rules/test.second-rule.yaml",
        ),
    )
    with pytest.raises(VerticalPackageValidationError, match="duplicate vertical asset digest"):
        manager.install(
            _bundle(assets=(first, duplicate_digest), provider_required=False),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )

    with pytest.raises(VerticalPackageValidationError, match="unknown references"):
        manager.install(
            _bundle(asset_references=("action:unknown",), provider_required=False),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )
    assert manager.list() == ()


def test_install_rejects_collisions_with_disabled_packages_without_mutation() -> None:
    manager = _manager().install(
        _bundle(package_id="first-vertical"),
        archive=ARCHIVE,
        image_digest=IMAGE_DIGEST,
        verifier=_TrustAll(),
    )
    duplicate_digest = _bundle(package_id="second-vertical").assets[0]
    duplicate_digest = replace(
        duplicate_digest,
        declaration=replace(
            duplicate_digest.declaration,
            asset_id="policy:test.second-policy",
            kind=VerticalAssetKind.POLICY,
            resource_path="policies/test.second-policy.rego",
            references=(),
        ),
    )

    with pytest.raises(VerticalPackageValidationError, match="installed asset id"):
        manager.install(
            _bundle(package_id="second-vertical"),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )
    with pytest.raises(VerticalPackageValidationError, match="installed asset digest"):
        manager.install(
            _bundle(
                package_id="second-vertical",
                assets=(duplicate_digest,),
                provider_required=False,
            ),
            archive=ARCHIVE,
            image_digest=IMAGE_DIGEST,
            verifier=_TrustAll(),
        )
    assert manager.list() == (
        (
            "first-vertical",
            ExtensionState.DISABLED,
            manager.availability("first-vertical"),
        ),
    )
    assert manager.runtime() == VerticalPackageRuntime()
