"""Compile admitted question forms into verified plans and execute them on a fixture graph."""

from __future__ import annotations

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
        ({"want": "cause"}, "want_unsupported:cause"),
        ({"operation": "explain_cause"}, "operation_unsupported:explain_cause"),
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
    first = {**form["goals"][0], "operation": "explain_cause", "cue": span(utterance, "Why")}
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
            lambda form: form["mentions"][1].update(
                qualifier={"mention": "m1", "sense": "containment"}
            ),
            "qualified_mention_unsupported",
        ),
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
        (
            lambda form: _as_lookup(
                form,
                measure={"kind": "state"},
                relation={
                    "sense": "containment",
                    "anchor": "m1",
                    "anchor_role": "container",
                    "result_role": "member",
                    "cue": span("How many VMs are in rg-app?", "are in"),
                },
            ),
            "relation_unsupported_for_operation:lookup",
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


def test_a_qualifier_on_a_measure_mention_is_never_dropped() -> None:
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

    goal = _compile(utterance, form).goals[0]

    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("qualified_mention_unsupported",)


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
