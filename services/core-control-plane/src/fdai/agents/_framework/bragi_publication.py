"""Build content-addressed Bragi turn and handoff event payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.post_turn_review import (
    PostTurnBodyConsent,
    PostTurnReviewInputWire,
)
from fdai_service_contracts.post_turn_review import (
    post_turn_review_event_payload as shared_post_turn_review_event_payload,
)

from fdai.core.learning import PostTurnReviewInput, review_input_to_mapping
from fdai.shared.providers.user_context import UserPreferenceRecord

from .bragi_models import ConversationSession, Turn
from .introspection import canonical_json
from .outbox_publication import (
    PublicationClaim,
    await_bounded_publication,
    claim_expired,
    claim_matches,
    new_publication_claim_owner,
    publish_claimed_outbox,
)

_BRAGI_PUBLICATION_OUTBOX_PREFIX = "pantheon/bragi/publication-outbox/"
_BRAGI_PUBLICATION_OUTBOX_SCAN_LIMIT = 5_000
_BRAGI_PUBLICATION_TOMBSTONE_RETENTION = 1_024
_BRAGI_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)


def conversation_event_payload(
    session: ConversationSession, *, status: str = "active"
) -> dict[str, Any]:
    """Return a content-addressed Conversation without exposing user identity."""
    session_digest = hashlib.sha256(
        f"{session.session_id}\0{session.generation}".encode()
    ).hexdigest()
    principal_digest = hashlib.sha256(session.user_id.encode()).hexdigest()
    conversation_id = f"conversation-{session_digest[:32]}"
    payload = {
        "producer_principal": "Bragi",
        "id": conversation_id,
        "conversation_id": conversation_id,
        "correlation_id": conversation_id,
        "idempotency_key": f"conversation:{session_digest}",
        "session_ref": f"sha256:{session_digest}",
        "principal_scope": f"sha256:{principal_digest}",
        "status": status,
    }
    if session.created_at is not None:
        payload["created_at"] = session.created_at.isoformat()
    if session.last_active_at is not None:
        payload["last_active_at"] = session.last_active_at.isoformat()
    if session.ended_at is not None:
        payload["ended_at"] = session.ended_at.isoformat()
    return payload


def user_preference_event_payload(preference: UserPreferenceRecord) -> dict[str, Any]:
    """Return a revision-bound preference projection from one validated record."""
    if preference.updated_at is None:
        raise ValueError("published UserPreference requires updated_at")
    principal_digest = hashlib.sha256(preference.principal_id.encode()).hexdigest()
    body = {
        "locale": preference.locale,
        "verbosity": preference.verbosity,
        "answer_detail": preference.answer_detail,
        "answer_format": preference.answer_format,
        "answer_preferences_enabled": preference.answer_preferences_enabled,
        "answer_intent_detail": dict(preference.answer_intent_detail),
        "answer_intent_format": dict(preference.answer_intent_format),
        "timezone": preference.timezone,
        "share_with_learner": preference.share_with_learner,
        "revision": preference.revision,
        "updated_at": preference.updated_at.isoformat(),
    }
    body_digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "producer_principal": "Bragi",
        "id": f"user-preference-{principal_digest[:32]}",
        "correlation_id": f"preference-{principal_digest[:32]}",
        "idempotency_key": f"user-preference:{principal_digest}:{preference.revision}",
        "principal_scope": f"sha256:{principal_digest}",
        "preference_digest": f"sha256:{body_digest}",
        **body,
    }


def post_turn_review_event_payload(
    review: PostTurnReviewInput,
    *,
    preference: UserPreferenceRecord | None = None,
) -> dict[str, Any]:
    """Return the consent-filtered review envelope consumed by Norns."""
    principal_scope = (
        f"sha256:{hashlib.sha256(preference.principal_id.encode()).hexdigest()}"
        if preference is not None
        else ""
    )
    body_allowed = (
        preference is not None
        and preference.share_with_learner is True
        and principal_scope == review.principal_scope
    )
    carries_raw_body = review.operator_body is not None or review.assistant_body is not None
    if not body_allowed and (review.operator_body is not None or review.assistant_body is not None):
        review = PostTurnReviewInput(
            review_id=review.review_id,
            principal_scope=review.principal_scope,
            operator_turn_id=review.operator_turn_id,
            assistant_turn_id=review.assistant_turn_id,
            completed_at=review.completed_at,
            operator_body=None,
            assistant_body=None,
            tool_receipts=review.tool_receipts,
            validation_outcomes=review.validation_outcomes,
            explicit_corrections=review.explicit_corrections,
            evidence_refs=review.evidence_refs,
            memory_scope_kind=review.memory_scope_kind,
            memory_scope_ref=review.memory_scope_ref,
            failure_recovered=review.failure_recovered,
            procedure_fingerprint=review.procedure_fingerprint,
            repeated_procedure_count=review.repeated_procedure_count,
        )
        carries_raw_body = False
    body_consent = (
        PostTurnBodyConsent(
            share_with_learner=True,
            principal_scope=review.principal_scope,
            consent_ref=f"user-preference:{principal_scope}:{preference.revision}",
        )
        if body_allowed and carries_raw_body and preference is not None
        else None
    )
    return shared_post_turn_review_event_payload(
        PostTurnReviewInputWire.model_validate(review_input_to_mapping(review)),
        body_consent=body_consent,
    )


def turn_event_payload(
    *,
    session_id: str,
    user_id: str,
    session_generation: int,
    turn: Turn,
    contributor_limit: int,
) -> dict[str, Any]:
    """Return the bounded ``object.turn`` payload for an operator session."""
    session_digest = hashlib.sha256(f"{session_id}\0{session_generation}".encode()).hexdigest()
    principal_digest = hashlib.sha256(user_id.encode()).hexdigest()
    question_digest = hashlib.sha256(turn.question.encode()).hexdigest()
    answer_json = canonical_json(turn.answer)
    answer_digest = hashlib.sha256(answer_json.encode()).hexdigest()
    turn_key = f"{session_digest}:{turn.turn_index}"
    turn_id = f"turn-{hashlib.sha256(turn_key.encode()).hexdigest()[:32]}"
    trace_ref = str(turn.answer.get("trace_ref") or turn.answer.get("correlation_id") or turn_id)
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
        "session_ref": f"sha256:{session_digest}",
        "principal_scope": f"sha256:{principal_digest}",
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
    turn_index: int,
) -> dict[str, Any]:
    """Return the content-addressed ``object.turn`` payload for agent introspection."""
    question_digest = hashlib.sha256(question.encode()).hexdigest()
    answer_json = canonical_json(response)
    answer_digest = hashlib.sha256(answer_json.encode()).hexdigest()
    trace_ref = str(response.get("trace_ref") or "")
    identity = hashlib.sha256(
        f"{requester}\0{target_agent}\0{trace_ref}\0{question_digest}".encode()
    ).hexdigest()
    turn_id = f"turn-{identity[:32]}"
    session_digest = hashlib.sha256(f"{requester}:{target_agent}".encode()).hexdigest()
    principal_digest = hashlib.sha256(requester.encode()).hexdigest()
    return {
        "producer_principal": "Bragi",
        "id": turn_id,
        "turn_id": turn_id,
        "correlation_id": trace_ref or turn_id,
        "idempotency_key": f"a2a-turn:{identity}",
        "session_ref": f"a2a:sha256:{session_digest}",
        "principal_scope": f"sha256:{principal_digest}",
        "turn_index": turn_index,
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
    intent_category: str | None = None,
    resource_type: str = "unknown",
    primary_agent: str = "unassigned",
    failure_reason_code: str | None = None,
    emitted_at: datetime | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Return the content-free ``object.handoff-escalation`` payload."""
    if reason is not None:
        intent_category = intent_category or reason
        failure_reason_code = failure_reason_code or reason
    intent_category = intent_category or "unknown"
    failure_reason_code = failure_reason_code or "no_route"
    emitted_at = emitted_at or datetime.fromtimestamp(0, tz=UTC)
    normalized = " ".join(question.split()).casefold()
    selector_digest = hashlib.sha256(normalized.encode()).hexdigest()
    normalized_selector = f"sha256:{selector_digest}"
    problem_fingerprint = hashlib.sha256(
        "|".join(
            (
                intent_category,
                resource_type,
                normalized_selector,
                primary_agent,
                failure_reason_code,
            )
        ).encode("utf-8")
    ).hexdigest()
    escalation_id = hashlib.sha256(
        f"{session_id}\0{turn_index}\0{problem_fingerprint}".encode()
    ).hexdigest()
    return {
        "producer_principal": "Bragi",
        "id": f"handoff-{escalation_id[:32]}",
        "escalation_id": f"handoff-{escalation_id[:32]}",
        "correlation_id": f"handoff-{escalation_id[:32]}",
        "idempotency_key": f"handoff:{escalation_id}",
        "emitting_agent": primary_agent,
        "primary_agent": primary_agent,
        "intent_category": intent_category,
        "resource_type": resource_type,
        "normalized_selector": normalized_selector,
        "failure_reason_code": failure_reason_code,
        "problem_fingerprint": problem_fingerprint,
        "emitted_at": emitted_at.isoformat(),
    }


