"""Compile admitted question forms into verified plans and execute them on a fixture graph."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_binding import AnchorBindingReceipt
from fdai.core.conversation.semantic_reasoning_compiler import (
    GoalStatus,
    ReasoningCompilation,
    compile_question_form,
)
from fdai.core.conversation.semantic_reasoning_concepts import (
    ConceptBinding,
    ConceptOutcome,
    ConceptSelectionReceipt,
)
from fdai.core.conversation.semantic_reasoning_form import (
    SENSE_ROLES,
    MentionDomain,
    RelationSense,
)
from fdai.core.conversation.semantic_reasoning_operators import MAX_SIDES_PER_BATCH
from fdai_service_contracts.ontology_query import QueryNodeKind

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    admitted,
    concepts,
    execute,
    fixture_anchors,
    fixture_gateway,
    names,
    plan_verifier,
    production_manifest,
    span,
    synthetic_anchors,
)


def _compile(
    utterance: str,
    form: dict[str, Any],
    receipt: ConceptSelectionReceipt | None = None,
    anchors: AnchorBindingReceipt | None = None,
) -> ReasoningCompilation:
    admission = admitted(form, utterance)
    return compile_question_form(
        admission,
        concepts=receipt or concepts(),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=anchors if anchors is not None else synthetic_anchors(admission),
    )


async def _compile_bound(
    utterance: str,
    form: dict[str, Any],
    receipt: ConceptSelectionReceipt | None = None,
) -> ReasoningCompilation:
    """Compile after binding anchors against the fixture graph."""

    return _compile(utterance, form, receipt, await fixture_anchors(admitted(form, utterance)))


def _anchor(utterance: str, text: str, mention_id: str = "m1") -> dict[str, Any]:
    return {"id": mention_id, "form": "name", "domain": "instance", "span": span(utterance, text)}


def _relation_form(
    utterance: str,
    *,
    anchor: str,
    sense: str,
    position: str,
    cue: str,
    reach: str = "one_hop",
    operation: str = "traverse",
    extra_mentions: tuple[dict[str, Any], ...] = (),
    filters: tuple[dict[str, str], ...] = (),
    scope: str = "one_sense",
) -> dict[str, Any]:
    return {
        "mentions": [_anchor(utterance, anchor), *extra_mentions],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": operation,
                "subject": "m1",
                "subject_scope": "anchor",
                "filters": list(filters),
                "relation": {
                    "sense": sense,
                    "scope": scope,
                    **_roles(sense, position),
                    "reach": reach,
                    "cue": span(utterance, cue),
                },
                "cue": span(utterance, cue),
                "confidence": 0.92,
            }
        ],
    }


def _roles(sense: str, position: str) -> dict[str, str]:
    """Return anchor and result roles for the anchor's stored-side position."""

    if position == "either":
        return {"anchor_role": "either", "result_role": "either"}
    source, target = SENSE_ROLES[RelationSense(sense)]
    anchor, result = (source, target) if position == "source" else (target, source)
    return {"anchor_role": anchor.value, "result_role": result.value}


async def _endpoint_names(compilation: ReasoningCompilation) -> set[str]:
    gateway = await fixture_gateway()
    reached: set[str] = set()
    for batch in compilation.goals[0].batches:
        execution = await execute(batch.plan, gateway)
        assert execution.status == "completed"
        for node_id in batch.plan.output_node_ids:
            reached |= names(execution, node_id)
    return reached


@pytest.mark.parametrize(
    ("utterance", "anchor", "position", "cue", "expected"),
    (
        (
            "What does aks-prod-01 depend on?",
            "aks-prod-01",
            "source",
            "depend on",
            {"kv-app", "sql-app"},
        ),
        (
            "Which resources depend on sql-app?",
            "sql-app",
            "target",
            "depend on",
            {"aks-prod-01", "vm-app-01"},
        ),
        (
            "sql-app에 의존하는 리소스는?",
            "sql-app",
            "target",
            "의존하는",
            {"aks-prod-01", "vm-app-01"},
        ),
    ),
)
async def test_dependency_direction_follows_the_subject_position(
    utterance: str, anchor: str, position: str, cue: str, expected: set[str]
) -> None:
    compilation = await _compile_bound(
        utterance,
        _relation_form(utterance, anchor=anchor, sense="dependency", position=position, cue=cue),
    )
    goal = compilation.goals[0]

    assert goal.status is GoalStatus.COMPILED
    assert await _endpoint_names(compilation) == expected
    assert compilation.execution_authority is False


async def test_transitive_containment_reads_nested_members_and_hides_role_assignments() -> None:
    utterance = "What is inside rg-app?"
    compilation = await _compile_bound(
        utterance,
        _relation_form(
            utterance,
            anchor="rg-app",
            sense="containment",
            position="source",
            reach="transitive",
            cue="inside",
        ),
    )

    assert await _endpoint_names(compilation) == {
        "aks-prod-01",
        "kv-app",
        "snet-app",
        "sql-app",
        "vm-app-01",
        "vnet-app",
    }


async def test_scoped_count_uses_containment_not_a_shared_name_prefix() -> None:
    utterance = "rg-app 리소스 그룹에 있는 VM 개수는?"
    form = {
        "mentions": [
            _anchor(utterance, "rg-app"),
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VM"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m2",
                "subject_scope": "collection",
                "filters": [{"role": "scope", "mention": "m1"}],
                "cue": span(utterance, "개수"),
                "confidence": 0.9,
            }
        ],
    }
    compilation = await _compile_bound(
        utterance, form, concepts(("m2", MentionDomain.RESOURCE_TYPE, ("compute.vm",)))
    )
    (batch,) = compilation.goals[0].batches
    execution = await execute(batch.plan, await fixture_gateway())
    (row,) = execution.results[batch.plan.output_node_ids[0]].value.rows

    assert row.values["value"] == 1
    assert execution.results[batch.plan.output_node_ids[0]].value.complete


async def test_typed_endpoint_filter_reads_only_resource_endpoints() -> None:
    utterance = "Which VMs depend on sql-app?"
    compilation = await _compile_bound(
        utterance,
        _relation_form(
            utterance,
            anchor="sql-app",
            sense="dependency",
            position="target",
            cue="depend on",
            extra_mentions=(
                {
                    "id": "m2",
                    "form": "concept",
                    "domain": "resource_type",
                    "span": span(utterance, "VMs"),
                },
            ),
            filters=({"role": "type", "mention": "m2"},),
        ),
        concepts(("m2", MentionDomain.RESOURCE_TYPE, ("compute.vm",))),
    )

    assert compilation.goals[0].status is GoalStatus.COMPILED
    assert await _endpoint_names(compilation) == {"vm-app-01"}


async def test_relation_count_counts_distinct_endpoints_across_sides() -> None:
    utterance = "How many resources are peered with vnet-app?"
    compilation = await _compile_bound(
        utterance,
        _relation_form(
            utterance,
            anchor="vnet-app",
            sense="connectivity",
            position="either",
            cue="peered with",
            operation="count",
        ),
    )
    (batch,) = compilation.goals[0].batches
    execution = await execute(batch.plan, await fixture_gateway())
    (row,) = execution.results[batch.plan.output_node_ids[0]].value.rows

    assert row.values["value"] == 1


def test_all_kinds_batches_every_side_without_dropping_any() -> None:
    utterance = "Show every relationship of aks-prod-01"
    compilation = _compile(
        utterance,
        _relation_form(
            utterance,
            anchor="aks-prod-01",
            sense="dependency",
            position="either",
            cue="every relationship",
            scope="all_kinds",
        ),
    )
    goal = compilation.goals[0]
    sides = [
        node
        for batch in goal.batches
        for node in batch.plan.nodes
        if node.kind.value == "relationship_traversal"
    ]

    assert goal.status is GoalStatus.COMPILED
    assert all(len(batch.plan.output_node_ids) <= MAX_SIDES_PER_BATCH for batch in goal.batches)
    assert len({node.node_id for node in sides}) == len(sides)
    assert {batch.total for batch in goal.batches} == {len(goal.batches)}
    assert len(sides) > MAX_SIDES_PER_BATCH


@pytest.mark.parametrize(
    ("time", "expected"),
    (
        ({"kind": "unspecified"}, DEFAULT_LOOKBACK_SECONDS),
        (
            {
                "kind": "window",
                "value": {"duration": {"amount": 3, "unit": "day"}},
                "cue": "last 3 days",
            },
            259_200,
        ),
    ),
)
def test_history_binds_typed_windows_and_version_pinned_defaults(
    time: dict[str, Any], expected: int
) -> None:
    utterance = "What changed on vm-app-01 in the last 3 days?"
    if "cue" in time:
        time = {**time, "cue": span(utterance, time["cue"])}
    form = {
        "mentions": [_anchor(utterance, "vm-app-01")],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "history",
                "subject": "m1",
                "subject_scope": "anchor",
                "measure": {"kind": "change"},
                "time": time,
                "cue": span(utterance, "What changed"),
                "confidence": 0.9,
            }
        ],
    }
    goal = _compile(utterance, form).goals[0]
    (batch,) = goal.batches
    read = batch.plan.nodes[-1].arguments

    assert read["function_name"] == "query.resource_change_activity"
    assert read["arguments"] == {"lookback_seconds": expected}
    assert ("default_window_applied" in "".join(goal.limitations)) == ("cue" not in time)


