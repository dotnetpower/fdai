"""A blind reader confirms relation direction before a compilation is released."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fdai.core.conversation.semantic_reasoning_direction import (
    DirectionQuestion,
    direction_questions,
    direction_reasons,
    direction_schema,
)
from fdai.core.conversation.semantic_reasoning_form import (
    RelationScope,
    RelationSense,
    SemanticQuestionForm,
    SubjectRole,
)
from fdai.core.prompts.profiles import compose_static_selection
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm.semantic_question_form import (
    AzureOpenAIQuestionFormConfig,
    AzureOpenAIQuestionFormModel,
)

from tests.conversation.semantic_reasoning_support import ROOT, production_manifest, span
from tests.conversation.test_semantic_reasoning_review import _target
from tests.conversation.test_semantic_reasoning_shadow import _Identity


def _form(utterance: str, anchor: str, sense: str, roles: tuple[str, str]) -> SemanticQuestionForm:
    return SemanticQuestionForm.model_validate(
        {
            "mentions": [
                {"id": "m1", "form": "name", "domain": "instance", "span": span(utterance, anchor)}
            ],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "traverse",
                    "subject": "m1",
                    "subject_scope": "anchor",
                    "relation": {
                        "sense": sense,
                        "anchor_role": roles[0],
                        "result_role": roles[1],
                        "cue": span(utterance, anchor),
                    },
                    "cue": span(utterance, anchor),
                    "confidence": 0.9,
                }
            ],
        }
    )


def test_only_a_directional_relation_is_confirmed() -> None:
    descriptors = production_manifest().descriptors
    uses = "What uses kv-app?"
    peers = "What is vnet-hub peered with?"

    (question,) = direction_questions(
        (_form(uses, "kv-app", "dependency", ("dependency", "dependent")),),
        utterance=uses,
        descriptors=descriptors,
    )
    either = direction_questions(
        (_form(uses, "kv-app", "dependency", ("either", "either")),),
        utterance=uses,
        descriptors=descriptors,
    )
    reciprocal = direction_questions(
        (_form(peers, "vnet-hub", "connectivity", ("sender", "receiver")),),
        utterance=peers,
        descriptors=descriptors,
    )

    assert (question.anchor, question.first, question.second) == (
        "kv-app",
        SubjectRole.DEPENDENT,
        SubjectRole.DEPENDENCY,
    )
    every_kind = _form(uses, "kv-app", "dependency", ("dependency", "dependent"))
    goal = every_kind.goals[0]
    assert goal.relation is not None
    every_kind = every_kind.model_copy(
        update={
            "goals": (
                goal.model_copy(
                    update={
                        "relation": goal.relation.model_copy(
                            update={"scope": RelationScope.ALL_KINDS}
                        )
                    }
                ),
            )
        }
    )
    assert question.stated is SubjectRole.DEPENDENCY and question.mutual is False
    assert either == ()
    assert direction_questions((every_kind,), utterance=uses, descriptors=descriptors) == ()
    # Peering is mutual, but connectivity also has directed links, so the reader is asked.
    (peering,) = reciprocal
    assert peering.mutual is True


def test_the_reader_confirms_only_the_role_the_form_states() -> None:
    question = DirectionQuestion(
        "g1",
        "kv-app",
        RelationSense.DEPENDENCY,
        SubjectRole.DEPENDENT,
        SubjectRole.DEPENDENCY,
        SubjectRole.DEPENDENCY,
    )

    assert direction_reasons((question,), ({"reading": "second"},)) == ()
    assert direction_reasons((question,), ({"reading": "first"},)) == (
        "review_direction_differs:g1",
    )
    assert direction_reasons((question,), ({"reading": "unclear"},)) == (
        "review_direction_unclear:g1",
    )
    assert direction_reasons((question,), (None,)) == ("review_direction_unavailable:g1",)
    assert direction_reasons((question,), ({"reading": "either"},)) == (
        "review_direction_unclear:g1",
    )
    mutual = DirectionQuestion(
        "g1",
        "vnet-hub",
        RelationSense.CONNECTIVITY,
        SubjectRole.SENDER,
        SubjectRole.RECEIVER,
        SubjectRole.SENDER,
        mutual=True,
    )
    assert direction_reasons((mutual,), ({"reading": "either"},)) == ()
    assert direction_reasons((question,), ({"reading": "both"},)) == (
        "review_direction_unavailable:g1",
    )
    with pytest.raises(ValueError, match="cover every"):
        direction_reasons((question,), ())
    assert direction_schema()["properties"]["reading"]["enum"] == [
        "first",
        "second",
        "either",
        "unclear",
    ]


async def test_the_other_family_reads_a_masked_question_without_the_choice() -> None:
    identifier = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-app/providers/"
        "Microsoft.KeyVault/vaults/kv-app"
    )
    utterance = f"What uses {identifier}?"
    sent: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((str(request.url), json.loads(request.content)))
        content = {"reading": "second"}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    def adapter(direction: bool, reader: str | None = None) -> AzureOpenAIQuestionFormModel:
        return AzureOpenAIQuestionFormModel(
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            config=AzureOpenAIQuestionFormConfig(
                candidates=(_target("form-model"),),
                form_system_prompt="Return the closed question form.",
                concept_system_prompt="Choose concepts.",
                extraction_candidates=(_target("review-model"),),
                direction_system_prompt="Confirm the direction." if direction else None,
                direction_candidates=(_target(reader),) if reader else (),
            ),
        )

    question = DirectionQuestion(
        "g1",
        identifier,
        RelationSense.DEPENDENCY,
        SubjectRole.DEPENDENT,
        SubjectRole.DEPENDENCY,
        SubjectRole.DEPENDENCY,
    )
    answer = await adapter(True).check_direction(
        utterance=utterance, context=(), locale="en", question=question
    )
    unconfigured = await adapter(False).check_direction(
        utterance=utterance, context=(), locale="en", question=question
    )

    assert answer == {"reading": "second"} and unconfigured is None
    (url, body) = sent[0]
    assert "review-model" in url
    payload = json.loads(body["messages"][-1]["content"])
    assert set(payload) == {"utterance", "locale", "anchor", "sense", "first", "second"}
    assert "managedClusters" not in json.dumps(body) and "00000000-0000" not in json.dumps(body)
    assert payload["anchor"] == "⟦ID1⟧" and len(sent) == 1
    await adapter(True, "reasoning-model").check_direction(
        utterance=utterance, context=(), locale="en", question=question
    )
    assert "reasoning-model" in sent[1][0]
    # A tie-break reader is neither the first reader's family nor the proposer's: the
    # extractor's when the reasoning model read first, and none when the extractor did.
    await adapter(True, "reasoning-model").check_direction(
        utterance=utterance, context=(), locale="en", question=question, tiebreak=True
    )
    unasked = await adapter(True).check_direction(
        utterance=utterance, context=(), locale="en", question=question, tiebreak=True
    )
    assert "review-model" in sent[2][0] and unasked is None and len(sent) == 3
    tiebreak_payload = json.loads(sent[2][1]["messages"][-1]["content"])
    assert set(tiebreak_payload) == {"utterance", "locale", "anchor", "sense", "first", "second"}


def test_the_direction_prompt_composes_within_its_budget() -> None:
    registry = FileSystemPromptRegistry(ROOT / "rule-catalog")

    composed = compose_static_selection(registry.resolve("semantic.direction_check"))

    assert composed.system_text


def _connectivity_form(utterance: str) -> Any:
    from fdai.core.conversation.semantic_reasoning_form import SemanticQuestionForm

    start = utterance.index("aks-app")
    cue = utterance.index("connected to")
    return SemanticQuestionForm.model_validate(
        {
            "mentions": [
                {
                    "id": "m1",
                    "form": "name",
                    "domain": "instance",
                    "span": {"start": start, "end": start + len("aks-app")},
                }
            ],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "traverse",
                    "subject": "m1",
                    "subject_scope": "anchor",
                    "relation": {
                        "sense": "connectivity",
                        "anchor_role": "sender",
                        "result_role": "receiver",
                        "cue": {"start": cue, "end": cue + len("connected to")},
                    },
                    "cue": {"start": 0, "end": 4},
                    "confidence": 0.9,
                }
            ],
        }
    )


async def test_a_disputed_direction_holds_without_a_tiebreak_reader() -> None:
    from fdai.core.conversation.semantic_reasoning_direction import settle_directions

    utterance = "What is connected to aks-app?"
    # Connectivity has a directed and a reciprocal LinkType, so either is a possible reading.
    descriptors = (
        {"kind": "link", "semantic_traits": ["connectivity"]},
        {"kind": "link", "semantic_traits": ["connectivity", "reciprocal"]},
    )
    asked: list[bool] = []

    async def check(question: Any, tiebreak: bool) -> dict[str, Any] | None:
        asked.append(tiebreak)
        return {"reading": "second"}

    settled = await settle_directions(
        _connectivity_form(utterance), utterance=utterance, descriptors=descriptors, check=check
    )

    assert settled.reasons == ("review_direction_differs:g1",)
    assert settled.swapped == ()
    assert asked == [False]
