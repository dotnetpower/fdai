"""Build content-addressed Bragi turn and handoff event payloads."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .bragi_models import Turn


def turn_event_payload(
    *,
    session_id: str,
    turn: Turn,
    contributor_limit: int,
) -> dict[str, Any]:
    """Return the bounded ``object.turn`` payload for an operator session."""
    session_digest = hashlib.sha256(session_id.encode()).hexdigest()
    question_digest = hashlib.sha256(turn.question.encode()).hexdigest()
    answer_json = json.dumps(
        turn.answer,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    answer_digest = hashlib.sha256(answer_json.encode()).hexdigest()
    trace_ref = str(turn.answer.get("trace_ref") or turn.answer.get("correlation_id") or session_id)
    turn_key = f"{session_digest}:{turn.turn_index}"
    turn_id = f"turn-{hashlib.sha256(turn_key.encode()).hexdigest()[:32]}"
    contributors = turn.answer.get("contributors")
    safe_contributors = (
        [item for item in contributors[:contributor_limit] if isinstance(item, str)]
        if isinstance(contributors, list)
        else []
    )
    return {
        "producer_principal": "Bragi",
        "id": turn_id,
        "turn_id": turn_id,
        "correlation_id": trace_ref,
        "idempotency_key": f"turn:{session_digest}:{turn.turn_index}",
        "session_id": session_id,
        "turn_index": turn.turn_index,
        "question_ref": f"bragi-session:sha256:{session_digest}:turn:{turn.turn_index}:question",
        "question_sha256": question_digest,
        "primary_agent": turn.primary_agent or "Bragi",
        "contributors": safe_contributors,
        "answer_ref": f"bragi-session:sha256:{session_digest}:turn:{turn.turn_index}:answer",
        "answer_sha256": answer_digest,
        "score_breakdown": {
            "scores": dict(turn.decision.scores),
            "tie_break": turn.decision.tie_break,
            "method": turn.decision.method,
            "semantic_score": turn.decision.semantic_score,
            "semantic_margin": turn.decision.semantic_margin,
            "provider_status": turn.decision.provider_status,
        },
        "trace_ref": trace_ref,
    }


def a2a_turn_event_payload(
    *,
    requester: str,
    target_agent: str,
    question: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    """Return the content-addressed ``object.turn`` payload for agent introspection."""
    question_digest = hashlib.sha256(question.encode()).hexdigest()
    answer_json = json.dumps(
        response,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    answer_digest = hashlib.sha256(answer_json.encode()).hexdigest()
    trace_ref = str(response.get("trace_ref") or "")
    identity = hashlib.sha256(
        f"{requester}\0{target_agent}\0{trace_ref}\0{question_digest}".encode()
    ).hexdigest()
    turn_id = f"turn-{identity[:32]}"
    session_digest = hashlib.sha256(f"{requester}:{target_agent}".encode()).hexdigest()
    return {
        "producer_principal": "Bragi",
        "id": turn_id,
        "turn_id": turn_id,
        "correlation_id": trace_ref or turn_id,
        "idempotency_key": f"a2a-turn:{identity}",
        "session_id": f"a2a-{session_digest[:32]}",
        "turn_index": 0,
        "question_ref": f"a2a:sha256:{question_digest}:question",
        "question_sha256": question_digest,
        "primary_agent": target_agent,
        "contributors": [],
        "answer_ref": f"a2a:sha256:{answer_digest}:answer",
        "answer_sha256": answer_digest,
        "score_breakdown": {"requester": requester, "routing": "direct_a2a"},
        "trace_ref": trace_ref or turn_id,
    }


def handoff_event_payload(
    *,
    session_id: str,
    question: str,
    turn_index: int,
    reason: str,
) -> dict[str, Any]:
    """Return the content-free ``object.handoff-escalation`` payload."""
    normalized = " ".join(question.split()).casefold()
    selector_digest = hashlib.sha256(normalized.encode()).hexdigest()
    escalation_id = hashlib.sha256(
        f"{session_id}\0{turn_index}\0{reason}\0{selector_digest}".encode()
    ).hexdigest()
    return {
        "producer_principal": "Bragi",
        "id": f"handoff-{escalation_id[:32]}",
        "escalation_id": f"handoff-{escalation_id[:32]}",
        "correlation_id": session_id,
        "idempotency_key": f"handoff:{escalation_id}",
        "emitting_agent": "Bragi",
        "intent_category": reason,
        "normalized_selector": f"sha256:{selector_digest}",
        "failure_reason_code": reason,
        "emitted_at": datetime.now(UTC).isoformat(),
    }
