"""A blind constraint extraction releases a compilation only when the form states it all."""

from __future__ import annotations

import json
from typing import Any

import httpx
from fdai.core.conversation.semantic_reasoning_form import SemanticQuestionForm
from fdai.core.conversation.semantic_reasoning_proposal import resolve_question_form
from fdai.core.conversation.semantic_reasoning_review import (
    FormReview,
    extraction_schema,
    review_forms,
)
from fdai.core.conversation.semantic_reasoning_shadow import run_reasoning_shadow
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_question_form import (
    AzureOpenAIQuestionFormConfig,
    AzureOpenAIQuestionFormModel,
)

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    plan_verifier,
    production_manifest,
)
from tests.conversation.test_semantic_reasoning_shadow import _Identity, _Model

_AKS = "List the AKS ObjectTypes"


def _quote(text: str, occurrence: int = 1) -> dict[str, Any]:
    return {"text": text, "occurrence": occurrence}


def _constraint(text: str, role: str) -> dict[str, Any]:
    return {"quote": _quote(text), "role": role}


def _aks_form(cue: str = "List the AKS ObjectTypes", **extra: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "mentions": [
            {
                "id": "m1",
                "form": "concept",
                "domain": "declaration_kind",
                "span": _quote("ObjectTypes"),
            }
        ],
        "goals": [
            {
                "id": "g1",
                "level": "schema",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": _quote(cue),
                "confidence": 0.9,
            }
        ],
    }
    form.update(extra)
    return form


def _typed(raw: dict[str, Any], utterance: str = _AKS) -> SemanticQuestionForm:
    form = resolve_question_form(raw, utterance=utterance).form
    assert form is not None
    return form


_EXTRACTED = {
    "constraints": [
        _constraint("List", "asks"),
        _constraint("AKS", "restricts"),
        _constraint("ObjectTypes", "names"),
    ]
}


def test_a_stretched_cue_or_context_never_stands_in_for_a_constraint() -> None:
    stretched = _typed(_aks_form())
    in_context = _typed(_aks_form("List", context=[_quote("the AKS")]))
    stated = _aks_form("List", context=[_quote("the")])
    stated["mentions"].append(
        {"id": "m2", "form": "concept", "domain": "resource_class", "span": _quote("AKS")}
    )

    expected = FormReview("unfaithful", ("review_uncovered:restricts:9-12",))
    assert review_forms((stretched,), _EXTRACTED, utterance=_AKS) == expected
    assert review_forms((in_context,), _EXTRACTED, utterance=_AKS) == expected
    assert review_forms((_typed(stated),), _EXTRACTED, utterance=_AKS) == FormReview("faithful")


def test_a_constraint_needs_a_span_that_states_meaning_and_a_name_needs_a_mention() -> None:
    utterance = "Count VMs by type in the last 3 days"
    form = {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_type", "span": _quote("VMs")}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": "count", "group_by": "type", "cue": _quote("by type")},
                "time": {
                    "kind": "window",
                    "value": {"duration": {"amount": 3, "unit": "day"}},
                    "cue": _quote("in the last 3 days"),
                },
                "cue": _quote("Count"),
                "confidence": 0.9,
            }
        ],
    }
    typed = _typed(form, utterance)

    def verdict(*constraints: dict[str, Any]) -> FormReview:
        return review_forms((typed,), {"constraints": list(constraints)}, utterance=utterance)

    assert verdict(
        _constraint("Count", "asks"),
        _constraint("VMs", "names"),
        _constraint("by type", "groups"),
        _constraint("in the last 3 days", "times"),
    ) == FormReview("faithful")
    # Two readers may disagree on a role, so any span that states meaning covers it.
    assert verdict(_constraint("by type", "times")) == FormReview("faithful")
    # A name only a goal cue or a non-mention span covers is not stated as a thing.
    assert verdict(_constraint("Count", "names")).reasons == ("review_uncovered:names:0-5",)
    assert verdict(_constraint("by type", "names")).reasons == ("review_uncovered:names:10-17",)
    # A constraint that reaches past every meaningful span is not stated in full.
    assert verdict(_constraint("Count VMs", "restricts")).reasons == (
        "review_uncovered:restricts:0-9",
    )