def _history_form(utterance: str, cue: str, amount: int) -> dict[str, Any]:
    return {
        "mentions": [_anchor(utterance, "vm-app-01")],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "history",
                "subject": "m1",
                "subject_scope": "anchor",
                "measure": {"kind": "change"},
                "time": {
                    "kind": "window",
                    "value": {"duration": {"amount": amount, "unit": "day"}},
                    "cue": span(utterance, cue),
                },
                "cue": span(utterance, "What changed"),
                "confidence": 0.9,
            }
        ],
    }


@pytest.mark.parametrize(
    ("utterance", "cue", "amount", "disposition"),
    (
        ("What changed on vm-app-01 in the last 3 days?", "last 3 days", 7, "invalid"),
        ("What changed on vm-app-01 in the last 3 days?", "last 3 days", 3, "admitted"),
        ("What changed on vm-app-01 in the last \uff13 days?", "last \uff13 days", 3, "admitted"),
        (
            "What changed on vm-app-01 in the last 3 days and 2 hours?",
            "last 3 days and 2 hours",
            3,
            "clarify",
        ),
    ),
)
def test_digits_in_a_time_cue_must_equal_the_typed_value(
    utterance: str, cue: str, amount: int, disposition: str
) -> None:
    admission = admitted(_history_form(utterance, cue, amount), utterance)

    assert admission.disposition.value == disposition
    if disposition == "invalid":
        assert admission.reasons == ("time_value_mismatch:g1",)
    if disposition == "clarify":
        assert admission.reasons == ("time_value_compound:g1",)


def test_a_window_read_from_words_is_marked_as_the_model_reading() -> None:
    utterance = "What changed on vm-app-01 in the last three days?"

    goal = _compile(utterance, _history_form(utterance, "last three days", 3)).goals[0]

    assert goal.status is GoalStatus.COMPILED
    assert goal.limitations == ("time_window_model_judged:259200",)


def test_schema_goal_reads_declarations_and_never_instances() -> None:
    utterance = "What does the Resource ObjectType declare?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "object_type",
                "span": span(utterance, "Resource"),
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "operation": "describe_schema",
                "subject": "m1",
                "subject_scope": "anchor",
                "cue": span(utterance, "declare"),
                "confidence": 0.95,
            }
        ],
    }
    goal = _compile(
        utterance, form, concepts(("m1", MentionDomain.OBJECT_TYPE, ("Resource",)))
    ).goals[0]
    (batch,) = goal.batches

    assert [node.kind.value for node in batch.plan.nodes] == ["function"]
    assert batch.plan.nodes[0].arguments["arguments"]["name"] == "Resource"


@pytest.mark.parametrize(
    ("form_update", "reason"),
    (
        (
            {"relation": {"sense": "composition", "anchor_role": "part", "result_role": "whole"}},
            "relation_sense_unmapped:composition",
        ),
        (
            {
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "reach": "transitive",
                }
            },
            "relation_not_transitive",
        ),
        # A cause question reads causal context of one anchor; a stated relation is not read yet.
        ({"operation": "explain_cause", "want": "cause"}, "cause_context_atom_unsupported"),
    ),
)
def test_unexpressible_atoms_return_typed_reasons_instead_of_a_substitute(
    form_update: dict[str, Any], reason: str
) -> None:
    utterance = "Which resources depend on sql-app?"
    form = _relation_form(
        utterance, anchor="sql-app", sense="dependency", position="target", cue="depend on"
    )
    goal = form["goals"][0]
    if "relation" in form_update:
        goal["relation"] = {**goal["relation"], **form_update.pop("relation")}
    goal.update(form_update)
    compiled = _compile(utterance, form).goals[0]

    assert compiled.status is GoalStatus.UNSUPPORTED
    assert compiled.reasons == (reason,)
    assert compiled.batches == ()


def test_a_prior_result_reference_without_a_handle_clarifies() -> None:
    utterance = "Which resources depend on it?"
    form = _relation_form(
        utterance, anchor="it", sense="dependency", position="target", cue="depend on"
    )
    form["mentions"][0]["form"] = "anaphor"
    form["goals"][0]["subject_scope"] = "prior_result"

    compiled = _compile(utterance, form).goals[0]

    assert compiled.status is GoalStatus.CLARIFY
    assert compiled.reasons == ("prior_result_unavailable",)


def test_ungrounded_or_ambiguous_concepts_clarify() -> None:
    utterance = "List the databases"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "databases"),
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": span(utterance, "List"),
                "confidence": 0.9,
            }
        ],
    }
    ambiguous = ConceptSelectionReceipt(
        bindings=(
            ConceptBinding(
                "m1",
                MentionDomain.RESOURCE_TYPE,
                ConceptOutcome.AMBIGUOUS,
                candidate_ids=("group:database", "value:sql-database"),
                reason="concept_ambiguous:resource_type",
            ),
        )
    )

    compiled = _compile(utterance, form, ambiguous).goals[0]
    unbound = _compile(utterance, form).goals[0]

    assert compiled.status is GoalStatus.CLARIFY
    assert compiled.reasons == ("concept_ambiguous:resource_type",)
    assert unbound.status is GoalStatus.UNSUPPORTED
    assert unbound.reasons == ("concept_unbound:m1",)


def test_dependent_goal_is_blocked_when_its_dependency_fails() -> None:
    utterance = "Why did sql-app fail and what depends on it?"
    form = _relation_form(
        utterance, anchor="sql-app", sense="dependency", position="target", cue="depends on"
    )
    first = {
        **form["goals"][0],
        "operation": "explain_cause",
        "want": "cause",
        "cue": span(utterance, "Why"),
    }
    second = {**form["goals"][0], "id": "g2", "depends_on": ["g1"]}
    form["goals"] = [first, second]

    compilation = _compile(utterance, form)

    assert [goal.status for goal in compilation.goals] == [
        GoalStatus.UNSUPPORTED,
        GoalStatus.BLOCKED,
    ]
    assert compilation.goal("g2").reasons == ("dependency_not_compiled:g1",)


async def test_collection_subject_with_a_named_relation_object_anchors_on_the_object() -> None:
    utterance = "Which VMs depend on sql-app?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VMs"),
            },
            _anchor(utterance, "sql-app", "m2"),
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "relation": {
                    "sense": "dependency",
                    "anchor": "m2",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": span(utterance, "depend on"),
                },
                "cue": span(utterance, "Which VMs"),
                "confidence": 0.9,
            }
        ],
    }
    compilation = await _compile_bound(
        utterance, form, concepts(("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)))
    )

    assert compilation.goals[0].status is GoalStatus.COMPILED
    assert await _endpoint_names(compilation) == {"vm-app-01"}


async def test_impact_without_a_stated_relation_reads_the_reviewed_implied_dependents() -> None:
    utterance = "What is the impact if sql-app fails?"
    form = {
        "mentions": [_anchor(utterance, "sql-app")],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "impact",
                "subject": "m1",
                "subject_scope": "anchor",
                "cue": span(utterance, "impact"),
                "confidence": 0.9,
            }
        ],
    }
    compilation = await _compile_bound(utterance, form)

    assert "possible_impact_not_observed" in compilation.goals[0].limitations
    assert await _endpoint_names(compilation) == {"aks-prod-01", "vm-app-01"}


async def test_a_scope_that_is_also_the_subject_reads_the_scoped_collection() -> None:
    utterance = "rg-app에 있는 VM은 몇 개야?"
    form = {
        "mentions": [
            _anchor(utterance, "rg-app"),
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_class",
                "span": span(utterance, "VM"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "anchor",
                "filters": [
                    {"role": "type", "mention": "m2"},
                    {"role": "scope", "mention": "m1"},
                ],
                "cue": span(utterance, "몇 개"),
                "confidence": 0.9,
            }
        ],
    }
    compilation = await _compile_bound(
        utterance, form, concepts(("m2", MentionDomain.RESOURCE_CLASS, ("compute.vm",)))
    )
    (batch,) = compilation.goals[0].batches
    execution = await execute(batch.plan, await fixture_gateway())

    assert [row.values["value"] for row in execution.results["g1-count"].value.rows] == [1]


