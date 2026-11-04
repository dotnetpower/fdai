"""Tests for Area G (Items 31-35): Operator Decision Queue, Console Inbox, and bridges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fdai.core.decision_case.decision_queue import (
    DecisionQueueApprovalControl,
    DecisionQueueProjection,
    build_decision_queue_item,
    build_decision_queue_projection,
)
from fdai.core.decision_case.models import (
    ActionOption,
    DecisionCase,
    DecisionSelection,
    ObjectiveEffect,
)
from fdai.core.measurement.value_claim import (
    CohortRole,
    ObservationLane,
    ValueClaimDeclaration,
    ValueCohortObservation,
    ValueDirection,
    ValueUnit,
    settle_value_claim,
)
from fdai.core.ontology_platform.decision_functions import (
    CostOfDelayEvidence,
    assess_cost_of_delay,
)
from fdai.core.ontology_platform.enterprise_governance_bridges import (
    DeploymentAndServiceCatalogBridge,
    EnterpriseGovernanceOntologyBridge,
    ExternalChangeWindowRecord,
    ExternalOncallShiftRecord,
    ReleaseChangeEvent,
    ServiceCatalogEntry,
    build_decision_inbox_view_model,
    build_workflow_value_claim_drilldowns,
    persist_decision_queue_projection,
    read_decision_queue_operator_payload,
)
from fdai.core.workflow.ontology_native import OntologyOwnershipApprovalResolver
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def _sample_projection() -> DecisionQueueProjection:
    eff = ObjectiveEffect("obj-1", 0.8, 0.9, "mttr", -300.0, -100.0, 1800)
    opt = ActionOption("opt-1", "ops.restart-service", (eff,), ("ev:1",))
    case = DecisionCase(
        "case-1",
        "corr-1",
        "snap-1",
        NOW,
        (eff,),
        (opt,),
        ("obj-1",),
        ("c-1",),
        ("ev:1",),
        process_id="proc-1",
    )
    sel = DecisionSelection("opt-1", (("opt-1", 0.8),), 0.8, True, "best")
    cost = assess_cost_of_delay(
        CostOfDelayEvidence(Decimal("50"), "USD", "basis:1", NOW),
        target_ref="res-1",
        delay_hours=3,
    )
    item = build_decision_queue_item(
        case=case,
        selection=sel,
        target_resource_ref="res-1",
        approval_control=DecisionQueueApprovalControl(True, "owner", 2, True),
        blast_radius_tier="low",
        change_risk_tier="medium",
        cost_of_delay_reading=cost,
    )
    return build_decision_queue_projection((item,), as_of=NOW)


async def test_items_31_32_33_operator_decision_queue_inbox_and_value_claim_drilldown() -> None:
    store = InMemoryStateStore()
    proj = _sample_projection()

    # Item 31: persist and read through Operator payload helper
    await persist_decision_queue_projection(
        principal_id="operator-1", scope_ref="global", projection=proj, store=store
    )
    payload = await read_decision_queue_operator_payload(
        principal_id="operator-1", scope_ref="global", store=store
    )
    assert payload["state"] == "complete"
    assert payload["read_only"] is True
    assert payload["authority"] == "none"
    assert payload["items"][0]["cost_of_delay_amount"] == "150"

    # Item 32: Console Decision Inbox view model
    inbox = build_decision_inbox_view_model(proj)
    assert inbox.read_only is True
    assert inbox.total_pending_count == 1
    assert inbox.cards[0].cost_badge == "150 USD"
    assert inbox.cards[0].uncertainty_pct == 10
    assert inbox.cards[0].quorum_label == "owner (quorum 2)"

    # Item 33: Console ValueClaim drill-down by workflow
    decl = ValueClaimDeclaration(
        claim_id="c-1",
        workflow_ref="blast-radius-gated-service-restart",
        workflow_version="1.0.0",
        objective_ref="obj-mttr",
        metric_name="mttr_seconds",
        unit=ValueUnit.DURATION_SECONDS,
        direction=ValueDirection.DECREASE_IS_BETTER,
        target_value=Decimal("200"),
        scenario_set_version="s1",
        window_start=NOW - timedelta(days=10),
        window_end=NOW - timedelta(days=1),
        min_samples_per_cohort=5,
    )
    base = ValueCohortObservation(
        role=CohortRole.BASELINE,
        lane=ObservationLane.INDEPENDENT_OBSERVATION,
        scenario_set_version="s1",
        complete=True,
        samples=tuple(Decimal(v) for v in ("600", "600", "600", "600", "600", "600")),
        evidence_refs=("ev:b",),
        observed_at=NOW,
    )
    treat = ValueCohortObservation(
        role=CohortRole.TREATMENT,
        lane=ObservationLane.INDEPENDENT_OBSERVATION,
        scenario_set_version="s1",
        complete=True,
        samples=tuple(Decimal(v) for v in ("300", "300", "300", "300", "300", "300")),
        evidence_refs=("ev:t",),
        observed_at=NOW,
    )
    settlement = settle_value_claim(decl, (base, treat))
    drilldowns = build_workflow_value_claim_drilldowns(((decl, settlement),))
    assert len(drilldowns) == 1
    assert drilldowns[0].settled_claim_count == 1
    assert drilldowns[0].total_conservative_improvement == Decimal("1800")
    assert drilldowns[0].average_reduction_pct == 50.0


async def test_items_34_35_deployment_service_catalog_and_itsm_governance_bridges() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types, link_types=catalog.link_types
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="res-aks-1",
            object_type="Resource",
            properties={"id": "res-aks-1", "type": "kubernetes-cluster"},
        )
    )

    # Item 34: CI/CD Release + Service Catalog sync
    cat_bridge = DeploymentAndServiceCatalogBridge(store)
    await cat_bridge.sync_release_change(
        ReleaseChangeEvent(
            change_id="chg-rel-101",
            target_resource_ref="res-aks-1",
            actor_ref="ci:github-actions",
            status="succeeded",
            occurred_at=NOW - timedelta(minutes=20),
            evidence_ref="release:tag-v1.2",
        )
    )
    await cat_bridge.sync_service_catalog_entry(
        ServiceCatalogEntry(
            service_id="svc-orders",
            service_name="Order Fulfillment",
            criticality="critical",
            workload_id="wl-orders",
            workload_name="order-api",
            hosted_resource_refs=("res-aks-1",),
            ownership_id="own-orders",
            owner_ref="team:orders-eng",
            escalation_ref="oncall:orders-tier1",
            effective_from=NOW - timedelta(days=30),
            source_ref="catalog:backstage",
        )
    )

    # Item 35: ITSM ChangeWindow + On-call rotation update + Audit correlation receipt
    gov_bridge = EnterpriseGovernanceOntologyBridge(store)
    await gov_bridge.sync_change_window(
        ExternalChangeWindowRecord(
            window_id="win-cab-500",
            window_kind="maintenance",
            scope_ref="res-aks-1",
            status="approved",
            effective_from=NOW - timedelta(hours=1),
            effective_to=NOW + timedelta(hours=3),
            policy_ref="cab:standard-change",
            approval_ref="itsm:CHG00500",
        )
    )
    await gov_bridge.sync_oncall_shift(
        ExternalOncallShiftRecord(
            ownership_id="own-orders",
            owner_ref="team:orders-eng",
            oncall_escalation_ref="oncall:orders-weekend-shift",
            effective_from=NOW - timedelta(days=1),
            effective_to=NOW + timedelta(days=2),
            source_ref="oncall:schedule-1",
        )
    )
    corr = gov_bridge.bind_audit_receipt_to_ticket(
        process_id="proc-500",
        external_ticket_ref="itsm:CHG00500",
        audit_entry_digest="sha256:" + "f" * 64,
        correlated_at=NOW,
    )
    assert corr.execution_authority is False
    assert corr.correlation_digest.startswith("sha256:")

    # Verify dynamic ownership resolver sees the synced catalog & updated on-call shift
    resolver = OntologyOwnershipApprovalResolver(store)
    approvers = await resolver.resolve(target_resource_ref="res-aks-1", at=NOW)
    assert approvers is not None
    assert approvers.owner_refs == ("team:orders-eng",)
    assert approvers.escalation_refs == ("oncall:orders-weekend-shift",)