class BragiPublicationMixin:
    """Typed publication methods shared by Bragi's operator and A2A paths."""

    def _publication_now(self) -> datetime:
        clock = getattr(self, "_clock", None)
        if callable(clock):
            value = clock()
            if isinstance(value, datetime):
                return value
        raise RuntimeError("Bragi publication outbox requires an injected clock")

    async def _publish_conversation(
        self, session: ConversationSession, *, status: str = "active"
    ) -> bool:
        bus = getattr(self, "bus", None)
        if bus is None:
            return False
        await bus.publish(
            "Bragi", "object.conversation", conversation_event_payload(session, status=status)
        )
        return True

    async def _publish_a2a_turn(
        self,
        *,
        requester: str,
        target_agent: str,
        question: str,
        response: dict[str, Any],
        turn_index: int,
    ) -> None:
        bus = getattr(self, "bus", None)
        if bus is None:
            return
        await bus.publish(
            "Bragi",
            "object.turn",
            a2a_turn_event_payload(
                requester=requester,
                target_agent=target_agent,
                question=question,
                response=response,
                turn_index=turn_index,
            ),
        )

    async def publish_user_preference(self, preference: UserPreferenceRecord) -> bool:
        bus = getattr(self, "bus", None)
        if bus is None:
            return False
        await bus.publish(
            "Bragi",
            "object.user-preference",
            user_preference_event_payload(preference),
        )
        return True

    async def publish_post_turn_review(
        self,
        review: PostTurnReviewInput,
        *,
        preference: UserPreferenceRecord | None = None,
    ) -> bool:
        payload = post_turn_review_event_payload(review, preference=preference)
        return await self._publish_with_outbox("Bragi", "object.post-turn-review", payload)

    async def publish_handoff_event(self, payload: dict[str, Any]) -> bool:
        return await self._publish_with_outbox("Bragi", "object.handoff-escalation", payload)

    async def _publish_with_outbox(
        self, principal: str, topic: str, payload: dict[str, Any]
    ) -> bool:
        bus = getattr(self, "bus", None)
        state_store = getattr(self, "_state_store", None)
        if state_store is not None:
            await _checkpoint_publication(state_store, topic=topic, payload=payload)
        if bus is None:
            return False
        if state_store is None:
            await await_bounded_publication(
                bus.publish(principal, topic, payload),
                lease=_BRAGI_PUBLICATION_CLAIM_LEASE,
            )
            return True
        claim = await _claim_publication(state_store, payload, now=self._publication_now())
        if claim is None:
            return True
        await publish_claimed_outbox(
            claim,
            publish=lambda: bus.publish(principal, topic, payload),
            mark_published=lambda active_claim: _mark_publication_published(
                state_store, payload, active_claim
            ),
            release=lambda active_claim: _reset_publication_pending(
                state_store, payload, active_claim
            ),
            lease=_BRAGI_PUBLICATION_CLAIM_LEASE,
        )
        return True

    async def recover_bragi_publications(
        self, *, limit: int = _BRAGI_PUBLICATION_OUTBOX_SCAN_LIMIT
    ) -> int:
        """Publish pending or lease-expired rows, deferring each failed or malformed row."""

        bus = getattr(self, "bus", None)
        state_store = getattr(self, "_state_store", None)
        if bus is None or state_store is None:
            return 0
        record = getattr(self, "record_behavior", None)
        published = 0
        attempted = 0
        attempted_keys: set[str] = set()
        while attempted < limit:
            remaining = limit - attempted
            pending_rows, _pending_total = await state_store.read_state_page(
                _BRAGI_PUBLICATION_OUTBOX_PREFIX,
                limit=remaining,
                field="status",
                value="pending",
            )
            publishing_rows, _publishing_total = await state_store.read_state_page(
                _BRAGI_PUBLICATION_OUTBOX_PREFIX,
                limit=remaining,
                field="status",
                value="publishing",
            )
            rows = (*pending_rows, *publishing_rows)
            if not rows:
                break
            progress = 0
            for row in reversed(rows[:remaining]):
                topic = str(row.get("topic") or "")
                payload = row.get("payload")
                row_key = _recovery_row_key(row, payload)
                if row_key in attempted_keys:
                    continue
                attempted_keys.add(row_key)
                attempted += 1
                if topic not in {
                    "object.handoff-escalation",
                    "object.post-turn-review",
                } or not isinstance(payload, Mapping):
                    if callable(record):
                        record("publication_outbox:recovery_invalid_row")
                    continue
                try:
                    if await _publish_recovered_row(
                        state_store,
                        bus,
                        topic=topic,
                        payload=dict(payload),
                        now=self._publication_now(),
                    ):
                        published += 1
                        progress += 1
                except Exception:
                    if callable(record):
                        record("publication_outbox:recovery_publish_failed")
                    continue
            if progress == 0:
                break
        return published


