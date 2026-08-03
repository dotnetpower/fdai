"""Compile untrusted model candidates into typed ontology proposals."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.rule_catalog.pipeline.distill.ontology_identity import (
    EntityResolutionRequest,
    resolve_entity_identity,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    ClaimUnit,
    EntityResolution,
    OntologyChangeProposal,
    OntologyOperation,
    OntologyProperty,
    OntologyTargetKind,
    stable_digest,
)
from fdai.shared.providers.distiller import CandidateKind, DistilledCandidate

from .ontology_verify import VerificationContext

_COMMON_KEYS = frozenset(
    {
        "operation",
        "target_type",
        "target_identity",
        "authority",
        "source_assertion",
        "properties",
    }
)
_LINK_KEYS = _COMMON_KEYS | {"from_identity", "to_identity"}
_MAX_ASSERTION_CHARS = 16_384
_MAX_PROPERTIES = 64


@dataclass(frozen=True, slots=True)
class ProposalBuildIssue:
    candidate_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ProposalBuildResult:
    proposals: tuple[OntologyChangeProposal, ...] = ()
    issues: tuple[ProposalBuildIssue, ...] = ()


def build_ontology_proposals(
    *,
    candidates: Sequence[DistilledCandidate],
    claims: Sequence[ClaimUnit],
    extraction_run_id: str,
    ontology_release: str,
    expected_graph_revision: str,
    verification_context: VerificationContext | None = None,
) -> ProposalBuildResult:
    """Convert ontology candidates into immutable proposal contracts.

    Every candidate is untrusted model output. A malformed or unsupported
    candidate becomes a compact issue and produces no proposal.
    """
    claim_ids = [claim.claim_id for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claim ids MUST be unique for proposal compilation")

    proposals: list[OntologyChangeProposal] = []
    issues: list[ProposalBuildIssue] = []
    seen_candidate_ids: set[str] = set()

    for candidate in candidates:
        if candidate.kind not in {
            CandidateKind.ONTOLOGY_OBJECT,
            CandidateKind.ONTOLOGY_LINK,
        }:
            continue
        if candidate.candidate_id in seen_candidate_ids:
            issues.append(ProposalBuildIssue(candidate.candidate_id, "duplicate_candidate_id"))
            continue
        seen_candidate_ids.add(candidate.candidate_id)
        try:
            proposal = _build_one(
                candidate=candidate,
                claims=claims,
                extraction_run_id=extraction_run_id,
                ontology_release=ontology_release,
                expected_graph_revision=expected_graph_revision,
                verification_context=verification_context,
            )
        except (KeyError, TypeError, ValueError):
            issues.append(ProposalBuildIssue(candidate.candidate_id, "invalid_candidate_shape"))
            continue
        proposals.append(proposal)

    return ProposalBuildResult(proposals=tuple(proposals), issues=tuple(issues))


def _build_one(
    *,
    candidate: DistilledCandidate,
    claims: Sequence[ClaimUnit],
    extraction_run_id: str,
    ontology_release: str,
    expected_graph_revision: str,
    verification_context: VerificationContext | None,
) -> OntologyChangeProposal:
    body = candidate.body
    target_kind = (
        OntologyTargetKind.OBJECT
        if candidate.kind is CandidateKind.ONTOLOGY_OBJECT
        else OntologyTargetKind.LINK
    )
    allowed_keys = _COMMON_KEYS if target_kind is OntologyTargetKind.OBJECT else _LINK_KEYS
    if set(body) != allowed_keys:
        raise ValueError("ontology candidate body keys MUST match the strict shape")

    source_assertion = _require_string(body, "source_assertion")
    assertion_sha = hashlib.sha256(source_assertion.encode("utf-8")).hexdigest()
    matching_claims = [
        claim
        for claim in claims
        if claim.evidence.source_ref == candidate.source_ref
        and candidate.source_lines[0] <= claim.evidence.line_start
        and candidate.source_lines[1] >= claim.evidence.line_end
        and claim.evidence.text_sha256 == assertion_sha
    ]
    if len(matching_claims) != 1:
        raise ValueError("source assertion MUST resolve exactly one inventoried claim")
    claim = matching_claims[0]
    if candidate.content_sha != claim.evidence.content_sha256:
        raise ValueError("ontology candidate MUST pin the current document content digest")

    operation = OntologyOperation(_require_string(body, "operation"))
    target_type = _require_string(body, "target_type")
    supplied_target_identity = _require_string(body, "target_identity")
    authority = AuthorityClass(_require_string(body, "authority"))
    properties = _properties(body.get("properties"))
    from_identity = None
    to_identity = None
    if target_kind is OntologyTargetKind.LINK:
        from_identity = _require_string(body, "from_identity")
        to_identity = _require_string(body, "to_identity")

    if target_kind is OntologyTargetKind.OBJECT and verification_context is not None:
        entity_resolution = resolve_entity_identity(
            EntityResolutionRequest(
                supplied_identity=supplied_target_identity,
                target_type=target_type,
                operation=operation,
            ),
            entities=verification_context.entities,
            aliases=verification_context.aliases,
        )
    else:
        entity_resolution = EntityResolution(
            selected_identity=supplied_target_identity,
            candidates=(supplied_target_identity,),
            method="unverified",
        )
    target_identity = entity_resolution.selected_identity or supplied_target_identity

    proposal_material = {
        "source_ref": claim.evidence.source_ref,
        "content_sha256": claim.evidence.content_sha256,
        "claim_id": claim.claim_id,
        "operation": operation.value,
        "target_kind": target_kind.value,
        "target_type": target_type,
        "target_identity": target_identity,
        "authority": authority.value,
        "ontology_release": ontology_release,
        "expected_graph_revision": expected_graph_revision,
        "properties": [{"name": item.name, "value": item.value} for item in properties],
        "from_identity": from_identity,
        "to_identity": to_identity,
        "entity_resolution": {
            "selected_identity": entity_resolution.selected_identity,
            "candidates": list(entity_resolution.candidates),
            "method": entity_resolution.method,
        },
    }
    proposal_id = "odp-" + stable_digest(proposal_material)
    return OntologyChangeProposal(
        proposal_id=proposal_id,
        extraction_run_id=extraction_run_id,
        candidate_id=candidate.candidate_id,
        claim_id=claim.claim_id,
        operation=operation,
        target_kind=target_kind,
        target_type=target_type,
        target_identity=target_identity,
        ontology_release=ontology_release,
        expected_graph_revision=expected_graph_revision,
        authority=authority,
        evidence=claim.evidence,
        entity_resolution=entity_resolution,
        properties=properties,
        from_identity=from_identity,
        to_identity=to_identity,
    )


def _require_string(body: Mapping[str, object], key: str) -> str:
    value = body[key]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} MUST be a non-empty string")
    if key == "source_assertion" and len(value) > _MAX_ASSERTION_CHARS:
        raise ValueError("source_assertion exceeds the bounded extraction limit")
    return value


def _properties(value: object) -> tuple[OntologyProperty, ...]:
    if not isinstance(value, Mapping):
        raise TypeError("properties MUST be a mapping")
    if len(value) > _MAX_PROPERTIES:
        raise ValueError("ontology candidate exceeds the property-count limit")
    properties: list[OntologyProperty] = []
    for key, raw in value.items():
        if not isinstance(key, str) or not _is_scalar(raw):
            raise TypeError("ontology properties MUST contain scalar values")
        properties.append(OntologyProperty(name=key, value=raw))
    return tuple(sorted(properties, key=lambda item: item.name))


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


__all__ = ["ProposalBuildIssue", "ProposalBuildResult", "build_ontology_proposals"]
