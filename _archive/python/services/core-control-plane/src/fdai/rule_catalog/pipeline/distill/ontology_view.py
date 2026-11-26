"""JSON-safe reviewer projection for ontology distillation packages."""

from __future__ import annotations

from fdai.rule_catalog.pipeline.distill.ontology_review import OntologyReviewPackage


def build_ontology_review_view(package: OntologyReviewPackage) -> dict[str, object]:
    """Render evidence and graph diffs without embedding document text."""
    claim_by_id = {claim.claim_id: claim for claim in package.claims}
    return {
        "package_digest": package.package_digest,
        "document": {
            "document_id": package.document_id,
            "source_ref": package.source_ref,
            "access_policy_ref": package.access_policy_ref,
            "content_sha256": package.content_sha256,
            "extraction_run_id": package.extraction_run_id,
        },
        "target": {
            "ontology_release": package.ontology_release,
            "expected_graph_revision": package.expected_graph_revision,
        },
        "summary": {
            "total_claims": package.summary.total_claims,
            "critical_claims": package.summary.critical_claims,
            "mapped_claims": package.summary.mapped_claims,
            "unresolved_claims": package.summary.unresolved_claims,
            "proposals": package.summary.proposals,
            "denied_proposals": package.summary.denied_proposals,
            "review_proposals": package.summary.review_proposals,
        },
        "claims": [
            {
                "claim_id": claim.claim_id,
                "kind": claim.kind.value,
                "authority": claim.authority.value,
                "critical": claim.critical,
                "source_ref": claim.evidence.source_ref,
                "document_revision": claim.evidence.document_revision,
                "line_start": claim.evidence.line_start,
                "line_end": claim.evidence.line_end,
                "text_sha256": claim.evidence.text_sha256,
                "disposition": resolution.disposition.value,
                "candidate_ids": list(resolution.candidate_ids),
                "reason_code": resolution.reason_code,
            }
            for resolution in package.resolutions
            for claim in (claim_by_id[resolution.claim_id],)
        ],
        "proposals": [
            {
                "proposal_id": item.proposal.proposal_id,
                "proposal_digest": item.proposal.digest,
                "candidate_id": item.proposal.candidate_id,
                "claim_id": item.proposal.claim_id,
                "state": item.state.value,
                "operation": item.proposal.operation.value,
                "target_kind": item.proposal.target_kind.value,
                "target_type": item.proposal.target_type,
                "target_identity": item.proposal.target_identity,
                "from_identity": item.proposal.from_identity,
                "to_identity": item.proposal.to_identity,
                "properties": [
                    {"name": prop.name, "value": prop.value} for prop in item.proposal.properties
                ],
                "gates": [
                    {
                        "gate": receipt.gate,
                        "outcome": receipt.outcome.value,
                        "reason_codes": list(receipt.reason_codes),
                        "evidence_refs": list(receipt.evidence_refs),
                    }
                    for receipt in item.receipts
                ],
            }
            for item in package.proposals
        ],
        "issues": [
            {
                "reason_code": issue.reason_code,
                "claim_id": issue.claim_id,
                "candidate_id": issue.candidate_id,
                "proposal_id": issue.proposal_id,
                "critical": issue.critical,
            }
            for issue in package.issues
        ],
    }


__all__ = ["build_ontology_review_view"]