async def _publish_recovered_row(
    state_store: Any,
    bus: Any,
    *,
    topic: str,
    payload: dict[str, Any],
    now: datetime,
) -> bool:
    claim = await _claim_publication(state_store, payload, now=now)
    return await publish_claimed_outbox(
        claim,
        publish=lambda: bus.publish("Bragi", topic, payload),
        mark_published=lambda active_claim: _mark_publication_published(
            state_store, payload, active_claim
        ),
        release=lambda active_claim: _reset_publication_pending(state_store, payload, active_claim),
        lease=_BRAGI_PUBLICATION_CLAIM_LEASE,
    )


def _recovery_row_key(row: Mapping[str, Any], payload: object) -> str:
    if isinstance(payload, Mapping):
        correlation_id = str(payload.get("correlation_id") or "")
        idempotency_key = str(payload.get("idempotency_key") or "")
        if correlation_id and idempotency_key:
            return _publication_key(payload)
    return (
        "invalid:"
        + hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
    )


def _publication_key(payload: Mapping[str, Any]) -> str:
    correlation_id = str(payload.get("correlation_id") or "")
    idempotency_key = str(payload.get("idempotency_key") or "")
    if not correlation_id or not idempotency_key:
        raise RuntimeError("Bragi publication payload requires correlation_id and idempotency_key")
    digest = hashlib.sha256(f"{correlation_id}\0{idempotency_key}".encode()).hexdigest()
    return f"{_BRAGI_PUBLICATION_OUTBOX_PREFIX}{digest}"


