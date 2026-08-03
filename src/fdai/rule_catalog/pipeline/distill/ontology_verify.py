"""Deterministic verification gates for ontology change proposals."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    ClaimUnit,
    GateOutcome,
    GateReceipt,
    OntologyChangeProposal,
    OntologyOperation,
    OntologyTargetKind,
    ProposalState,
    VerifiedOntologyProposal,
    stable_digest,
)

_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_UNIT = re.compile(r"(?:%|\bms\b|\busd\b|\bgb\b|\btb\b|\brto\b|\brpo\b)", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:not|never|deny|denied|prohibited|forbidden)\b", re.IGNORECASE)
_COMPARATOR = re.compile(
    r">=|<=|>|<|\bat\s+least\b|\bat\s+most\b|\babove\b|\bmore\s+than\b|"
    r"\bbelow\b|\bless\s+than\b",
    re.IGNORECASE,
)
_COMPARATOR_NORMALIZATION = {
    "at least": ">=",
    "at most": "<=",
    "above": ">",
    "more than": ">",
    "below": "<",
    "less than": "<",
}
_AUTHORITY_PROPERTIES = frozenset(
    {"permission", "permissions", "authorized", "autonomy", "executor", "approval"}
)
_CATALOG_TYPES = frozenset({"ActionType", "Policy", "Rule", "Workflow"})
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class LinkDeclaration:
    name: str
    from_type: str
    to_type: str

    def __post_init__(self) -> None:
        if not self.name or not self.from_type or not self.to_type:
            raise ValueError("link declaration identity and endpoints MUST be non-empty")


@dataclass(frozen=True, slots=True)
class EntityRecord:
    identity: str
    object_type: str

    def __post_init__(self) -> None:
        if not self.identity or not self.object_type:
            raise ValueError("entity identity and object_type MUST be non-empty")


@dataclass(frozen=True, slots=True)
class SourceAuthorityPolicy:
    source_ref: str
    allowed: frozenset[AuthorityClass]
    priority: int

    def __post_init__(self) -> None:
        if not self.source_ref:
            raise ValueError("source authority policy source_ref MUST be non-empty")
        if not self.allowed:
            raise ValueError("source authority policy MUST allow at least one authority class")
        if self.priority < 0:
            raise ValueError("source authority priority MUST be non-negative")


@dataclass(frozen=True, slots=True)
class ExternalEvidenceReceipt:
    claim_id: str
    authority: AuthorityClass
    target_identity: str
    evidence_ref: str
    source_revision: str
    observed_at: str
    freshness_policy_ref: str
    evidence_digest: str
    matched: bool
    fresh: bool

    def __post_init__(self) -> None:
        if (
            not self.claim_id
            or not self.target_identity
            or not self.evidence_ref
            or not self.source_revision
            or not self.observed_at
            or not self.freshness_policy_ref
        ):
            raise ValueError("external evidence identity and reference MUST be non-empty")
        if (
            len(self.evidence_ref) > 2048
            or len(self.source_revision) > 512
            or len(self.freshness_policy_ref) > 512
        ):
            raise ValueError("external evidence reference exceeds the bounded length")
        _require_rfc3339_utc(self.observed_at)
        if _SHA256.fullmatch(self.evidence_digest) is None:
            raise ValueError("external evidence digest MUST be a lowercase SHA-256 digest")
        if type(self.matched) is not bool or type(self.fresh) is not bool:
            raise ValueError("external evidence matched and fresh flags MUST be booleans")
        if self.authority not in {
            AuthorityClass.PROVIDER_OBSERVATION,
            AuthorityClass.TELEMETRY_OBSERVATION,
        }:
            raise ValueError("external evidence MUST use an observation authority class")


@dataclass(frozen=True, slots=True)
class ExistingFact:
    fact_key: str
    value_digest: str
    source_priority: int
    source_ref: str
    authority: AuthorityClass
    evidence_ref: str

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.fact_key) is None or _SHA256.fullmatch(self.value_digest) is None:
            raise ValueError("existing fact key and value digest MUST be SHA-256 digests")
        if not self.source_ref or not self.evidence_ref:
            raise ValueError("existing fact source and evidence refs MUST be non-empty")
        if self.source_priority < 0:
            raise ValueError("existing fact source priority MUST be non-negative")


@dataclass(frozen=True, slots=True)
class VerificationContext:
    ontology_release: str
    current_graph_revision: str
    object_types: frozenset[str]
    links: tuple[LinkDeclaration, ...]
    entities: tuple[EntityRecord, ...]
    source_policies: tuple[SourceAuthorityPolicy, ...]
    claim_text: tuple[tuple[str, str], ...]
    external_evidence: tuple[ExternalEvidenceReceipt, ...] = ()
    existing_facts: tuple[ExistingFact, ...] = ()

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.ontology_release) is None:
            raise ValueError("verification ontology_release MUST be a SHA-256 digest")
        if not self.current_graph_revision.strip() or len(self.current_graph_revision) > 200:
            raise ValueError("verification graph revision MUST be bounded and non-empty")
        if any(not item or len(item) > 200 for item in self.object_types):
            raise ValueError("verification object type names MUST be bounded and non-empty")
        if len(self.object_types) > 10_000:
            raise ValueError("verification object type count exceeds the bounded limit")
        if len(self.links) > 10_000:
            raise ValueError("verification link count exceeds the bounded limit")
        if len(self.entities) > 100_000:
            raise ValueError("verification entity count exceeds the bounded limit")
        if len(self.external_evidence) > 10_000 or len(self.existing_facts) > 100_000:
            raise ValueError("verification evidence count exceeds the bounded limit")
        _require_unique((link.name for link in self.links), "link declarations")
        _require_unique((entity.identity for entity in self.entities), "entity records")
        _require_unique((policy.source_ref for policy in self.source_policies), "source policies")
        _require_unique((claim_id for claim_id, _ in self.claim_text), "claim text records")
        unknown_entity_types = {
            entity.object_type
            for entity in self.entities
            if entity.object_type not in self.object_types
        }
        if unknown_entity_types:
            raise ValueError("entity records MUST reference declared object types")
        if any(
            link.from_type not in self.object_types or link.to_type not in self.object_types
            for link in self.links
        ):
            raise ValueError("link endpoints MUST reference declared object types")


def verify_ontology_proposal(
    proposal: OntologyChangeProposal,
    claim: ClaimUnit,
    context: VerificationContext,
) -> VerifiedOntologyProposal:
    """Evaluate a proposal through ordered deterministic gates."""
    receipts = (
        _shape_gate(proposal, context),
        _grounding_gate(proposal, claim, context),
        _semantic_gate(proposal, claim, context),
        _identity_gate(proposal, context),
        _authority_gate(proposal, claim, context),
        _conflict_gate(proposal, context),
        _external_truth_gate(proposal, context),
        _safety_gate(proposal),
    )
    if any(receipt.outcome is GateOutcome.DENY for receipt in receipts):
        state = ProposalState.DENIED
        return VerifiedOntologyProposal(proposal=proposal, state=state, receipts=receipts)

    promotion = GateReceipt(
        gate="promotion_policy",
        outcome=GateOutcome.REVIEW,
        reason_codes=("review_only",),
    )
    return VerifiedOntologyProposal(
        proposal=proposal,
        state=ProposalState.REVIEW_REQUIRED,
        receipts=receipts + (promotion,),
    )


def proposal_fact_key(proposal: OntologyChangeProposal) -> str:
    return stable_digest(
        {
            "target_kind": proposal.target_kind.value,
            "target_type": proposal.target_type,
            "target_identity": proposal.target_identity,
            "from_identity": proposal.from_identity,
            "to_identity": proposal.to_identity,
            "property_names": sorted(item.name for item in proposal.properties),
        }
    )


def proposal_value_digest(proposal: OntologyChangeProposal) -> str:
    return stable_digest([{"name": item.name, "value": item.value} for item in proposal.properties])


def _shape_gate(proposal: OntologyChangeProposal, context: VerificationContext) -> GateReceipt:
    deny_reasons: list[str] = []
    review_reasons: list[str] = []
    if proposal.ontology_release != context.ontology_release:
        deny_reasons.append("ontology_release_mismatch")
    if proposal.expected_graph_revision != context.current_graph_revision:
        review_reasons.append("stale_graph_revision")
    if proposal.target_kind is OntologyTargetKind.OBJECT:
        if proposal.target_type not in context.object_types:
            deny_reasons.append("unknown_object_type")
    elif not any(link.name == proposal.target_type for link in context.links):
        deny_reasons.append("unknown_link_type")
    if deny_reasons:
        return _receipt("shape", GateOutcome.DENY, deny_reasons + review_reasons)
    if review_reasons:
        return _receipt("shape", GateOutcome.REVIEW, review_reasons)
    return _receipt("shape", GateOutcome.PASS)


def _grounding_gate(
    proposal: OntologyChangeProposal,
    claim: ClaimUnit,
    context: VerificationContext,
) -> GateReceipt:
    claim_text = dict(context.claim_text).get(claim.claim_id)
    reasons: list[str] = []
    if proposal.claim_id != claim.claim_id or proposal.evidence != claim.evidence:
        reasons.append("claim_evidence_mismatch")
    if claim_text is None:
        reasons.append("claim_text_missing")
    elif hashlib.sha256(claim_text.encode("utf-8")).hexdigest() != claim.evidence.text_sha256:
        reasons.append("claim_text_digest_mismatch")
    return _receipt("grounding", GateOutcome.DENY if reasons else GateOutcome.PASS, reasons)


def _semantic_gate(
    proposal: OntologyChangeProposal,
    claim: ClaimUnit,
    context: VerificationContext,
) -> GateReceipt:
    source = dict(context.claim_text).get(claim.claim_id, "")
    candidate = " ".join(str(item.value) for item in proposal.properties)
    source_signature = _semantic_signature(source)
    candidate_signature = _semantic_signature(candidate)
    if source_signature != candidate_signature and any(source_signature):
        return _receipt("semantic_fidelity", GateOutcome.REVIEW, ["semantic_signature_mismatch"])
    return _receipt("semantic_fidelity", GateOutcome.PASS)


def _identity_gate(proposal: OntologyChangeProposal, context: VerificationContext) -> GateReceipt:
    entities = {entity.identity: entity.object_type for entity in context.entities}
    reasons: list[str] = []
    outcome = GateOutcome.PASS
    if proposal.entity_resolution.selected_identity != proposal.target_identity:
        return _receipt("identity", GateOutcome.DENY, ["resolution_target_mismatch"])
    if proposal.target_kind is OntologyTargetKind.OBJECT:
        resolved_type = entities.get(proposal.target_identity)
        if resolved_type is None:
            reason = (
                "new_identity_requires_review"
                if proposal.operation is OntologyOperation.ADD
                else "existing_target_not_found"
            )
            reasons.append(reason)
            outcome = GateOutcome.REVIEW
        elif resolved_type != proposal.target_type:
            reasons.append("target_type_mismatch")
            outcome = GateOutcome.DENY
        elif proposal.operation is OntologyOperation.ADD:
            reasons.append("add_target_already_exists")
            outcome = GateOutcome.REVIEW
    else:
        declaration = next(
            (link for link in context.links if link.name == proposal.target_type),
            None,
        )
        if declaration is None:
            return _receipt("identity", GateOutcome.DENY, ["link_declaration_missing"])
        if entities.get(proposal.from_identity or "") != declaration.from_type:
            reasons.append("from_identity_type_mismatch")
        if entities.get(proposal.to_identity or "") != declaration.to_type:
            reasons.append("to_identity_type_mismatch")
        if reasons:
            outcome = GateOutcome.DENY
    return _receipt("identity", outcome, reasons)


def _authority_gate(
    proposal: OntologyChangeProposal,
    claim: ClaimUnit,
    context: VerificationContext,
) -> GateReceipt:
    policy = next(
        (
            item
            for item in context.source_policies
            if item.source_ref == proposal.evidence.source_ref
        ),
        None,
    )
    reasons: list[str] = []
    if proposal.authority is AuthorityClass.EXECUTION_AUTHORITY:
        reasons.append("document_cannot_grant_execution_authority")
    if proposal.authority is not claim.authority:
        reasons.append("claim_authority_mismatch")
    if policy is None or proposal.authority not in policy.allowed:
        reasons.append("source_not_authoritative")
    return _receipt("authority", GateOutcome.DENY if reasons else GateOutcome.PASS, reasons)


def _conflict_gate(
    proposal: OntologyChangeProposal,
    context: VerificationContext,
) -> GateReceipt:
    policy = next(
        (
            item
            for item in context.source_policies
            if item.source_ref == proposal.evidence.source_ref
        ),
        None,
    )
    if policy is None:
        return _receipt("conflict", GateOutcome.REVIEW, ["source_priority_unknown"])
    key = proposal_fact_key(proposal)
    value = proposal_value_digest(proposal)
    conflicts = [
        fact
        for fact in context.existing_facts
        if fact.fact_key == key and fact.value_digest != value
    ]
    if not conflicts:
        return _receipt("conflict", GateOutcome.PASS)
    if any(fact.source_priority >= policy.priority for fact in conflicts):
        return _receipt(
            "conflict",
            GateOutcome.REVIEW,
            ["authoritative_conflict"],
            evidence_refs=tuple(sorted(fact.evidence_ref for fact in conflicts)),
        )
    return _receipt("conflict", GateOutcome.PASS, evidence_refs=("lower_priority_conflict",))


def _external_truth_gate(
    proposal: OntologyChangeProposal,
    context: VerificationContext,
) -> GateReceipt:
    if proposal.authority not in {
        AuthorityClass.PROVIDER_OBSERVATION,
        AuthorityClass.TELEMETRY_OBSERVATION,
    }:
        return _receipt("external_truth", GateOutcome.PASS)
    matching = [
        receipt
        for receipt in context.external_evidence
        if receipt.claim_id == proposal.claim_id
        and receipt.authority is proposal.authority
        and receipt.target_identity == proposal.target_identity
        and receipt.matched
        and receipt.fresh
    ]
    if not matching:
        return _receipt("external_truth", GateOutcome.REVIEW, ["fresh_authority_evidence_missing"])
    return _receipt(
        "external_truth",
        GateOutcome.PASS,
        evidence_refs=tuple(sorted(receipt.evidence_ref for receipt in matching)),
    )


def _safety_gate(proposal: OntologyChangeProposal) -> GateReceipt:
    reasons: list[str] = []
    if proposal.target_type in _CATALOG_TYPES:
        reasons.append("catalog_change_requires_dedicated_pipeline")
    if any(item.name in _AUTHORITY_PROPERTIES for item in proposal.properties):
        reasons.append("authority_property_not_allowed")
    if reasons:
        return _receipt("safety", GateOutcome.DENY, reasons)
    if proposal.operation in {OntologyOperation.REMOVE, OntologyOperation.SUPERSEDE}:
        return _receipt("safety", GateOutcome.REVIEW, ["destructive_graph_change"])
    return _receipt("safety", GateOutcome.PASS)


def _semantic_signature(
    text: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], bool]:
    numbers = tuple(_NUMBER.findall(text.lower()))
    units = tuple(match.lower() for match in _UNIT.findall(text))
    comparators = tuple(
        _COMPARATOR_NORMALIZATION.get(match.group(0).lower(), match.group(0))
        for match in _COMPARATOR.finditer(text)
    )
    return numbers, units, comparators, _NEGATION.search(text) is not None


def _receipt(
    gate: str,
    outcome: GateOutcome,
    reasons: list[str] | None = None,
    *,
    evidence_refs: tuple[str, ...] = (),
) -> GateReceipt:
    return GateReceipt(
        gate=gate,
        outcome=outcome,
        reason_codes=tuple(reasons or ()),
        evidence_refs=evidence_refs,
    )


def _require_unique(values: Iterable[str], label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} MUST be unique")


def _require_rfc3339_utc(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("external evidence observed_at MUST be RFC 3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("external evidence observed_at MUST use UTC")


__all__ = [
    "EntityRecord",
    "ExistingFact",
    "ExternalEvidenceReceipt",
    "LinkDeclaration",
    "SourceAuthorityPolicy",
    "VerificationContext",
    "proposal_fact_key",
    "proposal_value_digest",
    "verify_ontology_proposal",
]
