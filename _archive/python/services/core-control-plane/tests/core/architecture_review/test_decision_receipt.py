from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.architecture_review import (
    ArchitectureDecisionAuthorityBasis,
    ArchitectureDecisionOutcome,
    ArchitectureReviewDecisionReceipt,
    build_architecture_review_decision_receipt,
)

NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _receipt(
    **overrides: object,
) -> ArchitectureReviewDecisionReceipt:
    values: dict[str, object] = {
        "review_case_id": "review-1",
        "change_id": "change-1",
        "decision_case_id": "decision-case-1",
        "impact_envelope_id": "impact-1",
        "target_revision": "revision-1",
        "context_snapshot_id": "context-1",
        "evidence_bundle_id": "evidence-bundle-1",
        "graph_revision": "graph-1",
        "catalog_release": "catalog-1",
        "evidence_refs": ("evidence-a", "evidence-b"),
        "conditions": ("condition-a",),
        "outcome": ArchitectureDecisionOutcome.CONDITIONAL,
        "rationale": "The exact evidence supports a bounded conditional decision.",
        "authority_basis": ArchitectureDecisionAuthorityBasis.HUMAN_APPROVAL,
        "authority_ref": "authority:approval-policy-1",
        "requester_id": "principal:requester",
        "judge_id": "agent:Forseti",
        "arbitrator_id": "agent:Odin",
        "approver_ids": ("principal:approver-a", "principal:approver-b"),
        "approval_receipt_refs": ("approval:a", "approval:b"),
        "quorum": 2,
        "audit_intent_ref": "audit:intent-1",
        "terminal_audit_ref": "audit:terminal-1",
        "recorded_at": NOW,
        "effective_from": NOW,
        "effective_until": NOW + timedelta(hours=1),
        "reevaluation_trigger": "evidence_or_scope_changes",
    }
    values.update(overrides)
    return build_architecture_review_decision_receipt(**values)


def test_receipt_is_content_addressed_and_replay_stable() -> None:
    first = _receipt()
    second = _receipt(evidence_refs=("evidence-b", "evidence-a"))

    assert first == second
    assert first.decision_id.startswith("arb-decision-")
    assert first.receipt_digest.startswith("sha256:")
    assert first.execution_authority is False
    assert ArchitectureReviewDecisionReceipt.model_validate_json(first.to_json()) == first


def test_receipt_identity_changes_with_every_authority_input() -> None:
    baseline = _receipt()

    assert _receipt(target_revision="revision-2").decision_id != baseline.decision_id
    assert _receipt(conditions=("condition-b",)).decision_id != baseline.decision_id
    assert _receipt(approval_receipt_refs=("approval:a", "approval:c")).decision_id != (
        baseline.decision_id
    )
    assert _receipt(graph_revision="graph-2").decision_id != baseline.decision_id


def test_human_approval_requires_quorum_and_distinct_principals() -> None:
    with pytest.raises(ValueError, match="satisfy approver quorum"):
        _receipt(approver_ids=("principal:approver-a",))

    with pytest.raises(ValueError, match="MUST NOT self-approve"):
        _receipt(
            requester_id="principal:approver-a",
            approver_ids=("principal:approver-a", "principal:approver-b"),
        )


def test_non_human_authority_cannot_claim_approval_receipts() -> None:
    with pytest.raises(ValueError, match="MUST NOT claim human approval"):
        _receipt(authority_basis=ArchitectureDecisionAuthorityBasis.OBSERVATION)


def test_tampered_receipt_fails_digest_validation() -> None:
    receipt = _receipt()
    payload = receipt.to_mapping()
    payload["target_revision"] = "revision-tampered"

    with pytest.raises(ValueError, match="digest does not match"):
        ArchitectureReviewDecisionReceipt.model_validate(payload)


def test_receipt_requires_ordered_effective_interval() -> None:
    with pytest.raises(ValueError, match="recorded_at <= effective_from"):
        _receipt(effective_until=NOW)