def test_a_role_that_does_not_belong_to_the_sense_is_inadmissible() -> None:
    utterance = "Which resources depend on sql-app?"
    form = _relation_form(
        utterance, anchor="sql-app", sense="dependency", position="target", cue="depend on"
    )
    form["goals"][0]["relation"]["anchor_role"] = "container"
    contradicted = _relation_form(
        utterance, anchor="sql-app", sense="dependency", position="target", cue="depend on"
    )
    contradicted["goals"][0]["relation"]["result_role"] = "dependency"

    admission = admitted(form, utterance)
    contradiction = admitted(contradicted, utterance)

    assert admission.disposition.value == "invalid"
    assert admission.reasons == ("relation_role_mismatch:g1",)
    assert contradiction.disposition.value == "clarify"
    assert contradiction.reasons == ("relation_roles_inconsistent:g1",)


def _as_lookup(form: dict[str, Any], **updates: Any) -> None:
    """Turn the scoped count into a state lookup of the anchor itself."""

    form["mentions"] = form["mentions"][:1]
    form["goals"][0].update(
        operation="lookup", subject="m1", subject_scope="anchor", filters=[], **updates
    )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    (
        (
            lambda form: form["goals"][0].update(measure={"kind": "state"}),
            "measure_unsupported:state",
        ),
        (
            lambda form: form["goals"][0].update(measure={"kind": "count", "mention": "m1"}),
            "measure_mention_unsupported",
        ),
        (
            lambda form: _as_lookup(form, measure={"kind": "state", "group_by": "type"}),
            "group_by_unsupported_for_operation:lookup",
        ),
    ),
)
def test_stated_atoms_no_builder_reads_are_never_dropped(mutate: Any, reason: str) -> None:
    utterance = "How many VMs are in rg-app?"
    form = {
        "mentions": [
            _anchor(utterance, "rg-app"),
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VMs"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m2",
                "subject_scope": "collection",
                "filters": [{"role": "scope", "mention": "m1"}],
                "cue": span(utterance, "How many"),
                "confidence": 0.9,
            }
        ],
    }
    mutate(form)

    goal = _compile(
        utterance, form, concepts(("m2", MentionDomain.RESOURCE_TYPE, ("compute.vm",)))
    ).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == (reason,)


def test_a_named_counterpart_is_not_dropped_from_a_relation() -> None:
    utterance = "Does aks-prod-01 depend on sql-app?"
    form = _relation_form(
        utterance, anchor="aks-prod-01", sense="dependency", position="source", cue="depend on"
    )
    form["mentions"].append(_anchor(utterance, "sql-app", "m2"))
    form["goals"][0]["relation"]["counterpart"] = "m2"

    goal = _compile(utterance, form).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("counterpart_unsupported",)


def test_a_long_provider_identifier_anchor_compiles_without_raising() -> None:
    identifier = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-app/providers/"
        "Microsoft.ContainerService/managedClusters/aks-prod-01"
    )
    utterance = f"What does {identifier} depend on?"
    form = _relation_form(
        utterance, anchor=identifier, sense="dependency", position="source", cue="depend on"
    )
    form["mentions"][0]["form"] = "identifier"

    goal = _compile(utterance, form).goals[0]

    assert goal.status is GoalStatus.COMPILED


@pytest.mark.parametrize(
    ("relation", "reason"),
    (
        (
            {"sense": "containment", "anchor_role": "container", "result_role": "member"},
            "impact_relation_unsupported",
        ),
        (
            {
                "sense": "dependency",
                "anchor_role": "dependency",
                "result_role": "dependent",
                "reach": "transitive",
            },
            "impact_relation_unsupported",
        ),
    ),
)
def test_impact_never_substitutes_another_stated_relation(
    relation: dict[str, Any], reason: str
) -> None:
    utterance = "What is affected if rg-app fails, including everything inside it?"
    form = _relation_form(
        utterance,
        anchor="rg-app",
        sense="dependency",
        position="target",
        cue="affected",
        operation="impact",
    )
    form["goals"][0]["relation"] = {**relation, "cue": span(utterance, "inside")}

    goal = _compile(utterance, form).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == (reason,)


def test_impact_on_a_named_other_resource_is_not_answered_as_a_list() -> None:
    utterance = "Is vm-app-01 impacted if sql-app fails?"
    form = _relation_form(
        utterance,
        anchor="vm-app-01",
        sense="dependency",
        position="target",
        cue="impacted",
        operation="impact",
    )
    form["mentions"].append(_anchor(utterance, "sql-app", "m2"))
    form["goals"][0]["relation"]["anchor"] = "m2"

    goal = _compile(utterance, form).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("result_instance_unsupported",)


def test_all_kinds_with_transitive_reach_is_refused_not_narrowed() -> None:
    utterance = "Show everything transitively related to aks-prod-01"
    form = _relation_form(
        utterance,
        anchor="aks-prod-01",
        sense="dependency",
        position="either",
        cue="transitively related",
        scope="all_kinds",
        reach="transitive",
    )

    goal = _compile(utterance, form).goals[0]

    assert goal.reasons == ("all_kinds_transitive_unsupported",)


def test_subject_kind_and_type_filter_intersect_instead_of_widening() -> None:
    utterance = "Which storage resources are storage accounts?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_class",
                "span": span(utterance, "storage resources"),
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "storage accounts"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "type", "mention": "m2"}],
                "cue": span(utterance, "Which"),
                "confidence": 0.9,
            }
        ],
    }
    narrowed = _compile(
        utterance,
        form,
        concepts(
            ("m1", MentionDomain.RESOURCE_CLASS, ("disk", "file-share", "object-storage")),
            ("m2", MentionDomain.RESOURCE_TYPE, ("object-storage",)),
        ),
    ).goals[0]
    disjoint = _compile(
        utterance,
        form,
        concepts(
            ("m1", MentionDomain.RESOURCE_CLASS, ("disk", "file-share")),
            ("m2", MentionDomain.RESOURCE_TYPE, ("object-storage",)),
        ),
    ).goals[0]
    (batch,) = narrowed.batches
    predicates = batch.plan.nodes[0].arguments["definition"]["predicates"]

    assert predicates[0] == {"property": "type", "operator": "equals", "equals": "object-storage"}
    assert disjoint.status is GoalStatus.CLARIFY
    assert disjoint.reasons == ("type_restrictions_disjoint",)


def test_a_non_resource_collection_carries_no_resource_policy_predicates() -> None:
    utterance = "How many Workloads are there?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "object_type",
                "span": span(utterance, "Workloads"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": span(utterance, "How many"),
                "confidence": 0.9,
            }
        ],
    }

    goal = _compile(
        utterance, form, concepts(("m1", MentionDomain.OBJECT_TYPE, ("Workload",)))
    ).goals[0]

    assert goal.status is GoalStatus.COMPILED
    assert goal.batches[0].plan.nodes[0].arguments["definition"]["predicates"] == []


def test_named_workloads_on_a_resource_keep_their_name_filter() -> None:
    utterance = "Which workloads named checkout run on vm-app-01?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "object_type",
                "span": span(utterance, "workloads"),
            },
            {
                "id": "m2",
                "form": "value",
                "domain": "instance",
                "span": span(utterance, "checkout"),
            },
            _anchor(utterance, "vm-app-01", "m3"),
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "name_fragment", "mention": "m2"}],
                "relation": {
                    "sense": "dependency",
                    "scope": "all_kinds",
                    "anchor": "m3",
                    "anchor_role": "either",
                    "result_role": "either",
                    "cue": span(utterance, "run on"),
                },
                "cue": span(utterance, "Which"),
                "confidence": 0.9,
            }
        ],
    }

    goal = _compile(
        utterance, form, concepts(("m1", MentionDomain.OBJECT_TYPE, ("Workload",)))
    ).goals[0]
    traversals = [
        node
        for batch in goal.batches
        for node in batch.plan.nodes
        if node.kind.value == "relationship_traversal"
    ]

    assert goal.status is GoalStatus.COMPILED
    assert traversals
    assert all(
        node.arguments["endpoint_predicates"]
        == [{"property": "name", "operator": "contains", "equals": "checkout"}]
        for node in traversals
    )


