"""Tests for complete document ontology review packages."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_identity import EntityAliasRecord
from fdai.rule_catalog.pipeline.distill.ontology_models import AuthorityClass, ProposalState
from fdai.rule_catalog.pipeline.distill.ontology_review import build_ontology_review_package
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    EntityRecord,
    SourceAuthorityPolicy,
    VerificationContext,
)
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistillationResult,
    DistilledCandidate,
    ManualDocument,
)

_RELEASE = "a" * 64


def _document(text: str = "Checkout service is owned by Platform team.") -> ManualDocument:
    return ManualDocument(
        doc_id="service-map",
        text=text,
        source_ref="doc:service-map",
        content_sha=hashlib.sha256(text.encode()).hexdigest(),
        metadata={"revision": "rev-1", "access_policy_ref": "access:service-map"},
    )


def _candidate(*, candidate_id: str = "candidate-1", assertion: str | None = None):
    return DistilledCandidate(
        kind=CandidateKind.ONTOLOGY_OBJECT,
        candidate_id=candidate_id,
        source_ref="doc:service-map",
        source_section="Ownership",
        source_lines=(1, 1),
        content_sha=hashlib.sha256(b"Checkout service is owned by Platform team.").hexdigest(),
        body={
            "operation": "update",
            "target_type": "BusinessService",
            "target_identity": "service:checkout",
            "authority": "declared_intent",
            "source_assertion": assertion or "Checkout service is owned by Platform team.",
            "properties": {"owner_ref": "team:platform"},
        },
    )


def _context() -> VerificationContext:
    return VerificationContext(
        ontology_release=_RELEASE,
        current_graph_revision="graph-5",
        object_types=frozenset({"BusinessService"}),
        links=(),
        entities=(EntityRecord("service:checkout", "BusinessService"),),
        source_policies=(
            SourceAuthorityPolicy(
                source_ref="doc:service-map",
                allowed=frozenset({AuthorityClass.DECLARED_INTENT}),
                priority=10,
            ),
        ),
        claim_text=(),
    )


def test_package_is_replay_stable_and_contains_no_source_text() -> None:
    package = build_ontology_review_package(
        document=_document(),
        result=DistillationResult(candidates=(_candidate(),)),
        context=_context(),
        extraction_run_id="run-1",
    )
    replay = build_ontology_review_package(
        document=_document(),
        result=DistillationResult(candidates=(_candidate(),)),
        context=_context(),
        extraction_run_id="run-1",
    )
    assert package.package_digest == replay.package_digest
    assert package.summary.total_claims == 1
    assert package.summary.mapped_claims == 1
    assert package.proposals[0].state is ProposalState.REVIEW_REQUIRED
    assert "Checkout service" not in repr(package)


def test_review_package_binds_unique_configured_alias() -> None:
    candidate = _candidate()
    body = dict(candidate.body)
    body["target_identity"] = "Checkout Service"
    candidate = replace(candidate, body=body)
    context = replace(
        _context(),
        aliases=(EntityAliasRecord("Checkout Service", "service:checkout"),),
    )

    package = build_ontology_review_package(
        document=_document(),
        result=DistillationResult(candidates=(candidate,)),
        context=context,
        extraction_run_id="run-1",
    )

    proposal = package.proposals[0].proposal
    assert proposal.target_identity == "service:checkout"
    assert proposal.entity_resolution.method == "alias"


def test_invalid_candidate_leaves_claim_unresolved() -> None:
    package = build_ontology_review_package(
        document=_document(),
        result=DistillationResult(candidates=(_candidate(assertion="Platform owns Checkout."),)),
        context=_context(),
        extraction_run_id="run-1",
    )
    assert package.proposals == ()
    assert package.summary.unresolved_claims == 1
    assert {issue.reason_code for issue in package.issues} == {
        "invalid_candidate_shape",
        "unmapped_claim",
    }


def test_duplicate_semantic_proposal_is_visible() -> None:
    package = build_ontology_review_package(
        document=_document(),
        result=DistillationResult(
            candidates=(
                _candidate(candidate_id="candidate-1"),
                _candidate(candidate_id="candidate-2"),
            )
        ),
        context=_context(),
        extraction_run_id="run-1",
    )
    assert len(package.proposals) == 1
    assert any(issue.reason_code == "duplicate_proposal_id" for issue in package.issues)


def test_non_ontology_candidate_can_account_for_claim_without_graph_proposal() -> None:
    rule = DistilledCandidate(
        kind=CandidateKind.RULE,
        candidate_id="rule-1",
        source_ref="doc:service-map",
        source_section="Ownership",
        source_lines=(1, 1),
    )
    package = build_ontology_review_package(
        document=_document(),
        result=DistillationResult(candidates=(rule,)),
        context=_context(),
        extraction_run_id="run-1",
    )
    assert package.summary.mapped_claims == 1
    assert package.summary.proposals == 0
    assert package.issues == ()


def test_execution_authority_candidate_is_denied_and_reported() -> None:
    text = "Operators may execute rollback without approval."
    candidate = _candidate(assertion=text)
    body = dict(candidate.body)
    body["authority"] = "execution_authority"
    candidate = DistilledCandidate(
        kind=candidate.kind,
        candidate_id=candidate.candidate_id,
        source_ref=candidate.source_ref,
        source_section=candidate.source_section,
        source_lines=candidate.source_lines,
        content_sha=hashlib.sha256(text.encode()).hexdigest(),
        body=body,
    )
    context = _context()
    context = VerificationContext(
        ontology_release=context.ontology_release,
        current_graph_revision=context.current_graph_revision,
        object_types=context.object_types,
        links=context.links,
        entities=context.entities,
        source_policies=(
            SourceAuthorityPolicy(
                "doc:service-map",
                frozenset({AuthorityClass.EXECUTION_AUTHORITY}),
                10,
            ),
        ),
        claim_text=(),
    )
    package = build_ontology_review_package(
        document=_document(text),
        result=DistillationResult(candidates=(candidate,)),
        context=context,
        extraction_run_id="run-1",
    )
    assert package.summary.denied_proposals == 1
    assert any(issue.reason_code == "proposal_denied" for issue in package.issues)


def test_review_requires_source_access_policy() -> None:
    document = _document()
    document = ManualDocument(
        doc_id=document.doc_id,
        text=document.text,
        source_ref=document.source_ref,
        content_sha=document.content_sha,
        metadata={"revision": "rev-1"},
    )
    with pytest.raises(ValueError, match="access_policy_ref"):
        build_ontology_review_package(
            document=document,
            result=DistillationResult(candidates=(_candidate(),)),
            context=_context(),
            extraction_run_id="run-1",
        )


def test_empty_claim_document_preserves_exact_content_digest() -> None:
    document = _document("Narrative only.")
    package = build_ontology_review_package(
        document=document,
        result=DistillationResult(),
        context=_context(),
        extraction_run_id="run-1",
    )
    assert package.content_sha256 == hashlib.sha256(document.text.encode()).hexdigest()


def test_review_package_rejects_inconsistent_summary() -> None:
    package = build_ontology_review_package(
        document=_document(),
        result=DistillationResult(candidates=(_candidate(),)),
        context=_context(),
        extraction_run_id="run-1",
    )
    with pytest.raises(ValueError, match="summary MUST match"):
        replace(
            package,
            summary=replace(package.summary, total_claims=package.summary.total_claims + 1),
        )
