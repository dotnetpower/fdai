"""Immutable, replay-stable authority record for one architecture review decision."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai.shared.contracts.models import ContractBase

NonEmpty = Annotated[str, Field(min_length=1, max_length=512)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]
BoundedRefs = Annotated[tuple[NonEmpty, ...], Field(min_length=1, max_length=64)]


class ArchitectureDecisionOutcome(StrEnum):
    """Allowed terminal architecture review outcomes."""

    CONFORMANT = "conformant"
    CONDITIONAL = "conditional"
    HELD = "held"
    REJECTED = "rejected"


class ArchitectureDecisionAuthorityBasis(StrEnum):
    """Authority recorded by the receipt without granting execution authority."""

    OBSERVATION = "observation"
    STANDING_AUTHORIZATION = "standing_authorization"
    HUMAN_APPROVAL = "human_approval"
    DENIED = "denied"


class ArchitectureReviewDecisionReceipt(ContractBase):
    """Bind one ARB decision to its exact immutable evidence and authority basis."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    decision_id: NonEmpty
    receipt_digest: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    review_case_id: NonEmpty
    change_id: NonEmpty
    decision_case_id: NonEmpty
    impact_envelope_id: NonEmpty
    target_revision: NonEmpty
    context_snapshot_id: NonEmpty
    evidence_bundle_id: NonEmpty
    graph_revision: NonEmpty
    catalog_release: NonEmpty
    evidence_refs: BoundedRefs
    conditions: Annotated[tuple[NonEmpty, ...], Field(max_length=32)] = ()
    outcome: ArchitectureDecisionOutcome
    rationale: BoundedText
    authority_basis: ArchitectureDecisionAuthorityBasis
    authority_ref: NonEmpty
    requester_id: NonEmpty
    judge_id: NonEmpty
    arbitrator_id: NonEmpty | None = None
    approver_ids: Annotated[tuple[NonEmpty, ...], Field(max_length=16)] = ()
    approval_receipt_refs: Annotated[tuple[NonEmpty, ...], Field(max_length=16)] = ()
    quorum: Annotated[int, Field(ge=0, le=16)] = 0
    audit_intent_ref: NonEmpty
    terminal_audit_ref: NonEmpty
    recorded_at: datetime
    effective_from: datetime
    effective_until: datetime
    reevaluation_trigger: NonEmpty
    execution_authority: Literal[False] = False

    @field_validator("recorded_at", "effective_from", "effective_until")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("architecture decision receipt timestamps MUST be timezone-aware")
        return value

    @field_validator(
        "evidence_refs",
        "conditions",
        "approver_ids",
        "approval_receipt_refs",
    )
    @classmethod
    def require_sorted_unique_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("architecture decision receipt references MUST be unique")
        if value != tuple(sorted(value)):
            raise ValueError("architecture decision receipt references MUST be sorted")
        return value

    @model_validator(mode="after")
    def validate_receipt(self) -> ArchitectureReviewDecisionReceipt:
        if not self.recorded_at <= self.effective_from < self.effective_until:
            raise ValueError(
                "architecture decision receipt times MUST satisfy "
                "recorded_at <= effective_from < effective_until"
            )
        if self.authority_basis is ArchitectureDecisionAuthorityBasis.HUMAN_APPROVAL:
            if self.quorum < 1:
                raise ValueError("human-approved architecture decision MUST require quorum")
            if len(self.approver_ids) < self.quorum:
                raise ValueError(
                    "human-approved architecture decision MUST satisfy approver quorum"
                )
            if len(self.approval_receipt_refs) < self.quorum:
                raise ValueError("human-approved architecture decision MUST bind approval receipts")
            if len(self.approver_ids) != len(self.approval_receipt_refs):
                raise ValueError(
                    "human-approved architecture decision MUST pair approvers and receipts"
                )
            decision_principals = {self.requester_id, self.judge_id}
            if self.arbitrator_id is not None:
                decision_principals.add(self.arbitrator_id)
            if decision_principals.intersection(self.approver_ids):
                raise ValueError(
                    "architecture decision requester, judge, and arbitrator MUST NOT self-approve"
                )
        elif self.quorum or self.approver_ids or self.approval_receipt_refs:
            raise ValueError(
                "non-human architecture decision MUST NOT claim human approval evidence"
            )
        material = _receipt_material(self)
        expected_digest = _receipt_digest(material)
        if self.receipt_digest != expected_digest:
            raise ValueError("architecture decision receipt digest does not match content")
        if self.decision_id != _decision_id(expected_digest):
            raise ValueError("architecture decision id does not match receipt digest")
        return self

    def to_mapping(self) -> dict[str, object]:
        """Return a stable JSON-compatible projection for ontology storage."""

        return self.model_dump(mode="json")

    def to_json(self) -> str:
        """Return canonical JSON for replay and audit hashing."""

        return json.dumps(
            self.to_mapping(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def to_decision_properties(self) -> dict[str, object]:
        """Project the receipt into the versioned Decision ontology shape."""

        properties: dict[str, object] = {
            "id": self.decision_id,
            "outcome": self.outcome.value,
            "rationale": self.rationale,
            "recorded_at": _timestamp(self.recorded_at),
            "effective_from": _timestamp(self.effective_from),
            "effective_until": _timestamp(self.effective_until),
            "receipt_schema_version": self.schema_version,
            "receipt_digest": self.receipt_digest,
            "review_case_id": self.review_case_id,
            "change_id": self.change_id,
            "decision_case_id": self.decision_case_id,
            "impact_envelope_id": self.impact_envelope_id,
            "target_revision": self.target_revision,
            "context_snapshot_id": self.context_snapshot_id,
            "evidence_bundle_id": self.evidence_bundle_id,
            "graph_revision": self.graph_revision,
            "catalog_release": self.catalog_release,
            "evidence_refs": list(self.evidence_refs),
            "conditions": list(self.conditions),
            "authority_basis": self.authority_basis.value,
            "authority_ref": self.authority_ref,
            "requester_id": self.requester_id,
            "judge_id": self.judge_id,
            "approver_ids": list(self.approver_ids),
            "approval_receipt_refs": list(self.approval_receipt_refs),
            "quorum": self.quorum,
            "audit_intent_ref": self.audit_intent_ref,
            "terminal_audit_ref": self.terminal_audit_ref,
            "reevaluation_trigger": self.reevaluation_trigger,
            "execution_authority": False,
        }
        if self.arbitrator_id is not None:
            properties["arbitrator_id"] = self.arbitrator_id
        return properties


def build_architecture_review_decision_receipt(
    *,
    review_case_id: str,
    change_id: str,
    decision_case_id: str,
    impact_envelope_id: str,
    target_revision: str,
    context_snapshot_id: str,
    evidence_bundle_id: str,
    graph_revision: str,
    catalog_release: str,
    evidence_refs: tuple[str, ...],
    conditions: tuple[str, ...],
    outcome: ArchitectureDecisionOutcome,
    rationale: str,
    authority_basis: ArchitectureDecisionAuthorityBasis,
    authority_ref: str,
    requester_id: str,
    judge_id: str,
    arbitrator_id: str | None,
    approver_ids: tuple[str, ...],
    approval_receipt_refs: tuple[str, ...],
    quorum: int,
    audit_intent_ref: str,
    terminal_audit_ref: str,
    recorded_at: datetime,
    effective_from: datetime,
    effective_until: datetime,
    reevaluation_trigger: str,
) -> ArchitectureReviewDecisionReceipt:
    """Build one content-addressed receipt after all authority inputs are known."""

    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "review_case_id": review_case_id,
        "change_id": change_id,
        "decision_case_id": decision_case_id,
        "impact_envelope_id": impact_envelope_id,
        "target_revision": target_revision,
        "context_snapshot_id": context_snapshot_id,
        "evidence_bundle_id": evidence_bundle_id,
        "graph_revision": graph_revision,
        "catalog_release": catalog_release,
        "evidence_refs": sorted(evidence_refs),
        "conditions": sorted(conditions),
        "outcome": outcome.value,
        "rationale": rationale,
        "authority_basis": authority_basis.value,
        "authority_ref": authority_ref,
        "requester_id": requester_id,
        "judge_id": judge_id,
        "arbitrator_id": arbitrator_id,
        "approver_ids": sorted(approver_ids),
        "approval_receipt_refs": sorted(approval_receipt_refs),
        "quorum": quorum,
        "audit_intent_ref": audit_intent_ref,
        "terminal_audit_ref": terminal_audit_ref,
        "recorded_at": _timestamp(recorded_at),
        "effective_from": _timestamp(effective_from),
        "effective_until": _timestamp(effective_until),
        "reevaluation_trigger": reevaluation_trigger,
        "execution_authority": False,
    }
    digest = _receipt_digest(material)
    return ArchitectureReviewDecisionReceipt.model_validate(
        {
            **material,
            "decision_id": _decision_id(digest),
            "receipt_digest": digest,
        }
    )


def _receipt_material(receipt: ArchitectureReviewDecisionReceipt) -> dict[str, object]:
    return receipt.model_dump(
        mode="json",
        exclude={"decision_id", "receipt_digest"},
    )


def _receipt_digest(material: dict[str, object]) -> str:
    encoded = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _decision_id(receipt_digest: str) -> str:
    return f"arb-decision-{receipt_digest.removeprefix('sha256:')[:32]}"


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("architecture decision receipt timestamps MUST be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "ArchitectureDecisionAuthorityBasis",
    "ArchitectureDecisionOutcome",
    "ArchitectureReviewDecisionReceipt",
    "build_architecture_review_decision_receipt",
]
