"""Offline synthetic verification of connected Hub-image bootstrap."""

from __future__ import annotations

import json
from base64 import b64encode
from datetime import UTC, datetime, timedelta

import pytest

from fdai_deployment_cli import cli, hub_image_deploy, source_application_inputs
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.hub_image_stage import prepare_host_selection, run_hub_image_stage
from fdai_deployment_cli.hub_image_trust import (
    EXPORT_DOMAIN,
    INVENTORY,
    key_id,
    verify_export,
)
from fdai_deployment_cli.lifecycle_release import parse_lifecycle_release_manifest
from fdai_deployment_cli.runtime_release import RuntimeReleaseError
from fdai_deployment_cli.source_image_stage import SourceImageTarget

COMMIT = "a" * 40
SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def catalog(hub_image_catalog):
    return hub_image_catalog


def verified(catalog, **kwargs):
    raw, signature = catalog.export()
    return verify_export(
        raw,
        signature=signature,
        export_key_id=key_id(catalog.key.public_key()),
        trusted_pem=catalog.pem,
        channel="RELEASE",
        **kwargs,
    )


@pytest.fixture
def selection(hub_image_selection):
    return hub_image_selection


def test_signed_complete_inventory_preserves_optional_backward_compatible_coordinates(catalog):
    release = parse_lifecycle_release_manifest(canonical_bytes(catalog.manifest))
    assert release.to_mapping() == catalog.manifest
    assert set(verified(catalog)["image_sources"]) == INVENTORY
    for component in catalog.manifest["components"].values():
        component.pop("image_ref")
    assert parse_lifecycle_release_manifest(canonical_bytes(catalog.manifest)).components
    with pytest.raises(ValueError, match="signed digest-pinned image_ref"):
        verified(catalog)


@pytest.mark.parametrize(
    "invalid",
    [
        "https://registry.example.com/image@sha256:" + "b" * 64,
        "registry.example.com/image:latest",
        "user:password@registry.example.com/image@sha256:" + "b" * 64,
        "registry.example.com/image@sha256:" + "b" * 64,
    ],
)
def test_signed_registry_ref_must_match_component_digest(catalog, invalid):
    catalog.manifest["components"]["clamav"]["image_ref"] = invalid
    with pytest.raises(RuntimeReleaseError):
        parse_lifecycle_release_manifest(canonical_bytes(catalog.manifest))


