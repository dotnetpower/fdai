"""V-SEM, V-PROV, and V-LEVEL reject tampered plans independently of the compiler."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_compiler import compile_question_form
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.semantic_reasoning_verification import verify_goal_semantics
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
    concepts,
    plan_verifier,
    production_manifest,
    span,
    synthetic_anchors,
)

_UTTERANCE = "Which VMs depend on sql-app?"


def _form() -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": span(_UTTERANCE, "sql-app")},
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(_UTTERANCE, "VMs"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "anchor",
                "filters": [{"role": "type", "mention": "m2"}],
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": span(_UTTERANCE, "depend on"),
                },
                "cue": span(_UTTERANCE, "Which VMs"),
                "confidence": 0.9,
            }
        ],
    }


def _compiled() -> tuple[Any, Any, OntologyQueryPlan]:
    admission = admitted(_form(), _UTTERANCE)
    receipt = concepts(("m2", MentionDomain.RESOURCE_TYPE, ("compute.vm",)))
    compilation = compile_question_form(
        admission,
        concepts=receipt,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=_UTTERANCE,
        anchors=synthetic_anchors(admission),
    )
    (batch,) = compilation.goals[0].batches
    return admission, receipt, batch.plan


def _violations(admission: Any, receipt: Any, plan: OntologyQueryPlan) -> tuple[str, ...]:
    return verify_goal_semantics(
        admission.form.goals[0],
        admission=admission,
        concepts=receipt,
        descriptors=production_manifest().descriptors,
        plans=(plan,),
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        anchors=synthetic_anchors(admission),
    )


def _with_nodes(plan: OntologyQueryPlan, nodes: tuple[OntologyQueryNode, ...]) -> OntologyQueryPlan:
    body = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    return OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})


def _rewrite(plan: OntologyQueryPlan, node_id: str, update: Any) -> OntologyQueryPlan:
    nodes = []
    for node in plan.nodes:
        if node.node_id == node_id:
            arguments = json.loads(node.arguments_json)
            update(arguments)
            node = node.model_copy(update={"arguments_json": canonical_json(arguments)})
        nodes.append(node)
    return _with_nodes(plan, tuple(nodes))


def test_compiled_plan_passes_independent_verification() -> None:
    admission, receipt, plan = _compiled()

    assert _violations(admission, receipt, plan) == ()


@pytest.mark.parametrize(
    ("node_id", "update", "violation"),
    (
        (
            "g1-anchor",
            lambda args: args["definition"]["predicates"][0].update(
                equals="00000000-0000-0000-0000-000000000000"
            ),
            "prov_all_zero_identifier:g1-anchor",
        ),
        (
            "g1-anchor",
            lambda args: args["definition"]["predicates"][0].update(equals="object-m9"),
            "prov_operand_without_source:g1-anchor:id",
        ),
        (
            "g1-side-1",
            lambda args: args["endpoint_predicates"][0].update(equals="kubernetes-cluster"),
            "prov_operand_without_source:g1-side-1:type",
        ),
        (
            "g1-side-1",
            lambda args: args.update(direction="outgoing"),
            "sem_relation_sides_differ",
        ),
        (
            "g1-side-1",
            lambda args: args.update(max_depth=3),
            "sem_relation_reach_differs",
        ),
        (
            "g1-side-1",
            lambda args: args.update(
                endpoint_predicates=[
                    item for item in args["endpoint_predicates"] if item["property"] != "type"
                ]
            ),
            "sem_type_filter_missing",
        ),
        (
            "g1-anchor",
            lambda args: args["definition"].update(object_ids=["sql-1"], predicates=[]),
            "prov_explicit_identity:g1-anchor",
        ),
    ),
)
def test_tampered_operands_or_semantics_are_rejected(
    node_id: str, update: Any, violation: str
) -> None:
    admission, receipt, plan = _compiled()

    assert violation in _violations(admission, receipt, _rewrite(plan, node_id, update))


def test_instance_goal_cannot_read_schema_functions() -> None:
    admission, receipt, plan = _compiled()
    schema = OntologyQueryNode(
        node_id="g1-schema",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": "query.ontology_relationships",
                "arguments": {"object_types": ["Resource"], "limit": 100},
                "dependency_arguments": {},
            }
        ),
        output_kind="ontology.relationships",
    )

    violations = _violations(admission, receipt, _with_nodes(plan, (*plan.nodes, schema)))

    assert "level_instance_reads_schema:g1-schema" in violations


def test_a_goal_without_any_plan_is_never_verified() -> None:
    admission, receipt, _plan = _compiled()

    assert verify_goal_semantics(
        admission.form.goals[0],
        admission=admission,
        concepts=receipt,
        descriptors=production_manifest().descriptors,
        plans=(),
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    ) == ("sem_no_plan",)


def test_a_traversal_from_another_identity_is_rejected() -> None:
    admission, receipt, plan = _compiled()
    swapped = _rewrite(
        plan,
        "g1-anchor",
        lambda args: args["definition"]["predicates"][0].update(equals="object-m2"),
    )

    violations = _violations(admission, receipt, swapped)

    assert "sem_relation_anchor_differs" in violations
    assert "prov_operand_without_source:g1-anchor:id" in violations


_SCOPED = "List VMs in rg-app"


def _scoped() -> tuple[Any, Any, OntologyQueryPlan]:
    form = {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": span(_SCOPED, "rg-app")},
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(_SCOPED, "VMs"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m2",
                "subject_scope": "collection",
                "filters": [{"role": "scope", "mention": "m1"}],
                "cue": span(_SCOPED, "List"),
                "confidence": 0.9,
            }
        ],
    }
    admission = admitted(form, _SCOPED)
    receipt = concepts(("m2", MentionDomain.RESOURCE_TYPE, ("compute.vm",)))
    compilation = compile_question_form(
        admission,
        concepts=receipt,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=_SCOPED,
        anchors=synthetic_anchors(admission),
    )
    (batch,) = compilation.goals[0].batches
    return admission, receipt, batch.plan


@pytest.mark.parametrize(
    ("node", "update", "violation"),
    (
        (
            "g1-members",
            lambda args: args.update(direction="incoming"),
            "sem_scope_containment_differs",
        ),
        ("g1-members", lambda args: args.update(max_depth=1), "sem_scope_containment_differs"),
        (
            "g1-scope",
            lambda args: args["definition"]["predicates"][0].update(equals="object-m2"),
            "sem_scope_anchor_differs",
        ),
    ),
)
def test_a_scope_read_that_is_not_the_bound_containment_is_rejected(
    node: str, update: Any, violation: str
) -> None:
    admission, receipt, plan = _scoped()

    assert _violations(admission, receipt, plan) == ()
    assert violation in _violations(admission, receipt, _rewrite(plan, node, update))


_LINK_COUNT = "How many LinkTypes are there?"
_RELATED_LINKS = "How many LinkTypes does the Resource ObjectType have?"


def _link_count(utterance: str, **goal: Any) -> dict[str, Any]:
    mentions = [
        {
            "id": "m1",
            "form": "concept",
            "domain": "declaration_kind",
            "span": span(utterance, "LinkTypes"),
        }
    ]
    if "relation" in goal:
        mentions.append(
            {
                "id": "m2",
                "form": "concept",
                "domain": "object_type",
                "span": span(utterance, "Resource"),
            }
        )
    return {
        "mentions": mentions,
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": span(utterance, "How many"),
                "confidence": 0.9,
                **goal,
            }
        ],
    }


@pytest.mark.parametrize(
    ("utterance", "goal", "violation"),
    (
        (
            _RELATED_LINKS,
            {
                "relation": {
                    "sense": "dependency",
                    "scope": "all_kinds",
                    "anchor": "m2",
                    "anchor_role": "either",
                    "result_role": "either",
                    "cue": span(_RELATED_LINKS, "have"),
                }
            },
            "sem_schema_relation_unread",
        ),
        (
            _LINK_COUNT,
            {"measure": {"kind": "count", "group_by": "endpoint"}},
            "sem_schema_group_by_unread",
        ),
    ),
)
def test_a_manifest_count_never_answers_a_stated_schema_relation_or_grouping(
    utterance: str, goal: dict[str, Any], violation: str
) -> None:
    receipt = concepts(
        ("m1", MentionDomain.DECLARATION_KIND, ("link",)),
        ("m2", MentionDomain.OBJECT_TYPE, ("Resource",)),
    )
    listing = admitted(_link_count(_LINK_COUNT), _LINK_COUNT)
    compilation = compile_question_form(
        listing,
        concepts=receipt,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=_LINK_COUNT,
        anchors=synthetic_anchors(listing),
    )
    (batch,) = compilation.goals[0].batches
    stated = admitted(_link_count(utterance, **goal), utterance)

    violations = verify_goal_semantics(
        stated.form.goals[0],
        admission=stated,
        concepts=receipt,
        descriptors=production_manifest().descriptors,
        plans=(batch.plan,),
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        anchors=synthetic_anchors(stated),
    )

    assert _violations(listing, receipt, batch.plan) == ()
    assert violation in violations


_LINKS_OF = "Which LinkTypes does the Resource ObjectType have?"
_LINKS_BETWEEN = "Which LinkTypes connect the Resource ObjectType to the Database ObjectType?"


def _links_form(utterance: str, **relation: Any) -> dict[str, Any]:
    mentions = [
        {
            "id": "m1",
            "form": "concept",
            "domain": "object_type",
            "span": span(utterance, "Resource"),
        }
    ]
    if "counterpart" in relation:
        mentions.append(
            {
                "id": "m2",
                "form": "concept",
                "domain": "object_type",
                "span": span(utterance, "Database"),
            }
        )
    return {
        "mentions": mentions,
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "operation": "describe_schema",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": {
                    "sense": "dependency",
                    "scope": "all_kinds",
                    "anchor_role": "either",
                    "result_role": "either",
                    "cue": span(utterance, "LinkTypes"),
                    **relation,
                },
                "cue": span(utterance, "Which LinkTypes"),
                "confidence": 0.9,
            }
        ],
    }


@pytest.mark.parametrize(
    ("utterance", "relation"),
    (
        (_LINKS_OF, {"anchor_role": "dependent", "result_role": "dependency"}),
        (_LINKS_BETWEEN, {"counterpart": "m2"}),
    ),
)
def test_a_relationship_read_never_answers_a_directed_or_paired_schema_relation(
    utterance: str, relation: dict[str, Any]
) -> None:
    receipt = concepts(
        ("m1", MentionDomain.OBJECT_TYPE, ("Resource",)),
        ("m2", MentionDomain.OBJECT_TYPE, ("Database",)),
    )
    listing = admitted(_links_form(_LINKS_OF), _LINKS_OF)
    compilation = compile_question_form(
        listing,
        concepts=receipt,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=_LINKS_OF,
        anchors=synthetic_anchors(listing),
    )
    (batch,) = compilation.goals[0].batches
    stated = admitted(_links_form(utterance, **relation), utterance)

    violations = verify_goal_semantics(
        stated.form.goals[0],
        admission=stated,
        concepts=receipt,
        descriptors=production_manifest().descriptors,
        plans=(batch.plan,),
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        anchors=synthetic_anchors(stated),
    )

    assert _violations(listing, receipt, batch.plan) == ()
    assert "sem_schema_relation_unread" in violations


def test_a_metric_read_must_name_the_grounded_concept_and_the_reviewed_window() -> None:
    from tests.conversation.test_semantic_reasoning_compiler import _CPU, _metric_form

    utterance = "What is the CPU of vm-app-01?"
    admission = admitted(_metric_form(utterance), utterance)
    compilation = compile_question_form(
        admission,
        concepts=_CPU,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    )
    plan = compilation.goals[0].batches[0].plan

    def invented(arguments: dict[str, Any]) -> None:
        arguments["arguments"]["metric_concepts"] = ["resource.memory.usage_pct"]

    def widened(arguments: dict[str, Any]) -> None:
        arguments["arguments"]["window_seconds"] = 604_800

    def state_instead(arguments: dict[str, Any]) -> None:
        arguments["function_name"] = "query.resource_current_state"
        arguments["arguments"] = {}

    assert _violations(admission, _CPU, plan) == ()
    assert "prov_function_arguments:g1-read" in _violations(
        admission, _CPU, _rewrite(plan, "g1-read", invented)
    )
    assert "prov_function_arguments:g1-read" in _violations(
        admission, _CPU, _rewrite(plan, "g1-read", widened)
    )
    # A metric is never answered by a current-state read.
    assert "sem_metric_read_differs" in _violations(
        admission, _CPU, _rewrite(plan, "g1-read", state_instead)
    )


def test_a_health_read_must_keep_exactly_the_grounded_health_concepts() -> None:
    from tests.conversation.test_semantic_reasoning_compiler import _UNHEALTHY, _health_form

    utterance = "List the unhealthy VMs"
    admission = admitted(_health_form(utterance), utterance)
    compilation = compile_question_form(
        admission,
        concepts=_UNHEALTHY,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    )
    plan = compilation.goals[0].batches[0].plan

    def widened(arguments: dict[str, Any]) -> None:
        arguments["arguments"]["health_concepts"] = ["resource_health.degraded"]

    def with_states(arguments: dict[str, Any]) -> None:
        arguments["arguments"]["state_concepts"] = ["resource_state.stopped"]

    assert _violations(admission, _UNHEALTHY, plan) == ()
    swapped = _violations(admission, _UNHEALTHY, _rewrite(plan, "g1-health", widened))
    assert "prov_function_arguments:g1-health" in swapped
    assert "sem_health_filter_missing" in swapped
    # State rows the health reader would union in were never stated.
    assert "prov_function_arguments:g1-health" in _violations(
        admission, _UNHEALTHY, _rewrite(plan, "g1-health", with_states)
    )


def test_a_lifecycle_read_must_keep_exactly_the_grounded_values() -> None:
    from tests.conversation.test_semantic_reasoning_compiler import (
        _OPEN_INCIDENT,
        _incident_form,
    )

    utterance = "List the open incidents"
    receipt = concepts(
        ("m1", MentionDomain.OBJECT_TYPE, ("Incident",)),
        ("m2", MentionDomain.STATE, (_OPEN_INCIDENT,)),
    )
    admission = admitted(_incident_form(utterance), utterance)
    compilation = compile_question_form(
        admission,
        concepts=receipt,
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=synthetic_anchors(admission),
    )
    plan = compilation.goals[0].batches[0].plan
    (node_id,) = [node.node_id for node in plan.nodes]

    def widened(arguments: dict[str, Any]) -> None:
        arguments["definition"]["predicates"] = [
            {"property": "status", "operator": "in", "values": ["open", "triaging"]}
        ]

    def dropped(arguments: dict[str, Any]) -> None:
        arguments["definition"]["predicates"] = []

    assert _violations(admission, receipt, plan) == ()
    assert f"prov_operand_without_source:{node_id}:status" in _violations(
        admission, receipt, _rewrite(plan, node_id, widened)
    )
    assert "sem_lifecycle_filter_missing" in _violations(
        admission, receipt, _rewrite(plan, node_id, dropped)
    )
