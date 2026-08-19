"""Deterministic question campaign selection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.conversation.question_perspectives import QuestionCapabilityFamily
from fdai.core.conversation.question_selection import (
    QuestionCaseHistory,
    QuestionSelectionDelta,
    select_question_cases,
)
from fdai.core.conversation.question_universe import (
    QuestionCaseClass,
    QuestionUniverseGrammar,
    generate_question_universe,
)
from fdai.core.ontology_platform import build_query_manifest
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release

DIGEST = "sha256:" + "f" * 64
NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _universe():
    objects = tuple(
        OntologyObjectType(
            schema_version="1.0.0",
            name=name,
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )
        for name in (
            "Resource",
            "BusinessService",
            "Incident",
            "Rule",
            "ServiceObjective",
            "CausalHypothesis",
        )
    )
    release = build_ontology_release(object_types=objects)
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=objects,
    )
    return generate_question_universe(
        manifests=(manifest,),
        grammar=QuestionUniverseGrammar.build(
            locales=("en", "ko"),
            case_classes=(QuestionCaseClass.POSITIVE,),
        ),
    )


def test_selection_is_replay_stable_and_never_exceeds_budget() -> None:
    universe = _universe()

    first, first_receipt = select_question_cases(universe=universe, budget=5, seed=17)
    second, second_receipt = select_question_cases(universe=universe, budget=5, seed=17)

    assert first == second
    assert first_receipt == second_receipt
    assert len(first) == 5
    assert first_receipt.selected_case_ids == tuple(item.case_id for item in first)


def test_selection_prioritizes_delta_unresolved_and_oldest_in_order() -> None:
    universe = _universe()
    topology_cases = tuple(
        item
        for item in universe.cases
        if item.required_capability is QuestionCapabilityFamily.TOPOLOGY
    )
    unresolved = next(item for item in universe.cases if item.declaration_id == "object:Incident")
    oldest = next(item for item in universe.cases if item.declaration_id == "object:Rule")
    recent = next(
        item for item in universe.cases if item.declaration_id == "object:ServiceObjective"
    )
    history_by_id = {
        item.case_id: QuestionCaseHistory(item.case_id, "passed", NOW) for item in universe.cases
    }
    history_by_id[unresolved.case_id] = QuestionCaseHistory(unresolved.case_id, "held", NOW)
    history_by_id[oldest.case_id] = QuestionCaseHistory(
        oldest.case_id,
        "passed",
        NOW - timedelta(days=30),
    )

    selected, _receipt = select_question_cases(
        universe=universe,
        budget=len(universe.cases),
        seed=3,
        history=tuple(history_by_id.values()),
        delta=QuestionSelectionDelta(
            declaration_ids=frozenset({"object:Resource"}),
            capability_families=frozenset({QuestionCapabilityFamily.TOPOLOGY}),
        ),
    )

    positions = {item.case_id: index for index, item in enumerate(selected)}
    changed_positions = [
        positions[item.case_id]
        for item in universe.cases
        if item.declaration_id == "object:Resource"
    ]
    topology_positions = [positions[item.case_id] for item in topology_cases]
    assert max(changed_positions) < min(topology_positions)
    assert max(topology_positions) < positions[unresolved.case_id]
    assert positions[unresolved.case_id] < positions[oldest.case_id]
    assert positions[oldest.case_id] < positions[recent.case_id]
