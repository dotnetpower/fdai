"""Durable Mimir governance projections outside the catalog journal."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict
from fdai.shared.providers.state_store import StateStore

_GOVERNANCE_PREFIX = "pantheon/mimir/governance/catalog-review"
_INVESTIGATION_PREFIX = f"{_GOVERNANCE_PREFIX}/investigation-candidates"
_QUARANTINE_PREFIX = f"{_GOVERNANCE_PREFIX}/quarantine"
_QUARANTINE_RETAIN = 5_000


class CatalogReviewCapacityError(RuntimeError):
    """Review work is saturated; transport must retry or dead-letter."""


class CatalogReviewPublicationError(RuntimeError):
    """The idempotent review publisher failed and durable work remains pending."""


class MimirCatalogGovernanceStore:
    """Persist candidate identity fences and quarantine terminal records."""

    def __init__(self, store: StateStore | None) -> None:
        self._store = store

    def bind(self, store: StateStore) -> None:
        if self._store is store:
            return
        if self._store is not None:
            raise RuntimeError("Mimir catalog review governance state store is already bound")
        self._store = store

    async def recover(
        self,
        *,
        investigation_candidates: BoundedLruDict[str, str],
        quarantined_candidates: deque[dict[str, Any]],
        max_pending_candidates: int,
        max_quarantine: int,
    ) -> int:
        store = self._store
        if store is None:
            return 0
        restored = 0
        rows = await store.read_states(
            f"{_INVESTIGATION_PREFIX}/",
            limit=max_pending_candidates,
        )
        for row in rows:
            key = str(row.get("idempotency_key") or "")
            digest = str(row.get("candidate_digest") or "")
            if not key or not digest:
                raise ValueError("Mimir durable investigation candidate fence is invalid")
            investigation_candidates.set(key, digest)
            restored += 1
        quarantine_rows = await store.read_states(f"{_QUARANTINE_PREFIX}/", limit=max_quarantine)
        for row in quarantine_rows:
            reason = str(row.get("reason") or "")
            summary = row.get("summary")
            if not isinstance(summary, Mapping) or not reason:
                raise ValueError("Mimir durable quarantine record is invalid")
            quarantined_candidates.append({**dict(summary), "quarantine_reason": reason})
            restored += 1
        return restored

    async def investigation_candidate(self, idempotency_key: str) -> str | None:
        store = self._store
        if store is None:
            return None
        row = await store.read_state(f"{_INVESTIGATION_PREFIX}/{idempotency_key}")
        if row is None:
            return None
        digest = row.get("candidate_digest")
        if not isinstance(digest, str) or not digest:
            raise ValueError("Mimir durable investigation candidate fence is invalid")
        return digest

    async def persist_investigation_candidate(
        self,
        idempotency_key: str,
        candidate_digest: str,
    ) -> None:
        store = self._store
        if store is None:
            return
        key = f"{_INVESTIGATION_PREFIX}/{idempotency_key}"
        value = {
            "kind": "mimir_investigation_candidate_fence",
            "revision": 1,
            "idempotency_key": idempotency_key,
            "candidate_digest": candidate_digest,
        }
        await store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "kind": "mimir_investigation_candidate_fenced",
                "principal": "Mimir",
                "idempotency_key": idempotency_key,
                "candidate_digest": candidate_digest,
                "grants_authority": False,
            },
        )

    async def quarantine(self, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        store = self._store
        if store is None:
            return None
        row = await store.read_state(
            f"{_QUARANTINE_PREFIX}/{catalog_candidate_idempotency_key(payload)}"
        )
        if row is None:
            return None
        stored = row.get("summary")
        reason = row.get("reason")
        if not isinstance(stored, Mapping) or not isinstance(reason, str) or not reason:
            raise ValueError("Mimir durable quarantine record is invalid")
        return {**dict(stored), "quarantine_reason": reason}

    async def persist_quarantine(self, payload: Mapping[str, Any], reason: str) -> None:
        store = self._store
        if store is None:
            return
        idempotency_key = catalog_candidate_idempotency_key(payload)
        await store.write_state_with_audit_if_absent(
            f"{_QUARANTINE_PREFIX}/{idempotency_key}",
            {
                "kind": "mimir_catalog_candidate_quarantine",
                "revision": 1,
                "idempotency_key": idempotency_key,
                "reason": reason,
                "summary": quarantine_summary(payload),
            },
            {
                "kind": "mimir_catalog_candidate_quarantined",
                "principal": "Mimir",
                "idempotency_key": idempotency_key,
                "reason": reason,
                "grants_authority": False,
            },
        )
        await store.delete_states_beyond(_QUARANTINE_PREFIX + "/", retain_newest=_QUARANTINE_RETAIN)


def catalog_candidate_idempotency_key(payload: Mapping[str, Any]) -> str:
    value = payload.get("idempotency_key")
    if not isinstance(value, str) or not value:
        raise ValueError("catalog review candidate requires an idempotency_key")
    return value


def quarantine_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    material = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    return {
        "idempotency_key": catalog_candidate_idempotency_key(payload),
        "candidate_digest": hashlib.sha256(material.encode()).hexdigest(),
        "producer_principal": str(payload.get("producer_principal") or ""),
        "source_signal": str(payload.get("source_signal") or ""),
        "target_rule_id": str(payload.get("target_rule_id") or ""),
        "correlation_id": str(payload.get("correlation_id") or ""),
    }


__all__ = [
    "CatalogReviewCapacityError",
    "CatalogReviewPublicationError",
    "MimirCatalogGovernanceStore",
    "catalog_candidate_idempotency_key",
    "quarantine_summary",
]
