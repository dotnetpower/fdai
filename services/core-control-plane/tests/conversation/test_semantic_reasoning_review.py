"""A blind constraint extraction releases a compilation only when the form states it all."""

from __future__ import annotations

import json
from typing import Any

import httpx
from fdai.core.conversation.semantic_reasoning_concepts import ConceptCandidate, ConceptShard
from fdai.core.conversation.semantic_reasoning_form import MentionDomain, SemanticQuestionForm
from fdai.core.conversation.semantic_reasoning_proposal import resolve_question_form
from fdai.core.conversation.semantic_reasoning_review import (
    FormReview,
    describe_uncovered,
    extraction_schema,
    resolve_extraction,
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
        content = {
            "constraints": [{"quote": _quote("⟦ID1⟧"), "role": "names"}],
            "literals": [_quote("⟦ID1⟧")],
        }
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
    assert extraction == {
        "constraints": [{"quote": _quote(identifier), "role": "names"}],
        "literals": [_quote(identifier)],
    }
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


def _one_mention_form(utterance: str, text: str, domain: str) -> SemanticQuestionForm:
    form = _aks_form("List", context=[_quote("the")])
    form["mentions"][0].update(domain=domain, span=_quote(text))
    return _typed(form, utterance)


def test_a_mention_that_merges_a_restriction_with_another_constraint_releases_nothing() -> None:
    merged = _one_mention_form(_AKS, "AKS ObjectTypes", "object_type")

    assert review_forms((merged,), _EXTRACTED, utterance=_AKS) == FormReview(
        "unfaithful", ("review_merged:9-12", "review_merged:13-24")
    )


def test_one_mention_may_hold_constraints_that_restate_or_only_name_one_thing() -> None:
    utterance = "List the AKS clusters"
    named = _one_mention_form(utterance, "AKS clusters", "resource_type")
    two_names = {"constraints": [_constraint("AKS", "names"), _constraint("clusters", "names")]}
    restated = {
        "constraints": [_constraint("AKS ObjectTypes", "names"), _constraint("AKS", "restricts")]
    }
    alone = {"constraints": [_constraint("AKS", "restricts")]}
    merged = _one_mention_form(_AKS, "AKS ObjectTypes", "object_type")

    assert review_forms((named,), two_names, utterance=utterance) == FormReview("faithful")
    assert review_forms((merged,), restated, utterance=_AKS) == FormReview("faithful")
    assert review_forms((merged,), alone, utterance=_AKS) == FormReview("faithful")


def test_a_kind_mention_that_holds_another_named_thing_releases_nothing() -> None:
    utterance = "List the Workload ObjectType"
    two_names = {
        "constraints": [_constraint("Workload", "names"), _constraint("ObjectType", "names")]
    }
    kind = _one_mention_form(utterance, "Workload ObjectType", "declaration_kind")
    named = _one_mention_form(utterance, "Workload ObjectType", "object_type")
    raw = _aks_form("List", context=[_quote("the")])
    raw["mentions"][0].update(domain="object_type", span=_quote("Workload"))
    raw["mentions"].append(
        {"id": "m2", "form": "concept", "domain": "declaration_kind", "span": _quote("ObjectType")}
    )
    split = _typed(raw, utterance)

    # A kind or ObjectType binds one name, so the name beside it is dropped or confused.
    for merged in (kind, named):
        assert review_forms((merged,), two_names, utterance=utterance) == FormReview(
            "unfaithful", ("review_merged:9-17", "review_merged:18-28")
        )
    # The kind word as its own declaration-kind mention states both names.
    assert review_forms((split,), two_names, utterance=utterance) == FormReview("faithful")


async def test_a_merged_mention_is_held_without_a_repair_it_could_not_make() -> None:
    merged = _aks_form("List", context=[_quote("the")])
    merged["mentions"][0].update(domain="object_type", span=_quote("AKS ObjectTypes"))
    model = _Model([merged, merged], {}, extraction=_EXTRACTED)

    observation = await _shadow(model)

    assert observation.review == "unfaithful" and observation.released is False
    assert observation.review_reasons == ("review_merged:9-12", "review_merged:13-24")
    assert len(model.form_calls) == 1


def test_a_repair_violation_names_a_mention_that_quotes_part_of_the_constraint() -> None:
    utterance = "첫 번째 것은 무엇에 의존해?"
    form = _aks_form("무엇에", context=[_quote("것은")])
    form["mentions"][0].update(form="ordinal", domain="instance", span=_quote("첫 번째"))
    form["mentions"][0]["position"] = 1
    form["goals"][0].update(level="instance", operation="traverse", subject_scope="prior_result")
    form["goals"][0]["relation"] = {
        "sense": "dependency",
        "anchor_role": "dependent",
        "result_role": "dependency",
        "cue": _quote("의존해"),
    }
    typed = _typed(form, utterance)
    extraction = resolve_extraction(
        {"constraints": [_constraint("첫 번째 것", "names")]}, utterance
    )
    assert extraction is not None

    partial = describe_uncovered(extraction.constraints[0], utterance, (typed,))
    alone = describe_uncovered(extraction.constraints[0], utterance)

    assert partial.endswith(
        "; mention m1 quotes only part of these words: widen its quote when they all name "
        "one thing, or give the other words their own place when they state something else"
    )
    assert "mention m1" not in alone


_FRAGMENT = "이름에 app-dev가 들어간 리소스는?"
_FRAGMENT_EXTRACTION = {
    "constraints": [
        _constraint("이름에 app-dev가 들어간", "restricts"),
        _constraint("리소스", "names"),
    ],
    "literals": [_quote("app-dev")],
}


def _fragment_form(value: str = "app-dev", cue: str = "이름에") -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_type", "span": _quote("리소스")},
            {"id": "m2", "form": "value", "domain": "instance", "span": _quote(value)},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "name_fragment", "mention": "m2", "cue": _quote(cue)}],
                "cue": _quote("리소스는"),
                "confidence": 0.9,
            }
        ],
    }


