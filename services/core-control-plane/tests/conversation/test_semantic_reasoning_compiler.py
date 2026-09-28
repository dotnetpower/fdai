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


def test_prior_result_references_wait_for_result_handles() -> None:
    utterance = "Which resources depend on it?"
    form = _relation_form(
        utterance, anchor="it", sense="dependency", position="target", cue="depend on"
    )
    form["mentions"][0]["form"] = "anaphor"
    form["goals"][0]["subject_scope"] = "prior_result"

    compiled = _compile(utterance, form).goals[0]

    assert compiled.status is GoalStatus.UNSUPPORTED
    assert compiled.reasons == ("subject_scope_unavailable:prior_result",)


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
