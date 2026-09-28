"""Utterance span accounting: no stated word leaves the form without the model's judgment."""

from __future__ import annotations

import json
from typing import Any

import httpx
from fdai.core.conversation.semantic_reasoning_admission import (
    AdmissionDisposition,
    FormAdmission,
    SpanAccounting,
    admit_question_form,
)
from fdai.core.conversation.semantic_reasoning_form import SemanticQuestionForm
from fdai.core.conversation.semantic_reasoning_proposal import resolve_question_form
from fdai.core.conversation.semantic_reasoning_repair import (
    FormRepair,
    repair_for,
    repair_keeps_operands,
)
from fdai.core.conversation.semantic_reasoning_shadow import run_reasoning_shadow

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    plan_verifier,
    production_manifest,
)
from tests.conversation.test_semantic_reasoning_shadow import _adapter, _Model

_AKS = "List the AKS ObjectTypes"


def _quote(text: str, occurrence: int = 1) -> dict[str, Any]:
    return {"text": text, "occurrence": occurrence}


def _aks_form(**extra: Any) -> dict[str, Any]:
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
                "cue": _quote("List"),
                "confidence": 0.9,
            }
        ],
        "context": [_quote("the")],
    }
    form.update(extra)
    return form


def _admit(raw: dict[str, Any], utterance: str, **kwargs: Any) -> FormAdmission:
    resolution = resolve_question_form(raw, utterance=utterance)
    assert resolution.form is not None, resolution
    return admit_question_form(resolution.form, utterance=utterance, **kwargs)


def _unaccounted(admission: FormAdmission) -> list[str]:
    return [reason for reason in admission.reasons if reason.startswith("span_unaccounted")]


def test_a_stated_word_outside_every_quote_makes_the_form_invalid() -> None:
    admission = _admit(_aks_form(), _AKS)

    assert admission.disposition is AdmissionDisposition.INVALID
    assert admission.reasons == ("span_unaccounted:9-12",)
    assert all("AKS" not in reason for reason in admission.reasons)


def test_every_quote_kind_accounts_for_its_words() -> None:
    as_mention = _aks_form()
    as_mention["mentions"].append(
        {"id": "m2", "form": "concept", "domain": "resource_class", "span": _quote("AKS")}
    )
    as_context = _aks_form(context=[_quote("the AKS")])

    # The mention is accounted for; that no goal uses it is a separate clarification.
    assert _admit(as_mention, _AKS).reasons == ("mention_unused:m2",)
    # Labeling a word as context is the model's explicit, auditable judgment.
    assert _admit(as_context, _AKS).disposition is AdmissionDisposition.ADMITTED


def test_korean_particles_and_hyphenated_names_stay_accounted_with_their_word() -> None:
    utterance = "rg-app에 있는 VM 목록 보여줘"
    form = {
        "mentions": [
            {"id": "m1", "form": "name", "domain": "instance", "span": _quote("rg-app")},
            {"id": "m2", "form": "concept", "domain": "resource_type", "span": _quote("VM")},
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
                    "anchor_role": "container",
                    "result_role": "member",
                    "cue": _quote("에 있는"),
                },
                "cue": _quote("목록 보여줘"),
                "confidence": 0.9,
            }
        ],
    }

    assert _unaccounted(_admit(form, utterance)) == []


def test_an_attached_particle_or_comparison_sign_needs_its_own_place() -> None:
    only = "AKS만 보여줘"
    form = {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_class", "span": _quote("AKS")}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": _quote("보여줘"),
                "confidence": 0.9,
            }
        ],
    }
    placed = json.loads(json.dumps(form))
    placed["goals"][0]["cue"] = _quote("만 보여줘")
    compared = "List VMs with CPU > 80%"
    comparison = {
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
                "cue": _quote("List"),
                "confidence": 0.9,
            }
        ],
        "context": [_quote("with CPU"), _quote("80")],
    }
    unsupported = json.loads(json.dumps(comparison))
    unsupported["context"] = [_quote("with")]
    unsupported["unsupported_constraints"] = [_quote("CPU > 80%")]

    assert _unaccounted(_admit(form, only)) == ["span_unaccounted:3-4"]
    assert _unaccounted(_admit(placed, only)) == []
    assert _unaccounted(_admit(comparison, compared)) == ["span_unaccounted:18-19"]
    clarified = _admit(unsupported, compared)
    assert clarified.disposition is AdmissionDisposition.CLARIFY
    assert clarified.reasons == ("constraint_unsupported:14-23",)


