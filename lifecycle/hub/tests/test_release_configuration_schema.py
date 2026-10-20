from __future__ import annotations

import hashlib
import json
from base64 import b64encode
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.domain import Installation, Issued, NoEligibleRelease
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_release_hub.database import releases
from fdai_release_hub.store import Change, ReleaseStore


@pytest.fixture
def vendor(tmp_path: Path, key: HubSigningKey, now: datetime) -> ReleaseStore:
    return ReleaseStore(tmp_path / "vendor.db", key, clock=lambda: now)


@pytest.fixture
def manifest(catalog: ReleaseCatalog, installation: Installation) -> dict:
    document = catalog.releases["1.6.0"].to_mapping()
    document["configuration_schema"] = {
        "format": "fdai.release-configuration-schema.v1",
        "release_version": "1.6.0",
        "schema_sha256": canonical_digest(installation.configuration.schema),
        "keys": dict(installation.configuration.schema),
    }
    return document


def change(vendor: ReleaseStore, action: str, manifest: dict | None = None) -> None:
    vendor.change(
        action,
        "1.6.0",
        Change(
            revision=vendor.snapshot()["revision"],
            confirmation="1.6.0",
            reason="Synthetic schema admission review",
            manifest=canonical_bytes(manifest).decode() if manifest is not None else None,
        ),
    )


def admitted(vendor: ReleaseStore, now: datetime) -> ReleaseCatalog:
    raw, pin = vendor.export()
    return load_pinned_export(raw, expected_sha256=pin, public_key=vendor.key.public_key, now=now)


def test_publication_admission_and_real_planner_consume_bound_schema(
    vendor: ReleaseStore, manifest: dict, installation: Installation, now: datetime
) -> None:
    change(vendor, "register", manifest)
    change(vendor, "publish")
    catalog = admitted(vendor, now)
    release = catalog.releases["1.6.0"]
    schema = release.configuration_schema
    assert schema is not None
    assert schema.release_version == "1.6.0"
    assert schema.digest == canonical_digest(installation.configuration.schema)
    assert schema.to_mapping() == installation.configuration.schema
    detached = schema.to_mapping()
    detached.clear()
    assert schema.to_mapping() == installation.configuration.schema
    assert release.to_mapping() == manifest
    assert release.digest == canonical_digest(manifest)

    target = replace(installation, settings=replace(installation.settings, channel="DEV"))
    outcome = plan_next(target, now, catalog=catalog, key=vendor.key)
    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_digest == release.digest
    assert outcome.plan.configuration_revision_digest == target.configuration.digest

    wrong_schema = json.loads(canonical_bytes(target.configuration.schema))
    wrong_schema["replicas"]["default"] = 99
    mismatched = replace(target, configuration=replace(target.configuration, schema=wrong_schema))
    blocked = plan_next(mismatched, now, catalog=catalog, key=vendor.key)
    assert isinstance(blocked, NoEligibleRelease)
    assert blocked.checks[0].blocks[0].reason_code == "release_configuration_schema_mismatch"


def corrupt(manifest: dict, problem: str) -> None:
    artifact = manifest["configuration_schema"]
    entry = artifact["keys"]["replicas"]
    if problem in {"x-fdai-axis", "x-fdai-owner"}:
        del entry[problem]
    elif problem == "blank-owner":
        entry["x-fdai-owner"] = " "
    elif problem == "unknown-owner":
        entry["x-fdai-owner"] = "unknown"
    elif problem == "unknown-metadata":
        entry["x-fdai-authority"] = True
    elif problem == "unknown-axis":
        entry["x-fdai-axis"] = "unknown"
    elif problem == "authority-axis":
        entry["x-fdai-axis"] = "standing-authority"
    elif problem == "authority-key":
        artifact["keys"]["approval_profile"] = entry
    elif problem == "nested-authority":
        entry["default"] = {"kill_switch": False}
    elif problem == "unknown-artifact-field":
        artifact["production_eligible"] = True
    elif problem == "format":
        artifact["format"] = "fdai.release-configuration-schema.v99"
    elif problem == "version":
        artifact["release_version"] = "1.5.0"
    elif problem == "invalid-version":
        artifact["release_version"] = "latest"
    elif problem == "null":
        manifest["configuration_schema"] = None
        return
    elif problem == "digest":
        artifact["schema_sha256"] = "0" * 64
        return
    else:
        raise AssertionError(problem)
    artifact["schema_sha256"] = canonical_digest(artifact["keys"])


