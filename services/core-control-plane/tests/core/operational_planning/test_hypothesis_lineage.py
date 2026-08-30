from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fdai.core.operational_planning.hypothesis_lineage import (
    OperationalHypothesisLineage,
    OperationalHypothesisLineageConflictError,
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
            "expected_effect_refs": ["effect-1", "effect-2"],
            "preconditions": ["fresh_context"],
            "option_kind": "intervention",
        },
    )
    expected_effects = (
        OntologyObjectRecord(
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
        ),
        OntologyObjectRecord(
            "effect-2",
            "ExpectedEffect",
            {
                "id": "effect-2",
                "metric": "replica_count",
                "direction": "increase",
                "lower_bound": 2.0,
                "upper_bound": 2.0,
                "window_seconds": 300,
                "uncertainty": 0.0,
                "predictor_version": "challenger-logic:v2",
                "created_at": _NOW,
            },
        ),
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
    observed_outcomes = (
        OntologyObjectRecord(
            "outcome-1",
            "ObservedOutcome",
            {
                "id": "outcome-1",
                "action_run_id": action_run.id,
                "expected_effect_ref": expected_effects[0].id,
                "verification": verification,
                "recovery_status": "not_required",
                "observed_values": {"latency_ms": 110.0},
                "telemetry_complete": True,
                "scorable": True,
                "observed_at": _NOW,
            },
        ),
        OntologyObjectRecord(
            "outcome-2",
            "ObservedOutcome",
            {
                "id": "outcome-2",
                "action_run_id": action_run.id,
                "expected_effect_ref": expected_effects[1].id,
                "verification": verification,
                "recovery_status": "not_required",
                "observed_values": {"replica_count": 2.0},
                "telemetry_complete": True,
                "scorable": True,
                "observed_at": _NOW,
            },
        ),
    )
    return OperationalHypothesisLineage(
        decision_case=decision_case,
        action_option=action_option,
        expected_effects=expected_effects,
        action_run=action_run,
        observed_outcomes=observed_outcomes,
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
            expected_effects=lineage.expected_effects,
            action_run=lineage.action_run,
            observed_outcomes=lineage.observed_outcomes,
        )


def test_rejects_incomplete_expected_effect_observation_set() -> None:
    lineage = _lineage()

    with pytest.raises(ValueError, match="does not observe every expected effect"):
        OperationalHypothesisLineage(
            decision_case=lineage.decision_case,
            action_option=lineage.action_option,
            expected_effects=lineage.expected_effects,
            action_run=lineage.action_run,
            observed_outcomes=lineage.observed_outcomes[:1],
        )


def _legacy_lineage() -> OperationalHypothesisLineage:
    lineage = _lineage()
    legacy_option = replace(
        lineage.action_option,
        properties={
            **lineage.action_option.properties,
            "expected_effect_ref": lineage.expected_effects[0].id,
        },
    )
    legacy_option = replace(
        legacy_option,
        properties={
            key: value
            for key, value in legacy_option.properties.items()
            if key != "expected_effect_refs"
        },
    )

    return OperationalHypothesisLineage(
        decision_case=lineage.decision_case,
        action_option=legacy_option,
        expected_effects=lineage.expected_effects[:1],
        action_run=lineage.action_run,
        observed_outcomes=lineage.observed_outcomes[:1],
    )


async def test_reads_legacy_singular_expected_effect_reference() -> None:
    lineage = _legacy_lineage()
    store = _Store()
    store.objects[lineage.action_option.id] = lineage.action_option

    await OperationalHypothesisLineageProjector(store=cast(OntologyInstanceStore, store)).project(
        lineage
    )

    written_objects, _ = store.calls[0]
    assert lineage.action_option not in written_objects
    assert set(store.objects) == {item.id for item in lineage.objects}


async def test_rejects_new_singular_expected_effect_reference() -> None:
    lineage = _legacy_lineage()

    with pytest.raises(ValueError, match="requires plural expected-effect references"):
        await OperationalHypothesisLineageProjector(
            store=cast(OntologyInstanceStore, _Store())
        ).project(lineage)


def test_rejects_ambiguous_singular_and_plural_effect_references() -> None:
    lineage = _lineage()
    ambiguous_option = replace(
        lineage.action_option,
        properties={
            **lineage.action_option.properties,
            "expected_effect_ref": lineage.expected_effects[0].id,
        },
    )

    with pytest.raises(ValueError, match="expected-effect references are ambiguous"):
        OperationalHypothesisLineage(
            decision_case=lineage.decision_case,
            action_option=ambiguous_option,
            expected_effects=lineage.expected_effects,
            action_run=lineage.action_run,
            observed_outcomes=lineage.observed_outcomes,
        )


def test_normalizes_effects_and_outcomes_to_declared_reference_order() -> None:
    lineage = _lineage()

    reordered = OperationalHypothesisLineage(
        decision_case=lineage.decision_case,
        action_option=lineage.action_option,
        expected_effects=tuple(reversed(lineage.expected_effects)),
        action_run=lineage.action_run,
        observed_outcomes=tuple(reversed(lineage.observed_outcomes)),
    )

    assert reordered.expected_effects == lineage.expected_effects
    assert reordered.observed_outcomes == lineage.observed_outcomes
    assert reordered.links == lineage.links


def test_rejects_duplicate_outcomes_for_one_expected_effect() -> None:
    lineage = _lineage()
    duplicate = replace(
        lineage.observed_outcomes[1],
        properties={
            **lineage.observed_outcomes[1].properties,
            "expected_effect_ref": lineage.expected_effects[0].id,
        },
    )

    with pytest.raises(ValueError, match="outcomes MUST cite unique expected effects"):
        OperationalHypothesisLineage(
            decision_case=lineage.decision_case,
            action_option=lineage.action_option,
            expected_effects=lineage.expected_effects,
            action_run=lineage.action_run,
            observed_outcomes=(lineage.observed_outcomes[0], duplicate),
        )


def test_rejects_cross_type_object_identity_collision() -> None:
    lineage = _lineage()
    colliding_outcome = replace(
        lineage.observed_outcomes[1],
        id=lineage.expected_effects[1].id,
    )

    with pytest.raises(ValueError, match="object ids MUST be unique"):
        OperationalHypothesisLineage(
            decision_case=lineage.decision_case,
            action_option=lineage.action_option,
            expected_effects=lineage.expected_effects,
            action_run=lineage.action_run,
            observed_outcomes=(lineage.observed_outcomes[0], colliding_outcome),
        )


async def test_replay_rejects_changed_observation_time() -> None:
    store = _Store()
    projector = OperationalHypothesisLineageProjector(store=cast(OntologyInstanceStore, store))
    lineage = _lineage()
    await projector.project(lineage)
    changed_outcome = replace(
        lineage.observed_outcomes[0],
        properties={
            **lineage.observed_outcomes[0].properties,
            "observed_at": _NOW + timedelta(seconds=1),
        },
    )
    changed = OperationalHypothesisLineage(
        decision_case=lineage.decision_case,
        action_option=lineage.action_option,
        expected_effects=lineage.expected_effects,
        action_run=lineage.action_run,
        observed_outcomes=(changed_outcome, lineage.observed_outcomes[1]),
    )

    with pytest.raises(OperationalHypothesisLineageConflictError):
        await projector.project(changed)


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
        lineage.observed_outcomes[0].id,
        lineage.observed_outcomes[0].object_type,
        {
            key: value
            for key, value in lineage.observed_outcomes[0].properties.items()
            if key != "observed_at"
        },
    )

    async with asyncio.timeout(10.0):
        with pytest.raises(OntologyInstanceValidationError):
            await store.replace_subgraph(objects=(incomplete,), links=())
        assert await store.get_object(incomplete.id) is None
