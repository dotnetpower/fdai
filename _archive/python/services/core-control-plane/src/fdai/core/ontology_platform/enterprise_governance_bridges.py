"""Operator Decision Queue API, Console Inbox & drilldowns, and enterprise bridges (Items 31-35).

Provides:
31. ``decision_queue_projection_key``, ``persist_decision_queue_projection``, and
    ``read_decision_queue_operator_payload``: principal-scoped ``StateStore`` persistence and
    read-only Operator payload reader for ``DecisionQueueProjection``.
32. ``build_decision_inbox_view_model``: Console Decision Inbox view model with cost-of-delay
    badges, risk tier badges, uncertainty percentages, and approval quorum labels.
33. ``build_workflow_value_claim_drilldowns``: per-workflow Outcome Assurance drill-down
    aggregating conservative 95% improvements and baseline reduction percentages.
34. ``DeploymentAndServiceCatalogBridge``: vendor-neutral bridge syncing CI/CD release events
    and service-catalog declarations into ``Change``, ``BusinessService``, ``Workload``, and
    ``Ownership`` ontology objects and links.
35. ``EnterpriseGovernanceOntologyBridge``: vendor-neutral ITSM change-window and on-call shift
    bridge into ``ChangeWindow`` and ``Ownership``, plus bidirectional audit correlation receipts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.decision_case.decision_queue import DecisionQueueProjection
from fdai.core.measurement.value_claim import (
    ValueClaimDeclaration,
    ValueClaimSettlement,
    ValueClaimStatus,
    ValueUnit,
)
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_store import StateStore


def decision_queue_projection_key(principal_id: str, scope_ref: str = "global") -> str:
    """Item 31: Deterministic StateStore key for one principal's DecisionQueueProjection."""

    clean_principal = principal_id.strip()
    clean_scope = scope_ref.strip()
    if not clean_principal or not clean_scope or "\x00" in clean_principal or "\x00" in clean_scope:
        raise ValueError("Decision queue principal_id and scope_ref MUST be non-empty")
    digest = hashlib.sha256(f"{clean_principal}\x00{clean_scope}".encode()).hexdigest()
    return f"decision-queue:projection:v1:{digest}"


async def persist_decision_queue_projection(
    *,
    principal_id: str,
    scope_ref: str,
    projection: DecisionQueueProjection,
    store: StateStore,
) -> str:
    """Item 31: Persist a read-only DecisionQueueProjection under the shared Operator key."""

    key = decision_queue_projection_key(principal_id, scope_ref)
    payload: dict[str, Any] = {
        "type": "decision-queue.operator-projection",
        "schema_version": "1.0.0",
        "read_only": True,
        "authority": "none",
        "principal_id": principal_id.strip(),
        "scope_ref": scope_ref.strip(),
        "ranking_currency": projection.ranking_currency,
        "as_of": projection.as_of.astimezone(UTC).isoformat(),
        "projection_digest": projection.projection_digest,
        "items": [
            {
                "case_id": item.case_id,
                "process_id": item.process_id,
                "target_resource_ref": item.target_resource_ref,
                "recommended_option_id": item.recommended_option_id,
                "recommended_action_type": item.recommended_action_type,
                "uncertainty": item.uncertainty,
                "blast_radius_tier": item.blast_radius_tier,
                "change_risk_tier": item.change_risk_tier,
                "cost_of_delay_amount": (
                    None if item.cost_of_delay_amount is None else str(item.cost_of_delay_amount)
                ),
                "cost_of_delay_currency": item.cost_of_delay_currency,
                "evidence_refs": list(item.evidence_refs),
                "approval_control": {
                    "requires_human_approval": item.approval_control.requires_human_approval,
                    "required_role": item.approval_control.required_role,
                    "quorum": item.approval_control.quorum,
                    "no_self_approval": item.approval_control.no_self_approval,
                    "approval_status": item.approval_control.approval_status,
                },
            }
            for item in projection.items
        ],
    }
    await store.write_state(key, payload)
    return key