def test_a_measure_mention_that_restates_the_subject_or_measure_is_read() -> None:
    utterance = "What is the current state of aks-prod-01?"
    form = {
        "mentions": [
            _anchor(utterance, "aks-prod-01"),
            {
                "id": "m2",
                "form": "value",
                "domain": "state",
                "span": span(utterance, "current state"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "lookup",
                "subject": "m1",
                "subject_scope": "anchor",
                "measure": {"kind": "state", "mention": "m2"},
                "cue": span(utterance, "What is"),
                "confidence": 0.9,
            }
        ],
    }
    subject = {
        **form,
        "goals": [{**form["goals"][0], "measure": {"kind": "state", "mention": "m1"}}],
    }
    subject["mentions"] = form["mentions"][:1]

    assert _compile(utterance, form).goals[0].status is GoalStatus.COMPILED
    assert _compile(utterance, subject).goals[0].status is GoalStatus.COMPILED


def test_a_schema_relation_with_one_sense_is_not_widened_to_every_link() -> None:
    utterance = "What can the Resource ObjectType depend on?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "object_type",
                "span": span(utterance, "Resource"),
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "operation": "describe_schema",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependent",
                    "result_role": "dependency",
                    "cue": span(utterance, "depend on"),
                },
                "cue": span(utterance, "What can"),
                "confidence": 0.9,
            }
        ],
    }

    goal = _compile(
        utterance, form, concepts(("m1", MentionDomain.OBJECT_TYPE, ("Resource",)))
    ).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("schema_relation_sense_unsupported",)


def _schema_mention(utterance: str, mention_id: str, domain: str, text: str) -> dict[str, Any]:
    form = "name" if domain == "instance" else "concept"
    return {"id": mention_id, "form": form, "domain": domain, "span": span(utterance, text)}


def _either(utterance: str, cue: str, **fields: Any) -> dict[str, Any]:
    return {
        "sense": "dependency",
        "scope": "all_kinds",
        "anchor_role": "either",
        "result_role": "either",
        "cue": span(utterance, cue),
        **fields,
    }


_KIND_LINKS = "How many LinkTypes does the Resource ObjectType have?"
_KIND_INSTANCE = "Which LinkTypes does vm-app-01 participate in?"
_TRANSITIVE = "What can the Resource ObjectType reach transitively?"
_INSTANCE_ANCHOR = "Which LinkTypes of the Resource ObjectType does vm-app-01 use?"
_PER_ENDPOINT = "How many ObjectTypes are there per endpoint?"
_DIRECTED = "What can the Resource ObjectType depend on through any LinkType?"
_PAIRED = "Which LinkTypes connect the Resource ObjectType to the Database ObjectType?"


@pytest.mark.parametrize(
    ("utterance", "mentions", "goal", "reason"),
    (
        (
            _KIND_LINKS,
            (("m1", "declaration_kind", "LinkTypes"), ("m2", "object_type", "Resource")),
            {
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "relation": _either(_KIND_LINKS, "have", anchor="m2"),
            },
            "schema_relation_unsupported:declaration_kind",
        ),
        (
            _KIND_INSTANCE,
            (("m1", "declaration_kind", "LinkTypes"), ("m2", "instance", "vm-app-01")),
            {
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "relation": _either(_KIND_INSTANCE, "participate in", anchor="m2"),
            },
            "schema_relation_unsupported:declaration_kind",
        ),
        (
            _TRANSITIVE,
            (("m1", "object_type", "Resource"),),
            {
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": _either(_TRANSITIVE, "reach transitively", reach="transitive"),
            },
            "schema_relation_reach_unsupported:transitive",
        ),
        (
            _INSTANCE_ANCHOR,
            (("m1", "object_type", "Resource"), ("m2", "instance", "vm-app-01")),
            {
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": _either(_INSTANCE_ANCHOR, "use", anchor="m2"),
            },
            "schema_relation_anchor_unsupported",
        ),
        (
            _PER_ENDPOINT,
            (("m1", "declaration_kind", "ObjectTypes"),),
            {
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": "count", "group_by": "endpoint"},
            },
            "schema_group_by_unsupported:endpoint",
        ),
        (
            _DIRECTED,
            (("m1", "object_type", "Resource"),),
            {
                "operation": "describe_schema",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": _either(
                    _DIRECTED, "depend on", anchor_role="dependent", result_role="dependency"
                ),
            },
            "schema_relation_roles_unsupported",
        ),
        (
            _PAIRED,
            (("m1", "object_type", "Resource"), ("m2", "object_type", "Database")),
            {
                "operation": "describe_schema",
                "subject": "m1",
                "subject_scope": "anchor",
                "relation": _either(_PAIRED, "connect", counterpart="m2"),
            },
            "counterpart_unsupported",
        ),
    ),
)
def test_a_schema_relation_or_grouping_no_declaration_read_answers_is_not_widened(
    utterance: str,
    mentions: tuple[tuple[str, str, str], ...],
    goal: dict[str, Any],
    reason: str,
) -> None:
    form = {
        "mentions": [_schema_mention(utterance, *mention) for mention in mentions],
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "cue": span(utterance, utterance.split()[0]),
                "confidence": 0.9,
                **goal,
            }
        ],
    }
    domains = {
        "declaration_kind": MentionDomain.DECLARATION_KIND,
        "object_type": MentionDomain.OBJECT_TYPE,
    }
    values = {
        "LinkTypes": ("link",),
        "ObjectTypes": ("object",),
        "Resource": ("Resource",),
        "Database": ("Database",),
    }
    receipt = concepts(
        *(
            (mention_id, domains[domain], values[text])
            for mention_id, domain, text in mentions
            if domain in domains
        )
    )

    compiled = _compile(utterance, form, receipt).goals[0]

    assert compiled.status is GoalStatus.UNSUPPORTED
    assert compiled.reasons == (reason,)


def test_a_declaration_count_grouped_by_type_counts_each_kind() -> None:
    utterance = "How many ObjectTypes are there by type?"
    form = {
        "mentions": [_schema_mention(utterance, "m1", "declaration_kind", "ObjectTypes")],
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": "count", "group_by": "type"},
                "cue": span(utterance, "How many"),
                "confidence": 0.9,
            }
        ],
    }

    goal = _compile(
        utterance, form, concepts(("m1", MentionDomain.DECLARATION_KIND, ("object",)))
    ).goals[0]

    assert goal.status is GoalStatus.COMPILED
    (batch,) = goal.batches
    assert [node.kind.value for node in batch.plan.nodes] == ["function", "aggregate"]


def test_a_qualifier_on_a_state_mention_is_rejected_at_admission() -> None:
    utterance = "What is the state of aks-prod-01 in rg-app?"
    form = {
        "mentions": [
            _anchor(utterance, "aks-prod-01"),
            _anchor(utterance, "rg-app", "m2"),
            {
                "id": "m3",
                "form": "value",
                "domain": "state",
                "span": span(utterance, "state"),
                "qualifier": {"mention": "m2", "sense": "containment"},
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "lookup",
                "subject": "m1",
                "subject_scope": "anchor",
                "measure": {"kind": "state", "mention": "m3"},
                "cue": span(utterance, "What is"),
                "confidence": 0.9,
            }
        ],
    }

    admission = admitted(form, utterance)

    # A qualifier only places one named resource inside another, so a qualified state is
    # rejected at admission with a reason its one repair can act on; it is never dropped.
    assert admission.disposition.value == "invalid"
    assert "qualifier_not_instance:m3" in admission.reasons


def _kind_mention(utterance: str, text: str, mention_id: str) -> dict[str, Any]:
    return {
        "id": mention_id,
        "form": "concept",
        "domain": "declaration_kind",
        "span": span(utterance, text),
    }


def test_an_uncited_declaration_kind_needs_exactly_one_schema_goal() -> None:
    utterance = "List resources and LinkTypes, and count ObjectTypes and FunctionTypes"
    instance_goal = {
        "id": "g1",
        "level": "instance",
        "operation": "select",
        "subject_scope": "collection",
        "cue": span(utterance, "List"),
        "confidence": 0.9,
    }
    instance_only = {
        "mentions": [_kind_mention(utterance, "LinkTypes", "m1")],
        "goals": [instance_goal],
    }
    two_schema_goals = {
        "mentions": [
            _kind_mention(utterance, "LinkTypes", "m1"),
            _kind_mention(utterance, "ObjectTypes", "m2"),
            _kind_mention(utterance, "FunctionTypes", "m3"),
        ],
        "goals": [
            {
                "id": f"g{index}",
                "level": "schema",
                "operation": "count",
                "subject": subject,
                "subject_scope": "collection",
                "cue": span(utterance, "count"),
                "confidence": 0.9,
            }
            for index, subject in ((1, "m2"), (2, "m3"))
        ],
    }

    assert admitted(instance_only, utterance).reasons == ("mention_unused:m1",)
    assert admitted(two_schema_goals, utterance).reasons == ("declaration_kind_goal_ambiguous:m1",)


