from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.odin import Odin
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.core.impact_analysis import ChangeAssessmentService, ImpactAnalyzer
from fdai.core.operational_context import OperationalContextMaterializer, SourceFreshness
from fdai.core.operational_planning import (
    ConstraintEvaluation,
    ConstraintStatus,
    SimulationReceipt,
    SimulationStatus,
    SpecialistPlanningCoordinator,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[4]
AT = "2026-07-31T00:00:00Z"


def _source_freshness_payload() -> list[dict[str, object]]:
    return [
        {
            "source": source,
            "observed_at": AT,
            "max_age_seconds": max_age_seconds,
        }
        for source, max_age_seconds in (
            ("cost:monthly", 86400),
            ("metrics:availability", 300),
        )
    ]


def _source_freshness() -> tuple[SourceFreshness, ...]:
    observed_at = datetime.fromisoformat(AT.replace("Z", "+00:00"))
    return tuple(
        SourceFreshness(
            source=str(item["source"]),
            observed_at=observed_at,
            max_age_seconds=int(item["max_age_seconds"]),
        )
        for item in _source_freshness_payload()
    )


async def _context_store() -> InMemoryOntologyInstanceStore:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    records = (
        OntologyObjectRecord(
            id="resource-example",
            object_type="Resource",
            properties={"id": "resource-example", "type": "app-service"},
        ),
        OntologyObjectRecord(
            id="workload-example",
            object_type="Workload",
            properties={
                "id": "workload-example",
                "name": "Example Workload",
                "workload_kind": "api",
                "effective_from": AT,
                "source_ref": "service-manifest:example",
            },
        ),
        OntologyObjectRecord(
            id="service-example",
            object_type="BusinessService",
            properties={
                "id": "service-example",
                "name": "Example Service",
                "criticality": "high",
                "effective_from": AT,
                "source_ref": "service-catalog:example",
            },
        ),
        OntologyObjectRecord(
            id="slo-example",
            object_type="ServiceObjective",
            properties={
                "id": "slo-example",
                "objective_kind": "availability",
                "metric": "successful_request_ratio",
                "unit": "ratio",
                "target": 0.999,
                "window_seconds": 2592000,
                "measurement_source_ref": "metrics:availability",
                "freshness_seconds": 300,
                "effective_from": AT,
            },
        ),
        OntologyObjectRecord(
            id="cost-example",
            object_type="CostObjective",
            properties={
                "id": "cost-example",
                "objective_kind": "run_rate",
                "currency": "USD",
                "target": 1000.0,
                "period_seconds": 2592000,
                "measurement_source_ref": "cost:monthly",
                "freshness_seconds": 86400,
                "effective_from": AT,
            },
        ),
    )
    for record in records:
        await store.upsert_object(record)
    for link in (
        OntologyLinkRecord(
            link_type="workload_runs_on",
            from_id="workload-example",
            to_id="resource-example",
        ),
        OntologyLinkRecord(
            link_type="implemented_by",
            from_id="service-example",
            to_id="workload-example",
        ),
        OntologyLinkRecord(
            link_type="service_has_service_objective",
            from_id="service-example",
            to_id="slo-example",
        ),
        OntologyLinkRecord(
            link_type="service_has_cost_objective",
            from_id="service-example",
            to_id="cost-example",
        ),
    ):
        await store.upsert_link(link)
    return store


@pytest.mark.parametrize("hil_margin", [0.1, 1.0])
async def test_specialist_conflict_reaches_objective_aware_hil_verdict(
    hil_margin: float,
) -> None:
    bus = InMemoryBus(registry=load_pantheon())
    store = await _context_store()
    forseti = Forseti(
        bus=bus,
        operational_context=OperationalContextMaterializer(store=store),
    )
    odin = Odin(bus=bus, hil_margin=hil_margin)
    thor = Thor(bus=bus)
    var = Var(bus=bus)
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)

    await forseti.on_typed_message(
        "object.cost-anomaly",
        {
            "correlation_id": "correlation-example",
            "resource_id": "resource-example",
            "recommendation": "scale_down",
            "impact": 0.2,
            "observed_at": AT,
            "source_freshness": _source_freshness_payload(),
        },
    )
    await forseti.on_typed_message(
        "object.capacity-forecast",
        {
            "correlation_id": "correlation-example",
            "resource_id": "resource-example",
            "recommendation": "scale_up",
            "impact": 1.0,
            "observed_at": AT,
            "source_freshness": _source_freshness_payload(),
        },
    )

    requests = bus.messages_on("object.arbitration-request")
    verdicts = bus.messages_on("object.verdict")
    assert requests[-1].payload["decision_case"]["selected_option_id"] == "capacity:scale_up"
    assert verdicts[-1].payload["action_type"] == "ops.scale-out"
    assert verdicts[-1].payload["risk_verdict"] == "hil"
    assert verdicts[-1].payload["decision_case"]["case_id"]
    action_runs = bus.messages_on("object.action-run")
    assert action_runs[-1].payload["state"] == "hil_pending"
    assert action_runs[-1].payload["decision_case"]["case_id"]
    ticket = var.pending_tickets()[0]
    assert ticket.decision_case is not None
    assert ticket.decision_case["case_id"] == verdicts[-1].payload["decision_case"]["case_id"]
    assert ticket.action_type == "ops.scale-out"
    assert ticket.decision_case["options"]
    assert ticket.decision_case["evidence_refs"]
    assert ticket.decision_case["no_action_effects"]
    assert ticket.decision_case["options"][0]["effects"]
    if hil_margin == 1.0:
        assert verdicts[-1].payload["reason"] == "arbitration_unresolved"


