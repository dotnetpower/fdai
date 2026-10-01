"""Default-off verified answer authoring ports and fail-closed review flow."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fdai.core.conversation.model_evidence_view import model_evidence_view_from_tables
from fdai.core.conversation.semantic_reasoning_claims import GoalEvidence, GoalEvidenceStatus
from fdai.core.conversation.verified_answer_authoring import VerifiedAnswerAuthoringService
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai_service_contracts.answer_claims import ComposedAnswer
from fdai_service_contracts.ontology_query import EvidenceAuthority

RELEASE_DIGEST = "sha256:" + "a" * 64


@dataclass(slots=True)
class _Author:
    family: str
    replies: list[ComposedAnswer | None]
    retry_reasons: list[tuple[str, ...]]

    async def author(
        self,
        *,
        utterance: str,
        evidence_view,
        retry_reasons: tuple[str, ...] = (),
    ) -> ComposedAnswer | None:
        del utterance
        assert "resource_id" not in evidence_view.canonical_json()
        self.retry_reasons.append(retry_reasons)
        return self.replies.pop(0)


@dataclass(slots=True)
class _Reviewer:
    family: str
    decisions: list[bool]

    async def review(self, *, answer: ComposedAnswer, evidence_view) -> bool:
        del answer
        assert "resource_id" not in evidence_view.canonical_json()
        return self.decisions.pop(0)


def _answer(text: str = "It is running.") -> ComposedAnswer:
    return ComposedAnswer.model_validate(
        {
            "text": text,
            "claims": [
                {
                    "id": "c1",
                    "kind": "state",
                    "span": {"start": 0, "end": len(text)},
                    "refs": [{"goal": "g1", "node": "state", "row": "r1", "field": "status"}],
                    "literals": [
                        {
                            "span": {"start": 6, "end": 13},
                            "value": "running",
                            "ref": {
                                "goal": "g1",
                                "node": "state",
                                "row": "r1",
                                "field": "status",
                            },
                        }
                    ],
                    "rows": ["r1"],
                }
            ],
        }
    )


def _evidence() -> tuple[GoalEvidence, ...]:
    return (
        GoalEvidence(
            goal_id="g1",
            status=GoalEvidenceStatus.VERIFIED,
            tables={
                "state": QueryTable(
                    rows=(
                        QueryRow.from_values(
                            "r1",
                            {
                                "status": "running",
                                "resource_id": "hidden",
                                "provider_body": {"raw": "hidden"},
                            },
                        ),
                    ),
                    complete=True,
                )
            },
        ),
    )


def _view():
    return model_evidence_view_from_tables(
        tuple(goal.tables["state"] for goal in _evidence()),
        authorities=(EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
        release_digest=RELEASE_DIGEST,
    )


def test_author_and_reviewer_families_must_differ() -> None:
    with pytest.raises(ValueError, match="families"):
        VerifiedAnswerAuthoringService(
            author=_Author("same", [_answer()], []),
            reviewer=_Reviewer("same", [True]),
        )


async def test_authoring_accepts_claims_only_after_vclaim_and_review() -> None:
    service = VerifiedAnswerAuthoringService(
        author=_Author("author-family", [_answer()], []),
        reviewer=_Reviewer("review-family", [True]),
    )

    result = await service.author_answer(
        utterance="What is the state?",
        evidence_view=_view(),
        evidence=_evidence(),
    )

    assert result.answer is not None
    assert result.held_reason is None
    assert result.attempts == 1


async def test_authoring_retries_once_on_vclaim_or_review_failure_then_holds() -> None:
    bad = _answer("It is stopped.")
    good = _answer()
    author = _Author("author-family", [bad, good], [])
    service = VerifiedAnswerAuthoringService(
        author=author,
        reviewer=_Reviewer("review-family", [False]),
    )

    result = await service.author_answer(
        utterance="What is the state?",
        evidence_view=_view(),
        evidence=_evidence(),
    )

    assert result.answer is None
    assert result.held_reason == "verified_answer_review_rejected"
    assert result.attempts == 2
    assert author.retry_reasons[1]