@pytest.mark.parametrize(
    "problem",
    [
        "x-fdai-axis",
        "x-fdai-owner",
        "blank-owner",
        "unknown-owner",
        "unknown-metadata",
        "unknown-axis",
        "authority-axis",
        "authority-key",
        "nested-authority",
        "unknown-artifact-field",
        "format",
        "version",
        "invalid-version",
        "null",
        "digest",
    ],
)
def test_actual_registration_and_independent_admission_reject_invalid_schemas(
    vendor: ReleaseStore, manifest: dict, now: datetime, problem: str
) -> None:
    corrupt(manifest, problem)
    with pytest.raises(ValueError):
        change(vendor, "register", manifest)
    assert vendor.snapshot()["revision"] == 0
    assert vendor.snapshot()["releases"] == []

    # An independently accepted pin and a real signature still cannot waive schema admission.
    raw, _ = vendor.export()
    export = json.loads(raw)
    payload = canonical_bytes(manifest)
    export["releases"]["1.6.0"] = {
        "manifest": payload.decode(),
        "signature": b64encode(vendor.key.sign(payload)).decode(),
    }
    raw = canonical_bytes(export)
    with pytest.raises(ValueError):
        load_pinned_export(
            raw,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            public_key=vendor.key.public_key,
            now=now,
        )


@pytest.mark.parametrize("problem", ["x-fdai-owner", "digest", "version", "valid-draft-tamper"])
def test_publication_revalidates_persisted_draft_before_signing(
    vendor: ReleaseStore, manifest: dict, problem: str
) -> None:
    change(vendor, "register", manifest)
    if problem == "valid-draft-tamper":
        schema = manifest["configuration_schema"]
        schema["keys"]["replicas"]["default"] = 3
        schema["schema_sha256"] = canonical_digest(schema["keys"])
    else:
        corrupt(manifest, problem)
    with vendor.connect() as db:
        db.execute(
            releases.update()
            .where(releases.c.id == "1.6.0")
            .values(manifest=canonical_bytes(manifest).decode())
        )
    with pytest.raises(ValueError):
        change(vendor, "publish")
    snapshot = vendor.snapshot()
    assert snapshot["revision"] == 1
    assert snapshot["releases"][0]["signature"] is None
    assert snapshot["channels"]["DEV"] == []


@pytest.mark.parametrize("attack", ["pin", "signature", "substitute-key", "relabel"])
def test_metadata_never_bypasses_existing_pin_signature_or_version_binding(
    vendor: ReleaseStore, manifest: dict, now: datetime, attack: str
) -> None:
    change(vendor, "register", manifest)
    change(vendor, "publish")
    raw, approved_pin = vendor.export()
    export = json.loads(raw)
    artifact = export["releases"]["1.6.0"]
    if attack == "relabel":
        export["releases"] = {"1.7.0": artifact}
        export["channels"]["DEV"] = ["1.7.0"]
    else:
        modified = json.loads(artifact["manifest"])
        modified["configuration_schema"]["keys"]["replicas"]["default"] = 3
        modified["configuration_schema"]["schema_sha256"] = canonical_digest(
            modified["configuration_schema"]["keys"]
        )
        payload = canonical_bytes(modified)
        artifact["manifest"] = payload.decode()
        if attack == "substitute-key":
            artifact["signature"] = b64encode(Ed25519PrivateKey.generate().sign(payload)).decode()
    raw = canonical_bytes(export)
    expected_error = {
        "pin": "trusted pin",
        "signature": "signature verification",
        "substitute-key": "signature verification",
        "relabel": "exact Release version",
    }[attack]
    with pytest.raises(ValueError, match=expected_error):
        load_pinned_export(
            raw,
            expected_sha256=approved_pin if attack == "pin" else hashlib.sha256(raw).hexdigest(),
            public_key=vendor.key.public_key,
            now=now,
        )


def test_legacy_release_remains_usable_without_new_configuration_capability(
    vendor: ReleaseStore, catalog: ReleaseCatalog, installation: Installation, now: datetime
) -> None:
    change(vendor, "register", catalog.releases["1.6.0"].to_mapping())
    change(vendor, "publish")
    legacy = admitted(vendor, now)
    assert legacy.releases["1.6.0"].configuration_schema is None
    target = replace(installation, settings=replace(installation.settings, channel="DEV"))
    assert isinstance(plan_next(target, now, catalog=legacy, key=vendor.key), Issued)
