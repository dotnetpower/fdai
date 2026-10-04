from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.operational_planning import SpecialistPlanningCoordinator
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineageUnavailableError,
)
from fdai.delivery.kinetic_proposal import StateStoreKineticActionProposalStore
from fdai.delivery.prospective_lineage import (
    OperationalPlanningProspectiveFinalizer,
    StateStoreProspectiveLineageMaterializer,
    StateStoreProspectiveLineageReadinessReader,
    build_prospective_lineage_records,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.operational_planning.test_coordinator import (
    _context,
    _PassedConstraints,
    _Simulator,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 8, 30, 5, tzinfo=UTC)


async def test_finalized_prospective_lineage_requires_materialization_and_saga_seal() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    release = catalog.build_release()
    ontology_store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    target = OntologyObjectRecord(
        id="resource-example",
        object_type="Resource",
        properties={
            "id": "resource-example",
            "type": "compute.vm",
            "properties": {},
        },
        revision=0,
    )
    assert await ontology_store.create_object_if_absent(target) is not None
    coordinator = SpecialistPlanningCoordinator(
        logic_release_digest=release.digest,
        constraint_evaluator=_PassedConstraints(),
        simulator=_Simulator(),
    )
    projection = await coordinator.build(
        correlation_id="prospective-lineage:e2e",
        context=_context(),
        advice={"cost": "scale_down", "capacity": "scale_up"},
        impacts={"cost": 0.2, "capacity": 0.9},
        arguments_by_domain={
            "cost": {
                "target_resource_ref": "resource-example",
                "reason": "Cost anomaly supports the reviewed scale-down candidate.",
            },
            "capacity": {
                "target_resource_ref": "resource-example",
                "reason": "Capacity forecast crossed the reviewed scaling threshold.",
            },
        },
        created_at=NOW,
    )
    assert projection is not None
    selected_option_id = projection.selection.selected_option_id
    assert selected_option_id is not None
    projection = await coordinator.finalize(
        projection,
        selected_option_id=selected_option_id,
        recorded_at=NOW,
    )
    state_store = InMemoryStateStore()
    proposal_store = StateStoreKineticActionProposalStore(store=state_store)
    finalizer = OperationalPlanningProspectiveFinalizer(
        proposal_store=proposal_store,
        ontology_store=ontology_store,
        ontology_release=release,
        action_types=catalog.action_types,
    )
    finalized = await finalizer.finalize(projection)
    materializer = StateStoreProspectiveLineageMaterializer(
        state_store=state_store,
        proposal_store=proposal_store,
        ontology_store=ontology_store,
    )
    readiness = StateStoreProspectiveLineageReadinessReader(state_store)

    assert await readiness.ready(finalized.proposal.proposal_id) is False
    assert await materializer.materialize(finalized.envelope) is True
    assert await materializer.materialize(finalized.envelope) is False
    assert await readiness.ready(finalized.proposal.proposal_id) is False
    assert await materializer.seal_saga(
        lineage_id=finalized.envelope.id,
        subgraph_digest=finalized.envelope.subgraph_digest,
    )
    assert await readiness.ready(finalized.proposal.proposal_id) is True

    stored_envelope = await ontology_store.get_object(finalized.envelope.id)
    stored_option = await ontology_store.get_object(finalized.lineage.action_option.id)
    assert stored_envelope is not None
    assert stored_option is not None
    assert stored_option.properties["arguments"]["digest"] == (finalized.proposal.arguments_digest)
    assert stored_option.properties["preconditions"]
    assert all(
        effect.properties["predictor_version"] == release.digest
        for effect in finalized.lineage.expected_effects
    )
    assert all(
        effect.properties["direction"] in {"increase", "decrease", "hold"}
        for effect in finalized.lineage.expected_effects
    )


async def test_prospective_lineage_fails_closed_without_precondition_evidence() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    release = catalog.build_release()
    ontology_store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    target = OntologyObjectRecord(
        id="resource-example",
        object_type="Resource",
        properties={
            "id": "resource-example",
            "type": "compute.vm",
            "properties": {},
        },
        revision=1,
    )
    assert await ontology_store.create_object_if_absent(target) is not None
    coordinator = SpecialistPlanningCoordinator(
        logic_release_digest=release.digest,
        constraint_evaluator=_PassedConstraints(),
        simulator=_Simulator(),
    )
    projection = await coordinator.build(
        correlation_id="prospective-lineage:missing-precondition",
        context=_context(),
        advice={"capacity": "scale_up"},
        impacts={"capacity": 0.9},
        arguments_by_domain={
            "capacity": {
                "target_resource_ref": "resource-example",
                "reason": "Capacity forecast crossed the reviewed scaling threshold.",
            },
        },
        created_at=NOW,
    )
    assert projection is not None
    selected_option_id = projection.selection.selected_option_id
    assert selected_option_id is not None
    projection = await coordinator.finalize(
        projection,
        selected_option_id=selected_option_id,
        recorded_at=NOW,
    )
    proposal_store = StateStoreKineticActionProposalStore(store=InMemoryStateStore())
    finalizer = OperationalPlanningProspectiveFinalizer(
        proposal_store=proposal_store,
        ontology_store=ontology_store,
        ontology_release=release,
        action_types=catalog.action_types,
    )
    finalized = await finalizer.finalize(projection)
    selected = next(
        option
        for option in projection.plan.decision_case.options
        if option.option_id == projection.plan.selection.selected_option_id
    )
    stripped_selected = replace(selected, constraint_evaluation_refs=())
    stripped_case = replace(
        projection.plan.decision_case,
        options=tuple(
            stripped_selected if option.option_id == selected.option_id else option
            for option in projection.plan.decision_case.options
        ),
    )
    stripped_plan = replace(projection.plan, decision_case=stripped_case)

    with pytest.raises(
        ProspectiveLineageUnavailableError,
        match="precondition_evidence_missing",
    ):
        build_prospective_lineage_records(plan=stripped_plan, proposal=finalized.proposal)