async def test_planned_change_assessment_lowers_arbitrated_decision_case() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    store = await _context_store()
    forseti = Forseti(
        bus=bus,
        operational_context=OperationalContextMaterializer(store=store),
        change_assessor=ChangeAssessmentService(analyzer=ImpactAnalyzer(store=store)),
    )
    odin = Odin(bus=bus, hil_margin=0.0)
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)

    await forseti.on_typed_message(
        "object.event",
        {
            "correlation_id": "change-correlation",
            "idempotency_key": "change-event",
            "resource_id": "resource-example",
            "event_type": "restart_needed",
            "detected_at": AT,
            "domain_advice": {"cost": "scale_down", "capacity": "scale_up"},
            "source_freshness": _source_freshness_payload(),
            "normalized_change": {
                "id": "change-1",
                "correlation_id": "change-correlation",
                "intent_kind": "planned",
                "target_ref": "resource-example",
                "occurred_at": AT,
                "desired_state_digest": "sha256:desired",
                "plan_receipt_ref": "plan:1",
            },
        },
    )

    request_case = bus.messages_on("object.arbitration-request")[-1].payload["decision_case"]
    assert request_case["change_assessment"]["review_required"] is True
    assert "graph_stale" in request_case["change_assessment"]["reasons"]
    case_verdict = next(
        message.payload
        for message in bus.messages_on("object.verdict")
        if message.payload.get("decision_case") is not None
    )
    assert case_verdict["risk_verdict"] == "hil"
    assert case_verdict["decision_case"]["change_assessment"]["review_required"] is True


async def test_malformed_semantic_case_cannot_reach_human_approval() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    thor = Thor(bus=bus)
    var = Var(bus=bus)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)

    await bus.publish(
        "Forseti",
        "object.verdict",
        {
            "correlation_id": "malformed-case",
            "idempotency_key": "malformed-case:verdict",
            "resource_id": "resource-example",
            "action_type": "ops.scale-out",
            "risk_verdict": "hil",
            "reason": "arbitration_unresolved",
            "decision_case": {"case_id": "incomplete"},
        },
    )

    assert bus.messages_on("object.action-run")[-1].payload["state"] == "deny_dropped"
    assert var.pending_tickets() == ()