async def read_decision_queue_operator_payload(
    *,
    principal_id: str | None,
    scope_ref: str = "global",
    store: StateStore,
) -> Mapping[str, Any]:
    """Item 31: Read the principal-scoped DecisionQueueProjection for the Operator API."""

    if principal_id is None or not principal_id.strip():
        raise PermissionError("Decision queue projection requires an authenticated principal")
    key = decision_queue_projection_key(principal_id, scope_ref)
    stored = await store.read_state(key)
    if stored is None:
        return {
            "type": "decision-queue.operator-projection",
            "schema_version": "1.0.0",
            "read_only": True,
            "authority": "none",
            "state": "unavailable",
            "principal_id": principal_id.strip(),
            "scope_ref": scope_ref.strip(),
            "items": [],
        }
    return {**dict(stored), "state": "complete", "read_only": True, "authority": "none"}


@dataclass(frozen=True, slots=True)
class DecisionInboxCardView:
    """Item 32: One card in the Console Decision Inbox UI."""

    rank: int
    case_id: str
    target_resource_ref: str
    recommended_action_type: str
    cost_badge: str
    blast_badge: str
    risk_badge: str
    uncertainty_pct: int
    quorum_label: str
    approval_status: str
    evidence_count: int


@dataclass(frozen=True, slots=True)
class DecisionInboxViewModel:
    """Item 32: Read-only Console Decision Inbox state."""

    cards: tuple[DecisionInboxCardView, ...]
    total_pending_count: int
    ranking_currency: str | None
    read_only: Literal[True] = True


def build_decision_inbox_view_model(
    projection: DecisionQueueProjection,
    *,
    status_filter: str | None = None,
) -> DecisionInboxViewModel:
    """Item 32: Transform a DecisionQueueProjection into the Console Decision Inbox view model."""

    cards: list[DecisionInboxCardView] = []
    pending_count = 0
    for item in projection.items:
        if item.approval_control.approval_status == "pending":
            pending_count += 1
        if status_filter is not None and item.approval_control.approval_status != status_filter:
            continue
        cost_badge = (
            f"{item.cost_of_delay_amount} {item.cost_of_delay_currency}"
            if item.cost_of_delay_amount is not None and item.cost_of_delay_currency
            else "Unpriced"
        )
        ctrl = item.approval_control
        quorum_label = f"{ctrl.required_role} (quorum {ctrl.quorum})"
        cards.append(
            DecisionInboxCardView(
                rank=len(cards) + 1,
                case_id=item.case_id,
                target_resource_ref=item.target_resource_ref,
                recommended_action_type=item.recommended_action_type or "no-op",
                cost_badge=cost_badge,
                blast_badge=f"blast:{item.blast_radius_tier}",
                risk_badge=f"risk:{item.change_risk_tier}",
                uncertainty_pct=round(item.uncertainty * 100),
                quorum_label=quorum_label,
                approval_status=ctrl.approval_status,
                evidence_count=len(item.evidence_refs),
            )
        )
    return DecisionInboxViewModel(
        cards=tuple(cards),
        total_pending_count=pending_count,
        ranking_currency=projection.ranking_currency,
    )


@dataclass(frozen=True, slots=True)
class WorkflowValueClaimDrilldown:
    """Item 33: Per-workflow ValueClaim realization summary for the Console."""

    workflow_ref: str
    objective_ref: str
    unit: ValueUnit
    currency: str | None
    settled_claim_count: int
    total_conservative_improvement: Decimal
    average_reduction_pct: float | None
    evidence_refs: tuple[str, ...]
    read_only: Literal[True] = True


