"""Tests for corpus scoring and low-risk promotion evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_evaluation import (
    ChangeRiskClass,
    ExpectedOntologyFact,
    PromotionPolicy,
    ShadowReviewOutcome,
    assess_low_risk_promotion,
    evaluate_review_package,
    normalize_review_package,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    ClaimDisposition,
    ClaimKind,
    ClaimResolution,
    ClaimUnit,
    EntityResolution,
    GateOutcome,
    GateReceipt,
    OntologyChangeProposal,
    OntologyOperation,
    OntologyProperty,
    OntologyTargetKind,
    ProposalState,
    SourceEvidence,
    VerifiedOntologyProposal,
)
from fdai.rule_catalog.pipeline.distill.ontology_review import (
    OntologyReviewPackage,
    OntologyReviewSummary,
)
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    proposal_fact_key,
    proposal_value_digest,
)


def _package() -> OntologyReviewPackage:
    evidence = SourceEvidence(
        "doc:a",
        "a",
        "rev-1",
        "a" * 64,
        1,
        1,
        "b" * 64,
        "manual",
        "line-1",
        "line:1",
    )
    claim = ClaimUnit(
        "claim-1",
        ClaimKind.RELATIONSHIP,
        AuthorityClass.DECLARED_INTENT,
        evidence,
        True,
    )
    proposal = OntologyChangeProposal(
        proposal_id="odp-1",
        extraction_run_id="run-1",
        candidate_id="candidate-1",
        claim_id=claim.claim_id,
        operation=OntologyOperation.UPDATE,
        target_kind=OntologyTargetKind.OBJECT,
        target_type="BusinessService",
        target_identity="service:a",
        ontology_release="c" * 64,
        expected_graph_revision="g1",
        authority=claim.authority,
        evidence=evidence,
        entity_resolution=EntityResolution("service:a", ("service:a",), "exact"),
        properties=(OntologyProperty("owner_ref", "team:a"),),
    )
    verified = VerifiedOntologyProposal(
        proposal,
        ProposalState.REVIEW_REQUIRED,
        (
            GateReceipt("shape", GateOutcome.PASS),
            GateReceipt("promotion_policy", GateOutcome.REVIEW, ("review_only",)),
        ),
    )
    return OntologyReviewPackage(
        document_id="a",
        source_ref="doc:a",
        access_policy_ref="access:a",
        content_sha256="a" * 64,
        extraction_run_id="run-1",
        ontology_release="c" * 64,
        expected_graph_revision="g1",
        claims=(claim,),
        resolutions=(ClaimResolution("claim-1", ClaimDisposition.MAPPED, ("candidate-1",)),),
        proposals=(verified,),
        issues=(),
        summary=OntologyReviewSummary(1, 1, 1, 0, 1, 0, 1),
    )


def test_frozen_evaluation_scores_exact_fact_and_critical_claim() -> None:
    package = _package()
    proposal = package.proposals[0].proposal
    report = evaluate_review_package(
        package,
        (
            ExpectedOntologyFact(
                "claim-1",
                proposal_fact_key(proposal),
                proposal_value_digest(proposal),
                True,
            ),
        ),
    )
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.critical_claim_recall == 1.0


def test_normalized_projection_ignores_format_locator_identity() -> None:
    package = _package()
    verified = package.proposals[0]
    relocated_evidence = replace(
        verified.proposal.evidence,
        source_format="pdf",
        structural_unit_id="pdf-page-1-block-1",
        structural_locator="pdf/page:1/block:1",
    )
    relocated_claim = replace(package.claims[0], evidence=relocated_evidence)
    relocated_proposal = replace(verified.proposal, evidence=relocated_evidence)
    relocated = replace(
        package,
        claims=(relocated_claim,),
        proposals=(replace(verified, proposal=relocated_proposal),),
    )

    assert package.package_digest != relocated.package_digest
    assert normalize_review_package(package) == normalize_review_package(relocated)


def test_normalized_projection_orders_mixed_scalar_properties() -> None:
    package = _package()
    first = package.proposals[0]
    second_proposal = replace(
        first.proposal,
        proposal_id="odp-2",
        candidate_id="candidate-2",
        properties=(OntologyProperty("owner_ref", 2),),
    )
    expanded = replace(
        package,
        proposals=(first, replace(first, proposal=second_proposal)),
        summary=replace(package.summary, proposals=2, review_proposals=2),
    )

    projection = normalize_review_package(expanded)

    assert len(projection.proposal_digest) == 64


def test_frozen_evaluation_reports_false_positive_and_negative() -> None:
    report = evaluate_review_package(
        _package(),
        (ExpectedOntologyFact("claim-2", "d" * 64, "e" * 64, True),),
    )
    assert report.false_positive == 1
    assert report.false_negative == 1
    assert report.critical_claim_recall == 0.0


def _outcomes(count: int, *, violation_at: int | None = None):
    start = date(2026, 1, 1)
    return tuple(
        ShadowReviewOutcome(
            proposal_digest=f"{index + 1:064x}",
            observed_day=start + timedelta(days=index % 30),
            reviewed=True,
            risk_class=ChangeRiskClass.LOW_RISK_MAPPING,
            correct=True,
            authority_violation=index == violation_at,
        )
        for index in range(count)
    )


def test_complete_live_shadow_evidence_is_eligible() -> None:
    assessment = assess_low_risk_promotion(_outcomes(500), as_of=date(2026, 1, 30))
    assert assessment.eligible is True
    assert assessment.reviewed_samples == 500
    assert assessment.distinct_days == 30
    assert assessment.precision_lower_bound >= 0.99


def test_guard_violation_blocks_promotion() -> None:
    assessment = assess_low_risk_promotion(
        _outcomes(500, violation_at=1),
        as_of=date(2026, 1, 30),
    )
    assert assessment.eligible is False
    assert "authority_violation" in assessment.reason_codes


def test_insufficient_evidence_reports_each_failed_gate() -> None:
    assessment = assess_low_risk_promotion(
        _outcomes(10),
        as_of=date(2026, 1, 30),
        policy=PromotionPolicy(min_distinct_days=30, min_reviewed_samples=500),
    )
    assert assessment.eligible is False
    assert "insufficient_reviewed_samples" in assessment.reason_codes
    assert "insufficient_distinct_days" in assessment.reason_codes
    assert "precision_lower_bound_not_met" in assessment.reason_codes


def test_duplicate_shadow_observation_cannot_inflate_sample_size() -> None:
    duplicate = _outcomes(1)[0]
    with pytest.raises(ValueError, match="MUST be unique"):
        assess_low_risk_promotion((duplicate, duplicate), as_of=date(2026, 1, 30))


def test_future_observations_and_governed_changes_cannot_promote() -> None:
    future = ShadowReviewOutcome(
        proposal_digest="f" * 64,
        observed_day=date(2026, 2, 1),
        reviewed=True,
        risk_class=ChangeRiskClass.LOW_RISK_MAPPING,
        correct=True,
    )
    assessment = assess_low_risk_promotion(
        _outcomes(500) + (future,),
        as_of=date(2026, 1, 30),
    )
    assert assessment.eligible is False
    assert "future_observation" in assessment.reason_codes

    governed = tuple(
        ShadowReviewOutcome(
            proposal_digest=f"{index + 1000:064x}",
            observed_day=date(2026, 1, 1) + timedelta(days=index % 30),
            reviewed=True,
            risk_class=ChangeRiskClass.GOVERNED_INTENT,
            correct=True,
        )
        for index in range(500)
    )
    governed_assessment = assess_low_risk_promotion(
        governed,
        as_of=date(2026, 1, 30),
    )
    assert governed_assessment.reviewed_samples == 0
    assert governed_assessment.eligible is False


def test_duplicate_expected_facts_are_rejected() -> None:
    expected = ExpectedOntologyFact("claim-1", "d" * 64, "e" * 64, True)
    with pytest.raises(ValueError, match="facts MUST be unique"):
        evaluate_review_package(_package(), (expected, expected))


def test_promotion_assessment_rejects_non_date_cutoff() -> None:
    with pytest.raises(ValueError, match="as_of MUST be a date"):
        assess_low_risk_promotion(
            _outcomes(1),
            as_of=datetime(2026, 1, 1, tzinfo=UTC),  # type: ignore[arg-type]
        )
