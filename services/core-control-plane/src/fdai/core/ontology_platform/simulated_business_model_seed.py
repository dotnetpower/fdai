"""Seed builders for simulated business operating models and 52-rule objective bindings."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.ontology_platform.catalog_projection import CatalogOntologyProjection
from fdai.core.ontology_platform.objective_binding_projection import (
    build_objective_binding_projection,
)
from fdai.rule_catalog.schema.control_objective import (
    ApplicableOntology,
    ControlObjective,
    ControlObjectiveState,
)
from fdai.rule_catalog.schema.equivalence_validation import (
    EquivalenceReceiptState,
    EquivalenceValidationReceipt,
    EquivalenceValidationResult,
)
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.rule import rule_content_hash
from fdai.rule_catalog.schema.rule_objective_binding import (
    BindingState,
    CatalogRecordPin,
    ObjectiveRelationship,
    RuleObjectiveBinding,
    RuleObjectiveBindingMigrationReport,
    build_rule_objective_binding_migration_report,
)
from fdai.shared.contracts.models import OntologyProvenance, Rule
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.operating_model import OperatingModelSnapshot


def _sha256(seed: str) -> str:
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def build_simulated_business_operating_model(
    *,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> OperatingModelSnapshot:
    """Build a complete 3-service, 6-resource operating model with all 6 intent types."""

    start = (effective_from or datetime(2026, 1, 1, tzinfo=UTC)).astimezone(UTC).isoformat()
    end = (effective_to or datetime(2027, 1, 1, tzinfo=UTC)).astimezone(UTC).isoformat()
    specs = (
        (
            "cap-commerce-checkout",
            "Commerce Checkout Capability",
            "svc-checkout-api",
            "Checkout API Service",
            ["결제 서비스", "checkout-service"],
            "tier-1-critical",
            "wl-checkout-aks",
            "Checkout AKS Workload",
            "kubernetes-deployment",
            (("res-aks-checkout-01", "kubernetes-cluster"), ("res-kv-secrets-01", "secret-store")),
            "obj-slo-checkout",
            "obj-rto-checkout",
            "obj-cost-checkout",
            "budget-checkout",
            "constraint-checkout-ha",
            "owner-checkout",
            "window-checkout",
        ),
        (
            "cap-order-fulfillment",
            "Order Fulfillment Capability",
            "svc-order-processor",
            "Order Processor Service",
            ["주문 처리 서비스", "order-service"],
            "tier-1-critical",
            "wl-order-worker",
            "Order Worker Workload",
            "container-app",
            (("res-pg-orders-01", "postgresql-server"), ("res-sql-billing-01", "sql-database")),
            "obj-slo-orders",
            "obj-rto-orders",
            "obj-cost-orders",
            "budget-orders",
            "constraint-orders-dr",
            "owner-orders",
            "window-orders",
        ),
        (
            "cap-ai-recommendations",
            "AI Recommendations Capability",
            "svc-recommendation-engine",
            "Recommendation Engine Service",
            ["추천 엔진 서비스", "recommendation-service"],
            "tier-2-important",
            "wl-rec-gpu-pool",
            "Recommendation GPU Workload",
            "vm-scale-set",
            (("res-vmss-rec-01", "compute.vm-scale-set"), ("res-law-ops-01", "log-workspace")),
            "obj-slo-rec",
            "obj-rto-rec",
            "obj-cost-rec",
            "budget-rec",
            "constraint-rec-cost",
            "owner-rec",
            "window-rec",
        ),
    )
    objects: list[OntologyObjectRecord] = []
    links: list[OntologyLinkRecord] = []
    src = "source:approved-enterprise-service-catalog"
    for (
        cap_id,
        cap_name,
        svc_id,
        svc_name,
        aliases,
        crit,
        wl_id,
        wl_name,
        wl_kind,
        resources,
        slo_id,
        rto_id,
        cost_id,
        budget_id,
        const_id,
        owner_id,
        win_id,
    ) in specs:
        objects.extend(
            (
                OntologyObjectRecord(
                    cap_id,
                    "BusinessCapability",
                    {"id": cap_id, "name": cap_name, "effective_from": start, "source_ref": src},
                ),
                OntologyObjectRecord(
                    svc_id,
                    "BusinessService",
                    {
                        "id": svc_id,
                        "name": svc_name,
                        "aliases": aliases,
                        "criticality": crit,
                        "effective_from": start,
                        "source_ref": src,
                    },
                ),
                OntologyObjectRecord(
                    wl_id,
                    "Workload",
                    {
                        "id": wl_id,
                        "name": wl_name,
                        "aliases": aliases,
                        "workload_kind": wl_kind,
                        "effective_from": start,
                        "source_ref": src,
                    },
                ),
                OntologyObjectRecord(
                    slo_id,
                    "ServiceObjective",
                    {
                        "id": slo_id,
                        "objective_kind": "availability",
                        "metric": "availability",
                        "unit": "ratio",
                        "target": 0.999,
                        "window_seconds": 2592000,
                        "measurement_source_ref": "source:azure-monitor-sli",
                        "freshness_seconds": 3600,
                        "effective_from": start,
                    },
                ),
                OntologyObjectRecord(
                    rto_id,
                    "RecoveryObjective",
                    {
                        "id": rto_id,
                        "rto_seconds": 900,
                        "rpo_seconds": 300,
                        "measurement_source_ref": "source:dr-drill-verifier",
                        "freshness_seconds": 86400,
                        "effective_from": start,
                    },
                ),
                OntologyObjectRecord(
                    cost_id,
                    "CostObjective",
                    {
                        "id": cost_id,
                        "objective_kind": "monthly_budget",
                        "currency": "USD",
                        "target": 15000,
                        "period_seconds": 2592000,
                        "measurement_source_ref": "source:finops-cost-export",
                        "freshness_seconds": 86400,
                        "effective_from": start,
                    },
                ),
                OntologyObjectRecord(
                    budget_id,
                    "Budget",
                    {
                        "id": budget_id,
                        "service_ref": svc_id,
                        "cost_objective_ref": cost_id,
                        "currency": "USD",
                        "limit": 15000,
                        "period_start": start,
                        "period_end": end,
                        "effective_from": start,
                        "source_ref": "source:finops-cost-export",
                        "source_revision": "rev-1",
                        "source_authority_ref": "authority:finops-board",
                    },
                ),
                OntologyObjectRecord(
                    const_id,
                    "ArchitectureConstraint",
                    {
                        "id": const_id,
                        "constraint_kind": "zone_redundancy",
                        "expression_ref": "policy:zone-redundancy",
                        "severity": "high",
                        "effective_from": start,
                    },
                ),
                OntologyObjectRecord(
                    owner_id,
                    "Ownership",
                    {
                        "id": owner_id,
                        "owner_ref": f"group:{svc_id}-owners",
                        "escalation_ref": f"route:{svc_id}-oncall",
                        "effective_from": start,
                        "source_ref": src,
                    },
                ),
                OntologyObjectRecord(
                    win_id,
                    "ChangeWindow",
                    {
                        "id": win_id,
                        "window_kind": "maintenance",
                        "scope_ref": svc_id,
                        "status": "approved",
                        "effective_from": start,
                        "effective_to": end,
                        "policy_ref": "policy:approved-change-window",
                    },
                ),
            )
        )
        links.extend(
            (
                OntologyLinkRecord("delivered_by", cap_id, svc_id),
                OntologyLinkRecord("implemented_by", svc_id, wl_id),
                OntologyLinkRecord("service_has_service_objective", svc_id, slo_id),
                OntologyLinkRecord("service_has_recovery_objective", svc_id, rto_id),
                OntologyLinkRecord("service_has_cost_objective", svc_id, cost_id),
                OntologyLinkRecord("service_has_budget", svc_id, budget_id),
                OntologyLinkRecord("budget_implements_cost_objective", budget_id, cost_id),
                OntologyLinkRecord("service_has_architecture_constraint", svc_id, const_id),
                OntologyLinkRecord("service_owned_by", svc_id, owner_id),
                OntologyLinkRecord("workload_owned_by", wl_id, owner_id),
                OntologyLinkRecord("objective_owned_by", slo_id, owner_id),
            )
        )
        for res_id, res_type in resources:
            objects.append(
                OntologyObjectRecord(
                    res_id,
                    "Resource",
                    {"id": res_id, "type": res_type, "name": res_id, "location": "koreacentral"},
                )
            )
            links.append(OntologyLinkRecord("workload_runs_on", wl_id, res_id))
    return OperatingModelSnapshot(
        source_revision="simulated-enterprise-operating-model@1.0.0",
        objects=tuple(objects),
        links=tuple(links),
    )


def project_all_authored_rule_objectives(
    *,
    rules: Sequence[Rule],
    repo_root: Path,
) -> tuple[CatalogOntologyProjection, RuleObjectiveBindingMigrationReport]:
    """Synthesize and project reviewed ControlObjectives and bindings for all 52 Rules."""

    objectives: list[ControlObjective] = []
    bindings: list[RuleObjectiveBinding] = []
    receipts: list[EquivalenceValidationReceipt] = []
    now_dt = datetime(2026, 10, 1, tzinfo=UTC)
    for rule in rules:
        rule_ref = f"{rule.id}@{rule.version}"
        r_digest = rule_content_hash(rule)
        impl_digest = load_rego_semantics(
            repo_root / rule.check_logic.reference
        ).normalized_semantic_digest
        obj_id = f"objective.{rule.id}"
        obj_digest = _sha256(f"ctrl-obj:{obj_id}:1.0.0")
        ev_refs = tuple(
            sorted(
                f"property.{rule.resource_type}.{prop}"
                for prop in (rule.evaluates or ("configuration",))
            )
        )
        objectives.append(
            ControlObjective.model_construct(
                schema_version="1.0.0",
                id=obj_id,
                version="1.0.0",
                title=f"Control objective for {rule.id}",
                description=f"Governed control objective for {rule.id}",
                operating_domain=rule.category.value,
                protected_outcome_refs=(f"outcome.{rule.id}",),
                applicable_ontology=ApplicableOntology(
                    object_type="Resource",
                    resource_types=(rule.resource_type,),
                    property_refs=ev_refs,
                ),
                predicate_family=f"Invariant enforced by {rule.id}",
                state=ControlObjectiveState.REVIEWED,
                semantic_surface_refs=(f"rule:{rule_ref}",),
                content_digest=obj_digest,
                provenance=OntologyProvenance(
                    source_url="https://github.com/dotnetpower/fdai",
                    resolved_ref=f"control-objective:{obj_id}@1.0.0",
                    content_hash=obj_digest,
                    license="MIT",
                    retrieved_at=now_dt,
                ),
            )
        )
        rec_id = f"equivalence.{rule.id}"
        rec_digest = _sha256(f"eq-receipt:{rec_id}:1.0.0")
        receipts.append(
            EquivalenceValidationReceipt.model_construct(
                id=rec_id,
                version="1.0.0",
                result=EquivalenceValidationResult.VALIDATED,
                reviewer="Heimdall",
                state=EquivalenceReceiptState.REVIEWED,
                content_digest=rec_digest,
            )
        )
        bind_id = f"binding.{rule.id}"
        bind_digest = _sha256(f"binding:{bind_id}:{obj_digest}:{r_digest}")
        bindings.append(
            RuleObjectiveBinding.model_construct(
                schema_version="1.0.0",
                id=bind_id,
                version="1.0.0",
                objective=CatalogRecordPin(ref=f"{obj_id}@1.0.0", content_digest=obj_digest),
                rule=CatalogRecordPin(ref=rule_ref, content_digest=r_digest),
                relationship=ObjectiveRelationship.REALIZES,
                applicability_delta={},
                variant_dimensions=(),
                implementation_signature_digest=impl_digest,
                evidence_signature_digest=_sha256(f"ev-sig:{rule_ref}"),
                required_evidence_refs=ev_refs,
                equivalence_receipt=CatalogRecordPin(
                    ref=f"{rec_id}@1.0.0",
                    content_digest=rec_digest,
                ),
                non_equivalence_reasons=(),
                reviewer="Mimir",
                state=BindingState.REVIEWED,
                content_digest=bind_digest,
            )
        )
    projection = build_objective_binding_projection(
        objectives=tuple(objectives),
        rules=tuple(rules),
        bindings=tuple(bindings),
        receipts=tuple(receipts),
    )
    authored_refs = frozenset(f"{rule.id}@{rule.version}" for rule in rules)
    report = build_rule_objective_binding_migration_report(
        authored_rule_refs=authored_refs,
        bindings=tuple(bindings),
        ambiguous_rule_refs=frozenset(),
    )
    return projection, report
