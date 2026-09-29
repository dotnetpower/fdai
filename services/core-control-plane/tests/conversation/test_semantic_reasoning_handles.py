"""Follow-up references bind only to the rows the operator saw, or clarify."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_admission import AdmissionDisposition
from fdai.core.conversation.semantic_reasoning_binding import (
    AnchorBinding,
    AnchorBindingReceipt,
    AnchorOutcome,
)
from fdai.core.conversation.semantic_reasoning_compiler import (
    GoalStatus,
    ReasoningCompilation,
    compile_question_form,
)
from fdai.core.conversation.semantic_reasoning_handles import (
    MAX_HANDLE_ROWS,
    HandleScope,
    ReferenceOutcome,
    ReferenceReceipt,
    ResultSetHandle,
    bind_references,
    reference_anchors,
)
from fdai.core.conversation.semantic_reasoning_verification import verify_goal_semantics
from fdai_service_contracts.ontology_query import OntologyQueryPlan, canonical_json, content_digest

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
)

_SCOPE = HandleScope(
    conversation_id="conversation-a",
    principal_id="principal-a",
    purpose=PURPOSE,
    manifest_digest="manifest-a",
    now=NOW,
)
_SUBSET = "Among them, which ones depend on sql-app?"
_ORDINAL = "What does the 2nd one depend on?"
_AGAIN = "Show them again"


def _handle(rows: tuple[str, ...] = ("aks-1", "kv-1", "vm-2"), **changes: Any) -> ResultSetHandle:
    values: dict[str, Any] = {
        "handle_id": "handle-a",
        "conversation_id": _SCOPE.conversation_id,
        "principal_id": _SCOPE.principal_id,
        "purpose": PURPOSE,
        "manifest_digest": _SCOPE.manifest_digest,
        "expires_at": NOW + timedelta(minutes=30),
        "object_type": "Resource",
        "row_ids": rows,
    }
    return ResultSetHandle(**{**values, **changes})


def _subset_form() -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": "anaphor", "domain": "instance", "span": span(_SUBSET, "them")},
            {"id": "m2", "form": "name", "domain": "instance", "span": span(_SUBSET, "sql-app")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "prior_result",
                "relation": {
                    "sense": "dependency",
                    "anchor": "m2",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": span(_SUBSET, "depend on"),
                },
                "cue": span(_SUBSET, "which ones"),
                "confidence": 0.9,
            }
        ],
    }


def _ordinal_form(text: str = "the 2nd one", position: int | None = 2) -> dict[str, Any]:
    utterance = _ORDINAL.replace("the 2nd one", text)
    mention: dict[str, Any] = {
        "id": "m1",
        "form": "ordinal",
        "domain": "instance",
        "span": span(utterance, text),
    }
    if position is not None:
        mention["position"] = position
    return {
        "mentions": [mention],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "traverse",
                "subject": "m1",
                "subject_scope": "prior_result",
                "relation": {
                    "sense": "dependency",
                    "anchor_role": "dependent",
                    "result_role": "dependency",
                    "cue": span(utterance, "depend on"),
                },
                "cue": span(utterance, "What"),
                "confidence": 0.9,
            }
        ],
    }


def _again_form(operation: str = "select") -> dict[str, Any]:
    goal: dict[str, Any] = {
        "id": "g1",
        "level": "instance",
        "operation": operation,
        "subject": "m1",
        "subject_scope": "prior_result",
        "cue": span(_AGAIN, "Show"),
        "confidence": 0.9,
    }
    if operation == "lookup":
        goal["measure"] = {"kind": "state"}
    return {
        "mentions": [
            {"id": "m1", "form": "anaphor", "domain": "instance", "span": span(_AGAIN, "them")}
        ],
        "goals": [goal],
    }


async def _compile(
    utterance: str,
    form: dict[str, Any],
    handles: tuple[ResultSetHandle, ...],
    scope: HandleScope | None = _SCOPE,
) -> tuple[ReasoningCompilation, ReferenceReceipt]:
    admission = admitted(form, utterance)
    references = bind_references(admission, handles, scope)
    anchors = reference_anchors(await fixture_anchors(admission), references)
    compilation = compile_question_form(
        admission,
        concepts=concepts(),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=utterance,
        anchors=anchors,
        references=references,
    )
    return compilation, references


async def _endpoints(compilation: ReasoningCompilation) -> set[str]:
    gateway = await fixture_gateway()
    reached: set[str] = set()
    for batch in compilation.goals[0].batches:
        execution = await execute(batch.plan, gateway)
        assert execution.status == "completed"
        for node_id in batch.plan.output_node_ids:
            reached |= names(execution, node_id)
    return reached


@pytest.mark.parametrize(
    "changes",
    (
        {"handle_id": ""},
        {"conversation_id": ""},
        {"principal_id": ""},
        {"expires_at": NOW.replace(tzinfo=None)},
        {"row_ids": ("aks-1", "aks-1")},
        {"row_ids": ("aks-1", "")},
        {"row_ids": tuple(f"row-{index}" for index in range(MAX_HANDLE_ROWS + 1))},
    ),
)
def test_a_malformed_handle_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="result handle"):
        _handle(**changes)


def test_a_scope_without_a_timezone_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        HandleScope("c", "p", PURPOSE, "m", NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    ("handles", "scope", "outcome"),
    (
        ((), _SCOPE, ReferenceOutcome.UNAVAILABLE),
        ((_handle(),), None, ReferenceOutcome.UNAVAILABLE),
        ((_handle(conversation_id="conversation-b"),), _SCOPE, ReferenceOutcome.FOREIGN),
        ((_handle(principal_id="principal-b"),), _SCOPE, ReferenceOutcome.FOREIGN),
        ((_handle(purpose="other-purpose"),), _SCOPE, ReferenceOutcome.FOREIGN),
        ((_handle(manifest_digest="manifest-b"),), _SCOPE, ReferenceOutcome.CHANGED),
        ((_handle(expires_at=NOW),), _SCOPE, ReferenceOutcome.EXPIRED),
        ((_handle(rows=()),), _SCOPE, ReferenceOutcome.EMPTY),
    ),
)
async def test_a_reference_outside_its_handle_clarifies_with_its_reason(
    handles: tuple[ResultSetHandle, ...],
    scope: HandleScope | None,
    outcome: ReferenceOutcome,
) -> None:
    compilation, references = await _compile(_SUBSET, _subset_form(), handles, scope)

    assert references.binding("m1").outcome is outcome  # type: ignore[union-attr]
    goal = compilation.goals[0]
    assert goal.status is GoalStatus.CLARIFY
    assert goal.reasons == (f"prior_result_{outcome.value}",)
    assert goal.batches == ()


async def test_the_most_recent_handle_is_the_one_a_follow_up_names() -> None:
    older = _handle(("vm-1",), handle_id="handle-old")
    compilation, references = await _compile(_SUBSET, _subset_form(), (older, _handle()))

    assert references.binding("m1").handle_id == "handle-a"  # type: ignore[union-attr]
    assert await _endpoints(compilation) == {"aks-prod-01"}


@pytest.mark.parametrize(
    ("text", "position", "rows", "expected"),
    (
        ("the 2nd one", 2, ("vm-1", "aks-1"), {"kv-app", "sql-app"}),
        ("the last one", -1, ("vm-1", "aks-1"), {"kv-app", "sql-app"}),
        ("the first one", 1, ("aks-1", "vm-1"), {"kv-app", "sql-app"}),
    ),
)
async def test_an_reference_anchors_the_one_row_at_its_position(
    text: str, position: int, rows: tuple[str, ...], expected: set[str]
) -> None:
    utterance = _ORDINAL.replace("the 2nd one", text)
    compilation, references = await _compile(
        utterance, _ordinal_form(text, position), (_handle(rows),)
    )

    assert references.binding("m1").row_ids == ("aks-1",)  # type: ignore[union-attr]
    assert compilation.goals[0].status is GoalStatus.COMPILED
    assert await _endpoints(compilation) == expected


@pytest.mark.parametrize(("text", "position"), (("the 3rd one", 3), ("the 3rd last", -3)))
async def test_an_ordinal_past_the_rows_shown_clarifies(text: str, position: int) -> None:
    utterance = _ORDINAL.replace("the 2nd one", text)
    compilation, _ = await _compile(
        utterance, _ordinal_form(text, position), (_handle(("aks-1", "vm-1")),)
    )

    assert compilation.goals[0].reasons == ("prior_result_out_of_range",)


async def test_counting_from_the_end_of_a_shortened_answer_clarifies() -> None:
    utterance = _ORDINAL.replace("the 2nd one", "the last one")
    compilation, references = await _compile(
        utterance, _ordinal_form("the last one", -1), (_handle(("vm-1", "aks-1"), truncated=True),)
    )

    assert references.binding("m1").outcome is ReferenceOutcome.AMBIGUOUS  # type: ignore[union-attr]
    assert compilation.goals[0].reasons == ("prior_result_ambiguous",)


async def test_counting_from_the_start_of_a_shortened_answer_names_a_row_that_was_shown() -> None:
    compilation, references = await _compile(
        _ORDINAL, _ordinal_form(), (_handle(("vm-1", "aks-1"), truncated=True),)
    )

    binding = references.binding("m1")
    assert binding is not None and binding.row_ids == ("aks-1",) and not binding.truncated
    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED
    assert "prior_result_truncated" not in goal.limitations


async def test_a_shortened_answer_limits_an_anaphor_to_the_rows_shown() -> None:
    compilation, _ = await _compile(_SUBSET, _subset_form(), (_handle(truncated=True),))

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.COMPILED
    assert "prior_result_truncated" in goal.limitations


async def test_showing_them_again_reads_exactly_the_rows_shown() -> None:
    compilation, _ = await _compile(_AGAIN, _again_form(), (_handle(("aks-1", "vm-2")),))

    assert compilation.goals[0].status is GoalStatus.COMPILED
    assert await _endpoints(compilation) == {"aks-prod-01", "vm-app-dev-01"}


@pytest.mark.parametrize("operation", ("lookup", "history", "impact"))
async def test_an_anaphor_never_starts_a_read_from_several_rows(operation: str) -> None:
    compilation, _ = await _compile(_AGAIN, _again_form(operation), (_handle(),))

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("prior_result_multiple_anchors_unsupported",)


def _it_form(utterance: str, word: str) -> dict[str, Any]:
    form = _ordinal_form()
    form["mentions"] = [
        {"id": "m1", "form": "anaphor", "domain": "instance", "span": span(utterance, word)}
    ]
    form["goals"][0]["relation"]["cue"] = span(utterance, "depend on")
    form["goals"][0]["cue"] = span(utterance, "What")
    return form


async def test_an_anaphor_over_several_rows_never_anchors_a_traversal() -> None:
    utterance = "What do they depend on?"
    compilation, _ = await _compile(utterance, _it_form(utterance, "they"), (_handle(),))

    assert compilation.goals[0].reasons == ("prior_result_multiple_anchors_unsupported",)


async def test_an_anaphor_over_a_one_row_answer_anchors_the_read_it_starts() -> None:
    utterance = "What does it depend on?"
    form = _it_form(utterance, "it")
    compilation, references = await _compile(utterance, form, (_handle(("aks-1",)),))
    looked_up, _ = await _compile(_AGAIN, _again_form("lookup"), (_handle(("aks-1",)),))

    assert references.binding("m1").row_ids == ("aks-1",)  # type: ignore[union-attr]
    assert compilation.goals[0].status is GoalStatus.COMPILED
    assert await _endpoints(compilation) == {"kv-app", "sql-app"}
    assert looked_up.goals[0].status is GoalStatus.COMPILED


@pytest.mark.parametrize(
    ("text", "position", "reason"),
    (
        ("the 2nd one", None, "ordinal_position_missing:m1"),
        ("the 2nd one", 0, "ordinal_position_missing:m1"),
        ("the 2nd one", 3, "ordinal_position_mismatch:m1"),
        ("the 2nd one", -3, "ordinal_position_mismatch:m1"),
    ),
)
def test_admission_checks_an_ordinal_position_against_its_digits(
    text: str, position: int | None, reason: str
) -> None:
    admission = admitted(_ordinal_form(text, position), _ORDINAL)

    assert admission.disposition is not AdmissionDisposition.ADMITTED
    assert reason in admission.reasons


def test_only_an_ordinal_carries_a_position() -> None:
    form = _subset_form()
    form["mentions"][1]["position"] = 1

    admission = admitted(form, _SUBSET)

    assert "position_unexpected:m2" in admission.reasons


async def test_verification_rejects_rows_the_handle_never_held() -> None:
    compilation, references = await _compile(_SUBSET, _subset_form(), (_handle(),))
    admission = admitted(_subset_form(), _SUBSET)
    (batch,) = compilation.goals[0].batches
    tampered = _rewrite_prior_rows(batch.plan, ["aks-1", "kv-1", "vm-9"])

    violations = _verify(admission, tampered, references)

    assert any(item.startswith("prov_operand_without_source:") for item in violations)
    assert "sem_prior_result_unrestricted" in violations


async def test_verification_rejects_a_plan_that_drops_the_row_restriction() -> None:
    compilation, references = await _compile(_SUBSET, _subset_form(), (_handle(),))
    admission = admitted(_subset_form(), _SUBSET)
    (batch,) = compilation.goals[0].batches
    tampered = _rewrite_prior_rows(batch.plan, None)

    assert _verify(admission, batch.plan, references) == ()
    assert _verify(admission, tampered, references) == ("sem_prior_result_unrestricted",)


def _verify(
    admission: Any,
    plan: OntologyQueryPlan,
    references: ReferenceReceipt,
    anchors: AnchorBindingReceipt | None = None,
) -> tuple:
    return verify_goal_semantics(
        admission.form.goals[0],
        admission=admission,
        concepts=concepts(),
        descriptors=production_manifest().descriptors,
        plans=(plan,),
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        anchors=reference_anchors(
            anchors if anchors is not None else _anchors_of(plan), references
        ),
        references=references,
    )


def _anchors_of(plan: OntologyQueryPlan) -> AnchorBindingReceipt:
    identities = []
    for node in plan.nodes:
        arguments = json.loads(node.arguments_json)
        for predicate in arguments.get("definition", {}).get("predicates", ()):
            if predicate.get("property") == "id" and predicate.get("operator") == "equals":
                identities.append(predicate["equals"])
    return AnchorBindingReceipt(
        tuple(AnchorBinding("m2", AnchorOutcome.BOUND, object_id=item) for item in identities)
    )


def _rewrite_prior_rows(plan: OntologyQueryPlan, rows: list[str] | None) -> OntologyQueryPlan:
    nodes = []
    for node in plan.nodes:
        arguments = json.loads(node.arguments_json)
        predicates = arguments.get("endpoint_predicates")
        if predicates is not None:
            kept = [item for item in predicates if item.get("property") != "id"]
            if rows is not None:
                kept.append({"property": "id", "operator": "in", "values": rows})
            arguments["endpoint_predicates"] = kept
            node = node.model_copy(update={"arguments_json": canonical_json(arguments)})
        nodes.append(node)
    body = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    return OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})


_SHOW_FIRST = "Show the first one"


def _show_first(operation: str = "select", **goal: Any) -> dict[str, Any]:
    return {
        "mentions": [
            {
                "id": "m1",
                "form": "ordinal",
                "domain": "instance",
                "span": span(_SHOW_FIRST, "the first one"),
                "position": 1,
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": operation,
                "subject": "m1",
                "subject_scope": "prior_result",
                "cue": span(_SHOW_FIRST, "Show"),
                "confidence": 0.9,
                **goal,
            }
        ],
    }


async def test_an_ordinal_that_starts_no_read_narrows_a_collection_to_its_one_row() -> None:
    selected, _ = await _compile(_SHOW_FIRST, _show_first(), (_handle(("vm-1", "aks-1")),))
    counted, _ = await _compile(_SHOW_FIRST, _show_first("count"), (_handle(("vm-1", "aks-1")),))

    assert selected.goals[0].status is GoalStatus.COMPILED
    assert await _endpoints(selected) == {"vm-app-01"}
    (batch,) = counted.goals[0].batches
    execution = await execute(batch.plan, await fixture_gateway())
    assert execution.status == "completed"
    counts = execution.results[batch.plan.output_node_ids[0]].value.rows
    assert [row.values["value"] for row in counts] == [1]


async def test_an_ordinal_subject_of_a_relation_anchored_elsewhere_keeps_its_row() -> None:
    utterance = "Does the first one depend on sql-app?"
    form = _subset_form()
    form["mentions"] = [
        {
            "id": "m1",
            "form": "ordinal",
            "domain": "instance",
            "span": span(utterance, "the first one"),
            "position": 1,
        },
        {"id": "m2", "form": "name", "domain": "instance", "span": span(utterance, "sql-app")},
    ]
    form["goals"][0]["relation"]["cue"] = span(utterance, "depend on")
    form["goals"][0]["cue"] = span(utterance, "Does")

    depends, _ = await _compile(utterance, form, (_handle(("aks-1", "vm-1")),))
    other, _ = await _compile(utterance, form, (_handle(("kv-1", "aks-1")),))

    assert await _endpoints(depends) == {"aks-prod-01"}
    assert await _endpoints(other) == set()


async def test_verification_requires_an_ordinal_row_on_a_collection_read() -> None:
    compilation, references = await _compile(
        _SHOW_FIRST, _show_first(), (_handle(("vm-1", "aks-1")),)
    )
    admission = admitted(_show_first(), _SHOW_FIRST)
    (batch,) = compilation.goals[0].batches
    unrestricted = _drop_definition_ids(batch.plan)

    assert _verify(admission, batch.plan, references) == ()
    assert "sem_prior_result_unrestricted" in _verify(admission, unrestricted, references)


async def test_a_reference_too_large_for_one_plan_node_is_unsupported() -> None:
    rows = tuple(
        f"/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-app/providers/"
        f"Microsoft.Compute/virtualMachines/vm-app-{index:04d}"
        for index in range(600)
    )
    compilation, _ = await _compile(_AGAIN, _again_form(), (_handle(rows),))

    goal = compilation.goals[0]
    assert goal.status is GoalStatus.UNSUPPORTED
    assert goal.reasons == ("prior_result_too_large",)


async def test_a_stale_handle_never_asks_to_clarify_what_stays_unsupported() -> None:
    expired = (_handle(expires_at=NOW),)
    verification = _show_first(want="verification")
    explained, _ = await _compile(_SHOW_FIRST, verification, expired)
    # A fresh one-row answer would anchor this lookup, so a stale handle clarifies it.
    lookup, _ = await _compile(_AGAIN, _again_form("lookup"), expired)

    assert explained.goals[0].reasons == ("want_unsupported:verification",)
    assert lookup.goals[0].reasons == ("prior_result_expired",)


def _drop_definition_ids(plan: OntologyQueryPlan) -> OntologyQueryPlan:
    nodes = []
    for node in plan.nodes:
        arguments = json.loads(node.arguments_json)
        definition = arguments.get("definition")
        if isinstance(definition, dict):
            definition["predicates"] = [
                item for item in definition.get("predicates", ()) if item.get("property") != "id"
            ]
            node = node.model_copy(update={"arguments_json": canonical_json(arguments)})
        nodes.append(node)
    body = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    return OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})


@pytest.mark.parametrize(("word", "form_name"), (("the first one", "ordinal"), ("it", "anaphor")))
async def test_a_reference_named_as_its_own_relation_anchor_starts_the_read(
    word: str, form_name: str
) -> None:
    utterance = f"What does {word} depend on?"
    form = _it_form(utterance, word)
    form["mentions"][0]["form"] = form_name
    if form_name == "ordinal":
        form["mentions"][0]["position"] = 1
    form["goals"][0]["relation"]["anchor"] = "m1"
    compilation, references = await _compile(utterance, form, (_handle(("aks-1",)),))
    admission = admitted(form, utterance)
    (batch,) = compilation.goals[0].batches
    narrowed_to_itself = _rewrite_prior_rows(batch.plan, ["aks-1"])

    # The only anchor is the reference itself, so the handle supplies its binding.
    anchors = AnchorBindingReceipt()

    assert await _endpoints(compilation) == {"kv-app", "sql-app"}
    assert _verify(admission, batch.plan, references, anchors) == ()
    assert "prov_operand_without_source:g1-side-1:id" in _verify(
        admission, narrowed_to_itself, references, anchors
    )