async def _checkpoint_publication(
    state_store: Any,
    *,
    topic: str,
    payload: Mapping[str, Any],
) -> None:
    key = _publication_key(payload)
    record = {
        "schema_version": "1.0.0",
        "revision": 1,
        "status": "pending",
        "topic": topic,
        "correlation_id": str(payload.get("correlation_id") or ""),
        "idempotency_key": str(payload.get("idempotency_key") or ""),
        "payload": dict(payload),
    }
    created = await state_store.write_state_if_absent(key, record)
    if created:
        return
    stored = await state_store.read_state(key)
    if not isinstance(stored, Mapping):
        raise RuntimeError("Bragi publication outbox row disappeared")
    if stored.get("status") == "published":
        return
    if stored.get("payload") != record["payload"]:
        raise RuntimeError("Bragi publication outbox idempotency collision")


async def _claim_publication(
    state_store: Any, payload: Mapping[str, Any], *, now: datetime
) -> PublicationClaim | None:
    key = _publication_key(payload)
    for _attempt in range(16):
        stored = await state_store.read_state(key)
        if stored is None:
            raise RuntimeError("Bragi publication outbox row disappeared")
        if stored.get("status") == "published":
            return None
        if stored.get("status") == "publishing" and not _publication_claim_expired(stored, now):
            return None
        revision = int(stored.get("revision", 1))
        claimed_at = now.isoformat()
        claim_owner = new_publication_claim_owner("Bragi")
        if await state_store.compare_and_set_state(
            key,
            {
                **dict(stored),
                "status": "publishing",
                "revision": revision + 1,
                "claim_owner": claim_owner,
                "claimed_at": claimed_at,
            },
            expected_revision=revision,
        ):
            return PublicationClaim(owner=claim_owner, claimed_at=claimed_at)
    raise RuntimeError("Bragi publication claim CAS retry limit exceeded")


