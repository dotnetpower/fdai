"""Durable StateStore adapter for inert semantic feedback candidates."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.rule_catalog.schema.rule_semantic_feedback import (
    RetrievalFailureLayer,
    SemanticFeedbackCandidate,
)
from fdai.shared.providers.state_store import StateStore

_PREFIX = "rule-semantic-feedback"


def _default_clock() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class StateStoreSemanticFeedbackCandidateStore:
    """Persist challenger-only candidates with one atomic shadow audit row."""

    store: StateStore
    clock: Callable[[], datetime] = _default_clock

    async def put(self, candidate: SemanticFeedbackCandidate) -> bool:
        """Create one candidate or verify an identical idempotent replay."""

        recorded_at = self.clock()
        if recorded_at.tzinfo is None:
            raise ValueError("semantic feedback clock MUST be timezone-aware")
        key = _key(candidate.candidate_id)
        payload = _serialize(candidate)
        created = await self.store.write_state_with_audit_if_absent(
            key,
            payload,
            {
                "actor": "Norns",
                "producer_principal": "Norns",
                "action_kind": "catalog.semantic_feedback_candidate.recorded",
                "mode": "shadow",
                "candidate_id": candidate.candidate_id,
                "attempt_id": candidate.attempt_id,
                "query_digest": candidate.query_digest,
                "target_rule_ref": candidate.target_rule_ref,
                "failure_layer": candidate.failure_layer.value,
                "promotion_applied": False,
                "recorded_at": recorded_at.isoformat(),
            },
        )
        if created:
            return True
        current = await self.store.read_state(key)
        if current is None or dict(current) != payload:
            raise ValueError("semantic feedback candidate idempotency conflict")
        return False

    async def get(self, candidate_id: str) -> SemanticFeedbackCandidate | None:
        raw = await self.store.read_state(_key(candidate_id))
        return _deserialize(raw) if raw is not None else None

    async def list(self, *, limit: int = 100) -> tuple[SemanticFeedbackCandidate, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("semantic feedback list limit MUST be in [1, 1000]")
        rows = await self.store.read_states(f"{_PREFIX}:", limit=limit)
        return tuple(_deserialize(row) for row in rows)


def _key(candidate_id: str) -> str:
    if not candidate_id:
        raise ValueError("semantic feedback candidate id MUST be non-empty")
    return f"{_PREFIX}:{hashlib.sha256(candidate_id.encode()).hexdigest()}"


def _serialize(candidate: SemanticFeedbackCandidate) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "candidate_id": candidate.candidate_id,
        "attempt_id": candidate.attempt_id,
        "query_digest": candidate.query_digest,
        "target_rule_ref": candidate.target_rule_ref,
        "failure_layer": candidate.failure_layer.value,
        "evidence_refs": list(candidate.evidence_refs),
        "mode": candidate.mode,
        "promotion_authority": candidate.promotion_authority,
        "revision": 1,
    }


def _deserialize(raw: Mapping[str, Any]) -> SemanticFeedbackCandidate:
    if raw.get("schema_version") != "1.0.0" or raw.get("revision") != 1:
        raise ValueError("semantic feedback candidate schema is unsupported")
    evidence_refs = raw.get("evidence_refs")
    if not isinstance(evidence_refs, list) or any(
        not isinstance(item, str) for item in evidence_refs
    ):
        raise ValueError("semantic feedback candidate evidence_refs are invalid")
    return SemanticFeedbackCandidate(
        candidate_id=_text(raw, "candidate_id"),
        attempt_id=_text(raw, "attempt_id"),
        query_digest=_text(raw, "query_digest"),
        target_rule_ref=_text(raw, "target_rule_ref"),
        failure_layer=RetrievalFailureLayer(_text(raw, "failure_layer")),
        evidence_refs=tuple(evidence_refs),
        mode=_text(raw, "mode"),
        promotion_authority=raw.get("promotion_authority") is True,
    )


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"semantic feedback candidate {key} is invalid")
    return value


__all__ = ["StateStoreSemanticFeedbackCandidateStore"]