def test_a_missing_empty_or_unlocated_extraction_releases_nothing() -> None:
    typed = _typed(_aks_form("List", context=[_quote("the AKS")]))

    assert review_forms((typed,), None, utterance=_AKS).outcome == "unavailable"
    assert review_forms((typed,), {"constraints": []}, utterance=_AKS).outcome == "invalid"
    unlocated = {"constraints": [_constraint("EKS", "names")]}
    assert review_forms((typed,), unlocated, utterance=_AKS).outcome == "invalid"
    unknown_role = {"constraints": [_constraint("AKS", "vibes")]}
    assert review_forms((typed,), unknown_role, utterance=_AKS).outcome == "invalid"
    assert extraction_schema()["$defs"]["SourceSpan"]["required"] == ["text", "occurrence"]


async def _shadow(model: _Model) -> Any:
    return await run_reasoning_shadow(
        model=model,
        utterance=_AKS,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )


async def test_an_uncovered_constraint_releases_nothing() -> None:
    admitted = _aks_form("List", context=[_quote("the AKS")])
    faithful = await _shadow(_Model([admitted], {}))
    rejected = await _shadow(_Model([admitted], {}, extraction=_EXTRACTED))

    assert faithful.review == "faithful" and faithful.released is True
    assert rejected.passes[0].disposition == "admitted"
    assert rejected.review == "unfaithful" and rejected.released is False
    assert rejected.review_reasons == ("review_uncovered:restricts:9-12",)
    assert "AKS" not in json.dumps(rejected.summary())


async def test_the_review_releases_only_a_complete_turn_and_fails_closed() -> None:
    class _Failing(_Model):
        async def extract_constraints(self, **kwargs: Any) -> dict[str, Any] | None:
            raise TimeoutError

    undeclared = _aks_form("List", context=[_quote("the AKS")])
    undeclared["goals"][0]["subject"] = "m9"
    skipped = await _shadow(_Model([undeclared, undeclared], {}))
    unavailable = await _shadow(_Failing([_aks_form("List", context=[_quote("the AKS")])], {}))

    assert skipped.passes[0].disposition == "invalid"
    assert skipped.review is None and skipped.released is False
    assert unavailable.review == "unavailable" and unavailable.released is False
    assert unavailable.review_reasons == ("review_error:TimeoutError",)


def _target(deployment: str) -> ModelRequestTarget:
    return ModelRequestTarget(
        endpoint="https://example.com",
        deployment=deployment,
        api_version="2024-06-01",
        auth_audience="https://example.com/.default",
        binding_id=f"binding-{deployment}",
    )


def _adapter(handler: Any, *, extraction: bool = True) -> AzureOpenAIQuestionFormModel:
    return AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=(_target("form-model"),),
            form_system_prompt="Return the closed question form.",
            concept_system_prompt="Choose concepts.",
            extraction_system_prompt="Extract constraints." if extraction else None,
            extraction_candidates=(_target("review-model"),),
        ),
    )


async def test_the_extractor_sees_only_the_masked_question_on_its_own_model() -> None:
    identifier = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-app/providers/"
        "Microsoft.ContainerService/managedClusters/aks-prod-01"
    )
    utterance = f"What does {identifier} depend on?"
    sent: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((str(request.url), json.loads(request.content)))
        content = {"constraints": [{"quote": _quote("⟦ID1⟧"), "role": "names"}]}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    extraction = await _adapter(handler).extract_constraints(
        utterance=utterance, context=(), locale="en"
    )
    disabled = await _adapter(handler, extraction=False).extract_constraints(
        utterance=utterance, context=(), locale="en"
    )

    assert len(sent) == 1
    url, body = sent[0]
    assert "review-model" in url and "form-model" not in url
    text = json.dumps(body, ensure_ascii=False)
    assert "00000000-0000" not in text and "managedClusters" not in text
    payload = json.loads(body["messages"][-1]["content"])
    assert set(payload) == {"utterance", "context", "locale"}
    assert extraction == {"constraints": [{"quote": _quote(identifier), "role": "names"}]}
    assert disabled is None


_GROUPED = "Count VMs by type"


def _grouped_form(**goal: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_type", "span": _quote("VMs")}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": "count", "group_by": "none"},
                "cue": _quote("Count"),
                "confidence": 0.9,
                **goal,
            }
        ],
        "context": [_quote("by type")],
    }
    return form


