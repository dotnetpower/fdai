"""Focused tests for principal-scoped conversation assurance projections."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.conversation_assurance_reader import (
    ConversationAssuranceReader,
    ConversationAssuranceReaderConfig,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    ConversationUnavailableError,
    OutboxReceipt,
    PrincipalScope,
)


class RecordingFallback:
    """Fail tests that unexpectedly delegate an assurance operation."""

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        return ConversationResponse(body={"operation": query.operation})

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        raise AssertionError(proposal.operation)

    async def open(self, request: ConversationStreamRequest):
        raise AssertionError(request.operation)


def _query(operation: str, assessment_id: str | None = None) -> ConversationQuery:
    return ConversationQuery(
        operation=operation,
        scope=PrincipalScope("operator-a"),
        path_params={} if assessment_id is None else {"assessment_id": assessment_id},
    )


async def test_assurance_list_and_detail_project_principal_rows(monkeypatch: Any) -> None:
    now = datetime(2026, 8, 27, tzinfo=UTC)
    assessment = {
        "assessment_id": "assessment-1",
        "turn_id": "turn-1",
        "conversation_id": "conversation-1",
        "rubric_version": "1.0.0",
        "state": "completed",
        "decision": {
            "verdict": "pass",
            "content_score": 96.0,
            "confidence": 0.9,
            "criteria": [],
            "reasons": [],
            "evaluator_identities": ["judge-a", "judge-b"],
            "disagreement": False,
            "model_calls": 2,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "cost_microusd": 15,
        },
        "assessed_at": now,
    }
    dispute = {
        "dispute_id": "dispute-1",
        "assessment_id": "assessment-1",
        "reason": "wrong_fact",
        "detail": "The cited value was stale.",
        "evidence_refs": ["audit:1"],
        "reported_at": now,
    }

    async def fetch(
        self: ConversationAssuranceReader,
        statement: str,
        parameters: tuple[object, ...],
    ) -> list[dict[str, object]]:
        del self
        assert parameters[0] == "operator-a"
        if "COUNT(*) AS total" in statement:
            return [
                {
                    "total": 1,
                    "pass": 1,
                    "fail": 0,
                    "inconclusive": 0,
                    "deferred": 0,
                    "average_content_score": 96.0,
                    "model_calls": 2,
                    "cost_microusd": 15,
                    "disputes": 1,
                }
            ]
        if "conversation_assurance_dispute" in statement:
            return [dispute]
        return [assessment]

    monkeypatch.setattr(ConversationAssuranceReader, "_fetch_all", fetch)
    reader = ConversationAssuranceReader(
        ConversationAssuranceReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    listing = await reader.read(_query("assurance.list"))
    detail = await reader.read(_query("assurance.get", "assessment-1"))

    assert isinstance(listing.body, dict)
    assert listing.body["summary"]["total"] == 1
    assert listing.body["summary"]["pass"] == 1
    assert listing.body["summary"]["disputes"] == 1
    assert listing.body["assessments"][0]["assessment_id"] == "assessment-1"
    assert isinstance(detail.body, dict)
    assert detail.body["assessment"]["assessment_id"] == "assessment-1"
    assert detail.body["turn"] == {
        "available": False,
        "question": None,
        "answer": None,
    }


async def test_unknown_conversation_operation_delegates() -> None:
    reader = ConversationAssuranceReader(
        ConversationAssuranceReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    response = await reader.read(_query("conversation.search"))

    assert response.body == {"operation": "conversation.search"}


async def test_malformed_assurance_decision_fails_closed(monkeypatch: Any) -> None:
    async def fetch(
        self: ConversationAssuranceReader,
        statement: str,
        parameters: tuple[object, ...],
    ) -> list[dict[str, object]]:
        del self, parameters
        if "COUNT(*) AS total" in statement:
            return [
                {
                    "total": 1,
                    "pass": 0,
                    "fail": 0,
                    "inconclusive": 0,
                    "deferred": 0,
                    "average_content_score": None,
                    "model_calls": 0,
                    "cost_microusd": 0,
                    "disputes": 0,
                }
            ]
        if "conversation_assurance_dispute" in statement:
            return []
        return [
            {
                "assessment_id": "assessment-1",
                "turn_id": "turn-1",
                "conversation_id": "conversation-1",
                "state": "completed",
                "decision": {},
                "assessed_at": datetime(2026, 8, 27, tzinfo=UTC),
            }
        ]

    monkeypatch.setattr(ConversationAssuranceReader, "_fetch_all", fetch)
    reader = ConversationAssuranceReader(
        ConversationAssuranceReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    with pytest.raises(ConversationUnavailableError, match="missing fields"):
        await reader.read(_query("assurance.list"))