def test_filter_and_measure_cues_account_for_their_words() -> None:
    utterance = "Count VMs by type that are running"
    form = {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_type", "span": _quote("VMs")},
            {"id": "m2", "form": "value", "domain": "state", "span": _quote("running")},
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "count",
                "subject": "m1",
                "subject_scope": "collection",
                "filters": [{"role": "state", "mention": "m2", "cue": _quote("that are")}],
                "measure": {"kind": "count", "group_by": "type", "cue": _quote("by type")},
                "cue": _quote("Count"),
                "confidence": 0.9,
            }
        ],
    }

    assert _unaccounted(_admit(form, utterance)) == []
    without_cues = json.loads(json.dumps(form))
    del without_cues["goals"][0]["filters"][0]["cue"]
    del without_cues["goals"][0]["measure"]["cue"]
    assert _unaccounted(_admit(without_cues, utterance)) == [
        "span_unaccounted:10-12",
        "span_unaccounted:13-17",
        "span_unaccounted:18-22",
        "span_unaccounted:23-26",
    ]


def test_a_pass_that_leaves_goals_for_later_defers_accounting_to_the_final_pass() -> None:
    first = _aks_form(context=[], remaining_goals=True)
    final = _aks_form(context=[])
    earlier_form = _aks_form(context=[_quote("the")])
    earlier_form["mentions"].append(
        {"id": "m2", "form": "concept", "domain": "resource_class", "span": _quote("AKS")}
    )
    earlier = SpanAccounting().after(
        resolve_question_form(earlier_form, utterance=_AKS).form  # type: ignore[arg-type]
    )

    assert _unaccounted(_admit(first, _AKS)) == []
    assert _unaccounted(_admit(final, _AKS)) == ["span_unaccounted:5-8", "span_unaccounted:9-12"]
    # An earlier mention carries over; an earlier pass's context never does.
    assert _unaccounted(_admit(final, _AKS, accounting=earlier)) == ["span_unaccounted:5-8"]
    assert _unaccounted(_admit(final, _AKS, accounting=SpanAccounting(required=False))) == []


def test_repair_violations_quote_the_whole_unaccounted_token_and_its_occurrence() -> None:
    utterance = "List the ObjectTypes, not the AKS-01 ObjectTypes"
    raw = _aks_form(context=[_quote("the"), _quote("not")])
    resolution = resolve_question_form(raw, utterance=utterance)
    admission = admit_question_form(resolution.form, utterance=utterance)  # type: ignore[arg-type]

    repair = repair_for(raw, resolution, admission, utterance=utterance)

    assert admission.reasons == (
        "span_unaccounted:26-29",
        "span_unaccounted:30-33",
        "span_unaccounted:34-36",
        "span_unaccounted:37-48",
    )
    assert repair is not None
    assert repair.violations == (
        'span_unaccounted: the word "the" at occurrence 2 is outside every mention, cue, '
        "and context quote",
        'span_unaccounted: the word "AKS-01" at occurrence 1 is outside every mention, cue, '
        "and context quote",
        'span_unaccounted: the word "ObjectTypes" at occurrence 2 is outside every mention, '
        "cue, and context quote",
    )


async def test_the_adapter_masks_an_identifier_named_in_a_repair_violation() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    identifier = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-app/providers/"
        "Microsoft.ContainerService/managedClusters/aks-prod-01"
    )
    utterance = f"Show {identifier} health"
    raw = {
        "mentions": [],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject_scope": "collection",
                "cue": _quote("Show"),
                "confidence": 0.9,
            }
        ],
        "context": [_quote("health")],
    }
    resolution = resolve_question_form(raw, utterance=utterance)
    admission = admit_question_form(resolution.form, utterance=utterance)  # type: ignore[arg-type]
    repair = repair_for(raw, resolution, admission, utterance=utterance)
    assert repair is not None
    (violation,) = repair.violations
    assert identifier in violation
    await _adapter(handler).propose_form(
        utterance=utterance,
        context=(),
        locale="en",
        pass_index=0,
        prior_goals=(),
        repair=FormRepair(previous={"mentions": [], "goals": []}, violations=(violation,)),
    )

    assert len(sent) == 1
    assert "00000000-0000" not in sent[0] and "managedClusters" not in sent[0]
    payload = json.loads(json.loads(sent[0])["messages"][-1]["content"])
    assert "⟦ID1⟧" in payload["repair"]["violations"][0]


