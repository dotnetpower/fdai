"""Shared ARB readiness and runtime gate evaluation."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.core.architecture_review import (
    ArchitectureReviewProductionGateEvaluator,
    ProductionEvidenceAttestation,
    ProductionEvidenceBinding,
    evaluate_readiness,
    validate_contract,
)

_ROOT = Path(__file__).resolve().parents[5]
_MANIFEST = _ROOT / "config" / "architecture-review.yaml"
_EVIDENCE_BODY = b'{"status":"passed"}'
_EVALUATED_AT = datetime(2026, 8, 29, tzinfo=UTC)


def _manifest() -> dict[str, object]:
    raw = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _production_ready_manifest() -> dict[str, object]:
    raw = deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["design_review_status"] = "approved"
    review["production_approval_status"] = "ready"
    for artifact in review["artifacts"]:
        assert isinstance(artifact, dict)
        if artifact["required_for"] == "production":
            artifact["status"] = "ready"
    review["blockers"] = [
        {
            "id": "ARB-READY",
            "severity": "low",
            "status": "resolved",
            "owner_slot": "architecture-owner",
            "resolution": "Tracked elsewhere.",
        }
    ]
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    gate["required_owner_slots"] = ["security-owner"]
    gate["owner_bindings"] = {
        "security-owner": {
            "subject": "group:security-reviewers",
            "escalation": "security-oncall",
        }
    }
    gate["required_evidence"] = ["network-data-flow-validation"]
    gate["evidence_bindings"] = {
        "network-data-flow-validation": {
            "uri": "evidence://network-data-flow-validation",
            "sha256": hashlib.sha256(_EVIDENCE_BODY).hexdigest(),
            "scope_ref": "scope:example-production",
            "revision": "revision:example-1",
            "approved_by": "group:security-reviewers",
            "approved_at": "2026-08-28T00:00:00Z",
            "expires_at": "2099-07-13T00:00:00Z",
            "freshness_seconds": 604800,
        }
    }
    return raw


def _attestation(**overrides: object) -> ProductionEvidenceAttestation:
    values: dict[str, object] = {
        "uri": "evidence://network-data-flow-validation",
        "body": _EVIDENCE_BODY,
        "scope_ref": "scope:example-production",
        "revision": "revision:example-1",
        "observed_at": datetime(2026, 8, 28, tzinfo=UTC),
        "authorized_approvers": ("group:security-reviewers",),
        "authentication_ref": "auth:provider-readback-1",
    }
    values.update(overrides)
    return ProductionEvidenceAttestation(**values)


def test_upstream_structure_is_valid_but_production_is_blocked() -> None:
    report = evaluate_readiness(_manifest(), repo_root=_ROOT)

    assert report.structure_valid is True
    assert report.production_ready is False
    assert any("missing owner bindings" in failure for failure in report.failures)


def test_malformed_manifest_is_structurally_unhealthy() -> None:
    raw = deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["design_review_status"] = "unknown"

    report = evaluate_readiness(raw, repo_root=_ROOT)

    assert report.structure_valid is False
    assert report.production_ready is False
    assert report.failures == ("design_review_status is invalid",)


def test_accepted_critical_blocker_requires_complete_risk_or_exception_contract() -> None:
    raw = _production_ready_manifest()
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["blockers"] = [
        {
            "id": "ARB-009",
            "severity": "critical",
            "status": "accepted",
            "owner_slot": "security-owner",
            "resolution": "Accepted temporarily.",
        }
    ]

    report = evaluate_readiness(raw, repo_root=_ROOT)

    assert report.structure_valid is False
    assert report.production_ready is False
    assert report.failures == ("blocker ARB-009.acceptance must be a mapping",)


def test_accepted_critical_blocker_requires_registered_owner_slot() -> None:
    raw = _production_ready_manifest()
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["blockers"] = [
        {
            "id": "ARB-009A",
            "severity": "critical",
            "status": "accepted",
            "owner_slot": "privacy-owner",
            "resolution": "Accepted temporarily.",
            "acceptance": {
                "kind": "risk",
                "mitigation": "Scope the data path.",
                "residual_risk": "One unreviewed privacy edge remains.",
                "reviewed_by": "group:privacy-reviewers",
                "review_date": "2099-08-01T00:00:00Z",
                "evidence": ["docs/roadmap/architecture/security-and-identity.md"],
            },
        }
    ]

    report = evaluate_readiness(raw, repo_root=_ROOT)

    assert report.structure_valid is False
    assert report.production_ready is False
    assert report.failures == (
        "blocker ARB-009A accepted critical/high status requires a registered owner slot",
    )


def test_production_ready_requires_current_accepted_risk_review() -> None:
    raw = _production_ready_manifest()
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["blockers"] = [
        {
            "id": "ARB-010",
            "severity": "high",
            "status": "accepted",
            "owner_slot": "security-owner",
            "resolution": "Accepted with review.",
            "acceptance": {
                "kind": "risk",
                "mitigation": "Keep the temporary network rule scoped.",
                "residual_risk": "Outbound exposure remains possible.",
                "reviewed_by": "group:security-reviewers",
                "review_date": "2026-08-01T00:00:00Z",
                "evidence": ["docs/roadmap/architecture/security-and-identity.md"],
            },
        }
    ]

    with pytest.raises(ValueError, match="accepted risk review is stale"):
        validate_contract(
            raw,
            repo_root=_ROOT,
            require_production_ready=True,
            evaluated_at=datetime(2026, 8, 2, tzinfo=UTC),
        )


def test_production_ready_requires_current_accepted_exception_window() -> None:
    raw = _production_ready_manifest()
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["blockers"] = [
        {
            "id": "ARB-011",
            "severity": "critical",
            "status": "accepted",
            "owner_slot": "security-owner",
            "resolution": "Temporary exception.",
            "acceptance": {
                "kind": "exception",
                "scope": "One staging subnet.",
                "reason": "Allow a bounded migration window.",
                "compensating_controls": "Alert on every outbound flow.",
                "approved_by": "group:security-reviewers",
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-08-03T00:00:00Z",
                "audit_ref": "audit:arb-011",
            },
        }
    ]

    with pytest.raises(ValueError, match="accepted exception is not currently effective"):
        validate_contract(
            raw,
            repo_root=_ROOT,
            require_production_ready=True,
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )


async def test_runtime_gate_fails_closed_for_blocked_or_unknown_gate() -> None:
    evaluator = ArchitectureReviewProductionGateEvaluator(
        manifest_path=_MANIFEST,
        repo_root=_ROOT,
    )

    assert (
        await evaluator.evaluate(
            rule_id="architecture-review.production-ready",
            step_id="production_gate",
            process_id="process-1",
        )
        is False
    )


def test_production_readiness_requires_provider_attestation() -> None:
    report = evaluate_readiness(
        _production_ready_manifest(),
        repo_root=_ROOT,
        evaluated_at=_EVALUATED_AT,
    )

    assert report.structure_valid is True
    assert report.production_ready is False
    assert report.failures == ("unattested production evidence: network-data-flow-validation",)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"body": b"tampered"}, "body digest mismatch"),
        ({"scope_ref": "scope:other"}, "scope mismatch"),
        ({"revision": "revision:other"}, "revision mismatch"),
        ({"authorized_approvers": ("group:other",)}, "approver is not authorized"),
        ({"observed_at": datetime(2026, 8, 1, tzinfo=UTC)}, "body is stale"),
        ({"synthetic": True}, "synthetic evidence is not production evidence"),
    ],
)
def test_production_readiness_rejects_invalid_attestation(
    overrides: dict[str, object],
    reason: str,
) -> None:
    report = evaluate_readiness(
        _production_ready_manifest(),
        repo_root=_ROOT,
        evaluated_at=_EVALUATED_AT,
        evidence_attestations={
            "network-data-flow-validation": _attestation(**overrides),
        },
    )

    assert report.production_ready is False
    assert report.failures == (
        f"invalid production evidence network-data-flow-validation: {reason}",
    )


def test_production_readiness_accepts_exact_provider_attestation() -> None:
    report = evaluate_readiness(
        _production_ready_manifest(),
        repo_root=_ROOT,
        evaluated_at=_EVALUATED_AT,
        evidence_attestations={
            "network-data-flow-validation": _attestation(),
        },
    )

    assert report == report.__class__(structure_valid=True, production_ready=True)


async def test_runtime_gate_retrieves_and_attests_production_evidence(
    tmp_path: Path,
) -> None:
    raw = _production_ready_manifest()
    manifest = tmp_path / "architecture-review.yaml"
    manifest.write_text(yaml.safe_dump(raw), encoding="utf-8")

    class _Provider:
        def __init__(self) -> None:
            self.bindings: list[ProductionEvidenceBinding] = []

        async def retrieve(
            self,
            binding: ProductionEvidenceBinding,
        ) -> ProductionEvidenceAttestation:
            self.bindings.append(binding)
            return ProductionEvidenceAttestation(
                uri=binding.uri,
                body=_EVIDENCE_BODY,
                scope_ref=binding.scope_ref,
                revision=binding.revision,
                observed_at=datetime(2026, 8, 28, tzinfo=UTC),
                authorized_approvers=(binding.approved_by,),
                authentication_ref="auth:provider-readback-1",
            )

    provider = _Provider()
    evaluator = ArchitectureReviewProductionGateEvaluator(
        manifest_path=manifest,
        repo_root=_ROOT,
        evidence_provider=provider,
    )

    assert (
        await evaluator.evaluate(
            rule_id="architecture-review.production-ready",
            step_id="production_gate",
            process_id="process-1",
        )
        is True
    )
    assert [binding.item for binding in provider.bindings] == ["network-data-flow-validation"]
    assert (
        await evaluator.evaluate(
            rule_id="unknown",
            step_id="production_gate",
            process_id="process-1",
        )
        is False
    )