async def _mark_publication_published(
    state_store: Any, payload: Mapping[str, Any], claim: PublicationClaim
) -> bool:
    key = _publication_key(payload)
    for _attempt in range(16):
        stored = await state_store.read_state(key)
        if stored is None or stored.get("status") == "published":
            return False
        if not claim_matches(stored, claim):
            return False
        revision = int(stored.get("revision", 1))
        if await state_store.compare_and_set_state(
            key,
            {
                "schema_version": "1.0.0",
                "revision": revision + 1,
                "status": "published",
                "topic": str(stored.get("topic") or ""),
                "correlation_id": str(stored.get("correlation_id") or ""),
                "idempotency_key": str(stored.get("idempotency_key") or ""),
                "payload": dict(stored.get("payload") or {}),
            },
            expected_revision=revision,
        ):
            await state_store.delete_states_beyond(
                _BRAGI_PUBLICATION_OUTBOX_PREFIX,
                retain_newest=(
                    _BRAGI_PUBLICATION_OUTBOX_SCAN_LIMIT + _BRAGI_PUBLICATION_TOMBSTONE_RETENTION
                ),
            )
            return True
    raise RuntimeError("Bragi publication mark CAS retry limit exceeded")


async def _reset_publication_pending(
    state_store: Any, payload: Mapping[str, Any], claim: PublicationClaim
) -> None:
    key = _publication_key(payload)
    for _attempt in range(16):
        stored = await state_store.read_state(key)
        if stored is None or stored.get("status") != "publishing":
            return
        if not claim_matches(stored, claim):
            return
        revision = int(stored.get("revision", 1))
        if await state_store.compare_and_set_state(
            key,
            {
                **dict(stored),
                "status": "pending",
                "revision": revision + 1,
                "claim_owner": "",
                "claimed_at": "",
            },
            expected_revision=revision,
        ):
            return
    raise RuntimeError("Bragi publication reset CAS retry limit exceeded")


def _publication_claim_expired(row: Mapping[str, Any], now: datetime) -> bool:
    return claim_expired(
        claimed_at=row.get("claimed_at"),
        now=now,
        lease=_BRAGI_PUBLICATION_CLAIM_LEASE,
    )