@pytest.mark.parametrize(
    "failure",
    [
        "export-signature",
        "missing-signature",
        "manifest-signature",
        "key-id",
        "expired",
        "revision",
        "same-revision",
        "recall",
        "release-lift",
        "capability-recall",
        "source-label",
        "platform",
        "product",
        "inventory",
        "outside-channel",
    ],
)
def test_signed_export_fails_closed(catalog, failure):
    options = {}
    if failure == "expired":
        catalog.document["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    elif failure == "revision":
        options["minimum_revision"] = 5
    elif failure == "same-revision":
        options.update(minimum_revision=4, previous_digest="0" * 64)
    elif failure in {"recall", "release-lift", "capability-recall"}:
        catalog.document["recalls"] = [
            {
                "scope": "capability" if failure == "capability-recall" else "release",
                "target": "example-capability" if failure == "capability-recall" else "1.2.0",
                "sequence": 1,
                "notice_digest": "d" * 64,
                "action": "recall",
            }
        ]
        if failure == "release-lift":
            catalog.document["recalls"].append(
                {
                    "scope": "release",
                    "target": "1.2.0",
                    "sequence": 2,
                    "notice_digest": "e" * 64,
                    "action": "lift",
                    "lifting_release_id": "1.2.0",
                }
            )
    elif failure == "source-label":
        catalog.manifest["release_version"] = "1.3.0"
    elif failure in {"platform", "product"}:
        catalog.manifest["platform_tag" if failure == "platform" else "product"] = (
            "linux-aarch64" if failure == "platform" else "example-product"
        )
    elif failure == "inventory":
        catalog.manifest["components"].pop("pgvector")
    elif failure == "outside-channel":
        catalog.document["channels"]["RELEASE"] = []
    raw, signature = catalog.export()
    if failure == "manifest-signature":
        doc = json.loads(raw)
        doc["releases"]["1.2.0"]["signature"] = b64encode(bytes(64)).decode()
        raw = canonical_bytes(doc)
        signature = b64encode(catalog.key.sign(EXPORT_DOMAIN + raw)).decode()
    if failure == "export-signature":
        signature = b64encode(catalog.key.sign(raw)).decode()
    if failure == "missing-signature":
        signature = ""
    with pytest.raises(ValueError):
        verify_export(
            raw,
            signature=signature,
            export_key_id="wrong" if failure == "key-id" else key_id(catalog.key.public_key()),
            trusted_pem=catalog.pem,
            channel="RELEASE",
            **options,
        )


def test_request_is_stable_minimal_self_reported_and_durable(selection, monkeypatch):
    calls = []

    def request(url, path, *, body):
        calls.append((url, path, json.loads(body)))
        return (
            201,
            {},
            canonical_bytes(
                {
                    **json.loads(body),
                    "status": "requested",
                    "trust": "self-reported",
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
            ),
        )

    monkeypatch.setattr(hub_image_deploy, "hub_request", request)
    result = hub_image_deploy.record_deployment_request(
        selection, subscription_id=SUBSCRIPTION, region="westus2"
    )
    assert result == hub_image_deploy.record_deployment_request(
        selection, subscription_id=SUBSCRIPTION, region="westus2"
    )
    assert len(calls) == 1
    payload = calls[0][2]
    assert set(payload) == {
        "request_id",
        "subscription_id",
        "release_id",
        "channel",
        "region",
        "source_commit",
        "catalog_digest",
    }
    assert payload["request_id"] == canonical_digest(
        {name: value for name, value in payload.items() if name != "request_id"}
    )
    with pytest.raises(ValueError, match="drifted"):
        hub_image_deploy.record_deployment_request(
            selection, subscription_id=SUBSCRIPTION, region="eastus"
        )


def test_uncertain_request_is_not_automatically_retried(selection, monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise ValueError("network uncertainty")

    monkeypatch.setattr(hub_image_deploy, "hub_request", fail)
    for expected in ("network uncertainty", "uncertain outcome"):
        with pytest.raises(ValueError, match=expected):
            hub_image_deploy.record_deployment_request(
                selection, subscription_id=SUBSCRIPTION, region="westus2"
            )
    assert len(calls) == 1


class Registry:
    def __init__(self):
        self.calls = []
        self.refs = {}

    def require_available(self, target):
        self.calls.append(("probe",))

    def build(self, *_args, **_kwargs):
        raise AssertionError("Hub path must never build")

    def import_image(self, target, *, source, image):
        self.calls.append(("import", source, image))
        digest = source.split("@")[1]
        self.refs[image] = digest
        self.refs[image.split(":")[0] + "@" + digest] = digest

    def read_digest(self, target, *, reference):
        self.calls.append(("read", reference))
        return self.refs[reference]


def test_all_seven_images_import_by_signed_pin_and_independent_readback(selection, tmp_path):
    registry = Registry()
    target = SourceImageTarget(SUBSCRIPTION, "crfdaiexample")
    args = {
        "selection": selection,
        "target": target,
        "registry": registry,
        "work_dir": tmp_path / "images",
    }
    receipt = run_hub_image_stage(**args)
    imports = [call for call in registry.calls if call[0] == "import"]
    assert {call[1] for call in imports} == set(selection.image_sources.values())
    assert len(imports) == 7
    assert len([call for call in registry.calls if call[0] == "read"]) == 14
    assert receipt["builder"] == "none"
    assert receipt["image_signature_verified"] is True
    assert receipt["release_signature_verified"] is False
    assert receipt["effect_verified"] is True
    registry.calls.clear()
    assert run_hub_image_stage(**args) == receipt
    assert all(call[0] == "read" for call in registry.calls)
    with pytest.raises(ValueError, match="target, mode or selection"):
        run_hub_image_stage(
            **{**args, "target": SourceImageTarget(SUBSCRIPTION, "crfdaidifferent")}
        )
    first = next(iter(registry.refs))
    registry.refs[first] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="readback differs"):
        run_hub_image_stage(**args)


def test_source_image_artifact_seam_imports_hub_and_never_builds(selection, tmp_path, monkeypatch):
    registry = Registry()
    monkeypatch.setattr(source_application_inputs, "AzureRegistryBuildService", lambda: registry)
    monkeypatch.setattr(
        source_application_inputs,
        "verify_source_snapshot",
        lambda *_args, **_kwargs: {
            "source_commit": COMMIT,
        },
    )
    context = {
        "artifact_source": "hub-signed-images",
        "hub_selection": str(selection.path),
        "hub_selection_digest": selection.digest,
        "source_snapshot": str(tmp_path),
        "source_snapshot_digest": "b" * 64,
        "subscription_id": SUBSCRIPTION,
        "registry_name": "crfdaiexample",
    }
    receipt, updated = source_application_inputs.source_image_import_receipt(
        context=context, work_dir=tmp_path
    )
    assert set(updated["image_refs"]) == INVENTORY
    assert receipt["provenance"] == "hub-signed-images-with-checkout-support"
    assert receipt["hub_selection_digest"] == selection.digest
    assert receipt["release_signature_verified"] is False
    assert receipt["image_signature_verified"] is True


def test_host_retains_exact_selection_and_rejects_mode_drift(selection, tmp_path):
    work = tmp_path / "host"
    work.mkdir(mode=0o700)
    retained = prepare_host_selection(path=selection.path, digest=selection.digest, work_dir=work)
    assert retained.path == work / "hub-selection.json"
    assert retained.digest == selection.digest
    with pytest.raises(ValueError, match="mode cannot change"):
        prepare_host_selection(path=None, digest=None, work_dir=work)
    with pytest.raises(ValueError, match="digest differs"):
        prepare_host_selection(path=selection.path, digest="0" * 64, work_dir=work)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--hub", ".", "--source", "."],
        ["--hub", ".", "--offline-kit", "kit.tar"],
        ["--source", ".", "--hub-url", "https://hub.example.com"],
        ["--offline-kit", "kit.tar", "--hub-channel", "DEV"],
        ["--hub", "."],
        ["--hub", ".", "--hub-url", "", "--hub-public-key", "public.pem"],
        ["--hub", ".", "--hub-channel", "", "--hub-public-key", "public.pem"],
    ],
)
def test_cli_conflicts_or_missing_independent_key_fail_before_azure(arguments, monkeypatch):
    monkeypatch.delenv("FDAI_HUB_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(cli, "ensure_azure_session", lambda: pytest.fail("unexpected Azure call"))
    try:
        code = cli.main(["provision", "azure", *arguments, "--region", "westus2"])
    except SystemExit as error:
        code = error.code
    assert code != 0