async def _fragment(model: _Model) -> Any:
    return await run_reasoning_shadow(
        model=model,
        account_spans=False,
        utterance=_FRAGMENT,
        context=(),
        locale="ko",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
        retain_compilations=True,
    )


async def test_a_review_repair_never_changes_a_literal_value() -> None:
    picks = {"m1": ["any:resource"]}
    widened = await _fragment(
        _Model(
            [_fragment_form(), _fragment_form("app-dev가 들어간", "이름에 app-dev가 들어간")],
            picks,
            extraction=_FRAGMENT_EXTRACTION,
        )
    )
    cued = await _fragment(
        _Model(
            [_fragment_form(), _fragment_form(cue="이름에 app-dev가 들어간")],
            picks,
            extraction=_FRAGMENT_EXTRACTION,
        )
    )

    assert widened.passes[1].repair == "operand_dropped" and widened.released is False
    assert cued.review == "faithful" and cued.released is True
    (batch,) = cued.compilations[0].goals[0].batches
    assert '"equals":"app-dev","operator":"contains","property":"name"' in "".join(
        node.arguments_json for node in batch.plan.nodes
    )


def test_a_repair_violation_keeps_a_literal_value_and_points_to_its_cue() -> None:
    typed = _typed(_fragment_form(), _FRAGMENT)
    extraction = resolve_extraction(_FRAGMENT_EXTRACTION, _FRAGMENT)
    assert extraction is not None

    described = describe_uncovered(extraction.constraints[0], _FRAGMENT, (typed,))

    assert described.endswith(
        "; mention m2 is a literal value whose quote must stay as it is, so state the other "
        "words in the cue of the filter or relation that cites it"
    )
    assert "widen" not in described


def _fragment_verdict(form: dict[str, Any], *literals: str) -> FormReview:
    extraction = {**_FRAGMENT_EXTRACTION, "literals": [_quote(item) for item in literals]}
    return review_forms((_typed(form, _FRAGMENT),), extraction, utterance=_FRAGMENT)


def test_a_literal_operand_must_equal_a_literal_the_extractor_quoted_alone() -> None:
    stated = _fragment_form(cue="이름에 app-dev가 들어간")
    named = _fragment_form(cue="이름에 app-dev가 들어간")
    named["mentions"][1]["form"] = "name"

    assert _fragment_verdict(stated, "app-dev") == FormReview("faithful")
    assert _fragment_verdict(named, "app-dev") == FormReview("faithful")
    assert _fragment_verdict(stated, "app-dev가").reasons == ("review_literal_differs:4-11",)
    assert _fragment_verdict(named).reasons == ("review_literal_differs:4-11",)
    assert extraction_schema()["required"] == ["constraints", "literals"]


def test_a_literal_the_extractor_cannot_locate_voids_the_review() -> None:
    typed = _typed(_fragment_form(cue="이름에 app-dev가 들어간"), _FRAGMENT)
    unlocated = {**_FRAGMENT_EXTRACTION, "literals": [_quote("app-prod")]}
    malformed = {**_FRAGMENT_EXTRACTION, "literals": "app-dev"}

    assert review_forms((typed,), unlocated, utterance=_FRAGMENT).outcome == "invalid"
    assert review_forms((typed,), malformed, utterance=_FRAGMENT).outcome == "invalid"