def test_a_stated_declaration_kind_that_does_not_ground_clarifies() -> None:
    utterance = "What does the Resource FooType declare?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "object_type",
                "span": span(utterance, "Resource"),
            },
            _kind_mention(utterance, "FooType", "m2"),
        ],
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "operation": "describe_schema",
                "subject": "m1",
                "subject_scope": "anchor",
                "cue": span(utterance, "declare"),
                "confidence": 0.9,
            }
        ],
    }
    receipt = ConceptSelectionReceipt(
        bindings=(
            ConceptBinding(
                "m1",
                MentionDomain.OBJECT_TYPE,
                ConceptOutcome.ACCEPTED,
                candidate_ids=("value:Resource",),
                values=("Resource",),
            ),
            ConceptBinding(
                "m2",
                MentionDomain.DECLARATION_KIND,
                ConceptOutcome.NOT_FOUND,
                reason="concept_not_found:declaration_kind",
            ),
        )
    )

    goal = _compile(utterance, form, receipt).goals[0]

    assert goal.status is GoalStatus.CLARIFY
    assert goal.reasons == ("concept_not_found:declaration_kind",)


@pytest.mark.parametrize(
    ("cue", "amount", "unit", "disposition", "reasons"),
    (
        ("last 1,440 minutes", 1440, "minute", "admitted", ()),
        ("last 1.5 hours", 90, "minute", "clarify", ("time_value_fractional:g1",)),
        ("last 1 hour 1 minute", 61, "minute", "clarify", ("time_value_compound:g1",)),
        ("last 1 hour 1 minute", 1, "hour", "clarify", ("time_value_compound:g1",)),
    ),
)
def test_grouped_numbers_verify_and_fractional_amounts_clarify(
    cue: str, amount: int, unit: str, disposition: str, reasons: tuple[str, ...]
) -> None:
    utterance = f"What changed on vm-app-01 in the {cue}?"
    form = _history_form(utterance, cue, amount)
    form["goals"][0]["time"]["value"] = {"duration": {"amount": amount, "unit": unit}}

    admission = admitted(form, utterance)

    assert (admission.disposition.value, admission.reasons) == (disposition, reasons)


def test_every_applied_window_is_restated_in_the_answer() -> None:
    utterance = "What changed on vm-app-01 in the last 3 days?"

    goal = _compile(utterance, _history_form(utterance, "last 3 days", 3)).goals[0]

    assert goal.limitations == ("time_window_applied:259200",)


@pytest.mark.parametrize(
    ("mention_text", "reasons"),
    (("last 3 days", ()), ("3 days", ("mention_unused:m2",))),
)
def test_a_mention_that_quotes_exactly_the_time_cue_restates_the_time(
    mention_text: str, reasons: tuple[str, ...]
) -> None:
    utterance = "What changed on vm-app-01 in the last 3 days?"
    form = _history_form(utterance, "last 3 days", 3)
    form["mentions"].append(
        {"id": "m2", "form": "value", "domain": "instance", "span": span(utterance, mention_text)}
    )

    assert admitted(form, utterance).reasons == reasons


_SCOPED_LINKS = "Workload ObjectType에는 어떤 LinkType이 있나요?"


def _scoped_kind_form(operation: str = "select", **extra: Any) -> dict[str, Any]:
    return {
        "mentions": [
            _schema_mention(_SCOPED_LINKS, "m1", "object_type", "Workload"),
            _schema_mention(_SCOPED_LINKS, "m2", "declaration_kind", "LinkType"),
        ],
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "operation": operation,
                "subject": "m2",
                "subject_scope": "collection",
                "filters": [{"role": "scope", "mention": "m1", "cue": span(_SCOPED_LINKS, "에는")}],
                "cue": span(_SCOPED_LINKS, "어떤"),
                "confidence": 0.9,
                **extra,
            }
        ],
    }


def _scoped_receipt(kind: str = "link") -> ConceptSelectionReceipt:
    return concepts(
        ("m1", MentionDomain.OBJECT_TYPE, ("Workload",)),
        ("m2", MentionDomain.DECLARATION_KIND, (kind,)),
    )


def test_a_kind_scoped_to_an_object_type_reads_that_object_types_link_types() -> None:
    goal = _compile(_SCOPED_LINKS, _scoped_kind_form(), _scoped_receipt()).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    (node,) = batch.plan.nodes
    assert node.arguments == {
        "function_name": "query.ontology_relationships",
        "arguments": {"object_types": ["Workload"], "limit": 100},
        "dependency_arguments": {},
    }


@pytest.mark.parametrize(
    ("form", "kind", "status", "reason"),
    (
        (_scoped_kind_form(), "action", GoalStatus.UNSUPPORTED, "schema_scope_unsupported"),
        (_scoped_kind_form("count"), "link", GoalStatus.CLARIFY, "schema_filter_conflict"),
    ),
)
def test_a_scoped_kind_without_a_reviewed_read_is_never_widened(
    form: dict[str, Any], kind: str, status: GoalStatus, reason: str
) -> None:
    goal = _compile(_SCOPED_LINKS, form, _scoped_receipt(kind)).goals[0]

    assert goal.status is status
    assert goal.reasons == (reason,)


@pytest.mark.parametrize("position", ("source", "target", "either"))
async def test_a_peering_answers_from_either_end_whatever_direction_is_stated(
    position: str,
) -> None:
    utterance = "What is vnet-hub peered with?"
    form = _relation_form(
        utterance, anchor="vnet-hub", sense="connectivity", position=position, cue="peered with"
    )

    compilation = await _compile_bound(utterance, form)

    assert compilation.goals[0].status is GoalStatus.COMPILED, compilation.goals[0].reasons
    assert await _endpoint_names(compilation) == {"vnet-app"}


def _state_form(utterance: str, *, operation: str = "select") -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VMs"),
            },
            {"id": "m2", "form": "concept", "domain": "state", "span": span(utterance, "running")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": operation,
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "state", "mention": "m2"}],
                "cue": span(utterance, "running"),
                "confidence": 0.93,
            }
        ],
    }


def test_a_stated_state_filters_the_collection_through_the_state_inventory() -> None:
    utterance = "List the running VMs"
    compilation = _compile(
        utterance,
        _state_form(utterance),
        concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
            ("m2", MentionDomain.STATE, ("resource_state.running",)),
        ),
    )

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    kinds = [node.kind.value for node in batch.plan.nodes]
    assert kinds == ["object_set", "function"]
    state = batch.plan.nodes[1]
    assert state.arguments["function_name"] == "query.resource_state_inventory"
    assert state.arguments["arguments"] == {"state_concepts": ["resource_state.running"]}
    assert batch.frame.output_shape == "resource_state_list"
    assert batch.frame.measure_concepts == ("resource_state.running",)


def test_a_counted_state_and_an_unbound_state_never_widen_the_read() -> None:
    utterance = "How many running VMs"
    counted = _compile(
        utterance,
        _state_form(utterance, operation="count"),
        concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
            ("m2", MentionDomain.STATE, ("resource_state.running",)),
        ),
    )
    unbound = _compile(
        utterance,
        _state_form(utterance, operation="count"),
        concepts(("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",))),
    )

    (batch,) = counted.goals[0].batches
    assert [node.kind.value for node in batch.plan.nodes] == ["object_set", "function", "aggregate"]
    assert unbound.goals[0].status is not GoalStatus.COMPILED


def test_a_qualifier_that_restates_the_subject_filter_is_read_with_the_filter() -> None:
    utterance = "How many running VMs"
    restating = _state_form(utterance, operation="count")
    restating["mentions"][0]["qualifier"] = {"mention": "m2", "sense": "classification"}
    unfiltered = _state_form(utterance, operation="count")
    unfiltered["mentions"][0]["qualifier"] = {"mention": "m2", "sense": "classification"}
    unfiltered["goals"][0]["filters"] = []
    unfiltered["goals"][0]["measure"] = {"kind": "count", "mention": "m2"}

    counted = _compile(
        utterance,
        restating,
        concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
            ("m2", MentionDomain.STATE, ("resource_state.running",)),
        ),
    )

    # Running VMs states the same state as a qualifier and as the goal's filter; the
    # filter reads it, so the qualifier drops nothing. Without that filter it is misplaced.
    (batch,) = counted.goals[0].batches
    assert [node.kind.value for node in batch.plan.nodes] == ["object_set", "function", "aggregate"]
    assert "qualifier_not_instance:m1" in admitted(unfiltered, utterance).reasons


def test_a_count_grouped_by_container_groups_members_by_their_direct_parent() -> None:
    utterance = "Count resources by resource group"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "resources"),
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {
                    "kind": "count",
                    "group_by": "container",
                    "cue": span(utterance, "by resource group"),
                },
                "cue": span(utterance, "Count"),
                "confidence": 0.9,
            }
        ],
    }
    compilation = _compile(utterance, form, concepts(("m1", MentionDomain.RESOURCE_TYPE, ())))

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    aggregate = batch.plan.nodes[-1]
    assert aggregate.arguments == {"operation": "count", "group_by": ["properties.parent_id"]}