def build_workflow_value_claim_drilldowns(
    pairs: Sequence[tuple[ValueClaimDeclaration, ValueClaimSettlement]],
) -> tuple[WorkflowValueClaimDrilldown, ...]:
    """Item 33: Aggregate conservative realized value by workflow for Console drill-downs."""

    grouped: dict[
        tuple[str, str, ValueUnit, str | None],
        list[tuple[ValueClaimDeclaration, ValueClaimSettlement]],
    ] = {}
    for decl, settlement in pairs:
        if decl.claim_id != settlement.claim_id:
            raise ValueError("Declaration and settlement claim_id mismatch")
        key = (decl.workflow_ref, decl.objective_ref, decl.unit, decl.currency)
        grouped.setdefault(key, []).append((decl, settlement))

    drilldowns: list[WorkflowValueClaimDrilldown] = []
    for (wf_ref, obj_ref, unit, currency), items in sorted(
        grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])
    ):
        total_imp = Decimal(0)
        reductions: list[float] = []
        refs: set[str] = set()
        settled_n = 0
        for _decl, st in items:
            refs.update(st.evidence_refs)
            if st.status is ValueClaimStatus.IMPROVED:
                settled_n += 1
                total_imp += st.conservative_total_improvement or Decimal(0)
                if (
                    st.baseline_mean is not None
                    and st.baseline_mean > Decimal(0)
                    and st.conservative_improvement_per_event is not None
                ):
                    reductions.append(
                        float((st.conservative_improvement_per_event / st.baseline_mean) * 100)
                    )
        avg_red = round(sum(reductions) / len(reductions), 2) if reductions else None
        drilldowns.append(
            WorkflowValueClaimDrilldown(
                workflow_ref=wf_ref,
                objective_ref=obj_ref,
                unit=unit,
                currency=currency,
                settled_claim_count=settled_n,
                total_conservative_improvement=total_imp,
                average_reduction_pct=avg_red,
                evidence_refs=tuple(sorted(refs)),
            )
        )
    return tuple(drilldowns)


@dataclass(frozen=True, slots=True)
class ReleaseChangeEvent:
    """Item 34: Provider-neutral CI/CD deployment release change event."""

    change_id: str
    target_resource_ref: str
    actor_ref: str
    status: str
    occurred_at: datetime
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class ServiceCatalogEntry:
    """Item 34: Provider-neutral service catalog entry (CMDB / Backstage)."""

    service_id: str
    service_name: str
    criticality: str
    workload_id: str
    workload_name: str
    hosted_resource_refs: tuple[str, ...]
    ownership_id: str
    owner_ref: str
    escalation_ref: str
    effective_from: datetime
    source_ref: str


class DeploymentAndServiceCatalogBridge:
    """Item 34: Sync neutral release changes and service-catalog records into the ontology."""

    def __init__(self, store: OntologyInstanceStore) -> None:
        self._store = store

    async def sync_release_change(self, event: ReleaseChangeEvent) -> OntologyObjectRecord:
        record = OntologyObjectRecord(
            id=event.change_id,
            object_type="Change",
            properties={
                "id": event.change_id,
                "change_kind": "deployment_release",
                "target_ref": event.target_resource_ref,
                "actor_ref": event.actor_ref,
                "status": event.status,
                "occurred_at": event.occurred_at,
                "evidence_ref": event.evidence_ref,
            },
        )
        await self._store.upsert_object(record)
        await self._store.upsert_link(
            OntologyLinkRecord(
                "change_targets_resource", event.change_id, event.target_resource_ref
            )
        )
        return record

    async def sync_service_catalog_entry(self, entry: ServiceCatalogEntry) -> None:
        svc = OntologyObjectRecord(
            id=entry.service_id,
            object_type="BusinessService",
            properties={
                "id": entry.service_id,
                "name": entry.service_name,
                "criticality": entry.criticality,
                "effective_from": entry.effective_from,
                "source_ref": entry.source_ref,
            },
        )
        wl = OntologyObjectRecord(
            id=entry.workload_id,
            object_type="Workload",
            properties={
                "id": entry.workload_id,
                "name": entry.workload_name,
                "workload_kind": "service",
                "effective_from": entry.effective_from,
                "source_ref": entry.source_ref,
            },
        )
        own = OntologyObjectRecord(
            id=entry.ownership_id,
            object_type="Ownership",
            properties={
                "id": entry.ownership_id,
                "owner_ref": entry.owner_ref,
                "escalation_ref": entry.escalation_ref,
                "effective_from": entry.effective_from,
                "source_ref": entry.source_ref,
            },
        )
        for obj in (svc, wl, own):
            await self._store.upsert_object(obj)
        await self._store.upsert_link(
            OntologyLinkRecord("implemented_by", entry.service_id, entry.workload_id)
        )
        await self._store.upsert_link(
            OntologyLinkRecord("service_owned_by", entry.service_id, entry.ownership_id)
        )
        for res_ref in entry.hosted_resource_refs:
            await self._store.upsert_link(
                OntologyLinkRecord("workload_runs_on", entry.workload_id, res_ref)
            )


