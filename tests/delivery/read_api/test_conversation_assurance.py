from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.conversation_assurance import (
    AssessmentRecord,
    AssuranceDecision,
    AssuranceVerdict,
    InMemoryConversationAssuranceLedger,
    assurance_principal_scope,
)
from fdai.delivery.read_api.routes.conversation_assurance import (
    make_conversation_assurance_routes,
)

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


async def _authorize(_request: object) -> str:
    return "operator-1"


def _assessment() -> AssessmentRecord:
    return AssessmentRecord(
        assessment_id="assessment-1",
        turn_id="turn-1",
        conversation_id="conversation-1",
        principal_scope=assurance_principal_scope("operator-1"),
        question_digest="q" * 64,
        answer_digest="a" * 64,
        evidence_manifest_digest="e" * 64,
        rubric_version="1.0.0",
        model_set_digest="m" * 64,
        decision=AssuranceDecision(
            verdict=AssuranceVerdict.FAIL,
            content_score=25.0,
            confidence=1.0,
            reasons=("verification_failed",),
        ),
        assessed_at=_NOW,
    )


def _client(ledger: InMemoryConversationAssuranceLedger) -> TestClient:
    app = Starlette(
        routes=list(make_conversation_assurance_routes(ledger=ledger, authorize=_authorize))
    )
    return TestClient(app, raise_server_exceptions=False)


def test_projection_and_idempotent_dispute() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    asyncio.run(ledger.append_assessment(_assessment()))
    with _client(ledger) as client:
        projection = client.get("/conversation-assurance")
        first = client.post(
            "/conversation-assurance/assessment-1/disputes",
            json={
                "reason": "wrong_fact",
                "detail": "The answer contradicts the observed state.",
                "idempotency_key": "feedback-1",
            },
        )
        duplicate = client.post(
            "/conversation-assurance/assessment-1/disputes",
            json={
                "reason": "wrong_fact",
                "detail": "The answer contradicts the observed state.",
                "idempotency_key": "feedback-1",
            },
        )

    assert projection.status_code == 200
    assert projection.json()["summary"]["fail"] == 1
    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["dispute"]["reported_at"] == first.json()["dispute"]["reported_at"]


def test_cross_scope_assessment_is_not_visible() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    other = replace(
        _assessment(),
        principal_scope=assurance_principal_scope("operator-2"),
    )
    asyncio.run(ledger.append_assessment(other))
    with _client(ledger) as client:
        response = client.get("/conversation-assurance")

    assert response.json()["summary"]["total"] == 0


def test_dispute_rejects_unsupported_reason() -> None:
    ledger = InMemoryConversationAssuranceLedger()
    asyncio.run(ledger.append_assessment(_assessment()))
    with _client(ledger) as client:
        response = client.post(
            "/conversation-assurance/assessment-1/disputes",
            json={
                "reason": "approve",
                "detail": "This must not become an approval surface.",
                "idempotency_key": "feedback-2",
            },
        )

    assert response.status_code == 400
