"""Regression coverage for exact-target active-revision planning."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal, Role, Turn
from fdai.core.ontology_platform import (
    OntologyQueryPlanExecutor,
    OntologyQueryPlanVerifier,
    QueryNodeResult,
    build_query_manifest,
)
from fdai.core.ontology_platform.property_values import (
    PropertyValueDomain,
    PropertyValueGroup,
)
from fdai.core.ontology_platform.resource_current_state_queries import (
    RESOURCE_CURRENT_STATE_FUNCTION_NAME,
    RESOURCE_CURRENT_STATE_MEASURE_CONCEPTS,
    resource_current_state_function_type,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryTerms,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import QueryNodeKind

NOW = datetime(2026, 8, 21, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


def _target_cardinality_language() -> InventoryQueryLanguageRegistry:
    return InventoryQueryLanguageRegistry(
        schema_version="1.1.0",
        version="1.1.0",
        default_scope="subscription",
        default_activity_lookback_seconds=604800,
        current_requires_fresh=True,
        suffixes=("은", "는", "이", "가", "의", "을", "를"),
        signals={
            "target_singular": QueryTerms(terms=("my", "this", "내", "해당")),
            "target_collection": QueryTerms(
                terms=("all", "every", "list", "모두", "모든", "전체", "목록")
            ),
        },
        query_kinds={},
        groupings={},
        projections={},
        scopes={},
        states={},
        operations={},
        time_units={},
    )


class _ManifestProvider:
    def __init__(self, manifest: Any) -> None:
        self._manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str):  # type: ignore[no-untyped-def]
        assert principal.role is Role.READER
        assert purpose == "operations-review"
        return self._manifest


class _Model:
    def __init__(self, *, frame: dict[str, object] | None = None) -> None:
        self.frame_calls = 0
        self.plan_calls = 0
        self.frame = frame or {
            "operation": "select",
            "subject_constraints": ["Resource"],
            "measure_concepts": ["active_revision"],
            "temporal_scope": {},
            "output_shape": "property_filtered_resources",
            "evidence_requirements": ["authoritative_inventory"],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": None,
            "confidence": 0.9,
        }

    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        self.frame_calls += 1
        return self.frame

    def propose_plan(self, **_kwargs: Any) -> None:
        self.plan_calls += 1
        return None


def _planner(model: _Model) -> SemanticPlanningService:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING),
        },
    )
    current_state = resource_current_state_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        function_types=(current_state,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        functions=(current_state,),
        bound_function_names=(current_state.name,),
        property_values=(
            PropertyValueDomain(
                object_type="Resource",
                property_name="type",
                values=("compute.container-app",),
                groups=(
                    PropertyValueGroup(
                        id="compute-container-app",
                        values=("compute.container-app",),
                        terms=("container app", "container apps"),
                    ),
                ),
            ),
        ),
    )
    return SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.FUNCTION),
        ),
        inventory_query_language=_target_cardinality_language(),
        now=lambda: NOW,
    )


def _runtime(model: _Model, query_calls: list[QueryNodeKind]) -> SemanticConversationRuntime:
    planner = _planner(model)

    async def object_set_handler(node, dependencies):  # type: ignore[no-untyped-def]
        query_calls.append(node.kind)
        assert dependencies == {}
        return QueryNodeResult(value={"rows": []})

    return SemanticConversationRuntime(
        planner=planner,
        executor=OntologyQueryPlanExecutor(
            handlers={QueryNodeKind.OBJECT_SET: object_set_handler},
            now=lambda: NOW,
        ),
    )


async def test_active_revision_without_exact_target_returns_verified_candidates() -> None:
    model = _Model()
    query_calls: list[QueryNodeKind] = []

    result = await _runtime(model, query_calls).handle(
        utterance="내 Container App에서 현재 활성화된 리비전은 무엇이야?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert result.planning.clarification is None
    assert result.planning.frame is not None
    assert result.planning.frame.output_shape == "resource_target_candidates"
    assert result.execution_authority is False
    assert model.plan_calls == 0
    assert query_calls == [QueryNodeKind.OBJECT_SET]


async def test_prior_turns_do_not_block_verified_target_candidates() -> None:
    model = _Model()
    query_calls: list[QueryNodeKind] = []

    result = await _runtime(model, query_calls).handle(
        utterance="내 Container App에서 현재 활성화된 리비전은 무엇이야?",
        prior_turns=(
            Turn(
                turn_id="prior-turn",
                direction="inbound",
                content="Earlier unrelated operator message.",
            ),
        ),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.disposition == "answered"
    assert result.planning.frame is not None
    assert result.planning.frame.output_shape == "resource_target_candidates"
    assert result.execution_authority is False
    assert model.plan_calls == 0
    assert query_calls == [QueryNodeKind.OBJECT_SET]


@pytest.mark.parametrize(
    ("utterance", "measure_concepts"),
    (
        ("내 Container App의 현재 활성 리비전을 보여줘.", ["active_revision"]),
        (
            "지난 1주일간 내 Container App의 메모리 사용률을 보여줘.",
            ["resource.memory.available_pct"],
        ),
    ),
)
def test_singular_subtype_cardinality_discovers_candidates_from_broad_frame(
    utterance: str,
    measure_concepts: list[str],
) -> None:
    model = _Model(
        frame={
            **_Model().frame,
            "measure_concepts": measure_concepts,
            "output_shape": "property_filtered_resources",
        }
    )

    outcome = _planner(model).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (QueryNodeKind.OBJECT_SET,)
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_current_state_function_declares_frame_measure_concepts() -> None:
    declaration = resource_current_state_function_type()

    assert declaration.output_schema["x-fdai-measure-concepts"] == list(
        RESOURCE_CURRENT_STATE_MEASURE_CONCEPTS
    )


def test_active_revision_with_exact_target_uses_current_state_function() -> None:
    model = _Model(
        frame={
            **_Model().frame,
            "subject_constraints": ["Resource", "orders-api-prod"],
        }
    )

    outcome = _planner(model).plan(
        utterance="orders-api-prod Container App의 현재 활성 리비전을 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "target_current_state"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[1].arguments["function_name"] == (
        RESOURCE_CURRENT_STATE_FUNCTION_NAME
    )
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    ("utterance", "measure_concepts"),
    (
        ("내 Container Apps 목록을 모두 보여줘.", ["type"]),
        ("Show CPU telemetry for all Container Apps.", ["cpu"]),
    ),
)
def test_broad_subtype_reads_stay_on_the_inventory_path(
    utterance: str,
    measure_concepts: list[str],
) -> None:
    model = _Model(
        frame={
            **_Model().frame,
            "measure_concepts": measure_concepts,
        }
    )

    outcome = _planner(model).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "property_filtered_resources"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (QueryNodeKind.OBJECT_SET,)
    assert outcome.execution_authority is False
    assert model.plan_calls == 0