@dataclass(frozen=True, slots=True)
class ExternalChangeWindowRecord:
    """Item 35: Provider-neutral ITSM change-management window (CAB schedule/freeze)."""

    window_id: str
    window_kind: str
    scope_ref: str
    status: str
    effective_from: datetime
    effective_to: datetime
    policy_ref: str
    approval_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalOncallShiftRecord:
    """Item 35: Provider-neutral on-call shift rotation record."""

    ownership_id: str
    owner_ref: str
    oncall_escalation_ref: str
    effective_from: datetime
    effective_to: datetime | None
    source_ref: str


@dataclass(frozen=True, slots=True)
class ExternalAuditCorrelationReceipt:
    """Item 35: Immutable receipt linking an FDAI process audit digest to an ITSM ticket."""

    process_id: str
    external_ticket_ref: str
    audit_entry_digest: str
    correlated_at: datetime
    correlation_digest: str
    execution_authority: Literal[False] = False


class EnterpriseGovernanceOntologyBridge:
    """Item 35: Sync neutral ITSM change windows, on-call shifts, and audit ticket receipts."""

    def __init__(self, store: OntologyInstanceStore) -> None:
        self._store = store

    async def sync_change_window(self, window: ExternalChangeWindowRecord) -> OntologyObjectRecord:
        props: dict[str, Any] = {
            "id": window.window_id,
            "window_kind": window.window_kind,
            "scope_ref": window.scope_ref,
            "status": window.status,
            "effective_from": window.effective_from,
            "effective_to": window.effective_to,
            "policy_ref": window.policy_ref,
        }
        if window.approval_ref is not None:
            props["approval_ref"] = window.approval_ref
        record = OntologyObjectRecord(
            id=window.window_id,
            object_type="ChangeWindow",
            properties=props,
        )
        await self._store.upsert_object(record)
        return record

    async def sync_oncall_shift(self, shift: ExternalOncallShiftRecord) -> OntologyObjectRecord:
        props: dict[str, Any] = {
            "id": shift.ownership_id,
            "owner_ref": shift.owner_ref,
            "escalation_ref": shift.oncall_escalation_ref,
            "effective_from": shift.effective_from,
            "source_ref": shift.source_ref,
        }
        if shift.effective_to is not None:
            props["effective_to"] = shift.effective_to
        record = OntologyObjectRecord(
            id=shift.ownership_id,
            object_type="Ownership",
            properties=props,
        )
        await self._store.upsert_object(record)
        return record

    def bind_audit_receipt_to_ticket(
        self,
        *,
        process_id: str,
        external_ticket_ref: str,
        audit_entry_digest: str,
        correlated_at: datetime,
    ) -> ExternalAuditCorrelationReceipt:
        if not process_id.strip() or not external_ticket_ref.strip():
            raise ValueError("process_id and external_ticket_ref MUST be non-empty")
        if not audit_entry_digest.startswith("sha256:"):
            raise ValueError("audit_entry_digest MUST be SHA-256")
        digest = content_digest(
            {
                "process_id": process_id,
                "external_ticket_ref": external_ticket_ref,
                "audit_entry_digest": audit_entry_digest,
                "correlated_at": correlated_at.astimezone(UTC).isoformat(),
            }
        )
        return ExternalAuditCorrelationReceipt(
            process_id=process_id,
            external_ticket_ref=external_ticket_ref,
            audit_entry_digest=audit_entry_digest,
            correlated_at=correlated_at,
            correlation_digest=digest,
        )


__all__ = [
    "DecisionInboxCardView",
    "DecisionInboxViewModel",
    "DeploymentAndServiceCatalogBridge",
    "EnterpriseGovernanceOntologyBridge",
    "ExternalAuditCorrelationReceipt",
    "ExternalChangeWindowRecord",
    "ExternalOncallShiftRecord",
    "ReleaseChangeEvent",
    "ServiceCatalogEntry",
    "WorkflowValueClaimDrilldown",
    "build_decision_inbox_view_model",
    "build_workflow_value_claim_drilldowns",
    "decision_queue_projection_key",
    "persist_decision_queue_projection",
    "read_decision_queue_operator_payload",
]
