"""Proposal-only lifecycle, projection, retirement, and rollback plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from fdai.rule_catalog.pipeline.distill.freshness import RetirementRequest
from fdai.rule_catalog.pipeline.distill.ontology_models import (
    ProposalState,
    VerifiedOntologyProposal,
    stable_digest,
)

_TRANSITIONS: dict[ProposalState, frozenset[ProposalState]] = {
    ProposalState.REVIEW_REQUIRED: frozenset({ProposalState.APPROVED, ProposalState.REJECTED}),
    ProposalState.APPROVED: frozenset({ProposalState.PROJECTED, ProposalState.REJECTED}),
    ProposalState.PROJECTED: frozenset(
        {ProposalState.RECONCILED, ProposalState.ROLLED_BACK, ProposalState.SUPERSEDED}
    ),
    ProposalState.RECONCILED: frozenset({ProposalState.ROLLED_BACK, ProposalState.SUPERSEDED}),
}
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ReconciliationOutcome(StrEnum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    STALE = "stale"
    UNSCORABLE = "unscorable"


@dataclass(frozen=True, slots=True)
class ProposalLifecycleRecord:
    proposal_digest: str
    state: ProposalState
    revision: int
    current_graph_revision: str
    rollback_graph_revision: str | None = None
    transition_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.proposal_digest) is None:
            raise ValueError("proposal lifecycle digest MUST be a lowercase SHA-256 digest")
        if self.revision < 1:
            raise ValueError("proposal lifecycle revision MUST be positive")
        if not self.current_graph_revision:
            raise ValueError("current graph revision MUST be non-empty")
        if any(not ref for ref in self.transition_refs):
            raise ValueError("proposal lifecycle transition refs MUST be non-empty")
        if len(self.transition_refs) != len(set(self.transition_refs)):
            raise ValueError("proposal lifecycle transition refs MUST be unique")


@dataclass(frozen=True, slots=True)
class ProjectionPlan:
    proposal_digest: str
    expected_graph_revision: str
    next_graph_revision: str
    rollback_graph_revision: str
    transition_ref: str

    @property
    def plan_digest(self) -> str:
        return stable_digest(
            {
                "proposal_digest": self.proposal_digest,
                "expected_graph_revision": self.expected_graph_revision,
                "next_graph_revision": self.next_graph_revision,
                "rollback_graph_revision": self.rollback_graph_revision,
                "transition_ref": self.transition_ref,
            }
        )


@dataclass(frozen=True, slots=True)
class RollbackPlan:
    proposal_digest: str
    failed_graph_revision: str
    restore_graph_revision: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    proposal_digest: str
    outcome: ReconciliationOutcome
    evidence_ref: str
    next_state: ProposalState
    rollback: RollbackPlan | None = None


@dataclass(frozen=True, slots=True)
class SourceProjectionRecord:
    source_ref: str
    proposal_digest: str
    target_identity: str
    fact_key: str
    graph_revision: str

    def __post_init__(self) -> None:
        if not self.source_ref or not self.target_identity or not self.graph_revision:
            raise ValueError("source projection identity fields MUST be non-empty")
        if (
            _SHA256.fullmatch(self.proposal_digest) is None
            or _SHA256.fullmatch(self.fact_key) is None
        ):
            raise ValueError("source projection digests MUST be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class TombstoneRequest:
    source_ref: str
    proposal_digest: str
    target_identity: str
    fact_key: str
    expected_graph_revision: str


@dataclass(frozen=True, slots=True)
class RetirementPlan:
    tombstones: tuple[TombstoneRequest, ...] = ()
    held: bool = False
    reason_code: str = ""


@dataclass(frozen=True, slots=True)
class AccessRevocationPlan:
    source_ref: str
    prior_acl_digest: str
    new_acl_digest: str
    block_artifact_refs: tuple[str, ...]


def start_lifecycle(
    verified: VerifiedOntologyProposal,
    *,
    graph_revision: str,
) -> ProposalLifecycleRecord:
    if verified.state not in {ProposalState.REVIEW_REQUIRED, ProposalState.DENIED}:
        raise ValueError("verified proposal MUST start in review_required or denied")
    return ProposalLifecycleRecord(
        proposal_digest=verified.verification_digest,
        state=verified.state,
        revision=1,
        current_graph_revision=graph_revision,
    )


def advance_lifecycle(
    record: ProposalLifecycleRecord,
    *,
    target: ProposalState,
    transition_ref: str,
    graph_revision: str | None = None,
    rollback_graph_revision: str | None = None,
) -> ProposalLifecycleRecord:
    if not transition_ref:
        raise ValueError("proposal lifecycle transition_ref MUST be non-empty")
    if target not in _TRANSITIONS.get(record.state, frozenset()):
        raise ValueError(f"invalid proposal lifecycle transition: {record.state} -> {target}")
    if (
        target not in {ProposalState.PROJECTED, ProposalState.ROLLED_BACK}
        and graph_revision is not None
        and graph_revision != record.current_graph_revision
    ):
        raise ValueError("graph revision can change only during projection or rollback")
    if target is not ProposalState.PROJECTED and rollback_graph_revision is not None:
        raise ValueError("rollback graph revision can be set only during projection")
    return ProposalLifecycleRecord(
        proposal_digest=record.proposal_digest,
        state=target,
        revision=record.revision + 1,
        current_graph_revision=graph_revision or record.current_graph_revision,
        rollback_graph_revision=rollback_graph_revision or record.rollback_graph_revision,
        transition_refs=record.transition_refs + (transition_ref,),
    )


def build_projection_plan(
    verified: VerifiedOntologyProposal,
    lifecycle: ProposalLifecycleRecord,
    *,
    next_graph_revision: str,
    transition_ref: str,
) -> ProjectionPlan:
    if lifecycle.state is not ProposalState.APPROVED:
        raise ValueError("only an approved proposal can create a projection plan")
    if lifecycle.proposal_digest != verified.verification_digest:
        raise ValueError("lifecycle proposal digest MUST match verified proposal")
    if lifecycle.current_graph_revision != verified.proposal.expected_graph_revision:
        raise ValueError("stale graph revision blocks ontology projection")
    if not next_graph_revision or next_graph_revision == lifecycle.current_graph_revision:
        raise ValueError("next graph revision MUST be new and non-empty")
    if not transition_ref:
        raise ValueError("projection transition_ref MUST be non-empty")
    return ProjectionPlan(
        proposal_digest=lifecycle.proposal_digest,
        expected_graph_revision=lifecycle.current_graph_revision,
        next_graph_revision=next_graph_revision,
        rollback_graph_revision=lifecycle.current_graph_revision,
        transition_ref=transition_ref,
    )


def record_projection(
    lifecycle: ProposalLifecycleRecord,
    plan: ProjectionPlan,
) -> ProposalLifecycleRecord:
    if lifecycle.proposal_digest != plan.proposal_digest:
        raise ValueError("projection plan MUST match lifecycle proposal")
    if lifecycle.current_graph_revision != plan.expected_graph_revision:
        raise ValueError("projection plan expected graph revision is stale")
    return advance_lifecycle(
        lifecycle,
        target=ProposalState.PROJECTED,
        transition_ref=plan.transition_ref,
        graph_revision=plan.next_graph_revision,
        rollback_graph_revision=plan.rollback_graph_revision,
    )


def reconcile_projection(
    lifecycle: ProposalLifecycleRecord,
    *,
    outcome: ReconciliationOutcome,
    evidence_ref: str,
) -> ReconciliationResult:
    if lifecycle.state is not ProposalState.PROJECTED:
        raise ValueError("only a projected proposal can be reconciled")
    if not evidence_ref:
        raise ValueError("reconciliation evidence_ref MUST be non-empty")
    if outcome is ReconciliationOutcome.MATCHED:
        return ReconciliationResult(
            lifecycle.proposal_digest,
            outcome,
            evidence_ref,
            ProposalState.RECONCILED,
        )
    if lifecycle.rollback_graph_revision is None:
        raise ValueError("failed reconciliation requires an exact rollback graph revision")
    return ReconciliationResult(
        lifecycle.proposal_digest,
        outcome,
        evidence_ref,
        ProposalState.ROLLED_BACK,
        rollback=RollbackPlan(
            proposal_digest=lifecycle.proposal_digest,
            failed_graph_revision=lifecycle.current_graph_revision,
            restore_graph_revision=lifecycle.rollback_graph_revision,
            reason_code=f"reconciliation_{outcome.value}",
        ),
    )


def record_reconciliation(
    lifecycle: ProposalLifecycleRecord,
    result: ReconciliationResult,
) -> ProposalLifecycleRecord:
    """Apply one reconciliation result to the immutable lifecycle record."""
    if lifecycle.proposal_digest != result.proposal_digest:
        raise ValueError("reconciliation result MUST match lifecycle proposal")
    graph_revision = result.rollback.restore_graph_revision if result.rollback is not None else None
    return advance_lifecycle(
        lifecycle,
        target=result.next_state,
        transition_ref=result.evidence_ref,
        graph_revision=graph_revision,
    )


def plan_source_retirement(
    retirements: tuple[RetirementRequest, ...],
    records: tuple[SourceProjectionRecord, ...],
    *,
    current_graph_revision: str,
    max_tombstones: int,
) -> RetirementPlan:
    if max_tombstones < 1:
        raise ValueError("max_tombstones MUST be positive")
    record_keys = [
        (record.source_ref, record.proposal_digest, record.fact_key) for record in records
    ]
    if len(record_keys) != len(set(record_keys)):
        raise ValueError("source projection records MUST be unique")
    if not current_graph_revision:
        raise ValueError("current_graph_revision MUST be non-empty")
    retired_refs = {item.source_ref for item in retirements}
    tombstones = tuple(
        TombstoneRequest(
            source_ref=record.source_ref,
            proposal_digest=record.proposal_digest,
            target_identity=record.target_identity,
            fact_key=record.fact_key,
            expected_graph_revision=current_graph_revision,
        )
        for record in sorted(records, key=lambda item: (item.source_ref, item.fact_key))
        if record.source_ref in retired_refs
    )
    if len(tombstones) > max_tombstones:
        return RetirementPlan(held=True, reason_code="tombstone_limit_exceeded")
    return RetirementPlan(tombstones=tombstones)


def plan_access_revocation(
    *,
    source_ref: str,
    prior_acl_digest: str,
    new_acl_digest: str,
    artifact_refs: tuple[str, ...],
) -> AccessRevocationPlan:
    if not source_ref:
        raise ValueError("access revocation source_ref MUST be non-empty")
    if _SHA256.fullmatch(prior_acl_digest) is None or _SHA256.fullmatch(new_acl_digest) is None:
        raise ValueError("access revocation ACL digests MUST be lowercase SHA-256")
    if prior_acl_digest == new_acl_digest:
        raise ValueError("access revocation requires an ACL change")
    if len(artifact_refs) != len(set(artifact_refs)):
        raise ValueError("access revocation artifact refs MUST be unique")
    return AccessRevocationPlan(
        source_ref=source_ref,
        prior_acl_digest=prior_acl_digest,
        new_acl_digest=new_acl_digest,
        block_artifact_refs=tuple(sorted(artifact_refs)),
    )


__all__ = [
    "AccessRevocationPlan",
    "ProjectionPlan",
    "ProposalLifecycleRecord",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "RetirementPlan",
    "RollbackPlan",
    "SourceProjectionRecord",
    "TombstoneRequest",
    "advance_lifecycle",
    "build_projection_plan",
    "plan_access_revocation",
    "plan_source_retirement",
    "reconcile_projection",
    "record_reconciliation",
    "record_projection",
    "start_lifecycle",
]