async def test_the_shadow_accounts_across_passes_and_repairs_an_unaccounted_word() -> None:
    utterance = "Count VMs and list AKS clusters"
    first = {
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
                "cue": _quote("Count"),
                "confidence": 0.9,
            }
        ],
        "remaining_goals": True,
    }
    dropped = {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_class", "span": _quote("clusters")}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": _quote("list"),
                "confidence": 0.9,
            }
        ],
        "context": [_quote("and")],
    }
    final = json.loads(json.dumps(dropped))
    final["mentions"][0]["span"] = _quote("AKS clusters")
    model = _Model([first, dropped, final], {})

    observation = await run_reasoning_shadow(
        model=model,
        utterance=utterance,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )

    assert [item.disposition for item in observation.passes] == ["admitted", "admitted"]
    assert observation.released is True
    assert observation.passes[1].repair == "applied"
    assert observation.passes[1].repaired_reasons == ("span_unaccounted:19-22",)
    repair = model.form_calls[2]["repair"]
    assert repair.violations == (
        'span_unaccounted: the word "AKS" at occurrence 1 is outside every mention, cue, '
        "and context quote",
    )


_COUNT = "Count VMs by type in the last 3 days"


def _count_form(**goal: Any) -> dict[str, Any]:
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
            }
        ],
    }
    form["goals"][0].update(goal)
    return form


def _typed(raw: dict[str, Any], utterance: str = _COUNT) -> SemanticQuestionForm:
    form = resolve_question_form(raw, utterance=utterance).form
    assert form is not None
    return form


def _placing(rejected: dict[str, Any], repaired: dict[str, Any]) -> bool:
    return repair_keeps_operands(
        rejected,
        _typed(repaired),
        utterance=_COUNT,
        typed=_typed(rejected),
        extension_only=True,
    )


def test_an_accounting_repair_may_state_defaults_but_never_rewrite_stated_meaning() -> None:
    grouping = {"kind": "count", "group_by": "type", "cue": _quote("by type")}
    window = {
        "kind": "window",
        "value": {"duration": {"amount": 3, "unit": "day"}},
        "cue": _quote("in the last 3 days"),
    }
    stated = _count_form(measure=grouping, time=window)
    relabeled = json.loads(json.dumps(stated))
    relabeled["mentions"][0]["domain"] = "resource_class"
    grouped = _count_form(measure=grouping)
    regrouped = json.loads(json.dumps(stated))
    regrouped["goals"][0]["measure"]["group_by"] = "none"
    extended = json.loads(json.dumps(stated))
    extended["goals"].append(
        {**json.loads(json.dumps(stated["goals"][0])), "id": "g2", "operation": "select"}
    )

    widened = json.loads(json.dumps(stated))
    widened["mentions"][0]["span"] = _quote("VMs by")

    assert _placing(_count_form(), stated)
    assert _placing(_count_form(), extended)
    assert _placing(_count_form(), widened)
    assert not _placing(widened, stated)
    assert not _placing(_count_form(), relabeled)
    assert not _placing(grouped, regrouped)


async def test_a_continuation_that_never_accounts_for_its_words_is_never_released() -> None:
    utterance = "Count VMs and list AKS clusters"
    first = {
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
                "cue": _quote("Count"),
                "confidence": 0.9,
            }
        ],
        "remaining_goals": True,
    }
    dropped = {
        "mentions": [
            {"id": "m1", "form": "concept", "domain": "resource_class", "span": _quote("clusters")}
        ],
        "goals": [
            {
                "id": "g1",
                "level": "instance",
                "operation": "select",
                "subject": "m1",
                "subject_scope": "collection",
                "cue": _quote("list"),
                "confidence": 0.9,
            }
        ],
        "context": [_quote("and")],
    }
    model = _Model([first, dropped, json.loads(json.dumps(dropped))], {})

    observation = await run_reasoning_shadow(
        model=model,
        utterance=utterance,
        context=(),
        locale="en",
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )

    assert [item.disposition for item in observation.passes] == ["admitted", "invalid"]
    assert observation.released is False
    assert "continuation_failed" in observation.notes