def _cause_form(utterance: str, *, measure: str | None = "state", **goal: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "g1",
        "level": "instance",
        "operation": "explain_cause",
        "want": "cause",
        "subject": "m1",
        "subject_scope": "anchor",
        "cue": span(utterance, "Why"),
        "confidence": 0.9,
    }
    if measure is not None:
        body["measure"] = {"kind": measure}
    body.update(goal)
    return {"mentions": [_anchor(utterance, "vm-app-01")], "goals": [body]}


def test_a_why_question_compiles_to_causal_context_that_names_no_cause() -> None:
    utterance = "Why is vm-app-01 stopped?"

    goal = _compile(utterance, _cause_form(utterance)).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    functions = [
        node.arguments["function_name"]
        for node in batch.plan.nodes
        if node.kind.value == "function"
    ]
    # The effect as observed now and the operations recorded before it, nothing ranked.
    assert functions == ["query.resource_current_state", "query.resource_change_activity"]
    assert len(batch.plan.output_node_ids) == 2
    assert batch.frame.output_shape == "cause_context"
    assert batch.frame.evidence_requirements == ("cause.not_established", "window.default.86400")
    assert goal.limitations == ("cause_not_established", "default_window_applied:86400")


def test_a_stated_window_bounds_the_causal_context_and_is_restated() -> None:
    utterance = "Why did vm-app-01 change in the last 3 days?"
    window = {
        "kind": "window",
        "value": {"duration": {"amount": 3, "unit": "day"}},
        "cue": span(utterance, "last 3 days"),
    }

    goal = _compile(utterance, _cause_form(utterance, measure="change", time=window)).goals[0]

    (batch,) = goal.batches
    activity = batch.plan.nodes[-1].arguments
    assert activity["arguments"] == {"lookback_seconds": 259_200}
    assert "window.applied.259200" in batch.frame.evidence_requirements


def test_a_cause_is_read_only_in_its_canonical_form() -> None:
    utterance = "Why is vm-app-01 stopped?"
    fact = _cause_form(utterance, want="fact")
    history = _cause_form(utterance, operation="history", measure="change")

    # A why question has one reading, so no other goal can drop its cause atom silently.
    assert "cause_form_inconsistent:g1" in admitted(fact, utterance).reasons
    assert "cause_form_inconsistent:g1" in admitted(history, utterance).reasons


def test_a_history_goal_reads_activity_as_activity_and_states_its_window() -> None:
    utterance = "What changed on vm-app-01 in the last 3 days?"

    goal = _compile(utterance, _history_form(utterance, "last 3 days", 3)).goals[0]

    (batch,) = goal.batches
    assert batch.frame.output_shape == "change_activity"
    assert batch.frame.evidence_requirements == ("window.applied.259200",)


def test_a_relation_on_its_own_named_subject_restates_a_history_read() -> None:
    utterance = "What changed on vm-app-01 in the last 3 days?"
    form = _history_form(utterance, "last 3 days", 3)
    form["goals"][0]["relation"] = {
        "sense": "containment",
        "anchor": "m1",
        "anchor_role": "container",
        "result_role": "member",
        "cue": span(utterance, "on"),
    }
    traverse = _relation_form(
        "What depends on sql-app?",
        anchor="sql-app",
        sense="dependency",
        position="target",
        cue="depends on",
    )
    traverse["goals"][0]["subject"] = "m1"

    history = _compile(utterance, form).goals[0]
    traversal = _compile("What depends on sql-app?", traverse).goals[0]

    # The operations in vm-app-01 are its own history; nothing more is related.
    assert history.status is GoalStatus.COMPILED, history.reasons
    # A traversal from a named subject that is also its anchor stays an ordinary read.
    assert traversal.status is GoalStatus.COMPILED, traversal.reasons


def test_one_membership_stated_as_scope_and_containment_is_read_as_the_whole_group() -> None:
    utterance = "rg-app에 있는 VM 목록"
    form = {
        "mentions": [
            _anchor(utterance, "rg-app"),
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "VM"),
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
                "relation": {
                    "sense": "containment",
                    "anchor": "m1",
                    "anchor_role": "container",
                    "result_role": "member",
                    "cue": span(utterance, "에 있는"),
                },
                "cue": span(utterance, "목록"),
                "confidence": 0.9,
            }
        ],
    }

    goal = _compile(
        utterance, form, concepts(("m2", MentionDomain.RESOURCE_TYPE, ("compute.vm",)))
    ).goals[0]

    # The scope states the group's whole membership; the one-hop containment restates it.
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    depths = {
        node.arguments.get("max_depth")
        for batch in goal.batches
        for node in batch.plan.nodes
        if node.kind.value == "relationship_traversal"
    }
    assert depths == {5}


def test_a_stated_region_filters_by_the_reviewed_location_code() -> None:
    utterance = "koreacentral 리전에 있는 스토리지 계정"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "value",
                "domain": "region",
                "span": span(utterance, "koreacentral"),
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "스토리지 계정"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m2",
                "subject_scope": "collection",
                "filters": [
                    {"role": "region", "mention": "m1", "cue": span(utterance, "리전에 있는")}
                ],
                "cue": span(utterance, "스토리지 계정"),
                "confidence": 0.9,
            }
        ],
    }
    bound = concepts(
        ("m1", MentionDomain.REGION, ("koreacentral",)),
        ("m2", MentionDomain.RESOURCE_TYPE, ("object-storage",)),
    )

    goal = _compile(utterance, form, bound).goals[0]
    unbound = _compile(
        utterance, form, concepts(("m2", MentionDomain.RESOURCE_TYPE, ("object-storage",)))
    ).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    predicates = batch_predicates(goal)
    assert {"property": "location", "operator": "equals", "equals": "koreacentral"} in predicates
    # A region that no two choosers ground never widens the read to every region.
    assert unbound.status is not GoalStatus.COMPILED


def batch_predicates(goal: Any) -> list[dict[str, Any]]:
    return [
        predicate
        for batch in goal.batches
        for node in batch.plan.nodes
        if node.kind.value == "object_set"
        for predicate in node.arguments["definition"].get("predicates") or ()
    ]


def test_a_stated_failure_premise_of_an_impact_goal_is_read_as_the_impact() -> None:
    utterance = "What is affected if sql-app fails?"
    form = {
        "mentions": [_anchor(utterance, "sql-app")],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "impact",
                "subject": "m1",
                "subject_scope": "anchor",
                "measure": {"kind": "state", "cue": span(utterance, "fails")},
                "cue": span(utterance, "What is affected"),
                "confidence": 0.9,
            }
        ],
    }

    goal = _compile(utterance, form).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    assert "possible_impact_not_observed" in goal.limitations
    # The answer states that the rows are possible impact, never observed impact.
    assert all(
        "impact.possible_not_observed" in batch.frame.evidence_requirements
        for batch in goal.batches
    )


def _collection_history_form(
    utterance: str, subject: str, cue: str, *, amount: int, unit: str, measure: str = "change"
) -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, subject),
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "history",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": measure},
                "time": {
                    "kind": "window",
                    "value": {"duration": {"amount": amount, "unit": unit}},
                    "cue": span(utterance, cue),
                },
                "cue": span(utterance, "changed"),
                "confidence": 0.9,
            }
        ],
    }


def test_a_collection_history_reads_the_newest_change_of_every_resource_in_the_window() -> None:
    utterance = "Which resources changed in the last 24 hours?"
    form = _collection_history_form(utterance, "resources", "last 24 hours", amount=24, unit="hour")

    goal = _compile(utterance, form, concepts(("m1", MentionDomain.RESOURCE_TYPE, ()))).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    (read,) = batch.plan.nodes
    arguments = read.arguments["arguments"]
    assert read.arguments["function_name"] == "query.recent_resource_changes"
    assert arguments["end_at"] == arguments["known_at"] == NOW.isoformat()
    # The row bound is the reader's declared maximum, never a builder's own copy.
    assert arguments["limit"] == 20
    assert batch.frame.output_shape == "resource_changes"
    assert goal.limitations == ("time_window_applied:86400",)
    assert "window.applied.86400" in batch.frame.evidence_requirements


@pytest.mark.parametrize(
    ("measure", "values", "reason"),
    (
        ("change", ("compute.vm",), "recent_change_kind_unsupported"),
        ("event", (), "collection_history_unsupported:event"),
    ),
)
def test_a_collection_history_the_reader_cannot_restrict_is_unsupported(
    measure: str, values: tuple[str, ...], reason: str
) -> None:
    utterance = "Which resources changed in the last 24 hours?"
    form = _collection_history_form(
        utterance, "resources", "last 24 hours", amount=24, unit="hour", measure=measure
    )

    goal = _compile(utterance, form, concepts(("m1", MentionDomain.RESOURCE_TYPE, values))).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == (reason,)


