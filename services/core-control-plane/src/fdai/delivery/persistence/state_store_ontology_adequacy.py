"""Durable StateStore sink for held ontology adequacy reviews."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.conversation_assurance import OntologyAdequacyReview
from fdai.shared.providers.state_store import StateStore

_PREFIX = "ontology-adequacy-review"


@dataclass(frozen=True, slots=True)
class StateStoreOntologyAdequacyReviewSink:
    store: StateStore

    async def submit(self, review: OntologyAdequacyReview) -> None:
        key = f"{_PREFIX}:{hashlib.sha256(review.review_id.encode()).hexdigest()}"
        payload = {
            "review_id": review.review_id,
            "attribution_id": review.attribution_id,
            "state": review.state.value,
            "candidate_kind": (
                review.candidate_kind.value if review.candidate_kind is not None else None
            ),
            "competency_question_digest": review.competency_question_digest,
            "ontology_release": review.ontology_release,
            "graph_revision": review.graph_revision,
            "evidence_refs": list(review.evidence_refs),
            "reason_codes": list(review.reason_codes),
            "revision": 1,
        }
        created = await self.store.write_state_with_audit_if_absent(
            key,
            payload,
            {
                "actor": "Muninn",
                "producer_principal": "Muninn",
                "action_kind": "ontology.adequacy_review.recorded",
                "mode": "shadow",
                "review_id": review.review_id,
                "attribution_id": review.attribution_id,
                "state": review.state.value,
                "candidate_kind": payload["candidate_kind"],
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        if created:
            return
        current = await self.store.read_state(key)
        if current is None or dict(current) != payload:
            raise ValueError("ontology adequacy review idempotency conflict")


__all__ = ["StateStoreOntologyAdequacyReviewSink"]
