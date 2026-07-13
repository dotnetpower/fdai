"""Materialize architecture-review manifest state into the ontology graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.process_runtime import ProcessEvent, ProcessEventKind, ProcessSnapshot


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
        decision_id = f"{review_id}:decision:{step_id}"
        await self.store.upsert_object(
            OntologyObjectRecord(
                id=decision_id,
                object_type="Decision",
                properties={
                    "id": decision_id,
                    "outcome": str(event.payload.get("decision", "unknown")),
                    "rationale": str(event.payload.get("reason", "workflow decision")),
                    "recorded_at": event.recorded_at.isoformat(),
                },
            )
        )
        await _link(self.store, "resolved_by", review_id, decision_id)
        gate = _mapping(review.get("production_gate"), "production_gate")
        evidence = _mapping(gate.get("evidence_bindings"), "evidence_bindings")
        for key in sorted(evidence):
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
    await store.upsert_link(
        OntologyLinkRecord(link_type=kind, from_id=source, to_id=target)
    )


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