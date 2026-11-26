"""Signed manual evidence never substitutes caller claims for trusted source identity."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.core.wara import WaraAssessmentRequest, WaraAssessmentRuntime, WaraScopedResource
from fdai.delivery.wara_manual_evidence import (
    SignedWaraManualEvidenceSource,
    admit_signed_manual_evidence,
    manual_evidence_signing_bytes,
)
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.wara_assessment import load_wara_assessment_catalog

ROOT = Path(__file__).resolve().parents[4]
AT = datetime(2026, 10, 30, tzinfo=UTC)
RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/rg-example/providers/Microsoft.Compute/virtualMachines/vm-example"
)


@pytest.fixture
def assets():
    root = ROOT / "rule-catalog/collected/wara-aprl"
    framework = load_framework_catalog(root, best_practices=(), objective_refs=frozenset())[0]
    catalog, _ = load_wara_assessment_catalog(
        root / "assessment/crosswalk.json",
        root / "assessment/queries.json",
        framework=framework,
        framework_path=root / "azure-wara.json",
    )
    record = next(
        item
        for item in catalog.recommendations
        if item.manual_evidence is not None
        and item.provider_resource_type.casefold() == "microsoft.compute/virtualmachines"
    )
    request = WaraAssessmentRequest(
        assessment_id="wara-assessment:manual-test",
        framework_revision=catalog.source_revision,
        crosswalk_digest=catalog.crosswalk_digest,
        ontology_release="ontology-example",
        inventory_generation="inventory-example",
        workload_id="workload-example",
        resources=(WaraScopedResource(RESOURCE_ID, record.provider_resource_type),),
        evaluated_at=AT,
        recorded_at=AT,
    )
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    trust = {
        "schema_version": "1.0.0",
        "bindings": [
            {
                "key_id": "test-key",
                "producer": record.manual_evidence.authoritative_producer,
                "public_key_base64": base64.b64encode(key.public_key().public_bytes_raw()).decode(),
                "workload_ids": [request.workload_id],
                "valid_from": (AT - timedelta(days=1)).isoformat(),
                "valid_until": (AT + timedelta(days=1)).isoformat(),
            }
        ],
    }
    receipt = {
        "recommendation_id": record.aprl_guid,
        "evidence_ref": "evidence:manual-example",
        "evidence_kind": record.manual_evidence.kind,
        "producer": record.manual_evidence.authoritative_producer,
        "scope_digest": request.scope_digest,
        "source_revision": request.framework_revision,
        "inventory_generation": request.inventory_generation,
        "observed_at": (AT - timedelta(minutes=1)).isoformat(),
        "recorded_at": (AT - timedelta(minutes=1)).isoformat(),
        "evidence_digest": "sha256:" + "a" * 64,
        "freshness_ceiling_seconds": record.manual_evidence.freshness_ceiling_seconds,
        "complete": True,
        "truncated": False,
        "conflicting": False,
        "synthetic": False,
        "provider_error": None,
        "outcome": "satisfied",
    }
    payload = {
        "schema_version": "1.0.0",
        "producer": receipt["producer"],
        "workload_id": request.workload_id,
        "scope_digest": request.scope_digest,
        "framework_revision": request.framework_revision,
        "crosswalk_digest": request.crosswalk_digest,
        "ontology_release": request.ontology_release,
        "inventory_generation": request.inventory_generation,
        "receipts": [receipt],
    }
    return catalog, record, request, key, trust, payload


def _signed(key, payload) -> bytes:
    signature = key.sign(manual_evidence_signing_bytes("test-key", payload))
    return json.dumps(
        {
            "key_id": "test-key",
            "payload": payload,
            "signature_base64": base64.b64encode(signature).decode(),
        }
    ).encode()


def _admit(assets):
    catalog, _, request, key, trust, payload = assets
    return admit_signed_manual_evidence(
        _signed(key, payload),
        trust_body=json.dumps(trust).encode(),
        request=request,
        catalog=catalog,
    )


def test_trusted_exact_scope_manual_receipt_reaches_runtime(assets) -> None:
    catalog, record, request, _, _, _ = assets
    receipts = _admit(assets)
    assert len(receipts) == 1
    assert receipts[0].evidence_ref.startswith("wara-manual:sha256:")
    result = WaraAssessmentRuntime(catalog).assess(replace(request, evidence=receipts))
    control = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)
    assert control.satisfaction.value == "satisfied"
    assert result.execution_authority is False


def test_signed_fallback_is_not_counted_as_automatic_evaluation(assets) -> None:
    catalog, _, request, _, _, payload = assets
    record = next(
        item
        for item in catalog.recommendations
        if item.automation_available
        and item.provider_resource_type.casefold() == "microsoft.compute/virtualmachines"
    )
    payload["receipts"][0].update(
        {
            "recommendation_id": record.aprl_guid,
            "evidence_kind": record.manual_evidence.kind,
            "freshness_ceiling_seconds": record.manual_evidence.freshness_ceiling_seconds,
        }
    )
    result = WaraAssessmentRuntime(catalog).assess(replace(request, evidence=_admit(assets)))
    control = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)
    assert control.satisfaction.value == "satisfied"
    assert "manual_evidence_fallback" in control.limitations
    assert record.automation_available is True
    assert result.execution_authority is False


def test_signed_bundle_accounts_for_all_393_active_receipts_and_rejects_394(assets) -> None:
    catalog, _, _, _, _, payload = assets
    template = payload["receipts"][0]
    payload["receipts"] = [
        {
            **template,
            "recommendation_id": record.aprl_guid,
            "evidence_kind": record.manual_evidence.kind,
            "freshness_ceiling_seconds": record.manual_evidence.freshness_ceiling_seconds,
        }
        for record in catalog.recommendations
    ]
    assert len(_admit(assets)) == 393
    payload["receipts"].append(dict(template))
    with pytest.raises(ValueError, match="schema"):
        _admit(assets)


@pytest.mark.parametrize("change", ["revoked", "wrong_workload", "expired", "unknown_key"])
def test_source_trust_is_not_supplied_by_the_evidence_file(assets, change) -> None:
    _, _, _, _, trust, _ = assets
    binding = trust["bindings"][0]
    if change == "revoked":
        binding["revoked"] = True
    elif change == "wrong_workload":
        binding["workload_ids"] = ["workload-other"]
    elif change == "expired":
        binding["valid_until"] = (AT - timedelta(seconds=1)).isoformat()
    else:
        binding["key_id"] = "key-other"
    with pytest.raises(ValueError, match="WARA manual evidence"):
        _admit(assets)


@pytest.mark.parametrize(
    "field",
    [
        "scope_digest",
        "framework_revision",
        "crosswalk_digest",
        "ontology_release",
        "inventory_generation",
    ],
)
def test_signed_receipt_cannot_be_replayed_across_assessment_pins(assets, field) -> None:
    assets[-1][field] = "different-pin"
    with pytest.raises(ValueError, match="current assessment"):
        _admit(assets)


def test_receipt_identity_retains_the_exact_installed_trust_binding(assets) -> None:
    first = _admit(assets)[0]
    assets[-2]["bindings"][0]["valid_until"] = (AT + timedelta(days=2)).isoformat()
    second = _admit(assets)[0]
    assert first.evidence_ref != second.evidence_ref
    assert first.evidence_digest == second.evidence_digest


@pytest.mark.parametrize("change", ["string_boolean", "naive_time", "unknown_field", "duplicate"])
def test_signed_malformed_or_duplicate_receipts_are_rejected(assets, change) -> None:
    payload = assets[-1]
    receipt = payload["receipts"][0]
    if change == "string_boolean":
        receipt["complete"] = "true"
    elif change == "naive_time":
        receipt["observed_at"] = "2026-10-30T00:00:00"
    elif change == "unknown_field":
        receipt["execution_authority"] = True
    else:
        payload["receipts"].append(dict(receipt))
    with pytest.raises(ValueError, match="WARA manual evidence"):
        _admit(assets)


def test_tampering_is_not_hidden_by_a_matching_content_digest(assets) -> None:
    catalog, _, request, key, trust, payload = assets
    envelope = json.loads(_signed(key, payload))
    envelope["payload"]["receipts"][0]["outcome"] = "failed"
    with pytest.raises(ValueError, match="signature"):
        admit_signed_manual_evidence(
            json.dumps(envelope).encode(),
            trust_body=json.dumps(trust).encode(),
            request=request,
            catalog=catalog,
        )


@pytest.mark.parametrize("field", ["synthetic", "conflicting", "truncated"])
def test_authenticity_never_upgrades_inadmissible_evidence(assets, field) -> None:
    catalog, record, request, _, _, payload = assets
    payload["receipts"][0][field] = True
    result = WaraAssessmentRuntime(catalog).assess(replace(request, evidence=_admit(assets)))
    control = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)
    assert control.satisfaction.value == "unknown"


async def test_file_source_reads_only_the_configured_signed_bundle(assets, tmp_path) -> None:
    catalog, _, request, key, trust, payload = assets
    evidence_file = tmp_path / "evidence.json"
    trust_file = tmp_path / "trust.json"
    evidence_file.write_bytes(_signed(key, payload))
    trust_file.write_text(json.dumps(trust))
    source = SignedWaraManualEvidenceSource(evidence_file=evidence_file, trust_file=trust_file)
    assert await source.read(request, catalog) == _admit(assets)
