"""Immutable contracts for document-to-ontology change proposals.

These records are build-time, proposal-only values. They carry no executor
identity and expose no graph mutation method. Deterministic builders and gates
in sibling modules are responsible for producing and evaluating them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

type Scalar = str | int | float | bool | None

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,199}$")
_PROPERTY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_PROPERTY_STRING = 4096


class ClaimKind(StrEnum):
    NORMATIVE = "normative"
    THRESHOLD = "threshold"
    ENTITY = "entity"
    RELATIONSHIP = "relationship"
    PROCEDURE = "procedure"
    OBSERVATION = "observation"
    HISTORY = "history"


class AuthorityClass(StrEnum):
    DECLARED_INTENT = "declared_intent"
    PROCEDURE = "procedure"
    HISTORICAL_EVIDENCE = "historical_evidence"
    PROVIDER_OBSERVATION = "provider_observation"
    TELEMETRY_OBSERVATION = "telemetry_observation"
    EXECUTION_AUTHORITY = "execution_authority"


class ClaimDisposition(StrEnum):
    MAPPED = "mapped"
    IGNORED_WITH_REASON = "ignored_with_reason"
    NEEDS_REVIEW = "needs_review"


class OntologyOperation(StrEnum):
    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    SUPERSEDE = "supersede"


class OntologyTargetKind(StrEnum):
    OBJECT = "object"
    LINK = "link"


class ProposalState(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    PROJECTED = "projected"
    RECONCILED = "reconciled"
    DENIED = "denied"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


class GateOutcome(StrEnum):
    PASS = "pass"  # noqa: S105 - verification outcome, not a credential
    REVIEW = "review"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    source_ref: str
    document_id: str
    document_revision: str
    content_sha256: str
    line_start: int
    line_end: int
    text_sha256: str

    def __post_init__(self) -> None:
        if (
            not self.source_ref.strip()
            or not self.document_id.strip()
            or not self.document_revision.strip()
        ):
            raise ValueError("source evidence identity fields MUST be non-empty")
        if len(self.source_ref) > 2048 or len(self.document_id) > 1024:
            raise ValueError("source evidence reference exceeds the bounded length")
        if len(self.document_revision) > 512:
            raise ValueError("source evidence revision exceeds the bounded length")
        _require_digest(self.content_sha256, "content_sha256")
        _require_digest(self.text_sha256, "text_sha256")
        if self.line_start < 1 or self.line_end < self.line_start:
            raise ValueError("source evidence lines MUST be a 1-based inclusive range")


@dataclass(frozen=True, slots=True)
class ClaimUnit:
    claim_id: str
    kind: ClaimKind
    authority: AuthorityClass
    evidence: SourceEvidence
    critical: bool

    def __post_init__(self) -> None:
        _require_identifier(self.claim_id, "claim_id")


@dataclass(frozen=True, slots=True)
class ClaimResolution:
    claim_id: str
    disposition: ClaimDisposition
    candidate_ids: tuple[str, ...] = ()
    reason_code: str = ""

    def __post_init__(self) -> None:
        _require_identifier(self.claim_id, "claim_id")
        if self.disposition is ClaimDisposition.MAPPED and not self.candidate_ids:
            raise ValueError("mapped claim resolution MUST name at least one candidate")
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("mapped candidate ids MUST be unique")
        for candidate_id in self.candidate_ids:
            _require_identifier(candidate_id, "candidate_id")
        if self.disposition is not ClaimDisposition.MAPPED and self.candidate_ids:
            raise ValueError("unmapped claim resolution MUST NOT name candidates")
        if self.disposition is not ClaimDisposition.MAPPED and not self.reason_code:
            raise ValueError("unmapped claim resolution MUST include a reason_code")


@dataclass(frozen=True, slots=True)
class OntologyProperty:
    name: str
    value: Scalar

    def __post_init__(self) -> None:
        if _PROPERTY.fullmatch(self.name) is None:
            raise ValueError(f"invalid ontology property name: {self.name!r}")
        if isinstance(self.value, float) and not (-float("inf") < self.value < float("inf")):
            raise ValueError("ontology property float MUST be finite")
        if isinstance(self.value, str) and len(self.value) > _MAX_PROPERTY_STRING:
            raise ValueError("ontology property string MUST be at most 4096 characters")
        if (
            isinstance(self.value, int)
            and not isinstance(self.value, bool)
            and abs(self.value) > 10**18
        ):
            raise ValueError("ontology property integer MUST fit the signed 64-bit value envelope")


@dataclass(frozen=True, slots=True)
class EntityResolution:
    selected_identity: str | None = None
    candidates: tuple[str, ...] = ()
    method: str = "unresolved"

    def __post_init__(self) -> None:
        if len(self.candidates) > 32:
            raise ValueError("entity resolution candidates MUST be bounded to 32")
        if self.selected_identity is not None:
            _require_identifier(self.selected_identity, "selected_identity")
            if self.candidates and self.selected_identity not in self.candidates:
                raise ValueError("selected identity MUST be present in bounded candidates")
        if len(self.candidates) != len(set(self.candidates)):
            raise ValueError("entity resolution candidates MUST be unique")
        for candidate in self.candidates:
            _require_identifier(candidate, "entity candidate")
        if _PROPERTY.fullmatch(self.method) is None:
            raise ValueError(f"invalid entity resolution method: {self.method!r}")


@dataclass(frozen=True, slots=True)
class OntologyChangeProposal:
    proposal_id: str
    extraction_run_id: str
    candidate_id: str
    claim_id: str
    operation: OntologyOperation
    target_kind: OntologyTargetKind
    target_type: str
    target_identity: str
    ontology_release: str
    expected_graph_revision: str
    authority: AuthorityClass
    evidence: SourceEvidence
    entity_resolution: EntityResolution
    properties: tuple[OntologyProperty, ...] = ()
    from_identity: str | None = None
    to_identity: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.proposal_id, "proposal_id")
        _require_identifier(self.extraction_run_id, "extraction_run_id")
        _require_identifier(self.candidate_id, "candidate_id")
        _require_identifier(self.claim_id, "claim_id")
        _require_identifier(self.target_type, "target_type")
        _require_identifier(self.target_identity, "target_identity")
        _require_digest(self.ontology_release, "ontology_release")
        _require_identifier(self.expected_graph_revision, "expected_graph_revision")
        names = [item.name for item in self.properties]
        if len(names) != len(set(names)):
            raise ValueError("ontology proposal property names MUST be unique")
        if self.target_kind is OntologyTargetKind.LINK:
            if self.from_identity is None or self.to_identity is None:
                raise ValueError("link proposal MUST name from_identity and to_identity")
            _require_identifier(self.from_identity, "from_identity")
            _require_identifier(self.to_identity, "to_identity")
        elif self.from_identity is not None or self.to_identity is not None:
            raise ValueError("object proposal MUST NOT name link endpoints")

    @property
    def digest(self) -> str:
        return stable_digest(_proposal_payload(self))


@dataclass(frozen=True, slots=True)
class GateReceipt:
    gate: str
    outcome: GateOutcome
    reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _PROPERTY.fullmatch(self.gate) is None:
            raise ValueError(f"invalid gate name: {self.gate!r}")
        if self.outcome is not GateOutcome.PASS and not self.reason_codes:
            raise ValueError("non-passing gate receipt MUST include a reason code")


@dataclass(frozen=True, slots=True)
class VerifiedOntologyProposal:
    proposal: OntologyChangeProposal
    state: ProposalState
    receipts: tuple[GateReceipt, ...]

    def __post_init__(self) -> None:
        if not self.receipts:
            raise ValueError("verified proposal MUST contain gate receipts")
        outcomes = {receipt.outcome for receipt in self.receipts}
        if GateOutcome.DENY in outcomes and self.state is not ProposalState.DENIED:
            raise ValueError("a denied gate MUST produce a denied proposal")
        if GateOutcome.DENY not in outcomes and self.state is ProposalState.DENIED:
            raise ValueError("a denied proposal MUST contain a denied gate")
        if GateOutcome.REVIEW in outcomes and self.state not in {
            ProposalState.REVIEW_REQUIRED,
            ProposalState.DENIED,
        }:
            raise ValueError("a review gate MUST keep the proposal in review")

    @property
    def verification_digest(self) -> str:
        return stable_digest(
            {
                "proposal_digest": self.proposal.digest,
                "state": self.state.value,
                "receipts": [
                    {
                        "gate": receipt.gate,
                        "outcome": receipt.outcome.value,
                        "reason_codes": list(receipt.reason_codes),
                        "evidence_refs": list(receipt.evidence_refs),
                    }
                    for receipt in self.receipts
                ],
            }
        )


def stable_digest(value: object) -> str:
    """Return a replay-stable SHA-256 digest for JSON-compatible values."""
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _proposal_payload(proposal: OntologyChangeProposal) -> dict[str, object]:
    return {
        "proposal_id": proposal.proposal_id,
        "extraction_run_id": proposal.extraction_run_id,
        "candidate_id": proposal.candidate_id,
        "claim_id": proposal.claim_id,
        "operation": proposal.operation.value,
        "target_kind": proposal.target_kind.value,
        "target_type": proposal.target_type,
        "target_identity": proposal.target_identity,
        "ontology_release": proposal.ontology_release,
        "expected_graph_revision": proposal.expected_graph_revision,
        "authority": proposal.authority.value,
        "evidence": {
            "source_ref": proposal.evidence.source_ref,
            "document_id": proposal.evidence.document_id,
            "document_revision": proposal.evidence.document_revision,
            "content_sha256": proposal.evidence.content_sha256,
            "line_start": proposal.evidence.line_start,
            "line_end": proposal.evidence.line_end,
            "text_sha256": proposal.evidence.text_sha256,
        },
        "entity_resolution": {
            "selected_identity": proposal.entity_resolution.selected_identity,
            "candidates": list(proposal.entity_resolution.candidates),
            "method": proposal.entity_resolution.method,
        },
        "properties": [
            {"name": item.name, "value": item.value}
            for item in sorted(proposal.properties, key=lambda item: item.name)
        ],
        "from_identity": proposal.from_identity,
        "to_identity": proposal.to_identity,
    }


def _require_digest(value: str, field_name: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field_name} MUST be a lowercase SHA-256 digest")


def _require_identifier(value: str, field_name: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"invalid {field_name}: {value!r}")


__all__ = [
    "AuthorityClass",
    "ClaimDisposition",
    "ClaimKind",
    "ClaimResolution",
    "ClaimUnit",
    "EntityResolution",
    "GateOutcome",
    "GateReceipt",
    "OntologyChangeProposal",
    "OntologyOperation",
    "OntologyProperty",
    "OntologyTargetKind",
    "ProposalState",
    "SourceEvidence",
    "VerifiedOntologyProposal",
    "stable_digest",
]
