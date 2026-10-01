"""Shared helpers for Bragi conversation and turn runtime mixins."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.agents._framework.bragi_constants import (
    _BRAGI_STATE_PREFIX,
    _INTENT_TRAINING_EVIDENCE_PREFIX,
    _MAX_QUESTION_CHARS,
    _MAX_SESSION_TURNS,
    _TURN_OUTBOX_CLAIM_LEASE,
    _TURN_OUTBOX_TOMBSTONE_RETENTION,
)
from fdai.agents._framework.bragi_models import ConversationSession, Turn
from fdai.agents._framework.introspection import durable_evidence_refs
from fdai.agents._framework.outbox_publication import claim_expired
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.shared.providers.user_context import UserPreferenceRecord


def _validate_question(question: str) -> None:
    if len(question) > _MAX_QUESTION_CHARS:
        raise ValueError("question MUST be at most 2000 characters")


def _locale_is_supported(locale: object) -> bool:
    return locale == "en" or locale == "ko"


def _validate_tool_answer_envelope(agent_name: str, answer: Mapping[str, Any]) -> str | None:
    facts = answer.get("facts")
    if not isinstance(facts, Mapping):
        return "tool_answer_invalid"
    if not durable_evidence_refs(facts.get("evidence_refs"), agent_name=agent_name):
        return "tool_evidence_incomplete"
    results = answer.get("conversation_tool_results")
    if not isinstance(results, list) or not results:
        return "tool_evidence_incomplete"
    for result in results:
        if not isinstance(result, Mapping):
            return "tool_evidence_incomplete"
        if result.get("status") != "ok":
            return str(result.get("reason") or "tool_evidence_incomplete")
        count = result.get("evidence_ref_count")
        if not isinstance(count, int) or count <= 0:
            return "tool_evidence_incomplete"
    return None


def _next_turn_index(session: ConversationSession) -> int:
    return session.turns[-1].turn_index + 1 if session.turns else 0


def _append_turn(session: ConversationSession, turn: Turn) -> None:
    session.turns.append(turn)
    session.next_turn_index = max(session.next_turn_index, turn.turn_index + 1)
    if len(session.turns) > _MAX_SESSION_TURNS:
        del session.turns[:-_MAX_SESSION_TURNS]


def _session_digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _session_ref(session_id: str, generation: int) -> str:
    return f"sha256:{hashlib.sha256(f'{session_id}\0{generation}'.encode()).hexdigest()}"


def _principal_scope(user_id: str) -> str:
    return f"sha256:{hashlib.sha256(user_id.encode('utf-8')).hexdigest()}"


def _prior_turns_ref(session: ConversationSession, *, limit: int = 8) -> str:
    if not session.turns:
        return ""
    principal_scope = _principal_scope(session.user_id)
    session_ref = _session_ref(session.session_id, session.generation)
    material = [
        {
            "turn_index": turn.turn_index,
            "question_sha256": hashlib.sha256(turn.question.encode("utf-8")).hexdigest(),
            "answer_sha256": hashlib.sha256(
                repr(sorted(turn.answer.items())).encode("utf-8")
            ).hexdigest(),
        }
        for turn in session.turns[-limit:]
    ]
    digest = hashlib.sha256(repr((principal_scope, session_ref, material)).encode()).hexdigest()
    return f"bragi-prior-turns:{principal_scope}:{session_ref}:sha256:{digest}"


def _resource_type_from_proposal(judgment: SemanticJudgmentProposal | None) -> str:
    if judgment is None:
        return "unknown"
    for target in judgment.targets:
        if target.kind in {"object_type", "resource_type"}:
            return str(target.canonical_value or target.value)
    for target in judgment.targets:
        if target.kind == "resource":
            return "Resource"
    return "unknown"


def _session_sequence_key(session_id: str) -> str:
    return f"{_BRAGI_STATE_PREFIX}/session/{_session_digest(session_id)}/sequence"


def _intent_training_stage_key(
    *,
    contract_version: str,
    corpus_digest: str,
    candidate_digest: str,
    stage: str,
) -> str:
    key = stable_idempotency_key(
        "bragi-intent-training-stage",
        contract_version,
        corpus_digest,
        candidate_digest,
        stage,
    )
    return f"{_INTENT_TRAINING_EVIDENCE_PREFIX}{key}"


def _turn_outbox_key(session_ref: str, turn_index: int, generation: int | None = None) -> str:
    del generation
    digest = hashlib.sha256(session_ref.encode("utf-8")).hexdigest()
    return f"{_BRAGI_STATE_PREFIX}/turn-outbox/{digest}/{turn_index:020d}"


def _turn_claim_expired(row: Mapping[str, Any], now: datetime) -> bool:
    return claim_expired(
        claimed_at=row.get("claimed_at"),
        now=now,
        lease=_TURN_OUTBOX_CLAIM_LEASE,
    )


def _published_turn_outbox_tombstone(stored: Mapping[str, Any], *, revision: int) -> dict[str, Any]:
    payload = stored.get("payload")
    payload_digest = (
        _payload_digest(payload)
        if isinstance(payload, Mapping)
        else str(stored.get("payload_digest") or "")
    )
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "status": "published",
        "session_ref": str(stored.get("session_ref") or ""),
        "turn_index": int(stored.get("turn_index") or 0),
        "payload_digest": payload_digest,
        "retention_window": str(_TURN_OUTBOX_TOMBSTONE_RETENTION),
    }


def _payload_digest(payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"sha256:{digest}"


def _preference_from_index_row(row: Mapping[str, Any]) -> UserPreferenceRecord:
    updated_at_raw = row.get("updated_at")
    updated_at = datetime.fromisoformat(updated_at_raw) if isinstance(updated_at_raw, str) else None
    answer_intent_detail = row.get("answer_intent_detail")
    answer_intent_format = row.get("answer_intent_format")
    return UserPreferenceRecord(
        principal_id=str(row["principal_id"]),
        locale=str(row.get("locale") or "en"),
        verbosity=str(row.get("verbosity") or "concise"),
        answer_detail=str(row.get("answer_detail") or "standard"),
        answer_format=str(row.get("answer_format") or "prose"),
        answer_preferences_enabled=bool(row.get("answer_preferences_enabled", True)),
        answer_intent_detail=(
            dict(answer_intent_detail) if isinstance(answer_intent_detail, Mapping) else {}
        ),
        answer_intent_format=(
            dict(answer_intent_format) if isinstance(answer_intent_format, Mapping) else {}
        ),
        timezone=str(row["timezone"]) if isinstance(row.get("timezone"), str) else None,
        share_with_learner=bool(row.get("share_with_learner", False)),
        revision=int(row.get("revision", 0)),
        updated_at=updated_at,
    )
