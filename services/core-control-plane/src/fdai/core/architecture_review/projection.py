"""Materialize architecture-review manifest state into the ontology graph."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.architecture_review.decision_receipt import ArchitectureReviewDecisionReceipt
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind, ProcessSnapshot

from .observation_loop import ArchitectureReviewObservation


@dataclass(frozen=True, slots=True)
class ArchitectureReviewProjector:
    store: OntologyInstanceStore
    manifest: Mapping[str, Any]

    async def project(
        self,
        snapshot: ProcessSnapshot,
        *,
        event: ProcessEvent | None = None,
    ) -> None:
        review = _mapping(self.manifest.get("architecture_review"), "architecture_review")
        review_id = str(review["review_id"])
        design_status = str(review["design_review_status"])
        production_status = str(review["production_approval_status"])
        await self.store.upsert_object(
            OntologyObjectRecord(
                id=review_id,
                object_type="ReviewCase",
                properties={
                    "id": review_id,
                    "title": "FDAI target architecture review",
                    "review_kind": "architecture",
                    "status": _case_status(snapshot, design_status, production_status),
                    "design_status": design_status,
                    "production_status": production_status,
                    "scope_ref": snapshot.target_resource_id,
                    "workflow_ref": snapshot.workflow_ref,
                    "opened_at": snapshot.started_at.isoformat(),
                    "updated_at": snapshot.updated_at.isoformat(),
                },
            )
        )
        await _link(self.store, "runs_review", snapshot.process_id, review_id)
        target = await self.store.get_object(snapshot.target_resource_id)
        if target is not None and target.object_type == "Resource":
            await _link(self.store, "scoped_to", review_id, snapshot.target_resource_id)
        for check in _checks(review, review_id):
            await self._upsert_check(review_id, check, snapshot)
        await self._project_bindings(review, review_id)
        if event is not None:
            await self._project_transition(review, review_id, event)

    async def project_observation(
        self,
        observation: ArchitectureReviewObservation,
        *,
        process_id: str | None = None,
    ) -> None:
        """Project only authoritative observation lineage into ARB read models.

        The manifest remains a design profile. Review checks created here are
        reconciled against the current evidence bundle and never grant authority.
        """

        review_id = f"arb-review:{observation.change_id}"
        process_ref = _observation_process_ref(observation) or process_id
        recorded_at = (
            observation.context.recorded_at
            if observation.context is not None
            else datetime.fromtimestamp(0, tz=UTC)
        )
        await self.store.upsert_object(
            OntologyObjectRecord(
                id=review_id,
                object_type="ReviewCase",
                properties={
                    "id": review_id,
                    "title": "Observation-mode architecture review",
                    "review_kind": "architecture",
                    "status": observation.recommendation,
                    "design_status": "conditional",
                    "production_status": "blocked",
                    "scope_ref": observation.target_ref,
                    "workflow_ref": "architecture-review",
                    "opened_at": recorded_at.isoformat(),
                    "updated_at": recorded_at.isoformat(),
                },
            )
        )
        if process_ref is not None:
            await _link(self.store, "runs_review", process_ref, review_id)
        target = await self.store.get_object(observation.target_ref)
        if target is not None and target.object_type == "Resource":
            await _link(self.store, "scoped_to", review_id, observation.target_ref)

        current_checks: set[str] = set()
        evidence_available = observation.evidence is not None
        existing_change = await self.store.get_object(observation.change_id)
        if existing_change is None and observation.normalized_change:
            await self.store.upsert_object(
                OntologyObjectRecord(
                    id=observation.change_id,
                    object_type="Change",
                    properties=dict(observation.normalized_change),
                )
            )
            existing_change = await self.store.get_object(observation.change_id)
        if existing_change is not None and existing_change.object_type == "Change":
            target = await self.store.get_object(observation.target_ref)
        else:
            target = None
        if target is not None and target.object_type == "Resource":
            await _link(
                self.store,
                "change_targets_resource",
                observation.change_id,
                observation.target_ref,
            )
        if observation.context is not None and observation.evidence is not None:
            bundle = observation.evidence.bundle
            for entry in bundle.citation_manifest:
                check_id = _check_id(review_id, "evidence", entry.evidence_ref)
                current_checks.add(check_id)
                expired = any(
                    "expired" in reason
                    for reason in (*bundle.evidence_issues, *bundle.hold_reasons)
                )
                status = "expired" if expired else ("blocked" if bundle.hold_required else "ready")
                await self._upsert_lineage_check(
                    review_id=review_id,
                    check_id=check_id,
                    check_key=entry.evidence_ref,
                    status=status,
                    updated_at=recorded_at,
                )
                artifact_id = _observation_artifact_id(observation, entry)
                await self.store.upsert_object(
                    OntologyObjectRecord(
                        id=artifact_id,
                        object_type="EvidenceArtifact",
                        properties={
                            "id": artifact_id,
                            "kind": entry.lane.value,
                            "uri": f"evidence://{entry.evidence_ref}",
                            "sha256": entry.item_digest,
                            "status": status,
                            "classification": "internal",
                            "captured_at": entry.cutoff,
                        },
                    )
                )
                await _link(self.store, "supported_by", check_id, artifact_id)

            if observation.decision_case is not None:
                case = observation.decision_case
                await self.store.upsert_object(
                    OntologyObjectRecord(
                        id=case.case_id,
                        object_type="DecisionCase",
                        properties={
                            "id": case.case_id,
                            "target_ref": observation.target_ref,
                            "evidence_cutoff": bundle.cutoff,
                            "context_digest": case.context_snapshot_id,
                            "no_action_baseline": {
                                "objective_ids": list(case.protected_objective_ids),
                                "observation_only": True,
                            },
                            "uncertainty": 1.0 if bundle.hold_required else 0.0,
                            "status": observation.recommendation,
                            "created_at": case.created_at,
                        },
                    )
                )
                if existing_change is not None and existing_change.object_type == "Change":
                    await _link(
                        self.store,
                        "case_evaluates_change",
                        case.case_id,
                        observation.change_id,
                    )
                decision_id = f"{review_id}:decision:{case.case_id[:32]}"
                await self.store.upsert_object(
                    OntologyObjectRecord(
                        id=decision_id,
                        object_type="Decision",
                        properties={
                            "id": decision_id,
                            "outcome": observation.recommendation,
                            "rationale": (
                                "; ".join(observation.reasons) or "observation evidence accepted"
                            ),
                            "recorded_at": recorded_at,
                        },
                    )
                )
                await _link(self.store, "resolved_by", review_id, decision_id)

            if observation.impact_envelope is not None:
                envelope = observation.impact_envelope
                properties = envelope.to_ontology_object().properties
                await self.store.upsert_object(
                    OntologyObjectRecord(
                        id=envelope.envelope_id,
                        object_type="ImpactEnvelope",
                        properties={
                            key: properties[key]
                            for key in (
                                "id",
                                "decision_case_id",
                                "graph_revision",
                                "target_set_digest",
                                "affected_set_digest",
                                "max_affected_resources",
                                "max_dependency_depth",
                                "max_duration_seconds",
                                "objective_bounds",
                                "required_signals",
                                "forbidden_signals",
                                "telemetry_requirements",
                                "uncertainty",
                                "expires_at",
                            )
                        },
                    )
                )
                if existing_change is not None and existing_change.object_type == "Change":
                    await _link(
                        self.store,
                        "change_bounded_by_envelope",
                        observation.change_id,
                        envelope.envelope_id,
                    )

        if evidence_available:
            existing = await self.store.query_objects(object_types=("ReviewCheck",), limit=1000)
            for check in existing.objects:
                if (
                    check.id.startswith(f"{review_id}:check:evidence:")
                    and check.id not in current_checks
                ):
                    await self.store.upsert_object(
                        OntologyObjectRecord(
                            id=check.id,
                            object_type="ReviewCheck",
                            properties={
                                **dict(check.properties),
                                "status": "removed",
                                "updated_at": recorded_at,
                            },
                            revision=check.revision,
                        )
                    )

    async def _upsert_lineage_check(
        self,
        *,
        review_id: str,
        check_id: str,
        check_key: str,
        status: str,
        updated_at: datetime,
    ) -> None:
        await self.store.upsert_object(
            OntologyObjectRecord(
                id=check_id,
                object_type="ReviewCheck",
                properties={
                    "id": check_id,
                    "check_key": check_key,
                    "category": "evidence",
                    "status": status,
                    "severity": "high",
                    "required": True,
                    "description": "Authoritative ARB evidence bundle item",
                    "updated_at": updated_at,
                },
            )
        )
        await _link(self.store, "contains_check", review_id, check_id)

    async def _project_transition(
        self,
        review: Mapping[str, Any],
        review_id: str,
        event: ProcessEvent,
    ) -> None:
        if event.kind in {
            ProcessEventKind.APPROVAL_REQUESTED,
            ProcessEventKind.APPROVAL_RECORDED,
        }:
            await self._project_approval(review_id, event)
        if event.kind is ProcessEventKind.DECISION_RECORDED:
            await self._project_decision(review, review_id, event)

    async def _project_approval(self, review_id: str, event: ProcessEvent) -> None:
        step_id = _event_step_id(event)
        approval_id = f"{review_id}:approval:{step_id}"
        existing = await self.store.get_object(approval_id)
        requested_at = event.recorded_at.isoformat()
        if existing is not None:
            requested_at = str(existing.properties["requested_at"])
        recorded = event.kind is ProcessEventKind.APPROVAL_RECORDED
        properties: dict[str, Any] = {
            "id": approval_id,
            "status": str(event.payload.get("decision", "recorded" if recorded else "pending")),
            "required_role": str(event.payload.get("required_role", "approver")),
            "quorum": int(event.payload.get("quorum", 1)),
            "no_self_approval": bool(event.payload.get("no_self_approval", True)),
            "requested_at": requested_at,
        }
        if recorded:
            properties["decided_at"] = event.recorded_at.isoformat()
            approver_id = event.payload.get("approver_id")
            receipt_ref = event.payload.get("approval_receipt_ref")
            if isinstance(approver_id, str) and approver_id:
                properties["approver_id"] = approver_id
            if isinstance(receipt_ref, str) and receipt_ref:
                properties["receipt_ref"] = receipt_ref
        await self.store.upsert_object(
            OntologyObjectRecord(
                id=approval_id,
                object_type="Approval",
                properties=properties,
            )
        )
        await _link(self.store, "has_approval", review_id, approval_id)

    async def _project_decision(
        self,
        review: Mapping[str, Any],
        review_id: str,
        event: ProcessEvent,
    ) -> None:
        step_id = _event_step_id(event)
        raw_receipt = event.payload.get("decision_receipt")
        receipt = (
            ArchitectureReviewDecisionReceipt.model_validate(raw_receipt)
            if raw_receipt is not None
            else None
        )
        if receipt is not None:
            if receipt.review_case_id != review_id:
                raise ValueError("architecture decision receipt review case does not match")
            if receipt.recorded_at != event.recorded_at:
                raise ValueError("architecture decision receipt recorded_at does not match event")
            if receipt.outcome.value != str(event.payload.get("decision", "")):
                raise ValueError("architecture decision receipt outcome does not match event")
        gate = _mapping(review.get("production_gate"), "production_gate")
        evidence = _mapping(gate.get("evidence_bindings"), "evidence_bindings")
        evidence_refs = receipt.evidence_refs if receipt is not None else tuple(sorted(evidence))
        unknown_evidence = set(evidence_refs) - evidence.keys()
        if unknown_evidence:
            raise ValueError(
                "architecture decision receipt references unknown evidence: "
                + ", ".join(sorted(unknown_evidence))
            )
        if receipt is not None:
            recorded_approvers: set[str] = set()
            for approval_ref in receipt.approval_receipt_refs:
                approval = await self.store.get_object(approval_ref)
                if (
                    approval is None
                    or approval.object_type != "Approval"
                    or approval.properties.get("status") != "approved"
                ):
                    raise ValueError(
                        "architecture decision receipt approval is not authoritatively recorded"
                    )
                if approval.properties.get("receipt_ref") != approval_ref:
                    raise ValueError(
                        "architecture decision receipt approval identity does not match"
                    )
                approver_id = approval.properties.get("approver_id")
                if not isinstance(approver_id, str) or not approver_id:
                    raise ValueError(
                        "architecture decision receipt approval has no recorded approver"
                    )
                recorded_approvers.add(approver_id)
            if recorded_approvers != set(receipt.approver_ids):
                raise ValueError(
                    "architecture decision receipt approvers do not match recorded approvals"
                )
        decision_id = receipt.decision_id if receipt else f"{review_id}:decision:{step_id}"
        properties = (
            receipt.to_decision_properties()
            if receipt is not None
            else {
                "id": decision_id,
                "outcome": str(event.payload.get("decision", "unknown")),
                "rationale": str(event.payload.get("reason", "workflow decision")),
                "recorded_at": event.recorded_at.isoformat(),
            }
        )
        await self.store.upsert_object(
            OntologyObjectRecord(
                id=decision_id,
                object_type="Decision",
                properties=properties,
            )
        )
        await _link(self.store, "resolved_by", review_id, decision_id)
        for key in evidence_refs:
            await _link(
                self.store,
                "based_on",
                decision_id,
                f"evidence:{review_id}:{key}",
            )

    async def _upsert_check(
        self,
        review_id: str,
        check: Mapping[str, Any],
        snapshot: ProcessSnapshot,
    ) -> None:
        check_id = str(check["id"])
        await self.store.upsert_object(
            OntologyObjectRecord(
                id=check_id,
                object_type="ReviewCheck",
                properties={
                    "id": check_id,
                    "check_key": str(check["check_key"]),
                    "category": str(check["category"]),
                    "status": str(check["status"]),
                    "severity": str(check["severity"]),
                    "required": bool(check["required"]),
                    "description": str(check["description"]),
                    "updated_at": snapshot.updated_at.isoformat(),
                },
            )
        )
        await _link(self.store, "contains_check", review_id, check_id)

    async def _project_bindings(
        self,
        review: Mapping[str, Any],
        review_id: str,
    ) -> None:
        gate = _mapping(review.get("production_gate"), "production_gate")
        owners = _mapping(gate.get("owner_bindings"), "owner_bindings")
        for slot, raw in sorted(owners.items()):
            binding = _mapping(raw, f"owner_bindings.{slot}")
            principal_id = f"principal:{slot}:{binding['subject']}"
            await self.store.upsert_object(
                OntologyObjectRecord(
                    id=principal_id,
                    object_type="Principal",
                    properties={
                        "id": principal_id,
                        "kind": _principal_kind(str(binding["subject"])),
                        "role": slot,
                        "escalation_ref": str(binding["escalation"]),
                    },
                )
            )
            await _link(
                self.store,
                "assigned_to",
                _check_id(review_id, "owner", slot),
                principal_id,
            )
        evidence = _mapping(gate.get("evidence_bindings"), "evidence_bindings")
        for key, raw in sorted(evidence.items()):
            binding = _mapping(raw, f"evidence_bindings.{key}")
            artifact_id = f"evidence:{review_id}:{key}"
            await self.store.upsert_object(
                OntologyObjectRecord(
                    id=artifact_id,
                    object_type="EvidenceArtifact",
                    properties={
                        "id": artifact_id,
                        "kind": key,
                        "uri": str(binding["uri"]),
                        "sha256": str(binding["sha256"]),
                        "status": "ready",
                        "classification": "internal",
                        "captured_at": str(binding["approved_at"]),
                        "expires_at": str(binding["expires_at"]),
                    },
                )
            )
            await _link(
                self.store,
                "supported_by",
                _check_id(review_id, "evidence", key),
                artifact_id,
            )


async def _link(store: OntologyInstanceStore, kind: str, source: str, target: str) -> None:
    await store.upsert_link(OntologyLinkRecord(link_type=kind, from_id=source, to_id=target))


def _checks(review: Mapping[str, Any], review_id: str) -> Sequence[Mapping[str, Any]]:
    checks: list[Mapping[str, Any]] = []
    for raw in _sequence(review.get("artifacts"), "artifacts"):
        artifact = _mapping(raw, "artifact")
        status = str(artifact["status"])
        checks.append(
            _check(
                review_id,
                "artifact",
                str(artifact["id"]),
                status,
                "high" if status != "ready" else "low",
                f"{artifact['required_for']} review artifact",
            )
        )
    for raw in _sequence(review.get("blockers"), "blockers"):
        blocker = _mapping(raw, "blocker")
        checks.append(
            _check(
                review_id,
                "blocker",
                str(blocker["id"]),
                str(blocker["status"]),
                str(blocker["severity"]),
                str(blocker["resolution"]),
            )
        )
    gate = _mapping(review.get("production_gate"), "production_gate")
    owners = _mapping(gate.get("owner_bindings"), "owner_bindings")
    for raw in _sequence(gate.get("required_owner_slots"), "required_owner_slots"):
        slot = str(raw)
        checks.append(
            _check(
                review_id,
                "owner",
                slot,
                "ready" if slot in owners else "blocked",
                "critical",
                "Required accountable owner binding",
            )
        )
    evidence = _mapping(gate.get("evidence_bindings"), "evidence_bindings")
    for raw in _sequence(gate.get("required_evidence"), "required_evidence"):
        key = str(raw)
        checks.append(
            _check(
                review_id,
                "evidence",
                key,
                "ready" if key in evidence else "blocked",
                "high",
                "Required production evidence binding",
            )
        )
    return tuple(checks)


def _check(
    review_id: str,
    category: str,
    key: str,
    status: str,
    severity: str,
    description: str,
) -> Mapping[str, Any]:
    return {
        "id": _check_id(review_id, category, key),
        "check_key": key,
        "category": category,
        "status": status,
        "severity": severity,
        "required": True,
        "description": description,
    }


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be a mapping")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} MUST be a sequence")
    return value


def _check_id(review_id: str, category: str, key: str) -> str:
    return f"{review_id}:check:{category}:{key}"


def _observation_artifact_id(
    observation: ArchitectureReviewObservation,
    entry: Any,
) -> str:
    """Return an evidence identity bound to both bundle and item content."""

    material = json.dumps(
        {
            "bundle": observation.evidence.bundle.digest if observation.evidence else "",
            "evidence_ref": entry.evidence_ref,
            "item_digest": entry.item_digest,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"evidence:sha256:{hashlib.sha256(material).hexdigest()}"


def _observation_process_ref(
    observation: ArchitectureReviewObservation,
) -> str | None:
    value = dict(observation.normalized_change).get("process_ref")
    if value is None:
        return None
    process_ref = str(value).strip()
    return process_ref or None


def _case_status(snapshot: ProcessSnapshot, design: str, production: str) -> str:
    if snapshot.status.value in {"failed", "cancelled", "timed_out"}:
        return snapshot.status.value
    if production == "ready":
        return "approved"
    if design in {"approved", "conditional"}:
        return "evidence_pending"
    return "open"


def _principal_kind(subject: str) -> str:
    return subject.split(":", maxsplit=1)[0] if ":" in subject else "group"


def _event_step_id(event: ProcessEvent) -> str:
    if event.step_id is None:
        raise ValueError(f"{event.kind.value} event MUST carry step_id")
    return event.step_id


__all__ = ["ArchitectureReviewProjector"]
