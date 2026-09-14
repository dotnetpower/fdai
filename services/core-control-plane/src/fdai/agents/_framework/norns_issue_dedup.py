"""Idempotent issue-learning claims for Norns."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.norns_learning import (
    NornsLearningState,
    observe_fingerprint,
)
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "pantheon/norns/issue-learning"


class NornsIssueDeduplicator:
    """Claim each Saga issue operation before it can change learning evidence."""

    def __init__(self, state_store: StateStore | None, local_capacity: int) -> None:
        self._state_store = state_store
        self._local_claims: BoundedLruDict[str, str] = BoundedLruDict(local_capacity)

    async def observe(
        self,
        state: NornsLearningState,
        payload: Mapping[str, Any],
    ) -> None:
        """Count a fingerprint only after its operation claim succeeds."""
        if await self.claim(payload):
            observe_fingerprint(state, payload)
        else:
            state.record_behavior("issue_learning_duplicate")

    async def claim(self, payload: Mapping[str, Any]) -> bool:
        """Return true once per operation, rejecting identity collisions."""
        operation_id = payload.get("idempotency_key")
        fingerprint = payload.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            return False
        if (
            not isinstance(operation_id, str)
            or not operation_id
            or operation_id != operation_id.strip()
        ):
            if self._state_store is not None:
                raise ValueError("durable Norns issue learning requires a stable idempotency_key")
            return True

        prior_fingerprint = self._local_claims.get(operation_id)
        if prior_fingerprint is not None:
            if prior_fingerprint != fingerprint:
                raise ValueError("issue learning operation collides with a fingerprint")
            return False

        claim = {
            "schema_version": "1.0.0",
            "operation_id": operation_id,
            "fingerprint": fingerprint,
        }
        if self._state_store is not None:
            digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
            key = f"{_STATE_PREFIX}/{digest}"
            created = await self._state_store.write_state_with_audit_if_absent(
                key,
                claim,
                {
                    "actor": "Norns",
                    "action_kind": "issue_learning.claimed",
                    "operation_id_digest": f"sha256:{digest}",
                    "fingerprint": fingerprint,
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                },
            )
            if not created:
                stored = await self._state_store.read_state(key)
                if stored is None:
                    raise RuntimeError("issue learning claim disappeared after collision")
                if dict(stored) != claim:
                    raise ValueError("issue learning operation collides with different content")
                self._local_claims.set(operation_id, fingerprint)
                return False
        self._local_claims.set(operation_id, fingerprint)
        return True


__all__ = ["NornsIssueDeduplicator"]
