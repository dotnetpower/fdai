"""Regression tests for the OHL scale-out completion evidence validator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/quality/repository/validate-ohl-scale-out-evidence.py"
BUILDER_SCRIPT = ROOT / "scripts/quality/repository/build-ohl-scale-out-evidence-bundle.py"
CONTRACT = json.loads((ROOT / "config/ohl-scale-out-evidence.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_ohl_scale_out_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_ohl_scale_out_bundle", BUILDER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _candidate() -> dict[str, object]:
    manifest = deepcopy(CONTRACT)
    manifest["status"] = "complete"
    manifest["evidence_level"] = "live_execution"
    manifest["residuals"] = []
    manifest["result"] = {
        "status": "verified",
        "source_receipt_digest": None,
        "completed_at": "2026-01-15T00:20:01Z",
    }
    return manifest


def _bundle() -> dict[str, object]:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    correlation_id = "ohl-campaign-correlation"
    target_revision = "vmss-revision-1"
    receipt_kinds = list(CONTRACT["evidence"]["required_receipts"])
    receipts = []
    for index, kind in enumerate(receipt_kinds):
        source = "executor" if kind == "provider_scale_out" else f"observer-{kind}"
        receipt = {
            "kind": kind,
            "evidence_level": "live_execution",
            "authority_class": "protected-runner-observation",
            "source_identity_digest": _digest(source),
            "scope_digest": _digest("one-dedicated-target"),
            "purpose": "OHL scale-out completion",
            "query_version": "v1",
            "event_time": _timestamp(started_at + timedelta(seconds=index)),
            "recorded_at": _timestamp(started_at + timedelta(seconds=index + 1)),
            "freshness_seconds": 1,
            "completeness": True,
            "provenance_digest": _digest(f"receipt-{kind}"),
            "synthetic": False,
            "correlation_id": correlation_id,
            "target_revision": target_revision,
            "verified": True,
        }
        if kind == "graph_shadow_prediction":
            receipt.update(
                {
                    "prediction_digest": _digest("graph-prediction"),
                    "ontology_release_digest": _digest("ontology-release"),
                    "graph_revision": "graph-revision-1",
                    "inventory_generation": "inventory-generation-1",
                    "base_snapshot_digest": _digest("base-snapshot"),
                    "evidence_cutoff": "2026-01-01T00:00:00Z",
                    "horizon_end": "2026-01-01T00:05:00Z",
                    "active_model_refs": ["active-model-1"],
                    "challenger_model_refs": ["challenger-model-1"],
                    "invariant_evidence_digests": [_digest("invariant-evidence")],
                    "mode": "shadow",
                    "execution_authority": False,
                    "complete": True,
                    "truncated": False,
                }
            )
        elif kind == "graph_shadow_outcome":
            receipt.update(
                {
                    "prediction_digest": _digest("graph-prediction"),
                    "observation_digest": _digest("graph-observation"),
                    "observer_identity_digest": _digest(source),
                    "executor_identity_digest": _digest("executor"),
                    "observer_executor_distinct": True,
                    "observed_at": "2026-01-01T00:10:00Z",
                    "status": "closed",
                    "completeness": True,
                    "censoring_refs": [],
                    "evidence_refs": [_digest("graph-evidence")],
                    "active_model_mutated": False,
                    "promotion_applied": False,
                }
            )
        receipts.append(receipt)
    receipt_digests = {receipt["kind"]: receipt["provenance_digest"] for receipt in receipts}
    condition_kinds = {
        "a3e_non_applicability_verified": "a3e_non_applicability",
        "partial_execution_observed": "partial_state_observation",
        "rollback_independently_verified": "independent_recovery",
        "cleanup_verified": "cleanup",
        "graph_prediction_live_and_non_synthetic": "graph_shadow_prediction",
        "graph_outcome_independently_closed": "graph_shadow_outcome",
        "observation_horizon_preserved": "graph_shadow_outcome",
        "recurrence_window_complete": "cleanup",
        "promotion_floor_met": "promotion_floor",
        "zero_policy_escapes": "graph_shadow_outcome",
        "production_graph_provider_bound": "production_graph_provider_binding",
        "production_scale_out_executor_bound": "production_scale_out_executor_binding",
    }
    conditions = {
        condition: receipt_digests[condition_kinds[condition]]
        for condition in CONTRACT["acceptance"]["manifest_complete_requires"]
    }
    samples = []
    for index in range(100):
        event_time = started_at + timedelta(days=14 * index / 99)
        horizon_end = event_time + timedelta(seconds=300)
        observed_at = horizon_end + timedelta(seconds=300)
        predicted = index >= 2
        samples.append(
            {
                "sample_id": f"sample-{index:03d}",
                "prediction_digest": _digest(f"prediction-{index}"),
                "outcome_digest": _digest(f"outcome-{index}"),
                "event_time": _timestamp(event_time),
                "horizon_end": _timestamp(horizon_end),
                "observed_at": _timestamp(observed_at),
                "observation_window_seconds": 60,
                "evidence_level": "live_execution",
                "synthetic": False,
                "complete": True,
                "truncated": False,
                "censored": False,
                "predicted_success": predicted,
                "observed_success": True,
                "policy_escape": False,
                "active_model_mutated": False,
                "promotion_applied": False,
                "observer_identity_digest": _digest("independent-observer"),
                "executor_identity_digest": _digest("executor"),
            }
        )
    return {
        "schema_version": 1,
        "campaign_id": "ohl-campaign-1",
        "correlation_id": correlation_id,
        "target_revision": target_revision,
        "started_at": _timestamp(started_at),
        "recurrence_observed_at": _timestamp(started_at + timedelta(days=14, minutes=20)),
        "receipts": receipts,
        "condition_receipts": conditions,
        "samples": samples,
    }


def _validate(
    validator: ModuleType,
    manifest: dict[str, object],
    bundle: dict[str, object],
) -> list[str]:
    source = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    manifest["result"]["source_receipt_digest"] = hashlib.sha256(source).hexdigest()
    return validator.validate_completion(
        manifest,
        bundle,
        source_receipt_sha256=hashlib.sha256(source).hexdigest(),
    )


def test_accepts_exact_complete_receipt_bundle(validator: ModuleType) -> None:
    assert _validate(validator, _candidate(), _bundle()) == []


def test_accepts_bundle_assembled_by_builder(
    validator: ModuleType,
    builder: ModuleType,
) -> None:
    source = _bundle()
    bundle = builder.build_bundle(
        CONTRACT,
        source["receipts"],
        source["samples"],
        campaign_id=source["campaign_id"],
        correlation_id=source["correlation_id"],
        target_revision=source["target_revision"],
        started_at=source["started_at"],
        recurrence_observed_at=source["recurrence_observed_at"],
    )

    assert _validate(validator, _candidate(), bundle) == []


def test_rejects_arbitrary_manifest_receipt_digest(validator: ModuleType) -> None:
    manifest = _candidate()
    manifest["result"]["source_receipt_digest"] = "a" * 64

    errors = validator.validate_completion(
        manifest,
        _bundle(),
        source_receipt_sha256=_digest("actual-bundle"),
    )

    assert "manifest.result.source_receipt_digest MUST match the exact bundle bytes" in errors


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda bundle: bundle["samples"].pop(),
            "samples MUST contain at least 100 live observations",
        ),
        (
            lambda bundle: bundle["samples"][0].update({"policy_escape": True}),
            "samples[0].policy_escape MUST equal false",
        ),
        (
            lambda bundle: bundle["samples"][0].update({"synthetic": True}),
            "samples[0].synthetic MUST equal false",
        ),
        (
            lambda bundle: bundle["samples"][0].update({"active_model_mutated": True}),
            "samples[0].active_model_mutated MUST equal false",
        ),
        (
            lambda bundle: bundle["samples"][0].update({"promotion_applied": True}),
            "samples[0].promotion_applied MUST equal false",
        ),
        (
            lambda bundle: bundle["samples"][0].update({"complete": False}),
            "samples[0].complete MUST equal true",
        ),
        (
            lambda bundle: bundle["samples"][0].update({"censored": True}),
            "samples[0].censored MUST equal false",
        ),
        (
            lambda bundle: bundle["samples"][2].update({"predicted_success": False}),
            "sample accuracy MUST be at least 0.98",
        ),
        (
            lambda bundle: bundle["samples"][0].update({"horizon_end": "2026-01-01T00:04:59Z"}),
            "samples[0].horizon_end MUST preserve the configured horizon",
        ),
        (
            lambda bundle: bundle["samples"][0].update({"observed_at": "2026-01-01T00:09:59Z"}),
            "samples[0].observed_at MUST follow the telemetry grace period",
        ),
        (
            lambda bundle: bundle["samples"][0].update(
                {
                    "event_time": "2025-12-31T23:59:59Z",
                    "horizon_end": "2026-01-01T00:04:59Z",
                    "observed_at": "2026-01-01T00:09:59Z",
                }
            ),
            "samples[0].event_time MUST not precede the campaign",
        ),
        (
            lambda bundle: bundle["samples"][0].update(
                {"observer_identity_digest": _digest("executor")}
            ),
            "samples[0] observer identity MUST differ from executor identity",
        ),
        (
            lambda bundle: bundle["samples"][0].update(
                {"executor_identity_digest": _digest("forged-executor")}
            ),
            "samples[0].executor_identity_digest MUST match provider_scale_out",
        ),
        (
            lambda bundle: bundle["receipts"].pop(),
            "receipts missing required kind: production_scale_out_executor_binding",
        ),
        (
            lambda bundle: next(
                receipt for receipt in bundle["receipts"] if receipt["kind"] == "rollback"
            ).update({"verified": False}),
            "verified MUST be true",
        ),
        (
            lambda bundle: next(
                receipt for receipt in bundle["receipts"] if receipt["kind"] == "cleanup"
            ).update({"synthetic": True}),
            "synthetic MUST be false",
        ),
        (
            lambda bundle: bundle["receipts"][0].update({"freshness_seconds": 2}),
            "freshness_seconds MUST match its timestamps",
        ),
        (
            lambda bundle: bundle.update({"recurrence_observed_at": "2026-01-14T23:59:59Z"}),
            "bundle.recurrence_observed_at MUST close the full recurrence window",
        ),
    ],
)
def test_rejects_incomplete_or_unsafe_completion_evidence(
    validator: ModuleType,
    mutate: object,
    expected: str,
) -> None:
    bundle = _bundle()
    mutate(bundle)

    errors = _validate(validator, _candidate(), bundle)
    assert any(expected in error for error in errors), errors


def test_rejects_condition_bound_to_wrong_receipt_kind(validator: ModuleType) -> None:
    bundle = _bundle()
    bundle["condition_receipts"]["cleanup_verified"] = bundle["receipts"][0]["provenance_digest"]

    assert "condition_receipts.cleanup_verified MUST reference cleanup" in _validate(
        validator, _candidate(), bundle
    )


@pytest.mark.parametrize(
    ("receipt_kind", "field", "replacement", "expected"),
    [
        (
            "graph_shadow_prediction",
            "active_model_refs",
            None,
            "missing active_model_refs",
        ),
        (
            "graph_shadow_prediction",
            "execution_authority",
            True,
            "graph_shadow_prediction.execution_authority MUST equal false",
        ),
        (
            "graph_shadow_outcome",
            "prediction_digest",
            _digest("wrong-prediction"),
            "graph_shadow_outcome MUST close the graph prediction digest",
        ),
        (
            "graph_shadow_outcome",
            "active_model_mutated",
            True,
            "graph_shadow_outcome.active_model_mutated MUST equal false",
        ),
        (
            "graph_shadow_outcome",
            "promotion_applied",
            True,
            "graph_shadow_outcome.promotion_applied MUST equal false",
        ),
    ],
)
def test_rejects_incomplete_or_unsafe_graph_receipts(
    validator: ModuleType,
    receipt_kind: str,
    field: str,
    replacement: object,
    expected: str,
) -> None:
    bundle = _bundle()
    receipt = next(item for item in bundle["receipts"] if item["kind"] == receipt_kind)
    if replacement is None:
        del receipt[field]
    else:
        receipt[field] = replacement

    errors = _validate(validator, _candidate(), bundle)
    assert any(expected in error for error in errors), errors


@pytest.mark.parametrize(
    "source",
    [
        b'{"schema_version":1,"schema_version":1}',
        b'{"schema_version":NaN}',
    ],
)
def test_rejects_noncanonical_json_inputs(validator: ModuleType, source: bytes) -> None:
    with pytest.raises(ValueError):
        validator._load_json_bytes(source)