def _event_form(utterance: str, cue: str, *, amount: int, unit: str) -> dict[str, Any]:
    return {
        "mentions": [_anchor(utterance, "vm-app-01")],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "history",
                "subject": "m1",
                "subject_scope": "anchor",
                "measure": {"kind": "event"},
                "time": {
                    "kind": "window",
                    "value": {"duration": {"amount": amount, "unit": unit}},
                    "cue": span(utterance, cue),
                },
                "cue": span(utterance, "events"),
                "confidence": 0.9,
            }
        ],
    }


def test_an_event_history_reads_every_reviewed_event_family_of_the_anchor() -> None:
    utterance = "What events did vm-app-01 have in the last 3 hours?"

    goal = _compile(utterance, _event_form(utterance, "last 3 hours", amount=3, unit="hour"))
    (compiled,) = goal.goals

    assert compiled.status is GoalStatus.COMPILED, compiled.reasons
    (batch,) = compiled.batches
    read = batch.plan.nodes[-1].arguments
    assert read["function_name"] == "query.resource_event_history"
    assert read["arguments"] == {
        "event_families": ["resource_event.kubernetes", "resource_event.resource_health"],
        "lookback_seconds": 10_800,
    }
    assert batch.frame.output_shape == "resource_event_history"


def test_an_event_window_beyond_the_reader_bound_is_unsupported() -> None:
    utterance = "What events did vm-app-01 have in the last 3 days?"

    goal = _compile(utterance, _event_form(utterance, "last 3 days", amount=3, unit="day"))

    assert goal.goals[0].status is GoalStatus.UNSUPPORTED
    assert goal.goals[0].reasons == ("event_window_unsupported",)


@pytest.mark.parametrize("width", (2, 7, 8, 15, 50))
def test_a_union_tree_reads_every_member_once_within_one_console_goal_fan_in(width: int) -> None:
    from fdai.core.conversation.semantic_reasoning_nodes import union_tree
    from fdai_service_contracts.ontology_query import MAX_INTENT_GOAL_DEPENDENCIES

    members = [f"side-{index}" for index in range(1, width + 1)]

    nodes = union_tree("g1-union", members)

    ids = {node.node_id for node in nodes}
    assert nodes[-1].node_id == "g1-union" and len(ids) == len(nodes)
    assert all(2 <= len(node.depends_on) <= MAX_INTENT_GOAL_DEPENDENCIES for node in nodes)
    read = [item for node in nodes for item in node.depends_on if item not in ids]
    assert sorted(read) == sorted(members)
    # A union that already fits keeps its single node and id.
    assert (len(nodes) == 1) == (width <= MAX_INTENT_GOAL_DEPENDENCIES)


def test_what_changed_with_no_kind_stated_reads_resources_in_general() -> None:
    utterance = "What changed in the last 6 hours?"
    form = {
        "mentions": [],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "history",
                "subject_scope": "collection",
                "measure": {"kind": "change"},
                "time": {
                    "kind": "window",
                    "value": {"duration": {"amount": 6, "unit": "hour"}},
                    "cue": span(utterance, "last 6 hours"),
                },
                "cue": span(utterance, "What changed"),
                "confidence": 0.9,
            }
        ],
    }

    goal = _compile(utterance, form).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (read,) = goal.batches[0].plan.nodes
    assert read.arguments["function_name"] == "query.recent_resource_changes"
    assert goal.limitations == ("time_window_applied:21600",)


def test_a_count_measure_may_restate_the_type_filter_of_a_goal_without_a_subject() -> None:
    utterance = "How many virtual machines are there?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": span(utterance, "virtual machines"),
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject_scope": "collection",
                "filters": [{"role": "type", "mention": "m1"}],
                "measure": {"kind": "count", "mention": "m1"},
                "cue": span(utterance, "How many"),
                "confidence": 0.9,
            }
        ],
    }

    goal = _compile(utterance, form, concepts(("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",))))

    assert goal.goals[0].status is GoalStatus.COMPILED, goal.goals[0].reasons


def test_an_absolute_history_window_must_end_at_the_trusted_compile_clock() -> None:
    from datetime import timedelta

    from fdai.core.conversation.semantic_reasoning_verification import verify_goal_semantics

    utterance = "Which resources changed in the last 24 hours?"
    form = _collection_history_form(utterance, "resources", "last 24 hours", amount=24, unit="hour")
    receipt = concepts(("m1", MentionDomain.RESOURCE_TYPE, ()))
    admission = admitted(form, utterance)
    goal = _compile(utterance, form, receipt).goals[0]
    plans = tuple(batch.plan for batch in goal.batches)

    def violations(evaluation_time: Any) -> tuple[str, ...]:
        return verify_goal_semantics(
            admission.form.goals[0],
            admission=admission,
            concepts=receipt,
            descriptors=production_manifest().descriptors,
            plans=plans,
            default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
            evaluation_time=evaluation_time,
        )

    assert violations(NOW) == ()
    # A window of the right length that ends anywhere else is not the stated recent window.
    assert violations(NOW + timedelta(days=1)) == ("prov_function_arguments:g1-changes",)
    assert violations(None) == ("prov_function_arguments:g1-changes",)


def _metric_form(utterance: str, *, time: dict[str, Any] | None = None) -> dict[str, Any]:
    goal: dict[str, Any] = {
        "id": "g1",
        "level": "instance",
        "operation": "lookup",
        "subject": "m1",
        "subject_scope": "anchor",
        "measure": {"kind": "metric", "mention": "m2"},
        "cue": span(utterance, "What is"),
        "confidence": 0.9,
    }
    if time is not None:
        goal["time"] = time
    return {
        "mentions": [
            _anchor(utterance, "vm-app-01"),
            {"id": "m2", "form": "concept", "domain": "metric", "span": span(utterance, "CPU")},
        ],
        "goals": [goal],
    }


_CPU = concepts(("m2", MentionDomain.METRIC, ("resource.cpu.utilization_pct",)))


def test_a_metric_lookup_reads_the_grounded_concept_over_the_bound_resource() -> None:
    utterance = "What is the CPU of vm-app-01?"

    compilation = _compile(utterance, _metric_form(utterance), _CPU)

    (goal,) = compilation.goals
    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    reads = [
        json.loads(node.arguments_json)
        for node in batch.plan.nodes
        if node.kind is QueryNodeKind.FUNCTION
    ]
    assert reads == [
        {
            "function_name": "query.resource_metric_inventory",
            "arguments": {
                "metric_concepts": ["resource.cpu.utilization_pct"],
                "window_seconds": 900,
            },
            "dependency_arguments": {"g1-anchor": "query_result"},
        }
    ]
    assert batch.frame.output_shape == "target_resource_metric"
    # The reviewed default window is stated as a notice, never silently applied.
    assert goal.limitations == ("default_window_applied:900",)
    assert "window.default.900" in batch.frame.evidence_requirements


def test_a_stated_metric_window_is_read_within_the_reader_bounds() -> None:
    utterance = "What is the CPU of vm-app-01 in the last 2 hours?"
    hours = {
        "kind": "window",
        "value": {"duration": {"amount": 2, "unit": "hour"}},
        "cue": span(utterance, "in the last 2 hours"),
    }
    worded = "What is the CPU of vm-app-01 in the last hour?"
    hour = {
        "kind": "window",
        "value": {"duration": {"amount": 1, "unit": "hour"}},
        "cue": span(worded, "in the last hour"),
    }
    minutes = "What is the CPU of vm-app-01 in the last 2 minutes?"
    short_window = {
        "kind": "window",
        "value": {"duration": {"amount": 2, "unit": "minute"}},
        "cue": span(minutes, "in the last 2 minutes"),
    }

    stated = _compile(utterance, _metric_form(utterance, time=hours), _CPU).goals[0]
    judged = _compile(worded, _metric_form(worded, time=hour), _CPU).goals[0]
    short = _compile(minutes, _metric_form(minutes, time=short_window), _CPU).goals[0]
    unbound = _compile(utterance, _metric_form(utterance, time=hours)).goals[0]

    assert stated.status is GoalStatus.COMPILED
    assert stated.limitations == ("time_window_applied:7200",)
    # A window read from words without digits is the model's reading, stated as such.
    assert judged.limitations == ("time_window_model_judged:3600",)
    # A window below the reader's bound, or a metric no chooser grounded, never reads.
    assert short.status is GoalStatus.UNSUPPORTED
    assert short.reasons == ("metric_window_out_of_bounds",)
    assert unbound.status is not GoalStatus.COMPILED


def _health_form(utterance: str, *, operation: str = "select", state: str = "") -> dict[str, Any]:
    mentions: list[dict[str, Any]] = [
        {"id": "m1", "form": "concept", "domain": "resource_type", "span": span(utterance, "VMs")},
        {"id": "m2", "form": "concept", "domain": "health", "span": span(utterance, "unhealthy")},
    ]
    filters = [{"role": "health", "mention": "m2"}]
    if state:
        mentions.append(
            {"id": "m3", "form": "concept", "domain": "state", "span": span(utterance, state)}
        )
        filters.append({"role": "state", "mention": "m3"})
    return {
        "mentions": mentions,
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": operation,
                "subject": "m1",
                "subject_scope": "collection",
                "filters": filters,
                "cue": span(utterance, "unhealthy"),
                "confidence": 0.93,
            }
        ],
    }