async def test_selected_option_action_mismatch_is_denied() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    store = await _context_store()
    forseti = Forseti(operational_context=OperationalContextMaterializer(store=store))
    request = await forseti._emit_arbitration_request(  # noqa: SLF001 - semantic wire fixture
        resource_id="resource-example",
        advice={"cost": "scale_down", "capacity": "scale_up"},
        correlation_id="mismatched-selection",
        impacts={"cost": 0.2, "capacity": 1.0},
        observed_at=AT,
        source_freshness=_source_freshness(),
    )
    thor = Thor(bus=bus)
    var = Var(bus=bus)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)

    await bus.publish(
        "Forseti",
        "object.verdict",
        {
            "correlation_id": "mismatched-selection",
            "idempotency_key": "mismatched-selection:verdict",
            "resource_id": "resource-example",
            "action_type": "ops.scale-in",
            "risk_verdict": "hil",
            "reason": "arbitration_resolved",
            "decision_case": request["decision_case"],
        },
    )

    assert bus.messages_on("object.action-run")[-1].payload["state"] == "deny_dropped"
    assert var.pending_tickets() == ()


class _PlanningConstraints:
    async def evaluate(self, *, context, option):
        return (
            ConstraintEvaluation(
                "protected_objectives",
                ConstraintStatus.PASSED,
                3,
                "verified",
                (f"context:{context.snapshot_id}", *option.evidence_refs),
            ),
        )


class _PlanningSimulator:
    async def simulate(
        self, *, context, candidate_id, action_type, effects, observed_at
    ) -> SimulationReceipt:
        return SimulationReceipt(
            receipt_id=f"simulation:{candidate_id}",
            candidate_id=candidate_id,
            snapshot_id=context.snapshot_id,
            logic_invocation_id="logic-invocation:" + "f" * 64,
            status=SimulationStatus.SUCCEEDED,
            started_at=observed_at,
            completed_at=observed_at,
            evidence_refs=(f"simulation:{action_type}", f"effects:{len(effects)}"),
        )


async def test_specialist_events_carry_operational_plan_to_human_review() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    store = await _context_store()
    planning = SpecialistPlanningCoordinator(
        logic_release_digest="sha256:" + "e" * 64,
        constraint_evaluator=_PlanningConstraints(),
        simulator=_PlanningSimulator(),
    )
    forseti = Forseti(
        bus=bus,
        operational_context=OperationalContextMaterializer(store=store),
        operational_planner=planning,
    )
    odin = Odin(bus=bus)
    thor = Thor(bus=bus)
    var = Var(bus=bus)
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)

    await forseti.on_typed_message(
        "object.cost-anomaly",
        {
            "correlation_id": "planning-e2e",
            "resource_id": "resource-example",
            "recommendation": "scale_down",
            "impact": 0.2,
            "observed_at": AT,
            "source_freshness": _source_freshness_payload(),
        },
    )
    await forseti.on_typed_message(
        "object.capacity-forecast",
        {
            "correlation_id": "planning-e2e",
            "resource_id": "resource-example",
            "recommendation": "scale_up",
            "impact": 0.9,
            "observed_at": AT,
            "source_freshness": _source_freshness_payload(),
        },
    )

    verdict = bus.messages_on("object.verdict")[-1].payload
    case = verdict["decision_case"]
    assert case["operational_plan"]["complete"] is True
    assert case["logic_release_digest"] == "sha256:" + "e" * 64
    assert verdict["action_type"] == "ops.scale-out"
    assert var.pending_tickets()[0].decision_case["operational_plan"]["plan_id"]


async def test_non_semantic_decision_case_action_mismatch_is_denied() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    store = await _context_store()
    forseti = Forseti(operational_context=OperationalContextMaterializer(store=store))
    request = await forseti._emit_arbitration_request(  # noqa: SLF001 - semantic wire fixture
        resource_id="resource-example",
        advice={"cost": "scale_down", "capacity": "scale_up"},
        correlation_id="non-semantic-mismatch",
        impacts={"cost": 0.2, "capacity": 1.0},
        observed_at=AT,
        source_freshness=_source_freshness(),
    )
    thor = Thor(bus=bus)
    var = Var(bus=bus)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)

    await bus.publish(
        "Forseti",
        "object.verdict",
        {
            "correlation_id": "non-semantic-mismatch",
            "idempotency_key": "non-semantic-mismatch:verdict",
            "resource_id": "resource-example",
            "action_type": "ops.scale-in",
            "risk_verdict": "hil",
            "reason": "policy_review",
            "decision_case": request["decision_case"],
        },
    )

    assert bus.messages_on("object.action-run")[-1].payload["state"] == "deny_dropped"
    assert var.pending_tickets() == ()