async def test_a_review_repair_never_moves_a_name_that_a_fragment_filter_reads() -> None:
    first = _fragment_form()
    first["mentions"][1]["form"] = "name"
    widened = _fragment_form("app-dev가 들어간", "이름에 app-dev가 들어간")
    widened["mentions"][1]["form"] = "name"

    observation = await _fragment(
        _Model([first, widened], {"m1": ["any:resource"]}, extraction=_FRAGMENT_EXTRACTION)
    )

    assert observation.passes[1].repair == "operand_dropped"
    assert observation.released is False


def test_a_value_no_plan_reads_verbatim_needs_no_extracted_literal() -> None:
    utterance = "List stopped VMs"
    form = {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_type", "span": _quote("VMs")},
            {"id": "m2", "form": "value", "domain": "state", "span": _quote("stopped")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "state", "mention": "m2", "cue": _quote("stopped")}],
                "cue": _quote("List"),
                "confidence": 0.9,
            }
        ],
    }
    extraction = {
        "constraints": [_constraint("stopped", "restricts"), _constraint("VMs", "names")],
        "literals": [],
    }

    assert review_forms((_typed(form, utterance),), extraction, utterance=utterance) == (
        FormReview("faithful")
    )


def _dependents_form(utterance: str) -> SemanticQuestionForm:
    form = {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": _quote("sql-app")},
            {"id": "m2", "form": "concept", "domain": "resource_type", "span": _quote("리소스")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m2",
                "subject_scope": "collection",
                "relation": {
                    "sense": "dependency",
                    "anchor": "m1",
                    "anchor_role": "dependency",
                    "result_role": "dependent",
                    "cue": _quote("의존하는"),
                },
                "cue": _quote("는?"),
                "confidence": 0.9,
            }
        ],
    }
    return _typed(form, utterance)


def test_a_restriction_isolated_in_an_attached_particle_is_never_stated_by_its_mention() -> None:
    only = "sql-app에만 의존하는 리소스는?"
    plain = "sql-app에 의존하는 리소스는?"
    isolated = {
        "constraints": [
            _constraint("sql-app", "names"),
            _constraint("만", "restricts"),
            _constraint("의존하는", "relates"),
            _constraint("리소스", "names"),
        ],
        "literals": [],
    }
    phrased = {
        "constraints": [
            _constraint("sql-app에 의존하는", "relates"),
            _constraint("리소스", "names"),
        ],
        "literals": [],
    }

    assert review_forms((_dependents_form(only),), isolated, utterance=only).reasons == (
        "review_uncovered:restricts:8-9",
    )
    assert review_forms((_dependents_form(plain),), phrased, utterance=plain) == (
        FormReview("faithful")
    )


_ONLY = "Which resources depend only on sql-app?"
_ONLY_EXTRACTION = {
    "constraints": [
        _constraint("resources", "names"),
        _constraint("depend", "relates"),
        _constraint("only", "negates"),
        _constraint("sql-app", "names"),
    ],
    "literals": [],
}


def _only_form(cue: str = "depend only on", **extra: Any) -> dict[str, Any]:
    return {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_type", "span": _quote("resources")},
            {"id": "m2", "form": "name", "domain": "instance", "span": _quote("sql-app")},
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
                    "cue": _quote(cue),
                },
                "cue": _quote("Which"),
                "confidence": 0.9,
            }
        ],
        **extra,
    }


def test_an_exclusion_absorbed_into_a_cue_is_never_stated() -> None:
    absorbed = _typed(_only_form(), _ONLY)
    acknowledged = _typed(_only_form("depend", unsupported_constraints=[_quote("only")]), _ONLY)

    assert review_forms((absorbed,), _ONLY_EXTRACTION, utterance=_ONLY).reasons == (
        "review_unexpressible:negates:23-27",
    )
    assert review_forms((acknowledged,), _ONLY_EXTRACTION, utterance=_ONLY) == (
        FormReview("faithful")
    )


def test_an_exclusion_attached_to_a_name_needs_an_unsupported_constraint() -> None:
    utterance = "sql-app에만 의존하는 리소스는?"
    typed = _dependents_form(utterance)
    whole_word = {
        "constraints": [
            _constraint("sql-app에만", "negates"),
            _constraint("의존하는", "relates"),
            _constraint("리소스", "names"),
        ],
        "literals": [],
    }

    assert review_forms((typed,), whole_word, utterance=utterance).reasons == (
        "review_unexpressible:negates:0-9",
    )