_UNHEALTHY = concepts(
    ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
    ("m2", MentionDomain.HEALTH, ("resource_health.unhealthy",)),
)


def test_a_stated_health_filters_the_collection_through_the_health_inventory() -> None:
    utterance = "List the unhealthy VMs"

    goal = _compile(utterance, _health_form(utterance), _UNHEALTHY).goals[0]

    assert goal.status is GoalStatus.COMPILED, goal.reasons
    (batch,) = goal.batches
    collection, health = batch.plan.nodes
    assert collection.kind is QueryNodeKind.OBJECT_SET
    assert {
        "property": "type",
        "operator": "equals",
        "equals": "compute.vm",
    } in collection.arguments["definition"]["predicates"]
    assert json.loads(health.arguments_json) == {
        "function_name": "query.resource_health_inventory",
        "arguments": {"health_concepts": ["resource_health.unhealthy"], "state_concepts": []},
        "dependency_arguments": {"g1-collection": "query_result"},
    }
    assert batch.frame.output_shape == "resource_health_list"
    assert batch.frame.measure_concepts == ("resource_health.unhealthy",)


def test_a_health_filter_never_counts_never_mixes_with_state_and_needs_its_reader() -> None:
    counted = "How many unhealthy VMs"
    mixed = "List the stopped unhealthy VMs"
    listing = "List the unhealthy VMs"
    admission = admitted(_health_form(listing), listing)

    count = _compile(counted, _health_form(counted, operation="count"), _UNHEALTHY).goals[0]
    both = _compile(
        mixed,
        _health_form(mixed, state="stopped"),
        concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
            ("m2", MentionDomain.HEALTH, ("resource_health.unhealthy",)),
            ("m3", MentionDomain.STATE, ("resource_state.stopped",)),
        ),
    ).goals[0]
    unbound = compile_question_form(
        admission,
        concepts=_UNHEALTHY,
        manifest=production_manifest(unbound=("query.resource_health_inventory",)),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=listing,
        anchors=synthetic_anchors(admission),
    ).goals[0]
    ungrounded = _compile(
        listing,
        _health_form(listing),
        concepts(("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",))),
    ).goals[0]

    # Health rows also report unknown coverage, so a row count is not a count of matches.
    assert (count.status, count.reasons) == (GoalStatus.UNSUPPORTED, ("health_count_unsupported",))
    # The health reader unions state rows, while stated restrictions intersect.
    assert (both.status, both.reasons) == (
        GoalStatus.UNSUPPORTED,
        ("state_and_health_filter_unsupported",),
    )
    assert (unbound.status, unbound.reasons) == (
        GoalStatus.UNSUPPORTED,
        ("function_unavailable:query.resource_health_inventory",),
    )
    assert ungrounded.status is not GoalStatus.COMPILED


_OPEN_INCIDENT = "lifecycle:Incident.status=open"


def _incident_form(
    utterance: str, *, operation: str = "select", subject: str = "incidents"
) -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "object_type",
                "span": span(utterance, subject),
            },
            {"id": "m2", "form": "concept", "domain": "state", "span": span(utterance, "open")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": operation,
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "state", "mention": "m2"}],
                "cue": span(utterance, "open"),
                "confidence": 0.93,
            }
        ],
    }


def test_the_lifecycle_state_of_another_object_type_reads_as_an_exact_predicate() -> None:
    listing = "List the open incidents"
    counting = "How many open incidents"
    receipt = concepts(
        ("m1", MentionDomain.OBJECT_TYPE, ("Incident",)),
        ("m2", MentionDomain.STATE, (_OPEN_INCIDENT,)),
    )

    listed = _compile(listing, _incident_form(listing), receipt).goals[0]
    counted = _compile(counting, _incident_form(counting, operation="count"), receipt).goals[0]

    assert listed.status is GoalStatus.COMPILED, listed.reasons
    (batch,) = listed.batches
    (read,) = batch.plan.nodes
    definition = read.arguments["definition"]
    assert definition["selector"]["name"] == "Incident"
    assert definition["predicates"] == [
        {"property": "status", "operator": "equals", "equals": "open"}
    ]
    # An exact predicate has no coverage rows, so its matches may be counted.
    assert counted.status is GoalStatus.COMPILED, counted.reasons
    assert [node.kind.value for node in counted.batches[0].plan.nodes] == [
        "object_set",
        "aggregate",
    ]


def test_a_lifecycle_state_never_restricts_another_subject() -> None:
    utterance = "List the open incidents"
    resources = "List the open VMs"

    mismatched = _compile(
        utterance,
        _incident_form(utterance),
        concepts(
            ("m1", MentionDomain.OBJECT_TYPE, ("Incident",)),
            ("m2", MentionDomain.STATE, ("resource_state.running",)),
        ),
    ).goals[0]
    on_resources = _compile(
        resources,
        _incident_form(resources, subject="VMs")
        | {
            "mentions": [
                {
                    "id": "m1",
                    "form": "concept",
                    "domain": "resource_type",
                    "span": span(resources, "VMs"),
                },
                {"id": "m2", "form": "concept", "domain": "state", "span": span(resources, "open")},
            ]
        },
        concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
            ("m2", MentionDomain.STATE, (_OPEN_INCIDENT,)),
        ),
    ).goals[0]
    mixed = _compile(
        utterance,
        _incident_form(utterance),
        concepts(
            ("m1", MentionDomain.OBJECT_TYPE, ("Incident",)),
            ("m2", MentionDomain.STATE, (_OPEN_INCIDENT, "resource_state.running")),
        ),
    ).goals[0]

    # A Resource state has no reader on an Incident, and an Incident state never filters VMs.
    assert (mismatched.status, mismatched.reasons) == (
        GoalStatus.UNSUPPORTED,
        ("filter_unsupported:state",),
    )
    assert (on_resources.status, on_resources.reasons) == (
        GoalStatus.UNSUPPORTED,
        ("state_filter_subject_mismatch",),
    )
    assert (mixed.status, mixed.reasons) == (
        GoalStatus.UNSUPPORTED,
        ("state_filter_domain_unsupported",),
    )


def _regions_form(utterance: str, regions: tuple[str, ...]) -> dict[str, Any]:
    mentions: list[dict[str, Any]] = [
        {"id": "m1", "form": "concept", "domain": "resource_type", "span": span(utterance, "VMs")}
    ]
    for index, region in enumerate(regions, start=2):
        mentions.append(
            {
                "id": f"m{index}",
                "form": "value",
                "domain": "region",
                "span": span(utterance, region),
            }
        )
    return {
        "mentions": mentions,
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [
                    {"role": "region", "mention": f"m{index}"}
                    for index in range(2, len(regions) + 2)
                ],
                "cue": span(utterance, "List"),
                "confidence": 0.9,
            }
        ],
    }


def test_several_stated_regions_or_lifecycle_states_read_as_one_union() -> None:
    regions = "List the VMs in koreacentral or eastus"
    states = "List the open or triaging incidents"
    lifecycle_form = _incident_form(states)
    lifecycle_form["mentions"].append(
        {"id": "m3", "form": "concept", "domain": "state", "span": span(states, "triaging")}
    )
    lifecycle_form["goals"][0]["filters"].append({"role": "state", "mention": "m3"})

    located = _compile(
        regions,
        _regions_form(regions, ("koreacentral", "eastus")),
        concepts(
            ("m1", MentionDomain.RESOURCE_TYPE, ("compute.vm",)),
            ("m2", MentionDomain.REGION, ("koreacentral",)),
            ("m3", MentionDomain.REGION, ("eastus",)),
        ),
    ).goals[0]
    staged = _compile(
        states,
        lifecycle_form,
        concepts(
            ("m1", MentionDomain.OBJECT_TYPE, ("Incident",)),
            ("m2", MentionDomain.STATE, (_OPEN_INCIDENT,)),
            ("m3", MentionDomain.STATE, ("lifecycle:Incident.status=triaging",)),
        ),
    ).goals[0]

    # A row holds one location and one status, so a conjunction would match nothing.
    assert located.status is GoalStatus.COMPILED, located.reasons
    location = [item for item in batch_predicates(located) if item["property"] == "location"]
    assert location == [
        {"property": "location", "operator": "in", "values": ["eastus", "koreacentral"]}
    ]
    assert staged.status is GoalStatus.COMPILED, staged.reasons
    assert batch_predicates(staged) == [
        {"property": "status", "operator": "in", "values": ["open", "triaging"]}
    ]
