"""Tests for immutable document-ontology proposal contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    ClaimDisposition,
    ClaimResolution,
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

_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _evidence() -> SourceEvidence:
    return SourceEvidence(
        source_ref="doc:runbook",
        document_id="runbook",
        document_revision="rev-1",
        content_sha256=_SHA_A,
        line_start=3,
        line_end=4,
        text_sha256=_SHA_B,
        source_format="manual",
        structural_unit_id="line-3",
        structural_locator="line:3",
    )


def _proposal(*, properties: tuple[OntologyProperty, ...] = ()) -> OntologyChangeProposal:
    return OntologyChangeProposal(
        proposal_id="odp-1",
        extraction_run_id="run-1",
        candidate_id="candidate-1",
        claim_id="claim-1",
        operation=OntologyOperation.UPDATE,
        target_kind=OntologyTargetKind.OBJECT,
        target_type="BusinessService",
        target_identity="service:checkout",
        ontology_release=_SHA_A,
        expected_graph_revision="graph-7",
        authority=AuthorityClass.DECLARED_INTENT,
        evidence=_evidence(),
        entity_resolution=EntityResolution(
            selected_identity="service:checkout",
            candidates=("service:checkout",),
            method="exact",
        ),
        properties=properties,
    )


def test_proposal_digest_is_stable_across_property_order() -> None:
    left = _proposal(
        properties=(
            OntologyProperty("criticality", "high"),
            OntologyProperty("display_name", "Checkout"),
        )
    )
    right = _proposal(
        properties=(
            OntologyProperty("display_name", "Checkout"),
            OntologyProperty("criticality", "high"),
        )
    )
    assert left.digest == right.digest


def test_invalid_source_range_fails_closed() -> None:
    with pytest.raises(ValueError, match="1-based inclusive"):
        SourceEvidence(
            source_ref="doc:runbook",
            document_id="runbook",
            document_revision="rev-1",
            content_sha256=_SHA_A,
            line_start=0,
            line_end=1,
            text_sha256=_SHA_B,
            source_format="manual",
            structural_unit_id="line-1",
            structural_locator="line:1",
        )


def test_source_evidence_rejects_blank_or_unbounded_references() -> None:
    with pytest.raises(ValueError, match="MUST be non-empty"):
        replace(_evidence(), source_ref="   ")
    with pytest.raises(ValueError, match="bounded length"):
        replace(_evidence(), source_ref="x" * 2049)
    with pytest.raises(ValueError, match="structural identity"):
        replace(_evidence(), structural_unit_id=" ")
    with pytest.raises(ValueError, match="structural locator"):
        replace(_evidence(), structural_locator=" ")
    with pytest.raises(ValueError, match="structural identity exceeds"):
        replace(_evidence(), structural_locator="x" * 257)


def test_link_requires_both_endpoints() -> None:
    with pytest.raises(ValueError, match="from_identity and to_identity"):
        OntologyChangeProposal(
            proposal_id="odp-link",
            extraction_run_id="run-1",
            candidate_id="candidate-link",
            claim_id="claim-1",
            operation=OntologyOperation.ADD,
            target_kind=OntologyTargetKind.LINK,
            target_type="depends_on",
            target_identity="link:one",
            ontology_release=_SHA_A,
            expected_graph_revision="graph-7",
            authority=AuthorityClass.DECLARED_INTENT,
            evidence=_evidence(),
            entity_resolution=EntityResolution(method="new"),
            from_identity="service:checkout",
        )


def test_mapped_claim_requires_candidate() -> None:
    with pytest.raises(ValueError, match="at least one candidate"):
        ClaimResolution(claim_id="claim-1", disposition=ClaimDisposition.MAPPED)


def test_mapped_claim_rejects_invalid_or_duplicate_candidate_ids() -> None:
    with pytest.raises(ValueError, match="invalid candidate_id"):
        ClaimResolution(
            claim_id="claim-1",
            disposition=ClaimDisposition.MAPPED,
            candidate_ids=("../candidate",),
        )
    with pytest.raises(ValueError, match="MUST be unique"):
        ClaimResolution(
            claim_id="claim-1",
            disposition=ClaimDisposition.MAPPED,
            candidate_ids=("candidate-1", "candidate-1"),
        )


def test_revision_method_and_property_value_are_bounded() -> None:
    with pytest.raises(ValueError, match="expected_graph_revision"):
        replace(_proposal(), expected_graph_revision="   ")
    with pytest.raises(ValueError, match="resolution method"):
        EntityResolution(method="   ")
    with pytest.raises(ValueError, match="at most 4096"):
        OntologyProperty("description", "x" * 4097)
    with pytest.raises(ValueError, match="bounded to 32"):
        EntityResolution(candidates=tuple(f"service:{index}" for index in range(33)))


def test_denied_gate_forces_denied_state() -> None:
    receipt = GateReceipt(
        gate="authority",
        outcome=GateOutcome.DENY,
        reason_codes=("source_not_authoritative",),
    )
    with pytest.raises(ValueError, match="denied gate"):
        VerifiedOntologyProposal(
            proposal=_proposal(),
            state=ProposalState.REVIEW_REQUIRED,
            receipts=(receipt,),
        )


def test_verification_digest_is_replay_stable() -> None:
    verified = VerifiedOntologyProposal(
        proposal=_proposal(),
        state=ProposalState.REVIEW_REQUIRED,
        receipts=(
            GateReceipt(gate="shape", outcome=GateOutcome.PASS),
            GateReceipt(
                gate="promotion_policy",
                outcome=GateOutcome.REVIEW,
                reason_codes=("review_only",),
            ),
        ),
    )
    replay = VerifiedOntologyProposal(
        proposal=_proposal(),
        state=ProposalState.REVIEW_REQUIRED,
        receipts=verified.receipts,
    )
    assert verified.verification_digest == replay.verification_digest
