from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fdai.core.operational_planning.hypothesis_lineage import (
    OperationalHypothesisLineage,
    OperationalHypothesisLineageProjector,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[5]
_NOW = datetime(2026, 8, 12, tzinfo=UTC)
_LINEAGE_OBJECT_TYPES = frozenset(
    {"DecisionCase", "ActionOption", "ExpectedEffect", "ActionRun", "ObservedOutcome"}
)
_LINEAGE_LINK_TYPES = frozenset({"considers", "expects", "executed_as", "resulted_in"})
_ProjectionCall = tuple[tuple[OntologyObjectRecord, ...], tuple[OntologyLinkRecord, ...]]


class _Store:
    def __init__(self) -> None:
        self.objects: dict[str, OntologyObjectRecord] = {}
        self.calls: list[_ProjectionCall] = []

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        return self.objects.get(object_id)

    async def replace_subgraph(
        self,
        *,
        objects: tuple[OntologyObjectRecord, ...],
        links: tuple[OntologyLinkRecord, ...],
        **_kwargs: object,
    ) -> None:
        self.calls.append((objects, links))
        self.objects.update((item.id, item) for item in objects)


def _lineage(*, verification: str = "independent") -> OperationalHypothesisLineage:
    decision_case = OntologyObjectRecord(
        "case-1",
        "DecisionCase",
        {
            "id": "case-1",
            "target_ref": "workload-1",
            "evidence_cutoff": _NOW,
            "context_digest": "sha256:context",
            "no_action_baseline": {"metric": "latency_ms", "expected": 240.0},
            "uncertainty": 0.1,
            "status": "selected",
            "created_at": _NOW,
        },
    )
    action_option = OntologyObjectRecord(
        "option-1",
        "ActionOption",
        {
            "id": "option-1",
            "decision_case_id": decision_case.id,
            "action_type_ref": "ops.scale-out",
            "arguments": {"replicas": 2},
            "expected_effect_ref": "effect-1",
            "preconditions": ["fresh_context"],
            "option_kind": "intervention",
        },
    )
    expected_effect = OntologyObjectRecord(
        "effect-1",
        "ExpectedEffect",
        {
            "id": "effect-1",
            "metric": "latency_ms",
            "direction": "decrease",
            "lower_bound": 80.0,
            "upper_bound": 140.0,
            "window_seconds": 300,
            "uncertainty": 0.1,
            "predictor_version": "challenger-logic:v2",
            "created_at": _NOW,
        },
    )
    action_run = OntologyObjectRecord(
        "run-1",
        "ActionRun",
        {
            "id": "run-1",
            "action_type_ref": "ops.scale-out",
            "action_type_version": "1.0.0",
            "target_ref": "workload-1",
            "status": "succeeded",
            "mode": "shadow",
            "idempotency_key": "run-1",
            "started_at": _NOW,
            "receipt_ref": "provider-receipt-1",
        },
    )
    observed_outcome = OntologyObjectRecord(
        "outcome-1",
        "ObservedOutcome",
        {
            "id": "outcome-1",
            "action_run_id": action_run.id,
            "expected_effect_ref": expected_effect.id,
            "verification": verification,
            "recovery_status": "not_required",
            "observed_values": {"latency_ms": 110.0},
            "telemetry_complete": True,
            "scorable": True,
            "observed_at": _NOW,
        },
    )
    return OperationalHypothesisLineage(
        decision_case=decision_case,
        action_option=action_option,
        expected_effect=expected_effect,
        action_run=action_run,
        observed_outcome=observed_outcome,
    )


async def test_projects_replayable_prospective_lineage_without_rewriting_case() -> None:
    store = _Store()
    projector = OperationalHypothesisLineageProjector(store=cast(OntologyInstanceStore, store))
    lineage = _lineage()

    async with asyncio.timeout(0.5):
        await projector.project(lineage)
        await projector.project(lineage)

    first_objects, first_links = store.calls[0]
    replay_objects, replay_links = store.calls[1]
    assert first_objects == lineage.objects
    assert {item.link_type for item in first_links} == {
        "considers",
        "expects",
        "executed_as",
        "resulted_in",
    }
    assert replay_objects == ()
    assert replay_links == first_links


def test_rejects_provider_receipt_as_independent_outcome() -> None:
    with pytest.raises(ValueError, match="independent observation"):
        _lineage(verification="provider_receipt")


def test_rejects_missing_no_action_baseline() -> None:
    lineage = _lineage()
    changed_case = OntologyObjectRecord(
        lineage.decision_case.id,
        lineage.decision_case.object_type,
        {**lineage.decision_case.properties, "no_action_baseline": {}},
    )
    with pytest.raises(ValueError, match="no-action baseline"):
        OperationalHypothesisLineage(
            decision_case=changed_case,
            action_option=lineage.action_option,
            expected_effect=lineage.expected_effect,
            action_run=lineage.action_run,
            observed_outcome=lineage.observed_outcome,
        )


def _shipped_lineage_store() -> InMemoryOntologyInstanceStore:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    object_types = tuple(
        item for item in catalog.object_types if item.name in _LINEAGE_OBJECT_TYPES
    )
    link_types = tuple(item for item in catalog.link_types if item.name in _LINEAGE_LINK_TYPES)
    assert {item.name for item in object_types} == _LINEAGE_OBJECT_TYPES
    assert {item.name for item in link_types} == _LINEAGE_LINK_TYPES
    return InMemoryOntologyInstanceStore(object_types=object_types, link_types=link_types)


async def test_shipped_catalog_accepts_and_traverses_one_lineage() -> None:
    """The four declared segments validate and traverse against the shipped catalog.

    The projector's other tests use a fake store, so nothing proved that a
    lineage satisfies its declared ObjectType schemas and link endpoints.
    """
    store = _shipped_lineage_store()
    lineage = _lineage()

    async with asyncio.timeout(10.0):
        await OperationalHypothesisLineageProjector(store=store).project(lineage)
        snapshot = await store.traverse(
            root_ids=(lineage.decision_case.id,),
            link_types=tuple(sorted(_LINEAGE_LINK_TYPES)),
            max_depth=3,
        )

    assert {item.id for item in snapshot.objects} == {item.id for item in lineage.objects}
    assert {(item.link_type, item.from_id, item.to_id) for item in snapshot.links} == {
        (item.link_type, item.from_id, item.to_id) for item in lineage.links
    }


async def test_shipped_catalog_rejects_a_lineage_missing_a_required_property() -> None:
    """A fabricated record without its declared properties MUST NOT reach the graph."""
    store = _shipped_lineage_store()
    lineage = _lineage()
    incomplete = OntologyObjectRecord(
        lineage.observed_outcome.id,
        lineage.observed_outcome.object_type,
        {
            key: value
            for key, value in lineage.observed_outcome.properties.items()
            if key != "observed_at"
        },
    )

    async with asyncio.timeout(10.0):
        with pytest.raises(OntologyInstanceValidationError):
            await store.replace_subgraph(objects=(incomplete,), links=())
        assert await store.get_object(incomplete.id) is None
