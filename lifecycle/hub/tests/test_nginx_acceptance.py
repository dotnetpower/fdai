"""Synthetic owned-namespace tests, not native AKS ownership or deployment evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_release import NGINX_ACCEPTANCE_SCHEMA

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.domain import Installation, Issued, NoEligibleRelease, NoManagedEntity
from fdai_lifecycle_hub.inventory import release_inventory
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.store import CatalogError, Change, ReleaseStore


def _manifest() -> dict[str, object]:
    return {
        "schema_version": NGINX_ACCEPTANCE_SCHEMA,
        "release_version": "1.5.0",
        "source_commit": "a" * 40,
        "platform_tag": "linux-x86_64",
        "workloads": {"nginx": {"image_digest": "sha256:" + "b" * 64}},
    }


def _change(vendor: ReleaseStore, action: str, **fields: object) -> None:
    command = Change.model_validate(
        {
            "revision": vendor.snapshot()["revision"],
            "confirmation": "1.5.0",
            "reason": "Synthetic nginx input review",
            **fields,
        }
    )
    vendor.change(action, "1.5.0", command, actor="vendor-operator")


@pytest.fixture
def vendor(tmp_path: Path, key: HubSigningKey, now: datetime) -> ReleaseStore:
    vendor = ReleaseStore(tmp_path / "vendor.db", key, clock=lambda: now)
    _change(vendor, "register", manifest=canonical_bytes(_manifest()).decode())
    _change(vendor, "publish")
    return vendor


def _catalog(vendor: ReleaseStore, now: datetime) -> ReleaseCatalog:
    raw, pin = vendor.export()
    return load_pinned_export(raw, expected_sha256=pin, public_key=vendor.key.public_key, now=now)


def _target(installation: Installation) -> Installation:
    core = next(entity for entity in installation.entities if entity.entity_id == "core")
    return replace(
        installation,
        settings=replace(installation.settings, channel="DEV"),
        entities=frozenset({replace(core, entity_id="nginx", kind="nginx-acceptance")}),
        reported=replace(
            installation.reported,
            schema_revision=0,
            entities={"nginx": installation.reported.entities["core"]},
        ),
    )


def test_published_nginx_manifest_reaches_a_signed_narrow_plan(
    vendor: ReleaseStore, installation: Installation, key: HubSigningKey, now: datetime
) -> None:
    admitted = _catalog(vendor, now)
    outcome = plan_next(_target(installation), now, catalog=admitted, key=key)
    assert isinstance(outcome, Issued)
    assert outcome.plan.entity_ids == frozenset({"nginx"})
    assert outcome.plan.capability_ids == ()
    assert outcome.plan.envelope.capability_modes == {}
    assert outcome.plan.envelope.destructive_allowed is False
    key.public_key.verify(outcome.plan.signature, outcome.plan.signed_payload)
    releases = release_inventory(admitted)["releases"]
    assert isinstance(releases, list)
    [inventory] = releases
    assert inventory["images"] == [
        {"section": "workloads", "component": "nginx", "image_digest": "sha256:" + "b" * 64}
    ]


@pytest.mark.parametrize("channel", ["RELEASE_CANDIDATE", "RELEASE"])
def test_vendor_cannot_promote_acceptance_to_production(vendor: ReleaseStore, channel: str) -> None:
    before = vendor.snapshot()
    with pytest.raises(CatalogError, match="restricted to DEV"):
        _change(vendor, "contribute", channel=channel)
    assert vendor.snapshot() == before


def test_pinned_catalog_cannot_smuggle_acceptance_into_another_channel(
    vendor: ReleaseStore, now: datetime
) -> None:
    raw, _ = vendor.export()
    document = json.loads(raw)
    document["channels"]["RELEASE"] = ["1.5.0"]
    forged = canonical_bytes(document)
    with pytest.raises(ValueError, match="restricted to DEV"):
        load_pinned_export(
            forged,
            expected_sha256=hashlib.sha256(forged).hexdigest(),
            public_key=vendor.key.public_key,
            now=now,
        )


def test_normal_fdai_entities_cannot_select_an_nginx_release(
    vendor: ReleaseStore, installation: Installation, key: HubSigningKey, now: datetime
) -> None:
    normal = replace(installation, settings=replace(installation.settings, channel="DEV"))
    outcome = plan_next(normal, now, catalog=_catalog(vendor, now), key=key)
    assert isinstance(outcome, NoEligibleRelease)
    assert outcome.checks[0].blocks[0].reason_code == "nginx_acceptance_entity_required"


def test_nginx_entities_cannot_select_a_full_fdai_release(
    catalog: ReleaseCatalog, installation: Installation, key: HubSigningKey, now: datetime
) -> None:
    runtime_catalog = replace(catalog, channels={"DEV": frozenset(catalog.releases)})
    outcome = plan_next(_target(installation), now, catalog=runtime_catalog, key=key)
    assert isinstance(outcome, NoEligibleRelease)
    assert all(
        check.blocks[0].reason_code == "nginx_acceptance_release_required"
        for check in outcome.checks
    )


def test_nginx_input_does_not_prove_native_ownership(
    vendor: ReleaseStore, installation: Installation, key: HubSigningKey, now: datetime
) -> None:
    target = _target(installation)
    target = replace(
        target,
        entities=frozenset(
            replace(entity, settings=None, ownership=None) for entity in target.entities
        ),
    )
    assert isinstance(
        plan_next(target, now, catalog=_catalog(vendor, now), key=key), NoManagedEntity
    )


def test_acceptance_recall_still_blocks_planning(
    vendor: ReleaseStore, installation: Installation, key: HubSigningKey, now: datetime
) -> None:
    _change(vendor, "recall")
    outcome = plan_next(_target(installation), now, catalog=_catalog(vendor, now), key=key)
    assert isinstance(outcome, NoEligibleRelease)
    assert "release_recalled" in {block.reason_code for block in outcome.checks[0].blocks}


def test_acceptance_database_and_missing_image_checks_are_not_bypassed(
    vendor: ReleaseStore, installation: Installation, key: HubSigningKey, now: datetime
) -> None:
    target = _target(installation)
    for state, expected in (
        (replace(target.reported, schema_revision=15), "schema_revision_outside_tolerated_range"),
        (
            replace(
                target.reported,
                entities={
                    "nginx": replace(
                        target.reported.entities["nginx"], artifact_digests=frozenset()
                    )
                },
            ),
            "artifact_unavailable",
        ),
    ):
        outcome = plan_next(
            replace(target, reported=state), now, catalog=_catalog(vendor, now), key=key
        )
        assert isinstance(outcome, NoEligibleRelease)
        assert expected in {block.reason_code for block in outcome.checks[0].blocks}
