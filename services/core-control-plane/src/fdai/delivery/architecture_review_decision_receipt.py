"""Read immutable ARB decision receipts from the ontology projection."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai.core.architecture_review import ArchitectureReviewDecisionReceipt
from fdai.shared.providers.ontology_instance import OntologyInstanceStore, OntologyObjectRecord


class OntologyArchitectureReviewDecisionReceiptProvider:
    """Resolve one unambiguous latest receipt without granting authority."""

    def __init__(self, store: OntologyInstanceStore) -> None:
        self._store = store

    async def retrieve(self, review_case_id: str) -> ArchitectureReviewDecisionReceipt:
        if not review_case_id.strip():
            raise ValueError("architecture review case id MUST be non-empty")
        snapshot = await self._store.query_objects(
            object_types=("Decision",),
            property_equals={"review_case_id": review_case_id},
            limit=64,
            include_relationships=False,
        )
        candidates = tuple(
            record
            for record in snapshot.objects
            if isinstance(record.properties.get("receipt_digest"), str)
        )
        if not candidates:
            raise ValueError("architecture review decision receipt is unavailable")
        latest_recorded_at = max(_recorded_at(record) for record in candidates)
        latest = tuple(
            record for record in candidates if _recorded_at(record) == latest_recorded_at
        )
        if len(latest) != 1:
            raise ValueError("latest architecture review decision receipt is ambiguous")
        return ArchitectureReviewDecisionReceipt.model_validate(
            _receipt_mapping(latest[0].properties)
        )


def _recorded_at(record: OntologyObjectRecord) -> datetime:
    value = record.properties.get("recorded_at")
    if not isinstance(value, str):
        raise ValueError("architecture review decision recorded_at is invalid")
    try:
        recorded_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("architecture review decision recorded_at is invalid") from exc
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("architecture review decision recorded_at MUST include a timezone")
    return recorded_at


def _receipt_mapping(properties: Mapping[str, object]) -> dict[str, object]:
    mapping = {
        "schema_version": properties.get("receipt_schema_version"),
        "decision_id": properties.get("id"),
        "receipt_digest": properties.get("receipt_digest"),
        "review_case_id": properties.get("review_case_id"),
        "change_id": properties.get("change_id"),
        "decision_case_id": properties.get("decision_case_id"),
        "impact_envelope_id": properties.get("impact_envelope_id"),
        "target_revision": properties.get("target_revision"),
        "context_snapshot_id": properties.get("context_snapshot_id"),
        "evidence_bundle_id": properties.get("evidence_bundle_id"),
        "graph_revision": properties.get("graph_revision"),
        "catalog_release": properties.get("catalog_release"),
        "evidence_refs": properties.get("evidence_refs"),
        "conditions": properties.get("conditions"),
        "outcome": properties.get("outcome"),
        "rationale": properties.get("rationale"),
        "authority_basis": properties.get("authority_basis"),
        "authority_ref": properties.get("authority_ref"),
        "requester_id": properties.get("requester_id"),
        "judge_id": properties.get("judge_id"),
        "approver_ids": properties.get("approver_ids"),
        "approval_receipt_refs": properties.get("approval_receipt_refs"),
        "quorum": properties.get("quorum"),
        "audit_intent_ref": properties.get("audit_intent_ref"),
        "terminal_audit_ref": properties.get("terminal_audit_ref"),
        "recorded_at": properties.get("recorded_at"),
        "effective_from": properties.get("effective_from"),
        "effective_until": properties.get("effective_until"),
        "reevaluation_trigger": properties.get("reevaluation_trigger"),
        "execution_authority": properties.get("execution_authority"),
    }
    arbitrator_id = properties.get("arbitrator_id")
    if arbitrator_id is not None:
        mapping["arbitrator_id"] = arbitrator_id
    return mapping


__all__ = ["OntologyArchitectureReviewDecisionReceiptProvider"]