async def _grouped(model: _Model) -> Any:
    return await run_reasoning_shadow(
        model=model,
        utterance=_GROUPED,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )


_GROUPED_EXTRACTION = {
    "constraints": [
        _constraint("Count", "asks"),
        _constraint("VMs", "names"),
        _constraint("by type", "groups"),
    ]
}


async def test_one_review_repair_states_the_uncovered_constraint_and_releases() -> None:
    stated = _grouped_form(measure={"kind": "count", "group_by": "type", "cue": _quote("by type")})
    stated["context"] = []
    model = _Model([_grouped_form(), stated], {}, extraction=_GROUPED_EXTRACTION)

    observation = await _grouped(model)

    assert [item.disposition for item in observation.passes] == ["admitted", "admitted"]
    assert observation.passes[1].repair == "review_applied"
    assert observation.passes[1].repaired_reasons == ("review_uncovered:groups:10-17",)
    assert model.form_calls[1]["repair"].violations == (
        'review_uncovered: the words "by type" at occurrence 1 state a groups constraint that '
        "no mention, filter, relation, time, measure, or unsupported constraint states",
    )
    assert observation.review == "faithful" and observation.released is True
    assert len(model.review_calls) == 1


async def test_a_review_repair_that_rewrites_meaning_or_fails_releases_nothing() -> None:
    regrouped = _grouped_form(
        operation="select",
        measure={"kind": "count", "group_by": "type", "cue": _quote("by type")},
    )
    regrouped["context"] = []
    rewritten = await _grouped(
        _Model([_grouped_form(), regrouped], {}, extraction=_GROUPED_EXTRACTION)
    )
    unrepaired = await _grouped(
        _Model([_grouped_form(), _grouped_form()], {}, extraction=_GROUPED_EXTRACTION)
    )

    assert rewritten.passes[1].disposition == "invalid"
    assert rewritten.passes[1].repair == "operand_dropped"
    assert rewritten.released is False
    assert unrepaired.passes[1].disposition == "admitted"
    assert unrepaired.review == "unfaithful" and unrepaired.released is False


def test_a_hypothetical_premise_is_stated_only_by_an_impact_goal() -> None:
    utterance = "What could break if sql-app fails?"
    form = {
        "mentions": [{"id": "m1", "form": "name", "domain": "instance", "span": _quote("sql-app")}],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "impact",
                "subject": "m1",
                "subject_scope": "anchor",
                "cue": _quote("What could break if"),
                "confidence": 0.9,
            }
        ],
        "context": [_quote("fails")],
    }
    listing = json.loads(json.dumps(form))
    listing["goals"][0]["operation"] = "select"
    extraction = {
        "constraints": [
            _constraint("What could break", "asks"),
            _constraint("sql-app", "names"),
            _constraint("if sql-app fails", "supposes"),
        ]
    }

    assert review_forms((_typed(form, utterance),), extraction, utterance=utterance).faithful
    assert review_forms((_typed(listing, utterance),), extraction, utterance=utterance).reasons == (
        "review_uncovered:supposes:17-33",
    )


def test_a_particle_attached_to_a_mention_belongs_to_that_mention() -> None:
    utterance = "vm-app-01을 포함하는 리소스 그룹은?"
    form = {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": _quote("vm-app-01")},
            {
                "id": "m2",
                "form": "concept",
                "domain": "resource_type",
                "span": _quote("리소스 그룹"),
            },
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m2",
                "subject_scope": "collection",
                "relation": {
                    "sense": "containment",
                    "anchor": "m1",
                    "anchor_role": "member",
                    "result_role": "container",
                    "cue": _quote("포함하는"),
                },
                "cue": _quote("은?"),
                "confidence": 0.9,
            }
        ],
    }
    typed = _typed(form, utterance)
    uncued = json.loads(json.dumps(form))
    uncued["goals"][0]["relation"]["cue"] = _quote("은?")
    attached = {"constraints": [_constraint("vm-app-01을 포함하는", "relates")]}

    # The case ending after vm-app-01 is part of that word, so the relation cue covers the rest.
    assert review_forms((typed,), attached, utterance=utterance).faithful
    # A word no span states stays uncovered even beside an attached particle.
    assert review_forms((_typed(uncued, utterance),), attached, utterance=utterance).reasons == (
        "review_uncovered:relates:0-15",
    )
