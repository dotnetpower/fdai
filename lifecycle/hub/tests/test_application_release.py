"""Synthetic package admission; no runtime ownership or Azure deployment is inferred."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_release import (
    APPLICATION_COMPONENT_RELEASE_SCHEMA,
    APPLICATION_RELEASE_SCHEMA,
)
from fdai_deployment_cli.runtime_release import RuntimeReleaseError

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.domain import Installation, Issued, NoEligibleRelease, NoManagedEntity
from fdai_lifecycle_hub.execution_settings import ApplicationBindingRequest, settings_digest
from fdai_lifecycle_hub.inventory import release_inventory
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.schemas import settings_json
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore
from fdai_release_hub.store import CatalogError, Change, ReleaseStore


def manifest(product: str = "example-web") -> dict[str, object]:
    return {
        "schema_version": APPLICATION_RELEASE_SCHEMA,
        "product": product,
        "release_version": "1.5.0",
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "workloads": {"frontend": {"image_digest": "sha256:" + "b" * 64}},
    }


def change(vendor: ReleaseStore, action: str, **fields: object) -> None:
    command = Change.model_validate(
        {
            "revision": vendor.snapshot()["revision"],
            "confirmation": "1.5.0",
            "reason": "Synthetic application package review",
            **fields,
        }
    )
    vendor.change(action, "1.5.0", command, actor="vendor-operator")


def publish(
    tmp_path: Path, key: HubSigningKey, now: datetime, product: str = "example-web"
) -> ReleaseStore:
    vendor = ReleaseStore(tmp_path / "vendor.db", key, clock=lambda: now)
    change(vendor, "register", manifest=canonical_bytes(manifest(product)).decode())
    change(vendor, "publish")
    return vendor


def catalog_from(vendor: ReleaseStore, now: datetime) -> ReleaseCatalog:
    raw, pin = vendor.export()
    return load_pinned_export(raw, expected_sha256=pin, public_key=vendor.key.public_key, now=now)


def target(installation: Installation, product: str | None = "example-web") -> Installation:
    entity = next(entity for entity in installation.entities if entity.entity_id == "core")
    return replace(
        installation,
        settings=replace(installation.settings, channel="DEV", product=product),
        entities=frozenset({replace(entity, entity_id="frontend", kind="application")}),
        reported=replace(
            installation.reported,
            schema_revision=0,
            entities={"frontend": installation.reported.entities["core"]},
        ),
    )


@pytest.mark.parametrize("product", ["example-web", "example-api", "fdai"])
def test_publication_import_and_signed_plan_are_application_neutral(
    tmp_path: Path, key: HubSigningKey, now: datetime, installation: Installation, product: str
) -> None:
    vendor = publish(tmp_path, key, now, product)
    admitted = catalog_from(vendor, now)
    outcome = plan_next(target(installation, product), now, catalog=admitted, key=key)
    assert isinstance(outcome, Issued)
    assert outcome.plan.entity_ids == frozenset({"frontend"})
    assert outcome.plan.capability_ids == ()
    assert outcome.plan.envelope.capability_modes == {}
    assert outcome.plan.envelope.destructive_allowed is False
    key.public_key.verify(outcome.plan.signature, outcome.plan.signed_payload)
    releases = release_inventory(admitted)["releases"]
    assert isinstance(releases, list)
    [inventory] = releases
    assert inventory["product"] == product
    assert inventory["images"] == [
        {"section": "workloads", "component": "frontend", "image_digest": "sha256:" + "b" * 64}
    ]
    # Channel names do not encode an application's identity or grant execution authority.
    change(vendor, "contribute", channel="RELEASE_CANDIDATE")
    change(vendor, "contribute", channel="RELEASE")
    assert "1.5.0" in catalog_from(vendor, now).channels["RELEASE"]


@pytest.mark.parametrize("product", ["example-web", "example-worker", "fdai"])
def test_component_release_uses_existing_publication_pin_and_planning_path(
    tmp_path: Path, key: HubSigningKey, now: datetime, installation: Installation, product: str
) -> None:
    document = manifest(product)
    document.pop("workloads")
    document.update(
        schema_version=APPLICATION_COMPONENT_RELEASE_SCHEMA,
        components={"frontend": {"image_digest": "sha256:" + "b" * 64}},
    )
    vendor = ReleaseStore(tmp_path / "vendor.db", key, clock=lambda: now)
    change(vendor, "register", manifest=canonical_bytes(document).decode())
    change(vendor, "publish")
    catalog = catalog_from(vendor, now)
    outcome = plan_next(target(installation, product), now, catalog=catalog, key=key)
    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_digest == canonical_digest(document)
    key.public_key.verify(outcome.plan.signature, outcome.plan.signed_payload)
    [inventory] = release_inventory(catalog)["releases"]
    assert inventory["images"] == [
        {"section": "components", "component": "frontend", "image_digest": "sha256:" + "b" * 64}
    ]
    change(vendor, "recall")
    recalled = plan_next(
        target(installation, product), now, catalog=catalog_from(vendor, now), key=key
    )
    assert isinstance(recalled, NoEligibleRelease)
    assert "release_recalled" in {block.reason_code for block in recalled.checks[0].blocks}


@pytest.mark.parametrize("product", [None, "different-application"])
def test_package_cannot_choose_its_own_installation_binding(
    tmp_path: Path,
    key: HubSigningKey,
    now: datetime,
    installation: Installation,
    product: str | None,
) -> None:
    catalog = catalog_from(publish(tmp_path, key, now), now)
    outcome = plan_next(target(installation, product), now, catalog=catalog, key=key)
    assert isinstance(outcome, NoEligibleRelease)
    assert outcome.checks[0].blocks[0].reason_code == "release_product_mismatch"


def test_application_binding_never_falls_back_to_legacy_inventory(
    catalog: ReleaseCatalog, key: HubSigningKey, now: datetime, installation: Installation
) -> None:
    installation = replace(
        installation, settings=replace(installation.settings, product="example-web")
    )
    outcome = plan_next(installation, now, catalog=catalog, key=key)
    assert isinstance(outcome, NoEligibleRelease)
    assert all(
        check.blocks[0].reason_code == "release_product_mismatch" for check in outcome.checks
    )


def test_package_identity_and_schema_do_not_prove_ownership(
    tmp_path: Path, key: HubSigningKey, now: datetime, installation: Installation
) -> None:
    installation = target(installation)
    installation = replace(
        installation,
        entities=frozenset(
            replace(entity, settings=None, ownership=None) for entity in installation.entities
        ),
    )
    assert isinstance(
        plan_next(
            installation,
            now,
            catalog=catalog_from(publish(tmp_path, key, now), now),
            key=key,
        ),
        NoManagedEntity,
    )


def test_recall_and_artifact_and_schema_gates_remain_active(
    tmp_path: Path, key: HubSigningKey, now: datetime, installation: Installation
) -> None:
    vendor = publish(tmp_path, key, now)
    admitted = catalog_from(vendor, now)
    installation = target(installation)
    for reported, expected in (
        (
            replace(installation.reported, schema_revision=15),
            "schema_revision_outside_tolerated_range",
        ),
        (
            replace(
                installation.reported,
                entities={
                    "frontend": replace(
                        installation.reported.entities["frontend"], artifact_digests=frozenset()
                    )
                },
            ),
            "artifact_unavailable",
        ),
    ):
        outcome = plan_next(
            replace(installation, reported=reported), now, catalog=admitted, key=key
        )
        assert isinstance(outcome, NoEligibleRelease)
        assert expected in {block.reason_code for block in outcome.checks[0].blocks}
    change(vendor, "recall")
    outcome = plan_next(installation, now, catalog=catalog_from(vendor, now), key=key)
    assert isinstance(outcome, NoEligibleRelease)
    assert "release_recalled" in {block.reason_code for block in outcome.checks[0].blocks}


def test_duplicate_keys_and_version_relabeling_are_rejected_before_publication(
    tmp_path: Path, key: HubSigningKey, now: datetime
) -> None:
    vendor = ReleaseStore(tmp_path / "vendor.db", key, clock=lambda: now)
    original = canonical_bytes(manifest()).decode()
    duplicated = original[:-1] + ',"product":"other"}'
    with pytest.raises(RuntimeReleaseError):
        change(vendor, "register", manifest=duplicated)
    with pytest.raises(CatalogError, match="version"):
        change(vendor, "register", manifest=original.replace("1.5.0", "1.6.0"))
    assert vendor.snapshot()["releases"] == []


@pytest.mark.parametrize("count", [1_000, 180_000])
def test_unicode_configuration_defaults_are_readable_after_publication_or_rejected_atomically(
    tmp_path: Path, key: HubSigningKey, now: datetime, count: int
) -> None:
    schema = {
        "label": {
            "default": "가" * count,
            "x-fdai-axis": "installation-path",
            "x-fdai-owner": "customer",
        }
    }
    document = {
        **manifest(),
        "configuration_schema": {
            "format": "fdai.release-configuration-schema.v1",
            "release_version": "1.5.0",
            "schema_sha256": canonical_digest(schema),
            "keys": schema,
        },
    }
    raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    assert len(raw) < 1_048_576
    vendor = ReleaseStore(tmp_path / "vendor.db", key, clock=lambda: now)
    if count == 180_000:
        assert len(canonical_bytes(document)) > 1_048_576
        before = vendor.snapshot()
        with pytest.raises(RuntimeReleaseError):
            change(vendor, "register", manifest=raw.decode("utf-8"))
        assert vendor.snapshot() == before
    else:
        change(vendor, "register", manifest=raw.decode("utf-8"))
        change(vendor, "publish")
        assert catalog_from(vendor, now).releases["1.5.0"].to_mapping() == document


def test_application_binding_survives_store_reopen(
    hub_store: HubStore,
    installation: Installation,
    enroll: Callable[[HubStore, Installation], None],
    now: datetime,
) -> None:
    settings = replace(installation.settings, product="example-web")
    raw = settings_json.dump_json(settings)
    assert settings_json.validate_json(raw).product == "example-web"
    assert (
        settings_json.validate_python(
            {**settings_json.dump_python(settings, mode="json"), "product": None}
        ).product
        is None
    )
    enroll(hub_store, installation)
    digest = settings_digest(installation.settings)
    hub_store.bind_application(
        installation.installation_id,
        ApplicationBindingRequest(
            request_id=UUID(int=1),
            expected_settings_digest=digest,
            product="example-web",
            reason_code="application_package_test",
            confirmation=f"bind application {installation.installation_id} example-web {digest}",
        ),
        operator="operator",
        now=now,
    )
    assert (
        HubStore(hub_store.engine).load(installation.installation_id).settings.product
        == "example-web"
    )
