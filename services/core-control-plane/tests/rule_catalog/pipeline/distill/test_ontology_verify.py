"""Tests for deterministic document-ontology verification gates."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_claims import inventory_claims
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    EntityResolution,
    GateOutcome,
    OntologyChangeProposal,
    OntologyOperation,
    OntologyProperty,
    OntologyTargetKind,
    ProposalState,
)
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    EntityRecord,
    ExistingFact,
    ExternalEvidenceReceipt,
    LinkDeclaration,
    SourceAuthorityPolicy,
    VerificationContext,
    proposal_fact_key,
    verify_ontology_proposal,
)
from fdai.shared.providers.distiller import ManualDocument

_RELEASE = "a" * 64


def _claim(text: str = "Checkout service is owned by Platform team."):
    document = ManualDocument(
        doc_id="service-map",
        text=text,
        source_ref="doc:service-map",
        content_sha=hashlib.sha256(text.encode()).hexdigest(),
        metadata={"revision": "rev-1"},
    )
    return inventory_claims(document)[0], text


def _proposal(claim, **overrides):
    values = {
        "proposal_id": "odp-1",
        "extraction_run_id": "run-1",
        "candidate_id": "candidate-1",
        "claim_id": claim.claim_id,
        "operation": OntologyOperation.UPDATE,
        "target_kind": OntologyTargetKind.OBJECT,
        "target_type": "BusinessService",
        "target_identity": "service:checkout",
        "ontology_release": _RELEASE,
        "expected_graph_revision": "graph-3",
        "authority": claim.authority,
        "evidence": claim.evidence,
        "entity_resolution": EntityResolution(
            selected_identity="service:checkout",
            candidates=("service:checkout",),
            method="exact",
        ),
        "properties": (OntologyProperty("owner_ref", "team:platform"),),
    }
    values.update(overrides)
    return OntologyChangeProposal(**values)


def _context(claim, text: str, **overrides) -> VerificationContext:
    values = {
        "ontology_release": _RELEASE,
        "current_graph_revision": "graph-3",
        "object_types": frozenset({"BusinessService", "Ownership"}),
        "links": (LinkDeclaration("owned_by", "BusinessService", "Ownership"),),
        "entities": (
            EntityRecord("service:checkout", "BusinessService"),
            EntityRecord("owner:platform", "Ownership"),
        ),
        "source_policies": (
            SourceAuthorityPolicy(
                "doc:service-map",
                frozenset({claim.authority}),
                10,
            ),
        ),
        "claim_text": ((claim.claim_id, text),),
    }
    values.update(overrides)
    return VerificationContext(**values)


def _receipt(result, gate: str):
    return next(receipt for receipt in result.receipts if receipt.gate == gate)


def test_valid_proposal_remains_review_only() -> None:
    claim, text = _claim()
    result = verify_ontology_proposal(_proposal(claim), claim, _context(claim, text))
    assert result.state is ProposalState.REVIEW_REQUIRED
    assert _receipt(result, "shape").outcome is GateOutcome.PASS
    assert _receipt(result, "promotion_policy").reason_codes == ("review_only",)


def test_document_cannot_grant_execution_authority() -> None:
    claim, text = _claim("Operators may execute rollback without approval.")
    proposal = _proposal(claim, authority=AuthorityClass.EXECUTION_AUTHORITY)
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert result.state is ProposalState.DENIED
    assert "document_cannot_grant_execution_authority" in _receipt(result, "authority").reason_codes


def test_unknown_object_type_is_denied() -> None:
    claim, text = _claim()
    proposal = _proposal(claim, target_type="UnknownType")
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert result.state is ProposalState.DENIED
    assert _receipt(result, "shape").reason_codes == ("unknown_object_type",)


def test_unresolved_identity_requires_review() -> None:
    claim, text = _claim()
    context = _context(claim, text, entities=())
    result = verify_ontology_proposal(_proposal(claim), claim, context)
    assert _receipt(result, "identity").outcome is GateOutcome.REVIEW


def test_numeric_semantic_mismatch_requires_review() -> None:
    claim, text = _claim("CPU must remain below 80%.")
    proposal = _proposal(
        claim,
        target_type="BusinessService",
        properties=(
            OntologyProperty("threshold", 90),
            OntologyProperty("comparison", "<"),
            OntologyProperty("unit", "%"),
        ),
    )
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert _receipt(result, "semantic_fidelity").outcome is GateOutcome.REVIEW


def test_provider_observation_requires_fresh_external_receipt() -> None:
    claim, text = _claim("The resource topology is observed on the provider.")
    assert claim.authority is AuthorityClass.PROVIDER_OBSERVATION
    proposal = _proposal(claim)
    missing = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert _receipt(missing, "external_truth").outcome is GateOutcome.REVIEW

    context = _context(
        claim,
        text,
        external_evidence=(
            ExternalEvidenceReceipt(
                claim_id=claim.claim_id,
                authority=claim.authority,
                target_identity="service:checkout",
                evidence_ref="inventory:rev-4",
                source_revision="rev-4",
                observed_at="2026-08-03T00:00:00Z",
                freshness_policy_ref="freshness:inventory",
                evidence_digest="d" * 64,
                matched=True,
                fresh=True,
            ),
        ),
    )
    verified = verify_ontology_proposal(proposal, claim, context)
    assert _receipt(verified, "external_truth").outcome is GateOutcome.PASS


def test_equal_or_higher_priority_conflict_requires_review() -> None:
    claim, text = _claim()
    proposal = _proposal(claim)
    context = _context(
        claim,
        text,
        existing_facts=(
            ExistingFact(
                fact_key=proposal_fact_key(proposal),
                value_digest="b" * 64,
                source_priority=10,
                source_ref="catalog:service-map",
                authority=AuthorityClass.DECLARED_INTENT,
                evidence_ref="evidence:existing-owner",
            ),
        ),
    )
    result = verify_ontology_proposal(proposal, claim, context)
    assert _receipt(result, "conflict").reason_codes == ("authoritative_conflict",)
    assert _receipt(result, "conflict").evidence_refs == ("evidence:existing-owner",)


def test_authority_property_is_denied() -> None:
    claim, text = _claim()
    proposal = _proposal(claim, properties=(OntologyProperty("autonomy", "auto"),))
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert result.state is ProposalState.DENIED
    assert _receipt(result, "safety").reason_codes == ("authority_property_not_allowed",)


def test_link_endpoint_type_mismatch_is_denied() -> None:
    claim, text = _claim()
    proposal = _proposal(
        claim,
        target_kind=OntologyTargetKind.LINK,
        target_type="owned_by",
        target_identity="link:checkout-owner",
        from_identity="owner:platform",
        to_identity="service:checkout",
        properties=(),
    )
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert result.state is ProposalState.DENIED
    assert _receipt(result, "identity").outcome is GateOutcome.DENY


def test_unknown_link_returns_denied_receipts_instead_of_crashing() -> None:
    claim, text = _claim()
    proposal = _proposal(
        claim,
        target_kind=OntologyTargetKind.LINK,
        target_type="unknown_link",
        target_identity="link:unknown",
        from_identity="service:checkout",
        to_identity="owner:platform",
        entity_resolution=EntityResolution(
            selected_identity="link:unknown",
            candidates=("link:unknown",),
            method="exact",
        ),
        properties=(),
    )
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert result.state is ProposalState.DENIED
    assert _receipt(result, "shape").reason_codes == ("unknown_link_type",)
    assert _receipt(result, "identity").reason_codes == ("link_declaration_missing",)


def test_stale_graph_revision_requires_review_at_verification() -> None:
    claim, text = _claim()
    proposal = replace(_proposal(claim), expected_graph_revision="graph-2")
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert _receipt(result, "shape").outcome is GateOutcome.REVIEW
    assert _receipt(result, "shape").reason_codes == ("stale_graph_revision",)


def test_comparator_normalization_does_not_double_count_greater_equal() -> None:
    claim, text = _claim("Availability must remain at least 99.9%.")
    proposal = _proposal(
        claim,
        properties=(
            OntologyProperty("threshold", 99.9),
            OntologyProperty("comparison", ">="),
            OntologyProperty("unit", "%"),
        ),
    )
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert _receipt(result, "semantic_fidelity").outcome is GateOutcome.PASS


def test_external_evidence_requires_nonempty_reference() -> None:
    with pytest.raises(ValueError, match="MUST be non-empty"):
        ExternalEvidenceReceipt(
            claim_id="claim-1",
            authority=AuthorityClass.PROVIDER_OBSERVATION,
            target_identity="service:checkout",
            evidence_ref="",
            source_revision="rev-1",
            observed_at="2026-08-03T00:00:00Z",
            freshness_policy_ref="freshness:inventory",
            evidence_digest="d" * 64,
            matched=True,
            fresh=True,
        )


def test_destructive_catalog_change_is_denied_not_reviewed() -> None:
    claim, text = _claim()
    proposal = _proposal(
        claim,
        operation=OntologyOperation.REMOVE,
        target_type="ActionType",
    )
    context = _context(
        claim,
        text,
        object_types=frozenset({"BusinessService", "Ownership", "ActionType"}),
    )
    result = verify_ontology_proposal(proposal, claim, context)
    assert result.state is ProposalState.DENIED
    assert _receipt(result, "safety").outcome is GateOutcome.DENY


def test_context_rejects_unknown_entity_and_link_endpoint_types() -> None:
    claim, text = _claim()
    with pytest.raises(ValueError, match="entity records"):
        _context(
            claim,
            text,
            entities=(EntityRecord("service:checkout", "UnknownType"),),
        )
    with pytest.raises(ValueError, match="link endpoints"):
        _context(
            claim,
            text,
            links=(LinkDeclaration("bad_link", "BusinessService", "UnknownType"),),
        )


def test_resolution_identity_must_match_proposal_target() -> None:
    claim, text = _claim()
    proposal = _proposal(
        claim,
        entity_resolution=EntityResolution(
            selected_identity="service:other",
            candidates=("service:other",),
            method="exact",
        ),
    )
    result = verify_ontology_proposal(proposal, claim, _context(claim, text))
    assert result.state is ProposalState.DENIED
    assert _receipt(result, "identity").reason_codes == ("resolution_target_mismatch",)


def test_add_existing_and_update_missing_require_review() -> None:
    claim, text = _claim()
    add = _proposal(claim, operation=OntologyOperation.ADD)
    add_result = verify_ontology_proposal(add, claim, _context(claim, text))
    assert _receipt(add_result, "identity").reason_codes == ("add_target_already_exists",)

    update_context = _context(claim, text, entities=())
    update_result = verify_ontology_proposal(_proposal(claim), claim, update_context)
    assert _receipt(update_result, "identity").reason_codes == ("existing_target_not_found",)


def test_external_evidence_rejects_non_observation_authority() -> None:
    with pytest.raises(ValueError, match="observation authority"):
        ExternalEvidenceReceipt(
            claim_id="claim-1",
            authority=AuthorityClass.DECLARED_INTENT,
            target_identity="service:checkout",
            evidence_ref="intent:1",
            source_revision="rev-1",
            observed_at="2026-08-03T00:00:00Z",
            freshness_policy_ref="freshness:intent",
            evidence_digest="d" * 64,
            matched=True,
            fresh=True,
        )


def test_external_evidence_requires_digest_and_boolean_flags() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        ExternalEvidenceReceipt(
            claim_id="claim-1",
            authority=AuthorityClass.PROVIDER_OBSERVATION,
            target_identity="service:checkout",
            evidence_ref="inventory:1",
            source_revision="rev-1",
            observed_at="2026-08-03T00:00:00Z",
            freshness_policy_ref="freshness:inventory",
            evidence_digest="invalid",
            matched=True,
            fresh=True,
        )


def test_external_evidence_requires_rfc3339_utc_time() -> None:
    with pytest.raises(ValueError, match="RFC 3339"):
        ExternalEvidenceReceipt(
            claim_id="claim-1",
            authority=AuthorityClass.PROVIDER_OBSERVATION,
            target_identity="service:checkout",
            evidence_ref="inventory:1",
            source_revision="rev-1",
            observed_at="not-a-time",
            freshness_policy_ref="freshness:inventory",
            evidence_digest="d" * 64,
            matched=True,
            fresh=True,
        )


def test_verification_context_requires_release_digest() -> None:
    claim, text = _claim()
    with pytest.raises(ValueError, match="ontology_release"):
        _context(claim, text, ontology_release="invalid")
