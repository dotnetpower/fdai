"""Regression tests for sanitized T2 startup-proof evidence."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deployment" / "azure" / "t2_startup_proof_evidence.py"
SCHEMA = ROOT / "config" / "t2-startup-proof-evidence.schema.json"
SOURCE_REVISION = "1" * 40
DIGEST = f"sha256:{'a' * 64}"
PROOF_ID = "b" * 32


@pytest.fixture(scope="module")
def evidence_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("t2_startup_proof_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _report(*, reuse_count: int = 2) -> dict[str, object]:
    started_at = datetime(2026, 9, 12, 1, 0, tzinfo=UTC)
    sampled_at = started_at + timedelta(seconds=10)
    first_reused_at = started_at + timedelta(minutes=5)
    latest_reused_at = started_at + timedelta(minutes=10)
    return {
        "generated_at": _timestamp(latest_reused_at + timedelta(seconds=1)),
        "decision": "ready",
        "results": [
            {
                "probe_id": "model.cross-check.0.0",
                "status": "passed",
                "observed_at": _timestamp(latest_reused_at),
                "expires_at": _timestamp(latest_reused_at + timedelta(minutes=5)),
                "latency_ms": 1.0,
                "failure_class": None,
                "evidence": {
                    "sampled": False,
                    "previously_proven": True,
                    "proof_id": PROOF_ID,
                    "proof_started_at_unix_ms": int(started_at.timestamp() * 1000),
                    "proof_sampled_at_unix_ms": int(sampled_at.timestamp() * 1000),
                    "first_reused_at_unix_ms": int(first_reused_at.timestamp() * 1000),
                    "latest_reused_at_unix_ms": int(latest_reused_at.timestamp() * 1000),
                    "reuse_count": reuse_count,
                },
                "model_evidence": {
                    "sample_count": 2,
                    "total_latency_ms": [100.0, 120.0],
                    "structured_output_proven": True,
                },
            }
        ],
        "missing_probe_ids": [],
        "stale_probe_ids": [],
        "authority_ceilings": {"t2.cross-check.0.0": "deployment"},
        "decision_evidence_rejection_reasons": [],
    }


def _invocations(*, additional: bool = False, priced: bool = True) -> list[dict[str, object]]:
    values = [
        {
            "occurred_at": datetime(2026, 9, 12, 1, 0, 4, tzinfo=UTC),
            "correlation_id": "startup-readiness:model.cross-check.0.0",
            "capability_id": "t2.reasoner.primary",
            "model_key": "deployment-private-name",
            "mode": "enforce",
            "usage_scope": "control_plane",
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "cost": Decimal("0.0012") if priced else None,
            "currency": "USD" if priced else None,
        },
        {
            "occurred_at": datetime(2026, 9, 12, 1, 0, 8, tzinfo=UTC),
            "correlation_id": "startup-readiness:model.cross-check.0.0",
            "capability_id": "t2.reasoner.primary",
            "model_key": "deployment-private-name",
            "mode": "enforce",
            "usage_scope": "control_plane",
            "prompt_tokens": 110,
            "completion_tokens": 25,
            "cost": Decimal("0.0014") if priced else None,
            "currency": "USD" if priced else None,
        },
    ]
    if additional:
        values.append(
            {
                **values[-1],
                "occurred_at": datetime(2026, 9, 12, 1, 6, tzinfo=UTC),
            }
        )
    return values


def _build(evidence_module: ModuleType, **overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "source_revision": SOURCE_REVISION,
        "image_digest": DIGEST,
        "revision_ref_digest": DIGEST,
        "replica_ref_digest": DIGEST,
        "source_identity_digest": DIGEST,
        "environment": "dev",
        "workflow_run_id": 123,
        "workflow_run_attempt": 1,
        "captured_at": datetime(2026, 9, 12, 1, 10, 2, tzinfo=UTC),
        "revision_created_at": datetime(2026, 9, 12, 0, 59, tzinfo=UTC),
    }
    arguments.update(overrides)
    return evidence_module.build_t2_startup_proof_evidence(
        _report(),
        _invocations(),
        **arguments,
    )


def test_builds_sanitized_evidence_for_two_reuses(evidence_module: ModuleType) -> None:
    receipt = _build(evidence_module)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)
    assert receipt["candidate_count"] == 1
    candidate = receipt["candidates"][0]
    assert candidate["sample_count"] == 2
    assert candidate["reuse_count"] == 2
    assert candidate["metered_invocation_count"] == 2
    assert candidate["additional_invocation_count"] == 0
    assert candidate["total_tokens"] == 255
    assert candidate["total_cost"] == "0.0026"
    assert candidate["initial_sampled"] is True
    assert candidate["current_sampled"] is False
    assert candidate["previously_proven"] is True
    assert "deployment-private-name" not in str(receipt)
    assert receipt["synthetic"] is False
    assert receipt["execution_authority"] is False


def test_schema_rejects_unreviewed_raw_identity_fields(evidence_module: ModuleType) -> None:
    receipt = _build(evidence_module)
    receipt["subscription_id"] = "00000000-0000-0000-0000-000000000000"
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


def test_rejects_fewer_than_two_reuses(evidence_module: ModuleType) -> None:
    with pytest.raises(evidence_module.T2StartupProofEvidencePendingError, match="only 1"):
        evidence_module.build_t2_startup_proof_evidence(
            _report(reuse_count=1),
            _invocations(),
            source_revision=SOURCE_REVISION,
            image_digest=DIGEST,
            revision_ref_digest=DIGEST,
            replica_ref_digest=DIGEST,
            source_identity_digest=DIGEST,
            environment="dev",
            workflow_run_id=123,
            workflow_run_attempt=1,
            captured_at=datetime(2026, 9, 12, 1, 10, 2, tzinfo=UTC),
            revision_created_at=datetime(2026, 9, 12, 0, 59, tzinfo=UTC),
        )


def test_rejects_an_additional_model_invocation(evidence_module: ModuleType) -> None:
    with pytest.raises(evidence_module.T2StartupProofEvidenceError, match="invocation count"):
        evidence_module.build_t2_startup_proof_evidence(
            _report(),
            _invocations(additional=True),
            source_revision=SOURCE_REVISION,
            image_digest=DIGEST,
            revision_ref_digest=DIGEST,
            replica_ref_digest=DIGEST,
            source_identity_digest=DIGEST,
            environment="dev",
            workflow_run_id=123,
            workflow_run_attempt=1,
            captured_at=datetime(2026, 9, 12, 1, 10, 2, tzinfo=UTC),
            revision_created_at=datetime(2026, 9, 12, 0, 59, tzinfo=UTC),
        )


def test_rejects_incomplete_cost_metering(evidence_module: ModuleType) -> None:
    with pytest.raises(evidence_module.T2StartupProofEvidenceError, match="cost is incomplete"):
        evidence_module.build_t2_startup_proof_evidence(
            _report(),
            _invocations(priced=False),
            source_revision=SOURCE_REVISION,
            image_digest=DIGEST,
            revision_ref_digest=DIGEST,
            replica_ref_digest=DIGEST,
            source_identity_digest=DIGEST,
            environment="dev",
            workflow_run_id=123,
            workflow_run_attempt=1,
            captured_at=datetime(2026, 9, 12, 1, 10, 2, tzinfo=UTC),
            revision_created_at=datetime(2026, 9, 12, 0, 59, tzinfo=UTC),
        )


def test_rejects_zero_token_usage(evidence_module: ModuleType) -> None:
    invocations = _invocations()
    invocations[0]["prompt_tokens"] = 0
    invocations[0]["completion_tokens"] = 0

    with pytest.raises(evidence_module.T2StartupProofEvidenceError, match="usage is unavailable"):
        evidence_module.build_t2_startup_proof_evidence(
            _report(),
            invocations,
            source_revision=SOURCE_REVISION,
            image_digest=DIGEST,
            revision_ref_digest=DIGEST,
            replica_ref_digest=DIGEST,
            source_identity_digest=DIGEST,
            environment="dev",
            workflow_run_id=123,
            workflow_run_attempt=1,
            captured_at=datetime(2026, 9, 12, 1, 10, 2, tzinfo=UTC),
            revision_created_at=datetime(2026, 9, 12, 0, 59, tzinfo=UTC),
        )


def test_rejects_a_stale_or_predeployment_proof(evidence_module: ModuleType) -> None:
    with pytest.raises(evidence_module.T2StartupProofEvidenceError, match="not fresh"):
        _build(evidence_module, maximum_proof_age_seconds=60)

    with pytest.raises(evidence_module.T2StartupProofEvidenceError, match="predates"):
        _build(
            evidence_module,
            revision_created_at=datetime(2026, 9, 12, 1, 0, 1, tzinfo=UTC),
        )