def test_a_comparison_absorbed_into_a_measure_cue_is_never_stated() -> None:
    utterance = "Which VMs run above 80% CPU?"
    form = {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_type", "span": _quote("VMs")}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "measure": {"kind": "metric", "cue": _quote("run above 80% CPU")},
                "cue": _quote("Which"),
                "confidence": 0.9,
            }
        ],
    }
    extraction = {
        "constraints": [
            _constraint("VMs", "names"),
            _constraint("above 80%", "compares"),
            _constraint("CPU", "measures"),
        ],
        "literals": [],
    }

    assert review_forms((_typed(form, utterance),), extraction, utterance=utterance).reasons == (
        "review_unexpressible:compares:14-23",
    )


async def test_one_review_repair_turns_an_absorbed_exclusion_into_a_clarification() -> None:
    repaired = _only_form(unsupported_constraints=[_quote("only")])
    shortened = _only_form("depend", unsupported_constraints=[_quote("only")])
    model = _Model([_only_form(), repaired], {"m1": ["any:resource"]}, extraction=_ONLY_EXTRACTION)
    dropping = _Model(
        [_only_form(), shortened], {"m1": ["any:resource"]}, extraction=_ONLY_EXTRACTION
    )

    observation = await run_reasoning_shadow(
        model=model,
        account_spans=False,
        utterance=_ONLY,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )

    shortened_observation = await run_reasoning_shadow(
        model=dropping,
        account_spans=False,
        utterance=_ONLY,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )

    assert "review_unexpressible" in model.form_calls[1]["repair"].violations[0]
    assert observation.passes[-1].disposition == "clarify"
    assert observation.passes[-1].reasons == ("constraint_unsupported:23-27",)
    assert observation.released is False
    # A repair that shortens the cue drops what it stated, so nothing is released either.
    assert shortened_observation.passes[-1].repair == "operand_dropped"
    assert shortened_observation.released is False


async def test_the_second_concept_chooser_is_the_other_model_family() -> None:
    sent: list[str] = []
    schemas: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        schemas.append(json.loads(request.content)["response_format"]["json_schema"]["schema"])
        content = {"shard_digest": "digest", "choices": []}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    candidate = ConceptCandidate("value:compute.vm", ("compute.vm",), ("virtual machine",))
    shard = ConceptShard(MentionDomain.RESOURCE_TYPE, 0, 1, (candidate,), "digest")
    mentions = ({"mention": "m1", "text": "VMs"},)
    adapter = _adapter(handler)
    unpaired = AzureOpenAIQuestionFormModel(
        identity=_Identity(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=AzureOpenAIQuestionFormConfig(
            candidates=(_target("form-model"),),
            form_system_prompt="Return the closed question form.",
            concept_system_prompt="Choose concepts.",
        ),
    )

    await adapter.choose_concepts(utterance="List VMs", mentions=mentions, shard=shard)
    await adapter.choose_concepts(utterance="List VMs", mentions=mentions, shard=shard, second=True)
    none = await unpaired.choose_concepts(
        utterance="List VMs", mentions=mentions, shard=shard, second=True
    )

    assert ["form-model" in url for url in sent] == [True, False]
    assert "review-model" in sent[1]
    assert none is None
    # Both choosers may name only the presented mention, candidate, and shard digest.
    for schema in schemas:
        choice = schema["properties"]["choices"]["items"]["properties"]
        assert choice["mention"]["enum"] == ["m1"]
        assert choice["candidate_ids"]["items"]["enum"] == ["value:compute.vm"]
        assert schema["properties"]["shard_digest"]["enum"] == [shard.digest]


def test_a_word_meaning_all_states_no_restriction_to_cover() -> None:
    utterance = "sql-app에 의존하는 모든 리소스는?"
    typed = _dependents_form(utterance)
    extraction = {
        "constraints": [
            _constraint("sql-app에 의존하는", "relates"),
            _constraint("모든", "quantifies"),
            _constraint("리소스", "names"),
        ],
        "literals": [],
    }

    assert review_forms((typed,), extraction, utterance=utterance) == FormReview("faithful")
    assert "quantifies" in extraction_schema()["$defs"]["ConstraintRole"]["enum"]


def test_a_references_position_words_are_never_a_merged_restriction() -> None:
    utterance = "What does the second one depend on?"
    form = {
        "mentions": [
            {
                "id": "m1",
                "form": "ordinal",
                "domain": "instance",
                "span": _quote("second one"),
                "position": 2,
            }
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
                    "anchor_role": "dependent",
                    "result_role": "dependency",
                    "cue": _quote("depend on"),
                },
                "cue": _quote("What does"),
                "confidence": 0.9,
            }
        ],
    }
    extraction = {
        "constraints": [
            _constraint("second", "restricts"),
            _constraint("one", "names"),
            _constraint("depend on", "relates"),
        ],
        "literals": [],
    }

    assert review_forms((_typed(form, utterance),), extraction, utterance=utterance) == (
        FormReview("faithful")
    )
