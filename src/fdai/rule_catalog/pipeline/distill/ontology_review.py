"""Assemble review-only document ontology packages."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from fdai.rule_catalog.pipeline.distill.ontology_build import build_ontology_proposals
from fdai.rule_catalog.pipeline.distill.ontology_claims import (
    claim_text_records,
    document_content_digest,
    inventory_claims,
    reconcile_claims,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    ClaimDisposition,
    ClaimResolution,
    ClaimUnit,
    ProposalState,
    VerifiedOntologyProposal,
    stable_digest,
)
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    VerificationContext,
    verify_ontology_proposal,
)
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistillationResult,
    ManualDocument,
)

_ONTOLOGY_KINDS = frozenset({CandidateKind.ONTOLOGY_OBJECT, CandidateKind.ONTOLOGY_LINK})
_MAX_CLAIMS = 10_000
_MAX_CANDIDATES = 5_000
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class OntologyReviewIssue:
    reason_code: str
    claim_id: str | None = None
    candidate_id: str | None = None
    proposal_id: str | None = None
    critical: bool = False


@dataclass(frozen=True, slots=True)
class OntologyReviewSummary:
    total_claims: int
    critical_claims: int
    mapped_claims: int
    unresolved_claims: int
    proposals: int
    denied_proposals: int
    review_proposals: int


@dataclass(frozen=True, slots=True)
class OntologyReviewPackage:
    document_id: str
    source_ref: str
    access_policy_ref: str
    content_sha256: str
    extraction_run_id: str
    ontology_release: str
    expected_graph_revision: str
    claims: tuple[ClaimUnit, ...]
    resolutions: tuple[ClaimResolution, ...]
    proposals: tuple[VerifiedOntologyProposal, ...]
    issues: tuple[OntologyReviewIssue, ...]
    summary: OntologyReviewSummary

    def __post_init__(self) -> None:
        if (
            not self.document_id.strip()
            or not self.source_ref.strip()
            or not self.access_policy_ref.strip()
        ):
            raise ValueError("ontology review document identity and access policy MUST be present")
        if (
            len(self.document_id) > 1024
            or len(self.source_ref) > 2048
            or len(self.access_policy_ref) > 2048
        ):
            raise ValueError("ontology review document reference exceeds the bounded length")
        if _SHA256.fullmatch(self.content_sha256) is None:
            raise ValueError("ontology review content_sha256 MUST be a SHA-256 digest")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("ontology review claim ids MUST be unique")
        resolution_ids = [resolution.claim_id for resolution in self.resolutions]
        if sorted(resolution_ids) != sorted(claim_ids):
            raise ValueError("ontology review resolutions MUST cover every claim exactly once")
        proposal_ids = [item.proposal.proposal_id for item in self.proposals]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("ontology review proposal ids MUST be unique")
        expected_summary = OntologyReviewSummary(
            total_claims=len(self.claims),
            critical_claims=sum(claim.critical for claim in self.claims),
            mapped_claims=sum(
                item.disposition is ClaimDisposition.MAPPED for item in self.resolutions
            ),
            unresolved_claims=sum(
                item.disposition is not ClaimDisposition.MAPPED for item in self.resolutions
            ),
            proposals=len(self.proposals),
            denied_proposals=sum(item.state is ProposalState.DENIED for item in self.proposals),
            review_proposals=sum(
                item.state is ProposalState.REVIEW_REQUIRED for item in self.proposals
            ),
        )
        if self.summary != expected_summary:
            raise ValueError("ontology review summary MUST match package contents")

    @property
    def package_digest(self) -> str:
        return stable_digest(
            {
                "document_id": self.document_id,
                "source_ref": self.source_ref,
                "access_policy_ref": self.access_policy_ref,
                "content_sha256": self.content_sha256,
                "extraction_run_id": self.extraction_run_id,
                "ontology_release": self.ontology_release,
                "expected_graph_revision": self.expected_graph_revision,
                "claims": [claim.claim_id for claim in self.claims],
                "resolutions": [
                    {
                        "claim_id": item.claim_id,
                        "disposition": item.disposition.value,
                        "candidate_ids": list(item.candidate_ids),
                        "reason_code": item.reason_code,
                    }
                    for item in self.resolutions
                ],
                "proposals": [item.verification_digest for item in self.proposals],
                "issues": [
                    {
                        "reason_code": issue.reason_code,
                        "claim_id": issue.claim_id,
                        "candidate_id": issue.candidate_id,
                        "proposal_id": issue.proposal_id,
                        "critical": issue.critical,
                    }
                    for issue in self.issues
                ],
            }
        )


def build_ontology_review_package(
    *,
    document: ManualDocument,
    result: DistillationResult,
    context: VerificationContext,
    extraction_run_id: str,
) -> OntologyReviewPackage:
    """Build one immutable review package from untrusted distiller output."""
    access_policy_ref = document.metadata.get("access_policy_ref", "")
    if not access_policy_ref:
        raise ValueError("ontology review requires a source access_policy_ref")
    if len(result.candidates) > _MAX_CANDIDATES:
        raise ValueError("ontology review candidate count exceeds the bounded limit")
    claims = inventory_claims(document)
    if len(claims) > _MAX_CLAIMS:
        raise ValueError("ontology review claim count exceeds the bounded limit")
    enriched_context = replace(context, claim_text=claim_text_records(document, claims))
    built = build_ontology_proposals(
        candidates=result.candidates,
        claims=claims,
        extraction_run_id=extraction_run_id,
        ontology_release=context.ontology_release,
        expected_graph_revision=context.current_graph_revision,
    )

    valid_candidate_ids = {proposal.candidate_id for proposal in built.proposals}
    accounting_candidates = tuple(
        candidate
        for candidate in result.candidates
        if candidate.kind not in _ONTOLOGY_KINDS or candidate.candidate_id in valid_candidate_ids
    )
    resolutions = reconcile_claims(
        claims,
        accounting_candidates,
        exact_candidate_claims={
            proposal.candidate_id: proposal.claim_id for proposal in built.proposals
        },
    )
    claim_by_id = {claim.claim_id: claim for claim in claims}

    issues = [
        OntologyReviewIssue(reason_code=issue.reason_code, candidate_id=issue.candidate_id)
        for issue in built.issues
    ]
    for resolution in resolutions:
        if resolution.disposition is ClaimDisposition.MAPPED:
            continue
        claim = claim_by_id[resolution.claim_id]
        issues.append(
            OntologyReviewIssue(
                reason_code=resolution.reason_code,
                claim_id=resolution.claim_id,
                critical=claim.critical,
            )
        )

    verified: list[VerifiedOntologyProposal] = []
    seen_proposal_ids: set[str] = set()
    for proposal in built.proposals:
        if proposal.proposal_id in seen_proposal_ids:
            issues.append(
                OntologyReviewIssue(
                    reason_code="duplicate_proposal_id",
                    claim_id=proposal.claim_id,
                    candidate_id=proposal.candidate_id,
                    proposal_id=proposal.proposal_id,
                    critical=claim_by_id[proposal.claim_id].critical,
                )
            )
            continue
        seen_proposal_ids.add(proposal.proposal_id)
        checked = verify_ontology_proposal(
            proposal,
            claim_by_id[proposal.claim_id],
            enriched_context,
        )
        verified.append(checked)
        if checked.state is ProposalState.DENIED:
            issues.append(
                OntologyReviewIssue(
                    reason_code="proposal_denied",
                    claim_id=proposal.claim_id,
                    candidate_id=proposal.candidate_id,
                    proposal_id=proposal.proposal_id,
                    critical=claim_by_id[proposal.claim_id].critical,
                )
            )

    summary = OntologyReviewSummary(
        total_claims=len(claims),
        critical_claims=sum(claim.critical for claim in claims),
        mapped_claims=sum(
            resolution.disposition is ClaimDisposition.MAPPED for resolution in resolutions
        ),
        unresolved_claims=sum(
            resolution.disposition is not ClaimDisposition.MAPPED for resolution in resolutions
        ),
        proposals=len(verified),
        denied_proposals=sum(item.state is ProposalState.DENIED for item in verified),
        review_proposals=sum(item.state is ProposalState.REVIEW_REQUIRED for item in verified),
    )
    return OntologyReviewPackage(
        document_id=document.doc_id,
        source_ref=document.source_ref,
        access_policy_ref=access_policy_ref,
        content_sha256=document_content_digest(document),
        extraction_run_id=extraction_run_id,
        ontology_release=context.ontology_release,
        expected_graph_revision=context.current_graph_revision,
        claims=claims,
        resolutions=resolutions,
        proposals=tuple(verified),
        issues=tuple(issues),
        summary=summary,
    )


__all__ = [
    "OntologyReviewIssue",
    "OntologyReviewPackage",
    "OntologyReviewSummary",
    "build_ontology_review_package",
]
