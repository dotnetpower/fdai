"""A property lookup of one bound Resource reads one reviewed field and nothing else."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation.semantic_manifest import ConceptVocabularies
from fdai.core.conversation.semantic_reasoning_binding import (
    AnchorBinding,
    AnchorBindingReceipt,
    AnchorOutcome,
)
from fdai.core.conversation.semantic_reasoning_compiler import GoalStatus, compile_question_form
from fdai.core.conversation.semantic_reasoning_concepts import (
    ConceptBinding,
    ConceptOutcome,
    ConceptSelectionReceipt,
    concept_catalogs,
)
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.semantic_reasoning_verification import verify_goal_semantics
from fdai.rule_catalog.schema.property_semantic import (
    EquivalentProviderPath,
    PropertySemanticRegistry,
)
from fdai_core_service.semantic_property_answer import render_property_value_answer
from fdai_core_service.semantic_verified_rows import with_stated_notices
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    execute,
    fixture_anchors,
    fixture_gateway,
    plan_verifier,
    production_catalog,
    production_manifest,
    span,
)

_ZONE = "resilience.database.zone_redundant.enabled"
_UTTERANCE = "Is zone redundancy enabled on sql-app?"


def _form(utterance: str = _UTTERANCE, anchor: str = "sql-app") -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": span(utterance, anchor)},
            {
                "id": "m2",
                "form": "concept",
                "domain": "property",
                "span": span(utterance, "zone redundancy"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "lookup",
                "subject": "m1",
                "subject_scope": "anchor",
                "measure": {"kind": "property", "mention": "m2"},
                "cue": span(utterance, "enabled"),
                "confidence": 0.9,
            }
        ],
    }


def _concepts(
    values: tuple[str, ...] = (_ZONE,), outcome: ConceptOutcome = ConceptOutcome.ACCEPTED
) -> ConceptSelectionReceipt:
    return ConceptSelectionReceipt(
        bindings=(
            ConceptBinding(
                "m2",
                MentionDomain.PROPERTY,
                outcome,
                candidate_ids=tuple(f"property:{item}" for item in values),
                values=values if outcome is ConceptOutcome.ACCEPTED else (),
            ),
        )
    )


def _anchors(resource_type: str | None = "sql-database") -> AnchorBindingReceipt:
    return AnchorBindingReceipt(
        (AnchorBinding("m1", AnchorOutcome.BOUND, object_id="sql-1", resource_type=resource_type),)
    )


def _compile(
    concepts: ConceptSelectionReceipt | None = None,
    anchors: AnchorBindingReceipt | None = None,
) -> Any:
    admission = admitted(_form(), _UTTERANCE)
    return admission, compile_question_form(
        admission,
        concepts=concepts or _concepts(),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=_UTTERANCE,
        anchors=anchors or _anchors(),
    )


def _plan() -> tuple[Any, OntologyQueryPlan]:
    admission, compilation = _compile()
    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    return admission, goal.batches[0].plan


def _violations(admission: Any, plan: OntologyQueryPlan) -> tuple[str, ...]:
    return verify_goal_semantics(
        admission.form.goals[0],
        admission=admission,
        concepts=_concepts(),
        descriptors=production_manifest().descriptors,
        plans=(plan,),
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        anchors=_anchors(),
        evaluation_time=NOW,
        property_reads=production_manifest().property_reads,
    )


def _with_nodes(
    plan: OntologyQueryPlan,
    nodes: tuple[OntologyQueryNode, ...],
    outputs: tuple[str, ...] | None = None,
) -> OntologyQueryPlan:
    body = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    if outputs is not None:
        body["output_node_ids"] = list(outputs)
    return OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})


def _with_fields(plan: OntologyQueryPlan, fields: list[str]) -> OntologyQueryPlan:
    nodes = tuple(
        node.model_copy(update={"arguments_json": canonical_json({"fields": fields})})
        if node.kind is QueryNodeKind.PROJECT
        else node
        for node in plan.nodes
    )
    return _with_nodes(plan, nodes)


def test_the_property_catalog_offers_declared_domains_and_every_reviewed_semantic() -> None:
    manifest = production_manifest()
    catalog = concept_catalogs(manifest.descriptors, property_reads=manifest.property_reads)
    candidates = {item.id: item for item in catalog[MentionDomain.PROPERTY]}

    reviewed = {item.semantic_id for item in production_catalog().property_semantics.semantics}
    assert {f"property:{item}" for item in reviewed} <= set(candidates)
    # Only Resource properties with a declared value domain join the reviewed semantics.
    assert {key for key in candidates if key.startswith("property:Resource.")} == {
        "property:Resource.location",
        "property:Resource.type",
    }
    zone = candidates[f"property:{_ZONE}"]
    assert zone.values == (_ZONE,)
    assert "sql-database.zone_redundant" in zone.labels


def test_a_resource_type_with_two_reviewed_paths_for_one_semantic_is_left_out() -> None:
    registry = production_catalog().property_semantics
    semantics = tuple(
        item.model_copy(
            update={
                "equivalent_provider_paths": (
                    *item.equivalent_provider_paths,
                    EquivalentProviderPath(
                        provider="aws", resource_type="sql-database", path="multi_az"
                    ),
                )
            }
        )
        if item.semantic_id == _ZONE
        else item
        for item in registry.semantics
    )
    doubled = PropertySemanticRegistry.model_construct(**{**dict(registry), "semantics": semantics})

    reads = {
        item.semantic_id: item
        for item in ConceptVocabularies(property_semantics=doubled).property_reads()
    }

    assert _ZONE not in reads
    assert reads["resilience.database.geo_backup.enabled"].paths == (
        ("sql-database", "geo_redundant_backup_enabled"),
    )


def test_the_manifest_digest_binds_the_reviewed_property_reads() -> None:
    manifest = production_manifest()

    assert manifest.property_reads
    assert all(item.max_age_seconds > 0 and item.paths for item in manifest.property_reads)
    assert {item.semantic_id for item in manifest.property_reads} >= {_ZONE}


def test_a_property_lookup_projects_only_the_reviewed_path_of_the_bound_anchor() -> None:
    admission, compilation = _compile()

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    assert goal.limitations == ("property_source_inventory:86400",)
    (batch,) = goal.batches
    anchor, project = batch.plan.nodes
    assert anchor.kind is QueryNodeKind.OBJECT_SET
    assert anchor.arguments["definition"]["predicates"] == [
        {"property": "id", "operator": "equals", "equals": "sql-1"}
    ]
    assert project.kind is QueryNodeKind.PROJECT
    assert project.arguments["fields"] == [
        "id",
        "properties.name",
        "properties.type",
        "properties.properties.zone_redundant",
    ]
    assert batch.frame.output_shape == "target_property_value"
    assert batch.frame.measure_concepts == (_ZONE, "properties.properties.zone_redundant")
    assert batch.frame.evidence_requirements == ("property.inventory.86400",)
    assert _violations(admission, batch.plan) == ()


def test_a_declared_value_domain_property_projects_its_own_field() -> None:
    _admission, compilation = _compile(concepts=_concepts(("Resource.location",)))

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    project = goal.batches[0].plan.nodes[-1]
    assert project.arguments["fields"][-1] == "properties.location"


@pytest.mark.parametrize(
    ("concepts", "anchors", "reason"),
    [
        (_concepts(outcome=ConceptOutcome.NOT_FOUND), _anchors(), "property_unreviewed"),
        (
            _concepts(("runtime.vm.power_state",)),
            _anchors("compute.vm"),
            "property_freshness_unestablished",
        ),
        (_concepts(), _anchors("compute.vm"), "property_type_unsupported"),
        (_concepts(), _anchors(None), "property_type_unbound"),
        (
            _concepts((_ZONE, "resilience.database.audit.enabled")),
            _anchors(),
            "property_count_unsupported",
        ),
    ],
)
def test_a_property_without_a_reviewed_readable_path_holds_with_its_typed_reason(
    concepts: ConceptSelectionReceipt, anchors: AnchorBindingReceipt, reason: str
) -> None:
    _admission, compilation = _compile(concepts=concepts, anchors=anchors)

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.UNSUPPORTED
    assert reason in goal.reasons
    assert not goal.batches


@pytest.mark.parametrize(
    "fields",
    [
        ["id", "properties.name", "properties.type", "properties.properties.admin_password"],
        ["id", "properties.name", "properties.type"],
        [
            "id",
            "properties.name",
            "properties.type",
            "properties.properties.zone_redundant",
            "properties.properties.audit_enabled",
        ],
    ],
)
def test_v_prov_rejects_any_projection_the_bindings_did_not_choose(fields: list[str]) -> None:
    admission, plan = _plan()

    assert "prov_property:g1-read" in _violations(admission, _with_fields(plan, fields))


def test_v_sem_requires_the_projection_on_the_exact_anchor_read() -> None:
    admission, plan = _plan()
    anchor = plan.nodes[0]
    moved = anchor.model_copy(
        update={
            "arguments_json": canonical_json(
                {
                    "definition": {
                        **anchor.arguments["definition"],
                        "predicates": [{"property": "id", "operator": "equals", "equals": "kv-1"}],
                    }
                }
            )
        }
    )

    assert "sem_property_read_missing" in _violations(
        admission, _with_nodes(plan, plan.nodes[:1], ("g1-anchor",))
    )
    assert "sem_property_read_missing" in _violations(
        admission, _with_nodes(plan, (moved, plan.nodes[1]))
    )


def test_the_structural_verifier_reads_inside_only_an_object_property() -> None:
    _admission, plan = _plan()
    manifest = production_manifest()

    assert plan_verifier().verify(plan, manifest=manifest) == plan
    with pytest.raises(ValueError, match="absent from dependency output schema"):
        plan_verifier().verify(
            _with_fields(plan, ["id", "properties.name.first"]), manifest=manifest
        )


async def _answer(bag: dict[str, Any] | None, *, korean: bool = False) -> str:
    admission = admitted(_form(), _UTTERANCE)
    anchors = await fixture_anchors(admission)
    binding = anchors.binding("m1")
    assert binding is not None and binding.resource_type == "sql-database"
    compilation = compile_question_form(
        admission,
        concepts=_concepts(),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=_UTTERANCE,
        anchors=anchors,
    )
    (batch,) = compilation.goals[0].batches
    gateway = await fixture_gateway({} if bag is None else {"sql-1": bag})
    execution = await execute(batch.plan, gateway)
    table = execution.results["g1-read"].value
    output = {"rows": [{"values": dict(row.values)} for row in table.rows]}
    answer = render_property_value_answer(
        [output],
        korean=korean,
        output_shape=batch.frame.output_shape,
        measure_concepts=batch.frame.measure_concepts,
    )
    assert answer is not None
    return with_stated_notices(
        answer, batch.frame.evidence_requirements, locale="ko-KR" if korean else "en-US"
    )


async def test_a_property_lookup_answers_with_the_exact_reviewed_value() -> None:
    answer = await _answer({"zone_redundant": True, "admin_password": "never shown"})

    assert answer.splitlines()[0] == f"## {_ZONE} of sql-app"
    assert f"- {_ZONE}: true" in answer
    assert "- Resource type: sql-database" in answer
    assert "reviewed freshness bound for this property is 1 day" in answer
    assert "never shown" not in answer


async def test_a_missing_property_value_is_stated_as_unknown() -> None:
    answer = await _answer(None, korean=True)

    assert "이 속성에는 기록된 값이 없어 알 수 없습니다." in answer
    assert "검토된 최신성 기준은 1일입니다." in answer


@pytest.mark.parametrize(
    ("outputs", "shape", "concepts"),
    [
        ([{"rows": []}], "target_property_value", (_ZONE, "properties.properties.x")),
        (
            [{"rows": [{"values": {"id": "a"}}, {"values": {"id": "b"}}]}],
            "target_property_value",
            (_ZONE, "properties.properties.x"),
        ),
        (
            [{"rows": [{"values": {"id": "a", "x.y": 1, "x.z": 2}}]}],
            "target_property_value",
            (_ZONE, "x.y"),
        ),
        ([{"rows": [{"values": {"id": "a", "x.y": 1}}]}], "resource_list", (_ZONE, "x.y")),
        ([{"rows": [{"values": {"id": "a", "x.y": 1}}]}], "target_property_value", ()),
    ],
)
def test_the_property_renderer_defers_on_any_other_shape(
    outputs: list[dict[str, Any]], shape: str, concepts: tuple[str, ...]
) -> None:
    assert (
        render_property_value_answer(
            outputs, korean=False, output_shape=shape, measure_concepts=concepts
        )
        is None
    )


def test_a_long_property_value_is_named_not_cut() -> None:
    values = {"id": "a", "properties.name": "n", "properties.properties.rules": ["x" * 500]}

    answer = render_property_value_answer(
        [{"rows": [{"values": values}]}],
        korean=False,
        output_shape="target_property_value",
        measure_concepts=("security.network.rules", "properties.properties.rules"),
    )

    assert answer is not None and "(see technical details)" in answer
    assert "x" * 500 not in answer


def test_a_structured_value_dropped_from_answer_rows_is_named_not_replaced_by_the_type() -> None:
    # Answer rows keep scalar fields only, so a list-valued property arrives without its field.
    values = {"id": "a", "properties.name": "sql-app", "properties.type": "sql-database"}

    answer = render_property_value_answer(
        [{"rows": [{"values": values}]}],
        korean=False,
        output_shape="target_property_value",
        measure_concepts=(
            "observability.diagnostic.settings",
            "properties.properties.diagnostic_settings",
        ),
    )

    assert answer is not None
    assert "observability.diagnostic.settings: a structured value" in answer
    assert "observability.diagnostic.settings: sql-database" not in answer


def test_a_missing_name_clarifies_before_any_provider_path_is_chosen() -> None:
    missing = AnchorBindingReceipt((AnchorBinding("m1", AnchorOutcome.ABSENT),))

    _admission, compilation = _compile(anchors=missing)

    goal = compilation.goals[0]
    assert "anchor_not_found:m1" in goal.reasons
