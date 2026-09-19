"""Deterministic planning for principal-scoped ontology manifest lists."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.conversation.semantic_manifest_planning import (
    build_ontology_schema_frame,
    compile_ontology_manifest_plan,
)
from fdai.core.conversation.semantic_planning_frame_checks import (
    deterministic_pre_frame_selection,
)
from fdai.core.conversation.semantic_planning_models import SemanticOutputShape
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    OntologyQueryPlanVerifier,
    QueryManifest,
    build_query_manifest,
)
from fdai.core.ontology_platform.manifest_queries import (
    ONTOLOGY_MANIFEST_FUNCTION_NAME,
    ontology_manifest_function_type,
)
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import QueryNodeKind
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

_NOW = datetime(2026, 9, 10, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64
_UTTERANCE = (
    "List all queryable ontology object types visible to this operator in the current scope."
)


def _manifest() -> QueryManifest:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    rule = OntologyObjectType(
        schema_version="1.0.0",
        name="Rule",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    function = ontology_manifest_function_type()
    objects = (resource, rule)
    release = build_ontology_release(object_types=objects, function_types=(function,))
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=_DIGEST,
        object_types=objects,
        functions=(function,),
        bound_function_names=(function.name,),
    )


def _judgment(
    requested_facets: tuple[str, ...] = (
        "object_type",
        "queryable",
        "visible",
        "current_scope",
    ),
    *,
    primary_intent: str = "query.ontology_declaration",
) -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": primary_intent,
            "targets": [],
            "requested_facets": requested_facets,
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }
    )


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    (
        (
            "query.ontology_declaration",
            ("object_type", "queryable", "visible", "current_scope"),
        ),
        (
            "query.ontology_declaration",
            ("object_type_visibility", "current_scope", "list"),
        ),
        (
            "query.ontology_declaration",
            ("object_type", "visible", "current_scope", "list"),
        ),
        (
            "query.ontology_declaration",
            ("object_types", "visible", "current_scope"),
        ),
        (
            "query.ontology_relationships",
            ("object_types", "visible_to_operator", "current_scope"),
        ),
        (
            "query.ontology_relationships",
            ("object_types", "visible_in_current_scope"),
        ),
        (
            "query.ontology_relationships",
            ("readable_object_types",),
        ),
        (
            "query.ontology_relationships",
            ("object_types", "available"),
        ),
    ),
)
def test_queryable_object_types_use_the_principal_manifest_without_model_fallback(
    primary_intent: str,
    requested_facets: tuple[str, ...],
) -> None:
    manifest = _manifest()
    selected = deterministic_pre_frame_selection(
        judgment=_judgment(requested_facets, primary_intent=primary_intent),
        judgment_accepted=True,
        utterance=_UTTERANCE,
        context=(),
        descriptors=manifest.descriptors,
        manifest_descriptors=manifest.descriptors,
    )

    assert selected is not None
    proposal, frame, investigation = selected
    assert investigation is None
    assert proposal.output_shape is SemanticOutputShape.ONTOLOGY_MANIFEST
    assert frame.subject_constraints == ("object",)
    assert frame.evidence_requirements == ("principal_manifest_evidence",)

    plan = compile_ontology_manifest_plan(
        frame=frame,
        manifest=manifest,
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        evaluation_time=_NOW,
    )

    assert plan is not None
    assert plan.output_node_ids == ("manifest",)
    assert plan.nodes[0].arguments["function_name"] == ONTOLOGY_MANIFEST_FUNCTION_NAME
    assert plan.nodes[0].arguments["arguments"] == {"kinds": ["object"], "limit": 1000}


@pytest.mark.parametrize(
    "requested_facets",
    (
        ("object_type", "queryable"),
        ("object_types", "visible_to_operator"),
        ("object_types", "current_scope"),
        ("object_type", "visible", "current_scope"),
        ("object_type", "visible", "list"),
        ("object_type", "current_scope", "list"),
    ),
)
def test_manifest_list_requires_current_visible_queryable_facets(
    requested_facets: tuple[str, ...],
) -> None:
    manifest = _manifest()
    judgment = _judgment(requested_facets)

    assert (
        build_ontology_schema_frame(
            judgment,
            utterance=_UTTERANCE,
            context=(),
            descriptors=manifest.descriptors,
        )
        is None
    )


@pytest.mark.parametrize("kind", ("object", "interface", "link", "action", "function"))
@pytest.mark.parametrize("readable", ("available", "queryable", "readable"))
@pytest.mark.parametrize("combined", (False, True))
def test_readable_manifest_facets_preserve_exact_declaration_kind(
    kind: str,
    readable: str,
    combined: bool,
) -> None:
    manifest = _manifest()
    facets = (f"{readable}_{kind}_types",) if combined else (f"{kind}_types", readable)
    selected = build_ontology_schema_frame(
        _judgment(facets, primary_intent="query.ontology_relationships"),
        utterance="이 운영자가 조회할 수 있는 선언 유형을 보여 주세요.",
        context=(),
        descriptors=manifest.descriptors,
    )

    assert selected is not None
    _, frame = selected
    assert frame.subject_constraints == (kind,)
    assert frame.output_shape == SemanticOutputShape.ONTOLOGY_MANIFEST
    assert frame.evidence_requirements == ("principal_manifest_evidence",)


@pytest.mark.parametrize(
    "facets",
    (
        ("unavailable_object_types",),
        ("unreadable_object_types",),
        ("not_readable_object_types",),
        ("object_types",),
        ("object_types", "link_types", "available"),
        ("readable_object_types", "readable_function_types"),
        ("object_types", "available", "unavailable"),
        ("readable_object_types", "historical"),
        ("readable_object_types", "properties"),
    ),
)
def test_readable_manifest_facets_do_not_invent_or_merge_declaration_scope(
    facets: tuple[str, ...],
) -> None:
    assert (
        build_ontology_schema_frame(
            _judgment(facets, primary_intent="query.ontology_relationships"),
            utterance=_UTTERANCE,
            context=(),
            descriptors=_manifest().descriptors,
        )
        is None
    )


@pytest.mark.parametrize(
    "updates",
    (
        {"ambiguous": True},
        {"secondary_intents": ("query.ontology_declaration",)},
        {"action_posture": "draft_only"},
        {"execution_authority": True},
    ),
)
def test_readable_manifest_facets_preserve_judgment_guards(updates: dict[str, object]) -> None:
    judgment = _judgment(("readable_object_types",)).model_copy(update=updates)

    assert (
        build_ontology_schema_frame(
            judgment,
            utterance=_UTTERANCE,
            context=(),
            descriptors=_manifest().descriptors,
        )
        is None
    )
