"""L2 cohort: gold question forms compile and execute to their reviewed outcomes."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_admission import AdmissionDisposition
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
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.semantic_reasoning_handles import (
    HandleScope,
    ResultSetHandle,
    bind_references,
    reference_anchors,
)

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    ROOT,
    admitted,
    execute,
    fixture_anchors,
    fixture_gateway,
    names,
    plan_verifier,
    production_manifest,
)

_COHORT = json.loads(
    (ROOT / "eval/ontology-reasoning/reasoning-cohort.v1.json").read_text(encoding="utf-8")
)
_CASES = tuple(_COHORT["cases"])
_HOLDOUT = json.loads(
    (ROOT / "eval/ontology-reasoning/reasoning-holdout.v1.json").read_text(encoding="utf-8")
)
_HOLDOUT_CASES = tuple(_HOLDOUT["cases"])


def _spanned(value: Any, utterance: str) -> Any:
    """Replace every ``text``/``cue`` needle with its exact first-occurrence span."""

    if isinstance(value, list):
        return [_spanned(item, utterance) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key == "unsupported_constraints":
            result[key] = [
                {"start": utterance.index(text), "end": utterance.index(text) + len(text)}
                for text in item
            ]
        elif key in {"text", "cue", "reach_cue"} and isinstance(item, str):
            start = utterance.index(item)
            result["span" if key == "text" else key] = {"start": start, "end": start + len(item)}
        else:
            result[key] = _spanned(item, utterance)
    return result


def _receipt(case: dict[str, Any], form: dict[str, Any]) -> ConceptSelectionReceipt:
    domains = {item["id"]: MentionDomain(item["domain"]) for item in form["mentions"]}
    bindings = []
    for mention_id, values in case["concepts"].items():
        domain = domains[mention_id]
        if values is None:
            bindings.append(
                ConceptBinding(
                    mention_id,
                    domain,
                    ConceptOutcome.NOT_FOUND,
                    reason=f"concept_not_found:{domain.value}",
                )
            )
        else:
            bindings.append(
                ConceptBinding(mention_id, domain, ConceptOutcome.ACCEPTED, values=tuple(values))
            )
    return ConceptSelectionReceipt(bindings=tuple(bindings))


def cohort_handles(case: dict[str, Any]) -> tuple[tuple[ResultSetHandle, ...], HandleScope]:
    """Return the earlier answer a follow-up case refers to, and the scope it asks from."""

    scope = HandleScope(
        conversation_id="cohort-conversation",
        principal_id="cohort-principal",
        purpose=PURPOSE,
        manifest_digest="cohort-manifest",
        now=NOW,
    )
    handle = case.get("handle")
    if handle is None:
        return (), scope
    return (
        ResultSetHandle(
            handle_id=f"handle-{case['id']}",
            conversation_id=scope.conversation_id,
            principal_id=scope.principal_id,
            purpose=PURPOSE,
            manifest_digest=scope.manifest_digest,
            expires_at=NOW + timedelta(hours=1),
            object_type="Resource",
            row_ids=tuple(handle["rows"]),
            truncated=bool(handle.get("truncated", False)),
        ),
    ), scope


async def _compile(case: dict[str, Any]) -> ReasoningCompilation:
    form = _spanned(case["form"], case["utterance"])
    admission = admitted(form, case["utterance"])
    assert admission.disposition is AdmissionDisposition.ADMITTED, admission.reasons
    handles, scope = cohort_handles(case)
    references = bind_references(admission, handles, scope)
    return compile_question_form(
        admission,
        concepts=_receipt(case, form),
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        utterance=case["utterance"],
        anchors=reference_anchors(await fixture_anchors(admission), references),
        references=references,
    )


def test_cohort_is_bilingual_and_generic() -> None:
    pairs: dict[str, set[str]] = {}
    for case in _CASES:
        pairs.setdefault(case["pair"], set()).add(case["locale"])
    assert _COHORT["schema_version"] == "1.0.0"
    assert all(locales == {"en", "ko"} for locales in pairs.values())
    assert len({case["id"] for case in _CASES}) == len(_CASES)
    assert {case["reasoning"] for case in _CASES} >= {
        "aggregation",
        "causal",
        "closure",
        "containment",
        "evidence",
        "followup",
        "relation",
        "schema",
        "temporal",
    }


def test_the_holdout_is_bilingual_and_shares_no_question_with_the_cohort() -> None:
    pairs: dict[str, set[str]] = {}
    for case in _HOLDOUT_CASES:
        pairs.setdefault(case["pair"], set()).add(case["locale"])
    assert _HOLDOUT["schema_version"] == "1.0.0"
    assert all(locales == {"en", "ko"} for locales in pairs.values())
    assert len({case["id"] for case in _HOLDOUT_CASES}) == len(_HOLDOUT_CASES)
    assert not {case["id"] for case in _HOLDOUT_CASES} & {case["id"] for case in _CASES}
    assert not {case["utterance"] for case in _HOLDOUT_CASES} & {
        case["utterance"] for case in _CASES
    }


@pytest.mark.parametrize("case", _CASES + _HOLDOUT_CASES, ids=lambda case: case["id"])
async def test_gold_form_reaches_its_reviewed_outcome(case: dict[str, Any]) -> None:
    if "admission" in case["expect"]:
        # A constraint no closed atom states clarifies at admission, before any compile.
        admission = admitted(_spanned(case["form"], case["utterance"]), case["utterance"])
        expected_admission = case["expect"]["admission"]
        assert admission.disposition.value == expected_admission["disposition"]
        assert list(admission.reasons) == expected_admission["reasons"]
        return
    compilation = await _compile(case)
    assert compilation.execution_authority is False
    for goal_id, expected in case["expect"].items():
        goal = compilation.goal(goal_id)
        assert goal.status is GoalStatus(expected["status"]), goal.reasons
        if "reasons" in expected:
            assert list(goal.reasons) == expected["reasons"]
        for limitation in expected.get("limitations", ()):
            assert limitation in goal.limitations
        if "function" in expected:
            functions = {
                node.arguments.get("function_name")
                for batch in goal.batches
                for node in batch.plan.nodes
            }
            assert expected["function"] in functions
        if "lookback_seconds" in expected:
            (batch,) = goal.batches
            assert batch.plan.nodes[-1].arguments["arguments"] == {
                "lookback_seconds": expected["lookback_seconds"]
            }
        if {"endpoints", "count", "groups"} & set(expected):
            await _assert_executed(goal, expected)


async def _assert_executed(goal: Any, expected: dict[str, Any]) -> None:
    gateway = await fixture_gateway()
    reached: set[str] = set()
    aggregates: list[dict[str, Any]] = []
    for batch in goal.batches:
        execution = await execute(batch.plan, gateway)
        assert execution.status == "completed"
        for node_id in batch.plan.output_node_ids:
            table = execution.results[node_id].value
            assert table.complete
            if any(
                node.node_id == node_id and node.kind.value == "aggregate"
                for node in batch.plan.nodes
            ):
                aggregates.extend(row.values for row in table.rows)
            else:
                reached |= names(execution, node_id)
    if "endpoints" in expected:
        assert reached == set(expected["endpoints"])
    if "count" in expected:
        assert [row["value"] for row in aggregates] == [expected["count"]]
    if "groups" in expected:
        assert {row["group"]["properties.type"]: row["value"] for row in aggregates} == expected[
            "groups"
        ]
