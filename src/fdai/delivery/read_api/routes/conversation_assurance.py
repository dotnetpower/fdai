"""Principal-scoped projection and dispute intake for answer assurance."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.conversation_assurance import (
    AssessmentRecord,
    ConversationAssuranceLedger,
    DisputeReason,
    DisputeRecord,
    assurance_principal_scope,
)
from fdai.shared.providers.user_context import ConversationHistoryStore, ConversationTurnRole

_MAX_BODY_BYTES = 8_000
_MAX_DETAIL_CHARS = 1_000


def make_conversation_assurance_routes(
    *,
    ledger: ConversationAssuranceLedger,
    authorize: Callable[[Request], Awaitable[str]],
    conversation_store: ConversationHistoryStore | None = None,
) -> tuple[Route, ...]:
    async def get_assurance(request: Request) -> Response:
        principal_id = await authorize(request)
        scope = assurance_principal_scope(principal_id)
        limit = _limit(request.query_params.get("limit"))
        assessments = await ledger.list_assessments(principal_scope=scope, limit=limit)
        disputes = await ledger.list_disputes(principal_scope=scope, limit=1_000)
        return JSONResponse(_projection(assessments, disputes))

    async def get_assessment_detail(request: Request) -> Response:
        principal_id = await authorize(request)
        scope = assurance_principal_scope(principal_id)
        assessment_id = request.path_params["assessment_id"]
        assessment = await ledger.get_assessment(
            principal_scope=scope,
            assessment_id=assessment_id,
        )
        if assessment is None:
            raise HTTPException(status_code=404, detail="assessment was not found")
        question: str | None = None
        answer: str | None = None
        if conversation_store is not None:
            turns = await conversation_store.list_turns(
                principal_id=principal_id,
                conversation_id=assessment.conversation_id,
                limit=200,
            )
            assistant = next((item for item in turns if item.turn_id == assessment.turn_id), None)
            if assistant is not None and assistant.role is ConversationTurnRole.ASSISTANT:
                answer = assistant.content
                operators = [
                    item
                    for item in turns
                    if item.role is ConversationTurnRole.OPERATOR
                    and item.turn_index < assistant.turn_index
                ]
                if operators:
                    question = max(operators, key=lambda item: item.turn_index).content
        return JSONResponse(
            {
                "assessment": _assessment_mapping(assessment),
                "turn": {
                    "available": answer is not None,
                    "question": question,
                    "answer": answer,
                },
            }
        )

    async def post_dispute(request: Request) -> Response:
        principal_id = await authorize(request)
        scope = assurance_principal_scope(principal_id)
        assessment_id = request.path_params["assessment_id"]
        assessment = await ledger.get_assessment(
            principal_scope=scope,
            assessment_id=assessment_id,
        )
        if assessment is None:
            raise HTTPException(status_code=404, detail="assessment was not found")
        body = await _json_body(request)
        reason = _reason(body.get("reason"))
        detail = body.get("detail")
        idempotency_key = body.get("idempotency_key")
        if not isinstance(detail, str) or not 1 <= len(detail.strip()) <= _MAX_DETAIL_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"detail MUST contain 1..{_MAX_DETAIL_CHARS} characters",
            )
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
            raise HTTPException(
                status_code=400,
                detail="idempotency_key MUST contain 1..128 characters",
            )
        evidence_refs = _evidence_refs(body.get("evidence_refs"))
        allowed_refs = {
            ref for criterion in assessment.decision.criteria for ref in criterion.evidence_refs
        }
        if not set(evidence_refs).issubset(allowed_refs):
            raise HTTPException(
                status_code=400,
                detail="evidence_refs MUST be a subset of assessed evidence",
            )
        dispute = DisputeRecord(
            dispute_id=_dispute_id(assessment_id, scope, idempotency_key),
            assessment_id=assessment_id,
            principal_scope=scope,
            reported_by=scope,
            reason=reason,
            detail=detail.strip(),
            evidence_refs=evidence_refs,
            reported_at=datetime.now(tz=UTC),
        )
        try:
            created = await ledger.append_dispute(dispute)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail="idempotency_key was reused with different dispute content",
            ) from exc
        returned = dispute
        if not created:
            known = await ledger.list_disputes(
                principal_scope=scope,
                assessment_id=assessment_id,
                limit=1_000,
            )
            returned = next(
                (item for item in known if item.dispute_id == dispute.dispute_id),
                dispute,
            )
        return JSONResponse(
            {"dispute": _dispute_mapping(returned), "duplicate": not created},
            status_code=201 if created else 200,
        )

    return (
        Route("/conversation-assurance", get_assurance, methods=["GET"]),
        Route(
            "/conversation-assurance/{assessment_id:str}",
            get_assessment_detail,
            methods=["GET"],
        ),
        Route(
            "/conversation-assurance/{assessment_id:str}/disputes",
            post_dispute,
            methods=["POST"],
        ),
    )


def _projection(
    assessments: tuple[AssessmentRecord, ...],
    disputes: tuple[DisputeRecord, ...],
) -> dict[str, object]:
    verdicts = Counter(item.decision.verdict.value for item in assessments)
    states = Counter(item.state.value for item in assessments)
    score_values = [
        item.decision.content_score
        for item in assessments
        if item.decision.verdict.value != "inconclusive"
    ]
    return {
        "source": "conversation-assurance-ledger",
        "read_only": True,
        "disputes_available": True,
        "policy_mutations_available": False,
        "summary": {
            "total": len(assessments),
            "pass": verdicts["pass"],
            "fail": verdicts["fail"],
            "inconclusive": verdicts["inconclusive"],
            "deferred": states["deferred"],
            "disputes": len(disputes),
            "average_content_score": (
                sum(score_values) / len(score_values) if score_values else None
            ),
            "model_calls": sum(item.decision.model_calls for item in assessments),
            "cost_microusd": sum(item.decision.cost_microusd for item in assessments),
        },
        "assessments": [_assessment_mapping(item) for item in assessments],
        "disputes": [_dispute_mapping(item) for item in disputes],
    }


def _assessment_mapping(item: AssessmentRecord) -> dict[str, object]:
    return {
        "assessment_id": item.assessment_id,
        "turn_id": item.turn_id,
        "conversation_id": item.conversation_id,
        "state": item.state.value,
        "verdict": item.decision.verdict.value,
        "content_score": item.decision.content_score,
        "confidence": item.decision.confidence,
        "criteria": [
            {
                "criterion": score.criterion.value,
                "score": score.score,
                "rationale": score.rationale,
                "evidence_refs": list(score.evidence_refs),
            }
            for score in item.decision.criteria
        ],
        "reasons": list(item.decision.reasons),
        "evaluator_identities": list(item.decision.evaluator_identities),
        "disagreement": item.decision.disagreement,
        "model_calls": item.decision.model_calls,
        "prompt_tokens": item.decision.prompt_tokens,
        "completion_tokens": item.decision.completion_tokens,
        "cost_microusd": item.decision.cost_microusd,
        "rubric_version": item.rubric_version,
        "assessed_at": item.assessed_at.isoformat(),
    }


def _dispute_mapping(item: DisputeRecord) -> dict[str, object]:
    return {
        "dispute_id": item.dispute_id,
        "assessment_id": item.assessment_id,
        "reason": item.reason.value,
        "detail": item.detail,
        "evidence_refs": list(item.evidence_refs),
        "reported_at": item.reported_at.isoformat(),
    }


async def _json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    return body


def _reason(value: object) -> DisputeReason:
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="reason is unsupported")
    try:
        return DisputeReason(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="reason is unsupported") from exc


def _evidence_refs(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if (
        not isinstance(value, list)
        or len(value) > 64
        or not all(isinstance(item, str) and 1 <= len(item) <= 512 for item in value)
    ):
        raise HTTPException(status_code=400, detail="evidence_refs MUST be a bounded string array")
    return tuple(value)


def _limit(value: str | None) -> int:
    try:
        limit = int(value or "100")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="limit MUST be an integer") from exc
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit MUST be in [1, 200]")
    return limit


def _dispute_id(assessment_id: str, scope: str, idempotency_key: str) -> str:
    digest = hashlib.sha256("\0".join((assessment_id, scope, idempotency_key)).encode()).hexdigest()
    return f"conversation-dispute:{digest}"


__all__ = ["make_conversation_assurance_routes"]
